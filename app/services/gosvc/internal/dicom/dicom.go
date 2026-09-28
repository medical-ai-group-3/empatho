// Package dicom — DICOM 헤더 파싱. 명세 19-2 G-F7.
//
// 라이브러리를 안 쓴다. 필요한 것이 **머리말 태그 몇 개**뿐이고, 화소는
// 아예 안 건드리기 때문이다. 화소를 건드리기 시작하면 JPEG2000·JPEG-LS
// 디코더가 필요해지고 그건 순수 Go 로 안 된다 (C 라이브러리를 끌어와야 한다).
//
// 그래서 이 파서는 (7FE0,0010) PixelData 를 만나면 **거기서 멈춘다.**
// 수 GB 짜리 WSI 든 40MB 짜리 맘모그램이든 읽는 양은 앞쪽 수십 KB 다.
//
// 지원하는 전송 구문
//
//	1.2.840.10008.1.2      암시적 VR 리틀엔디안
//	1.2.840.10008.1.2.1    명시적 VR 리틀엔디안 (대부분)
//	1.2.840.10008.1.2.2    명시적 VR 빅엔디안
//	그 외(JPEG·JPEG2000·RLE) 는 전부 명시적 VR 리틀엔디안 머리말이라
//	머리말 파싱은 똑같이 된다. 화소만 압축돼 있고 우리는 화소를 안 본다.
package dicom

import (
	"bufio"
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"
)

var ErrNotDICOM = errors.New("DICOM 이 아니다")

// Meta 는 I-2 로 넘길 값들이다.
//
// ⚠ PatientName(0010,0010) 은 **일부러 안 담는다.** 가명화 정책이 정해지기
// 전에는 이름을 Go 로그·콜백 본문에 흘리지 않는다. 필요하면 팀 결정 뒤에
// 추가한다.
type Meta struct {
	// 식별자 — I-1 의 object_key 와 이걸로 영상이 어느 촬영인지 정해진다
	StudyInstanceUID  string `json:"study_instance_uid"`
	SeriesInstanceUID string `json:"series_instance_uid"`
	SOPInstanceUID    string `json:"sop_instance_uid"`
	SOPClassUID       string `json:"sop_class_uid"`
	PatientID         string `json:"patient_id"`

	// 촬영
	Modality     string `json:"modality"`   // MG · US · MR
	StudyDate    string `json:"study_date"` // YYYYMMDD
	StudyTime    string `json:"study_time"`
	BodyPart     string `json:"body_part,omitempty"`
	Manufacturer string `json:"manufacturer,omitempty"`
	ModelName    string `json:"manufacturer_model_name,omitempty"`

	// 맘모그래피 전용 — 이 둘이 없으면 좌우·촬영방향을 알 수 없다
	Laterality   string `json:"laterality,omitempty"`    // L · R
	ViewPosition string `json:"view_position,omitempty"` // CC · MLO (ML · LM · XCCL … 도 그대로)

	// MRI 조영 전·후를 가리는 데 쓴다. 값은 그대로 넘기고 판정은 Django 가
	// 한다 — laterality 와 같은 방식이다. 조영제 태그(0018,0010)로는 못
	// 가린다. 조영 전 시리즈에도 똑같이 찍혀 있다.
	SeriesDescription string `json:"series_description,omitempty"` // ax dyn pre · Ph1/ax 3d dyn

	// 화소
	Rows              int       `json:"rows"`
	Columns           int       `json:"columns"`
	BitsAllocated     int       `json:"bits_allocated,omitempty"`
	BitsStored        int       `json:"bits_stored,omitempty"`
	NumberOfFrames    int       `json:"number_of_frames,omitempty"`
	PhotometricInterp string    `json:"photometric_interpretation,omitempty"`
	PixelSpacing      []float64 `json:"pixel_spacing,omitempty"`     // mm/px
	PixelSpacingTag   string    `json:"pixel_spacing_tag,omitempty"` // 어느 태그에서 왔나

	// MRI 3D 재구성용 기하 정보 (MRI 팀 요청 2026-09-02)
	//
	// 슬라이스를 Z축으로 쌓으려면 이 넷이 있어야 한다. 없으면 낱장이
	// **어느 위치의 어느 방향 단면인지** 알 수 없어서 후처리가 시작조차 안 된다.
	//
	//	ImagePositionPatient    첫 화소의 환자 좌표 (x,y,z) mm
	//	ImageOrientationPatient 행·열 방향 코사인 6개 — 단면이 어느 쪽을 향하나
	//	SliceThickness          단면 두께 mm
	//	SpacingBetweenSlices    단면 중심 간 거리 mm. 두께와 다를 수 있다
	//	                        (겹쳐 찍으면 간격 < 두께, 띄워 찍으면 반대)
	//
	// 맘모는 이 값들이 없다. 낱장 2D 촬영이라 쌓을 것이 없기 때문이다.
	ImagePositionPatient    []float64 `json:"image_position_patient,omitempty"`
	ImageOrientationPatient []float64 `json:"image_orientation_patient,omitempty"`
	SliceThickness          float64   `json:"slice_thickness,omitempty"`
	SpacingBetweenSlices    float64   `json:"spacing_between_slices,omitempty"`

	TransferSyntaxUID  string `json:"transfer_syntax_uid"`
	BurnedInAnnotation string `json:"burned_in_annotation,omitempty"` // YES 면 화면에 글자가 박혀 있다
}

