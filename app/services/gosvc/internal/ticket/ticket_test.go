package ticket

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"testing"
	"time"
)

// 여기서 지키는 것은 하나다 — **읽기만 재사용되고 쓰기는 안 된다.**
//
// 읽기에서 replay 방어를 일부러 뺐기 때문에, 그 경계가 어디까지인지를
// 시험으로 박아 둔다. 나중에 누가 reusable 에 업로드 purpose 를 한 줄
// 더하면 여기서 걸린다.

func mint(t *testing.T, key []byte, purpose, nonce string, ttl time.Duration) string {
	t.Helper()
	hdr := base64.RawURLEncoding.EncodeToString(
		[]byte(`{"alg":"HS256","typ":"JWT"}`))
	body, _ := json.Marshal(Claims{
		Purpose: purpose, ScopeID: "51201", ObjectKeyPrefix: "study/51201/",
		Nonce: nonce, Exp: time.Now().Add(ttl).Unix(),
	})
	pay := base64.RawURLEncoding.EncodeToString(body)
	m := hmac.New(sha256.New, key)
	m.Write([]byte(hdr + "." + pay))
	return hdr + "." + pay + "." +
		base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}

func TestReadTicketIsReusable(t *testing.T) {
	key := []byte("k")
	v := NewVerifier(key, "download", "tile")
	tok := mint(t, key, "tile", "n1", time.Minute)

	// 타일 한 화면이 수십 장을 당긴다. 몇 번을 써도 통해야 한다.
	for i := range 30 {
		if _, err := v.Verify(tok); err != nil {
			t.Fatalf("%d번째에서 거절됐다: %v", i+1, err)
		}
	}
	if len(v.used) != 0 {
		t.Errorf("읽기는 nonce 를 쌓지 않아야 한다. %d개 쌓였다", len(v.used))
	}
}

func TestWriteTicketStaysOneShot(t *testing.T) {
	key := []byte("k")
	v := NewVerifier(key, "download", "tile")

	for _, p := range []string{
		"dicom_upload", "wsi_upload", "derived_upload",
		"report_pdf", "prescription_pdf",
	} {
		tok := mint(t, key, p, "n-"+p, time.Minute)
		if _, err := v.Verify(tok); err != nil {
			t.Fatalf("%s 첫 번째가 거절됐다: %v", p, err)
		}
		if _, err := v.Verify(tok); !errors.Is(err, ErrReplayed) {
			t.Errorf("%s 는 1회용이어야 한다. got=%v", p, err)
		}
	}
}

// reusable 에 안 적힌 purpose 는 읽기처럼 생겼어도 1회용이다.
func TestUnlistedPurposeStaysOneShot(t *testing.T) {
	key := []byte("k")
	v := NewVerifier(key, "tile") // download 는 뺐다
	tok := mint(t, key, "download", "n2", time.Minute)

	if _, err := v.Verify(tok); err != nil {
		t.Fatalf("첫 번째가 거절됐다: %v", err)
	}
	if _, err := v.Verify(tok); !errors.Is(err, ErrReplayed) {
		t.Errorf("목록에 없으면 1회용이어야 한다. got=%v", err)
	}
}

func wants(t *testing.T, v *Verifier, tok string, target error) {
	t.Helper()
	if _, err := v.Verify(tok); !errors.Is(err, target) {
		t.Errorf("%v 를 기대했다. got=%v", target, err)
	}
}

// 재사용을 허용한다고 나머지 검사까지 느슨해지면 안 된다.
func TestReadTicketStillChecksTheRest(t *testing.T) {
	key := []byte("k")
	v := NewVerifier(key, "tile")

	wants(t, v, mint(t, key, "tile", "n3", -time.Minute), ErrExpired)
	wants(t, v, mint(t, []byte("다른키"), "tile", "n4", time.Minute), ErrSignature)

	// nonce 를 소진만 안 할 뿐, 없으면 여전히 거절이다
	wants(t, v, mint(t, key, "tile", "", time.Minute), ErrMalformed)
}
