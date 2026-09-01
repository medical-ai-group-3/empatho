// file-gateway — 명세 19-2. 바이트는 Django 를 안 거치고 여기로 흐른다.
//
//	G-F1  POST /svc/v1/upload/init                  청크 업로드 개시 → upload_id
//	G-F2  PUT  /svc/v1/upload/{upload_id}/part/{n}  청크 (개별 재시도 가능)
//	G-F3  POST /svc/v1/upload/{upload_id}/complete  병합 · sha256 · 커밋 → I-1
//	G-F4  POST /svc/v1/files                        단일 파일 (DICOM 낱장 · PDF) → I-1
//	G-F5  GET  /svc/v1/files/{object_key}           스트리밍 다운로드 (Range 지원)
//
// 지켜야 하는 것 (명세 19장)
//
//	· Go 는 Django 가 서명한 티켓만 검증한다. 자체 권한 판정 없음
//	· Go 는 Postgres 에 직접 안 쓴다. 커밋 결과는 I-1 콜백으로만
//	· object_key 는 **티켓의 object_key_prefix 에서만** 만든다.
//	  클라이언트가 준 이름을 그대로 쓰면 남의 자리에 쓸 수 있다.
//
// 아직 안 한 것 — G-F6(썸네일) · G-F7(DICOM 파싱 · Orthanc) · 19-5 피라미드
package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"

	"cdss/gosvc/internal/callback"
	"cdss/gosvc/internal/storage"
	"cdss/gosvc/internal/ticket"
	"cdss/gosvc/internal/upload"
)

type gw struct {
	st  storage.Store
	up  *upload.Manager
	cb  *callback.Client
	tv  *ticket.Verifier
	cls string // storage_class
}

func main() {
	addr := env("GW_ADDR", ":8091")
	tkey, cbBase, cbSec := os.Getenv("TICKET_KEY"),
		os.Getenv("CALLBACK_BASE"), os.Getenv("CALLBACK_SECRET")
	if tkey == "" || cbBase == "" || cbSec == "" {
		log.Fatal("TICKET_KEY · CALLBACK_BASE · CALLBACK_SECRET 이 필요하다")
	}
	st, err := makeStore()
	if err != nil {
		log.Fatalf("저장소: %v", err)
	}
	um, err := upload.NewManager(env("GW_SPOOL", "/var/tmp/gw-spool"), 24*time.Hour)
	if err != nil {
		log.Fatalf("스풀: %v", err)
	}
	g := &gw{st: st, up: um,
		cb:  callback.New(cbBase, []byte(cbSec), os.Getenv("CALLBACK_CERT"), os.Getenv("CALLBACK_KEY"), 4),
		tv:  ticket.NewVerifier([]byte(tkey)),
		cls: env("GW_STORAGE_CLASS", "standard")}

	// 버려진 청크 세션 청소. 안 하면 스풀이 계속 찬다.
	go func() {
		for range time.Tick(30 * time.Minute) {
			if n := um.Sweep(); n > 0 {
				log.Printf("[gw] 버려진 업로드 세션 %d개 정리", n)
			}
		}
	}()

	log.Printf("file-gateway %s · bucket %s", addr, st.Bucket())
	log.Fatal((&http.Server{Addr: addr, Handler: g.routes(),
		ReadHeaderTimeout: 10 * time.Second}).ListenAndServe())
}

// routes — 경로를 main 에서 떼어 놓는다. 시험이 이 함수를 그대로 쓴다.
// 서버가 실제로 받는 것과 시험이 두드리는 것이 같아야 한다.
func (g *gw) routes() *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /svc/v1/upload/init", g.initUpload)
	mux.HandleFunc("PUT /svc/v1/upload/{id}/part/{n}", g.putPart)
	mux.HandleFunc("POST /svc/v1/upload/{id}/complete", g.complete)
	mux.HandleFunc("POST /svc/v1/files", g.putFile)
	mux.HandleFunc("GET /svc/v1/files/{key...}", g.getFile)
	mux.HandleFunc("GET /svc/v1/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, 200, map[string]any{"ok": true, "bucket": g.st.Bucket()})
	})
	return mux
}

func makeStore() (storage.Store, error) {
	if root := os.Getenv("GW_LOCAL_ROOT"); root != "" {
		log.Printf("[gw] ⚠ 로컬 디스크 저장소 (%s). 개발용이다", root)
		return storage.NewFS(root), nil
	}
	return storage.NewS3(
		env("GARAGE_ENDPOINT", "127.0.0.1:3900"),
		os.Getenv("GARAGE_ACCESS_KEY"), os.Getenv("GARAGE_SECRET_KEY"),
		env("GARAGE_BUCKET", "cdss"), env("GARAGE_REGION", "garage"),
		os.Getenv("GARAGE_SSL") == "1")
}