// HasGeometry — 3D 로 쌓을 수 있는가.
//
// 위치와 방향이 **둘 다** 있어야 한다. 위치만 있으면 어느 방향 단면인지
// 모르고, 방향만 있으면 어디에 놓을지 모른다. 하나라도 없으면 재구성은
// 못 한다 — 그래서 반쪽으로 통과시키지 않는다.
//
// 두께·간격은 여기서 안 본다. 없어도 위치들로 간격을 역산할 수 있고,
// 실제로 그렇게 하는 뷰어가 많다.
func (m *Meta) HasGeometry() bool {
	return len(m.ImagePositionPatient) == 3 && len(m.ImageOrientationPatient) == 6
}

// HasSpacing — 화소 간격을 아는가.
//
// 이게 왜 중요한가: 맘모 검출기의 미세석회 민감도는 **해상도에 직접 걸린다.**
// 우리 외부 검증에서 같은 모델·같은 운영점으로 @1FP 민감도가
// CBIS 57.9% → VinDr 43.2% 로 떨어졌고, VinDr 을 1.42배로 키우자
// 54.6% 로 78% 가 회복됐다. 종괴는 안 그랬다(41.7% → 37.4%).
//
// 즉 **들어온 영상의 mm/px 를 모르면 미세석회 결과를 믿을 수 없다.**
// 그래서 없으면 없다고 I-2 에 남긴다. 조용히 비워두면 나중에 아무도 모른다.
func (m *Meta) HasSpacing() bool { return len(m.PixelSpacing) == 2 }

type tag struct{ g, e uint16 }

func (t tag) String() string { return fmt.Sprintf("(%04X,%04X)", t.g, t.e) }

var (
	tTransferSyntax = tag{0x0002, 0x0010}
	tPixelData      = tag{0x7FE0, 0x0010}
	tItem           = tag{0xFFFE, 0xE000}
	tItemDelim      = tag{0xFFFE, 0xE00D}
	tSeqDelim       = tag{0xFFFE, 0xE0DD}
	tViewCodeSeq    = tag{0x0054, 0x0220}
	tCodeValue      = tag{0x0008, 0x0100}
	tCodingScheme   = tag{0x0008, 0x0102}
)

// 4바이트 길이를 쓰는 VR. 나머지는 2바이트다. 여기를 틀리면 그 뒤 전부 어긋난다.
var longVR = map[string]bool{
	"OB": true, "OW": true, "OF": true, "OD": true, "OL": true, "OV": true,
	"SQ": true, "UT": true, "UN": true, "UC": true, "UR": true,
}

