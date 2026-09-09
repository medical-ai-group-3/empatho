// llm-proxy — 명세 19-4. 판독 결과를 소견으로 바꿔 Django 에 넣는다.
//
//	G-L1  POST /svc/v1/llm/report-narrative   판독 결과 → 리포트 서버 → I-4
//	      GET  /svc/v1/llm/health             터널이 살아 있는지
//
// ── 2026-09-02 변경 ────────────────────────────────────────────────
//
// Ollama 직접 호출을 그만뒀다. 이제 워크스테이션 리포트 서버(:8002)를 부른다.
//
//	이전   Go 가 프롬프트를 만들고 → Ollama 를 흘려 받고 → Go 가 문장을 검사
//	지금   Go 가 판독 결과를 넘기고 → 리포트 서버가 전부 하고 → 결과만 받는다
//
// 왜 바꿨나
//
//	① 검사와 흘려보내기가 상충한다. "63.9px 가 그대로 있나" 도 "근거
//	   표시가 붙었나" 도 문장이 끝나야 판정된다. 검사에 걸리면 모델 출력을
//	   버리고 뼈대 문장으로 되돌리는데, 이미 흘려보낸 글자는 못 되돌린다.
//	   틀린 숫자를 잠깐 보여줬다 고치는 건 판독 화면에서 할 일이 아니다.
//	② 규칙(문구·프롬프트)이 한 곳에 모인다. 소켓마다 규칙이 다른데
//	   Go 가 들고 있으면 소켓이 늘 때마다 Go 를 고쳐야 한다.
//	③ 실측 1초 미만이라(모델 적재된 뒤) 기다릴 만하다.
//
// 무엇이 없어졌나
//
//	· 스트리밍(SSE) — 응답이 JSON 한 덩어리로 온다
//	· G-L2 대화 — 이번 범위에서 뺐다. 자유 질문에는 숫자 검사도 근거
//	  검사도 적용할 수 없어서, 지금 붙이면 검증 안 된 출력이 검증된
//	  소견과 같은 화면에 섞인다. 사용자는 그 차이를 모른다.
//	  나중에 붙일 때는 대화용 규칙을 따로 정하고 11434 터널이 필요해진다.
//
// internal/narrative(근거 검사)와 internal/ollama 는 **남겨 뒀다.**
// 되돌릴 일이 생기면 그게 있어야 하고, 같은 규칙이 두 곳에 적혀 있으면
// 리포트 서버 쪽 판정과 대조해 볼 수 있다. 지금은 아무도 안 부른다.
//
// 지켜야 하는 것 (명세 19장)
//
//	· Go 는 Django 가 서명한 티켓만 검증한다. 자체 권한 판정 없음
//	· Go 는 Postgres 에 직접 쓰지 않는다. 결과는 I-4 콜백으로만
//	· 리포트 서버가 죽어도 리포트는 발급된다 → 503, narrative_text=null
//
// 환경변수
//
//	LLM_ADDR            :8090
//	REPORT_BASE         http://tunnel:8002                  (필수)
//	REPORT_TIMEOUT      2m
//	TICKET_KEY          Django 와 공유하는 티켓 서명 키      (필수)
//	CALLBACK_BASE       http://web:8000                     (필수)
//	CALLBACK_SECRET     I-4 X-Signature 키                  (필수)
//	CALLBACK_CERT/KEY   mTLS 인증서 (운영 필수)
//	CORS_ORIGINS        허용할 프런트 출처. 쉼표로 여러 개
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/httpx"
	"cdss/gosvc/internal/report"
	"cdss/gosvc/internal/ticket"
)

const purposeNarrative = "report_narrative"

type server struct {
	rep *report.Client
	cb  *callback.Client
	tv  *ticket.Verifier
}

