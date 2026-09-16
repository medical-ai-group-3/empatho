package report

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// fake — 리포트 서버 흉내. 받은 것을 그대로 붙잡아 둔다.
type fake struct {
	srv      *httptest.Server
	path     string
	gotReq   Request
	status   int
	respBody string
}

func newFake(t *testing.T) *fake {
	t.Helper()
	f := &fake{status: 200}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(f.status)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		f.path = r.URL.Path
		b, _ := io.ReadAll(r.Body)
		json.Unmarshal(b, &f.gotReq)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(f.status)
		if f.respBody != "" {
			io.WriteString(w, f.respBody)
			return
		}
		io.WriteString(w, `{"소견":"우상방에 종괴가 있다.","안내":[],
			"evidence":["MG-01"],"dropped":[],"fallback":null,
			"prompt_version":"mg-2026-09-02.a"}`)
	})
	f.srv = httptest.NewServer(mux)
	t.Cleanup(f.srv.Close)
	return f
}

func TestNarrate_보내는_모양(t *testing.T) {
	f := newFake(t)
	c := New(f.srv.URL, 5*time.Second)

	res, err := c.Narrate(context.Background(), "mammo", Request{
		Result:   json.RawMessage(`{"lesion_found":true}`),
		Evidence: []string{"MG-01", "MG-02"},
	})
	if err != nil {
		t.Fatalf("호출 실패: %v", err)
	}
	if f.path != "/report/mammo" {
		t.Errorf("경로가 /report/mammo 여야 한다. got=%s", f.path)
	}
	if len(f.gotReq.Evidence) != 2 || f.gotReq.Evidence[0] != "MG-01" {
		t.Errorf("근거 ID 목록이 그대로 가야 한다. got=%v", f.gotReq.Evidence)
	}
	// 좌표·화소 간격은 애초에 보낼 칸이 없다. Request 에 그 필드가
	// 생기면 이 시험이 아니라 설계 합의를 다시 봐야 한다.
	if string(f.gotReq.Result) != `{"lesion_found":true}` {
		t.Errorf("판독 결과가 그대로 가야 한다. got=%s", f.gotReq.Result)
	}
	if res.Text != "우상방에 종괴가 있다." {
		t.Errorf("소견을 못 읽었다. got=%q", res.Text)
	}
	if res.PromptVersion != "mg-2026-09-02.a" {
		t.Errorf("prompt_version 을 못 읽었다. got=%q", res.PromptVersion)
	}
}

// 병변이 없으면 근거 목록이 빈다. 그때 null 이 아니라 [] 로 나가야 한다 —
// "근거 없음" 과 "그런 칸이 없음" 은 받는 쪽에서 다르게 읽힌다.
func TestNarrate_근거가_비면_빈배열(t *testing.T) {
	f := newFake(t)
	c := New(f.srv.URL, 5*time.Second)

	if _, err := c.Narrate(context.Background(), "mammo", Request{
		Result: json.RawMessage(`{"lesion_found":false}`),
	}); err != nil {
		t.Fatalf("호출 실패: %v", err)
	}
	if f.gotReq.Evidence == nil {
		t.Fatal("evidence 가 null 로 갔다. 빈 배열이어야 한다")
	}
	if len(f.gotReq.Evidence) != 0 {
		t.Errorf("빈 배열이어야 한다. got=%v", f.gotReq.Evidence)
	}
}

func TestNarrate_한국어_키를_읽는다(t *testing.T) {
	f := newFake(t)
	f.respBody = `{"소견":"소견 없음","안내":[{"id":"MG-N01","text":"주의"}],
		"evidence":[],"dropped":[{"sentence":"버려진 문장","reason":"근거 없음"}],
		"fallback":"숫자 검사 실패","prompt_version":"v1"}`
	c := New(f.srv.URL, 5*time.Second)

	res, err := c.Narrate(context.Background(), "mammo", Request{})
	if err != nil {
		t.Fatalf("호출 실패: %v", err)
	}
	if len(res.Notes) != 1 || res.Notes[0].ID != "MG-N01" {
		t.Errorf("안내 문구를 못 읽었다. got=%+v", res.Notes)
	}
	if len(res.Dropped) != 1 || res.Dropped[0].Reason != "근거 없음" {
		t.Errorf("dropped 를 못 읽었다. got=%+v", res.Dropped)
	}
	if res.Fallback == nil || *res.Fallback != "숫자 검사 실패" {
		t.Errorf("fallback 을 못 읽었다. got=%v", res.Fallback)
	}
}

// fallback 은 포인터다. null 과 빈 문자열을 구분해야 하기 때문이다 —
// null 은 "되돌리지 않았다", "" 는 "되돌렸는데 사유가 비었다" 다.
func TestNarrate_fallback_null(t *testing.T) {
	f := newFake(t)
	c := New(f.srv.URL, 5*time.Second)
	res, err := c.Narrate(context.Background(), "mammo", Request{})
	if err != nil {
		t.Fatalf("호출 실패: %v", err)
	}
	if res.Fallback != nil {
		t.Errorf("fallback 이 null 이면 nil 이어야 한다. got=%v", *res.Fallback)
	}
}

