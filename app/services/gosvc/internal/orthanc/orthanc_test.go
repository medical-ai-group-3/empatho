package orthanc

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// ⚠ 이 시험은 **가짜 서버**를 상대한다. 진짜 Orthanc 로는 안 돌려봤다
//
//	(인스턴스가 없다). 확인하는 것은 우리 쪽 처리 — 본문을 그대로 보내는가,
//	인증을 붙이는가, 중복을 실패로 취급하지 않는가 — 뿐이다.
//	Orthanc 가 정말 이렇게 답하는지는 실물에 붙여서 확인해야 한다.

func fake(t *testing.T, h http.HandlerFunc) *Client {
	t.Helper()
	srv := httptest.NewServer(h)
	t.Cleanup(srv.Close)
	return New(srv.URL, "orthanc", "pw")
}

func TestStoreSendsBodyAndAuth(t *testing.T) {
	var got []byte
	var ct, user, pass string
	var ok bool
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/instances" {
			t.Errorf("경로 = %s", r.URL.Path)
		}
		got, _ = io.ReadAll(r.Body)
		ct = r.Header.Get("Content-Type")
		user, pass, ok = r.BasicAuth()
		w.Write([]byte(`{"ID":"abc123","ParentStudy":"st1","Status":"Success"}`))
	})

	res, err := c.Store(context.Background(), strings.NewReader("DICM원본바이트"))
	if err != nil {
		t.Fatalf("%v", err)
	}
	if string(got) != "DICM원본바이트" {
		t.Errorf("본문이 바뀌었다: %q", got)
	}
	if ct != "application/dicom" {
		t.Errorf("Content-Type = %q", ct)
	}
	if !ok || user != "orthanc" || pass != "pw" {
		t.Errorf("기본 인증이 안 붙었다: %v %q", ok, user)
	}
	if res.ID != "abc123" || res.ParentStudy != "st1" {
		t.Errorf("응답 = %+v", res)
	}
}

// 409 는 "이미 있다" 다. 재시도가 이걸 만드는 것은 정상이므로
// 실패로 취급하면 안 된다 — 취급하면 멀쩡한 업로드가 오류로 보고된다.
func TestStoreDuplicate409(t *testing.T) {
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(409)
	})
	_, err := c.Store(context.Background(), strings.NewReader("x"))
	if !errors.Is(err, ErrDuplicate) {
		t.Fatalf("409 를 %v 로 봤다", err)
	}
}

// Orthanc 는 이미 있는 인스턴스에 **200 + Status:AlreadyStored** 를 내기도 한다.
// 상태 코드만 보면 성공으로 지나가서 중복을 못 잡는다.
func TestStoreAlreadyStored200(t *testing.T) {
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"ID":"same1","Status":"AlreadyStored"}`))
	})
	res, err := c.Store(context.Background(), strings.NewReader("x"))
	if !errors.Is(err, ErrDuplicate) {
		t.Fatalf("AlreadyStored 를 %v 로 봤다", err)
	}
	// 중복이어도 식별자는 돌려줘야 한다. I-2 에 실어야 하기 때문이다.
	if res == nil || res.ID != "same1" {
		t.Errorf("중복인데 식별자를 안 줬다: %+v", res)
	}
}

func TestStoreServerError(t *testing.T) {
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(500)
		w.Write([]byte("boom"))
	})
	_, err := c.Store(context.Background(), strings.NewReader("x"))
	if err == nil || errors.Is(err, ErrDuplicate) {
		t.Fatalf("500 을 %v 로 봤다", err)
	}
	if !strings.Contains(err.Error(), "500") {
		t.Errorf("오류에 상태 코드가 없다: %v", err)
	}
}

// 응답이 JSON 이 아니면 오류여야 한다. 조용히 빈 식별자로 넘어가면
// I-2 에 빈 orthanc_instance_id 가 실려 나중에 조회가 안 된다.
func TestStoreBadJSON(t *testing.T) {
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("<html>프록시가 가로챘다</html>"))
	})
	if _, err := c.Store(context.Background(), strings.NewReader("x")); err == nil {
		t.Fatal("JSON 이 아닌 응답을 성공으로 봤다")
	}
}

// 인증 정보가 없으면 헤더를 안 붙여야 한다 (인증 꺼둔 Orthanc)
func TestStoreNoAuth(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, _, ok := r.BasicAuth(); ok {
			t.Error("인증 정보가 없는데 헤더를 붙였다")
		}
		w.Write([]byte(`{"ID":"a","Status":"Success"}`))
	}))
	defer srv.Close()
	if _, err := New(srv.URL, "", "").Store(context.Background(),
		strings.NewReader("x")); err != nil {
		t.Fatal(err)
	}
}

// URL 이 비면 nil 이어야 한다. 호출부가 nil 을 보고 전송을 건너뛴다.
func TestNewWithoutURL(t *testing.T) {
	if c := New("", "", ""); c != nil {
		t.Errorf("설정이 없는데 클라이언트를 만들었다: %+v", c)
	}
}

func TestHealthy(t *testing.T) {
	c := fake(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/system" {
			t.Errorf("경로 = %s", r.URL.Path)
		}
	})
	if err := c.Healthy(context.Background()); err != nil {
		t.Errorf("%v", err)
	}
}
