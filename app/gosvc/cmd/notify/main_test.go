// notify 시험.
//
// 여기서 지키려는 것
//
//	· 남의 알림이 남에게 가면 안 된다 (환자 판독 결과가 새는 것과 같다)
//	· 발행은 아무나 못 한다 — 서명 없이 되면 누구나 가짜 알림을 쏜다
//	· 확인 처리가 Django 에 안 갔는데 200 을 내면 알림이 계속 다시 뜬다
//
// SSE 를 시험하려면 진짜 서버가 필요하다. httptest.ResponseRecorder 는
// Flusher 가 아니라 스트리밍 경로를 못 태운다.
package main

import (
	"bufio"
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/hub"
	"cdss/gosvc/internal/ticket"
)

const (
	tkey  = "ticket-key"
	cbsec = "cb-secret"
)

type i3 struct {
	Idem string
	Body callback.NotificationDelivery
}

type rig struct {
	s   *svc
	srv *httptest.Server

	mu   sync.Mutex
	got  []i3
	code int
}

func newRig(t *testing.T) *rig {
	t.Helper()
	r := &rig{code: 200}
	dj := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		b, _ := io.ReadAll(req.Body)
		var d callback.NotificationDelivery
		json.Unmarshal(b, &d)
		r.mu.Lock()
		r.got = append(r.got, i3{Idem: req.Header.Get("Idempotency-Key"), Body: d})
		code := r.code
		r.mu.Unlock()
		w.WriteHeader(code)
	}))
	t.Cleanup(dj.Close)

	r.s = &svc{
		h:      hub.New(4),
		cb:     callback.New(dj.URL, []byte(cbsec), "", "", 0),
		tv:     ticket.NewVerifier([]byte(tkey)),
		secret: []byte(cbsec),
	}
	r.srv = httptest.NewServer(r.s.routes())
	t.Cleanup(r.srv.Close)
	return r
}

func (r *rig) deliveries() []i3 {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]i3(nil), r.got...)
}

// waitDeliveries — I-3 은 배경으로 나가므로 잠깐 기다린다.
func (r *rig) waitDeliveries(n int) []i3 {
	for i := 0; i < 100; i++ {
		if d := r.deliveries(); len(d) >= n {
			return d
		}
		time.Sleep(10 * time.Millisecond)
	}
	return r.deliveries()
}

var nonceSeq int

func mint(t *testing.T, purpose, scope string) string {
	t.Helper()
	nonceSeq++
	c := ticket.Claims{Purpose: purpose, ScopeID: scope, PatientID: "P-1",
		Exp:   time.Now().Add(5 * time.Minute).Unix(),
		Nonce: fmt.Sprintf("n-%d", nonceSeq)}
	b64 := func(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }
	pay, _ := json.Marshal(c)
	signing := b64([]byte(`{"alg":"HS256","typ":"JWT"}`)) + "." + b64(pay)
	m := hmac.New(sha256.New, []byte(tkey))
	m.Write([]byte(signing))
	return signing + "." + b64(m.Sum(nil))
}

// signed — Django 가 보내는 것과 같은 서명된 요청
func (r *rig) signed(t *testing.T, method, path string, body any) *http.Response {
	t.Helper()
	b, _ := json.Marshal(body)
	if body == nil {
		b = []byte("{}")
	}
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	req, _ := http.NewRequest(method, r.srv.URL+path, bytes.NewReader(b))
	req.Header.Set("X-Timestamp", ts)
	req.Header.Set("X-Signature", callback.Sign([]byte(cbsec), ts, b))
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return res
}

// stream — SSE 를 연다. 이벤트를 채널로 흘린다.
type sseEvent struct{ Event, Data string }

