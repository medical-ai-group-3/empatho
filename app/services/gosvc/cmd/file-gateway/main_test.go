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
	"encoding/binary"
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
	"cdss/gosvc/internal/orthanc"
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

// 받은 내부 콜백 한 건
type i1 struct {
	Path   string
	Idem   string
	TS     string
	Sig    string
	Body   []byte
	Parsed callback.StorageObject
	Dicom  callback.DicomMetadata
}

type rig struct {
	g       *gw
	mux     *http.ServeMux
	root    string // FS 저장소 뿌리
	derRoot string // 파생물 버킷 뿌리

	mu   sync.Mutex
	got  []i1
	code int // Django 가 낼 응답 코드

	// failPath 에 들어온 콜백만 500 을 낸다. I-2 만 실패시킬 때 쓴다.
	failPath string
}

func newRig(t *testing.T) *rig {
	t.Helper()
	r := &rig{root: filepath.Join(t.TempDir(), "store"), code: 200}

	dj := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		b, _ := io.ReadAll(req.Body)
		var o callback.StorageObject
		var d callback.DicomMetadata
		json.Unmarshal(b, &o)
		json.Unmarshal(b, &d)
		r.mu.Lock()
		r.got = append(r.got, i1{
			Path: req.URL.Path,
			Idem: req.Header.Get("Idempotency-Key"),
			TS:   req.Header.Get("X-Timestamp"),
			Sig:  req.Header.Get("X-Signature"),
			Body: b, Parsed: o, Dicom: d,
		})
		code := r.code
		if r.failPath != "" && req.URL.Path == r.failPath {
			code = 500
		}
		r.mu.Unlock()
		w.WriteHeader(code)
	}))
	t.Cleanup(dj.Close)

	um, err := upload.NewManager(filepath.Join(t.TempDir(), "spool"), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	r.derRoot = filepath.Join(t.TempDir(), "derived")
	r.g = &gw{
		st:  storage.NewFS(r.root),
		der: storage.NewFS(r.derRoot),
		up:  um,
		// 재시도 0 — 실패 시험이 백오프 때문에 몇 초씩 걸리면 안 된다
		cb:  callback.New(dj.URL, []byte(cbsec), "", "", 0),
		tv:  ticket.NewVerifier([]byte(tkey)),
		cls: "standard",
	}
	r.mux = r.g.routes()
	return r
}

// callbacks — I-1 만. I-2 는 dicoms() 로 따로 본다.
func (r *rig) callbacks() []i1 { return r.pick("/internal/v1/storage-objects") }
func (r *rig) dicoms() []i1    { return r.pick("/internal/v1/dicom-instances") }

