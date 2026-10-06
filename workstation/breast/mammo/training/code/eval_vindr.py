#!/usr/bin/env python
"""
VinDr-Mammo 외부 검증 — CBIS 로 학습한 검출기를 다른 데이터셋에서 잰다.

무엇을 답하나
  "다른 병원, 다른 장비에서도 되는가."  발표에서 나올 질문이다.

무엇을 답하지 못하나
  VinDr 에는 BI-RADS 어휘집 서술어(모양·경계·형태·분포)가 없다. 소견 종류와
  박스만 있다. 그래서 **검출까지만** 잰다. 끝단 61.7% 는 여기서 못 잰다.

CBIS 와 다른 점 — check_vindr.py 로 실측한 것
  ① MONOCHROME1 이 73/441 장. 그대로 읽으면 밝기가 반전돼 조직 마스크가
     공기를 조직으로 잡는다. 헤더대로 뒤집는다. (개별 영상의 조직 비율로
     판단하면 안 된다 — 반전된 영상 중에도 우연히 정상처럼 보이는 것이 있다.)
  ② 영상이 작다. CBIS 긴 변 약 5,200px, VinDr 3,518~3,580px.
     같은 크기의 병변이 화소로는 더 작게 찍힌다. 우리 검출기는 원본 해상도
     타일로 학습했으므로 이 차이가 성능에 직결될 수 있다. 그래서 병변 박스의
     화소 크기와 mm 크기를 둘 다 찍어 원인을 가릴 수 있게 한다.
  ③ 유방이 화면에서 차지하는 비율   CBIS 40.9% · VinDr 17.2% (각 25장 실측)
     tissue_bbox 로 잘라내고 훑으므로 성능에 직접 영향은 작다.
     다만 영상당 타일 수가 줄어 오탐 기회도 줄어든다 — FROC 해석에 감안한다.
  ④ WindowCenter 가 441/441 에 있다(CBIS 에는 없었다). **무시한다.**
     우리 전처리는 백분위 절단 + min-max 이고, 여기서만 다르게 하면 두
     데이터셋 수치를 나란히 놓을 수 없다.

운영점은 CBIS 와 같게 맞춘다 — wbf@0.3 + 조직 마스크 필터.
FROC 은 같은 코드(eval_det)로 낸다. 그래야 비교가 성립한다.

사용
  python3 eval_vindr.py --dry            # 정답·크기만 (GPU 안 씀, 1분)
  python3 eval_vindr.py
  python3 eval_vindr.py --n 50 --save-json ../../archive/outputs/vindr_dets.json
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 조각화 완화. torch 가 CUDA 를 초기화하기 전에 걸려야 해서 import 앞이다.
# OOM 메시지가 직접 권하는 설정이다 — 공유 GPU 에서 남은 자리가 조각나
# 있으면 총량이 충분해도 큰 덩어리 하나를 못 잡는다.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

try:
    import cv2
    import numpy as np
    import pandas as pd
    import pydicom
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_det import at_fp, center_in, froc, iou                # noqa: E402
from eval_mammo_det import (PROMPTS, RES, build, import_medsam3,  # noqa: E402
                            make_batch, read_out)
from merge_boxes import WAYS, cluster                           # noqa: E402
from make_tiles import norm8, positions, tissue_bbox, tissue_mask  # noqa: E402
import mammo_cfg                                                # noqa: E402
from paths import CKPT, LABELS, MEDSAM3, RAW_VINDR              # noqa: E402

FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)
# VinDr 소견 이름 -> 우리 프롬프트
WANT = {"Mass": "mass", "Suspicious Calcification": "calcification"}

# 같은 코드로 잰 CBIS 값 — 나란히 찍어 비교한다 (에폭 6 · wbf@0.3 + 조직 필터)
CBIS = {"calcification": {0.25: .215, 0.5: .392, 1.0: .579, 2.0: .743, 4.0: .833},
        "mass":          {0.25: .262, 0.5: .387, 1.0: .564, 2.0: .703, 4.0: .799}}


def read_dicom(path):
    """
    화소와 PixelSpacing 을 돌려준다. MONOCHROME1 이면 뒤집는다.

    pydicom 의 pixel_array 는 PhotometricInterpretation 을 적용하지 않는다.
    MONOCHROME1 은 '값이 작을수록 밝다' 이므로 그대로 쓰면 반전된 영상이다.
    check_vindr.py 로 세어보니 441장 중 73장이 그렇다.

    ⚠ 화소 데이터가 잘린 파일이 섞여 있다. 200/435 에서 이것 때문에 죽어
      11.6분치 추론을 날렸다. 여기서 예외를 삼키고 부르는 쪽이 건너뛰게 한다
      — 한 장 때문에 나머지 434장을 못 재는 게 훨씬 손해다.
      어떤 파일이 깨졌는지는 scan_vindr.py 로 따로 센다.
    """
    try:
        d = pydicom.dcmread(str(path))
        arr = d.pixel_array
    except Exception as e:
        return None, None, f"!{type(e).__name__}: {e}"
    if arr.ndim != 2:
        return None, None, "!2차원이 아니다"
    photo = str(getattr(d, "PhotometricInterpretation", "MONOCHROME2"))
    if photo == "MONOCHROME1":
        arr = arr.max() - arr
    ps = getattr(d, "PixelSpacing", None) or getattr(d, "ImagerPixelSpacing", None)
    mm = float(ps[0]) if ps else None
    return arr, mm, photo


def load_gt(csv, have):
    """
    finding_annotations.csv 에서 우리가 찾는 두 종류만 뽑는다.
    반환 {image_id: [(프롬프트이름, (x0,y0,x1,y1)), ...]}  좌표는 원본 화소.
    """
    df = pd.read_csv(csv)
    need = ["image_id", "finding_categories", "xmin", "ymin", "xmax", "ymax"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        sys.exit(f"라벨에 없는 컬럼: {miss}")
    df = df[df.image_id.astype(str).isin(have)]
    out = defaultdict(list)
    n_row, n_nan, n_other = 0, 0, 0
    for r in df.to_dict("records"):
        cats = str(r["finding_categories"])
        hit = [v for k, v in WANT.items() if k in cats]
        if not hit:
            n_other += 1
            continue
        b = [r["xmin"], r["ymin"], r["xmax"], r["ymax"]]
        if any(v != v for v in b):          # NaN — 박스 없는 행
            n_nan += 1
            continue
        for name in hit:                    # 한 박스에 두 종류가 붙기도 한다
            out[str(r["image_id"])].append((name, tuple(float(v) for v in b)))
        n_row += 1
    print(f"  정답 {n_row:,}행 · 영상 {len(out):,}장"
          f"   (박스 없음 {n_nan} · 다른 소견 {n_other})")
    return out


def show_sizes(gt, imgs, n=60):
    """
    병변 박스의 화소·mm 크기. CBIS 와 다르면 성능 차이의 원인 후보가 된다.
    영상을 헤더만 읽으므로 빠르다.
    """
    per = defaultdict(list)
    mms = []
    for i, (iid, lst) in enumerate(list(gt.items())[:n]):
        try:
            d = pydicom.dcmread(str(imgs[iid]), stop_before_pixels=True)
        except Exception:
            continue
        ps = getattr(d, "PixelSpacing", None) or \
            getattr(d, "ImagerPixelSpacing", None)
        mm = float(ps[0]) if ps else None
        if mm:
            mms.append(mm)
        for name, b in lst:
            w, h = b[2] - b[0], b[3] - b[1]
            per[name].append((max(w, h), max(w, h) * mm if mm else np.nan))
    print(f"\n  병변 박스 크기  (표본 {n}장)")
    print(f"    {'종류':16s}{'건':>6s}{'화소 중앙':>11s}{'10~90퍼':>16s}{'mm 중앙':>10s}")
    print("    " + "-" * 60)
    for name, v in per.items():
        px = np.array([x[0] for x in v])
        mm = np.array([x[1] for x in v], float)
        mm = mm[~np.isnan(mm)]
        print(f"    {name:16s}{len(px):>6d}{np.median(px):>11.0f}"
              f"{np.percentile(px,10):>8.0f}~{np.percentile(px,90):<7.0f}"
              f"{np.median(mm) if len(mm) else float('nan'):>10.1f}")
    if mms:
        m = np.array(mms)
        print(f"\n    화소 간격  중앙 {np.median(m):.3f}mm "
              f"(범위 {m.min():.3f}~{m.max():.3f})")
    print("\n    ! CBIS 는 긴 변 약 5,200px, VinDr 은 3,518~3,580px 다.")
    print("      같은 mm 크기의 병변이 화소로는 더 작게 찍힌다. 우리 검출기는")
    print("      원본 해상도 타일로 학습했으므로 이 차이가 성능에 직결될 수 있다.")


def nms_like(boxes, way, thr, topk=0):
    merged = [WAYS[way](g) for g in cluster(boxes, thr)]
    merged.sort(key=lambda b: -b[4])
    return merged[:topk] if topk else merged


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(mammo_cfg.DEFAULT))
    known, _ = pre.parse_known_args()
    CFG = mammo_cfg.load(known.config)

    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument("--repo", default=str(MEDSAM3))
    ap.add_argument("--lora", default=str(CKPT / "last_lora.pt"))
    ap.add_argument("--csv", default=str(LABELS / "finding_annotations.csv"))
    ap.add_argument("--tile", type=int, default=RES)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--thr", type=float, default=0.05)
    ap.add_argument("--nms", type=float, default=0.3)
    ap.add_argument("--merge", default="wbf", choices=list(WAYS))
    ap.add_argument("--tissue-frac", type=float, default=0.5)
    # 화소 간격을 CBIS 에 맞춰 키운다.
    #
    # 왜 필요한가
    #   VinDr 은 0.085mm/px 다. 낱개 미세석회(0.2~0.5mm)가 2.4~5.9px 로 찍힌다.
    #   CBIS 가 그보다 조밀하면 우리 검출기는 더 큰 알갱이를 보고 배운 것이다.
    #   이 프로젝트의 핵심 발견이 '석회는 화소 크기가 줄면 사라진다' 였으므로
    #   (5배 축소로 신호의 84%를 잃었다), 배율 차이는 그냥 넘길 수 없다.
    #
    #   맞추지 않고 한 번, 맞추고 한 번 돌려야 원인이 갈린다.
    #     떨어졌는데 배율을 맞추니 회복  -> 해상도 문제
    #     맞춰도 그대로               -> 촬영 방식이나 정답 기준 문제
    #
    #   ! 키운다고 없던 정보가 생기지는 않는다. 0.085mm 검출기가 실제로
    #     분해하지 못한 것은 키워도 흐릿할 뿐이다. 그래도 '모델이 학습한
    #     크기로 보여줬을 때' 를 재는 것이 목적이라 의미가 있다.
    ap.add_argument("--target-mm", type=float, default=0.0,
                    help="이 화소 간격이 되도록 키운다. CBIS 값을 넣어라. "
                         "0 이면 원본 크기 그대로")
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--dry", action="store_true",
                    help="정답과 크기만 본다. 모델을 안 세운다")
    ap.add_argument("--oom-retry", type=int, default=2,
                    help="OOM 이 나면 자리를 비우고 몇 번까지 다시 해볼까. "
                         "GPU 를 다른 사람과 같이 쓴다")
    ap.add_argument("--oom-wait", type=int, default=60,
                    help="OOM 재시도 전 대기(초)")
    ap.add_argument("--save-json", default="")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--target-modules",
                    default="q_proj,k_proj,v_proj,out_proj,qkv,proj,fc1,fc2,"
                            "linear1,linear2")
    ap.add_argument("--vision", type=int, default=1)
    ap.add_argument("--text", type=int, default=0)
    ap.add_argument("--detr-enc", type=int, default=1)
    ap.add_argument("--detr-dec", type=int, default=1)
    ap.add_argument("--mask-dec", type=int, default=0)
    ap.set_defaults(**mammo_cfg.lora_args(CFG))
    a = ap.parse_args()

    # import_medsam3 가 os.chdir 를 한다. 상대경로를 지금 굳힌다.
    a.lora = str(Path(a.lora).expanduser().resolve())
    a.csv = str(Path(a.csv).expanduser().resolve())
    if a.save_json:
        a.save_json = str(Path(a.save_json).expanduser().resolve())

    print("=" * 76)
    print("VinDr-Mammo 외부 검증 — CBIS 로 학습한 검출기")
    print("=" * 76)
    print(f"  영상    {RAW_VINDR}")
    print(f"  합치기  {a.merge}@{a.nms:g} · 조직 필터 {a.tissue_frac:.0%}"
          "   (CBIS 운영점과 같다)")
    print(f"  배율    " + (f"화소 간격을 {a.target_mm:.4f}mm 로 맞춘다"
                          if a.target_mm > 0 else "원본 그대로"))

    imgs = {}
    for ext in ("*.dicom", "*.dcm", "*.DCM"):
        for f in RAW_VINDR.rglob(ext):
            imgs[f.stem] = f
    print(f"  DICOM   {len(imgs):,}개")
    if not imgs:
        sys.exit("받은 영상이 없다")

    gt = load_gt(a.csv, set(imgs))
    uids = sorted(gt)
    if a.n:
        uids = uids[:a.n]

    if a.dry:
        show_sizes(gt, imgs)
        print("\n  --dry 는 여기까지다. 모델을 세우려면 빼고 돌려라.")
        return

    M = import_medsam3(a.repo)          # 여기서 cwd 가 바뀐다
    dev = torch.device("cuda")
    model = build(a, M, dev)

    stride = max(1, a.tile - a.overlap)
    dets = {n: [] for n in PROMPTS}
    gts = {n: defaultdict(list) for n in PROMPTS}
    n_tiles, done, inv, t0 = 0, 0, 0, time.time()
    scales, skipped, oomed = [], [], []

    print(f"\n[2/2] 추론  {len(uids)}장")
    for i, iid in enumerate(uids, 1):
        arr, mm, photo = read_dicom(imgs[iid])
        if arr is None:
            # 조용히 건너뛰지 않는다. 몇 장이 빠졌는지 모르면 민감도의 분모가
            # 틀린 채로 결과를 읽게 된다.
            skipped.append((iid, (photo or "?").lstrip("!")))
            continue
        if photo == "MONOCHROME1":
            inv += 1

        # 정규화를 먼저 하고 키운다 — 백분위는 원본 화소 분포에서 잡아야
        # CBIS 와 같은 전처리가 된다.
        u8 = norm8(arr, a.clip)
        sc = 1.0
        if a.target_mm > 0 and mm:
            sc = mm / a.target_mm
            if abs(sc - 1.0) > 0.01:
                u8 = cv2.resize(u8, None, fx=sc, fy=sc,
                                interpolation=cv2.INTER_CUBIC)
                scales.append(sc)

        tmask = tissue_mask(u8)
        tb = tissue_bbox(tmask, a.pad)
        if tb is None:
            continue
        cx0, cy0, cx1, cy1 = tb
        img = u8[cy0:cy1, cx0:cx1]
        tsub = tmask[cy0:cy1, cx0:cx1] > 0
        H, W = img.shape[:2]

        for name, b in gt[iid]:            # 정답도 같은 배율로 옮긴다
            gts[name][iid].append((b[0] * sc - cx0, b[1] * sc - cy0,
                                   b[2] * sc - cx0, b[3] * sc - cy0))

        # GPU 를 다른 사람과 같이 쓴다. 남은 자리가 없으면 OOM 이 나는데,
        # 그때 죽어버리면 그때까지의 추론(20여분)이 통째로 날아간다.
        # 자리를 비우고 기다렸다 다시 해보고, 그래도 안 되면 이 한 장만
        # 건너뛴다. 몇 장을 건너뛰었는지는 끝에 반드시 찍는다.
        raw, ok = None, False
        for attempt in range(a.oom_retry + 1):
            try:
                raw = {n: [] for n in PROMPTS}
                got_tiles = 0
                with torch.inference_mode():
                    for ty in positions(H, a.tile, stride):
                        for tx in positions(W, a.tile, stride):
                            sub = img[ty:ty + a.tile, tx:tx + a.tile]
                            if sub.shape != (a.tile, a.tile):
                                q = np.zeros((a.tile, a.tile), np.uint8)
                                q[:sub.shape[0], :sub.shape[1]] = sub
                                sub = q
                            got = read_out(model(make_batch(M, sub, dev)), a.thr)
                            got_tiles += 1
                            for n, lst in got.items():
                                for b in lst:
                                    raw[n].append((b[0] + tx, b[1] + ty,
                                                   b[2] + tx, b[3] + ty, b[4]))
                n_tiles += got_tiles
                ok = True
                break
            except torch.OutOfMemoryError:
                torch.cuda.empty_cache()
                free_gb = torch.cuda.mem_get_info()[0] / 2**30
                if attempt < a.oom_retry:
                    print(f"\n  OOM — 자리를 비우고 {a.oom_wait}초 뒤 다시 "
                          f"(여유 {free_gb:.1f}GB · {attempt+1}/{a.oom_retry})",
                          flush=True)
                    time.sleep(a.oom_wait)
                else:
                    oomed.append(iid)
                    print(f"\n  OOM — {iid[:20]} 건너뜀 (여유 {free_gb:.1f}GB). "
                          f"다른 작업이 GPU 를 쓰고 있다", flush=True)
        if not ok:
            continue

        for n in PROMPTS:
            cand = raw[n]
            if a.tissue_frac > 0:                  # 합치기 '전' 에 거른다
                keep = []
                for b in cand:
                    x0, y0 = max(0, int(b[0])), max(0, int(b[1]))
                    x1 = min(tsub.shape[1], int(b[2]))
                    y1 = min(tsub.shape[0], int(b[3]))
                    if x1 > x0 and y1 > y0 and \
                            tsub[y0:y1, x0:x1].mean() >= a.tissue_frac:
                        keep.append(b)
                cand = keep
            for b in nms_like(cand, a.merge, a.nms):
                dets[n].append(dict(img=iid, box=list(b[:4]), score=float(b[4])))
        done += 1
        if i % 10 == 0 or i == len(uids):
            el = time.time() - t0
            print(f"\r  {i}/{len(uids)}  타일 {n_tiles:,}  {el/60:.1f}분 · "
                  f"남은 {el/i*(len(uids)-i)/60:.0f}분"
                  + (f" · 건너뜀 {len(skipped)}" if skipped else "")
                  + "   ", end="", flush=True)
        # 중간 저장. 마지막에만 저장했다가 200/435 에서 죽어 11.6분치를 날렸다.
        # 추론이 GPU 20여분이라 다시 도는 비용이 저장 비용보다 훨씬 크다.
        if a.save_json and i % 50 == 0:
            try:
                p = Path(a.save_json)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.with_suffix(".partial.json").write_text(
                    json.dumps(dets, default=float))
            except Exception as e:
                print(f"\n  ! 중간 저장 실패: {type(e).__name__}: {e}")
    print()
    print(f"\n  영상 {done}장 · 타일 {n_tiles:,} (영상당 {n_tiles/max(1,done):.1f})")
    print(f"  MONOCHROME1 뒤집음 {inv}장")
    if oomed:
        print(f"\n  ! OOM 으로 건너뛴 영상 {len(oomed)}장 — 분모가 그만큼 줄었다")
        print(f"      {', '.join(i[:16] for i in oomed[:6])}"
              + (f" … 외 {len(oomed)-6}" if len(oomed) > 6 else ""))
        print("    GPU 가 비었을 때 다시 돌릴 것. nvidia-smi 로 확인.")
    if skipped:
        # 분모가 달라진다. 조용히 넘어가면 민감도를 435장 기준으로 읽게 된다.
        print(f"\n  ! 못 읽은 영상 {len(skipped)}장 — 아래 수치의 분모는 "
              f"{len(uids)}장이 아니라 {done}장이다")
        for iid, why in skipped[:10]:
            print(f"      {iid[:24]:26s} {why[:70]}")
        if len(skipped) > 10:
            print(f"      … 외 {len(skipped)-10}장")
        print("    화소 데이터가 잘린 파일이다. scan_vindr.py 로 전수 확인하고")
        print("    다시 받은 뒤 재실행할 것.")
    if scales:
        v = np.array(scales)
        print(f"  배율 조정 {len(v)}장 · 중앙 {np.median(v):.2f}배 "
              f"(목표 화소 간격 {a.target_mm:.4f}mm)")
    elif a.target_mm > 0:
        print(f"  ! --target-mm 을 줬는데 조정된 영상이 없다 "
              f"(PixelSpacing 이 없거나 이미 목표값이다)")
    print(f"  ! CBIS 는 영상당 31.3 타일이었다. VinDr 은 영상이 작아 타일이 적고,")
    print(f"    그만큼 오탐 기회도 적다. FROC 해석에 감안해라.")

    out = {}
    for name in PROMPTS:
        g = {u: v for u, v in gts[name].items() if v}
        n_gt = sum(len(v) for v in g.values())
        if not n_gt:
            continue
        print(f"\n{'='*76}\n{name}   정답 {n_gt}건 / 영상 {len(g)}장 "
              f"(전체 {done}장)\n{'='*76}")
        res = {}
        for label, fn in ((f"IoU>{a.iou:.1f}",
                           lambda p, q: 1.0 if iou(p, q) >= a.iou else 0.0),
                          ("중심 명중",
                           lambda p, q: 1.0 if center_in(p, q) else 0.0)):
            curve = froc(dets[name], n_gt, done, fn, g)
            print(f"\n  ── {label} ──")
            print(f"    {'영상당 오탐':12s}{'VinDr':>9s}{'CBIS':>9s}{'차이':>9s}")
            for t in FP_POINTS:
                s, _ = at_fp(curve, t)
                c = CBIS[name][t] if label == "중심 명중" else None
                d = f"{(s-c)*100:+8.1f}p" if c is not None else " " * 9
                cc = f"{c:8.1%}" if c is not None else " " * 8
                print(f"      {t:4.2f}      {s:8.1%}{cc} {d}")
                if label == "중심 명중":
                    res[t] = float(s)
            if curve:
                print(f"    (검출 {len(curve):,}개 · 최대 "
                      f"{max(s for _, s, _ in curve):.1%})")
        out[name] = res

    print("\n" + "=" * 76)
    print("읽는 법")
    print("=" * 76)
    print("  CBIS 열은 같은 가중치·같은 운영점·같은 FROC 코드로 잰 값이다.")
    print("  떨어졌다면 원인 후보가 셋이다 — 어느 것인지 따로 확인해야 한다.")
    print("    ① 촬영 방식 (필름 스캔 대 디지털)")
    print("    ② 영상 크기 (5,200px 대 3,550px) — 병변의 화소 크기가 다르다")
    print("    ③ 정답 기준 (CBIS 는 조직검사 확정 병변, VinDr 은 판독의 표시)")
    print("  ③ 이 특히 중요하다. VinDr 의 'Suspicious Calcification' 은 판독의가")
    print("  의심스럽다고 표시한 것이고 조직검사로 확인된 것이 아니다.")
    print("  두 데이터셋의 '정답' 이 같은 것을 뜻하지 않는다.")

    if a.save_json:
        try:
            p = Path(a.save_json)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(dets, default=float))
            print(f"\n  검출 저장 -> {p}")
        except Exception as e:
            print(f"\n  ! 저장 실패: {type(e).__name__}: {e}")
    print(f"\n  요약 {json.dumps(out, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
