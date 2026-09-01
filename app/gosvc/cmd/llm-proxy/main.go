// llm-proxy — 명세 19-4. Go 가 호출하는 LLM 은 Ollama 뿐이다.
//
//	G-L1  POST /svc/v1/llm/report-narrative   리포트 서술 (SSE) → I-4 콜백
//	G-L3  GET  /svc/v1/llm/models             Ollama 상주 모델
//	      GET  /svc/v1/llm/health
//
// 지켜야 하는 것 (명세 19장)
//
//	· Go 는 Django 가 서명한 티켓만 검증한다. 자체 권한 판정 없음
//	· Go 는 Postgres 에 직접 쓰지 않는다. 결과는 I-4 콜백으로만
//	· 근거 좌표 없는 문장은 버리고 dropped_sentence_log 로 되돌린다
//	· Ollama 가 죽어도 리포트는 발급된다 → 503 UPSTREAM_LLM_UNAVAILABLE
//
// 환경변수
//
//	LLM_ADDR            :8090
//	OLLAMA_BASE         http://127.0.0.1:11434
//	OLLAMA_MODEL        medgemma
//	TICKET_KEY          Django 와 공유하는 티켓 서명 키   (필수)
//	CALLBACK_BASE       https://django-internal          (필수)
//	CALLBACK_SECRET     I-4 X-Signature 키               (필수)
//	CALLBACK_CERT/KEY   mTLS 인증서 (운영 필수)
package main

