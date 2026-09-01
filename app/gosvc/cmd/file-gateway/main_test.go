// file-gateway 시험.
//
// 여기서 지키려는 것은 성능이 아니라 **틀리면 조용한** 것들이다.
//
//	· 조각 순서가 어긋나면 → 파일이 깨진 채로 커밋된다 (아무도 모른다)
//	· 조각 하나가 빠지면   → 짧은 파일이 정상처럼 커밋된다
//	· 상한을 넘겨도        → 다 받고 나서야 안다
//	· 티켓 범위를 안 보면  → 남의 환자 파일이 내려간다
//
// 넷 다 로그에 아무 흔적을 안 남기므로 시험으로만 잡힌다.
package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/storage"
	"cdss/gosvc/internal/ticket"
	"cdss/gosvc/internal/upload"
)

const (
	tkey   = "ticket-signing-key"
	cbsec  = "callback-secret"
	prefix = "patients/P-77/studies/S-9"
)

// ── 발판 ────────────────────────────────────────────────────────────

// 받은 I-1 콜백 한 건
type i1 struct {
	Idem   string
	TS     string
	Sig    string
	Body   []byte
	Parsed callback.StorageObject
}

type rig struct {
	g    *gw
	mux  *http.ServeMux
	root string // FS 저장소 뿌리

	mu   sync.Mutex
	got  []i1
	code int // Django 가 낼 응답 코드
}

func newRig(t *testing.T) *rig {
	t.Helper()
	r := &rig{root: filepath.Join(t.TempDir(), "store"), code: 200}

	dj := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		b, _ := io.ReadAll(req.Body)
		var o callback.StorageObject
		json.Unmarshal(b, &o)
		r.mu.Lock()
		r.got = append(r.got, i1{
			Idem: req.Header.Get("Idempotency-Key"),
			TS:   req.Header.Get("X-Timestamp"),
			Sig:  req.Header.Get("X-Signature"),
			Body: b, Parsed: o,
		})
		code := r.code
		r.mu.Unlock()
		w.WriteHeader(code)
	}))
	t.Cleanup(dj.Close)

	um, err := upload.NewManager(filepath.Join(t.TempDir(), "spool"), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	r.g = &gw{
		st: storage.NewFS(r.root),
		up: um,
		// 재시도 0 — 실패 시험이 백오프 때문에 몇 초씩 걸리면 안 된다
		cb:  callback.New(dj.URL, []byte(cbsec), "", "", 0),
		tv:  ticket.NewVerifier([]byte(tkey)),
		cls: "standard",
	}
	r.mux = r.g.routes()
	return r
}

func (r *rig) callbacks() []i1 {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]i1(nil), r.got...)
}

func (r *rig) djangoReturns(code int) {
	r.mu.Lock()
	r.code = code
	r.mu.Unlock()
}

// mint — Django 가 발급할 티켓과 같은 형태의 HS256 JWT.
// nonce 는 매번 새로 만든다. 같은 티켓을 두 번 쓰면 재사용으로 막히는데,
// 그건 별도 시험에서 일부러 확인한다.
var nonceSeq int

func mint(t *testing.T, edit ...func(*ticket.Claims)) string {
	t.Helper()
	nonceSeq++
	c := ticket.Claims{
		Purpose: "dicom_upload", PatientID: "P-77", ScopeID: "S-9",
		MaxBytes: 1 << 20, ContentType: "application/dicom",
		ObjectKeyPrefix: prefix,
		Exp:             time.Now().Add(5 * time.Minute).Unix(),
		Nonce:           fmt.Sprintf("n-%d", nonceSeq),
	}
	for _, f := range edit {
		f(&c)
	}
	b64 := func(b []byte) string { return base64.RawURLEncoding.EncodeToString(b) }
	head := b64([]byte(`{"alg":"HS256","typ":"JWT"}`))
	pay, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	signing := head + "." + b64(pay)
	m := hmac.New(sha256.New, []byte(tkey))
	m.Write([]byte(signing))
	return signing + "." + b64(m.Sum(nil))
}

