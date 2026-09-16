// Package ticket — Django 가 서명한 단기 티켓을 검증한다.
//
// 명세 19-1. Go 는 자체 권한 판정을 하지 않는다. 티켓이 유효한지, 요청이
// 티켓 범위 안인지만 본다. 권한 판정은 Django 단독이다.
//
// 형식은 HS256 JWT 다 — Django 쪽이 PyJWT 로 jwt.encode(claims, key,
// algorithm="HS256") 하면 그대로 맞는다. 라이브러리를 안 쓰고 표준
// 라이브러리로 검증한다(의존성 없음).
//
// ⚠ 팀과 맞춰야 하는 것: 서명 키 공유 방식과 클레임 이름.
//
//	아래 Claims 구조는 명세 19-1 표를 그대로 옮긴 것이다.
package ticket

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"time"
)

var (
	ErrMalformed = errors.New("TICKET_MALFORMED")
	ErrSignature = errors.New("TICKET_SIGNATURE")
	ErrExpired   = errors.New("TICKET_EXPIRED")        // 401
	ErrReplayed  = errors.New("TICKET_REPLAYED")       // 401 — nonce 재사용
	ErrScope     = errors.New("TICKET_SCOPE_MISMATCH") // 403
)

// Claims 는 명세 19-1 의 클레임 표와 1:1 이다.
type Claims struct {
	Purpose         string `json:"purpose"` // report_narrative 등
	PatientID       string `json:"patient_id"`
	ScopeID         string `json:"scope_id"` // report_id · study_id ...
	MaxBytes        int64  `json:"max_bytes,omitempty"`
	ContentType     string `json:"content_type,omitempty"`
	ObjectKeyPrefix string `json:"object_key_prefix,omitempty"`
	ObjectName      string `json:"object_name,omitempty"` // 앱이 정하면 이 이름
	Exp             int64  `json:"exp"`
	Nonce           string `json:"nonce"`
}

// Verifier 는 서명·만료·재사용을 본다.
//
// nonce 저장소가 메모리라 프로세스가 하나일 때만 1회용이 보장된다.
// ⚠ 인스턴스를 여러 개 띄우면 Redis 로 옮겨야 한다. 안 옮기면 A 인스턴스에서
//
//	쓴 티켓을 B 인스턴스가 받아준다.
//
// reusable 에 적은 purpose 는 **nonce 를 소진하지 않는다.** 명세 §19-5 의
// 「뷰어 세션 단위 발급」이 그 뜻이다 — 타일 뷰어는 화면 하나에 수십 장을
// 당기는데, 1회용이면 그만큼 발급을 받아야 한다.
//
// ⚠ 읽기 티켓은 exp 까지 몇 번이든 쓸 수 있다. 대신 서는 것이 둘이고 둘 다
//
//	발급하는 쪽(Django)에 있다.
//	  object_key_prefix  이제 이것이 유일한 경계다. 검사 하나로 좁혀야 한다
//	  exp                이것이 곧 재사용 가능 시간이다
//
//	쓰기는 절대 넣지 말 것. 재사용되면 같은 자리에 덮어쓸 수 있다.
type Verifier struct {
	key      []byte
	reusable map[string]bool // 이 purpose 는 nonce 를 소진하지 않는다
	mu       sync.Mutex
	used     map[string]int64 // nonce -> exp. 만료된 것은 청소한다
}

func NewVerifier(key []byte, reusable ...string) *Verifier {
	r := make(map[string]bool, len(reusable))
	for _, p := range reusable {
		r[p] = true
	}
	return &Verifier{key: key, reusable: r, used: make(map[string]int64)}
}

func (v *Verifier) Verify(token string) (*Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, ErrMalformed
	}
	signing := parts[0] + "." + parts[1]
	sig, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return nil, ErrMalformed
	}
	mac := hmac.New(sha256.New, v.key)
	mac.Write([]byte(signing))
	// 상수 시간 비교 — 서명 비교에 == 를 쓰면 타이밍으로 새어 나간다
	if !hmac.Equal(sig, mac.Sum(nil)) {
		return nil, ErrSignature
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, ErrMalformed
	}
	var c Claims
	if err := json.Unmarshal(raw, &c); err != nil {
		return nil, ErrMalformed
	}
	now := time.Now().Unix()
	if c.Exp == 0 || c.Exp < now {
		return nil, ErrExpired
	}
	if c.Nonce == "" {
		return nil, ErrMalformed
	}

	// 읽기 티켓은 여기서 끝난다. nonce 는 **여전히 필수**다 — 값을 계속
	// 유일하게 받아 두면, 나중에 소진을 다시 켤 때 양쪽 형식을 안 바꿔도 된다.
	if v.reusable[c.Purpose] {
		return &c, nil
	}

	v.mu.Lock()
	defer v.mu.Unlock()
	v.sweep(now)
	if _, seen := v.used[c.Nonce]; seen {
		return nil, ErrReplayed
	}
	v.used[c.Nonce] = c.Exp
	return &c, nil
}

// RequireScope — 티켓이 가리키는 리소스와 요청이 같은지. 명세 19-1.
func (c *Claims) RequireScope(purpose, scopeID string) error {
	if c.Purpose != purpose || c.ScopeID != scopeID {
		return ErrScope
	}
	return nil
}

func (v *Verifier) sweep(now int64) {
	for n, exp := range v.used {
		if exp < now {
			delete(v.used, n)
		}
	}
}