import (
	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/narrative"
	"cdss/gosvc/internal/ollama"
	"cdss/gosvc/internal/ticket"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

const (
	purposeNarrative = "report_narrative"
	purposeChat      = "chat"
)

// 대화 상한. 없으면 앞선 대화가 계속 쌓여 컨텍스트 창을 넘기고,
// 그러면 Ollama 가 **앞쪽을 조용히 잘라낸다** — 근거 목록이 먼저 잘린다.
const (
	maxTurns    = 24
	maxCharsMsg = 4000
)

type server struct {
	oll *ollama.Client
	cb  *callback.Client
	tv  *ticket.Verifier
}

// Evidence 는 Django 가 넘겨주는 근거 하나다. id 는 문장이 인용할 이름표다.
type Evidence struct {
	ID   string `json:"id"`   // "L1" 등. 문장이 [[e:L1]] 로 가리킨다
	Kind string `json:"kind"` // lesion · measurement · pathology ...
	Text string `json:"text"` // 모델에게 보여줄 사실 한 줄
}

type narrativeReq struct {
	ReportID string     `json:"report_id"`
	Locale   string     `json:"locale"`   // ko 기본
	Evidence []Evidence `json:"evidence"` // 비면 400 — 근거 없이 서술만 받지 않는다
	Extra    string     `json:"extra_instruction,omitempty"`
}

func main() {
	addr := env("LLM_ADDR", ":8090")
	tkey := os.Getenv("TICKET_KEY")
	cbBase := os.Getenv("CALLBACK_BASE")
	cbSec := os.Getenv("CALLBACK_SECRET")
	if tkey == "" || cbBase == "" || cbSec == "" {
		log.Fatal("TICKET_KEY · CALLBACK_BASE · CALLBACK_SECRET 이 필요하다")
	}
	s := &server{
		oll: ollama.New(env("OLLAMA_BASE", "http://127.0.0.1:11434"),
			env("OLLAMA_MODEL", "medgemma"), 10*time.Minute),
		cb: callback.New(cbBase, []byte(cbSec),
			os.Getenv("CALLBACK_CERT"), os.Getenv("CALLBACK_KEY"), 4),
		tv: ticket.NewVerifier([]byte(tkey)),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /svc/v1/llm/report-narrative", s.reportNarrative)
	mux.HandleFunc("POST /svc/v1/llm/chat", s.chat)
	mux.HandleFunc("GET /svc/v1/llm/models", s.models)
	mux.HandleFunc("GET /svc/v1/llm/health", s.health)

	log.Printf("llm-proxy %s · ollama %s · model %s", addr, s.oll.Base, s.oll.Model)
	srv := &http.Server{
		Addr:    addr,
		Handler: mux,
		// 스트리밍이라 쓰기 타임아웃을 걸면 긴 서술이 중간에 끊긴다.
		ReadHeaderTimeout: 10 * time.Second,
	}
	log.Fatal(srv.ListenAndServe())
}

// ── G-L1 ────────────────────────────────────────────────────────────
func (s *server) reportNarrative(w http.ResponseWriter, r *http.Request) {
	var req narrativeReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).
		Decode(&req); err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다: "+err.Error())
		return
	}
	// ① 티켓 — 권한 판정이 아니라 검증만
	cl, err := s.tv.Verify(bearer(r))
	if err != nil {
		code, status := 401, "TICKET_EXPIRED"
		switch {
		case errors.Is(err, ticket.ErrScope):
			code, status = 403, "TICKET_SCOPE_MISMATCH"
		case errors.Is(err, ticket.ErrReplayed):
			status = "TICKET_REPLAYED"
		case errors.Is(err, ticket.ErrSignature), errors.Is(err, ticket.ErrMalformed):
			status = "TICKET_INVALID"
		}
		fail(w, code, status, err.Error())
		return
	}
	if err := cl.RequireScope(purposeNarrative, req.ReportID); err != nil {
		fail(w, 403, "TICKET_SCOPE_MISMATCH",
			"티켓이 가리키는 리포트와 요청이 다르다")
		return
	}
	// ② 근거가 없으면 시작하지 않는다.
	//    근거 없는 문장은 어차피 전부 버려지므로 빈 결과를 만들 뿐이고,
	//    GPU 시간만 쓴다.
	if len(req.Evidence) == 0 {
		fail(w, 400, "NO_EVIDENCE",
			"evidence 가 비었다. 근거 없는 서술은 명세상 전부 버려진다")
		return
	}

	allowed := make([]string, 0, len(req.Evidence))
	for _, e := range req.Evidence {
		allowed = append(allowed, e.ID)
	}

	// ③ 스트리밍 준비
	fl, canStream := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no") // nginx 버퍼링 방지
	w.WriteHeader(http.StatusOK)

	// ⚠ 생성은 요청 컨텍스트에 묶지 않는다.
	//   화면이 중간에 닫혀도 서술을 끝까지 받아 I-4 로 저장해야 한다.
	//   r.Context() 를 쓰면 브라우저가 닫히는 순간 취소되고, 그때까지 쓴
	//   GPU 시간이 통째로 버려진다.
	genCtx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()

	raw, gerr := s.oll.Chat(genCtx, buildPrompt(req), func(chunk string) error {
		select {
		case <-r.Context().Done():
			return errors.New("client gone") // 흘려보내기만 멈춘다
		default:
		}
		if _, err := fmt.Fprintf(w, "event: token\ndata: %s\n\n",
			jsonStr(chunk)); err != nil {
			return err
		}
		if canStream {
			fl.Flush()
		}
		return nil
	})

	if gerr != nil {
		// 명세 — Ollama 가 죽어도 리포트는 content_json 만으로 발급된다.
		// 여기서 에러를 올려도 리포트 발급 자체는 막히지 않는다.
		log.Printf("[G-L1] report=%s ollama 실패: %v", req.ReportID, gerr)
		sse(w, fl, "error", map[string]any{
			"code": "UPSTREAM_LLM_UNAVAILABLE", "detail": gerr.Error(),
			"note": "리포트는 content_json 만으로 발급된다 (narrative_text=null)",
		})
		return
	}

	// ④ 근거 없는 문장 버리기
	res := narrative.Filter(raw, allowed)
	drops := make([]callback.Drop, 0, len(res.Dropped))
	for _, d := range res.Dropped {
		drops = append(drops, callback.Drop{Sentence: d.Sentence, Reason: d.Reason})
	}
	log.Printf("[G-L1] report=%s 문장 유지 %d자 · 버림 %d건 · 근거 %d개",
		req.ReportID, len([]rune(res.Text)), len(drops), len(res.Evidence))

	// ⑤ I-4 — 여기가 '데이터 전송' 이다. Go 는 DB 에 직접 안 쓴다.
	//    멱등키는 리포트당 고정이라 재시도가 중복 행을 안 만든다.
	//    nonce 를 섞지 않는 이유가 그것이다 — 매번 달라지면 멱등성이 없다.
	cbCtx, cbCancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cbCancel()
	cerr := s.cb.PostNarrative(cbCtx, req.ReportID, "narrative:"+req.ReportID,
		callback.Narrative{
			NarrativeText:      res.Text,
			EvidenceLinks:      res.Evidence,
			DroppedSentenceLog: drops,
		})
	if cerr != nil {
		sse(w, fl, "error", map[string]any{
			"code": "CALLBACK_FAILED", "detail": cerr.Error(),
			"note": "서술은 만들었으나 Django 에 저장하지 못했다",
		})
		return
	}
	sse(w, fl, "done", map[string]any{
		"report_id": req.ReportID,
		"chars":     len([]rune(res.Text)),
		"evidence":  res.Evidence,
		"dropped":   len(drops),
		"patient":   cl.PatientID,
	})
}

