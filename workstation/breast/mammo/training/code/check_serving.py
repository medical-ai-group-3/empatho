#!/usr/bin/env python
"""
서빙 코드를 실제로 태워 본다 — 정적 검사는 통과했지만 한 번도 안 돌려봤다.

무엇을 검사하나
  1단계 (GPU 안 씀)   지금 돌려도 된다. VinDr 이 도는 중에도 안전하다.
    · 패키지 · import
    · 체크포인트 3개가 실제로 열리는가
    · read_mammogram 이 경로와 bytes 로 같은 배열을 내는가  ← 서빙 새 경로
    · MONOCHROME1 을 정말 뒤집는가
    · crop_to_tensor 가 학습 데이터셋과 최대차 0 인가
    · filter_tissue · merge_boxes_one · expand_box 를 실제 영상으로
    · 응답 스키마 선언이 코드와 맞는가

  2단계 (GPU 씀)      VinDr 이 끝난 뒤에.
    · load_model → predict 한 장
    · 응답이 mammo_api.md 스키마와 맞는가
    · 소요 시간 · GPU 사용량

왜 나눠 놨나
  2단계는 검출기 1 + 서술어 2 를 올려 6GB 를 쓴다. 지금 남은 자리가 5.8GB 라
  돌리면 OOM 이 나거나 더 나쁘게는 돌고 있는 VinDr 을 밀어낸다.
  그래서 2단계는 여유를 먼저 재고 모자라면 스스로 거부한다.

사용
  python3 check_serving.py                 # 1단계만 (기본)
  python3 check_serving.py --stage 2       # VinDr 끝난 뒤
  python3 check_serving.py --stage 2 --image <경로>
"""

import argparse
import importlib
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 조각화 완화. CUDA 할당자가 이 값을 초기화 때 읽으므로 torch 사용 전에
# 걸어야 한다. 실측에서 1.90GiB 가 "예약됐지만 미사용" 으로 놀다가
# 1.60GiB 할당이 실패했다 — OOM 메시지가 직접 권하는 설정이다.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

MIN_LONG = 3000        # 이보다 작으면 전체 촬영이 아니다. 아래 pick_image 참조

OK, BAD, SKIP = "  ✓", "  ✗", "  ·"
fails, skips = [], []


def pick_image(explicit, roots, min_long=MIN_LONG, max_try=300):
    """
    시험용 '전체 유방 촬영' 을 고른다. 두 번 거른다.

    1차 — 크기. ROI 조각(수백 px)을 뺀다.
      그냥 sorted(rglob("*.dcm"))[0] 을 쓰면 조각이 뽑힌다. 실제로 그렇게
      시험해서 0.94초에 후보 122개가 나왔다 — 통과는 했지만 타일 훑기를
      한 번도 안 탄 시험이었다.

    2차 — 이진 여부. CBIS 는 **마스크도 전체 크기**라 크기만으로는 안 걸러진다.
      1-2.dcm(마스크 · 5,056px)이 뽑혀서 조직 상자가 병변 덩어리만 잡히고
      타일이 1장으로 끝났다. 값 종류가 2개 이하면 마스크다
      (MammoROIDataset 의 skip_binary 와 같은 기준).

    화소를 읽어야 2차를 걸 수 있으므로 1차를 통과한 것만 읽는다.
    """
    import numpy as np
    import pydicom
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p, "지정"
    n_small = n_binary = 0
    for root in roots:
        files = sorted(Path(root).rglob("*.dcm")) + \
            sorted(Path(root).rglob("*.dicom"))
        for f in files[:max_try]:
            try:
                d = pydicom.dcmread(str(f), stop_before_pixels=True)
                L = max(int(d.Rows), int(d.Columns))
            except Exception:
                continue
            if L < min_long:
                n_small += 1
                continue
            try:
                arr = pydicom.dcmread(str(f)).pixel_array
            except Exception:
                continue
            if len(np.unique(arr)) <= 2:        # 마스크
                n_binary += 1
                continue
            return f, (f"자동 · 긴 변 {L:,}px · 값 {len(np.unique(arr)):,}종 "
                       f"(조각 {n_small} · 마스크 {n_binary} 건너뜀)")
    return None, ""