func (r *rig) do(t *testing.T, method, path, tok string, body io.Reader,
	hdr ...string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(method, path, body)
	if tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	for i := 0; i+1 < len(hdr); i += 2 {
		req.Header.Set(hdr[i], hdr[i+1])
	}
	w := httptest.NewRecorder()
	r.mux.ServeHTTP(w, req)
	return w
}

func decode(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &m); err != nil {
		t.Fatalf("응답이 JSON 이 아니다 (%d): %s", w.Code, w.Body.String())
	}
	return m
}

// ── G-F1~G-F3 청크 업로드 ───────────────────────────────────────────

// 조각을 **거꾸로** 보내도 순서대로 붙어야 한다.
// HTTP/2 병렬 전송이면 실제로 늦게 보낸 조각이 먼저 도착한다.
func TestChunkedUploadOutOfOrder(t *testing.T) {
	r := newRig(t)
	p1, p2, p3 := []byte("첫번째-조각|"), []byte("두번째-조각|"), []byte("세번째-조각")
	want := append(append(append([]byte{}, p1...), p2...), p3...)

	res := decode(t, r.do(t, "POST", "/svc/v1/upload/init", mint(t),
		strings.NewReader(`{"filename":"study.DCM"}`)))
	id, _ := res["upload_id"].(string)
	if id == "" {
		t.Fatalf("upload_id 가 없다: %v", res)
	}

	for _, pr := range []struct {
		n int
		b []byte
	}{{3, p3}, {1, p1}, {2, p2}} {
		w := r.do(t, "PUT", fmt.Sprintf("/svc/v1/upload/%s/part/%d", id, pr.n),
			mint(t), bytes.NewReader(pr.b))
		if w.Code != 200 {
			t.Fatalf("조각 %d: %d %s", pr.n, w.Code, w.Body)
		}
	}

	w := r.do(t, "POST", "/svc/v1/upload/"+id+"/complete", mint(t), nil)
	if w.Code != 201 {
		t.Fatalf("complete: %d %s", w.Code, w.Body)
	}
	out := decode(t, w)
	key, _ := out["object_key"].(string)

	// ① 키는 티켓 접두사 아래여야 한다
	if !strings.HasPrefix(key, prefix+"/") {
		t.Errorf("키가 티켓 접두사 밖이다: %s", key)
	}
	// ② 확장자는 소문자로 살린다 (.DCM → .dcm)
	if !strings.HasSuffix(key, ".dcm") {
		t.Errorf("확장자가 안 붙었다: %s", key)
	}
	// ③ 저장된 내용이 보낸 순서 그대로여야 한다
	blob, err := os.ReadFile(filepath.Join(r.root, filepath.FromSlash(key)))
	if err != nil {
		t.Fatalf("저장된 객체를 못 읽는다: %v", err)
	}
	if !bytes.Equal(blob, want) {
		t.Errorf("내용이 다르다\n  받은 것: %q\n  보낸 것: %q", blob, want)
	}
	// ④ sha256 은 **붙인 결과**의 것이어야 한다
	sum := sha256.Sum256(want)
	if out["checksum_sha256"] != hex.EncodeToString(sum[:]) {
		t.Errorf("sha256 불일치: %v", out["checksum_sha256"])
	}
	if int64(out["byte_size"].(float64)) != int64(len(want)) {
		t.Errorf("byte_size 불일치: %v (실제 %d)", out["byte_size"], len(want))
	}

	// ⑤ I-1 콜백 — 명세 21장
	cbs := r.callbacks()
	if len(cbs) != 1 {
		t.Fatalf("I-1 이 %d번 갔다 (1번이어야 한다)", len(cbs))
	}
	c := cbs[0]
	if c.Idem != "obj:"+key {
		t.Errorf("멱등키가 object_key 기반이 아니다: %s", c.Idem)
	}
	if c.Sig != callback.Sign([]byte(cbsec), c.TS, c.Body) {
		t.Errorf("X-Signature 가 안 맞는다")
	}
	if c.Parsed.ByteSize != int64(len(want)) ||
		c.Parsed.ChecksumSHA256 != hex.EncodeToString(sum[:]) {
		t.Errorf("I-1 본문이 응답과 다르다: %+v", c.Parsed)
	}
	if c.Parsed.PatientID != "P-77" || c.Parsed.ScopeID != "S-9" {
		t.Errorf("I-1 이 티켓의 환자·범위를 안 실었다: %+v", c.Parsed)
	}
	if c.Parsed.StorageClass != "standard" || c.Parsed.Bucket == "" {
		t.Errorf("I-1 에 bucket·storage_class 가 빠졌다: %+v", c.Parsed)
	}

	// ⑥ 조각 스풀은 지워져야 한다
	if _, ok := r.g.up.Get(id); ok {
		t.Errorf("complete 뒤에도 세션이 남아 있다")
	}
}