// Evidence — 근거 행 하나.
//
// ⚠ 이 행은 **리포트 서버로 안 간다.** 거기로는 ID 목록만 보낸다.
//
//	리포트 서버가 하는 근거 검사는 "모델이 인용한 ID 가 목록 안에 있나"
//	뿐이라 좌표를 볼 일이 없고, 프롬프트가 밀리미터 환산을 금지하고 있어
//	화소 간격도 쓸 데가 없다. 행은 우리가 들고 있다가 응답과 합친다.
//
// PixelSpacingMM 이 왜 행마다 있나
//
//	장비마다 다르다. 우리 데이터 443장을 실측하니 0.0814 · 0.0828 · 0.083 ·
//	0.085 로 갈렸고, 폭이 4% 다. 상수로 박으면 밀리미터 환산이 그만큼
//	조용히 어긋난다. 미세석회는 그 크기로 판정이 갈리는 병변이다.
//
//	모르는 경우에는 null 이어야 한다. 0 이나 임의 상수로 채우면 화면이
//	그럴듯한 밀리미터를 보여주는데 그게 틀린 값이다.
type Evidence struct {
	ID    string  `json:"id"`              // "MG-01". 문장이 이걸 인용한다
	Kind  string  `json:"kind,omitempty"`  // lesion · measurement · pathology
	Image *Image  `json:"image,omitempty"` // 맘모는 좌우·촬영방향이 붙는다
	Box   []int   `json:"box,omitempty"`   // [x1,y1,x2,y2]
	Poly  [][]int `json:"polygon,omitempty"`
	Frame string  `json:"frame,omitempty"` // "pixel"

	// PixelSpacingMM — 포인터다. null 과 0 을 구분해야 한다.
	// 초음파는 판독 결과에 이 값이 없어서 null 로 온다.
	PixelSpacingMM *float64 `json:"pixel_spacing_mm"`
}

type Image struct {
	Laterality string `json:"laterality,omitempty"` // R · L
	View       string `json:"view,omitempty"`       // CC · MLO
}

type narrativeReq struct {
	ReportID string `json:"report_id"`

	// Socket — 어느 소켓의 판독인가. 리포트 서버의 /report/{socket} 이 된다.
	// 소켓마다 프롬프트와 안내 문구표가 다르다.
	Socket string `json:"socket"` // mammo · us · mri · pathology

	// Result — 판독 결과 그대로. Go 는 안을 안 본다.
	// 형태가 소켓마다 달라서 구조체로 받으면 소켓이 늘 때마다 Go 를 고쳐야 한다.
	Result json.RawMessage `json:"result"`

	// Evidence — 근거 행. 비어 있어도 된다(병변 없음).
	Evidence []Evidence `json:"evidence"`
}

// narrativeResp — 화면에 돌려주는 것. I-4 로 보내는 것과 같은 내용이되,
// 근거는 ID 가 아니라 **행 전체**로 돌려준다. 화면이 상자를 그려야 해서다.
type narrativeResp struct {
	ReportID      string           `json:"report_id"`
	Text          string           `json:"narrative_text"`
	Notes         []report.Note    `json:"notes"`
	Evidence      []Evidence       `json:"evidence"` // 인용된 것만, 행 전체
	Dropped       []report.Dropped `json:"dropped"`
	Fallback      *string          `json:"fallback"`
	PromptVersion string           `json:"prompt_version"`
}