// Parse — 머리말을 읽어 Meta 를 만든다. PixelData 에서 멈춘다.
//
// max 는 읽을 상한(바이트). 0 이면 8MB. 상한을 두는 이유는 깨진 파일이
// 길이 필드에 쓰레기를 담고 있으면 무한정 읽기 때문이다.
func Parse(r io.Reader, max int64) (*Meta, error) {
	if max <= 0 {
		max = 8 << 20
	}
	lr := io.LimitReader(r, max)

	// 128바이트 서두 + "DICM". 서두 없이 바로 DICM 으로 시작하는 파일도 있다.
	//
	// ⚠ 여기서 bufio 로 감싸 놓고 읽으면 안 된다 — bufio 가 앞질러 읽어 둔
	//   내용을 되돌릴 방법이 없어 뒤쪽 파서가 엉뚱한 자리에서 시작한다.
	head := make([]byte, 132)
	n, _ := io.ReadFull(lr, head)
	var rest io.Reader
	switch {
	case n >= 132 && string(head[128:132]) == "DICM":
		rest = lr
	case n >= 4 && string(head[0:4]) == "DICM":
		rest = io.MultiReader(bytes.NewReader(head[4:n]), lr)
	default:
		return nil, ErrNotDICOM
	}

	m := &Meta{}
	p := &parser{r: bufio.NewReaderSize(rest, 64<<10),
		explicit: true, bo: binary.LittleEndian}

	// (0002,xxxx) 파일 메타 그룹은 전송 구문과 무관하게 **항상** 명시적 VR LE 다.
	// 여기서 전송 구문을 읽어 그 뒤 본문의 해석 방식을 정한다.
	if err := p.walk(m, func(t tag) bool { return t.g == 0x0002 }); err != nil {
		return nil, err
	}
	switch strings.TrimRight(m.TransferSyntaxUID, "\x00 ") {
	case "1.2.840.10008.1.2": // 암시적 VR LE
		p.explicit, p.bo = false, binary.LittleEndian
	case "1.2.840.10008.1.2.2": // 명시적 VR BE
		p.explicit, p.bo = true, binary.BigEndian
	default: // 명시적 VR LE — 압축 전송 구문도 머리말은 이것이다
		p.explicit, p.bo = true, binary.LittleEndian
	}
	if err := p.walk(m, func(t tag) bool { return t != tPixelData }); err != nil {
		return nil, err
	}
	if m.SOPInstanceUID == "" && m.StudyInstanceUID == "" {
		return nil, ErrNotDICOM
	}
	m.ViewPosition = resolveView(m.ViewPosition, p.viewCode, p.viewScheme)
	m.Laterality = strings.ToUpper(strings.TrimSpace(m.Laterality))
	return m, nil
}

type parser struct {
	r        *bufio.Reader
	explicit bool
	bo       binary.ByteOrder

	// ViewCodeSequence(0054,0220) 첫 항목의 코드. ViewPosition 이 비었을 때만 쓴다.
	viewCode, viewScheme string
}

// walk — take 가 false 를 낼 때까지 태그를 읽는다.
//
// ⚠ 멈출 태그는 **소비하지 않고** 멈춰야 한다. 메타 그룹을 다 읽고 나면
//
//	같은 스트림을 다른 전송 구문으로 이어서 읽기 때문에, 한 요소라도
//	미리 먹으면 그 뒤가 통째로 어긋난다. 그래서 태그만 먼저 엿본다.
func (p *parser) walk(m *Meta, take func(tag) bool) error {
	for {
		t, ok := p.peekTag()
		if !ok {
			return nil // 상한까지 읽었거나 파일이 끝났다. 모은 것만 쓴다
		}
		if !take(t) {
			return nil
		}
		t, vr, length, err := p.element()
		if stopped(err) {
			return nil
		}
		if err != nil {
			return err
		}
		// ViewCodeSequence 만은 안으로 들어간다. CMMD 처럼 (0018,5101)
		// ViewPosition 없이 촬영방향을 **여기에만** 적는 맘모가 있다.
		if t == tViewCodeSeq && (vr == "SQ" || vr == "UN" || length == 0xFFFFFFFF) {
			// 명시적 VR 파일에서 VR 이 UN 이면 안쪽은 암시적 VR LE 다 (PS3.5 6.2.2).
			if err := p.readViewCodeSeq(length, p.explicit && vr == "UN"); err != nil {
				return ignoreStop(err)
			}
			continue
		}
		// 그 밖의 시퀀스는 값을 안 쓴다. 안쪽으로 안 들어가고 통째로 건너뛴다.
		// 우리가 필요한 나머지 태그는 전부 최상위에 있다.
		if vr == "SQ" || (length == 0xFFFFFFFF && vr != "OB") {
			if err := p.skipSeq(length); err != nil {
				return ignoreStop(err)
			}
			continue
		}
		if length == 0xFFFFFFFF { // 캡슐화 화소 등 — 여기까지 오면 그만 읽는다
			return nil
		}
		val, err := p.bytes(length)
		if err != nil {
			return ignoreStop(err)
		}
		p.assign(m, t, vr, val)
	}
}

