// llm-proxy — 명세 19-4. 판독 결과를 소견으로 바꿔 Django 에 넣는다.
//
//	G-L1  POST /svc/v1/llm/report-narrative   판독 결과 → 리포트 서버 → I-4
//	G-L2  POST /svc/v1/llm/chat               환자 문의 → Ollama (내부 서명)
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
//	· G-L2 대화 — 이번 범위에서 뺐다 (→ 2026-09-17 에 다시 넣었다, 아래)
//
// internal/narrative(근거 검사)는 **남겨 뒀다.** 되돌릴 일이 생기면 그게
// 있어야 하고, 같은 규칙이 두 곳에 적혀 있으면 리포트 서버 쪽 판정과 대조해
// 볼 수 있다. 지금은 아무도 안 부른다.
//
// ── 2026-09-17 변경 — G-L2 대화를 넣었다 ──────────────────────────
//
// 09-02 에 뺀 이유는 「자유 질문에는 검사를 걸 자리가 없다」였다. 그래서
// 자유 질문을 안 받는다 — **이미 발급된 리포트 1건에 대한 후속 질문만**
// 받는다. 답의 재료가 그 소견과 근거 목록으로 고정되면 검사가 다시 가능해진다.
//
// 규칙과 한도는 internal/chat 한 곳에 있다. 소켓마다 갈리지 않아 소켓이
// 늘어도 안 고친다 — G-L1 을 리포트 서버로 옮긴 이유가 여기엔 안 걸린다.
//
// **저장하지 않는다** (팀 결정). 대화 표도 콜백도 없고 이력은 화면이 들고
// 있다. 그 대가로 「화면이 보낸 소견이 진짜인가」를 Go 가 볼 수 없게 되는데,
// 티켓에 실린 content_hash 로 대조한다.
//
// 흘려보내지(SSE) 않는 것은 G-L1 과 같다. 다만 이유는 다르다 — 여기서는
// 검사가 아니라 **나중에 바꿀 수 있어서** 안 했다. ollama.Chat 이 onChunk 를
// 받게 돼 있어서, 느리다고 판단되면 지금 nil 인 자리를 채우면 된다.
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
	"crypto/hmac"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/chat"
	"cdss/gosvc/internal/httpx"
	"cdss/gosvc/internal/ollama"
	"cdss/gosvc/internal/report"
	"cdss/gosvc/internal/ticket"
)

const purposeNarrative = "report_narrative"