func (r *rig) pick(path string) []i1 {
	r.mu.Lock()
	defer r.mu.Unlock()
	var out []i1
	for _, c := range r.got {
		if c.Path == path {
			out = append(out, c)
		}
	}
	return out
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
func TestKeyForKeepsNiiGz(t *testing.T) {
	cl := &ticket.Claims{ObjectKeyPrefix: prefix}
	if k := keyFor(cl, "duke_465_0000.nii.gz"); !strings.HasSuffix(k, ".nii.gz") {
		t.Errorf("확장자가 잘렸다: %s", k)
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

// ── G-F7  DICOM 파싱 → I-2 ──────────────────────────────────────────

// 시험용 유방촬영 DICOM 을 바이트로 짓는다.
// 실제 자료를 못 쓴다 — CBIS-DDSM 은 재배포 금지, EMBED 는 DUA 로 묶여 있다.
func mgDICOM(sop, laterality, view, spacing string) []byte {
	var b bytes.Buffer
	b.Write(make([]byte, 128))
	b.WriteString("DICM")
	el := func(g, e uint16, vr, v string) {
		if len(v)%2 == 1 {
			v += "\x00"
		}
		binary.Write(&b, binary.LittleEndian, g)
		binary.Write(&b, binary.LittleEndian, e)
		b.WriteString(vr)
		binary.Write(&b, binary.LittleEndian, uint16(len(v)))
		b.WriteString(v)
	}
	us := func(g, e, n uint16) {
		binary.Write(&b, binary.LittleEndian, g)
		binary.Write(&b, binary.LittleEndian, e)
		b.WriteString("US")
		binary.Write(&b, binary.LittleEndian, uint16(2))
		binary.Write(&b, binary.LittleEndian, n)
	}
	el(0x0002, 0x0010, "UI", "1.2.840.10008.1.2.1")
	el(0x0008, 0x0018, "UI", sop)
	el(0x0008, 0x0060, "CS", "MG")
	el(0x0010, 0x0010, "PN", "홍^길동")
	el(0x0010, 0x0020, "LO", "DCM-PID-1")
	if spacing != "" {
		el(0x0018, 0x1164, "DS", spacing)
	}
	el(0x0018, 0x5101, "CS", view)
	el(0x0020, 0x000D, "UI", "1.2.3.STUDY")
	el(0x0020, 0x000E, "UI", "1.2.3.SERIES")
	el(0x0020, 0x0062, "CS", laterality)
	us(0x0028, 0x0010, 4096)
	us(0x0028, 0x0011, 3328)
	// PixelData — 여기서 파서가 멈춰야 한다
	binary.Write(&b, binary.LittleEndian, uint16(0x7FE0))
	binary.Write(&b, binary.LittleEndian, uint16(0x0010))
	b.WriteString("OW")
	binary.Write(&b, binary.LittleEndian, uint16(0))
	binary.Write(&b, binary.LittleEndian, uint32(2048))
	b.Write(bytes.Repeat([]byte{0xAB}, 2048))
	return b.Bytes()
}

func TestDicomSingleFileSendsI2(t *testing.T) {
	r := newRig(t)
	raw := mgDICOM("1.2.3.SOP", "R", "CC", `0.07\0.07`)

	w := r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(raw),
		"X-Filename", "study.dcm")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	key := decode(t, w)["object_key"].(string)

	// I-1 이 먼저, I-2 가 나중 — 명세 21장 순서 보장
	all := r.pick("/internal/v1/storage-objects")
	dc := r.dicoms()
	if len(all) != 1 || len(dc) != 1 {
		t.Fatalf("I-1 %d건 · I-2 %d건 (각 1건이어야 한다)", len(all), len(dc))
	}
	r.mu.Lock()
	order := []string{r.got[0].Path, r.got[1].Path}
	r.mu.Unlock()
	if order[0] != "/internal/v1/storage-objects" {
		t.Errorf("I-2 가 I-1 보다 먼저 갔다: %v", order)
	}

	m := dc[0].Dicom
	if m.ObjectKey != key {
		t.Errorf("I-2 의 object_key 가 I-1 과 다르다: %q vs %q", m.ObjectKey, key)
	}
	if dc[0].Idem != "dcm:"+key {
		t.Errorf("I-2 멱등키: %q", dc[0].Idem)
	}
	if dc[0].Idem == all[0].Idem {
		t.Errorf("I-1 과 I-2 가 같은 멱등키를 쓴다 — 서로 덮어쓴다")
	}
	if dc[0].Sig != callback.Sign([]byte(cbsec), dc[0].TS, dc[0].Body) {
		t.Errorf("I-2 서명이 안 맞는다")
	}
	for _, c := range []struct{ name, got, want string }{
		{"sop", m.SOPInstanceUID, "1.2.3.SOP"},
		{"study", m.StudyInstanceUID, "1.2.3.STUDY"},
		{"series", m.SeriesInstanceUID, "1.2.3.SERIES"},
		{"modality", m.Modality, "MG"},
		{"laterality", m.Laterality, "R"},
		{"view", m.ViewPosition, "CC"},
		{"dicom_patient_id", m.DicomPatientID, "DCM-PID-1"},
		{"ticket patient_id", m.PatientID, "P-77"}, // 티켓 쪽 값
	} {
		if c.got != c.want {
			t.Errorf("%s = %q (%q 여야 한다)", c.name, c.got, c.want)
		}
	}
	if m.Rows != 4096 || m.Columns != 3328 {
		t.Errorf("크기 %dx%d", m.Columns, m.Rows)
	}
	if len(m.PixelSpacing) != 2 || m.PixelSpacing[0] != 0.07 {
		t.Errorf("화소 간격 = %v", m.PixelSpacing)
	}
}

// 환자 이름은 I-2 본문에 절대 안 들어가야 한다. 가명화 정책 미정 상태다.
func TestDicomCallbackHasNoPatientName(t *testing.T) {
	r := newRig(t)
	raw := mgDICOM("1.2.3.SOP", "L", "MLO", `0.07\0.07`)
	if !bytes.Contains(raw, []byte("홍^길동")) {
		t.Fatal("시험 자료에 이름이 없다 — 시험이 의미 없다")
	}
	r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(raw), "X-Filename", "a.dcm")

	dc := r.dicoms()
	if len(dc) != 1 {
		t.Fatalf("I-2 %d건", len(dc))
	}
	if bytes.Contains(dc[0].Body, []byte("홍")) {
		t.Errorf("환자 이름이 I-2 본문에 실렸다: %s", dc[0].Body)
	}
}

// 청크 업로드로 올려도 똑같이 I-2 가 가야 한다.
// 조각을 이어 붙이며 앞부분을 따로 받는 경로가 따로라 별도로 확인한다.
func TestDicomChunkedSendsI2(t *testing.T) {
	r := newRig(t)
	raw := mgDICOM("1.2.3.CHUNKED", "L", "MLO", `0.085\0.085`)

	id := decode(t, r.do(t, "POST", "/svc/v1/upload/init", mint(t),
		strings.NewReader(`{"filename":"a.dcm"}`)))["upload_id"].(string)
	// 머리말 한가운데를 가르도록 조각을 나눈다
	for i, chunk := range [][]byte{raw[:150], raw[150:400], raw[400:]} {
		if w := r.do(t, "PUT", fmt.Sprintf("/svc/v1/upload/%s/part/%d", id, i+1),
			mint(t), bytes.NewReader(chunk)); w.Code != 200 {
			t.Fatalf("조각 %d: %d %s", i+1, w.Code, w.Body)
		}
	}
	if w := r.do(t, "POST", "/svc/v1/upload/"+id+"/complete", mint(t), nil); w.Code != 201 {
		t.Fatalf("complete: %d %s", w.Code, w.Body)
	}
	dc := r.dicoms()
	if len(dc) != 1 {
		t.Fatalf("청크 업로드에서 I-2 가 %d건", len(dc))
	}
	if dc[0].Dicom.SOPInstanceUID != "1.2.3.CHUNKED" {
		t.Errorf("SOP = %q", dc[0].Dicom.SOPInstanceUID)
	}
	if len(dc[0].Dicom.PixelSpacing) != 2 || dc[0].Dicom.PixelSpacing[0] != 0.085 {
		t.Errorf("간격 = %v", dc[0].Dicom.PixelSpacing)
	}
}

// DICOM 이 아닌 것(PDF 등)에는 I-2 를 보내면 안 된다
func TestNonDicomSendsNoI2(t *testing.T) {
	r := newRig(t)
	pdf := append([]byte("%PDF-1.7\n"), bytes.Repeat([]byte("x"), 500)...)
	if w := r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(pdf),
		"X-Filename", "report.pdf"); w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	if n := len(r.dicoms()); n != 0 {
		t.Errorf("PDF 에 I-2 를 %d건 보냈다", n)
	}
	if n := len(r.callbacks()); n != 1 {
		t.Errorf("I-1 은 갔어야 한다: %d건", n)
	}
}