// 잘린 파일과 읽기 상한은 **오류가 아니다.** 거기까지 모은 것을 쓴다.
//
// 실제로 VinDr 에서 잘린 DICOM 을 겪었다(19,700,800 중 15,325,769 바이트).
// 그런 파일도 머리말은 멀쩡해서 어느 촬영인지는 알 수 있다. 통째로
// 버리면 "어느 파일이 잘렸는지" 조차 알 수 없게 된다.
func stopped(err error) bool {
	return errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF)
}

func ignoreStop(err error) error {
	if stopped(err) {
		return nil
	}
	return err
}

// peekTag — 태그 4바이트만 엿본다. 소비하지 않는다.
func (p *parser) peekTag() (tag, bool) {
	b, err := p.r.Peek(4)
	if err != nil || len(b) < 4 {
		return tag{}, false
	}
	return tag{p.bo.Uint16(b[0:2]), p.bo.Uint16(b[2:4])}, true
}

func (p *parser) element() (tag, string, uint32, error) {
	var g, e uint16
	if err := binary.Read(p.r, p.bo, &g); err != nil {
		return tag{}, "", 0, err
	}
	if err := binary.Read(p.r, p.bo, &e); err != nil {
		return tag{}, "", 0, io.ErrUnexpectedEOF
	}
	t := tag{g, e}

	// 항목 구분자는 VR 을 안 갖는다 — 명시적 VR 파일에서도 그렇다
	if t.g == 0xFFFE {
		var l uint32
		if err := binary.Read(p.r, p.bo, &l); err != nil {
			return t, "", 0, io.ErrUnexpectedEOF
		}
		return t, "", l, nil
	}
	if !p.explicit {
		var l uint32
		if err := binary.Read(p.r, p.bo, &l); err != nil {
			return t, "", 0, io.ErrUnexpectedEOF
		}
		return t, implicitVR(t), l, nil
	}
	v := make([]byte, 2)
	if _, err := io.ReadFull(p.r, v); err != nil {
		return t, "", 0, io.ErrUnexpectedEOF
	}
	vr := string(v)
	if longVR[vr] {
		var pad uint16
		var l uint32
		binary.Read(p.r, p.bo, &pad) // 예약 2바이트
		if err := binary.Read(p.r, p.bo, &l); err != nil {
			return t, vr, 0, io.ErrUnexpectedEOF
		}
		return t, vr, l, nil
	}
	var l uint16
	if err := binary.Read(p.r, p.bo, &l); err != nil {
		return t, vr, 0, io.ErrUnexpectedEOF
	}
	return t, vr, uint32(l), nil
}

// skipSeq — 시퀀스를 건너뛴다.
//
// 길이가 정해져 있으면 그만큼 버리면 된다. 정해져 있지 않으면(0xFFFFFFFF)
// 항목을 따라가며 시퀀스 구분자(FFFE,E0DD)까지 가야 한다. 여기를 대충
// 하면 그 뒤 태그가 전부 어긋나서 **엉뚱한 값이 조용히 들어간다.**
func (p *parser) skipSeq(length uint32) error {
	if length != 0xFFFFFFFF {
		_, err := p.bytes(length)
		return err
	}
	depth := 1
	for depth > 0 {
		t, vr, l, err := p.element()
		if err != nil {
			return err
		}
		switch {
		case t == tSeqDelim:
			depth--
		case t == tItem && l == 0xFFFFFFFF:
			// 길이 미정 항목 — 안쪽을 계속 읽는다
		case t == tItem:
			if _, err := p.bytes(l); err != nil {
				return err
			}
		case t == tItemDelim:
			// 항목 끝
		case vr == "SQ" || l == 0xFFFFFFFF:
			depth++
		default:
			if _, err := p.bytes(l); err != nil {
				return err
			}
		}
	}
	return nil
}