type server struct {
	rep *report.Client
	cb  *callback.Client
	tv  *ticket.Verifier

	// ol 은 **nil 일 수 있다.** OLLAMA_BASE 가 비면 대화만 503 이 되고
	// 소견(G-L1)은 그대로 돈다. 여기서 log.Fatal 을 내면 대화 설정 하나
	// 빠뜨린 것 때문에 판독 경로가 통째로 멈춘다.
	ol          *ollama.Client
	chatTimeout time.Duration

	// secret — Django 가 대화 요청에 서명하는 키. 티켓이 아니다.
	//
	// 대화는 **서버 간 호출**이다. 브라우저가 Django 의 /api/v1/chat 을
	// 부르고 Django 가 여기를 부른다. notify 의 G-N2 발행과 같은 자리라
	// 같은 수법을 쓴다 — 「티켓은 사용자용이고 발행은 서버 간 호출이다」.
	secret []byte
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

// ── G-L2 ────────────────────────────────────────────────────────────

// chatReq — **Django 가** 보내는 것. 브라우저가 아니다.
//
// 소견과 근거를 Django 가 DB 에서 읽어 실어 준다. 그래서 위조를 막을 장치가
// 따로 필요 없다 — 맥락이 브라우저를 거치지 않는다.
//
// (2026-09-17 중간에 바뀐 자리다. 처음에는 브라우저가 Go 를 직접 부르고
//
//	소견을 본문에 실어 보냈다. 그때는 그것이 진짜인지 볼 방법이 없어서
//	티켓에 소견 해시를 실어 대조했다. Django 가 부르게 되면서 해시도 티켓도
//	통째로 필요 없어졌다.)
type chatReq struct {
	ReportID string `json:"report_id"`

	// Narrative — **비어 있을 수 있다.** 아직 열린 리포트가 없는 환자다.
	// 그때는 용어 설명만 한다 — internal/chat 의 규칙이 두 경우를 나눈다.
	Narrative string `json:"narrative_text"`

	// Evidence — 근거 **id 만**. 행(좌표·화소 간격)은 화면이 이미 갖고 있고
	// 모델은 인용만 하면 되므로 보낼 이유가 없다.
	Evidence []string `json:"evidence"`

	// Messages — 주고받은 말. 지금 화면은 마지막 질문 하나만 보내지만
	// 여러 마디를 받아 둔다 — 화면이 이력을 싣기 시작하면 그대로 돈다.
	Messages []chat.Turn `json:"messages"`
}

type chatResp struct {
	ReportID string   `json:"report_id"`
	Text     string   `json:"text"`
	Evidence []string `json:"evidence"` // 이 답이 실제로 인용한 id

	// Fabricated — 모델이 지어낸 인용. 본문에서는 지웠고 기록으로만 남긴다.
	// 화면이 이걸 보여줄 필요는 없지만, 비어 있지 않다는 것은 모델이 규칙을
	// 어겼다는 뜻이라 개발 중에 눈에 보이는 편이 낫다.
	Fabricated []string `json:"fabricated_citations"`

	// Fallback — 모델 출력을 버리고 고정 문구로 되돌렸는가. G-L1 의 I-4 가
	// 같은 두 칸(fallback · fallback_reason)을 쓴다. 되돌렸다는 사실과
	// 왜 되돌렸는지를 나눠 두어야 나중에 「이 답은 왜 이런가」에 답할 수 있다.
	Fallback       bool   `json:"fallback"`
	FallbackReason string `json:"fallback_reason,omitempty"`

	Model string `json:"model"`
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
		// chat 은 nonce 를 소진하지 않는다 — 티켓 하나로 대화 한 세션을 간다.
		//
		// tile 과 같은 이유다(명세 §19-5 「뷰어 세션 단위 발급」). 1회용이면
		// 화면이 말 한 마디마다 티켓을 새로 받아야 하고, 두 번째 질문부터
		// TICKET_REPLAYED 가 떠서 원인을 엉뚱한 데서 찾게 된다.
		//
		// 쓰기가 아니라 안전하다 — 대화는 아무것도 저장하지 않으므로 같은
		// 요청을 다시 보내도 덮어쓸 자리가 없다. 재사용을 막는 것은 exp
		// (TICKET_TTL_CHAT) 하나뿐이니 거기를 길게 잡지 말 것.
		tv:          ticket.NewVerifier([]byte(tkey)),
		secret:      []byte(cbSec),
		chatTimeout: dur("CHAT_TIMEOUT", 3*time.Minute),
	}
	if ob := os.Getenv("OLLAMA_BASE"); ob != "" {
		model := env("OLLAMA_MODEL", "medgemma")
		s.ol = ollama.New(ob, model, s.chatTimeout)
		log.Printf("대화(G-L2) 켜짐 · ollama %s · 모델 %s", ob, model)
	} else {
		log.Print("⚠ OLLAMA_BASE 가 비어 있다 — /svc/v1/llm/chat 은 503 을 낸다. " +
			"소견(G-L1)은 리포트 서버로 가므로 영향이 없다")
	}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /svc/v1/llm/report-narrative", s.reportNarrative)
	mux.HandleFunc("POST /svc/v1/llm/chat", s.chat)
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

// ── G-L2 · 대화 ─────────────────────────────────────────────────────
//
// 리포트 1건에 대한 후속 질문. **아무것도 저장하지 않는다** — 콜백이 없다.
func (s *server) chat(w http.ResponseWriter, r *http.Request) {
	// ① Django 가 보낸 것인가. 티켓이 아니라 내부 서명이다 — 이 경로는
	//    브라우저가 직접 부르지 않는다.
	body, ok := s.signed(w, r)
	if !ok {
		return
	}
	var req chatReq
	if err := json.Unmarshal(body, &req); err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다: "+err.Error())
		return
	}
	if s.ol == nil {
		fail(w, 503, "UPSTREAM_LLM_UNAVAILABLE",
			"OLLAMA_BASE 가 비어 있어 대화를 받을 수 없다 — conf/gosvc.env 와 "+
				"터널 컨테이너의 11434 넘김을 확인할 것")
		return
	}

	// ② 규칙·한도 검사와 메시지 조립. 전부 internal/chat 에 있다.
	msgs, err := chat.Build(req.Narrative, req.Evidence, req.Messages)
	if err != nil {
		fail(w, 400, "BAD_REQUEST", err.Error())
		return
	}

	// ③ Ollama.
	//
	// ⚠ 여기는 G-L1 과 **반대로** 요청 컨텍스트에 묶는다.
	//
	//   G-L1   화면이 닫혀도 끝까지 받아 I-4 로 저장해야 한다 → 떼어 놓는다
	//   G-L2   저장할 곳이 없다. 화면이 닫히면 그 답은 아무도 안 본다 →
	//          계속 돌리면 남의 판독이 기다리는 GPU 를 그냥 버리는 것이다
	//
	// 같은 파일 안에서 규칙이 반대인 자리라 그대로 베끼지 말 것.
	ctx, cancel := context.WithTimeout(r.Context(), s.chatTimeout)
	defer cancel()

	// onChunk 가 nil 이라 한 덩어리로 받는다. SSE 로 바꿀 때 채우는 자리가
	// 여기다 — 그 외에는 고칠 것이 없다.
	raw, err := s.ol.Chat(ctx, msgs, nil)
	if err != nil {
		log.Printf("[G-L2] report=%s ollama 실패: %v", req.ReportID, err)
		fail(w, 503, "UPSTREAM_LLM_UNAVAILABLE", err.Error()+
			" — 워크스테이션 터널의 11434 넘김을 확인할 것")
		return
	}

	// ④ 지어낸 인용을 걷어낸다. 문장은 버리지 않는다 — 되묻는 말에는 근거가
	//    붙을 자리가 없어서, narrative.Filter 를 그대로 걸면 "네, 그렇습니다"
	//    같은 답이 통째로 사라진다.
	text, cited, fab := chat.StripCitations(raw, req.Evidence)
	if len(fab) > 0 {
		log.Printf("[G-L2] report=%s ⚠ 지어낸 근거 인용을 지웠다: %v",
			req.ReportID, fab)
	}

	// ⑤ 내보내도 되는 답인가. 아니면 **통째로 버린다.**
	//
	//    G-L1 이 검사에 걸린 문장을 뼈대 문장으로 되돌리는 것과 같은 수법이다.
	//    여기서 걸리는 것은 규칙을 어기고 병명·치료를 말한 답이고, 이 대화는
	//    환자용 앱에서만 쓰이므로 그대로 내보내면 환자가 확인되지 않은 진단을
	//    받는다.
	//
	//    근거도 같이 버린다. 버린 글의 인용이라 가리킬 곳이 없다.
	if reason := chat.Screen(text, req.Narrative); reason != "" {
		log.Printf("[G-L2] report=%s ⚠ 되돌렸다(%q) · 버린 답 %d자",
			req.ReportID, reason, len([]rune(text)))
		writeJSON(w, 200, chatResp{
			ReportID:       req.ReportID,
			Text:           chat.Fallback,
			Evidence:       []string{},
			Fabricated:     []string{},
			Fallback:       true,
			FallbackReason: reason,
			Model:          s.ol.Model,
		})
		return
	}

	log.Printf("[G-L2] report=%s %d자 · 인용 %d개 · 주고받은 말 %d개",
		req.ReportID, len([]rune(text)), len(cited), len(req.Messages))

	writeJSON(w, 200, chatResp{
		ReportID:   req.ReportID,
		Text:       text,
		Evidence:   cited,
		Fabricated: fab,
		Model:      s.ol.Model,
	})
}

