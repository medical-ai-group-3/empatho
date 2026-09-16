package dicom

import (
	"bytes"
	"encoding/binary"
	"io"
	"strings"
	"testing"
)

// ── DICOM 을 손으로 지어내는 도구 ────────────────────────────────────
//
// 시험용 DICOM 을 저장소에서 가져올 수 없다. CBIS-DDSM 은 재배포 금지고
// EMBED 는 DUA 로 묶여 있다. 그래서 바이트를 직접 쌓는다.
// 어차피 파서가 봐야 하는 것은 바이트 배치라 이게 더 정확하다.

type builder struct {
	buf      bytes.Buffer
	explicit bool
	bo       binary.ByteOrder
}

func newB(explicit bool, bo binary.ByteOrder) *builder {
	b := &builder{explicit: explicit, bo: bo}
	b.buf.Write(make([]byte, 128)) // 서두
	b.buf.WriteString("DICM")
	return b
}

func (b *builder) el(g, e uint16, vr, val string) {
	v := []byte(val)
	if len(v)%2 == 1 {
		v = append(v, 0) // DICOM 값은 짝수 길이여야 한다
	}
	b.raw(g, e, vr, v)
}

func (b *builder) us(g, e uint16, n uint16) {
	v := make([]byte, 2)
	b.bo.PutUint16(v, n)
	b.raw(g, e, "US", v)
}

func (b *builder) raw(g, e uint16, vr string, v []byte) {
	binary.Write(&b.buf, b.bo, g)
	binary.Write(&b.buf, b.bo, e)
	if !b.explicit {
		binary.Write(&b.buf, b.bo, uint32(len(v)))
		b.buf.Write(v)
		return
	}
	b.buf.WriteString(vr)
	if longVR[vr] {
		binary.Write(&b.buf, b.bo, uint16(0))
		binary.Write(&b.buf, b.bo, uint32(len(v)))
	} else {
		binary.Write(&b.buf, b.bo, uint16(len(v)))
	}
	b.buf.Write(v)
}

// meta — 파일 메타 그룹. 전송 구문과 무관하게 항상 명시적 VR LE 다.
func (b *builder) meta(ts string) {
	save, sbo := b.explicit, b.bo
	b.explicit, b.bo = true, binary.LittleEndian
	b.el(0x0002, 0x0002, "UI", "1.2.840.10008.5.1.4.1.1.1.2") // 유방촬영 SOP Class
	b.el(0x0002, 0x0003, "UI", "1.2.3.4.5")
	b.el(0x0002, 0x0010, "UI", ts)
	b.explicit, b.bo = save, sbo
}

func (b *builder) bytes() []byte { return b.buf.Bytes() }

// 전형적인 유방촬영 한 장
func mammo(explicit bool, bo binary.ByteOrder, ts string) []byte {
	b := newB(explicit, bo)
	b.meta(ts)
	b.el(0x0008, 0x0016, "UI", "1.2.840.10008.5.1.4.1.1.1.2")
	b.el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.7")
	b.el(0x0008, 0x0020, "DA", "20260901")
	b.el(0x0008, 0x0060, "CS", "MG")
	b.el(0x0008, 0x0070, "LO", "HOLOGIC, Inc.")
	b.el(0x0010, 0x0010, "PN", "홍^길동") // 환자 이름 — 일부러 안 담아야 한다
	b.el(0x0010, 0x0020, "LO", "P-77")
	b.el(0x0018, 0x1164, "DS", `0.07\0.07`) // ImagerPixelSpacing
	b.el(0x0018, 0x5101, "CS", "MLO")
	b.el(0x0020, 0x000D, "UI", "1.2.3.4")
	b.el(0x0020, 0x000E, "UI", "1.2.3.4.5")
	b.el(0x0020, 0x0062, "CS", "L")
	b.el(0x0028, 0x0004, "CS", "MONOCHROME2")
	b.us(0x0028, 0x0010, 4096) // Rows
	b.us(0x0028, 0x0011, 3328) // Columns
	b.us(0x0028, 0x0100, 16)
	b.us(0x0028, 0x0101, 12)
	b.el(0x0028, 0x0301, "CS", "NO")
	b.el(0x0028, 0x0030, "DS", `0.1\0.1`) // PixelSpacing — 뒤에 와도 무시돼야 한다
	b.raw(0x7FE0, 0x0010, "OW", bytes.Repeat([]byte{0xAB}, 4096))
	return b.bytes()
}