def head(t):
    print(f"\n{'─' * 70}\n{t}\n{'─' * 70}")


def check(name, fn):
    """검사 하나. 예외는 실패로 잡되 나머지 검사는 계속 돈다."""
    try:
        msg = fn()
    except Exception as e:
        fails.append(name)
        print(f"{BAD} {name}\n      {type(e).__name__}: {e}")
        if "-v" in sys.argv:
            traceback.print_exc()
        return False
    if msg is None:
        skips.append(name)
        print(f"{SKIP} {name}   건너뜀")
        return True
    print(f"{OK} {name}   {msg}")
    return True


# ── 응답 스키마 선언. mammo_api.md 와 같아야 한다 ────────────────────
# 여기를 고치면 문서도 고쳐라. 반대도 마찬가지다.
TOP = {"file", "image", "dicom", "lesions", "summary", "detection",
       "model", "params", "limitations", "elapsed_sec", "disclaimer"}
LESION = {"id", "kind", "box", "frame", "score", "crop", "descriptors",
          "birads", "biopsy", "certainty", "certainty_axes", "confidence",
          "ai_size_px", "ai_size_mm", "ai_size_measurable",
          "size_omitted_reason", "aspect_ratio", "display",
          "evidence_id", "evidence_id_omitted_reason"}
SUMMARY = {"n_lesions", "max_birads", "biopsy", "abstained", "abstain_reason"}
PERCLASS = {"candidates", "outside_tissue", "thin_tile", "below_threshold", "kept", "threshold"}


