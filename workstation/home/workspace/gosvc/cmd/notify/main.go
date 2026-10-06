// notify — 실시간 알림. 명세 19-3 G-N1~G-N5.
//
// ⚠⚠ 경로 이름은 **내가 정한 것이다.** 명세 19-3 의 표에 적힌 G-N1~G-N5 의
//
//	정확한 경로를 확인하지 못했다. 아래는 나머지 경로 규칙(/svc/v1/...)에
//	맞춘 추정이고, 팀 확인 뒤 바꿔야 한다. 바꿀 곳은 routes() 한 군데다.
//
//	G-N1  GET  /svc/v1/notify/stream        SSE 구독 (티켓)
//	G-N2  POST /svc/v1/notify/publish       Django → Go 발행 (내부 서명)
//	G-N3  POST /svc/v1/notify/ack           확인 처리 → I-3 (티켓)
//	G-N4  GET  /svc/v1/notify/health
//	G-N5  GET  /svc/v1/notify/stats         구독 현황 (내부 서명)
//
// 지켜야 하는 것
//
//	· Go 는 알림을 **만들지 않는다.** Django 가 만들어 발행하고 Go 는 흘린다
//	· Go 는 Postgres 에 직접 안 쓴다. 전달 결과는 I-3 콜백으로만
//	· 발행은 절대 막히면 안 된다 — 느린 화면 하나가 전원을 막으면 안 된다
package main

import (
	"context"
	"crypto/hmac"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/httpx"
	"cdss/gosvc/internal/hub"
	"cdss/gosvc/internal/ticket"
)

const purposeNotify = "notify"

type svc struct {
	h      *hub.Hub
	cb     *callback.Client
	tv     *ticket.Verifier
	secret []byte // Django 가 발행 요청에 서명하는 키
}

func main() {
	addr := env("NOTIFY_ADDR", ":8092")
	tkey, cbBase, cbSec := os.Getenv("TICKET_KEY"),
		os.Getenv("CALLBACK_BASE"), os.Getenv("CALLBACK_SECRET")
	if tkey == "" || cbBase == "" || cbSec == "" {
		log.Fatal("TICKET_KEY · CALLBACK_BASE · CALLBACK_SECRET 이 필요하다")
	}
	s := &svc{
		h: hub.New(atoi(env("NOTIFY_BUFFER", "32"))),
		cb: callback.New(cbBase, []byte(cbSec),
			os.Getenv("CALLBACK_CERT"), os.Getenv("CALLBACK_KEY"), 4),
		tv:     ticket.NewVerifier([]byte(tkey)),
		secret: []byte(cbSec), // 발행 서명도 같은 키를 쓴다
	}
	log.Printf("notify %s", addr)
	log.Fatal((&http.Server{Addr: addr,
		Handler:           httpx.CORS(s.routes(), os.Getenv("CORS_ORIGINS")),
		ReadHeaderTimeout: 10 * time.Second}).ListenAndServe())
}

func (s *svc) routes() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /svc/v1/notify/stream", s.stream)    // G-N1
	mux.HandleFunc("POST /svc/v1/notify/publish", s.publish) // G-N2
	mux.HandleFunc("POST /svc/v1/notify/ack", s.ack)         // G-N3
	mux.HandleFunc("GET /svc/v1/notify/health", s.health)    // G-N4
	mux.HandleFunc("GET /svc/v1/notify/stats", s.stats)      // G-N5
	return mux
}