func (r *rig) open(t *testing.T, tok string) (<-chan sseEvent, func(), *http.Response) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	req, _ := http.NewRequestWithContext(ctx, "GET",
		r.srv.URL+"/svc/v1/notify/stream", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		cancel()
		t.Fatal(err)
	}
	ch := make(chan sseEvent, 64)
	go func() {
		defer close(ch)
		defer res.Body.Close()
		sc := bufio.NewScanner(res.Body)
		var cur sseEvent
		for sc.Scan() {
			line := sc.Text()
			switch {
			case strings.HasPrefix(line, "event: "):
				cur.Event = line[7:]
			case strings.HasPrefix(line, "data: "):
				cur.Data = line[6:]
			case line == "":
				if cur.Event != "" {
					select {
					case ch <- cur:
					default:
					}
				}
				cur = sseEvent{}
			}
		}
	}()
	return ch, cancel, res
}

func next(t *testing.T, ch <-chan sseEvent, want string) sseEvent {
	t.Helper()
	deadline := time.After(3 * time.Second)
	for {
		select {
		case ev, ok := <-ch:
			if !ok {
				t.Fatalf("스트림이 %q 전에 닫혔다", want)
			}
			if ev.Event == want {
				return ev
			}
		case <-deadline:
			t.Fatalf("%q 를 못 받았다", want)
		}
	}
}

// ── G-N1 · G-N2 ─────────────────────────────────────────────────────

func TestPublishReachesStream(t *testing.T) {
	r := newRig(t)
	ch, cancel, _ := r.open(t, mint(t, purposeNotify, "user-1"))
	defer cancel()
	next(t, ch, "ready") // 연결 확인까지 기다려야 발행이 구독을 만난다

	res := r.signed(t, "POST", "/svc/v1/notify/publish", publishReq{
		NotificationID: "N1", UserIDs: []string{"user-1"},
		Type: "report_ready", Payload: json.RawMessage(`{"report_id":"R9"}`)})
	defer res.Body.Close()
	if res.StatusCode != 202 {
		b, _ := io.ReadAll(res.Body)
		t.Fatalf("발행 %d: %s", res.StatusCode, b)
	}

	ev := next(t, ch, "notification")
	var got hub.Event
	if err := json.Unmarshal([]byte(ev.Data), &got); err != nil {
		t.Fatalf("본문을 못 읽는다: %s", ev.Data)
	}
	if got.ID != "N1" || got.Type != "report_ready" {
		t.Errorf("받은 알림 = %+v", got)
	}
	if !strings.Contains(string(got.Payload), "R9") {
		t.Errorf("payload 가 안 실렸다: %s", got.Payload)
	}

	// I-3 delivered 가 가야 한다
	d := r.waitDeliveries(1)
	if len(d) != 1 {
		t.Fatalf("I-3 %d건", len(d))
	}
	if d[0].Body.Status != "delivered" || d[0].Body.UserID != "user-1" ||
		d[0].Body.NotificationID != "N1" {
		t.Errorf("I-3 본문 = %+v", d[0].Body)
	}
	if d[0].Idem != "notif:N1:user-1:delivered" {
		t.Errorf("I-3 멱등키 = %q", d[0].Idem)
	}
}

// ★ 남에게 새면 안 된다
func TestPublishDoesNotReachOtherUser(t *testing.T) {
	r := newRig(t)
	ch, cancel, _ := r.open(t, mint(t, purposeNotify, "user-2"))
	defer cancel()
	next(t, ch, "ready")

	r.signed(t, "POST", "/svc/v1/notify/publish", publishReq{
		NotificationID: "N1", UserIDs: []string{"user-1"}, Type: "report_ready"}).
		Body.Close()

	select {
	case ev := <-ch:
		if ev.Event == "notification" {
			t.Fatalf("남의 알림을 받았다: %s", ev.Data)
		}
	case <-time.After(300 * time.Millisecond):
	}
}