# ══════════════════════ 1단계 ══════════════════════
def stage1(a):
    head("1단계 — GPU 안 씀. VinDr 이 도는 중에도 안전하다")

    # ── 패키지
    def pkgs():
        want = ["torch", "numpy", "cv2", "pydicom", "pandas"]
        # multipart 를 빼먹으면 serve_mammo 가 import 단계에서 죽는다.
        # UploadFile·Form 을 쓰는 순간 FastAPI 가 요구한다 —
        #   RuntimeError: Form data requires "python-multipart" to be installed
        # fastapi 만 보고 "있다" 고 넘어갔다가 서버가 안 떴다.
        opt = ["fastapi", "uvicorn", "anyio", "multipart"]
        miss = [m for m in want if importlib.util.find_spec(m) is None]
        if miss:
            raise RuntimeError(f"없는 패키지: {miss}")
        gone = [m for m in opt if importlib.util.find_spec(m) is None]
        if gone:
            fix = "python-multipart" if gone == ["multipart"] else \
                  "'fastapi[standard]' uvicorn python-multipart"
            return (f"필수 {len(want)}개 있음 · 라우터용 {gone} 없음 "
                    f"→ pip install {fix}")
        return f"필수 {len(want)}개 · 라우터용 {len(opt)}개 전부 있음"
    check("패키지", pkgs)

    # ── import
    def imports():
        import mammo_io                                   # noqa: F401
        import infer_mammo                                # noqa: F401
        n = len(infer_mammo.DEFAULTS)
        try:
            import serve_mammo                            # noqa: F401
            r = " · serve_mammo 도 import 됨"
        except SystemExit:
            r = " · serve_mammo 는 fastapi 가 없어 못 올림"
        return f"mammo_io · infer_mammo (기본값 {n}개){r}"
    if not check("import", imports):
        print("\n  import 가 안 되면 아래는 볼 것도 없다. 여기서 멈춘다.")
        return

    import numpy as np
    import torch
    import infer_mammo
    from mammo_io import (crop_to_tensor, expand_box, filter_tissue,
                          merge_boxes_one, read_mammogram)

    # ── 체크포인트
    def ckpts():
        out = []
        for k, p in infer_mammo.DEFAULT_CKPT.items():
            p = Path(p)
            if not p.is_file():
                raise FileNotFoundError(f"{k}: {p}")
            if k == "det":
                out.append(f"det {p.stat().st_size/2**20:.0f}MB")
                continue
            d = torch.load(str(p), map_location="cpu", weights_only=False)
            if d.get("kind") != k:
                raise ValueError(f"{k} 체크포인트의 kind 가 {d.get('kind')} 다")
            out.append(f"{k} ep{d.get('epoch')} F1 {d.get('test_f1')} "
                       f"축{len(d['cols'])}")
        return " · ".join(out)
    check("체크포인트 3개", ckpts)

    # ── read_mammogram: 경로 vs bytes  (서빙에서만 쓰는 새 경로)
    def io_paths():
        from paths import RAW_VINDR
        src = a.image and Path(a.image)
        if not src or not src.is_file():
            c = sorted(Path(RAW_VINDR).rglob("*.dicom"))[:1]
            if not c:
                return None
            src = c[0]
        a1, m1, meta1 = read_mammogram(src)
        a2, m2, meta2 = read_mammogram(src.read_bytes())
        if a1.shape != a2.shape or not np.array_equal(a1, a2):
            raise ValueError("경로로 읽은 것과 bytes 로 읽은 것이 다르다")
        if m1 != m2 or meta1 != meta2:
            raise ValueError(f"메타가 다르다: {meta1} vs {meta2}")
        return (f"{src.name[:14]} {a1.shape[1]}x{a1.shape[0]} "
                f"{m1}mm/px · 경로==bytes")
    check("read_mammogram 경로/bytes 일치", io_paths)

    # ── MONOCHROME1 을 정말 뒤집는가
    def mono1():
        import pydicom
        from paths import RAW_VINDR
        for f in sorted(Path(RAW_VINDR).rglob("*.dicom"))[:120]:
            d = pydicom.dcmread(str(f), stop_before_pixels=True)
            if str(getattr(d, "PhotometricInterpretation", "")) != "MONOCHROME1":
                continue
            raw = pydicom.dcmread(str(f)).pixel_array
            got, _, meta = read_mammogram(f)
            if not np.array_equal(got, raw.max() - raw):
                raise ValueError(f"{f.name}: 뒤집지 않았다")
            return f"{f.name[:14]} · 반전 확인 (photometric={meta['photometric']})"
        return None            # 표본에 MONOCHROME1 이 없었다
    check("MONOCHROME1 반전", mono1)

    # ── crop_to_tensor 가 학습 데이터셋과 같은가  (최대차 0 이어야 한다)
    def preproc():
        import pydicom
        from mammo_data import MammoROIDataset
        from paths import ROI_INDEX
        from train_mammo import SCHEMA
        worst, got = 0.0, 0
        for kind in ("calc", "mass"):
            csv = ROI_INDEX / f"roi_index_{kind}_test.csv"
            if not csv.is_file():
                continue
            ck = torch.load(str(infer_mammo.DEFAULT_CKPT[kind]),
                            map_location="cpu", weights_only=False)
            ar = ck.get("args", {}) or {}
            size = int(ar.get("size", 1008))
            pad = not ar.get("no_pad", False)
            clip = ar.get("clip", 99.9)
            ds = MammoROIDataset(csv, SCHEMA, kind, size=size, augment=False,
                                 pad_square=pad, clip_pct=clip)
            n = 0
            for i in range(len(ds)):
                if n >= 3:
                    break
                row = ds.df.iloc[i]
                arr = ds._read_roi(row["roi_file"])
                if arr is None:
                    continue
                ref = ((ds._resize(torch.from_numpy(arr)[None, None])[0]
                        .repeat(3, 1, 1)) - 0.5) / 0.5
                raw = pydicom.dcmread(str(row["roi_file"])).pixel_array
                mine = crop_to_tensor(raw, size, pad, clip)
                worst = max(worst, float((ref - mine).abs().max()))
                n += 1
                got += 1
        if not got:
            return None
        if worst >= 1e-5:
            raise ValueError(f"최대 차이 {worst:.2e} — 학습과 다른 입력이다. "
                             "이대로 재면 시스템 성능이 아니라 전처리 오류다")
        return f"{got}건 · 최대 차이 {worst:.2e}"
    check("crop_to_tensor == 학습 전처리", preproc)

    # ── 박스 후처리를 실제 영상으로
    def boxes():
        from make_tiles import norm8, tissue_bbox, tissue_mask
        from paths import RAW_VINDR
        src = a.image and Path(a.image)
        if not src or not src.is_file():
            c = sorted(Path(RAW_VINDR).rglob("*.dicom"))[:1]
            if not c:
                return None
            src = c[0]
        arr, _, _ = read_mammogram(src)
        u8 = norm8(arr, 99.9)
        tm = tissue_mask(u8)
        tb = tissue_bbox(tm, 32)
        if tb is None:
            raise ValueError("조직 영역을 못 찾았다")
        tsub = tm[tb[1]:tb[3], tb[0]:tb[2]] > 0
        H, W = tsub.shape
        rng = np.random.default_rng(0)
        bx = [(float(x), float(y), float(x + 120), float(y + 120),
               float(rng.random()))
              for x, y in zip(rng.integers(0, W - 130, 300),
                              rng.integers(0, H - 130, 300))]
        kept, drop = filter_tissue(bx, tsub, 0.5)
        if drop + len(kept) != len(bx):
            raise ValueError("조직 필터의 개수가 안 맞는다")
        merged = merge_boxes_one(kept, "wbf", 0.3)
        if len(merged) > len(kept):
            raise ValueError("합친 결과가 원본보다 많다")
        if any(merged[i][4] < merged[i + 1][4] for i in range(len(merged) - 1)):
            raise ValueError("점수 내림차순이 아니다")
        e = expand_box(merged[0][:4], 20.0, arr.shape) if merged else None
        if e and not (0 <= e[0] < e[2] <= arr.shape[1]
                      and 0 <= e[1] < e[3] <= arr.shape[0]):
            raise ValueError(f"넓힌 상자가 영상 밖이다: {e}")
        return (f"조직 {tsub.mean():.0%} · 300개 → 조직필터 {len(kept)} "
                f"→ wbf {len(merged)} · 여백20px 확장 OK")
    check("filter_tissue · merge_boxes_one · expand_box", boxes)

    # ── 스키마 선언이 코드와 맞는가
    def schema():
        import ast
        src = Path(infer_mammo.__file__).read_text()
        fn = {n.name: n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef)}
        ret = [n for n in ast.walk(fn["predict"]) if isinstance(n, ast.Return)][-1]
        top = {k.value for k in ret.value.keys if isinstance(k, ast.Constant)}
        if top != TOP:
            raise ValueError(f"최상위 불일치 — 코드에만 {top-TOP} · "
                             f"선언에만 {TOP-top}")
        return f"최상위 {len(top)}개 일치"
    check("응답 스키마 선언 == 코드", schema)


