package dicom

import (
	"bytes"
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"
)

// ── ViewCodeSequence(0054,0220) 로 촬영방향 알아내기 ─────────────────
//
// CMMD 같은 데이터셋은 (0018,5101) ViewPosition 을 안 쓰고 촬영방향을
// ViewCodeSequence 에만 적는다. 그걸 못 읽으면 view_position 이 비고
// Django 가 병변 id 를 "R-?-0" 으로 만들어 AI 상자가 영상에 안 붙는다.

// codeItem — (0008,0100) CodeValue · (0008,0102) CodingSchemeDesignator ·
// (0008,0104) CodeMeaning 을 담은 항목 본문. modifier 면 ViewModifierCodeSequence
// 를 **중첩 시퀀스**로 붙인다 — 그 안의 CodeValue 가 바깥을 덮으면 안 된다.
func codeItem(explicit bool, bo binary.ByteOrder, code, scheme, meaning string, modifier bool) []byte {
	ib := &builder{explicit: explicit, bo: bo}
	ib.el(0x0008, 0x0100, "SH", code)
	ib.el(0x0008, 0x0102, "SH", scheme)
	ib.el(0x0008, 0x0104, "LO", meaning)
	if modifier {
		mb := &builder{explicit: explicit, bo: bo}
		mb.el(0x0008, 0x0100, "SH", "399161006") // 촬영방향이 아닌 수식어 코드
		mb.el(0x0008, 0x0102, "SH", "SCT")
		ib.raw(0x0054, 0x0222, "SQ", seqItem(bo, mb.buf.Bytes()))
	}
	return ib.buf.Bytes()
}

// seqItem — 길이가 정해진 항목 하나
func seqItem(bo binary.ByteOrder, body []byte) []byte {
	var b bytes.Buffer
	binary.Write(&b, bo, uint16(0xFFFE))
	binary.Write(&b, bo, uint16(0xE000))
	binary.Write(&b, bo, uint32(len(body)))
	b.Write(body)
	return b.Bytes()
}

// mammoVC — ViewPosition 대신(또는 함께) ViewCodeSequence 를 가진 맘모 한 장.
// vp 가 "" 이면 (0018,5101) 을 안 넣는다. undefined 면 시퀀스·항목을 길이 미정으로 쓴다.
func mammoVC(explicit bool, bo binary.ByteOrder, ts, vp string, items [][]byte, undefined bool) []byte {
	b := newB(explicit, bo)
	b.meta(ts)
	b.el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.7")
	b.el(0x0008, 0x0060, "CS", "MG")
	if vp != "" {
		b.el(0x0018, 0x5101, "CS", vp)
	}
	b.el(0x0020, 0x000D, "UI", "1.2.3.4")
	b.el(0x0020, 0x0062, "CS", "R")
	b.us(0x0028, 0x0010, 2294) // Rows

	// (0054,0220) 은 (0028,xxxx) 뒤, PixelData 앞이다.
	if undefined {
		w := func(g, e uint16, l uint32) {
			binary.Write(&b.buf, bo, g)
			binary.Write(&b.buf, bo, e)
			binary.Write(&b.buf, bo, l)
		}
		binary.Write(&b.buf, bo, uint16(0x0054))
		binary.Write(&b.buf, bo, uint16(0x0220))
		if explicit {
			b.buf.WriteString("SQ")
			binary.Write(&b.buf, bo, uint16(0))
		}
		binary.Write(&b.buf, bo, uint32(0xFFFFFFFF))
		for _, it := range items {
			w(0xFFFE, 0xE000, 0xFFFFFFFF)
			b.buf.Write(it)
			w(0xFFFE, 0xE00D, 0)
		}
		w(0xFFFE, 0xE0DD, 0)
	} else {
		var seq []byte
		for _, it := range items {
			seq = append(seq, seqItem(bo, it)...)
		}
		b.raw(0x0054, 0x0220, "SQ", seq)
	}
	// 시퀀스 뒤 태그 — 스트림이 어긋나면 여기서 티가 난다
	b.el(0x0054, 0x0300, "LO", "after")
	b.us(0x6000, 0x0010, 7)
	b.raw(0x7FE0, 0x0010, "OW", bytes.Repeat([]byte{0xAB}, 64))
	return b.bytes()
}