// ── G-N1  구독 ──────────────────────────────────────────────────────
//
// 티켓의 scope_id 를 사용자 식별자로 쓴다. Django 가 로그인한 사용자에게만
// 티켓을 내주므로, 여기서 사용자 판정을 따로 하지 않는다 (명세 19-1).
func (s *svc) stream(w http.ResponseWriter, r *http.Request) {
	cl, err := s.tv.Verify(bearer(r))
	if err != nil {
		fail(w, 401, ticketCode(err), err.Error())
		return
	}
	if cl.Purpose != purposeNotify || cl.ScopeID == "" {
		fail(w, 403, "TICKET_SCOPE_MISMATCH", "notify 티켓이 아니다")
		return
	}
	fl, ok := w.(http.Flusher)
	if !ok {
		fail(w, 500, "NO_STREAMING", "이 서버는 스트리밍을 못 한다")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Accel-Buffering", "no") // nginx 버퍼링 방지
	w.WriteHeader(http.StatusOK)

	sub, unsub := s.h.Subscribe(cl.ScopeID)
	defer unsub()

	// 연 직후 한 번 알린다. 화면이 "연결됐다" 를 알아야 재연결 로직을 멈춘다.
	sse(w, fl, "ready", map[string]any{"user_id": cl.ScopeID})

	// 심박. 없으면 중간의 프록시가 조용한 연결을 끊는데, 화면은 끊긴 줄
	// 모르고 계속 기다린다. 주석 줄(: )은 SSE 에서 무시되므로 안전하다.
	tick := time.NewTicker(20 * time.Second)
	defer tick.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-tick.C:
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		case <-sub.Done():
			return
		case ev := <-sub.C:
			// 버퍼가 넘쳐 알림을 잃었으면 먼저 알린다.
			// 개별 알림은 잃되 **잃었다는 사실은 안 잃는다.**
			if sub.Lagged() {
				sse(w, fl, "resync", map[string]any{
					"reason": "buffer_overflow",
					"note":   "알림을 일부 놓쳤다. 목록을 다시 받아 갈 것",
				})
			}
			sse(w, fl, "notification", ev)
			s.report(ev.ID, cl.ScopeID, "delivered")
		}
	}
}

// ── G-N2  발행 ──────────────────────────────────────────────────────
//
// Django 만 부른다. 티켓이 아니라 콜백과 같은 HMAC 서명으로 막는다 —
// 티켓은 사용자용이고 이건 서버 간 호출이다.
type publishReq struct {
	NotificationID string          `json:"notification_id"`
	UserIDs        []string        `json:"user_ids"`
	Type           string          `json:"type"`
	Payload        json.RawMessage `json:"payload,omitempty"`
}

func (s *svc) publish(w http.ResponseWriter, r *http.Request) {
	body, ok := s.readSigned(w, r)
	if !ok {
		return
	}
	var req publishReq
	if err := json.Unmarshal(body, &req); err != nil {
		fail(w, 400, "BAD_REQUEST", err.Error())
		return
	}
	if req.NotificationID == "" || len(req.UserIDs) == 0 {
		fail(w, 400, "BAD_REQUEST", "notification_id 와 user_ids 가 필요하다")
		return
	}
	ev := hub.Event{ID: req.NotificationID, Type: req.Type,
		Payload: req.Payload, CreatedAt: time.Now().UTC()}

	out := map[string]int{}
	for _, u := range req.UserIDs {
		n := s.h.Publish(u, ev)
		out[u] = n
		if n == 0 {
			// 접속한 창이 없다. 실패가 아니다 — 나중에 목록으로 받아 간다.
			// 다만 Django 가 "안 갔다" 를 알아야 미확인으로 남길 수 있다.
			s.report(ev.ID, u, "no_subscriber")
		}
	}
	log.Printf("[G-N2] notif=%s type=%s 대상 %d명", req.NotificationID,
		req.Type, len(req.UserIDs))
	writeJSON(w, 202, map[string]any{
		"notification_id": req.NotificationID, "delivered": out,
	})
}

// ── G-N3  확인 ──────────────────────────────────────────────────────
func (s *svc) ack(w http.ResponseWriter, r *http.Request) {
	cl, err := s.tv.Verify(bearer(r))
	if err != nil {
		fail(w, 401, ticketCode(err), err.Error())
		return
	}
	if cl.Purpose != purposeNotify || cl.ScopeID == "" {
		fail(w, 403, "TICKET_SCOPE_MISMATCH", "notify 티켓이 아니다")
		return
	}
	var req struct {
		NotificationIDs []string `json:"notification_ids"`
	}
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<16)).
		Decode(&req); err != nil {
		fail(w, 400, "BAD_REQUEST", err.Error())
		return
	}
	if len(req.NotificationIDs) == 0 {
		fail(w, 400, "BAD_REQUEST", "notification_ids 가 비었다")
		return
	}
	// I-3 은 **동기로** 보낸다. 여기서 200 을 냈는데 Django 가 못 받으면
	// 화면에서는 읽음인데 DB 에서는 미확인이라 알림이 다시 뜬다.
	ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
	defer cancel()
	failed := []string{}
	for _, id := range req.NotificationIDs {
		if err := s.cb.PostNotificationDelivery(ctx,
			callback.NotificationDelivery{NotificationID: id, UserID: cl.ScopeID,
				Channel: "sse", Status: "read",
				At: time.Now().UTC().Format(time.RFC3339)}); err != nil {
			failed = append(failed, id)
		}
	}
	if len(failed) > 0 {
		log.Printf("[G-N3] ✗ I-3 실패 user=%s %v", cl.ScopeID, failed)
		writeJSON(w, 502, map[string]any{
			"code": "CALLBACK_FAILED", "failed": failed,
			"detail": "확인 처리를 Django 에 반영하지 못했다",
		})
		return
	}
	writeJSON(w, 200, map[string]any{"acked": req.NotificationIDs})
}

