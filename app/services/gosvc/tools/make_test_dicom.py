#!/usr/bin/env python3
"""시험용 유방촬영 DICOM 을 만든다. 의존성 없음.

왜 필요한가
    실제 자료를 시험에 쓸 수 없다. CBIS-DDSM 은 재배포 금지고 VinDr·EMBED 는
    인증·DUA 로 묶여 있다. 개인 컴퓨터나 CI 로 옮기면 그 조항에 걸린다.

    그래서 **바이트를 직접 쌓아** 만든다. 어차피 파서가 보는 것은 바이트
    배치라 이게 실제 파일보다 오히려 정확한 시험이 된다.

만드는 것
    명시적 VR 리틀엔디안 · MG · 좌측 MLO · ImagerPixelSpacing 0.07mm/px

사용
    python3 make_test_dicom.py out.dcm
    python3 make_test_dicom.py out.dcm --spacing 0.085 --no-spacing
"""
import argparse
import struct
import sys


def build(spacing: str | None, rows=4096, cols=3328, pixel_kb=64) -> bytes:
    b = bytearray(b"\0" * 128 + b"DICM")

    def el(g, e, vr, v):
        v = v.encode() if isinstance(v, str) else v
        if len(v) % 2:
            v += b"\0"                      # DICOM 값은 짝수 길이여야 한다
        b.extend(struct.pack("<HH", g, e))
        b.extend(vr.encode())
        if vr in ("OB", "OW", "SQ", "UN", "UT"):
            b.extend(struct.pack("<HI", 0, len(v)))   # 예약 2 + 길이 4
        else:
            b.extend(struct.pack("<H", len(v)))       # 길이 2
        b.extend(v)

    def us(g, e, n):
        el(g, e, "US", struct.pack("<H", n))

    el(0x0002, 0x0010, "UI", "1.2.840.10008.1.2.1")   # 명시적 VR LE
    el(0x0008, 0x0016, "UI", "1.2.840.10008.5.1.4.1.1.1.2")
    el(0x0008, 0x0018, "UI", "1.2.3.4.5.6.7.8.9")
    el(0x0008, 0x0020, "DA", "20260901")
    el(0x0008, 0x0060, "CS", "MG")
    el(0x0008, 0x0070, "LO", "TEST MFR")
    el(0x0008, 0x1090, "LO", "TEST MODEL")
    # 환자 이름 — 파서가 이걸 **안 담는지** 확인하려고 일부러 넣는다
    el(0x0010, 0x0010, "PN", "TEST^PATIENT")
    el(0x0010, 0x0020, "LO", "DCM-PID-TEST")
    if spacing:
        el(0x0018, 0x1164, "DS", f"{spacing}\\{spacing}")
    el(0x0018, 0x5101, "CS", "MLO")
    el(0x0020, 0x000D, "UI", "1.2.3.STUDY")
    el(0x0020, 0x000E, "UI", "1.2.3.SERIES")
    el(0x0020, 0x0062, "CS", "L")
    el(0x0028, 0x0004, "CS", "MONOCHROME2")
    us(0x0028, 0x0010, rows)
    us(0x0028, 0x0011, cols)
    us(0x0028, 0x0100, 16)
    us(0x0028, 0x0101, 12)
    el(0x0028, 0x0301, "CS", "NO")
    el(0x7FE0, 0x0010, "OW", b"\xAB" * (pixel_kb * 1024))
    return bytes(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--spacing", default="0.07", help="mm/px")
    ap.add_argument("--no-spacing", action="store_true",
                    help="화소 간격을 빼고 만든다 — CBIS 같은 필름 스캔 흉내")
    ap.add_argument("--pixel-kb", type=int, default=64,
                    help="화소 자리 크기. 청크 업로드를 시험하려면 키운다")
    a = ap.parse_args()
    raw = build(None if a.no_spacing else a.spacing, pixel_kb=a.pixel_kb)
    with open(a.out, "wb") as f:
        f.write(raw)
    print(f"{a.out}  {len(raw):,} bytes  "
          f"간격 {'없음' if a.no_spacing else a.spacing + ' mm/px'}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
