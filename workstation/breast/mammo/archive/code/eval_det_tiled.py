#!/usr/bin/env python
"""
타일 검출기 평가 — 유방 전체를 훑어 원본 영상 단위로 잰다.

왜 따로 만드나
  학습용 타일을 그대로 평가에 쓰면 오탐이 과소평가된다. 학습용은 영상당
  음성 타일을 2장만 뽑았는데, 실제로는 유방 전체를 훑는다. 훑는 면적이
  넓어질수록 오탐 기회가 늘어난다. 3.5 타일만 보고 '영상당 오탐 1개' 라고
  하면 실제보다 후한 값이 나온다.

  그래서 중간 파일을 만들지 않는다. 원본 DICOM 을 읽어 유방 전체를 타일로
  훑고, 박스를 원본 좌표로 되돌린 뒤 타일 간 중복을 지우고, 원본 영상
  단위로 FROC 을 낸다. 디스크를 안 쓰고 실제 배치와 같은 조건이다.

무엇과 비교하나
  기준선   eval_det.py — 1024 로 줄인 전체 영상 (지금 산출물)
  이 쪽    원본 해상도 타일

  입력 방식이 다르지만 최종 지표는 같은 것을 잰다.
  '같은 598명에 대해 영상당 오탐 1개를 허용할 때 병변의 몇 %를 찾는가'
  이 층위에서는 정당한 비교다.

겹침 처리
  타일이 겹치므로 같은 병변이 여러 번 잡힌다. 원본 좌표로 되돌린 뒤
  NMS 로 합친다. FROC 은 정답 하나를 한 번만 맞힌 것으로 세므로
  합치지 않으면 중복 검출이 전부 오탐이 되어 부당하게 나빠진다.

사용
  python3 eval_det_tiled.py --check              # 3장만
  python3 eval_det_tiled.py --n 100
  python3 eval_det_tiled.py --ckpt det_tile_run/checkpoints/checkpoint.pt
"""

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    import cv2
    import pandas as pd
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

# 지표와 모델 구성은 기준선과 똑같은 코드를 쓴다 — 달라지면 비교가 깨진다
from eval_det import at_fp, build_model, center_in, extract_boxes, froc, iou
from make_tiles import CAT, mask_box, norm8, positions, tissue_bbox, tissue_mask

HOME = Path.home()
RAW = HOME / "workspace/breast/data/cbis/raw"
INDEX = HOME / "workspace/breast/labels/index"
DEF_CKPT = HOME / "workspace/breast/mammo/det_tile_run/checkpoints/checkpoint.pt"

PROMPTS = {1: "mass", 2: "calcification"}     # 기존 det/ 및 eval_det.py 와 같은 번호
FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)


def nms(boxes, thr):
    """겹치는 검출을 합친다. boxes = [(x0,y0,x1,y1,score), ...]"""
    if not boxes:
        return []
    b = sorted(boxes, key=lambda x: -x[4])
    keep = []
    while b:
        cur = b.pop(0)
        keep.append(cur)
        b = [x for x in b if iou(cur[:4], x[:4]) < thr]
    return keep