// ── 티켓 ────────────────────────────────────────────────────────────
func (g *gw) auth(w http.ResponseWriter, r *http.Request, want ...string) *ticket.Claims {
	cl, err := g.tv.Verify(bearer(r))
	if err != nil {
		code, status := 401, "TICKET_EXPIRED"
		switch {
		case errors.Is(err, ticket.ErrReplayed):
			status = "TICKET_REPLAYED"
		case errors.Is(err, ticket.ErrSignature), errors.Is(err, ticket.ErrMalformed):
			status = "TICKET_INVALID"
		}
		fail(w, code, status, err.Error())
		return nil
	}
	if len(want) > 0 {
		ok := false
		for _, p := range want {
			if cl.Purpose == p {
				ok = true
			}
		}
		if !ok {
			fail(w, 403, "TICKET_SCOPE_MISMATCH",
				"티켓 purpose 가 "+cl.Purpose+" 다")
			return nil
		}
	}
	if cl.ObjectKeyPrefix == "" {
		fail(w, 403, "TICKET_SCOPE_MISMATCH",
			"티켓에 object_key_prefix 가 없다 — Django 가 확정해서 내려줘야 한다")
		return nil
	}
	return cl
}

// keyFor — object_key 는 **티켓 접두사 + 우리가 만든 이름** 이다.
// 클라이언트가 준 파일명은 확장자만 참고하고 경로로 쓰지 않는다.
// 그래야 남의 자리에 못 쓴다.
func keyFor(cl *ticket.Claims, filename string) string {
	// 확장자만 뽑는다. 경로 구분자·상위 참조가 섞여 들어오면 버린다.
	ext := strings.ToLower(path.Ext(path.Base(filepath.ToSlash(filename))))
	if len(ext) > 12 || strings.ContainsAny(ext, `/\`) || strings.Contains(ext, "..") {
		ext = ""
	}
	var b [12]byte
	rand.Read(b[:])
	return strings.TrimSuffix(cl.ObjectKeyPrefix, "/") + "/" +
		hex.EncodeToString(b[:]) + ext
}

// ── G-F1 ────────────────────────────────────────────────────────────
func (g *gw) initUpload(w http.ResponseWriter, r *http.Request) {
	cl := g.auth(w, r, "wsi_upload", "dicom_upload")
	if cl == nil {
		return
	}
	var req struct {
		Filename string `json:"filename"`
	}
	json.NewDecoder(io.LimitReader(r.Body, 1<<16)).Decode(&req)

	var b [16]byte
	rand.Read(b[:])
	id := hex.EncodeToString(b[:])
	s := g.up.Init(id, keyFor(cl, req.Filename), cl.ContentType,
		cl.PatientID, cl.ScopeID, cl.MaxBytes)
	log.Printf("[G-F1] upload=%s scope=%s max=%d", id, cl.ScopeID, cl.MaxBytes)
	writeJSON(w, 200, map[string]any{
		"upload_id": s.ID, "max_bytes": s.MaxBytes,
		"content_type": s.ContentType,
	})
}

// ── G-F2 ────────────────────────────────────────────────────────────
func (g *gw) putPart(w http.ResponseWriter, r *http.Request) {
	if g.auth(w, r, "wsi_upload", "dicom_upload") == nil {
		return
	}
	s, ok := g.up.Get(r.PathValue("id"))
	if !ok {
		fail(w, 404, "UPLOAD_NOT_FOUND", "개시되지 않은 업로드다")
		return
	}
	n, err := upload.ParsePart(r.PathValue("n"))
	if err != nil {
		fail(w, 400, "BAD_PART_NUMBER", err.Error())
		return
	}
	sz, err := g.up.WritePart(s, n, r.Body)
	if err != nil {
		if errors.Is(err, upload.ErrTooBig) {
			fail(w, 413, "UPLOAD_TOO_LARGE",
				"티켓 max_bytes 를 넘는다")
			return
		}
		fail(w, 500, "PART_WRITE_FAILED", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"part": n, "bytes": sz})
}

// ── G-F3 ────────────────────────────────────────────────────────────
func (g *gw) complete(w http.ResponseWriter, r *http.Request) {
	if g.auth(w, r, "wsi_upload", "dicom_upload") == nil {
		return
	}
	s, ok := g.up.Get(r.PathValue("id"))
	if !ok {
		fail(w, 404, "UPLOAD_NOT_FOUND", "개시되지 않은 업로드다")
		return
	}
	// 성공하든 실패하든 조각은 지운다
	defer g.up.Cleanup(s.ID)

	sum, total, err := g.up.Assemble(s, func(rd io.Reader, size int64, ct string) error {
		return g.st.Put(r.Context(), s.ObjectKey, rd, size, ct)
	})
	if err != nil {
		fail(w, 400, "ASSEMBLE_FAILED", err.Error())
		return
	}
	g.commit(w, r, s.ObjectKey, sum, total, s.ContentType, s.PatientID, s.ScopeID)
}

// ── G-F4 ────────────────────────────────────────────────────────────
func (g *gw) putFile(w http.ResponseWriter, r *http.Request) {
	cl := g.auth(w, r, "dicom_upload", "report_pdf", "prescription_pdf")
	if cl == nil {
		return
	}
	max := cl.MaxBytes
	if max <= 0 {
		max = 1 << 30
	}
	// 받으면서 해시하고, 받으면서 상한을 잰다.
	//
	// 다 받은 뒤에 크기를 재면 상한을 넘는 파일도 일단 저장소에 다 올라간다.
	// 그러면 Garage 는 이미 몇 GB 를 먹었고 지우는 것은 뒷수습이다.
	// capReader 는 상한을 넘는 순간 읽기를 실패시켜 Put 자체를 중단시킨다.
	h := sha256.New()
	key := keyFor(cl, r.Header.Get("X-Filename"))
	cr := &capReader{r: r.Body, limit: max}
	ct := cl.ContentType
	if ct == "" {
		ct = r.Header.Get("Content-Type")
	}
	if err := g.st.Put(r.Context(), key, io.TeeReader(cr, h), -1, ct); err != nil {
		// 중단된 자리에 조각이 남았을 수 있다. 저장소 구현에 맡기지 않고 지운다.
		g.st.Delete(r.Context(), key)
		if errors.Is(err, upload.ErrTooBig) {
			fail(w, 413, "UPLOAD_TOO_LARGE", "티켓 max_bytes 를 넘는다")
			return
		}
		fail(w, 500, "PUT_FAILED", err.Error())
		return
	}
	g.commit(w, r, key, hex.EncodeToString(h.Sum(nil)), cr.read, ct,
		cl.PatientID, cl.ScopeID)
}

// capReader — limit 바이트를 넘겨 읽는 순간 ErrTooBig 를 낸다.
// io.LimitReader 는 조용히 EOF 를 내서 **잘린 파일이 정상처럼 저장된다.**
// 잘린 DICOM 을 정상으로 커밋하는 것이 이 계통에서 제일 나쁜 결과라 직접 짠다.
type capReader struct {
	r     io.Reader
	limit int64
	read  int64
}

func (c *capReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.read += int64(n)
	if c.limit > 0 && c.read > c.limit {
		return n, upload.ErrTooBig
	}
	return n, err
}

// commit — I-1 콜백. 여기가 'Django 에 알리는' 자리다.
//
// 콜백이 실패하면 Garage 에는 있는데 DB 에 없는 고아 객체가 된다.
// 명세 21장이 그 상태를 정상으로 취급하지 말라고 못 박았으므로 502 로 알린다.
func (g *gw) commit(w http.ResponseWriter, r *http.Request,
	key, sum string, size int64, ct, patient, scope string) {
	obj := callback.StorageObject{
		Bucket: g.st.Bucket(), ObjectKey: key, ChecksumSHA256: sum,
		ByteSize: size, ContentType: ct, StorageClass: g.cls,
		PatientID: patient, ScopeID: scope,
	}
	if err := g.cb.PostStorageObject(r.Context(), obj); err != nil {
		log.Printf("[gw] ✗ I-1 실패 key=%s — 고아 객체가 된다: %v", key, err)
		fail(w, 502, "CALLBACK_FAILED",
			"파일은 저장했으나 Django 에 등록하지 못했다")
		return
	}
	log.Printf("[gw] 커밋 key=%s %d bytes sha=%s…", key, size, sum[:12])
	writeJSON(w, 201, map[string]any{
		"object_key": key, "bucket": obj.Bucket, "byte_size": size,
		"checksum_sha256": sum, "content_type": ct,
	})
}

// ── G-F5 ────────────────────────────────────────────────────────────
func (g *gw) getFile(w http.ResponseWriter, r *http.Request) {
	cl := g.auth(w, r, "download", "tile")
	if cl == nil {
		return
	}
	key := r.PathValue("key")
	// 티켓 접두사 밖의 객체는 못 읽는다. 이게 권한 경계다.
	if !strings.HasPrefix(key, strings.TrimSuffix(cl.ObjectKeyPrefix, "/")+"/") {
		fail(w, 403, "TICKET_SCOPE_MISMATCH", "티켓 범위 밖 객체다")
		return
	}
	rd, info, err := g.st.Open(r.Context(), key)
	if err != nil {
		fail(w, 404, "OBJECT_NOT_FOUND", err.Error())
		return
	}
	defer rd.Close()
	if info.ContentType != "" {
		w.Header().Set("Content-Type", info.ContentType)
	}
	if info.ETag != "" {
		w.Header().Set("ETag", info.ETag)
	}
	// Range · If-Range · 다중 구간을 직접 짜지 않는다. 반드시 틀린다.
	http.ServeContent(w, r, path.Base(key), info.ModTime, rd)
}

// ── 잡동사니 ────────────────────────────────────────────────────────
func env(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func bearer(r *http.Request) string {
	if h := r.Header.Get("Authorization"); strings.HasPrefix(h, "Bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return r.Header.Get("X-Ticket")
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, code int, status, detail string) {
	writeJSON(w, code, map[string]string{"code": status, "detail": detail})
}