// 화소 간격이 없는 DICOM(CBIS-DDSM 같은 필름 스캔)도 받아야 한다.
// 다만 간격을 **지어내면 안 된다** — 없으면 없다고 가야 한다.
func TestDicomWithoutSpacing(t *testing.T) {
	r := newRig(t)
	raw := mgDICOM("1.2.3.NOSPACE", "R", "CC", "")
	w := r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(raw),
		"X-Filename", "a.dcm")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	dc := r.dicoms()
	if len(dc) != 1 {
		t.Fatalf("I-2 %d건", len(dc))
	}
	if len(dc[0].Dicom.PixelSpacing) != 0 {
		t.Errorf("없는 간격을 지어냈다: %v", dc[0].Dicom.PixelSpacing)
	}
	// 응답에 명시적으로 null 이 실려야 한다. 필드가 빠지면 호출부가
	// "안 봤다" 와 "없다" 를 구별 못 한다.
	d, ok := decode(t, w)["dicom"].(map[string]any)
	if !ok {
		t.Fatal("응답에 dicom 이 없다")
	}
	if v, present := d["pixel_spacing_mm"]; !present || v != nil {
		t.Errorf("pixel_spacing_mm = %v (null 이어야 한다)", v)
	}
}

// I-2 가 실패해도 **요청은 성공**이다. I-1 이 이미 끝나 객체가 등록됐으므로
// 여기서 502 를 내면 클라이언트가 재업로드해서 같은 파일이 두 벌 생긴다.
// 대신 응답에 실패를 표시해야 한다 — 조용히 삼키면 안 된다.
func TestDicomMetadataFailureDoesNotFailRequest(t *testing.T) {
	r := newRig(t)
	r.failPath = "/internal/v1/dicom-instances"
	raw := mgDICOM("1.2.3.SOP", "R", "CC", `0.07\0.07`)

	w := r.do(t, "POST", "/svc/v1/files", mint(t), bytes.NewReader(raw),
		"X-Filename", "a.dcm")
	if w.Code != 201 {
		t.Fatalf("I-2 실패가 요청을 죽였다: %d %s", w.Code, w.Body)
	}
	d, ok := decode(t, w)["dicom"].(map[string]any)
	if !ok {
		t.Fatal("응답에 dicom 이 없다")
	}
	if d["metadata_registered"] != false {
		t.Errorf("실패를 표시 안 했다: %v", d)
	}
}