// readViewCodeSeq — ViewCodeSequence 를 읽어 **첫 항목**의 CodeValue ·
// CodingSchemeDesignator 만 담는다. 나머지(두 번째 항목, 안쪽의
// ViewModifierCodeSequence 같은 중첩 시퀀스)는 skipSeq 와 같은 규칙으로
// 건너뛴다. 끝나면 스트림은 시퀀스 바로 뒤에 있어야 한다 — 어긋나면
// 그 뒤 태그가 조용히 틀린다(TestSkipsSequences 와 같은 이유).
func (p *parser) readViewCodeSeq(length uint32, unImplicit bool) error {
	if unImplicit {
		// 안쪽 요소를 암시적 VR LE 로 읽는다. 바깥 설정은 끝나면 되돌린다.
		saveE, saveBO := p.explicit, p.bo
		p.explicit, p.bo = false, binary.LittleEndian
		defer func() { p.explicit, p.bo = saveE, saveBO }()
	}
	if length != 0xFFFFFFFF {
		// 길이가 정해진 시퀀스 — 통째로 읽어 두고 따로 훑는다.
		// 바깥 스트림은 정확히 length 만큼만 소비된다.
		b, err := p.bytes(length)
		if err != nil || b == nil {
			return err
		}
		sub := p.sub(b)
		items := 0
		sub.scanCodeItems(&items)
		p.viewCode, p.viewScheme = sub.viewCode, sub.viewScheme
		return nil
	}
	items := 0
	return p.scanCodeItems(&items)
}

func (p *parser) sub(b []byte) *parser {
	return &parser{r: bufio.NewReader(bytes.NewReader(b)), explicit: p.explicit, bo: p.bo}
}

// scanCodeItems — 시퀀스 구분자나 입력 끝까지 요소를 읽는다.
// items 는 지금까지 만난 항목 수. 첫 항목(items==1) 안의 코드만 담는다.
func (p *parser) scanCodeItems(items *int) error {
	for {
		t, vr, l, err := p.element()
		if err != nil {
			if stopped(err) {
				return nil // 길이가 정해진 조각의 끝, 또는 잘린 파일
			}
			return err
		}
		switch {
		case t == tSeqDelim:
			return nil
		case t == tItemDelim:
			// 항목 끝
		case t == tItem && l == 0xFFFFFFFF:
			*items++ // 길이 미정 항목 — 안쪽을 이어서 읽는다
		case t == tItem:
			*items++
			b, err := p.bytes(l)
			if err != nil {
				return err
			}
			if *items == 1 && b != nil {
				sub := p.sub(b)
				n := 1
				sub.scanCodeItems(&n)
				p.viewCode, p.viewScheme = sub.viewCode, sub.viewScheme
			}
		case vr == "SQ" || l == 0xFFFFFFFF:
			// 중첩 시퀀스(ViewModifierCodeSequence 등) — 안 본다
			if err := p.skipSeq(l); err != nil {
				return err
			}
		default:
			b, err := p.bytes(l)
			if err != nil {
				return err
			}
			if *items != 1 {
				continue
			}
			v := strings.TrimRight(string(b), "\x00 ")
			switch t {
			case tCodeValue:
				p.viewCode = strings.TrimSpace(v)
			case tCodingScheme:
				p.viewScheme = strings.ToUpper(strings.TrimSpace(v))
			}
		}
	}
}

// viewCodes — CID 4014 View for Mammography 의 코드 → ViewPosition 용어.
// SCT(SNOMED-CT) 와 옛 SNOMED-RT(SRT, "R-…") 를 둘 다 받는다. 약어는
// CID 4014 의 ACR MQCM 열을 그대로 쓴다.
//
// 127457009(tissue specimen from breast)은 촬영방향이 아니라서 안 넣는다.
var viewCodes = map[string]string{
	"399260004": "ML", "R-10224": "ML", // medio-lateral
	"399368009": "MLO", "R-10226": "MLO", // medio-lateral oblique
	"399352003": "LM", "R-10228": "LM", // latero-medial
	"399099002": "LMO", "R-10230": "LMO", // latero-medial oblique
	"399162004": "CC", "R-10242": "CC", // cranio-caudal
	"399196006": "FB", "R-10244": "FB", // caudo-cranial (from below)
	"399188001": "SIO", "R-102D0": "SIO", // superolateral to inferomedial oblique
	"441555000": "ISO", "R-40AAA": "ISO", // inferomedial to superolateral oblique
	"399192008": "XCCL", "R-1024A": "XCCL", // cranio-caudal exaggerated laterally
	"399101009": "XCCM", "R-1024B": "XCCM", // cranio-caudal exaggerated medially
}

