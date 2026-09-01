package main

import (
	"bufio"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/ollama"
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

// 가짜 Ollama — 줄 단위 JSON 을 천천히 흘려보낸다
func fakeOllama(chunks []string, delay time.Duration) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/api/tags") {
			json.NewEncoder(w).Encode(map[string]any{
				"models": []map[string]any{{"name": "medgemma", "size": 1}}})
			return
		}
		fl, _ := w.(http.Flusher)
		for _, c := range chunks {
			fmt.Fprintf(w, `{"message":{"content":%q},"done":false}`+"\n", c)
			if fl != nil {
				fl.Flush()
			}
			time.Sleep(delay)
		}
		fmt.Fprint(w, `{"done":true}`+"\n")
		if fl != nil {
			fl.Flush()
		}
	}))
}

type capture struct {
	mu   sync.Mutex
	got  []callback.Narrative
	idem []string
	sig  []string
	body [][]byte
}

func fakeDjango(c *capture) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		var n callback.Narrative
		json.Unmarshal(b, &n)
		c.mu.Lock()
		c.got = append(c.got, n)
		c.idem = append(c.idem, r.Header.Get("Idempotency-Key"))
		c.sig = append(c.sig, r.Header.Get("X-Signature"))
		c.body = append(c.body, b)
		c.mu.Unlock()
		w.WriteHeader(200)
	}))
}

func newServer(oURL, dURL string) *server {
	return &server{
		oll: ollama.New(oURL, "medgemma", time.Minute),
		cb:  callback.New(dURL, csec, "", "", 1),
		tv:  ticket.NewVerifier(tkey),
	}
}

func post(t *testing.T, s *server, tok string, body any) *httptest.ResponseRecorder {
	t.Helper()
	b, _ := json.Marshal(body)
	r := httptest.NewRequest("POST", "/svc/v1/llm/report-narrative", strings.NewReader(string(b)))
	r.Header.Set("Authorization", "Bearer "+tok)
	w := httptest.NewRecorder()
	s.reportNarrative(w, r)
	return w
}

func evid() []Evidence {
	return []Evidence{{ID: "L1", Kind: "lesion", Text: "우상방 종괴 1.2cm"},
		{ID: "L2", Kind: "lesion", Text: "미세석회 군집"}}
}

// ── 1. 정상 경로 + 근거 필터 + I-4 ────────────────────────────────
func TestHappyPathAndEvidenceFilter(t *testing.T) {
	chunks := []string{
		"우상방에 1.2cm 종괴가 있다 [[e:L1]]. ",
		"군집성 미세석회가 동반된다 [[e:L2]]. ",
		"악성이 강력히 의심된다. ",         // 근거 표시 없음 → 버림
		"림프절 전이가 보인다 [[e:L9]]. ", // 지어낸 id → 버림
	}
	o, d := fakeOllama(chunks, 0), fakeDjango(&capture{})
	defer o.Close()
	defer d.Close()
	cap := &capture{}
	d.Close()
	d = fakeDjango(cap)
	defer d.Close()

	s := newServer(o.URL, d.URL)
	tok := mkTicket(t, purposeNarrative, "R1", "n1", time.Now().Add(time.Minute))
	w := post(t, s, tok, narrativeReq{ReportID: "R1", Evidence: evid()})

	if w.Code != 200 {
		t.Fatalf("code=%d body=%s", w.Code, w.Body.String())
	}
	// SSE 토큰이 흘렀나
	if !strings.Contains(w.Body.String(), "event: token") {
		t.Fatal("토큰 이벤트가 없다")
	}
	if !strings.Contains(w.Body.String(), "event: done") {
		t.Fatalf("done 이벤트가 없다: %s", w.Body.String())
	}
	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.got) != 1 {
		t.Fatalf("I-4 콜백이 %d번 왔다", len(cap.got))
	}
	n := cap.got[0]
	if strings.Contains(n.NarrativeText, "악성이 강력히") {
		t.Error("근거 없는 문장이 살아남았다")
	}
	if strings.Contains(n.NarrativeText, "림프절") {
		t.Error("지어낸 근거를 인용한 문장이 살아남았다")
	}
	if !strings.Contains(n.NarrativeText, "종괴") || !strings.Contains(n.NarrativeText, "미세석회") {
		t.Errorf("근거 있는 문장이 버려졌다: %q", n.NarrativeText)
	}
	if strings.Contains(n.NarrativeText, "[[e:") {
		t.Error("근거 표시가 본문에 남았다")
	}
	if len(n.DroppedSentenceLog) != 2 {
		t.Errorf("버린 문장 %d건 (2건이어야)", len(n.DroppedSentenceLog))
	}
	if fmt.Sprint(n.EvidenceLinks) != "[L1 L2]" {
		t.Errorf("evidence_links=%v", n.EvidenceLinks)
	}
	// 멱등키 · 서명
	if cap.idem[0] != "narrative:R1" {
		t.Errorf("멱등키=%s", cap.idem[0])
	}
	t.Logf("서술 %q · 버림 %d · 근거 %v", n.NarrativeText,
		len(n.DroppedSentenceLog), n.EvidenceLinks)
}

