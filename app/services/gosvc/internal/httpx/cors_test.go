package httpx

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func inner() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Range", "bytes 0-9/100")
		w.WriteHeader(200)
		w.Write([]byte("ok"))
	})
}

func do(h http.Handler, method, origin string, pre bool) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, "/svc/v1/files/x", nil)
	if origin != "" {
		r.Header.Set("Origin", origin)
	}
	if pre {
		r.Header.Set("Access-Control-Request-Method", "PUT")
		r.Header.Set("Access-Control-Request-Headers", "authorization")
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

// 설정이 비면 아무것도 안 해야 한다 — 리버스 프록시 구성에서 그렇다.
func TestDisabledWhenEmpty(t *testing.T) {
	h := CORS(inner(), "")
	w := do(h, "GET", "http://localhost:3000", false)
	if w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Error("설정이 비었는데 헤더를 붙였다")
	}
	if w.Code != 200 {
		t.Errorf("본 요청이 %d", w.Code)
	}
}

// ★ 이게 없으면 브라우저 업로드가 시작조차 안 된다.
func TestPreflightAllowed(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")
	w := do(h, "OPTIONS", "http://localhost:3000", true)

	if w.Code != http.StatusNoContent {
		t.Fatalf("사전 요청이 %d (204 여야 한다)", w.Code)
	}
	if got := w.Header().Get("Access-Control-Allow-Origin"); got != "http://localhost:3000" {
		t.Errorf("Allow-Origin = %q", got)
	}
	// Authorization 이 허용돼야 티켓을 보낼 수 있다
	if !strings.Contains(w.Header().Get("Access-Control-Allow-Headers"), "Authorization") {
		t.Errorf("Authorization 이 안 열렸다: %q",
			w.Header().Get("Access-Control-Allow-Headers"))
	}
	// 청크 업로드는 PUT 이다
	if !strings.Contains(w.Header().Get("Access-Control-Allow-Methods"), "PUT") {
		t.Errorf("PUT 이 안 열렸다: %q", w.Header().Get("Access-Control-Allow-Methods"))
	}
	// Range 를 못 보내면 뷰어가 부분 요청을 못 한다
	if !strings.Contains(w.Header().Get("Access-Control-Allow-Headers"), "Range") {
		t.Errorf("Range 가 안 열렸다")
	}
	if w.Header().Get("Access-Control-Max-Age") == "" {
		t.Error("Max-Age 가 없다 — 조각마다 사전 요청이 붙어 왕복이 두 배가 된다")
	}
}

// 허용 목록 밖의 출처는 헤더를 받으면 안 된다
func TestOriginNotAllowed(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")

	w := do(h, "GET", "http://evil.example", false)
	if w.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Error("허용 안 한 출처에 헤더를 붙였다")
	}
	w = do(h, "OPTIONS", "http://evil.example", true)
	if w.Code != http.StatusForbidden {
		t.Errorf("허용 안 한 출처의 사전 요청이 %d", w.Code)
	}
}

// ★ "*" 를 쓰면 안 되는 이유 — Authorization 을 붙인 요청에서 브라우저가
// "*" 를 거부한다. 반드시 실제 출처를 되돌려줘야 한다.
func TestEchoesOriginNotWildcard(t *testing.T) {
	h := CORS(inner(), "*")
	w := do(h, "GET", "http://localhost:5173", false)
	got := w.Header().Get("Access-Control-Allow-Origin")
	if got == "*" {
		t.Fatal("'*' 를 그대로 돌려줬다 — 티켓을 붙인 요청이 전부 막힌다")
	}
	if got != "http://localhost:5173" {
		t.Errorf("Allow-Origin = %q", got)
	}
}

// 교차 출처에서는 응답 헤더가 기본으로 가려진다. 열어 줘야 뷰어가
// Content-Range 를 읽어 조각을 맞춘다.
func TestExposesRangeHeaders(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")
	w := do(h, "GET", "http://localhost:3000", false)
	e := w.Header().Get("Access-Control-Expose-Headers")
	for _, want := range []string{"Content-Range", "Accept-Ranges", "ETag"} {
		if !strings.Contains(e, want) {
			t.Errorf("%s 가 안 열렸다: %q", want, e)
		}
	}
}

// 출처마다 응답이 다르므로 캐시가 섞이면 안 된다
func TestVary(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")
	w := do(h, "GET", "http://localhost:3000", false)
	if !strings.Contains(w.Header().Get("Vary"), "Origin") {
		t.Error("Vary: Origin 이 없다 — 캐시가 다른 출처의 응답을 돌려줄 수 있다")
	}
}

// 끝의 / 가 붙어 와도 같은 출처로 봐야 한다
func TestTrailingSlash(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000/")
	w := do(h, "GET", "http://localhost:3000", false)
	if w.Header().Get("Access-Control-Allow-Origin") == "" {
		t.Error("끝의 / 때문에 같은 출처를 못 알아봤다")
	}
}

// 여러 출처
func TestMultipleOrigins(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000, https://cdss.example.org")
	for _, o := range []string{"http://localhost:3000", "https://cdss.example.org"} {
		if do(h, "GET", o, false).Header().Get("Access-Control-Allow-Origin") != o {
			t.Errorf("%s 가 허용 안 됐다", o)
		}
	}
}

// Origin 이 없는 요청(curl · 서버 간 호출)은 그대로 통과해야 한다
func TestNoOriginPassesThrough(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")
	w := do(h, "GET", "", false)
	if w.Code != 200 || w.Body.String() != "ok" {
		t.Errorf("Origin 없는 요청이 막혔다: %d", w.Code)
	}
}

// OPTIONS 지만 사전 요청이 아닌 것은 그냥 넘겨야 한다
func TestPlainOptionsPassesThrough(t *testing.T) {
	h := CORS(inner(), "http://localhost:3000")
	w := do(h, "OPTIONS", "http://localhost:3000", false)
	if w.Code != 200 {
		t.Errorf("일반 OPTIONS 가 %d", w.Code)
	}
}