func TestViewFromCodeSequence(t *testing.T) {
	le, be := binary.LittleEndian, binary.BigEndian
	const (
		tsELE = "1.2.840.10008.1.2.1"
		tsILE = "1.2.840.10008.1.2"
		tsEBE = "1.2.840.10008.1.2.2"
	)
	cc := func(e bool, bo binary.ByteOrder) []byte {
		return codeItem(e, bo, "399162004", "SCT", "cranio-caudal", false)
	}
	mlo := func(e bool, bo binary.ByteOrder) []byte {
		return codeItem(e, bo, "399368009", "SCT", "medio-lateral oblique", true)
	}
	cases := []struct {
		name      string
		explicit  bool
		bo        binary.ByteOrder
		ts        string
		vp        string
		items     [][]byte
		undefined bool
		want      string
	}{
		{"명시적LE·길이정함·CC", true, le, tsELE, "", [][]byte{cc(true, le)}, false, "CC"},
		{"명시적LE·길이미정·MLO+수식어", true, le, tsELE, "", [][]byte{mlo(true, le)}, true, "MLO"},
		{"명시적LE·길이정함·MLO+수식어", true, le, tsELE, "", [][]byte{mlo(true, le)}, false, "MLO"},
		{"암시적LE·길이정함·CC", false, le, tsILE, "", [][]byte{cc(false, le)}, false, "CC"},
		{"암시적LE·길이미정·MLO+수식어", false, le, tsILE, "", [][]byte{mlo(false, le)}, true, "MLO"},
		{"명시적BE·CC", true, be, tsEBE, "", [][]byte{cc(true, be)}, false, "CC"},
		{"첫 항목만 본다", true, le, tsELE, "", [][]byte{cc(true, le), mlo(true, le)}, true, "CC"},
		{"옛 SRT 코드", true, le, tsELE, "",
			[][]byte{codeItem(true, le, "R-10226", "SRT", "medio-lateral oblique", false)}, false, "MLO"},
		{"XCCL", true, le, tsELE, "",
			[][]byte{codeItem(true, le, "399192008", "SCT", "cranio-caudal exaggerated laterally", false)}, false, "XCCL"},
		{"ML", true, le, tsELE, "",
			[][]byte{codeItem(true, le, "399260004", "SCT", "medio-lateral", false)}, false, "ML"},
		{"모르는 코드는 비운다", true, le, tsELE, "",
			[][]byte{codeItem(true, le, "127457009", "SCT", "tissue specimen from breast", false)}, false, ""},
		{"다른 코딩 체계는 안 믿는다", true, le, tsELE, "",
			[][]byte{codeItem(true, le, "399162004", "LN", "?", false)}, false, ""},
		{"ViewPosition 이 이긴다", true, le, tsELE, "MLO", [][]byte{cc(true, le)}, false, "MLO"},
		{"ViewPosition 정리(공백·소문자)", true, le, tsELE, " cc", nil, false, "CC"},
		{"빈 시퀀스", true, le, tsELE, "", nil, false, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			m := mustParse(t, mammoVC(c.explicit, c.bo, c.ts, c.vp, c.items, c.undefined))
			if m.ViewPosition != c.want {
				t.Errorf("ViewPosition=%q, want %q", m.ViewPosition, c.want)
			}
			if m.Rows != 2294 || m.SOPInstanceUID != "1.2.3.4.5.6.7" || m.Laterality != "R" {
				t.Errorf("시퀀스 앞 태그가 틀렸다: rows=%d sop=%q lat=%q",
					m.Rows, m.SOPInstanceUID, m.Laterality)
			}
		})
	}
}

// 시퀀스를 읽은 뒤 스트림이 제자리여야 한다. 우리가 담는 태그를 시퀀스
// **뒤에** 두고(Rows · PixelSpacing) 그것이 제대로 읽히는지 본다.
func TestViewCodeSequenceKeepsStreamAligned(t *testing.T) {
	for _, undefined := range []bool{false, true} {
		b := newB(true, binary.LittleEndian)
		b.meta("1.2.840.10008.1.2.1")
		b.el(0x0008, 0x0018, "UI", "1.2.3")
		// 태그 순서를 일부러 어긴다 — 파서는 순서를 안 따지므로 뒤 태그를 볼 수 있다
		body := codeItem(true, binary.LittleEndian, "399368009", "SCT", "mlo", true)
		if undefined {
			b.buf.Write([]byte{0x54, 0x00, 0x20, 0x02})
			b.buf.WriteString("SQ")
			binary.Write(&b.buf, binary.LittleEndian, uint16(0))
			binary.Write(&b.buf, binary.LittleEndian, uint32(0xFFFFFFFF))
			binary.Write(&b.buf, binary.LittleEndian, []uint16{0xFFFE, 0xE000})
			binary.Write(&b.buf, binary.LittleEndian, uint32(0xFFFFFFFF))
			b.buf.Write(body)
			binary.Write(&b.buf, binary.LittleEndian, []uint16{0xFFFE, 0xE00D, 0, 0})
			binary.Write(&b.buf, binary.LittleEndian, []uint16{0xFFFE, 0xE0DD, 0, 0})
		} else {
			b.raw(0x0054, 0x0220, "SQ", seqItem(binary.LittleEndian, body))
		}
		b.us(0x0028, 0x0010, 555)
		b.el(0x0028, 0x0030, "DS", `0.1\0.1`)
		m := mustParse(t, b.bytes())
		if m.ViewPosition != "MLO" || m.Rows != 555 || !m.HasSpacing() {
			t.Errorf("undefined=%v: 시퀀스 뒤가 어긋났다 view=%q rows=%d spacing=%v",
				undefined, m.ViewPosition, m.Rows, m.PixelSpacing)
		}
	}
}