// ── 파생물 업로드 (3D 메시 · 마스크) ────────────────────────────────

func mintDerived(t *testing.T, edit ...func(*ticket.Claims)) string {
	t.Helper()
	all := append([]func(*ticket.Claims){func(c *ticket.Claims) {
		c.Purpose = "derived_upload"
		c.ContentType = "model/stl"
	}}, edit...)
	return mint(t, all...)
}

func TestPutDerived(t *testing.T) {
	r := newRig(t)
	body := []byte("solid mesh\n  facet normal 0 0 1\nendsolid")

	w := r.do(t, "POST", "/svc/v1/derived", mintDerived(t),
		bytes.NewReader(body), "X-Filename", "tumor.stl")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	out := decode(t, w)
	key := out["object_key"].(string)

	// 원본이 아니라 파생물 버킷에 있어야 한다
	if blob, err := os.ReadFile(filepath.Join(r.derRoot, filepath.FromSlash(key))); err != nil {
		t.Fatalf("파생물 버킷에 없다: %v", err)
	} else if !bytes.Equal(blob, body) {
		t.Error("저장된 내용이 다르다")
	}
	if _, err := os.Stat(filepath.Join(r.root, filepath.FromSlash(key))); err == nil {
		t.Error("원본 버킷에 쓰였다 — 버킷이 갈리지 않았다")
	}

	// I-1 로 등록됐는가. 이게 이 경로를 만든 이유다 —
	// 추론이 Garage 에 직접 쓰면 이 행이 안 생긴다.
	cbs := r.callbacks()
	if len(cbs) != 1 {
		t.Fatalf("I-1 이 한 번 가야 한다. got=%d", len(cbs))
	}
	if got := cbs[0].Parsed.Bucket; got != "local:"+r.derRoot {
		t.Errorf("I-1 의 bucket 이 파생물 버킷이어야 한다. got=%s", got)
	}
	if cbs[0].Parsed.ObjectKey != key {
		t.Errorf("object_key 불일치")
	}
	sum := sha256.Sum256(body)
	if cbs[0].Parsed.ChecksumSHA256 != hex.EncodeToString(sum[:]) {
		t.Error("체크섬이 I-1 에 실려야 한다")
	}
}

// 파생물은 DICOM 이 아니다. 머리말을 파싱하거나 Orthanc 로 보내면 안 된다.
func TestPutDerivedSkipsDICOM(t *testing.T) {
	r := newRig(t)
	// 일부러 DICOM 처럼 생긴 바이트를 넣는다
	body := append(make([]byte, 128), []byte("DICM")...)
	body = append(body, make([]byte, 64)...)

	w := r.do(t, "POST", "/svc/v1/derived", mintDerived(t),
		bytes.NewReader(body), "X-Filename", "mask.bin")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	if n := len(r.dicoms()); n != 0 {
		t.Errorf("파생물에 I-2 를 보내면 안 된다. got=%d", n)
	}
	if _, ok := decode(t, w)["dicom"]; ok {
		t.Error("응답에 dicom 정보가 있으면 안 된다")
	}
}

// 용도가 다른 티켓으로는 파생물을 못 올린다.
func TestPutDerivedRejectsWrongPurpose(t *testing.T) {
	r := newRig(t)
	w := r.do(t, "POST", "/svc/v1/derived", mint(t), // dicom_upload 티켓
		bytes.NewReader([]byte("x")), "X-Filename", "a.stl")
	if w.Code != 403 {
		t.Fatalf("403 이어야 한다. got=%d %s", w.Code, w.Body)
	}
	if len(r.callbacks()) != 0 {
		t.Error("거부됐으면 I-1 도 안 가야 한다")
	}
}

