package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/report"
	"cdss/gosvc/internal/ticket"
)

var tkey = []byte("ticket-key")
var csec = []byte("callback-secret")

func mkTicket(t *testing.T, purpose, scope, nonce string, exp time.Time) string {
	t.Helper()
	hdr := base64.RawURLEncoding.EncodeToString([]byte(`{"alg":"HS256","typ":"JWT"}`))
	pl, _ := json.Marshal(ticket.Claims{Purpose: purpose, ScopeID: scope,
		PatientID: "P1", Exp: exp.Unix(), Nonce: nonce})
	body := hdr + "." + base64.RawURLEncoding.EncodeToString(pl)
	m := hmac.New(sha256.New, tkey)
	m.Write([]byte(body))
	return body + "." + base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}

// ── 가짜 리포트 서버 ────────────────────────────────────────────────
type fakeReport struct {
	mu     sync.Mutex
	path   string
	req    report.Request
	status int
	body   string
	hold   chan struct{} // 닫힐 때까지 응답을 붙잡는다
}

func newFakeReport(t *testing.T) (*fakeReport, string) {
	t.Helper()
	f := &fakeReport{status: 200}
	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/health" {
				w.WriteHeader(f.status)
				return
			}
			b, _ := io.ReadAll(r.Body)
			f.mu.Lock()
			f.path = r.URL.Path
			json.Unmarshal(b, &f.req)
			status, body, hold := f.status, f.body, f.hold
			f.mu.Unlock()

			if hold != nil {
				select {
				case <-hold:
				case <-r.Context().Done():
					return
				}
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(status)
			if body == "" {
				body = `{"소견":"우상방에 종괴가 있다.","안내":[],
					"evidence":["MG-01"],"dropped":[],"fallback":null,
					"prompt_version":"mg-2026-09-02.a"}`
			}
			io.WriteString(w, body)
		}))
	t.Cleanup(srv.Close)
	return f, srv.URL
}

func (f *fakeReport) set(status int, body string) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.status, f.body = status, body
}

func (f *fakeReport) seen() (string, report.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.path, f.req
}

// ── 가짜 Django ─────────────────────────────────────────────────────
type capture struct {
	mu   sync.Mutex
	got  []callback.Narrative
	idem []string
	body [][]byte
	code int
}

func (c *capture) all() []callback.Narrative {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]callback.Narrative(nil), c.got...)
}

func fakeDjango(t *testing.T, c *capture) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			b, _ := io.ReadAll(r.Body)
			var n callback.Narrative
			json.Unmarshal(b, &n)
			c.mu.Lock()
			c.got = append(c.got, n)
			c.idem = append(c.idem, r.Header.Get("Idempotency-Key"))
			c.body = append(c.body, b)
			code := c.code
			c.mu.Unlock()
			if code == 0 {
				code = 200
			}
			w.WriteHeader(code)
		}))
	t.Cleanup(srv.Close)
	return srv.URL
}

func newServer(repURL, dURL string) *server {
	return &server{
		rep: report.New(repURL, 30*time.Second),
		cb:  callback.New(dURL, csec, "", "", 1),
		tv:  ticket.NewVerifier(tkey),
	}
}

func post(t *testing.T, s *server, tok string, body any) *httptest.ResponseRecorder {
	t.Helper()
	b, _ := json.Marshal(body)
	r := httptest.NewRequest("POST", "/svc/v1/llm/report-narrative",
		strings.NewReader(string(b)))
	r.Header.Set("Authorization", "Bearer "+tok)
	w := httptest.NewRecorder()
	s.reportNarrative(w, r)
	return w
}

func sp(v float64) *float64 { return &v }

func mammoEvidence() []Evidence {
	return []Evidence{
		{ID: "MG-01", Kind: "lesion", Frame: "pixel",
			Image: &Image{Laterality: "R", View: "MLO"},
			Box:   []int{100, 200, 180, 260}, PixelSpacingMM: sp(0.0814)},
		{ID: "MG-02", Kind: "lesion", Frame: "pixel",
			Image: &Image{Laterality: "R", View: "CC"},
			Box:   []int{110, 190, 190, 250}, PixelSpacingMM: sp(0.0814)},
	}
}

