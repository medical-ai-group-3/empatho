// file-gateway — 명세 19-2. 바이트는 Django 를 안 거치고 여기로 흐른다.
//
//	G-F1  POST /svc/v1/upload/init                  청크 업로드 개시 → upload_id
//	G-F2  PUT  /svc/v1/upload/{upload_id}/part/{n}  청크 (개별 재시도 가능)
//	G-F3  POST /svc/v1/upload/{upload_id}/complete  병합 · sha256 · 커밋 → I-1
//	G-F4  POST /svc/v1/files                        단일 파일 (DICOM 낱장 · PDF) → I-1
//	G-F5  GET  /svc/v1/files/{object_key}           스트리밍 다운로드 (Range 지원)
//	G-F7  (경로 없음) 커밋 직후 DICOM 머리말 파싱 → I-2, Orthanc 전송
//
// 지켜야 하는 것 (명세 19장)
//
//	· Go 는 Django 가 서명한 티켓만 검증한다. 자체 권한 판정 없음
//	· Go 는 Postgres 에 직접 안 쓴다. 커밋 결과는 I-1 콜백으로만
//	· object_key 는 **티켓의 object_key_prefix 에서만** 만든다.
//	  클라이언트가 준 이름을 그대로 쓰면 남의 자리에 쓸 수 있다.
//
// 아직 안 한 것 — G-F6(썸네일) · 19-5 피라미드(G-F8~G-F12)
package main

import (
	"bytes"
	"context"
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
	"cdss/gosvc/internal/dicom"
	"cdss/gosvc/internal/httpx"
	"cdss/gosvc/internal/orthanc"
	"cdss/gosvc/internal/storage"
	"cdss/gosvc/internal/ticket"
	"cdss/gosvc/internal/upload"
)