// 접속한 창이 없으면 no_subscriber 로 알려야 한다.
// 안 알리면 Django 가 "보냈다" 로 알고 미확인 목록에 안 남긴다.
func TestPublishWithNoSubscriber(t *testing.T) {
	r := newRig(t)
	res := r.signed(t, "POST", "/svc/v1/notify/publish", publishReq{
		NotificationID: "N9", UserIDs: []string{"아무도없음"}, Type: "x"})
	defer res.Body.Close()
	if res.StatusCode != 202 {
		t.Fatalf("%d", res.StatusCode)
	}
	d := r.waitDeliveries(1)
	if len(d) != 1 || d[0].Body.Status != "no_subscriber" {
		t.Fatalf("I-3 = %+v", d)
	}
}

// ★ 서명 없이 발행되면 누구나 가짜 알림을 쏜다
func TestPublishRequiresSignature(t *testing.T) {
	r := newRig(t)
	body := []byte(`{"notification_id":"N1","user_ids":["user-1"]}`)
	ts := strconv.FormatInt(time.Now().Unix(), 10)
	old := strconv.FormatInt(time.Now().Add(-10*time.Minute).Unix(), 10)

	for _, c := range []struct {
		name, ts, sig string
		want          int
	}{
		{"서명 없음", "", "", 401},
		{"서명 틀림", ts, "deadbeef", 401},
		{"타임스탬프만", ts, "", 401},
		// 가로챈 요청을 나중에 다시 보내는 것을 막는다
		{"오래된 서명", old, callback.Sign([]byte(cbsec), old, body), 401},
		{"정상", ts, callback.Sign([]byte(cbsec), ts, body), 202},
	} {
		t.Run(c.name, func(t *testing.T) {
			req, _ := http.NewRequest("POST",
				r.srv.URL+"/svc/v1/notify/publish", bytes.NewReader(body))
			if c.ts != "" {
				req.Header.Set("X-Timestamp", c.ts)
			}
			if c.sig != "" {
				req.Header.Set("X-Signature", c.sig)
			}
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != c.want {
				b, _ := io.ReadAll(res.Body)
				t.Errorf("%d (%d 여야 한다): %s", res.StatusCode, c.want, b)
			}
		})
	}
}

// ── 티켓 ────────────────────────────────────────────────────────────

func TestStreamRequiresNotifyTicket(t *testing.T) {
	r := newRig(t)
	for _, c := range []struct {
		name, tok string
		want      int
	}{
		{"없음", "", 401},
		{"용도 다름", mint(t, "download", "user-1"), 403},
		{"범위 없음", mint(t, purposeNotify, ""), 403},
	} {
		t.Run(c.name, func(t *testing.T) {
			req, _ := http.NewRequest("GET", r.srv.URL+"/svc/v1/notify/stream", nil)
			if c.tok != "" {
				req.Header.Set("Authorization", "Bearer "+c.tok)
			}
			res, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Fatal(err)
			}
			defer res.Body.Close()
			if res.StatusCode != c.want {
				t.Errorf("%d (%d 여야 한다)", res.StatusCode, c.want)
			}
		})
	}
}

// ── G-N3  확인 ──────────────────────────────────────────────────────

func TestAckSendsI3Read(t *testing.T) {
	r := newRig(t)
	body, _ := json.Marshal(map[string]any{"notification_ids": []string{"N1", "N2"}})
	req, _ := http.NewRequest("POST", r.srv.URL+"/svc/v1/notify/ack",
		bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+mint(t, purposeNotify, "user-1"))
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		b, _ := io.ReadAll(res.Body)
		t.Fatalf("%d: %s", res.StatusCode, b)
	}
	d := r.deliveries()
	if len(d) != 2 {
		t.Fatalf("I-3 %d건 (2건이어야 한다)", len(d))
	}
	for _, x := range d {
		if x.Body.Status != "read" {
			t.Errorf("status = %q", x.Body.Status)
		}
	}
	// delivered 와 read 가 같은 멱등키를 쓰면 나중 것이 걸러진다
	if d[0].Idem != "notif:N1:user-1:read" {
		t.Errorf("멱등키 = %q", d[0].Idem)
	}
}