func okTicket(t *testing.T, nonce string) string {
	return mkTicket(t, purposeNarrative, "R1", nonce, time.Now().Add(2*time.Minute))
}

// ── 1. 정상 경로 ────────────────────────────────────────────────────
func TestHappyPath(t *testing.T) {
	f, repURL := newFakeReport(t)
	c := &capture{}
	s := newServer(repURL, fakeDjango(t, c))

	w := post(t, s, okTicket(t, "n1"), narrativeReq{
		ReportID: "R1", Socket: "mammo",
		Result:   json.RawMessage(`{"lesion_found":true}`),
		Evidence: mammoEvidence(),
	})
	if w.Code != 200 {
		t.Fatalf("200 이어야 한다. got=%d %s", w.Code, w.Body.String())
	}

	// 리포트 서버로 간 것 — ID 목록만이어야 한다
	path, req := f.seen()
	if path != "/report/mammo" {
		t.Errorf("소켓이 경로에 들어가야 한다. got=%s", path)
	}
	if len(req.Evidence) != 2 || req.Evidence[0] != "MG-01" {
		t.Errorf("근거 ID 목록이 가야 한다. got=%v", req.Evidence)
	}
	if string(req.Result) != `{"lesion_found":true}` {
		t.Errorf("판독 결과가 그대로 가야 한다. got=%s", req.Result)
	}
	// 좌표·화소 간격이 리포트 서버로 새어 나가면 안 된다 (설계 합의)
	if strings.Contains(string(req.Result)+strings.Join(req.Evidence, ","),
		"pixel_spacing") {
		t.Error("화소 간격은 리포트 서버로 안 보낸다")
	}

	// 화면으로 돌려준 것 — 근거는 행 전체여야 한다
	var resp narrativeResp
	json.Unmarshal(w.Body.Bytes(), &resp)
	if len(resp.Evidence) != 1 || resp.Evidence[0].ID != "MG-01" {
		t.Fatalf("인용된 근거만 행으로 와야 한다. got=%+v", resp.Evidence)
	}
	if resp.Evidence[0].PixelSpacingMM == nil ||
		*resp.Evidence[0].PixelSpacingMM != 0.0814 {
		t.Error("화면에는 화소 간격이 실려 가야 한다 — 밀리미터 표시에 쓴다")
	}
	if resp.PromptVersion != "mg-2026-09-02.a" {
		t.Errorf("prompt_version 이 와야 한다. got=%q", resp.PromptVersion)
	}

	// I-4 로 간 것
	got := c.all()
	if len(got) != 1 {
		t.Fatalf("I-4 가 한 번 가야 한다. got=%d", len(got))
	}
	if got[0].NarrativeText != "우상방에 종괴가 있다." {
		t.Errorf("소견이 그대로 가야 한다. got=%q", got[0].NarrativeText)
	}
	if len(got[0].EvidenceLinks) != 1 || got[0].EvidenceLinks[0] != "MG-01" {
		t.Errorf("인용된 근거만 가야 한다. got=%v", got[0].EvidenceLinks)
	}
	if got[0].PromptVersion != "mg-2026-09-02.a" {
		t.Errorf("prompt_version 이 I-4 에 실려야 한다 — 나중에 "+
			"'왜 이렇게 나왔나' 를 답할 근거다. got=%q", got[0].PromptVersion)
	}
	if c.idem[0] != "narrative:R1" {
		t.Errorf("멱등키는 리포트당 고정이어야 한다. got=%q", c.idem[0])
	}
}