func mustParse(t *testing.T, raw []byte) *Meta {
	t.Helper()
	m, err := Parse(bytes.NewReader(raw), 0)
	if err != nil {
		t.Fatalf("파싱 실패: %v", err)
	}
	return m
}

// ── 시험 ────────────────────────────────────────────────────────────

func TestParseExplicitLE(t *testing.T) {
	m := mustParse(t, mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1"))

	for _, c := range []struct{ name, got, want string }{
		{"SOPInstanceUID", m.SOPInstanceUID, "1.2.3.4.5.6.7"},
		{"StudyInstanceUID", m.StudyInstanceUID, "1.2.3.4"},
		{"SeriesInstanceUID", m.SeriesInstanceUID, "1.2.3.4.5"},
		{"PatientID", m.PatientID, "P-77"},
		{"Modality", m.Modality, "MG"},
		{"StudyDate", m.StudyDate, "20260901"},
		{"Laterality", m.Laterality, "L"},
		{"ViewPosition", m.ViewPosition, "MLO"},
		{"Photometric", m.PhotometricInterp, "MONOCHROME2"},
		{"TransferSyntax", m.TransferSyntaxUID, "1.2.840.10008.1.2.1"},
	} {
		if c.got != c.want {
			t.Errorf("%s = %q (%q 여야 한다)", c.name, c.got, c.want)
		}
	}
	if m.Rows != 4096 || m.Columns != 3328 {
		t.Errorf("크기 = %dx%d (4096x3328 이어야 한다)", m.Rows, m.Columns)
	}
	if m.BitsAllocated != 16 || m.BitsStored != 12 {
		t.Errorf("비트 = %d/%d", m.BitsAllocated, m.BitsStored)
	}
}

// 암시적 VR 은 VR 이 안 적혀 있어 길이 필드 위치가 다르다.
// 여기를 틀리면 전부 어긋나는데 **오류 없이 엉뚱한 값이 들어간다.**
func TestParseImplicitLE(t *testing.T) {
	m := mustParse(t, mammo(false, binary.LittleEndian, "1.2.840.10008.1.2"))
	if m.SOPInstanceUID != "1.2.3.4.5.6.7" || m.PatientID != "P-77" {
		t.Errorf("암시적 VR 을 잘못 읽었다: %+v", m)
	}
	if m.Rows != 4096 || m.Columns != 3328 {
		t.Errorf("암시적 VR 에서 크기가 틀렸다: %dx%d", m.Rows, m.Columns)
	}
	if m.ViewPosition != "MLO" || m.Laterality != "L" {
		t.Errorf("암시적 VR 에서 좌우/방향이 틀렸다: %q %q",
			m.Laterality, m.ViewPosition)
	}
}

func TestParseExplicitBE(t *testing.T) {
	m := mustParse(t, mammo(true, binary.BigEndian, "1.2.840.10008.1.2.2"))
	if m.SOPInstanceUID != "1.2.3.4.5.6.7" {
		t.Errorf("빅엔디안을 잘못 읽었다: %+v", m)
	}
	if m.Rows != 4096 {
		t.Errorf("빅엔디안 US 를 잘못 읽었다: %d", m.Rows)
	}
}

// 압축 전송 구문이어도 **머리말은 명시적 VR LE** 라 그대로 읽혀야 한다.
// CBIS-DDSM 이 JPEG 무손실이라 이게 안 되면 우리 데이터가 통째로 안 읽힌다.
func TestParseCompressedTransferSyntax(t *testing.T) {
	for _, ts := range []string{
		"1.2.840.10008.1.2.4.70", // JPEG 무손실
		"1.2.840.10008.1.2.4.90", // JPEG2000 무손실
		"1.2.840.10008.1.2.5",    // RLE
	} {
		m := mustParse(t, mammo(true, binary.LittleEndian, ts))
		if m.SOPInstanceUID != "1.2.3.4.5.6.7" || m.Rows != 4096 {
			t.Errorf("%s 머리말을 못 읽었다: %+v", ts, m)
		}
	}
}

// ⚠ 이게 이 파서에서 제일 중요한 시험이다.
//
// 미세석회 민감도는 해상도에 직접 걸린다 — 같은 모델·같은 운영점으로
// @1FP 가 CBIS 57.9% → VinDr 43.2% 였고, 1.42배로 키우니 54.6% 로
// 78% 가 회복됐다. 그러니 들어온 영상의 mm/px 를 여기서 못 뽑으면
// 뒤쪽 판독 결과를 믿을 근거가 없다.
func TestPixelSpacing(t *testing.T) {
	m := mustParse(t, mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1"))
	if !m.HasSpacing() {
		t.Fatal("화소 간격을 못 뽑았다")
	}
	// ImagerPixelSpacing 이 PixelSpacing 보다 우선이어야 한다.
	// 맘모는 촬영기 간격이 맞고, PixelSpacing 은 재구성 후 값이라 다를 수 있다.
	if m.PixelSpacing[0] != 0.07 || m.PixelSpacingTag != "ImagerPixelSpacing" {
		t.Errorf("간격 = %v (%s) — ImagerPixelSpacing 0.07 이어야 한다",
			m.PixelSpacing, m.PixelSpacingTag)
	}
}

// CBIS-DDSM 에는 화소 간격이 아예 없다(필름 스캔). 없으면 없다고 나와야지
// 0 이나 엉뚱한 값이 들어가면 안 된다.
func TestPixelSpacingAbsent(t *testing.T) {
	b := newB(true, binary.LittleEndian)
	b.meta("1.2.840.10008.1.2.1")
	b.el(0x0008, 0x0018, "UI", "1.2.3")
	b.el(0x0020, 0x000D, "UI", "1.2")
	b.us(0x0028, 0x0010, 5000)
	m := mustParse(t, b.bytes())
	if m.HasSpacing() {
		t.Errorf("없는 간격을 지어냈다: %v", m.PixelSpacing)
	}
	if m.PixelSpacingTag != "" {
		t.Errorf("출처 태그가 남았다: %q", m.PixelSpacingTag)
	}
}

func TestPixelSpacingMalformed(t *testing.T) {
	for _, bad := range []string{"0.07", `0.07\`, `a\b`, `0\0`, "", `-1\-1`} {
		b := newB(true, binary.LittleEndian)
		b.meta("1.2.840.10008.1.2.1")
		b.el(0x0008, 0x0018, "UI", "1.2.3")
		b.el(0x0018, 0x1164, "DS", bad)
		m := mustParse(t, b.bytes())
		if m.HasSpacing() {
			t.Errorf("%q 를 간격으로 받았다: %v", bad, m.PixelSpacing)
		}
	}
}

// 환자 이름은 담지 않는다. 가명화 정책이 정해지기 전에는 콜백 본문에도
// 로그에도 이름이 나가면 안 된다.
func TestPatientNameNotCaptured(t *testing.T) {
	raw := mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1")
	if !bytes.Contains(raw, []byte("홍^길동")) {
		t.Fatal("시험 자료에 이름이 안 들어갔다 — 시험이 의미 없다")
	}
	m := mustParse(t, raw)
	blob := strings.Join([]string{m.PatientID, m.Manufacturer, m.ModelName,
		m.BodyPart, m.Modality, m.SOPInstanceUID}, "|")
	if strings.Contains(blob, "홍") {
		t.Errorf("환자 이름이 Meta 로 새어 나왔다: %+v", m)
	}
}

// 시퀀스를 잘못 건너뛰면 그 뒤 태그가 전부 어긋난다.
// 오류가 안 나고 **값만 조용히 틀린다** — 그래서 반드시 시험해야 한다.
func TestSkipsSequences(t *testing.T) {
	b := newB(true, binary.LittleEndian)
	b.meta("1.2.840.10008.1.2.1")
	b.el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.7")

	// 길이가 정해진 시퀀스: 안에 SOPInstanceUID 를 하나 더 넣어 둔다.
	// 안쪽으로 파고들면 바깥 값을 덮어써서 시험이 깨진다.
	var inner bytes.Buffer
	ib := &builder{explicit: true, bo: binary.LittleEndian}
	ib.el(0x0008, 0x0018, "UI", "9.9.9.9")
	item := ib.buf.Bytes()
	binary.Write(&inner, binary.LittleEndian, uint16(0xFFFE))
	binary.Write(&inner, binary.LittleEndian, uint16(0xE000))
	binary.Write(&inner, binary.LittleEndian, uint32(len(item)))
	inner.Write(item)
	b.raw(0x0008, 0x1110, "SQ", inner.Bytes())

	b.el(0x0018, 0x5101, "CS", "CC")
	b.us(0x0028, 0x0010, 1234)
	m := mustParse(t, b.bytes())

	if m.SOPInstanceUID != "1.2.3.4.5.6.7" {
		t.Errorf("시퀀스 안쪽 값이 바깥을 덮었다: %q", m.SOPInstanceUID)
	}
	if m.ViewPosition != "CC" || m.Rows != 1234 {
		t.Errorf("시퀀스 뒤 태그가 어긋났다: %q %d", m.ViewPosition, m.Rows)
	}
}

// 길이 미정 시퀀스 — 구분자를 따라가야 한다
func TestSkipsUndefinedLengthSequence(t *testing.T) {
	b := newB(true, binary.LittleEndian)
	b.meta("1.2.840.10008.1.2.1")
	b.el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.7")

	w := func(g, e uint16, l uint32) {
		binary.Write(&b.buf, binary.LittleEndian, g)
		binary.Write(&b.buf, binary.LittleEndian, e)
		binary.Write(&b.buf, binary.LittleEndian, l)
	}
	b.buf.Write([]byte{0x08, 0x00, 0x10, 0x11}) // (0008,1110)
	b.buf.WriteString("SQ")
	binary.Write(&b.buf, binary.LittleEndian, uint16(0))
	binary.Write(&b.buf, binary.LittleEndian, uint32(0xFFFFFFFF))
	w(0xFFFE, 0xE000, 0xFFFFFFFF) // 항목 시작 (길이 미정)
	b.el(0x0008, 0x0018, "UI", "9.9.9.9")
	w(0xFFFE, 0xE00D, 0) // 항목 끝
	w(0xFFFE, 0xE0DD, 0) // 시퀀스 끝

	b.el(0x0018, 0x5101, "CS", "CC")
	m := mustParse(t, b.bytes())
	if m.SOPInstanceUID != "1.2.3.4.5.6.7" || m.ViewPosition != "CC" {
		t.Errorf("길이 미정 시퀀스를 잘못 건너뛰었다: %q %q",
			m.SOPInstanceUID, m.ViewPosition)
	}
}

// 서두 없이 DICM 으로 시작하는 파일
func TestNoPreamble(t *testing.T) {
	full := mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1")
	m := mustParse(t, full[128:]) // 서두 128바이트를 떼어낸다
	if m.SOPInstanceUID != "1.2.3.4.5.6.7" || m.ViewPosition != "MLO" {
		t.Errorf("서두 없는 파일을 못 읽었다: %+v", m)
	}
}

func TestRejectsNonDICOM(t *testing.T) {
	for name, raw := range map[string][]byte{
		"빈 파일": {},
		"PDF":  []byte("%PDF-1.7\n" + strings.Repeat("x", 300)),
		"짧은 것": []byte("DIC"),
		"서두만":  make([]byte, 200),
	} {
		if _, err := Parse(bytes.NewReader(raw), 0); err == nil {
			t.Errorf("%s 를 DICOM 으로 받았다", name)
		}
	}
}

// DICM 은 맞는데 알맹이가 없는 것도 거부해야 한다.
// 받아주면 식별자 없는 행이 DB 에 생긴다.
func TestRejectsEmptyDataset(t *testing.T) {
	b := newB(true, binary.LittleEndian)
	b.meta("1.2.840.10008.1.2.1")
	if _, err := Parse(bytes.NewReader(b.bytes()), 0); err == nil {
		t.Error("식별자가 없는데 통과시켰다")
	}
}

// 잘린 파일 — 오류를 내든 모은 것만 돌려주든, **멈춰야** 한다.
// 실제로 VinDr 에서 잘린 DICOM 2건을 겪었다(19,700,800 중 15,325,769 바이트).
func TestTruncatedDoesNotHang(t *testing.T) {
	full := mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1")
	for _, cut := range []int{140, 200, 260, 300, len(full) / 2} {
		if cut > len(full) {
			continue
		}
		done := make(chan struct{})
		go func() { defer close(done); Parse(bytes.NewReader(full[:cut]), 0) }()
		<-done // 걸리면 시험 전체가 시간 초과로 죽는다
	}
}

// 길이 필드에 쓰레기가 들어 있어도 상한 안에서 멈춰야 한다
func TestRespectsMaxRead(t *testing.T) {
	b := newB(true, binary.LittleEndian)
	b.meta("1.2.840.10008.1.2.1")
	b.el(0x0008, 0x0018, "UI", "1.2.3")
	b.el(0x0020, 0x000D, "UI", "1.2")
	// 4GB 짜리라고 주장하는 요소
	b.buf.Write([]byte{0x08, 0x00, 0x70, 0x00})
	b.buf.WriteString("LO")
	binary.Write(&b.buf, binary.LittleEndian, uint16(0xFFFE))

	cnt := &counting{r: bytes.NewReader(b.bytes())}
	if _, err := Parse(cnt, 4096); err != nil {
		t.Fatalf("파싱 실패: %v", err)
	}
	if cnt.n > 4096 {
		t.Errorf("상한 4096 을 넘겨 %d 바이트를 읽었다", cnt.n)
	}
}

type counting struct {
	r io.Reader
	n int64
}

func (c *counting) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += int64(n)
	return n, err
}

// ── MRI 3D 기하 (MRI 팀 요청 2026-09-02) ────────────────────────────

// mri — 슬라이스 하나. 축상면(axial) 기준이다.
func mri(explicit bool, bo binary.ByteOrder, pos, orient, thick, spacing string) []byte {
	b := newB(explicit, bo)
	// 머리말이 알리는 전송 구문과 실제 본문 부호화가 같아야 한다.
	// 어긋나면 본문 첫 요소부터 어긋나서 파일 전체를 못 읽는다.
	ts := "1.2.840.10008.1.2" // 암시적 VR 리틀 엔디안
	if explicit {
		ts = "1.2.840.10008.1.2.1"
	}
	b.meta(ts)
	b.el(0x0008, 0x0016, "UI", "1.2.840.10008.5.1.4.1.1.4") // MR Image Storage
	b.el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.8")
	b.el(0x0008, 0x0060, "CS", "MR")
	b.el(0x0010, 0x0020, "LO", "P-88")
	if thick != "" {
		b.el(0x0018, 0x0050, "DS", thick)
	}
	if spacing != "" {
		b.el(0x0018, 0x0088, "DS", spacing)
	}
	b.el(0x0020, 0x000D, "UI", "1.2.3.9")
	b.el(0x0020, 0x000E, "UI", "1.2.3.9.1")
	if pos != "" {
		b.el(0x0020, 0x0032, "DS", pos)
	}
	if orient != "" {
		b.el(0x0020, 0x0037, "DS", orient)
	}
	b.el(0x0028, 0x0004, "CS", "MONOCHROME2")
	b.us(0x0028, 0x0010, 256)
	b.us(0x0028, 0x0011, 256)
	b.el(0x0028, 0x0030, "DS", `0.7\0.7`)
	b.raw(0x7FE0, 0x0010, "OW", bytes.Repeat([]byte{0x11}, 512))
	return b.bytes()
}

func TestMRIGeometry(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian,
		`-95.5\-120.0\32.25`, `1\0\0\0\1\0`, "3.0", "3.6"))

	if m.Modality != "MR" {
		t.Fatalf("modality=%q", m.Modality)
	}
	want := []float64{-95.5, -120.0, 32.25}
	if len(m.ImagePositionPatient) != 3 {
		t.Fatalf("위치가 3개여야 한다. got=%v", m.ImagePositionPatient)
	}
	for i, w := range want {
		if m.ImagePositionPatient[i] != w {
			t.Errorf("위치[%d]=%v, want %v", i, m.ImagePositionPatient[i], w)
		}
	}
	if len(m.ImageOrientationPatient) != 6 {
		t.Fatalf("방향이 6개여야 한다. got=%v", m.ImageOrientationPatient)
	}
	if m.SliceThickness != 3.0 {
		t.Errorf("두께=%v, want 3.0", m.SliceThickness)
	}
	if m.SpacingBetweenSlices != 3.6 {
		t.Errorf("간격=%v, want 3.6", m.SpacingBetweenSlices)
	}
	if !m.HasGeometry() {
		t.Error("HasGeometry 가 true 여야 한다")
	}
}

// ⚠ 이게 이 묶음에서 제일 중요한 시험이다.
//
// 환자 좌표는 **음수가 정상값**이고, 축상면 방향 코사인(1\0\0\0\1\0)은
// 여섯 값 중 넷이 0 이다. 화소 간격용 파서(양수만 통과)를 그대로 쓰면
// 이 둘이 통째로 버려지고, MRI 재구성이 "태그가 없다" 로 실패한다.
// 겉보기에는 파싱이 성공하므로 아무 오류도 안 난다.
func TestMRIGeometryAcceptsNegativeAndZero(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian,
		`-95.5\-120.0\0`, `0\-1\0\0\0\-1`, "", ""))

	if len(m.ImagePositionPatient) != 3 {
		t.Fatal("음수·0 이 섞인 위치가 버려졌다")
	}
	if m.ImagePositionPatient[2] != 0 {
		t.Errorf("0 이 살아 있어야 한다. got=%v", m.ImagePositionPatient[2])
	}
	if len(m.ImageOrientationPatient) != 6 {
		t.Fatal("음수·0 이 섞인 방향이 버려졌다")
	}
	if m.ImageOrientationPatient[1] != -1 {
		t.Errorf("음수가 살아 있어야 한다. got=%v", m.ImageOrientationPatient[1])
	}
	if !m.HasGeometry() {
		t.Error("위치·방향이 다 있으면 HasGeometry 가 true 여야 한다")
	}
}

// 일부 장비가 음수 간격을 낸다(슬라이스 순서가 좌표 반대 방향일 때).
// 부호를 버리면 쌓는 순서가 뒤집힌다.
func TestMRINegativeSpacingKept(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian,
		`0\0\0`, `1\0\0\0\1\0`, "3.0", "-3.0"))
	if m.SpacingBetweenSlices != -3.0 {
		t.Errorf("음수 간격이 그대로 와야 한다. got=%v", m.SpacingBetweenSlices)
	}
}

// 반쪽은 통과시키지 않는다. 위치만 있으면 어느 방향 단면인지 모르고,
// 방향만 있으면 어디에 놓을지 모른다. 둘 중 하나면 재구성을 못 한다.
func TestMRIGeometryPartialIsNotEnough(t *testing.T) {
	only := mustParse(t, mri(true, binary.LittleEndian, `1\2\3`, "", "", ""))
	if only.HasGeometry() {
		t.Error("위치만 있으면 false 여야 한다")
	}
	orient := mustParse(t, mri(true, binary.LittleEndian, "", `1\0\0\0\1\0`, "", ""))
	if orient.HasGeometry() {
		t.Error("방향만 있으면 false 여야 한다")
	}
}

// 개수가 어긋난 값은 받지 않는다. 3개여야 할 좌표가 2개면 파일이 깨진
// 것이고, 반쪽으로 받아 두면 엉뚱한 위치에 슬라이스가 놓인다.
func TestMRIGeometryWrongCount(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian, `1\2`, `1\0\0\0\1`, "", ""))
	if m.ImagePositionPatient != nil {
		t.Errorf("2개짜리 위치는 버려야 한다. got=%v", m.ImagePositionPatient)
	}
	if m.ImageOrientationPatient != nil {
		t.Errorf("5개짜리 방향은 버려야 한다. got=%v", m.ImageOrientationPatient)
	}
	if m.HasGeometry() {
		t.Error("HasGeometry 가 false 여야 한다")
	}
}

// 암시적 VR 파일에도 붙어야 한다. 이 태그들은 VR 사전에 없어서 UN 으로
// 떨어지는데, 값 바이트는 그대로 읽히므로 문자열로 파싱된다.
func TestMRIGeometryImplicitVR(t *testing.T) {
	m := mustParse(t, mri(false, binary.LittleEndian,
		`-1.5\2.5\3.5`, `1\0\0\0\1\0`, "2.0", "2.0"))
	if !m.HasGeometry() {
		t.Fatalf("암시적 VR 에서도 읽혀야 한다. pos=%v orient=%v",
			m.ImagePositionPatient, m.ImageOrientationPatient)
	}
	if m.SliceThickness != 2.0 {
		t.Errorf("두께=%v, want 2.0", m.SliceThickness)
	}
}

// 맘모에는 이 값들이 없다. 없는 것이 정상이고 오류가 아니다.
func TestMammoHasNoGeometry(t *testing.T) {
	m := mustParse(t, mammo(true, binary.LittleEndian, "1.2.840.10008.1.2.1"))
	if m.HasGeometry() {
		t.Error("맘모는 3D 기하가 없어야 한다")
	}
	if m.SliceThickness != 0 {
		t.Errorf("두께가 0 이어야 한다. got=%v", m.SliceThickness)
	}
}

// 두께 0 은 "값 없음" 이지 "두께가 0" 이 아니다.
func TestMRIZeroThicknessRejected(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian, `0\0\0`, `1\0\0\0\1\0`, "0", "0"))
	if m.SliceThickness != 0 {
		t.Errorf("0 은 안 담아야 한다. got=%v", m.SliceThickness)
	}
	if m.SpacingBetweenSlices != 0 {
		t.Errorf("0 은 안 담아야 한다. got=%v", m.SpacingBetweenSlices)
	}
}
