package imagemeta

import (
	"bytes"
	"image"
	"image/color"
	"image/jpeg"
	"image/png"
	"testing"
)

func pngBytes(t *testing.T, w, h int) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	img.Set(0, 0, color.RGBA{1, 2, 3, 255})
	var b bytes.Buffer
	if err := png.Encode(&b, img); err != nil {
		t.Fatalf("png 인코딩: %v", err)
	}
	return b.Bytes()
}

func jpegBytes(t *testing.T, w, h int) []byte {
	t.Helper()
	img := image.NewRGBA(image.Rect(0, 0, w, h))
	var b bytes.Buffer
	if err := jpeg.Encode(&b, img, nil); err != nil {
		t.Fatalf("jpeg 인코딩: %v", err)
	}
	return b.Bytes()
}

func TestPNG(t *testing.T) {
	// 병리 크롭이 512×512 다
	got := Parse(pngBytes(t, 512, 512))
	if got == nil {
		t.Fatal("PNG 인데 nil 이 나왔다")
	}
	if got.W != 512 || got.H != 512 {
		t.Fatalf("크기가 %dx%d (512x512 여야 한다)", got.W, got.H)
	}
}

func TestJPEG(t *testing.T) {
	// 초음파가 JPEG 로 올 수 있다
	got := Parse(jpegBytes(t, 800, 600))
	if got == nil {
		t.Fatal("JPEG 인데 nil 이 나왔다")
	}
	if got.W != 800 || got.H != 600 {
		t.Fatalf("크기가 %dx%d (800x600 이어야 한다)", got.W, got.H)
	}
}

// 머리말만 있어도 읽혀야 한다. 파일 전체를 들고 있지 않기 때문이다
// (file-gateway 는 앞 1MB 만 tap 으로 받아 둔다).
func TestPNG_머리말만(t *testing.T) {
	full := pngBytes(t, 2294, 1914)
	head := full[:64] // IHDR 은 33바이트 안에 있다
	got := Parse(head)
	if got == nil || got.W != 2294 || got.H != 1914 {
		t.Fatalf("머리말 64바이트로 못 읽었다: %+v", got)
	}
}

// ⚠ nil 은 오류가 아니다. DICOM · PDF · 메시 JSON 도 이 자리를 지나간다.
// 그때는 I-1 에서 키가 빠지고 Django 가 null 로 둔다.
func TestNotImage(t *testing.T) {
	cases := map[string][]byte{
		"빈 입력":     nil,
		"DICOM 흉내": append(make([]byte, 128), []byte("DICM")...),
		"PDF":      []byte("%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"),
		"JSON":     []byte(`{"kind":"mesh"}`),
		"쓰레기":      []byte{0x00, 0xff, 0x13, 0x37},
	}
	for name, b := range cases {
		if got := Parse(b); got != nil {
			t.Errorf("%s: nil 이어야 하는데 %+v 가 나왔다", name, got)
		}
	}
}

// 잘린 머리말이면 틀린 값을 싣느니 nil 이 낫다.
func TestTruncated(t *testing.T) {
	full := pngBytes(t, 512, 512)
	if got := Parse(full[:8]); got != nil { // 서명 8바이트뿐 — IHDR 이 없다
		t.Fatalf("잘린 PNG 인데 %+v 가 나왔다", got)
	}
}
