// Package imagemeta — 그림 파일의 머리말에서 픽셀 크기만 읽는다.
//
// 왜 필요한가
//
//	맘모·MRI 는 DICOM 이라 I-2 가 width_px · height_px 를 채운다.
//	초음파·병리는 PNG 라 I-2 를 안 탄다 — dicom.Parse 가 매직을 못 찾고
//	ErrNotDICOM 으로 끝난다. 그래서 storage_object 의 두 칸이 null 로 남고,
//	화면은 AI 폴리곤 좌표를 받아도 **원본이 몇 픽셀인지 몰라 못 그린다.**
//	좌표가 원본 픽셀 기준이라 기준 크기가 없으면 놓을 자리가 없다.
//
//	Go 가 I-1 에 실어 주면 Django 에 컬럼을 더할 필요가 없다 —
//	storage_object.width_px · height_px 가 이미 있다.
//
// 어떻게
//
//	image.DecodeConfig 는 **픽셀을 안 푼다.** 머리말만 읽고 크기와 색 모델만
//	돌려준다. 수백 MB 짜리 WSI 크롭이라도 앞 몇十 바이트만 본다.
//
//	png · jpeg 만 등록한다. 빈 import 가 각 포맷을 image 에 붙이는 방식이라,
//	쓰지 않는 포맷을 등록하면 그만큼 바이너리에 들어간다.
//	gif 는 의료 영상으로 안 쓴다. webp 는 표준 라이브러리에 없다.
package imagemeta

import (
	"bytes"
	"image"

	// 빈 import 로 디코더를 등록한다. 이게 없으면 DecodeConfig 가
	// 늘 image.ErrFormat 을 돌려준다 — 컴파일은 되고 런타임에만 조용히 실패한다.
	_ "image/jpeg"
	_ "image/png"
)

// Size — 픽셀 크기.
type Size struct {
	W int
	H int
}

// Parse — 머리말에서 크기를 읽는다. 그림이 아니면 nil 이다.
//
// ⚠ **nil 은 오류가 아니다.** DICOM · PDF · 메시 JSON 도 이 자리를 지나간다.
// 부르는 쪽은 nil 이면 그냥 안 싣는다 — I-1 에서 width_px 가 빠지고
// Django 는 지금처럼 null 로 둔다.
//
// head 는 파일의 앞부분이면 된다. PNG 는 IHDR 이 33바이트 안에 있고
// JPEG 도 SOF 가 보통 앞쪽 몇 KB 안에 온다. 잘린 머리말이면 오류가 나고
// 그때도 nil 이다 — 크기를 모르는 채로 틀린 값을 싣는 것보다 낫다.
func Parse(head []byte) *Size {
	if len(head) == 0 {
		return nil
	}
	cfg, _, err := image.DecodeConfig(bytes.NewReader(head))
	if err != nil {
		return nil
	}
	if cfg.Width <= 0 || cfg.Height <= 0 {
		return nil
	}
	return &Size{W: cfg.Width, H: cfg.Height}
}
