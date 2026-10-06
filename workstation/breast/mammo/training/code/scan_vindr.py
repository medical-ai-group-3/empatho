#!/usr/bin/env python
"""
VinDr DICOM 화소 데이터가 온전한지 441장 전부 확인한다.

왜 필요한가
  eval_vindr.py 가 200/435 에서 죽었다.

      ValueError: The number of bytes of pixel data is less than expected
                  (15325769 vs 19700800 bytes)

  19,700,800 = 3518 x 2800 x 2바이트. 헤더가 선언한 크기다.
  실제로 있는 건 15,325,769 바이트 — 77.8% 다. 그리고 이 값은 홀수인데,
  DICOM 화소 데이터는 규격상 항상 짝수 길이다. 전송이 중간에 끊긴 것이다.
  해상도 문제가 아니라 받다 만 파일이다.

  check_vindr.py 는 이걸 못 잡는다. 441장을 stop_before_pixels=True 로 읽어
  헤더만 봤고, 화소를 실제로 편 건 표본 25장뿐이었다. 내가 그걸 무결성
  점검이라고 불렀는데 헤더 점검이었다.

무엇을 하나
  선언된 크기(Rows x Columns x SamplesPerPixel x BitsAllocated/8)와
  실제 화소 바이트 수를 비교한다. 화소를 '푸는' 게 아니라 '세기만' 하므로
  441장에 몇 분이면 끝난다. 압축 전송구문이면 길이 비교가 성립하지 않으니
  그때만 실제로 디코드해 본다.

  깨진 파일의 재다운로드 URL 목록을 파일로 남긴다.

사용
  python3 scan_vindr.py
  python3 scan_vindr.py --delete-bad     # 깨진 파일을 지운다(받기 전에)
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

try:
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import LABELS, RAW_VINDR                       # noqa: E402

URL = ("https://physionet.org/files/vindr-mammo/1.0.0/"
       "images/{study_id}/{image_id}.dicom")
WANT = ("Mass", "Suspicious Calcification")


def expected_bytes(d):
    """헤더가 선언한 화소 바이트 수. 정보가 모자라면 None."""
    try:
        return (int(d.Rows) * int(d.Columns)
                * int(getattr(d, "SamplesPerPixel", 1))
                * (int(d.BitsAllocated) // 8)
                * int(getattr(d, "NumberOfFrames", 1) or 1))
    except Exception:
        return None


def check(f):
    """(상태, 상세) 를 돌려준다. 상태는 ok · short · long · compressed_bad · error."""
    try:
        d = pydicom.dcmread(str(f))          # 바이트만 읽는다. 디코드는 안 한다
    except Exception as e:
        return "error", f"{type(e).__name__}: {e}", None
    ts = getattr(getattr(d, "file_meta", None), "TransferSyntaxUID", None)
    exp = expected_bytes(d)
    size = f"{getattr(d,'Rows','?')}x{getattr(d,'Columns','?')}"
    if ts is not None and getattr(ts, "is_compressed", False):
        try:                                  # 압축이면 길이 비교가 성립 안 한다
            d.pixel_array
            return "ok", f"{size} 압축({ts.name})", size
        except Exception as e:
            return "compressed_bad", f"{size} {type(e).__name__}: {e}", size
    try:
        got = len(d.PixelData)
    except Exception:
        return "error", f"{size} PixelData 없음", size
    if exp is None:
        return "error", f"{size} 선언 크기를 못 구했다", size
    if got == exp:
        return "ok", f"{size} {got:,}B", size
    kind = "short" if got < exp else "long"
    odd = " · 홀수(전송 중단)" if got % 2 else ""
    return kind, (f"{size}  {got:,} / {exp:,}B  ({got/exp:.1%}){odd}"), size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(RAW_VINDR))
    ap.add_argument("--csv", default=str(LABELS / "finding_annotations.csv"))
    ap.add_argument("--out", default="vindr_redownload.txt")
    ap.add_argument("--delete-bad", action="store_true",
                    help="깨진 파일을 지운다. 다시 받기 전에 쓴다")
    a = ap.parse_args()

    files = sorted(Path(a.dir).rglob("*.dicom")) + sorted(Path(a.dir).rglob("*.dcm"))
    if not files:
        sys.exit(f"DICOM 이 없다: {a.dir}")
    print("=" * 74)
    print(f"VinDr 화소 데이터 무결성 — {len(files):,}개")
    print("  선언 크기와 실제 바이트 수를 비교한다 (디코드 안 함)")
    print("=" * 74)

    # 어느 영상이 정답을 갖고 있는지 — 깨진 파일의 실제 영향을 알아야 한다
    have_gt, study_of = set(), {}
    if Path(a.csv).is_file():
        df = pd.read_csv(a.csv)
        fc = "finding_categories" if "finding_categories" in df.columns else None
        if fc:
            m = df[fc].astype(str).str.contains("|".join(WANT), na=False)
            have_gt = set(df[m]["image_id"].astype(str))
        if "study_id" in df.columns:
            study_of = dict(zip(df["image_id"].astype(str),
                                df["study_id"].astype(str)))

    stat, bad = Counter(), []
    for i, f in enumerate(files, 1):
        st, detail, _ = check(f)
        stat[st] += 1
        if st != "ok":
            bad.append((f, st, detail))
        if i % 25 == 0 or i == len(files):
            print(f"\r  {i}/{len(files)}   정상 {stat['ok']:,} · "
                  f"문제 {len(bad)}   ", end="", flush=True)
    print()

    print(f"\n  정상          {stat['ok']:,}")
    for k in ("short", "long", "compressed_bad", "error"):
        if stat[k]:
            label = {"short": "잘림(짧다)", "long": "길다",
                     "compressed_bad": "압축 해제 실패", "error": "읽기 실패"}[k]
            print(f"  {label:14s}{stat[k]:,}")

    if not bad:
        print(f"\n  ✓ {len(files):,}장 전부 온전하다. 죽은 원인이 다른 데 있다는")
        print("    뜻이니 eval_vindr.log 의 마지막 줄을 볼 것 — OOM 일 수 있다.")
        return

    print(f"\n  문제 파일 {len(bad)}개")
    print("  " + "-" * 72)
    n_gt = 0
    for f, st, detail in bad:
        iid = f.stem
        g = "정답있음" if iid in have_gt else "정답없음"
        n_gt += iid in have_gt
        print(f"  {iid[:24]:26s} {st:8s} {g}  {detail}")

    print("  " + "-" * 72)
    print(f"  이 중 평가에 쓰이는(검출 대상 소견이 있는) 영상 {n_gt}장")
    print(f"  435장 중 {n_gt}장 = {n_gt/435:.1%} — 결과 해석에 이만큼 구멍이 난다")

    urls = []
    for f, _, _ in bad:
        iid = f.stem
        sid = study_of.get(iid) or f.parent.name
        urls.append(URL.format(study_id=sid, image_id=iid))
    Path(a.out).write_text("\n".join(urls) + "\n", encoding="utf-8")
    print(f"\n  재다운로드 목록 -> {a.out}  ({len(urls)}줄)")

    if a.delete_bad:
        for f, _, _ in bad:
            f.unlink()
        print(f"  깨진 파일 {len(bad)}개 삭제했다")
    else:
        print("  ※ 다시 받기 전에 깨진 파일을 지워야 한다 (--delete-bad)")

    print("\n  받는 법 — 자격증명은 ~/.netrc 에 있다. 화면에 찍지 말 것.")
    print(f"    wget -c -x -nH --cut-dirs=4 -P {a.dir} \\")
    print(f"         --netrc -i {a.out}")
    print("    -c 는 이어받기다. 잘린 파일을 지웠으므로 처음부터 받는다.")
    print("\n  받은 뒤 이 스크립트를 다시 돌려 전부 정상인지 확인할 것.")


if __name__ == "__main__":
    main()