// ── 2. 티켓 ────────────────────────────────────────────────────────
func TestTicket(t *testing.T) {
	o, cap := fakeOllama([]string{"가 [[e:L1]]."}, 0), &capture{}
	d := fakeDjango(cap)
	defer o.Close()
	defer d.Close()
	s := newServer(o.URL, d.URL)

	// 만료
	old := mkTicket(t, purposeNarrative, "R1", "x1", time.Now().Add(-time.Minute))
	if w := post(t, s, old, narrativeReq{ReportID: "R1", Evidence: evid()}); w.Code != 401 {
		t.Errorf("만료 티켓 code=%d", w.Code)
	}
	// 범위 불일치 — 티켓은 R1 인데 R2 를 요청
	tk := mkTicket(t, purposeNarrative, "R1", "x2", time.Now().Add(time.Minute))
	if w := post(t, s, tk, narrativeReq{ReportID: "R2", Evidence: evid()}); w.Code != 403 {
		t.Errorf("범위 불일치 code=%d", w.Code)
	}
	// 재사용 — 같은 nonce 두 번
	tk2 := mkTicket(t, purposeNarrative, "R3", "reuse", time.Now().Add(time.Minute))
	if w := post(t, s, tk2, narrativeReq{ReportID: "R3", Evidence: evid()}); w.Code != 200 {
		t.Fatalf("첫 사용 code=%d", w.Code)
	}
	if w := post(t, s, tk2, narrativeReq{ReportID: "R3", Evidence: evid()}); w.Code != 401 {
		t.Errorf("nonce 재사용이 통과했다 code=%d", w.Code)
	}
	// 서명 위조
	bad := tk2[:len(tk2)-4] + "AAAA"
	if w := post(t, s, bad, narrativeReq{ReportID: "R3", Evidence: evid()}); w.Code != 401 {
		t.Errorf("위조 서명 code=%d", w.Code)
	}
}

// ── 3. 근거 없이 요청하면 시작도 안 한다 ──────────────────────────
func TestNoEvidence(t *testing.T) {
	o, cap := fakeOllama([]string{"x"}, 0), &capture{}
	d := fakeDjango(cap)
	defer o.Close()
	defer d.Close()
	s := newServer(o.URL, d.URL)
	tk := mkTicket(t, purposeNarrative, "R1", "e0", time.Now().Add(time.Minute))
	w := post(t, s, tk, narrativeReq{ReportID: "R1"})
	if w.Code != 400 {
		t.Errorf("code=%d", w.Code)
	}
	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.got) != 0 {
		t.Error("근거가 없는데 콜백이 갔다")
	}
}

// ── 4. Ollama 가 죽어도 리포트는 막히지 않는다 ────────────────────
func TestOllamaDown(t *testing.T) {
	cap := &capture{}
	d := fakeDjango(cap)
	defer d.Close()
	s := newServer("http://127.0.0.1:1", d.URL) // 아무도 안 듣는 포트
	tk := mkTicket(t, purposeNarrative, "R1", "d1", time.Now().Add(time.Minute))
	w := post(t, s, tk, narrativeReq{ReportID: "R1", Evidence: evid()})
	if !strings.Contains(w.Body.String(), "UPSTREAM_LLM_UNAVAILABLE") {
		t.Errorf("body=%s", w.Body.String())
	}
	t.Log("Ollama 불가 → SSE error 이벤트로 알리고 리포트 발급은 안 막는다")
}

// ── 5. ★ 화면이 닫혀도 생성을 끝내고 I-4 가 간다 ──────────────────
func TestClientDisconnectStillCallsBack(t *testing.T) {
	// 조각 사이에 지연을 줘서, 중간에 클라이언트를 끊는다
	o := fakeOllama([]string{
		"우상방에 종괴 [[e:L1]]. ", "군집 석회 [[e:L2]]. ", "추가 소견 [[e:L1]]. ",
	}, 60*time.Millisecond)
	defer o.Close()
	cap := &capture{}
	d := fakeDjango(cap)
	defer d.Close()
	s := newServer(o.URL, d.URL)

	mux := http.NewServeMux()
	mux.HandleFunc("POST /svc/v1/llm/report-narrative", s.reportNarrative)
	hs := httptest.NewServer(mux)
	defer hs.Close()

	tk := mkTicket(t, purposeNarrative, "R9", "cut", time.Now().Add(time.Minute))
	b, _ := json.Marshal(narrativeReq{ReportID: "R9", Evidence: evid()})
	req, _ := http.NewRequest("POST", hs.URL+"/svc/v1/llm/report-narrative",
		strings.NewReader(string(b)))
	req.Header.Set("Authorization", "Bearer "+tk)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	// 첫 토큰만 읽고 끊는다
	br := bufio.NewReader(res.Body)
	br.ReadString('\n')
	res.Body.Close()

	// 서버는 계속 생성하고 콜백을 보내야 한다
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		cap.mu.Lock()
		n := len(cap.got)
		cap.mu.Unlock()
		if n > 0 {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	cap.mu.Lock()
	defer cap.mu.Unlock()
	if len(cap.got) == 0 {
		t.Fatal("화면이 닫히자 I-4 가 안 갔다 — 생성한 것이 버려진다")
	}
	got := cap.got[0].NarrativeText
	if !strings.Contains(got, "추가 소견") {
		t.Errorf("끊긴 뒤 조각이 빠졌다: %q", got)
	}
	t.Logf("화면을 끊었는데도 끝까지 생성하고 저장했다: %q", got)
}

// ── 6. I-4 서명이 Django 쪽에서 재현되는가 ────────────────────────
func TestSignature(t *testing.T) {
	ts := "1756600000"
	body := []byte(`{"narrative_text":"x"}`)
	want := callback.Sign(csec, ts, body)
	m := hmac.New(sha256.New, csec)
	m.Write([]byte(ts + "." + string(body)))
	if fmt.Sprintf("%x", m.Sum(nil)) != want {
		t.Fatal("서명 계산이 문서와 다르다")
	}
	t.Log("HMAC-SHA256(ts + \".\" + body) — Django 도 이대로 계산하면 된다")
}