// ★ I-3 이 실패했는데 200 을 내면 화면은 읽음, DB 는 미확인이 된다.
// 그러면 그 알림이 계속 다시 뜬다.
func TestAckFailsWhenCallbackFails(t *testing.T) {
	r := newRig(t)
	r.mu.Lock()
	r.code = 500
	r.mu.Unlock()

	body, _ := json.Marshal(map[string]any{"notification_ids": []string{"N1"}})
	req, _ := http.NewRequest("POST", r.srv.URL+"/svc/v1/notify/ack",
		bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+mint(t, purposeNotify, "user-1"))
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != 502 {
		t.Fatalf("I-3 이 실패했는데 %d 를 냈다", res.StatusCode)
	}
}

func TestAckRejectsEmpty(t *testing.T) {
	r := newRig(t)
	req, _ := http.NewRequest("POST", r.srv.URL+"/svc/v1/notify/ack",
		strings.NewReader(`{"notification_ids":[]}`))
	req.Header.Set("Authorization", "Bearer "+mint(t, purposeNotify, "user-1"))
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != 400 {
		t.Errorf("%d", res.StatusCode)
	}
}

// ── 밀림 ────────────────────────────────────────────────────────────

// 버퍼가 넘치면 resync 를 보내야 한다. 안 보내면 알림이 조용히 사라지고
// 사용자는 판독이 끝난 줄 모른다.
func TestOverflowSendsResync(t *testing.T) {
	r := newRig(t)
	tok := mint(t, purposeNotify, "user-1")
	ch, cancel, _ := r.open(t, tok)
	defer cancel()
	next(t, ch, "ready")

	// 버퍼는 4다. HTTP 로 한 건씩 보내면 그 왕복 시간에 화면이 다 읽어
	// 버려서 절대 안 넘친다. 스트림이 못 따라오게 하려면 왕복 없이
	// 빽빽하게 밀어 넣어야 한다 — 발행 자체를 직접 부른다.
	// (발행 경로는 TestPublishReachesStream 이 HTTP 로 확인한다)
	for i := 0; i < 3000; i++ {
		r.s.h.Publish("user-1", hub.Event{
			ID: fmt.Sprintf("N%d", i), Type: "report_ready"})
	}
	next(t, ch, "resync")
}

func TestHealth(t *testing.T) {
	r := newRig(t)
	res, err := http.Get(r.srv.URL + "/svc/v1/notify/health")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		t.Fatalf("%d", res.StatusCode)
	}
}

// 구독 현황은 아무나 못 본다 — 누가 접속해 있는지가 새면 안 된다
func TestStatsRequiresSignature(t *testing.T) {
	r := newRig(t)
	res, err := http.Get(r.srv.URL + "/svc/v1/notify/stats")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	if res.StatusCode != 401 {
		t.Errorf("서명 없이 %d 를 냈다", res.StatusCode)
	}
	res2 := r.signed(t, "GET", "/svc/v1/notify/stats", nil)
	defer res2.Body.Close()
	if res2.StatusCode != 200 {
		t.Errorf("서명했는데 %d", res2.StatusCode)
	}
}

// 연결이 끊기면 구독이 정리돼야 한다. 안 그러면 연결마다 메모리가 샌다.
func TestDisconnectCleansUp(t *testing.T) {
	r := newRig(t)
	ch, cancel, _ := r.open(t, mint(t, purposeNotify, "user-1"))
	next(t, ch, "ready")
	if _, conns := r.s.h.Stats(); conns != 1 {
		t.Fatalf("연결 %d개", conns)
	}
	cancel()
	for i := 0; i < 100; i++ {
		if _, conns := r.s.h.Stats(); conns == 0 {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	_, conns := r.s.h.Stats()
	t.Errorf("끊긴 뒤에도 연결 %d개가 남았다", conns)
}