// 반대 방향도 막혀야 한다 — 파생물 티켓으로 원본 경로를 쓰면 안 된다.
func TestOriginalPathRejectsDerivedTicket(t *testing.T) {
	r := newRig(t)
	w := r.do(t, "POST", "/svc/v1/files", mintDerived(t),
		bytes.NewReader([]byte("x")), "X-Filename", "a.stl")
	if w.Code != 403 {
		t.Fatalf("403 이어야 한다. got=%d %s", w.Code, w.Body)
	}
}

// 파생물 버킷이 설정 안 됐으면 조용히 원본에 쓰지 말고 404 를 내야 한다.
// 설정 누락과 정상 동작이 같아 보이면 아무도 모른 채 원본이 더러워진다.
func TestDerivedDisabledWhenNotConfigured(t *testing.T) {
	r := newRig(t)
	r.g.der = nil

	w := r.do(t, "POST", "/svc/v1/derived", mintDerived(t),
		bytes.NewReader([]byte("x")), "X-Filename", "a.stl")
	if w.Code != 404 {
		t.Fatalf("404 여야 한다. got=%d %s", w.Code, w.Body)
	}
	if len(r.callbacks()) != 0 {
		t.Error("I-1 이 가면 안 된다")
	}
	g := r.do(t, "GET", "/svc/v1/derived/"+prefix+"/x", mint(t, func(c *ticket.Claims) {
		c.Purpose = "download"
	}), nil)
	if g.Code != 404 {
		t.Errorf("내려받기도 404 여야 한다. got=%d", g.Code)
	}
}

// 올린 것을 다시 받을 수 있어야 한다. 티켓 접두사 밖은 못 본다.
func TestGetDerived(t *testing.T) {
	r := newRig(t)
	body := []byte("solid mesh")
	w := r.do(t, "POST", "/svc/v1/derived", mintDerived(t),
		bytes.NewReader(body), "X-Filename", "m.stl")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	key := decode(t, w)["object_key"].(string)

	dl := mint(t, func(c *ticket.Claims) { c.Purpose = "download" })
	g := r.do(t, "GET", "/svc/v1/derived/"+key, dl, nil)
	if g.Code != 200 {
		t.Fatalf("200 이어야 한다. got=%d %s", g.Code, g.Body)
	}
	if !bytes.Equal(g.Body.Bytes(), body) {
		t.Error("내려받은 내용이 다르다")
	}

	// 같은 키를 원본 경로로 받으면 없어야 한다 — 버킷이 갈려 있다는 증거
	o := r.do(t, "GET", "/svc/v1/files/"+key,
		mint(t, func(c *ticket.Claims) { c.Purpose = "download" }), nil)
	if o.Code != 404 {
		t.Errorf("원본 경로에서는 404 여야 한다. got=%d", o.Code)
	}
}

// ── DICOM 내려받기 ──────────────────────────────────────────────────

// withOrthanc — 가짜 Orthanc 를 붙인다. "메서드 경로" → 돌려줄 본문. 없는 경로는 404.
func (r *rig) withOrthanc(t *testing.T, routes map[string]string) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		body, ok := routes[req.Method+" "+req.URL.Path]
		if !ok {
			w.WriteHeader(404)
			return
		}
		w.Write([]byte(body))
	}))
	t.Cleanup(srv.Close)
	r.g.or = orthanc.New(srv.URL, "", "")
}

func dicomTicket(t *testing.T, scope string) string {
	return mint(t, func(c *ticket.Claims) { c.Purpose = "download"; c.ObjectKeyPrefix = scope })
}

func TestDicomInstanceDownload(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{
		"POST /tools/lookup":         `[{"ID":"inst-1","Type":"Instance"}]`,
		"GET /instances/inst-1/file": "DICM원본",
	})
	w := r.do(t, "GET", "/svc/v1/dicom/instances/1.2.3", dicomTicket(t, "dicom/instances/1.2.3"), nil)
	if w.Code != 200 || w.Body.String() != "DICM원본" {
		t.Fatalf("%d %q", w.Code, w.Body.String())
	}
}

func TestDicomSeriesDownload(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{"GET /series/ab-1/archive": "PK시리즈zip"})
	w := r.do(t, "GET", "/svc/v1/dicom/series/ab-1", dicomTicket(t, "dicom/series/ab-1"), nil)
	if w.Code != 200 || w.Body.String() != "PK시리즈zip" {
		t.Fatalf("%d %q", w.Code, w.Body.String())
	}
}