// 조각 하나가 빠진 채 complete 하면 **짧은 파일이 조용히 커밋된다.**
// 그게 제일 위험해서 400 으로 막는다.
func TestCompleteRejectsMissingPart(t *testing.T) {
	r := newRig(t)
	id, _ := decode(t, r.do(t, "POST", "/svc/v1/upload/init", mint(t),
		strings.NewReader(`{"filename":"a.dcm"}`)))["upload_id"].(string)

	for _, n := range []int{1, 3} { // 2번이 없다
		r.do(t, "PUT", fmt.Sprintf("/svc/v1/upload/%s/part/%d", id, n),
			mint(t), strings.NewReader("xxxx"))
	}
	w := r.do(t, "POST", "/svc/v1/upload/"+id+"/complete", mint(t), nil)
	if w.Code != 400 {
		t.Fatalf("빠진 조각을 통과시켰다: %d %s", w.Code, w.Body)
	}
	if len(r.callbacks()) != 0 {
		t.Errorf("실패했는데 I-1 을 보냈다 — DB 에 없는 파일이 생긴다")
	}
}

func TestPartRejectsOverMaxBytes(t *testing.T) {
	r := newRig(t)
	tok := mint(t, func(c *ticket.Claims) { c.MaxBytes = 10 })
	id, _ := decode(t, r.do(t, "POST", "/svc/v1/upload/init", tok,
		strings.NewReader(`{"filename":"a.dcm"}`)))["upload_id"].(string)

	if w := r.do(t, "PUT", "/svc/v1/upload/"+id+"/part/1", mint(t),
		strings.NewReader("0123456789")); w.Code != 200 {
		t.Fatalf("상한 이내인데 막혔다: %d %s", w.Code, w.Body)
	}
	w := r.do(t, "PUT", "/svc/v1/upload/"+id+"/part/2", mint(t),
		strings.NewReader("한 바이트 더"))
	if w.Code != 413 {
		t.Fatalf("상한을 넘겼는데 받았다: %d %s", w.Code, w.Body)
	}
	// 넘긴 조각은 세션에 남으면 안 된다 — 남으면 complete 가 상한을 넘긴다
	s, _ := r.g.up.Get(id)
	if _, _, err := r.g.up.Assemble(s, func(rd io.Reader, _ int64, _ string) error {
		n, _ := io.Copy(io.Discard, rd)
		if n != 10 {
			t.Errorf("거부한 조각이 남았다: %d 바이트", n)
		}
		return nil
	}); err != nil {
		t.Fatalf("조립 실패: %v", err)
	}
}

func TestPartRejectsBadNumber(t *testing.T) {
	r := newRig(t)
	id, _ := decode(t, r.do(t, "POST", "/svc/v1/upload/init", mint(t),
		strings.NewReader(`{"filename":"a.dcm"}`)))["upload_id"].(string)
	for _, n := range []string{"0", "-1", "abc"} {
		if w := r.do(t, "PUT", "/svc/v1/upload/"+id+"/part/"+n, mint(t),
			strings.NewReader("x")); w.Code != 400 {
			t.Errorf("조각 번호 %q 를 받았다: %d", n, w.Code)
		}
	}
}

func TestUnknownUploadIsNotFound(t *testing.T) {
	r := newRig(t)
	if w := r.do(t, "POST", "/svc/v1/upload/deadbeef/complete", mint(t), nil); w.Code != 404 {
		t.Errorf("없는 업로드에 %d 를 냈다", w.Code)
	}
}

// ── G-F4 단일 파일 ──────────────────────────────────────────────────