// buildPrompt — 근거를 목록으로 주고, 문장마다 인용을 강제한다.
func buildPrompt(req narrativeReq) []ollama.Message {
	var b strings.Builder
	b.WriteString("다음 근거만 사용해 유방 영상 판독 리포트의 서술 부분을 쓴다.\n\n")
	for _, e := range req.Evidence {
		fmt.Fprintf(&b, "[%s] (%s) %s\n", e.ID, e.Kind, e.Text)
	}
	b.WriteString(`
규칙
- 문장마다 끝에 근거 표시를 붙인다. 예: [[e:L1]]
- 위 목록에 없는 사실을 쓰지 않는다. 근거가 없으면 그 문장을 쓰지 않는다.
- 진단을 단정하지 않는다. 판독 보조 서술이다.
- 한국어. 구어체를 쓰지 않는다.
`)
	if req.Extra != "" {
		b.WriteString("\n" + req.Extra + "\n")
	}
	return []ollama.Message{
		{Role: "system", Content: "너는 유방영상 판독을 돕는 서술 보조다. " +
			"주어진 근거 밖의 내용을 만들지 않는다."},
		{Role: "user", Content: b.String()},
	}
}

// ── G-L2  챗봇 ──────────────────────────────────────────────────────
//
// G-L1 과 다른 점 하나가 설계 전체를 가른다.
//
//	G-L1 은 **리포트에 저장되는 글**이다. 그래서 근거 없는 문장을 버리고
//	I-4 로 DB 에 남긴다.
//	G-L2 는 **화면에서 한 번 읽고 마는 대화**다. 여기에 같은 문장 필터를
//	걸면 "그건 무슨 뜻인가요" 같은 질문에 아무 답도 못 한다 — 설명 문장은
//	근거 표시를 달 자리가 없기 때문이다.
//
// 그래서 G-L2 는
//
//	· 문장을 버리지 않는다
//	· **DB 에 안 남긴다** (콜백 없음). 대화는 진료 기록이 아니다
//	· 대신 근거를 컨텍스트로 넣고, 근거 밖 임상 사실을 단정하지 말라고 못 박는다
//	· 응답에 면책을 함께 내려보내 화면이 그대로 띄우게 한다
//
// ⚠ 팀과 맞출 것 — 대화를 진료 기록으로 남길지 여부. 남기기로 하면
//
//	명세 21장에 I-6 이 하나 더 필요하고, 그때는 문장 필터도 다시 봐야 한다.
type chatReq struct {
	SessionID string           `json:"session_id"`
	Messages  []ollama.Message `json:"messages"`
	Context   []Evidence       `json:"context,omitempty"`
}

func (s *server) chat(w http.ResponseWriter, r *http.Request) {
	var req chatReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20)).
		Decode(&req); err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다: "+err.Error())
		return
	}
	cl := s.verify(w, r, purposeChat, req.SessionID)
	if cl == nil {
		return
	}
	msgs, err := chatMessages(req)
	if err != nil {
		fail(w, 400, "BAD_REQUEST", err.Error())
		return
	}

	fl, canStream := w.(http.Flusher)
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	// G-L1 과 반대로 **요청 컨텍스트에 묶는다.**
	// 저장할 것이 없으니 화면이 닫히면 계속 만들 이유가 없다. 그냥 GPU 낭비다.
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Minute)
	defer cancel()

	var n int
	_, gerr := s.oll.Chat(ctx, msgs, func(chunk string) error {
		n += len([]rune(chunk))
		if _, err := fmt.Fprintf(w, "event: token\ndata: %s\n\n",
			jsonStr(chunk)); err != nil {
			return err
		}
		if canStream {
			fl.Flush()
		}
		return nil
	})
	if gerr != nil {
		if errors.Is(gerr, context.Canceled) {
			return // 사용자가 창을 닫았다. 오류가 아니다
		}
		log.Printf("[G-L2] session=%s ollama 실패: %v", req.SessionID, gerr)
		sse(w, fl, "error", map[string]any{
			"code": "UPSTREAM_LLM_UNAVAILABLE", "detail": gerr.Error(),
		})
		return
	}
	log.Printf("[G-L2] session=%s %d자 · 근거 %d개", req.SessionID, n, len(req.Context))
	sse(w, fl, "done", map[string]any{
		"session_id": req.SessionID, "chars": n,
		"persisted":  false,
		"disclaimer": "판독 보조 설명이다. 진단이 아니며 진료 기록으로 저장되지 않는다.",
	})
}