// 접두사로 시작만 보면 ab-1 티켓으로 ab-12 를 연다. 다른 종류(인스턴스 ↔ 시리즈)도 막는다.
func TestDicomRejectsOtherScope(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{"GET /series/ab-12/archive": "남의 시리즈"})
	for _, c := range []struct{ path, scope string }{
		{"/svc/v1/dicom/series/ab-12", "dicom/series/ab-1"},
		{"/svc/v1/dicom/series/ab-12", "dicom/instances/ab-12"},
	} {
		if w := r.do(t, "GET", c.path, dicomTicket(t, c.scope), nil); w.Code != 403 {
			t.Errorf("%s 를 %s 티켓으로 %d", c.path, c.scope, w.Code)
		}
	}
}

// Orthanc 경로에 그대로 들어가는 값이다. 형식 밖 글자는 Orthanc 에 닿기 전에 거절한다.
func TestDicomRejectsBadID(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{})
	for _, p := range []string{
		"/svc/v1/dicom/series/..%2Fsystem",
		"/svc/v1/dicom/instances/1.2.3%2F..",
	} {
		if w := r.do(t, "GET", p, dicomTicket(t, "dicom/series/x"), nil); w.Code != 400 {
			t.Errorf("%s → %d", p, w.Code)
		}
	}
}

func TestDicomInstanceNotFound(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{"POST /tools/lookup": `[]`})
	w := r.do(t, "GET", "/svc/v1/dicom/instances/9.9", dicomTicket(t, "dicom/instances/9.9"), nil)
	if w.Code != 404 {
		t.Fatalf("없는 인스턴스에 %d", w.Code)
	}
}

// ── DICOM 은 Orthanc 에만 ─────────────────────────────────────────────

// garageHas — FS 저장소에 그 키의 파일이 남아 있는가.
func (r *rig) garageHas(key string) bool {
	_, err := os.Stat(filepath.Join(r.root, filepath.FromSlash(key)))
	return err == nil
}

// Orthanc 가 시리즈 ID 를 주고 I-2 가 성공하면 Garage 사본이 사라진다.
func TestDicomDeletedFromGarageAfterOrthanc(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{
		"POST /instances": `{"ID":"inst-1","ParentSeries":"ser-1","ParentStudy":"st-1","Status":"Success"}`,
	})
	w := r.do(t, "POST", "/svc/v1/files", mint(t),
		bytes.NewReader(mgDICOM("1.2.3.SOP", "R", "CC", `0.07\0.07`)), "X-Filename", "a.dcm")
	if w.Code != 201 {
		t.Fatalf("%d %s", w.Code, w.Body)
	}
	key := decode(t, w)["object_key"].(string)
	if r.garageHas(key) {
		t.Errorf("Orthanc 저장 뒤에도 Garage 에 사본이 남았다: %s", key)
	}
	if len(r.dicoms()) != 1 || r.dicoms()[0].Dicom.OrthancSeriesID != "ser-1" {
		t.Errorf("I-2 에 Orthanc 시리즈 ID 가 안 실렸다")
	}
}

// I-2 가 실패하면 DB 가 아직 Garage 를 가리키므로 지우면 안 된다.
func TestDicomKeptWhenI2Fails(t *testing.T) {
	r := newRig(t)
	r.failPath = "/internal/v1/dicom-instances"
	r.withOrthanc(t, map[string]string{
		"POST /instances": `{"ID":"inst-1","ParentSeries":"ser-1","Status":"Success"}`,
	})
	w := r.do(t, "POST", "/svc/v1/files", mint(t),
		bytes.NewReader(mgDICOM("1.2.3.SOP", "R", "CC", `0.07\0.07`)), "X-Filename", "a.dcm")
	if key := decode(t, w)["object_key"].(string); !r.garageHas(key) {
		t.Errorf("I-2 실패인데 Garage 사본을 지웠다: %s", key)
	}
}

// Orthanc 가 ID 없이 답하면(409 중복 등) 어디에 있는지 모르므로 남긴다.
func TestDicomKeptWhenOrthancHasNoID(t *testing.T) {
	r := newRig(t)
	r.withOrthanc(t, map[string]string{"POST /instances": `{"Status":"Success"}`})
	w := r.do(t, "POST", "/svc/v1/files", mint(t),
		bytes.NewReader(mgDICOM("1.2.3.SOP", "R", "CC", `0.07\0.07`)), "X-Filename", "a.dcm")
	if key := decode(t, w)["object_key"].(string); !r.garageHas(key) {
		t.Errorf("Orthanc ID 가 없는데 Garage 사본을 지웠다: %s", key)
	}
}