func TestPutFile(t *testing.T) {
	r := newRig(t)
	body := []byte("DICM....단일 파일")
	w := r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(body),
		"X-Filename", "report.pdf")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	out := decode(t, w)
	sum := sha256.Sum256(body)
	if out["checksum_sha256"] != hex.EncodeToString(sum[:]) {
		t.Errorf("sha256 불일치")
	}
	if int64(out["byte_size"].(float64)) != int64(len(body)) {
		t.Errorf("byte_size 불일치: %v", out["byte_size"])
	}
	key := out["object_key"].(string)
	blob, err := os.ReadFile(filepath.Join(r.root, filepath.FromSlash(key)))
	if err != nil || !bytes.Equal(blob, body) {
		t.Errorf("저장된 내용이 다르다: %v", err)
	}
}

// 상한을 넘긴 파일은 **저장소에 남으면 안 된다.**
// io.LimitReader 로 막으면 잘린 파일이 조용히 커밋되므로 그것도 같이 본다.
func TestPutFileRejectsOverMaxBytes(t *testing.T) {
	r := newRig(t)
	tok := mint(t, func(c *ticket.Claims) { c.MaxBytes = 16 })
	w := r.do(t, "POST", "/svc/v1/files", tok,
		bytes.NewReader(bytes.Repeat([]byte("A"), 4096)), "X-Filename", "big.dcm")
	if w.Code != 413 {
		t.Fatalf("상한을 넘겼는데 %d 를 냈다: %s", w.Code, w.Body)
	}
	if len(r.callbacks()) != 0 {
		t.Errorf("거부했는데 I-1 을 보냈다")
	}
	var left []string
	filepath.Walk(r.root, func(p string, fi os.FileInfo, _ error) error {
		if fi != nil && !fi.IsDir() {
			left = append(left, p)
		}
		return nil
	})
	if len(left) != 0 {
		t.Errorf("거부한 파일이 저장소에 남았다: %v", left)
	}
}

// ── G-F5 다운로드 ───────────────────────────────────────────────────

// 객체를 하나 심고 그 키를 돌려준다
func (r *rig) seed(t *testing.T, key string, body []byte) {
	t.Helper()
	p := filepath.Join(r.root, filepath.FromSlash(key))
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, body, 0o644); err != nil {
		t.Fatal(err)
	}
}

func dlTicket(t *testing.T) string {
	return mint(t, func(c *ticket.Claims) { c.Purpose = "download" })
}

func TestDownload(t *testing.T) {
	r := newRig(t)
	body := []byte("0123456789abcdef")
	r.seed(t, prefix+"/obj.bin", body)

	w := r.do(t, "GET", "/svc/v1/files/"+prefix+"/obj.bin", dlTicket(t), nil)
	if w.Code != 200 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	if !bytes.Equal(w.Body.Bytes(), body) {
		t.Errorf("내용이 다르다: %q", w.Body.String())
	}
}

// Range 를 직접 짜면 반드시 틀린다. http.ServeContent 에 맡겼는지 확인한다.
// WSI 타일 뷰어가 이걸 쓴다.
func TestDownloadRange(t *testing.T) {
	r := newRig(t)
	body := []byte("0123456789abcdef")
	r.seed(t, prefix+"/obj.bin", body)

	w := r.do(t, "GET", "/svc/v1/files/"+prefix+"/obj.bin", dlTicket(t), nil,
		"Range", "bytes=4-9")
	if w.Code != 206 {
		t.Fatalf("Range 를 무시했다: %d", w.Code)
	}
	if got := w.Body.String(); got != "456789" {
		t.Errorf("구간이 틀리다: %q", got)
	}
	if cr := w.Header().Get("Content-Range"); cr != "bytes 4-9/16" {
		t.Errorf("Content-Range 가 틀리다: %q", cr)
	}
}

// 같은 병원 안이라도 티켓 범위 밖 객체는 못 내려간다. 여기가 권한 경계다.
func TestDownloadRejectsOutOfScope(t *testing.T) {
	r := newRig(t)
	r.seed(t, "patients/P-99/studies/S-1/secret.bin", []byte("남의 환자"))

	w := r.do(t, "GET", "/svc/v1/files/patients/P-99/studies/S-1/secret.bin",
		dlTicket(t), nil)
	if w.Code != 403 {
		t.Fatalf("남의 환자 파일을 %d 로 내줬다: %s", w.Code, w.Body)
	}
	if decode(t, w)["code"] != "TICKET_SCOPE_MISMATCH" {
		t.Errorf("코드가 틀리다: %s", w.Body)
	}
}