def load_gt(split):
    """{uid: {"dcm": path, "gt": {cat: [box, ...]}}} — 원본 좌표다."""
    out = {}
    for kind, cid in CAT.items():
        csv = INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            print(f"  ! 인덱스 없음: {csv}")
            continue
        for rec in pd.read_csv(csv).to_dict("records"):
            mp = str(rec.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            uid = str(rec.get("image_path", "")).strip().split("/")[-2]
            d = RAW / uid
            if not d.is_dir():
                continue
            fs = sorted(d.glob("*.dcm"))
            if not fs:
                continue
            out.setdefault(uid, {"dcm": fs[0], "gt": defaultdict(list),
                                 "masks": []})
            out[uid]["masks"].append((cid, mp))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(DEF_CKPT))
    ap.add_argument("--split", default="test")
    ap.add_argument("--tile", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--thr", type=float, default=0.05)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--nms", type=float, default=0.3,
                    help="타일 간 중복을 합칠 IoU 문턱")
    ap.add_argument("--n", type=int, default=0, help="영상 수 제한")
    ap.add_argument("--check", action="store_true", help="3장만 돌려 구조 확인")
    ap.add_argument("--no-seg", action="store_true")
    a = ap.parse_args()

    print("=" * 74)
    print("타일 검출기 평가 — 유방 전체 훑기, 원본 영상 단위")
    print("=" * 74)
    print(f"  체크포인트 {a.ckpt}")
    print(f"  타일 {a.tile}px · 겹침 {a.overlap}px · 합침 IoU {a.nms}")

    ents = load_gt(a.split)
    if not ents:
        sys.exit("  ! 평가할 영상이 없다")
    uids = sorted(ents)
    if a.check:
        uids = uids[:3]
    elif a.n:
        uids = uids[:a.n]
    print(f"  영상 {len(uids)}장")

    model = build_model(a.ckpt, a.device, with_seg=not a.no_seg)

    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    proc = Sam3Processor(model, device=a.device, confidence_threshold=a.thr)

    stride = max(1, a.tile - a.overlap)
    dets = {c: [] for c in PROMPTS}
    gts = {c: defaultdict(list) for c in PROMPTS}
    n_tiles, t0, done = 0, time.time(), 0

    import pydicom
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception as ex:
            print(f"\n  ! {uid} 읽기 실패: {ex}")
            continue
        if arr.ndim != 2:
            continue

        # 정답 — 원본 좌표
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = mask_box(mp)
            if b is None or shp != arr.shape[:2]:
                continue
            boxes.append((cid, b))
        if not boxes:
            continue

        u8 = norm8(arr, a.clip)
        mask = tissue_mask(u8)
        tb = tissue_bbox(mask, a.pad)
        if tb is None:
            continue
        cx0, cy0, cx1, cy1 = tb
        img = u8[cy0:cy1, cx0:cx1]
        H, W = img.shape[:2]
        for cid, b in boxes:
            gts[cid][uid].append((b[0] - cx0, b[1] - cy0,
                                  b[2] - cx0, b[3] - cy0))

        # 유방 전체를 훑는다
        raw = {c: [] for c in PROMPTS}
        for ty in positions(H, a.tile, stride):
            for tx in positions(W, a.tile, stride):
                sub = img[ty:ty + a.tile, tx:tx + a.tile]
                if sub.shape[0] != a.tile or sub.shape[1] != a.tile:
                    p = np.zeros((a.tile, a.tile), np.uint8)
                    p[:sub.shape[0], :sub.shape[1]] = sub
                    sub = p
                pil = Image.fromarray(sub).convert("RGB")
                n_tiles += 1
                for cid, prompt in PROMPTS.items():
                    # 프롬프트마다 state 를 새로 만든다 — 소비되는 구조다
                    state = proc.set_image(pil)
                    try:
                        res = proc.set_text_prompt(prompt, state)
                    except Exception as ex:
                        if i == 1:
                            print(f"\n    ! {prompt} 실패: "
                                  f"{type(ex).__name__}: {ex}")
                        continue
                    for bx in extract_boxes(res, a.tile, a.tile):
                        # 타일 좌표 -> 잘라낸 유방 좌표
                        raw[cid].append((bx[0] + tx, bx[1] + ty,
                                         bx[2] + tx, bx[3] + ty, bx[4]))

        for cid in PROMPTS:
            for bx in nms(raw[cid], a.nms):
                dets[cid].append(dict(img=uid, box=bx[:4], score=bx[4]))
        done += 1

        if a.check and i == 1:
            print(f"\n  첫 영상 {uid}")
            print(f"    유방 영역 {W}x{H}   타일 "
                  f"{len(positions(H,a.tile,stride))}x"
                  f"{len(positions(W,a.tile,stride))}")
            for cid, prompt in PROMPTS.items():
                print(f"    {prompt}: 합치기 전 {len(raw[cid])} -> "
                      f"후 {len(nms(raw[cid], a.nms))}   정답 {len(gts[cid][uid])}")
        if i % 5 == 0 or i == len(uids):
            el = time.time() - t0
            print(f"\r  {i}/{len(uids)}   타일 {n_tiles:,}   "
                  f"{el/60:.1f}분 경과 · 남은 {el/i*(len(uids)-i)/60:.0f}분   ",
                  end="", flush=True)
    print()

    if a.check:
        print("\n  구조 확인 완료. --check 를 빼고 돌려라.")
        return

    print(f"\n  영상 {done}장 · 타일 {n_tiles:,}장 "
          f"(영상당 {n_tiles/max(1,done):.1f})")

    # ── 지표 ───────────────────────────────────────────────────────────
    for cid, prompt in PROMPTS.items():
        g = {u: v for u, v in gts[cid].items() if v}
        n_gt = sum(len(v) for v in g.values())
        if n_gt == 0:
            continue
        print(f"\n{'='*74}")
        print(f"{prompt}   정답 병변 {n_gt}건 / 영상 {len(g)}장 (전체 {done}장)")
        print("=" * 74)

        for label, fn in (
                (f"IoU>{a.iou:.1f}",
                 lambda p, q: 1.0 if iou(p, q) >= a.iou else 0.0),
                ("중심 명중",
                 lambda p, q: 1.0 if center_in(p, q) else 0.0)):
            curve = froc(dets[cid], n_gt, done, fn, g)
            print(f"\n  ── {label} ──")
            print("    영상당 오탐    민감도    임계값")
            for t in FP_POINTS:
                s, sc = at_fp(curve, t)
                print(f"      {t:4.2f}         {s:6.1%}    "
                      f"{f'{sc:.3f}' if sc is not None else '—'}")
            if curve:
                print(f"    (전체 검출 {len(curve)}개 · "
                      f"최대 민감도 {max(s for _, s, _ in curve):.1%})")

        # ── 크기별 ────────────────────────────────────────────────────
        areas = [((q[2]-q[0])*(q[3]-q[1]), u, gi)
                 for u, gl in g.items() for gi, q in enumerate(gl)]
        if len(areas) >= 6:
            areas.sort()
            k = len(areas) // 3
            curve = froc(dets[cid], n_gt, done,
                         lambda p, q: 1.0 if center_in(p, q) else 0.0, g)
            _, sc = at_fp(curve, 1.0)
            sc = sc if sc is not None else 0.0
            keep = [d for d in dets[cid] if d["score"] >= sc]
            print("\n  ── 크기별 재현율 (중심 명중 · 오탐 1개/영상 지점) ──")
            print("    구간        병변수   한 변 중앙   재현율")
            for name, band in (("작은 1/3", areas[:k]),
                               ("중간 1/3", areas[k:2*k]),
                               ("큰 1/3", areas[2*k:])):
                hit = sum(1 for ar, u, gi in band
                          if any(d["img"] == u and center_in(d["box"], g[u][gi])
                                 for d in keep))
                med = np.sqrt(np.median([ar for ar, _, _ in band]))
                print(f"    {name:10s} {len(band):5d}   {med:8.0f}px   "
                      f"{hit/len(band):8.1%}")

    print(f"\n{'='*74}")
    print("기준선과 비교하는 법")
    print("=" * 74)
    print("  기준선  python3 eval_det.py            (1024 축소 전체 영상)")
    print("  이 쪽   python3 eval_det_tiled.py      (원본 해상도 타일)")
    print()
    print("  같은 환자군이므로 '오탐 1개/영상 지점의 민감도' 를 직접 비교한다.")
    print("  석회가 6.8% 에서 올라가고 종괴가 62% 를 유지하면 조치가 먹은 것이다.")
    print("  종괴가 떨어졌다면 타일이 큰 종괴를 잘랐다는 뜻이다 — 타일을 키운다.")


if __name__ == "__main__":
    main()