type gw struct {
	st  storage.Store
	up  *upload.Manager
	cb  *callback.Client
	tv  *ticket.Verifier
	or  *orthanc.Client // nil 이면 Orthanc 전송을 건너뛴다
	cls string          // storage_class
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
		cb: callback.New(cbBase, []byte(cbSec), os.Getenv("CALLBACK_CERT"), os.Getenv("CALLBACK_KEY"), 4),
		tv: ticket.NewVerifier([]byte(tkey)),
		or: orthanc.New(os.Getenv("ORTHANC_URL"),
			os.Getenv("ORTHANC_USER"), os.Getenv("ORTHANC_PASS")),
		cls: env("GW_STORAGE_CLASS", "standard")}
	if g.or == nil {
		log.Printf("[gw] ORTHANC_URL 이 비어 있다 — DICOM 은 파싱해서 I-2 만 보내고 " +
			"Orthanc 전송은 건너뛴다")
	}

	// 버려진 청크 세션 청소. 안 하면 스풀이 계속 찬다.
	go func() {
		for range time.Tick(30 * time.Minute) {
			if n := um.Sweep(); n > 0 {
				log.Printf("[gw] 버려진 업로드 세션 %d개 정리", n)
			}
		}
	}()

	log.Printf("file-gateway %s · bucket %s", addr, st.Bucket())
	log.Fatal((&http.Server{Addr: addr,
		Handler:           httpx.CORS(g.routes(), os.Getenv("CORS_ORIGINS")),
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

// makeStore — 저장소를 고른다.
//
// ⚠ GW_LOCAL_ROOT 는 **개발용이다.** 이게 설정돼 있으면 Garage 를 무시하고
//
//	로컬 디스크에 쓴다. 그 상태로 배포되면 파일이 컨테이너 안에 쌓이고
//	재시작하면 사라지는데, **업로드는 201 로 성공하고 로그도 정상이다.**
//	아무도 모른 채 자료가 없어진다.
//
//	그래서 GW_DEV=1 을 함께 주지 않으면 기동을 거부한다. 개발자가 한 번 더
//	의도를 밝히게 하는 것이 목적이다 — .env 에 남은 줄 하나로 이런 일이
//	벌어지면 안 된다.
func makeStore() (storage.Store, error) {
	if root := os.Getenv("GW_LOCAL_ROOT"); root != "" {
		if os.Getenv("GW_DEV") != "1" {
			return nil, errors.New(
				"GW_LOCAL_ROOT 가 설정돼 있다. 이건 개발용 로컬 디스크 저장소라 " +
					"컨테이너가 재시작하면 파일이 사라진다. 정말 쓰려면 GW_DEV=1 을 " +
					"함께 줄 것. 운영이면 GW_LOCAL_ROOT 를 지우고 GARAGE_* 를 설정할 것")
		}
		log.Printf("[gw] ⚠ 로컬 디스크 저장소 (%s). 개발용이다 — "+
			"재시작하면 사라진다", root)
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

	// 흘려보내는 김에 앞부분만 따로 받아 둔다 — G-F7 이 이걸 파싱한다.
	// 다 올리고 나서 저장소에서 다시 읽으면 왕복이 한 번 더 생긴다.
	tap := &headTap{max: headBytes}
	sum, total, err := g.up.Assemble(s, func(rd io.Reader, size int64, ct string) error {
		return g.st.Put(r.Context(), s.ObjectKey, io.TeeReader(rd, tap), size, ct)
	})
	if err != nil {
		fail(w, 400, "ASSEMBLE_FAILED", err.Error())
		return
	}
	g.commit(w, r, s.ObjectKey, sum, total, s.ContentType, s.PatientID, s.ScopeID,
		tap.b.Bytes())
}

// headTap — 앞 max 바이트만 모으고 나머지는 버린다.
// DICOM 머리말은 수십 KB 면 충분하다. 수 GB 를 통째로 붙들 이유가 없다.
const headBytes = 1 << 20

type headTap struct {
	b   bytes.Buffer
	max int
}

func (h *headTap) Write(p []byte) (int, error) {
	if room := h.max - h.b.Len(); room > 0 {
		if len(p) < room {
			room = len(p)
		}
		h.b.Write(p[:room])
	}
	return len(p), nil
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
	tap := &headTap{max: headBytes}
	ct := cl.ContentType
	if ct == "" {
		ct = r.Header.Get("Content-Type")
	}
	if err := g.st.Put(r.Context(), key,
		io.TeeReader(cr, io.MultiWriter(h, tap)), -1, ct); err != nil {
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
		cl.PatientID, cl.ScopeID, tap.b.Bytes())
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
	key, sum string, size int64, ct, patient, scope string, head []byte) {
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

	res := map[string]any{
		"object_key": key, "bucket": obj.Bucket, "byte_size": size,
		"checksum_sha256": sum, "content_type": ct,
	}
	// G-F7 — I-1 이 성공한 뒤에만 부른다 (명세 21장 순서 보장)
	if meta := g.ingestDICOM(r.Context(), key, patient, scope, head); meta != nil {
		res["dicom"] = meta
	}
	writeJSON(w, 201, res)
}

// ── G-F7 ────────────────────────────────────────────────────────────
//
// DICOM 이면 머리말을 읽어 I-2 로 넘기고, Orthanc 가 설정돼 있으면 올린다.
//
// **실패해도 요청은 성공이다.** I-1 은 이미 끝났고 객체는 등록됐다.
// 메타는 나중에 객체를 다시 읽어 복구할 수 있지만, 여기서 502 를 내면
// 클라이언트가 재업로드를 해서 같은 파일이 두 벌 생긴다. 대신 응답에
// 무엇이 안 됐는지 담고 로그에 남긴다 — 조용히 삼키지는 않는다.
func (g *gw) ingestDICOM(ctx context.Context, key, patient, scope string,
	head []byte) map[string]any {
	if len(head) == 0 {
		return nil
	}
	m, err := dicom.Parse(bytes.NewReader(head), 0)
	if err != nil {
		// DICOM 이 아닌 것(PDF 등)은 정상이다. 조용히 넘어간다.
		return nil
	}
	out := map[string]any{
		"sop_instance_uid":   m.SOPInstanceUID,
		"study_instance_uid": m.StudyInstanceUID,
		"modality":           m.Modality,
	}
	// 화소 간격이 없으면 표시한다. 미세석회 판독이 여기에 걸린다 —
	// mm/px 를 모르면 해상도 보정을 할 수 없고 결과를 믿을 근거가 없다.
	if m.HasSpacing() {
		out["pixel_spacing_mm"] = m.PixelSpacing
	} else {
		out["pixel_spacing_mm"] = nil
		log.Printf("[G-F7] ⚠ key=%s 화소 간격 없음 — 해상도 보정 불가", key)
	}

	cm := callback.DicomMetadata{
		ObjectKey: key, Bucket: g.st.Bucket(),
		StudyInstanceUID: m.StudyInstanceUID, SeriesInstanceUID: m.SeriesInstanceUID,
		SOPInstanceUID: m.SOPInstanceUID, SOPClassUID: m.SOPClassUID,
		DicomPatientID: m.PatientID,
		Modality:       m.Modality, StudyDate: m.StudyDate, StudyTime: m.StudyTime,
		BodyPart: m.BodyPart, Manufacturer: m.Manufacturer, ModelName: m.ModelName,
		Laterality: m.Laterality, ViewPosition: m.ViewPosition,
		Rows: m.Rows, Columns: m.Columns,
		BitsAllocated: m.BitsAllocated, BitsStored: m.BitsStored,
		NumberOfFrames: m.NumberOfFrames, PhotometricInterp: m.PhotometricInterp,
		PixelSpacing: m.PixelSpacing, PixelSpacingTag: m.PixelSpacingTag,
		TransferSyntaxUID:  m.TransferSyntaxUID,
		BurnedInAnnotation: m.BurnedInAnnotation,
		PatientID:          patient, ScopeID: scope,
	}
	if id, err := g.toOrthanc(ctx, key); err != nil {
		log.Printf("[G-F7] Orthanc 전송 실패 key=%s: %v", key, err)
		out["orthanc"] = "failed"
	} else if id != "" {
		cm.OrthancInstanceID = id
		out["orthanc"] = id
	}

	if err := g.cb.PostDicomMetadata(ctx, cm); err != nil {
		log.Printf("[G-F7] ✗ I-2 실패 key=%s sop=%s — 객체는 등록됐으나 "+
			"메타가 없다. 객체를 다시 읽어 복구할 것: %v", key, m.SOPInstanceUID, err)
		out["metadata_registered"] = false
		return out
	}
	out["metadata_registered"] = true
	log.Printf("[G-F7] I-2 key=%s %s %s%s %dx%d",
		key, m.Modality, m.Laterality, m.ViewPosition, m.Columns, m.Rows)
	return out
}

// toOrthanc — 커밋된 객체를 저장소에서 다시 읽어 Orthanc 로 보낸다.
// 업로드 본문은 스트림으로 흘려보내서 메모리에 안 남는다.
func (g *gw) toOrthanc(ctx context.Context, key string) (string, error) {
	if g.or == nil {
		return "", nil
	}
	rd, _, err := g.st.Open(ctx, key)
	if err != nil {
		return "", err
	}
	defer rd.Close()
	res, err := g.or.Store(ctx, rd)
	if errors.Is(err, orthanc.ErrDuplicate) {
		// 재시도가 만든 중복이다. 실패가 아니다.
		if res != nil {
			return res.ID, nil
		}
		return "", nil
	}
	if err != nil {
		return "", err
	}
	return res.ID, nil
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