// chatMessages — 대화를 상한 안으로 자르고 근거를 앞에 붙인다.
//
// **오래된 쪽부터 자른다.** 최근 대화가 문맥상 더 중요하고, 시스템 지시와
// 근거는 따로 앞에 다시 붙이므로 잘려도 잃지 않는다.
func chatMessages(req chatReq) ([]ollama.Message, error) {
	if len(req.Messages) == 0 {
		return nil, errors.New("messages 가 비었다")
	}
	if req.SessionID == "" {
		return nil, errors.New("session_id 가 없다")
	}
	turns := req.Messages
	if len(turns) > maxTurns {
		turns = turns[len(turns)-maxTurns:]
	}

	var sys strings.Builder
	sys.WriteString("너는 유방영상 판독 결과를 설명하는 보조다.\n" +
		"- 아래 근거 밖의 임상 사실을 새로 단정하지 않는다.\n" +
		"- 모르면 모른다고 말한다. 지어내지 않는다.\n" +
		"- 진단·치료를 지시하지 않는다. 판단은 의료진이 한다.\n" +
		"- 한국어. 구어체를 쓰지 않는다.\n")
	if len(req.Context) > 0 {
		sys.WriteString("\n[이 환자에 대해 확인된 근거]\n")
		for _, e := range req.Context {
			fmt.Fprintf(&sys, "- (%s) %s\n", e.Kind, e.Text)
		}
	}

	out := make([]ollama.Message, 0, len(turns)+1)
	out = append(out, ollama.Message{Role: "system", Content: sys.String()})
	for _, m := range turns {
		if m.Role != "user" && m.Role != "assistant" {
			return nil, fmt.Errorf("허용되지 않는 role: %q", m.Role)
		}
		c := []rune(m.Content)
		if len(c) > maxCharsMsg {
			c = c[:maxCharsMsg]
		}
		out = append(out, ollama.Message{Role: m.Role, Content: string(c)})
	}
	return out, nil
}

// verify — 티켓 검증. G-L1 과 G-L2 가 같은 판정을 쓰게 한다.
func (s *server) verify(w http.ResponseWriter, r *http.Request,
	purpose, scopeID string) *ticket.Claims {
	cl, err := s.tv.Verify(bearer(r))
	if err != nil {
		code, status := 401, "TICKET_EXPIRED"
		switch {
		case errors.Is(err, ticket.ErrScope):
			code, status = 403, "TICKET_SCOPE_MISMATCH"
		case errors.Is(err, ticket.ErrReplayed):
			status = "TICKET_REPLAYED"
		case errors.Is(err, ticket.ErrSignature), errors.Is(err, ticket.ErrMalformed):
			status = "TICKET_INVALID"
		}
		fail(w, code, status, err.Error())
		return nil
	}
	if err := cl.RequireScope(purpose, scopeID); err != nil {
		fail(w, 403, "TICKET_SCOPE_MISMATCH",
			"티켓이 가리키는 대상과 요청이 다르다")
		return nil
	}
	return cl
}

// ── G-L3 · health ───────────────────────────────────────────────────
func (s *server) models(w http.ResponseWriter, r *http.Request) {
	ms, err := s.oll.Models(r.Context())
	if err != nil {
		fail(w, 503, "UPSTREAM_LLM_UNAVAILABLE", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"model_in_use": s.oll.Model, "models": ms})
}

func (s *server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	_, err := s.oll.Models(ctx)
	writeJSON(w, 200, map[string]any{
		"ollama": err == nil, "model": s.oll.Model,
		"error": errStr(err),
	})
}

// ── 잡동사니 ────────────────────────────────────────────────────────
func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return r.Header.Get("X-Ticket")
}

func sse(w http.ResponseWriter, fl http.Flusher, event string, v any) {
	b, _ := json.Marshal(v)
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, b)
	if fl != nil {
		fl.Flush()
	}
}

func jsonStr(s string) string { b, _ := json.Marshal(s); return string(b) }

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, code int, status, detail string) {
	writeJSON(w, code, map[string]string{"code": status, "detail": detail})
}

func errStr(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}