func main() {
	addr := env("LLM_ADDR", ":8090")
	tkey := os.Getenv("TICKET_KEY")
	cbBase := os.Getenv("CALLBACK_BASE")
	cbSec := os.Getenv("CALLBACK_SECRET")
	repBase := os.Getenv("REPORT_BASE")
	if tkey == "" || cbBase == "" || cbSec == "" {
		log.Fatal("TICKET_KEY · CALLBACK_BASE · CALLBACK_SECRET 이 필요하다")
	}
	if repBase == "" {
		log.Fatal("REPORT_BASE 가 필요하다 (예: http://tunnel:8002 — " +
			"compose 의 터널 컨테이너를 거쳐 워크스테이션 리포트 서버로 간다)")
	}
	s := &server{
		rep: report.New(repBase, dur("REPORT_TIMEOUT", 2*time.Minute)),
		cb: callback.New(cbBase, []byte(cbSec),
			os.Getenv("CALLBACK_CERT"), os.Getenv("CALLBACK_KEY"), 4),
		tv: ticket.NewVerifier([]byte(tkey)),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /svc/v1/llm/report-narrative", s.reportNarrative)
	mux.HandleFunc("GET /svc/v1/llm/health", s.health)

	log.Printf("llm-proxy %s · report %s", addr, s.rep.Base)
	srv := &http.Server{
		Addr:              addr,
		Handler:           httpx.CORS(mux, os.Getenv("CORS_ORIGINS")),
		ReadHeaderTimeout: 10 * time.Second,
		// 리포트 서버가 느릴 때를 대비해 쓰기 타임아웃은 그보다 길게 잡는다.
		WriteTimeout: 5 * time.Minute,
	}
	log.Fatal(srv.ListenAndServe())
}

// ── G-L1 ────────────────────────────────────────────────────────────
func (s *server) reportNarrative(w http.ResponseWriter, r *http.Request) {
	var req narrativeReq
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<20)).
		Decode(&req); err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다: "+err.Error())
		return
	}
	// ① 티켓 — 권한 판정이 아니라 검증만
	cl := s.verify(w, r, purposeNarrative, req.ReportID)
	if cl == nil {
		return
	}
	if req.Socket == "" {
		fail(w, 400, "BAD_REQUEST",
			"socket 이 필요하다. 소켓마다 프롬프트와 안내 문구가 다르다")
		return
	}

	// ② 근거 ID 만 뽑는다. 행은 우리가 들고 있다가 나중에 합친다.
	//
	// ⚠ 비어 있어도 400 을 내지 않는다. 예전에는 냈다.
	//   병변이 없는 것은 정상적인 판독 결과이고, "소견 없음" 도 리포트에
	//   들어가야 하는 글이다. 근거가 비면 리포트 서버가 근거 검사를
	//   건너뛰고 숫자 검사만 한다.
	byID := make(map[string]Evidence, len(req.Evidence))
	allowed := make([]string, 0, len(req.Evidence))
	for _, e := range req.Evidence {
		if e.ID == "" {
			fail(w, 400, "BAD_REQUEST", "근거 행에 id 가 없다")
			return
		}
		if _, dup := byID[e.ID]; dup {
			fail(w, 400, "BAD_REQUEST", "근거 id 가 겹친다: "+e.ID)
			return
		}
		byID[e.ID] = e
		allowed = append(allowed, e.ID)
	}

	// ③ 리포트 서버 호출
	//
	// ⚠ 요청 컨텍스트에 묶지 않는다. 화면이 중간에 닫혀도 소견을 끝까지
	//   받아 I-4 로 저장해야 한다. r.Context() 를 쓰면 브라우저를 닫는
	//   순간 취소되고, 그때까지 쓴 GPU 시간이 통째로 버려진다.
	genCtx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
	defer cancel()

	res, gerr := s.rep.Narrate(genCtx, req.Socket, report.Request{
		Result:   req.Result,
		Evidence: allowed,
	})
	if gerr != nil {
		// 명세 — 리포트 서버가 죽어도 리포트는 content_json 만으로 발급된다.
		log.Printf("[G-L1] report=%s socket=%s 리포트 서버 실패: %v",
			req.ReportID, req.Socket, gerr)
		switch {
		case errors.Is(gerr, report.ErrBadSocket):
			fail(w, 400, "BAD_REQUEST", gerr.Error())
		case errors.Is(gerr, report.ErrUnreachable):
			fail(w, 503, "UPSTREAM_LLM_UNAVAILABLE", gerr.Error()+
				" — 워크스테이션 터널이 떠 있는지 확인할 것. "+
				"리포트는 content_json 만으로 발급된다 (narrative_text=null)")
		default:
			fail(w, 503, "UPSTREAM_LLM_UNAVAILABLE", gerr.Error()+
				" — 리포트는 content_json 만으로 발급된다 (narrative_text=null)")
		}
		return
	}

	// ④ 인용된 ID 를 행으로 되돌린다.
	//
	// ⚠ 리포트 서버가 우리가 안 준 ID 를 돌려주면 버린다. 그럴 일은
	//   없어야 하지만, 지어낸 인용은 근거 없는 문장보다 나쁘다 —
	//   확인된 것처럼 보인다. 여기가 마지막 관문이다.
	cited := make([]Evidence, 0, len(res.Evidence))
	var unknown []string
	for _, id := range res.Evidence {
		if e, ok := byID[id]; ok {
			cited = append(cited, e)
		} else {
			unknown = append(unknown, id)
		}
	}
	if len(unknown) > 0 {
		log.Printf("[G-L1] report=%s ⚠ 우리가 안 준 근거 id 가 왔다: %v",
			req.ReportID, unknown)
	}

	fb := ""
	if res.Fallback != nil {
		fb = *res.Fallback
	}
	log.Printf("[G-L1] report=%s socket=%s %d자 · 근거 %d개 · 버림 %d건 · %s%s",
		req.ReportID, req.Socket, len([]rune(res.Text)), len(cited),
		len(res.Dropped), res.PromptVersion, fbNote(fb))

	// ⑤ I-4 — 여기가 '데이터 전송' 이다. Go 는 DB 에 직접 안 쓴다.
	//    멱등키는 리포트당 고정이라 재시도가 중복 행을 안 만든다.
	//    nonce 를 섞지 않는 이유가 그것이다 — 매번 달라지면 멱등성이 없다.
	drops := make([]callback.Drop, 0, len(res.Dropped))
	for _, d := range res.Dropped {
		drops = append(drops, callback.Drop{Sentence: d.Sentence, Reason: d.Reason})
	}
	notes := make([]callback.Note, 0, len(res.Notes))
	for _, n := range res.Notes {
		notes = append(notes, callback.Note{ID: n.ID, Text: n.Text})
	}
	ids := make([]string, 0, len(cited))
	for _, e := range cited {
		ids = append(ids, e.ID)
	}

	cbCtx, cbCancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cbCancel()
	cerr := s.cb.PostNarrative(cbCtx, req.ReportID, "narrative:"+req.ReportID,
		callback.Narrative{
			NarrativeText:      res.Text,
			EvidenceLinks:      ids,
			DroppedSentenceLog: drops,
			Notes:              notes,
			PromptVersion:      res.PromptVersion,
			// 되돌렸는가(boolean) 와 왜(문자열)를 나눠 보낸다.
			// res.Fallback 이 nil 이면 안 되돌린 것이다 — 사유가 빈
			// 문자열인 경우와 구분해야 해서 nil 로 판정한다.
			Fallback:       res.Fallback != nil,
			FallbackReason: fb,
		})
	if cerr != nil {
		fail(w, 502, "CALLBACK_FAILED",
			"소견은 만들었으나 Django 에 저장하지 못했다: "+cerr.Error())
		return
	}

	writeJSON(w, 200, narrativeResp{
		ReportID:      req.ReportID,
		Text:          res.Text,
		Notes:         res.Notes,
		Evidence:      cited,
		Dropped:       res.Dropped,
		Fallback:      res.Fallback,
		PromptVersion: res.PromptVersion,
	})
}