// 소켓 이름은 그대로 주소에 들어간다. 경로를 벗어나는 값은 막아야 한다.
func TestNarrate_소켓이름_검사(t *testing.T) {
	f := newFake(t)
	c := New(f.srv.URL, 5*time.Second)

	bad := []string{
		"../health", // 다른 경로로 새어 나간다
		"../../etc/passwd",
		"mammo/../admin",
		"MAMMO", // 대문자는 안 받는다 — 이름이 갈리면 대조가 안 된다
		"",
		"mammo?x=1",
		"mammo#frag",
		"a b",
		strings.Repeat("a", 33),
	}
	for _, s := range bad {
		if _, err := c.Narrate(context.Background(), s, Request{}); !errors.Is(err, ErrBadSocket) {
			t.Errorf("소켓 %q 는 막아야 한다. err=%v", s, err)
		}
	}
	for _, s := range []string{"mammo", "us", "mri", "pathology", "socket_1", "mg-2"} {
		if _, err := c.Narrate(context.Background(), s, Request{}); err != nil {
			t.Errorf("소켓 %q 는 통과해야 한다. err=%v", s, err)
		}
	}
}

// 터널이 안 떠 있을 때가 가장 흔한 실패다. 그때 무엇이 문제인지
// 오류만 보고 알 수 있어야 한다.
func TestNarrate_안_닿으면_ErrUnreachable(t *testing.T) {
	// 포트 1 은 열려 있을 리 없다.
	c := New("http://127.0.0.1:1", 2*time.Second)
	_, err := c.Narrate(context.Background(), "mammo", Request{})
	if !errors.Is(err, ErrUnreachable) {
		t.Fatalf("ErrUnreachable 이어야 한다. got=%v", err)
	}
	if !strings.Contains(err.Error(), "127.0.0.1:1") {
		t.Errorf("어디에 못 닿았는지 오류에 나와야 한다. got=%v", err)
	}
}

func TestNarrate_오류응답(t *testing.T) {
	f := newFake(t)
	f.status = 500
	f.respBody = "내부 오류"
	c := New(f.srv.URL, 5*time.Second)

	_, err := c.Narrate(context.Background(), "mammo", Request{})
	if !errors.Is(err, ErrUpstream) {
		t.Fatalf("ErrUpstream 이어야 한다. got=%v", err)
	}
	if !strings.Contains(err.Error(), "500") {
		t.Errorf("상태 코드가 오류에 나와야 한다. got=%v", err)
	}
}

func TestNarrate_JSON이_아니면_ErrUpstream(t *testing.T) {
	f := newFake(t)
	f.respBody = "<html>502 Bad Gateway</html>"
	c := New(f.srv.URL, 5*time.Second)

	if _, err := c.Narrate(context.Background(), "mammo", Request{}); !errors.Is(err, ErrUpstream) {
		t.Fatalf("ErrUpstream 이어야 한다. got=%v", err)
	}
}

func TestNarrate_취소되면_멈춘다(t *testing.T) {
	// stop 은 시험이 끝날 때 닫는다. 이게 없으면 핸들러가 영영 안 끝나서
	// httptest.Server.Close 가 그 요청을 기다리다 시험 전체가 멈춘다.
	stop := make(chan struct{})
	slow := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			select {
			case <-r.Context().Done():
			case <-stop:
			}
		}))
	defer slow.Close()
	defer close(stop)

	c := New(slow.URL, time.Minute)
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	start := time.Now()
	if _, err := c.Narrate(ctx, "mammo", Request{}); err == nil {
		t.Fatal("취소됐으면 오류여야 한다")
	}
	if d := time.Since(start); d > 5*time.Second {
		t.Errorf("취소가 안 먹었다. %v 걸렸다", d)
	}
}

func TestHealth(t *testing.T) {
	f := newFake(t)
	c := New(f.srv.URL, 5*time.Second)
	if err := c.Health(context.Background()); err != nil {
		t.Errorf("살아 있으면 nil 이어야 한다. got=%v", err)
	}

	dead := New("http://127.0.0.1:1", 2*time.Second)
	if err := dead.Health(context.Background()); !errors.Is(err, ErrUnreachable) {
		t.Errorf("ErrUnreachable 이어야 한다. got=%v", err)
	}
}

func TestNew_기본_타임아웃(t *testing.T) {
	// 0 을 주면 넉넉한 기본값이 잡혀야 한다. 0 이 그대로 들어가면
	// http.Client 는 "제한 없음" 으로 읽어서 요청이 영영 안 끝난다.
	if c := New("http://x", 0); c.HTTP.Timeout != 2*time.Minute {
		t.Errorf("기본 타임아웃이 2분이어야 한다. got=%v", c.HTTP.Timeout)
	}
	if c := New("http://x/", 0); c.Base != "http://x" {
		t.Errorf("끝의 / 를 떼야 한다. got=%q", c.Base)
	}
}

// 리포트 서버는 모르는 소켓에도 200+abstained 를 준다. 성공으로 넘기면 빈 소견문이 저장된다
func TestNarrate_기권이면_소켓오류(t *testing.T) {
	f := newFake(t)
	f.respBody = `{"socket_id":"mammo", "abstained":true, "reason":"unknown_socket"}`
	c := New(f.srv.URL, 5*time.Second)

	res, err := c.Narrate(context.Background(), "mammo", Request{Result: json.RawMessage(`{}`)})
	if !errors.Is(err, ErrBadSocket) {
		t.Fatalf("기권을 소켓 오류로 돌려야 한다. res=%v err=%v", res, err)
	}
	if !strings.Contains(err.Error(), "unknown_socket") {
		t.Errorf("사유가 오류에 남아야 한다: %v", err)
	}
}