// resolveView — ViewPosition 을 정한다.
//
//  1. (0018,5101) ViewPosition 이 있으면 그것 (공백 정리·대문자).
//  2. 없으면 ViewCodeSequence 첫 항목의 코드를 viewCodes 로 옮긴다.
//     코딩 체계가 SCT·SRT·SNM3 이거나 비어 있을 때만 믿는다 — 다른 체계의
//     같은 숫자를 잘못 옮기지 않으려고.
//  3. 모르는 코드면 비워 둔다. 추측해서 채우면 AI 결과가 엉뚱한 영상에 붙는다.
func resolveView(vp, code, scheme string) string {
	if v := strings.ToUpper(strings.TrimSpace(vp)); v != "" {
		return v
	}
	if code == "" {
		return ""
	}
	switch scheme {
	case "", "SCT", "SRT", "SNM3", "99SDM":
	default:
		return ""
	}
	return viewCodes[strings.ToUpper(code)]
}

func (p *parser) bytes(n uint32) ([]byte, error) {
	if n == 0 {
		return nil, nil
	}
	// 너무 큰 값은 읽어서 담지 않고 버린다. 사설 태그에 수 MB 가 들어 있기도 하다.
	if n > 1<<20 {
		_, err := io.CopyN(io.Discard, p.r, int64(n))
		return nil, err
	}
	b := make([]byte, n)
	if _, err := io.ReadFull(p.r, b); err != nil {
		return nil, io.ErrUnexpectedEOF
	}
	return b, nil
}

func (p *parser) assign(m *Meta, t tag, vr string, v []byte) {
	s := func() string { return strings.TrimRight(string(v), "\x00 ") }
	u16 := func() int {
		if len(v) < 2 {
			return 0
		}
		return int(p.bo.Uint16(v))
	}
	switch t {
	case tTransferSyntax:
		m.TransferSyntaxUID = s()
	case tag{0x0008, 0x0016}:
		m.SOPClassUID = s()
	case tag{0x0008, 0x0018}:
		m.SOPInstanceUID = s()
	case tag{0x0008, 0x0020}:
		m.StudyDate = s()
	case tag{0x0008, 0x0030}:
		m.StudyTime = s()
	case tag{0x0008, 0x0060}:
		m.Modality = s()
	case tag{0x0008, 0x0070}:
		m.Manufacturer = s()
	case tag{0x0008, 0x1090}:
		m.ModelName = s()
	case tag{0x0010, 0x0020}:
		m.PatientID = s()
	case tag{0x0018, 0x0015}:
		m.BodyPart = s()
	case tag{0x0018, 0x5101}:
		m.ViewPosition = s()
	case tag{0x0008, 0x103E}:
		m.SeriesDescription = s()
	case tag{0x0020, 0x000D}:
		m.StudyInstanceUID = s()
	case tag{0x0020, 0x000E}:
		m.SeriesInstanceUID = s()
	case tag{0x0020, 0x0062}: // ImageLaterality — 값이 있을 때만 덮는다
		// (0020,0060) 이 태그 순서상 먼저 온다. 빈 ImageLaterality 가
		// 앞서 읽은 Laterality 를 지우면 안 된다.
		if v := s(); v != "" {
			m.Laterality = v
		}
	case tag{0x0020, 0x0060}: // Laterality — 위가 없을 때만
		if m.Laterality == "" {
			m.Laterality = s()
		}
	case tag{0x0028, 0x0010}:
		m.Rows = u16()
	case tag{0x0028, 0x0011}:
		m.Columns = u16()
	case tag{0x0028, 0x0100}:
		m.BitsAllocated = u16()
	case tag{0x0028, 0x0101}:
		m.BitsStored = u16()
	case tag{0x0028, 0x0004}:
		m.PhotometricInterp = s()
	case tag{0x0028, 0x0008}:
		m.NumberOfFrames, _ = strconv.Atoi(s())
	case tag{0x0028, 0x0301}:
		m.BurnedInAnnotation = s()

	// 화소 간격 — 맘모는 ImagerPixelSpacing 이 맞다.
	// PixelSpacing 은 재구성 후 간격이라 촬영기 간격과 다를 수 있다.
	// 둘 다 있으면 ImagerPixelSpacing 을 쓴다.
	case tag{0x0018, 0x1164}: // ImagerPixelSpacing
		if sp := parseDS2(s()); sp != nil {
			m.PixelSpacing, m.PixelSpacingTag = sp, "ImagerPixelSpacing"
		}
	// ── MRI 3D 기하 ──────────────────────────────────────────────
	//
	// ⚠ parseDS2 를 쓰면 안 된다. 그건 값이 양수일 때만 통과시킨다
	//   (화소 간격은 음수일 수 없으니 맞는 검사였다). 하지만 환자 좌표와
	//   방향 코사인은 **음수와 0 이 정상값이다.** 양수만 받으면 왼쪽 절반이나
	//   특정 방향 단면이 통째로 버려진다.
	case tag{0x0020, 0x0032}: // ImagePositionPatient
		if v := parseDSn(s(), 3); v != nil {
			m.ImagePositionPatient = v
		}
	case tag{0x0020, 0x0037}: // ImageOrientationPatient
		if v := parseDSn(s(), 6); v != nil {
			m.ImageOrientationPatient = v
		}
	case tag{0x0018, 0x0050}: // SliceThickness
		// 두께는 양수여야 한다. 0 은 값이 없다는 뜻이지 두께가 0 인 것이 아니다.
		if f, err := strconv.ParseFloat(strings.TrimSpace(s()), 64); err == nil && f > 0 {
			m.SliceThickness = f
		}
	case tag{0x0018, 0x0088}: // SpacingBetweenSlices
		// 일부 장비가 음수를 낸다(슬라이스 순서가 좌표 반대 방향일 때).
		// 부호를 버리지 않고 그대로 넘긴다 — 쌓는 쪽이 판단할 일이다.
		if f, err := strconv.ParseFloat(strings.TrimSpace(s()), 64); err == nil && f != 0 {
			m.SpacingBetweenSlices = f
		}

	case tag{0x0028, 0x0030}: // PixelSpacing
		if m.PixelSpacingTag == "" {
			if sp := parseDS2(s()); sp != nil {
				m.PixelSpacing, m.PixelSpacingTag = sp, "PixelSpacing"
			}
		}
	}
}