// ── 2. 병변 없음 — 예전에는 400 이었다 ──────────────────────────────
//
// 병변이 없는 것은 정상적인 판독 결과다. "소견 없음" 도 리포트에 들어가야
// 하는 글이라 서술 단계를 막으면 보고서가 통째로 빈다.
func TestEmptyEvidenceIsAllowed(t *testing.T) {
	f, repURL := newFakeReport(t)
	f.set(200, `{"소견":"검출된 병변이 없습니다.",
		"안내":[{"id":"MG-N00","text":"병변 없음"}],
		"evidence":[],"dropped":[],"fallback":null,"prompt_version":"v1"}`)
	c := &capture{}
	s := newServer(repURL, fakeDjango(t, c))

	w := post(t, s, okTicket(t, "n2"), narrativeReq{
		ReportID: "R1", Socket: "mammo",
		Result: json.RawMessage(`{"lesion_found":false}`),
	})
	if w.Code != 200 {
		t.Fatalf("병변이 없어도 200 이어야 한다. got=%d %s", w.Code, w.Body.String())
	}
	_, req := f.seen()
	if req.Evidence == nil {
		t.Error("근거는 null 이 아니라 빈 배열로 가야 한다")
	}
	got := c.all()
	if len(got) != 1 || got[0].NarrativeText != "검출된 병변이 없습니다." {
		t.Fatalf("소견 없음도 I-4 로 가야 한다. got=%+v", got)
	}
	if len(got[0].Notes) != 1 || got[0].Notes[0].ID != "MG-N00" {
		t.Errorf("고정 안내 문구가 I-4 에 실려야 한다. got=%+v", got[0].Notes)
	}
}

// ── 3. 지어낸 근거 id 는 버린다 ─────────────────────────────────────
//
// 지어낸 인용은 근거 없는 문장보다 나쁘다 — 확인된 것처럼 보인다.
func TestUnknownEvidenceIDDropped(t *testing.T) {
	f, repURL := newFakeReport(t)
	f.set(200, `{"소견":"x","안내":[],"evidence":["MG-01","MG-99"],
		"dropped":[],"fallback":null,"prompt_version":"v1"}`)
	c := &capture{}
	s := newServer(repURL, fakeDjango(t, c))

	w := post(t, s, okTicket(t, "n3"), narrativeReq{
		ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence(),
	})
	if w.Code != 200 {
		t.Fatalf("200 이어야 한다. got=%d", w.Code)
	}
	var resp narrativeResp
	json.Unmarshal(w.Body.Bytes(), &resp)
	if len(resp.Evidence) != 1 || resp.Evidence[0].ID != "MG-01" {
		t.Fatalf("우리가 안 준 MG-99 는 버려야 한다. got=%+v", resp.Evidence)
	}
	if links := c.all()[0].EvidenceLinks; len(links) != 1 {
		t.Errorf("I-4 에도 MG-99 가 가면 안 된다. got=%v", links)
	}
}

// ── 4. dropped · fallback 이 I-4 로 간다 ────────────────────────────
func TestDroppedAndFallbackReachDjango(t *testing.T) {
	f, repURL := newFakeReport(t)
	f.set(200, `{"소견":"뼈대 문장","안내":[],"evidence":[],
		"dropped":[{"sentence":"63.9px 종괴","reason":"숫자 검사 실패"}],
		"fallback":"숫자 검사 실패","prompt_version":"v2"}`)
	c := &capture{}
	s := newServer(repURL, fakeDjango(t, c))

	post(t, s, okTicket(t, "n4"), narrativeReq{
		ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence(),
	})
	got := c.all()
	if len(got) != 1 {
		t.Fatalf("I-4 가 한 번 가야 한다. got=%d", len(got))
	}
	if !got[0].Fallback {
		t.Error("되돌렸으면 fallback 이 true 여야 한다")
	}
	if got[0].FallbackReason != "숫자 검사 실패" {
		t.Errorf("되돌린 사유가 남아야 한다. got=%q", got[0].FallbackReason)
	}
	if len(got[0].DroppedSentenceLog) != 1 {
		t.Errorf("버린 문장이 남아야 한다. got=%+v", got[0].DroppedSentenceLog)
	}
}