// 접두사로 시작만 하면 통과하는 구현이면 P-7 티켓으로 P-77 을 읽는다.
// 경계에 / 를 붙여 막았는지 본다.
func TestDownloadPrefixIsPathBoundary(t *testing.T) {
	r := newRig(t)
	r.seed(t, prefix+"-other/x.bin", []byte("옆 폴더"))
	w := r.do(t, "GET", "/svc/v1/files/"+prefix+"-other/x.bin", dlTicket(t), nil)
	if w.Code != 403 {
		t.Fatalf("접두사 경계를 안 봤다: %d %s", w.Code, w.Body)
	}
}

func TestDownloadTraversal(t *testing.T) {
	r := newRig(t)
	r.seed(t, "outside.bin", []byte("뿌리 바깥"))
	for _, key := range []string{
		prefix + "/../../../outside.bin",
		prefix + "/..%2f..%2f..%2foutside.bin",
	} {
		w := r.do(t, "GET", "/svc/v1/files/"+key, dlTicket(t), nil)
		if w.Code == 200 {
			t.Errorf("경로 탈출을 허용했다: %s", key)
		}
	}
}

func TestDownloadMissingObject(t *testing.T) {
	r := newRig(t)
	if w := r.do(t, "GET", "/svc/v1/files/"+prefix+"/nope.bin",
		dlTicket(t), nil); w.Code != 404 {
		t.Errorf("없는 객체에 %d 를 냈다", w.Code)
	}
}

// ── 티켓 ────────────────────────────────────────────────────────────

func TestTicketRejections(t *testing.T) {
	r := newRig(t)
	seed := mint(t)

	for _, c := range []struct {
		name string
		tok  string
		code int
		want string
	}{
		{"없음", "", 401, "TICKET_"},
		{"서명 위조", seed[:len(seed)-4] + "AAAA", 401, "TICKET_INVALID"},
		{"만료", mint(t, func(c *ticket.Claims) {
			c.Exp = time.Now().Add(-time.Second).Unix()
		}), 401, "TICKET_EXPIRED"},
		{"용도 불일치", mint(t, func(c *ticket.Claims) {
			c.Purpose = "download"
		}), 403, "TICKET_SCOPE_MISMATCH"},
		{"접두사 없음", mint(t, func(c *ticket.Claims) {
			c.ObjectKeyPrefix = ""
		}), 403, "TICKET_SCOPE_MISMATCH"},
	} {
		t.Run(c.name, func(t *testing.T) {
			w := r.do(t, "POST", "/svc/v1/upload/init", c.tok, strings.NewReader("{}"))
			if w.Code != c.code {
				t.Fatalf("%d 를 냈다 (%d 여야 한다): %s", w.Code, c.code, w.Body)
			}
			if got, _ := decode(t, w)["code"].(string); !strings.HasPrefix(got, c.want) {
				t.Errorf("코드가 %q 다 (%q 로 시작해야 한다)", got, c.want)
			}
		})
	}
}

// 같은 티켓을 두 번 쓰면 두 번째는 막혀야 한다. 가로챈 티켓의 재사용을 막는다.
func TestTicketReplay(t *testing.T) {
	r := newRig(t)
	tok := mint(t)
	if w := r.do(t, "POST", "/svc/v1/upload/init", tok, strings.NewReader("{}")); w.Code != 200 {
		t.Fatalf("첫 사용이 막혔다: %d %s", w.Code, w.Body)
	}
	w := r.do(t, "POST", "/svc/v1/upload/init", tok, strings.NewReader("{}"))
	if w.Code != 401 || decode(t, w)["code"] != "TICKET_REPLAYED" {
		t.Fatalf("재사용을 받아줬다: %d %s", w.Code, w.Body)
	}
}

// ── 키 생성 ─────────────────────────────────────────────────────────