// signed — Django 가 보낸 요청인가. 내부 서명(HMAC)으로 본다.
//
// notify 의 G-N2 발행과 같은 수법이고 키도 같다(CALLBACK_SECRET). 다만
// 방향이 반대다 — 콜백은 Go 가 서명하고 Django 가 검증하는데, 여기는
// Django 가 서명하고 Go 가 검증한다.
//
// ⚠ 타임스탬프를 안 보면 가로챈 요청을 언제든 다시 보낼 수 있다. 대화는
// 저장하는 곳이 없어 덮어쓸 자리는 없지만, 남의 GPU 시간을 무한히 태울 수
// 있다. 5분을 벗어난 서명은 거부한다.
func (s *server) signed(w http.ResponseWriter, r *http.Request) ([]byte, bool) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 256<<10))
	if err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다")
		return nil, false
	}
	ts, sig := r.Header.Get("X-Timestamp"), r.Header.Get("X-Signature")
	if ts == "" || sig == "" {
		fail(w, 401, "SIGNATURE_MISSING", "X-Timestamp · X-Signature 가 필요하다")
		return nil, false
	}
	n, perr := strconv.ParseInt(ts, 10, 64)
	if perr != nil || abs64(time.Now().Unix()-n) > 300 {
		fail(w, 401, "SIGNATURE_STALE", "타임스탬프가 5분을 벗어났다")
		return nil, false
	}
	if !hmac.Equal([]byte(callback.Sign(s.secret, ts, body)), []byte(sig)) {
		fail(w, 401, "SIGNATURE_INVALID", "서명이 맞지 않는다")
		return nil, false
	}
	return body, true
}

func abs64(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

// verify — 티켓 검증. G-L1 만 쓴다 — 대화는 위의 내부 서명으로 간다.
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
		// 대화가 켜져 있는가(설정). 닿는가(ollama)와 다른 이야기다 —
		// 나누지 않으면 「설정을 빠뜨린 것」과 「터널이 죽은 것」이 같아 보인다.
		"chat": s.ol != nil,
	}
	if errors.Is(err, report.ErrUnreachable) {
		body["hint"] = "워크스테이션 터널이 안 떠 있을 가능성이 높다"
	}
	if s.ol != nil {
		_, oerr := s.ol.Models(ctx)
		body["ollama"] = oerr == nil
		body["ollama_base"] = s.ol.Base
		body["ollama_model"] = s.ol.Model
		body["ollama_error"] = errStr(oerr)
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