// parseDS2 — "0.085\0.085" 꼴. 역슬래시가 DICOM 의 다중값 구분자다.
func parseDS2(s string) []float64 {
	parts := strings.Split(s, `\`)
	if len(parts) != 2 {
		return nil
	}
	out := make([]float64, 2)
	for i, p := range parts {
		f, err := strconv.ParseFloat(strings.TrimSpace(p), 64)
		if err != nil || f <= 0 {
			return nil
		}
		out[i] = f
	}
	return out
}

// parseDSn — 값이 정확히 n 개인 DS 를 읽는다. 음수와 0 을 그대로 받는다.
//
// parseDS2 와 나눠 둔 이유가 그것이다. 화소 간격은 양수여야 맞지만
// 환자 좌표(ImagePositionPatient)와 방향 코사인(ImageOrientationPatient)은
// 음수·0 이 정상값이다. 예를 들어 축상면의 방향 코사인은 1\0\0\0\1\0 이라
// 여섯 값 중 넷이 0 이다. 양수만 받으면 이게 통째로 버려진다.
//
// 개수가 다르면 nil 을 낸다. 3 개여야 할 좌표가 2 개면 파일이 깨진 것이고,
// 그걸 반쪽으로 받아 두면 쌓는 쪽에서 엉뚱한 위치에 놓인다.
func parseDSn(s string, n int) []float64 {
	parts := strings.Split(s, `\`)
	if len(parts) != n {
		return nil
	}
	out := make([]float64, n)
	for i, p := range parts {
		f, err := strconv.ParseFloat(strings.TrimSpace(p), 64)
		if err != nil {
			return nil
		}
		out[i] = f
	}
	return out
}

// implicitVR — 암시적 VR 파일에는 VR 이 안 적혀 있다. 사전이 있어야 하는데
// 우리가 읽는 태그만 알면 되므로 그것만 담는다. 모르는 태그는 "UN" 으로
// 두고 길이만큼 건너뛴다 — 값을 안 쓰니 문제없다.
func implicitVR(t tag) string {
	switch t {
	case tag{0x0028, 0x0010}, tag{0x0028, 0x0011}, tag{0x0028, 0x0100},
		tag{0x0028, 0x0101}:
		return "US"
	}
	if t.g == 0x7FE0 {
		return "OW"
	}
	if t == tViewCodeSeq {
		return "SQ"
	}
	return "UN"
}