// 클라이언트가 준 파일명은 **경로가 아니다.** 확장자만 참고한다.
func TestKeyForIgnoresClientPath(t *testing.T) {
	cl := &ticket.Claims{ObjectKeyPrefix: prefix}
	for _, name := range []string{
		"../../../../etc/passwd",
		"/absolute/path.dcm",
		`C:\Users\x\study.dcm`,
		"a/b/c.dcm",
		"..",
		"",
		strings.Repeat("x", 300) + ".dcm",
	} {
		k := keyFor(cl, name)
		if !strings.HasPrefix(k, prefix+"/") {
			t.Errorf("%q → %q : 접두사 밖", name, k)
		}
		if strings.Contains(strings.TrimPrefix(k, prefix+"/"), "/") {
			t.Errorf("%q → %q : 접두사 아래에 경로가 생겼다", name, k)
		}
		if strings.Contains(k, "..") {
			t.Errorf("%q → %q : 상위 참조가 남았다", name, k)
		}
	}
}

// 같은 이름을 두 번 올려도 서로 덮어쓰면 안 된다
func TestKeyForIsUnique(t *testing.T) {
	cl := &ticket.Claims{ObjectKeyPrefix: prefix}
	seen := map[string]bool{}
	for i := 0; i < 200; i++ {
		k := keyFor(cl, "study.dcm")
		if seen[k] {
			t.Fatalf("키가 겹쳤다: %s", k)
		}
		seen[k] = true
	}
}

// ── I-1 실패 ────────────────────────────────────────────────────────

// 파일은 저장됐는데 Django 등록이 실패하면 고아 객체다.
// 200 을 내면 클라이언트는 성공으로 알고, 그 파일은 영영 아무도 안 찾는다.
func TestCommitFailsWhenCallbackFails(t *testing.T) {
	r := newRig(t)
	r.djangoReturns(500)
	w := r.do(t, "POST", "/svc/v1/files", mint(t),
		strings.NewReader("본문"), "X-Filename", "a.dcm")
	if w.Code != 502 {
		t.Fatalf("I-1 이 실패했는데 %d 를 냈다: %s", w.Code, w.Body)
	}
	if decode(t, w)["code"] != "CALLBACK_FAILED" {
		t.Errorf("코드가 틀리다: %s", w.Body)
	}
}

// 4xx 는 재시도해도 같다. 백오프로 시간을 쓰면 안 된다.
func TestCallbackDoesNotRetry4xx(t *testing.T) {
	r := newRig(t)
	r.djangoReturns(400)
	start := time.Now()
	r.do(t, "POST", "/svc/v1/files", mint(t), strings.NewReader("x"), "X-Filename", "a.dcm")
	if n := len(r.callbacks()); n != 1 {
		t.Errorf("4xx 를 %d번 보냈다 (1번이어야 한다)", n)
	}
	if d := time.Since(start); d > 2*time.Second {
		t.Errorf("4xx 에서 백오프를 돌았다: %v", d)
	}
}

// ── capReader ───────────────────────────────────────────────────────

// io.LimitReader 는 상한에서 EOF 를 낸다 → 잘린 파일이 정상처럼 저장된다.
// capReader 는 오류를 내야 한다.
func TestCapReader(t *testing.T) {
	src := strings.Repeat("A", 100)
	cr := &capReader{r: strings.NewReader(src), limit: 40}
	n, err := io.Copy(io.Discard, cr)
	if err == nil {
		t.Fatalf("상한을 넘겼는데 조용히 끝났다 (%d 바이트) — 잘린 파일이 커밋된다", n)
	}
	if !strings.Contains(err.Error(), upload.ErrTooBig.Error()) {
		t.Errorf("오류가 %v 다", err)
	}

	// 딱 맞는 크기는 통과해야 한다 (경계에서 한 바이트 틀리는 실수)
	ok := &capReader{r: strings.NewReader(src), limit: 100}
	if n, err := io.Copy(io.Discard, ok); err != nil || n != 100 {
		t.Errorf("정확히 상한인 입력이 막혔다: %d %v", n, err)
	}
	// limit 0 = 무제한
	no := &capReader{r: strings.NewReader(src), limit: 0}
	if n, err := io.Copy(io.Discard, no); err != nil || n != 100 {
		t.Errorf("무제한인데 막혔다: %d %v", n, err)
	}
}