// ── G-N4 · G-N5 ─────────────────────────────────────────────────────
func (s *svc) health(w http.ResponseWriter, r *http.Request) {
	users, conns := s.h.Stats()
	writeJSON(w, 200, map[string]any{"ok": true, "users": users, "connections": conns})
}

func (s *svc) stats(w http.ResponseWriter, r *http.Request) {
	if _, ok := s.readSigned(w, r); !ok {
		return
	}
	users, conns := s.h.Stats()
	writeJSON(w, 200, map[string]any{
		"users": users, "connections": conns,
		"published": s.h.Published.Load(),
		"delivered": s.h.Delivered.Load(),
		// lagging 이 0 이 아니면 버퍼를 키우거나 화면이 너무 느린 것이다
		"lagging": s.h.Lagging.Load(),
	})
}

// ── 잡동사니 ────────────────────────────────────────────────────────

// report — I-3 을 배경으로 보낸다.
//
// 전달 보고 때문에 스트림이 멈추면 안 된다. 한 사용자가 알림 20개를 받는
// 동안 콜백 20번을 동기로 기다리면 화면이 그만큼 늦게 받는다.
func (s *svc) report(notifID, userID, status string) {
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if err := s.cb.PostNotificationDelivery(ctx,
			callback.NotificationDelivery{NotificationID: notifID, UserID: userID,
				Channel: "sse", Status: status,
				At: time.Now().UTC().Format(time.RFC3339)}); err != nil {
			log.Printf("[notify] I-3(%s) 실패 notif=%s user=%s: %v",
				status, notifID, userID, err)
		}
	}()
}

// readSigned — 서버 간 호출을 콜백과 같은 방식으로 검증한다.
// HMAC-SHA256(ts + "." + body), 상수 시간 비교.
func (s *svc) readSigned(w http.ResponseWriter, r *http.Request) ([]byte, bool) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
	if err != nil {
		fail(w, 400, "BAD_REQUEST", "본문을 못 읽었다")
		return nil, false
	}
	ts := r.Header.Get("X-Timestamp")
	sig := r.Header.Get("X-Signature")
	if ts == "" || sig == "" {
		fail(w, 401, "SIGNATURE_MISSING", "X-Timestamp · X-Signature 가 필요하다")
		return nil, false
	}
	// 오래된 서명은 거부한다. 없으면 가로챈 요청을 언제든 다시 보낼 수 있다.
	if n, err := strconv.ParseInt(ts, 10, 64); err != nil ||
		absSec(time.Now().Unix()-n) > 300 {
		fail(w, 401, "SIGNATURE_STALE", "타임스탬프가 5분을 벗어났다")
		return nil, false
	}
	if !hmac.Equal([]byte(callback.Sign(s.secret, ts, body)), []byte(sig)) {
		fail(w, 401, "SIGNATURE_INVALID", "서명이 맞지 않는다")
		return nil, false
	}
	return body, true
}

func absSec(v int64) int64 {
	if v < 0 {
		return -v
	}
	return v
}

func ticketCode(err error) string {
	switch {
	case errors.Is(err, ticket.ErrReplayed):
		return "TICKET_REPLAYED"
	case errors.Is(err, ticket.ErrSignature), errors.Is(err, ticket.ErrMalformed):
		return "TICKET_INVALID"
	}
	return "TICKET_EXPIRED"
}

func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func atoi(s string) int { n, _ := strconv.Atoi(s); return n }

func bearer(r *http.Request) string {
	if h := r.Header.Get("Authorization"); strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return r.Header.Get("X-Ticket")
}

func sse(w http.ResponseWriter, fl http.Flusher, event string, v any) {
	b, _ := json.Marshal(v)
	fmt.Fprintf(w, "event: %s\ndata: %s\n\n", event, b)
	fl.Flush()
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, code int, status, detail string) {
	writeJSON(w, code, map[string]string{"code": status, "detail": detail})
}