// verify — 티켓 검증.
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

// health — 터널이 안 떠 있는 일이 잦다. 그때 여기만 보면 알 수 있어야 한다.
func (s *server) health(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
	defer cancel()
	err := s.rep.Health(ctx)
	body := map[string]any{
		"report_server": err == nil,
		"report_base":   s.rep.Base,
		"error":         errStr(err),
	}
	if errors.Is(err, report.ErrUnreachable) {
		body["hint"] = "워크스테이션 터널이 안 떠 있을 가능성이 높다"
	}
	writeJSON(w, 200, body)
}

// ── 잡동사니 ────────────────────────────────────────────────────────
func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

// dur — 잘못 적힌 값은 조용히 기본값으로 덮지 않고 죽는다.
// "2" 를 적어 놓고 2분인 줄 알았는데 파싱 실패로 기본값이 쓰이면
// 아무도 모른다.
func dur(k string, def time.Duration) time.Duration {
	v := os.Getenv(k)
	if v == "" {
		return def
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		log.Fatalf("%s 를 못 읽었다: %q (예: 90s, 2m)", k, v)
	}
	return d
}

func bearer(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return r.Header.Get("X-Ticket")
}

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

func fbNote(fb string) string {
	if fb == "" {
		return ""
	}
	return " · 되돌림(" + fb + ")"
}