// 비-MG 는 ViewCodeSequence 가 없다. 아무것도 안 채워야 한다.
func TestNoViewForNonMammo(t *testing.T) {
	m := mustParse(t, mri(true, binary.LittleEndian, `0\0\0`, `1\0\0\0\1\0`, "2", "2"))
	if m.ViewPosition != "" {
		t.Errorf("MRI 에 촬영방향이 생겼다: %q", m.ViewPosition)
	}
}

// Laterality — ImageLaterality(0020,0062) 우선, 없거나 비면 Laterality(0020,0060).
func TestLateralityFallback(t *testing.T) {
	build := func(lat, imgLat *string) []byte {
		b := newB(true, binary.LittleEndian)
		b.meta("1.2.840.10008.1.2.1")
		b.el(0x0008, 0x0018, "UI", "1.2.3")
		if lat != nil {
			b.el(0x0020, 0x0060, "CS", *lat)
		}
		if imgLat != nil {
			b.el(0x0020, 0x0062, "CS", *imgLat)
		}
		return b.bytes()
	}
	s := func(v string) *string { return &v }
	for _, c := range []struct {
		name        string
		lat, imgLat *string
		want        string
	}{
		{"ImageLaterality 만", nil, s("L"), "L"},
		{"Laterality 만", s("R"), nil, "R"},
		{"둘 다 — ImageLaterality 우선", s("R"), s("L"), "L"},
		{"ImageLaterality 가 비었다", s("R"), s(""), "R"},
		{"소문자·공백 정리", nil, s("l "), "L"},
	} {
		t.Run(c.name, func(t *testing.T) {
			m := mustParse(t, build(c.lat, c.imgLat))
			if m.Laterality != c.want {
				t.Errorf("Laterality=%q, want %q", m.Laterality, c.want)
			}
		})
	}
}

// 실제 CMMD 원본 — (0018,5101) 이 없고 ViewCodeSequence 만 있다.
// 4MB 짜리라 저장소에 안 넣는다. 그 경로에 있을 때만 돈다.
//
// 한 폴더 위의 R_CC.dcm 등은 ViewPosition 을 덧붙인 사본이다. SOP UID 로
// 짝을 지어 **원본에서 코드로 알아낸 값 == 사본 파일 이름** 인지 본다.
const cmmdDir = `C:\empatho-view\.scratch\dicom-samples\CMMD_D2-0140`

func TestCMMDOriginals(t *testing.T) {
	originals, _ := filepath.Glob(filepath.Join(cmmdDir, "original", "*.dcm"))
	if len(originals) == 0 {
		t.Skip("CMMD 표본이 없다: " + cmmdDir)
	}
	parse := func(path string) *Meta {
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer f.Close()
		m, err := Parse(f, 0)
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		return m
	}

	want := map[string]string{} // SOP UID → "R_CC" 등
	for _, name := range []string{"R_CC", "R_MLO", "L_CC", "L_MLO"} {
		p := filepath.Join(cmmdDir, name+".dcm")
		if _, err := os.Stat(p); err != nil {
			continue
		}
		want[parse(p).SOPInstanceUID] = name
	}

	seen := map[string]bool{}
	for _, p := range originals {
		m := parse(p)
		got := m.Laterality + "_" + m.ViewPosition
		t.Logf("%s → %s (modality=%s)", filepath.Base(p), got, m.Modality)
		if m.ViewPosition != "CC" && m.ViewPosition != "MLO" {
			t.Errorf("%s: ViewPosition=%q — CC/MLO 여야 한다", filepath.Base(p), m.ViewPosition)
		}
		if m.Laterality != "L" && m.Laterality != "R" {
			t.Errorf("%s: Laterality=%q", filepath.Base(p), m.Laterality)
		}
		if w, ok := want[m.SOPInstanceUID]; ok && w != got {
			t.Errorf("%s: 원본에서 %s 로 읽었는데 사본 이름은 %s", filepath.Base(p), got, w)
		} else if ok {
			t.Logf("  사본 %s.dcm 과 일치", w)
		}
		seen[got] = true
	}
	if len(originals) == 4 && len(seen) != 4 {
		t.Errorf("네 장이 L/R × CC/MLO 를 하나씩 덮어야 한다: %v", seen)
	}
}