// ── 5. 터널이 안 떠 있으면 503 · 원인을 말한다 ──────────────────────
func TestReportServerUnreachable(t *testing.T) {
	c := &capture{}
	s := newServer("http://127.0.0.1:1", fakeDjango(t, c))

	w := post(t, s, okTicket(t, "n5"), narrativeReq{
		ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence(),
	})
	if w.Code != 503 {
		t.Fatalf("503 이어야 한다. got=%d", w.Code)
	}
	body := w.Body.String()
	if !strings.Contains(body, "UPSTREAM_LLM_UNAVAILABLE") {
		t.Errorf("코드가 UPSTREAM_LLM_UNAVAILABLE 이어야 한다. got=%s", body)
	}
	if !strings.Contains(body, "터널") {
		t.Errorf("가장 흔한 원인(터널)을 짚어야 한다. got=%s", body)
	}
	if len(c.all()) != 0 {
		t.Error("소견을 못 만들었으면 I-4 를 보내면 안 된다")
	}
}

// ── 6. 소켓 이름 ────────────────────────────────────────────────────
func TestSocketRequired(t *testing.T) {
	_, repURL := newFakeReport(t)
	s := newServer(repURL, fakeDjango(t, &capture{}))

	w := post(t, s, okTicket(t, "n6"), narrativeReq{
		ReportID: "R1", Evidence: mammoEvidence(),
	})
	if w.Code != 400 {
		t.Fatalf("socket 이 없으면 400 이어야 한다. got=%d", w.Code)
	}
}

// 소켓 이름이 그대로 주소에 들어가므로 경로를 벗어나는 값은 막아야 한다.
func TestSocketPathTraversalRejected(t *testing.T) {
	f, repURL := newFakeReport(t)
	s := newServer(repURL, fakeDjango(t, &capture{}))

	w := post(t, s, okTicket(t, "n7"), narrativeReq{
		ReportID: "R1", Socket: "../health", Evidence: mammoEvidence(),
	})
	if w.Code != 400 {
		t.Fatalf("400 이어야 한다. got=%d %s", w.Code, w.Body.String())
	}
	if path, _ := f.seen(); path != "" {
		t.Errorf("서버를 아예 부르면 안 된다. 불린 경로=%s", path)
	}
}

// ── 7. 근거 행 검사 ─────────────────────────────────────────────────
func TestEvidenceRowValidation(t *testing.T) {
	_, repURL := newFakeReport(t)
	s := newServer(repURL, fakeDjango(t, &capture{}))

	// id 없는 행
	w := post(t, s, okTicket(t, "n8"), narrativeReq{
		ReportID: "R1", Socket: "mammo",
		Evidence: []Evidence{{Kind: "lesion"}},
	})
	if w.Code != 400 {
		t.Errorf("id 없는 행은 400 이어야 한다. got=%d", w.Code)
	}

	// id 가 겹치는 행 — 겹치면 어느 상자를 가리키는지 알 수 없다
	w = post(t, s, okTicket(t, "n9"), narrativeReq{
		ReportID: "R1", Socket: "mammo",
		Evidence: []Evidence{{ID: "MG-01"}, {ID: "MG-01"}},
	})
	if w.Code != 400 {
		t.Errorf("겹치는 id 는 400 이어야 한다. got=%d", w.Code)
	}
}

// ── 8. 티켓 ─────────────────────────────────────────────────────────
func TestTicketChecks(t *testing.T) {
	_, repURL := newFakeReport(t)
	s := newServer(repURL, fakeDjango(t, &capture{}))
	body := narrativeReq{ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence()}

	if w := post(t, s, "garbage", body); w.Code != 401 {
		t.Errorf("망가진 티켓은 401. got=%d", w.Code)
	}
	exp := mkTicket(t, purposeNarrative, "R1", "x1", time.Now().Add(-time.Minute))
	if w := post(t, s, exp, body); w.Code != 401 {
		t.Errorf("만료된 티켓은 401. got=%d", w.Code)
	}
	// 다른 리포트를 가리키는 티켓
	other := mkTicket(t, purposeNarrative, "R9", "x2", time.Now().Add(time.Minute))
	if w := post(t, s, other, body); w.Code != 403 {
		t.Errorf("범위가 다르면 403. got=%d", w.Code)
	}
	// 용도가 다른 티켓 — 업로드용으로 소견을 만들 수 없다
	wrong := mkTicket(t, "upload", "R1", "x3", time.Now().Add(time.Minute))
	if w := post(t, s, wrong, body); w.Code != 403 {
		t.Errorf("용도가 다르면 403. got=%d", w.Code)
	}
	// 같은 nonce 재사용
	tok := okTicket(t, "reuse")
	if w := post(t, s, tok, body); w.Code != 200 {
		t.Fatalf("첫 번째는 통과해야 한다. got=%d %s", w.Code, w.Body.String())
	}
	if w := post(t, s, tok, body); w.Code != 401 {
		t.Errorf("같은 티켓 재사용은 막아야 한다. got=%d", w.Code)
	}
}