# ══════════════════════ 2단계 ══════════════════════
def stage2(a):
    head("2단계 — GPU 를 쓴다")
    import torch
    if not torch.cuda.is_available():
        print(f"{BAD} CUDA 를 못 쓴다")
        fails.append("cuda")
        return
    free = torch.cuda.mem_get_info()[0] / 2**30
    if free < a.need and not a.force:
        print(f"{BAD} GPU 여유 {free:.1f}GB < 필요 {a.need}GB — 거부한다")
        print("    지금 돌리면 OOM 이 나거나 돌고 있는 작업을 밀어낸다.")
        print("    nvidia-smi 로 확인하고, 정말 돌리려면 --force")
        skips.append("2단계")
        return
    print(f"  GPU 여유 {free:.1f}GB")

    import infer_mammo
    from paths import RAW_CBIS, RAW_VINDR
    src, how = pick_image(a.image, (RAW_CBIS, RAW_VINDR))
    if not src:
        print(f"{BAD} 긴 변 {MIN_LONG:,}px 이상인 영상을 못 찾았다. "
              f"--image 로 지정할 것")
        fails.append("영상 없음")
        return
    print(f"  시험 영상  {src.name}  ({how})")

    t0 = time.time()
    bundle = infer_mammo.load_model()
    print(f"{OK} load_model   {time.time()-t0:.0f}초 · "
          f"GPU {torch.cuda.memory_allocated()/2**30:.1f}GB")

    r = infer_mammo.predict(bundle, str(src))
    print(f"{OK} predict      {r['elapsed_sec']}초 · {src.name[:24]}")

    def shape():
        if set(r) != TOP:
            raise ValueError(f"최상위 불일치: 남는 {set(r)-TOP} · 없는 {TOP-set(r)}")
        if set(r["summary"]) != SUMMARY:
            raise ValueError(f"summary 불일치: {set(r['summary'])^SUMMARY}")
        for st in r["detection"]["per_class"].values():
            if set(st) != PERCLASS:
                raise ValueError(f"per_class 불일치: {set(st)^PERCLASS}")
        for l in r["lesions"]:
            if set(l) != LESION:
                raise ValueError(f"lesion 불일치: {set(l)^LESION}")
            if not (0 <= l["box"][0] < l["box"][2] <= r["image"]["width"]):
                raise ValueError(f"박스가 영상 밖이다: {l['box']}")
        if r["summary"]["abstained"] != (len(r["lesions"]) == 0):
            raise ValueError("abstained 와 lesions 개수가 안 맞는다")
        return (f"최상위 {len(TOP)} · lesion {len(r['lesions'])}건 · "
                f"기권 {r['summary']['abstained']}")
    check("응답이 mammo_api.md 스키마와 맞는가", shape)

    def swept():
        """타일 훑기가 실제로 돌았나. 조각으로 시험하면 1타일로 끝나 의미가 없다."""
        n = r["detection"]["tiles"]
        w, h = r["image"]["width"], r["image"]["height"]
        if max(w, h) < MIN_LONG:
            raise ValueError(f"{w}x{h} — 전체 촬영이 아니다. 타일 훑기를 안 탄다")
        if n < 2:
            raise ValueError(f"타일 {n}장 — 훑기 경로가 사실상 안 돌았다")
        return f"{w}x{h} · 타일 {n}장 · {r['elapsed_sec']}초"
    check("전체 촬영으로 타일을 훑었는가", swept)

    s = r["summary"]
    print(f"\n  병변 {s['n_lesions']}건 · 최고등급 {s['max_birads']} · "
          f"조직검사 {s['biopsy']} · 기권 {s['abstained']}")
    for n, st in r["detection"]["per_class"].items():
        print(f"    {n:14s} 후보 {st['candidates']:,} → 조직밖 -{st['outside_tissue']:,}"
              f" · 점수<{st['threshold']:.3f} -{st['below_threshold']:,}"
              f" → {st['kept']}건")
    for l in r["lesions"][:3]:
        d = " · ".join(f"{k}={v['value']}({v['confidence']:.2f})"
                       for k, v in l["descriptors"].items())
        print(f"    [{l['id']}] {l['kind']:14s} {l['score']:.3f} "
              f"B{l['birads']} "
              + ("크기 미산출" if l.get("ai_size_px") is None
                 else f"{l['ai_size_px']:.0f}px")
              + f"  {d}")
    if s["abstained"]:
        print("    ※ 기권 — '정상' 이 아니라 '판정 못 함' 이다")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, default=1, choices=(1, 2, 12),
                    help="1=GPU 안 씀(기본) · 2=GPU · 12=둘 다")
    ap.add_argument("--image", default="", help="시험용 DICOM")
    ap.add_argument("--need", type=float, default=14.0,
                    help="2단계에 필요한 GPU 여유(GB). 실측 최대 사용량이 "
                         "11.3GB 라 8 로는 모자랐다 — 적재 6.7GB + 추론 활성값")
    ap.add_argument("--force", action="store_true",
                    help="여유가 모자라도 2단계를 돌린다. "
                         "돌고 있는 작업을 밀어낼 수 있다")
    a = ap.parse_args()

    print("=" * 70)
    print("서빙 코드 점검 — 정적 검사는 통과했다. 이제 실제로 태운다")
    print("=" * 70)

    if a.stage in (1, 12):
        stage1(a)
    if a.stage in (2, 12):
        stage2(a)

    print("\n" + "=" * 70)
    if fails:
        print(f"실패 {len(fails)}개 — {', '.join(fails)}")
        print("고치기 전에는 서빙을 붙이지 말 것.")
    else:
        print(f"통과. 건너뜀 {len(skips)}개"
              + (f" ({', '.join(skips)})" if skips else ""))
        if a.stage == 1:
            print("\n  1단계만 돈 것이다. 적재와 추론은 아직 안 탔다 —")
            print("  VinDr 이 끝나면  python3 check_serving.py --stage 2")
    print("=" * 70)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