// ── 9. 화면이 닫혀도 저장은 끝낸다 ──────────────────────────────────
//
// 생성을 요청 컨텍스트에 묶으면 브라우저를 닫는 순간 취소되고,
// 그때까지 쓴 GPU 시간이 통째로 버려진다.
func TestClientGoneStillSaves(t *testing.T) {
	f, repURL := newFakeReport(t)
	hold := make(chan struct{})
	f.mu.Lock()
	f.hold = hold
	f.mu.Unlock()

	c := &capture{}
	s := newServer(repURL, fakeDjango(t, c))

	b, _ := json.Marshal(narrativeReq{
		ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence()})
	r := httptest.NewRequest("POST", "/svc/v1/llm/report-narrative",
		strings.NewReader(string(b)))
	r.Header.Set("Authorization", "Bearer "+okTicket(t, "n10"))

	// 요청 컨텍스트를 먼저 끊는다 — 브라우저가 닫힌 상황
	ctx, cancel := context.WithCancel(r.Context())
	r = r.WithContext(ctx)
	cancel()

	done := make(chan struct{})
	go func() {
		defer close(done)
		s.reportNarrative(httptest.NewRecorder(), r)
	}()

	close(hold) // 리포트 서버가 이제 응답한다
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("끝나지 않았다")
	}
	if got := c.all(); len(got) != 1 {
		t.Fatalf("화면이 닫혀도 I-4 는 가야 한다. got=%d", len(got))
	}
}

// ── 10. Django 저장 실패 ────────────────────────────────────────────
func TestCallbackFailure(t *testing.T) {
	_, repURL := newFakeReport(t)
	c := &capture{code: 500}
	s := newServer(repURL, fakeDjango(t, c))

	w := post(t, s, okTicket(t, "n11"), narrativeReq{
		ReportID: "R1", Socket: "mammo", Evidence: mammoEvidence(),
	})
	if w.Code != 502 {
		t.Fatalf("502 여야 한다. got=%d %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "CALLBACK_FAILED") {
		t.Errorf("무엇이 실패했는지 말해야 한다. got=%s", w.Body.String())
	}
}

// ── 11. health ──────────────────────────────────────────────────────
func TestHealth(t *testing.T) {
	_, repURL := newFakeReport(t)
	s := newServer(repURL, fakeDjango(t, &capture{}))

	w := httptest.NewRecorder()
	s.health(w, httptest.NewRequest("GET", "/svc/v1/llm/health", nil))
	var body map[string]any
	json.Unmarshal(w.Body.Bytes(), &body)
	if body["report_server"] != true {
		t.Errorf("살아 있으면 true 여야 한다. got=%v", body)
	}

	dead := newServer("http://127.0.0.1:1", fakeDjango(t, &capture{}))
	w = httptest.NewRecorder()
	dead.health(w, httptest.NewRequest("GET", "/svc/v1/llm/health", nil))
	json.Unmarshal(w.Body.Bytes(), &body)
	if body["report_server"] != false {
		t.Errorf("안 닿으면 false 여야 한다. got=%v", body)
	}
	if body["hint"] == nil {
		t.Error("터널을 의심하라고 알려줘야 한다 — 가장 흔한 원인이다")
	}
}
