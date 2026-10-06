#!/usr/bin/env python
"""
타일 검출기 평가 — 동결 본체 + LoRA 를 세우고 유방 전체를 훑는다.

왜 새로 쓰나
  eval_det_tiled.py 는 전체 체크포인트를 통째로 불러오는 전제였다. 통합 구조는
  LoRA 만 저장하므로(11M · 44MB) 병합본을 세운 뒤 LoRA 를 얹어야 한다.
  모델을 세우는 방식이 학습과 한 글자도 달라선 안 된다 — 다르면 성능이
  아니라 구성 오류를 재게 된다.

왜 중간 파일을 안 만드나
  학습용 타일을 그대로 평가에 쓰면 오탐이 과소평가된다. 학습용은 영상당 음성
  타일을 2장만 뽑았는데 실제로는 유방 전체를 훑는다. 훑는 면적이 넓어질수록
  오탐 기회가 늘어난다.
  그래서 원본 DICOM 을 읽어 유방 전체를 타일로 훑고, 박스를 원본 좌표로
  되돌린 뒤 겹침을 합쳐 원본 영상 단위로 FROC 을 낸다.

기준선과 무엇을 비교하나
  기준선  1008 로 줄인 전체 영상 · 전체 미세조정 838M · 에폭 20
          종괴 57.3% · 석회 18.6%   (오탐 1개/영상 · 중심 명중)
          mAP 종괴 0.157 · 석회 0.002
  이 쪽   원본 해상도 타일 · 동결 + LoRA 11M

  입력 방식과 학습 방식이 다르지만 최종 질문은 같다 —
  '같은 598명에 대해 오탐을 1개 허용할 때 병변의 몇 %를 찾는가'.

사용
  python3 eval_mammo_det.py --check
  python3 eval_mammo_det.py --lora ../ckpt/best_lora.pt
  python3 eval_mammo_det.py --n 100 --save-json tile_dets.json
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import cv2
    import pandas as pd
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

# 지표는 기준선과 같은 코드를 쓴다 — 복사하면 한쪽만 고쳐졌을 때 비교가 깨진다
from eval_det import at_fp, center_in, froc, iou            # noqa: E402
import mammo_cfg                                            # noqa: E402
from make_tiles import (CAT, mask_box, norm8, positions,    # noqa: E402
                        tissue_bbox, tissue_mask)
# 적재·전처리는 서빙과 같은 구현을 쓴다. 여기에 복사본을 두면 서빙만 고쳐졌을 때
# 시연 화면과 이 측정치가 조용히 어긋난다 — mammo_io.py 머리말 참조.
from mammo_io import (PROMPTS, RES, build_detector,        # noqa: E402,F401
                      import_medsam3, make_batch, read_out)
from mammo_io import move_to_device as move                # noqa: E402,F401
from paths import CKPT, MEDSAM3, RAW_CBIS, ROI_INDEX       # noqa: E402

FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)


def build(a, M, dev):
    """학습과 같은 방식으로 세운다 — 병합본 + 같은 LoRA 설정 + 학습된 가중치."""
    print("[1/2] 병합본 + LoRA")
    lp = Path(a.lora)
    if not lp.is_absolute():
        lp = (CKPT / lp.name) if not lp.exists() else lp.resolve()
    if not lp.is_file():
        sys.exit(f"      ✗ 학습된 LoRA 가 없다: {lp}\n"
                 "        학습이 끝나야 평가할 수 있다.")
    model = build_detector(
        M, lp, dev, rank=a.rank, alpha=a.alpha,
        target_modules=[s.strip() for s in a.target_modules.split(",") if s.strip()],
        vision=a.vision, text=a.text, detr_enc=a.detr_enc,
        detr_dec=a.detr_dec, mask_dec=a.mask_dec, verbose=False)
    c = M["count_parameters"](model)
    print(f"      LoRA 자리 {c['trainable_parameters']:,} "
          f"({c['trainable_percentage']:.3f}%)")
    print(f"      가중치 {lp.name}  {lp.stat().st_size/2**20:.0f}MB")
    return model


def fake_out(tile, rng):
    """
    --dry 용 가짜 검출. 모델 없이 뒤쪽 경로(좌표 되돌리기 · NMS · FROC)를 굴린다.
    학습이 GPU 를 다 쓰고 있을 때 우리가 새로 짠 부분만 확인하기 위한 것이다.
    """
    out = {}
    for n in PROMPTS:
        k = int(rng.integers(1, 5))
        lst = []
        for _ in range(k):
            w = float(rng.integers(30, 200))
            x = float(rng.integers(0, max(1, tile - int(w))))
            y = float(rng.integers(0, max(1, tile - int(w))))
            lst.append((x, y, x + w, y + w, float(rng.random())))
        out[n] = lst
    return out


def nms(boxes, thr):
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
    out = {}
    for kind, cid in CAT.items():
        csv = ROI_INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            print(f"  ! 인덱스 없음: {csv}")
            continue
        for r in pd.read_csv(csv).to_dict("records"):
            mp = str(r.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            uid = str(r.get("image_path", "")).strip().split("/")[-2]
            d = RAW_CBIS / uid
            fs = sorted(d.glob("*.dcm")) if d.is_dir() else []
            if not fs:
                continue
            out.setdefault(uid, {"dcm": fs[0], "masks": []})
            out[uid]["masks"].append((cid, mp))
    return out


def main():
    # 설정을 먼저 읽어 argparse 기본값을 덮는다. 명령줄이 우선한다.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(mammo_cfg.DEFAULT))
    known, _ = pre.parse_known_args()
    CFG = mammo_cfg.load(known.config)

    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument("--repo", default=str(MEDSAM3))
    # best 가 아니라 last 다. best 는 검증 손실로 골랐는데 그 기준이 틀렸다 —
    # 손실이 오르는 동안 검출은 계속 좋아졌다(에폭 0 대 5 를 실측 비교).
    ap.add_argument("--lora", default=str(CKPT / "last_lora.pt"))
    ap.add_argument("--split", default="test")
    ap.add_argument("--tile", type=int, default=RES)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--thr", type=float, default=0.05)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--nms", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="3장만")
    ap.add_argument("--dry", action="store_true",
                    help="모델을 안 세운다. 가짜 검출로 뒤쪽 경로만 확인한다 "
                         "— GPU 를 학습이 쓰고 있을 때")
    ap.add_argument("--save-json", default="")
    # 합치기 전 박스도 남긴다.
    #
    # 왜
    #   --save-json 은 NMS 를 통과한 박스만 담는다. 그래서 나중에 '합치는
    #   방식을 바꾸면 어떻게 되나' 를 실험하려면 추론을 통째로 다시 해야 한다
    #   (83분 · GPU). 지금 한 줄 더 쓰면 그 실험이 CPU 몇 분으로 끝난다.
    #   종괴 AP75 가 0.088 -> 0.022 로 떨어진 원인 중 하나가 겹침 NMS 가
    #   점수 최대 박스 하나만 남기는 것이라, 그 실험을 반드시 하게 된다.
    ap.add_argument("--save-raw", default="",
                    help="합치기 전 박스도 저장한다 (합치는 방식 실험용)")
    ap.add_argument("--raw-topk", type=int, default=300,
                    help="영상·종류당 점수 상위 몇 개까지 남길지. "
                         "전부 남기면 파일이 수 GB 가 된다")
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
    # 설정에 있는 항목만 덮는다. 없으면 위의 기본값이 남는다.
    ap.set_defaults(**mammo_cfg.lora_args(CFG), **mammo_cfg.eval_args(CFG))
    a = ap.parse_args()

    # 상대경로를 지금 절대경로로 굳힌다.
    # import_medsam3 가 os.chdir 를 하므로, 그 뒤에는 상대경로가 다른 곳을
    # 가리킨다. 추론이 끝난 마지막 줄에서 그 사실을 알게 되면 늦다.
    if a.save_json:
        a.save_json = str(Path(a.save_json).expanduser().resolve())
    if a.save_raw:
        a.save_raw = str(Path(a.save_raw).expanduser().resolve())
    a.lora = str(Path(a.lora).expanduser().resolve())

    print("=" * 74)
    print("타일 검출기 평가 — 유방 전체 훑기, 원본 영상 단위")
    print("=" * 74)
    mammo_cfg.show(CFG, known.config)
    print(f"  타일 {a.tile}px · 겹침 {a.overlap}px · 합침 IoU {a.nms}")
    if a.save_json:
        print(f"  저장 {a.save_json}")

    ents = load_gt(a.split)
    uids = sorted(ents)
    if a.check:
        uids = uids[:3]
    elif a.n:
        uids = uids[:a.n]
    print(f"  영상 {len(uids)}장")

    M = import_medsam3(a.repo)          # 여기서 cwd 가 바뀐다
    if a.dry:
        print("[1/2] 모델 없음 — --dry")
        print("      정답 로드 · 타일 · 배치 구성 · 질의 순서 · 좌표 되돌리기 ·")
        print("      NMS · FROC 까지만 확인한다. 순전파는 학습이 검증하고 있다.")
        dev, model = None, None
        rng = np.random.default_rng(0)
    else:
        dev = torch.device("cuda")
        model = build(a, M, dev)
        rng = None

    import pydicom
    stride = max(1, a.tile - a.overlap)
    dets = {n: [] for n in PROMPTS}
    raws = {n: [] for n in PROMPTS}          # --save-raw 일 때만 채운다
    gts = {n: defaultdict(list) for n in PROMPTS}
    name_of = {v: k for k, v in CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}
    n_tiles, done, t0 = 0, 0, time.time()

    print(f"\n[2/2] 추론")
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception as ex:
            print(f"\n  ! {uid}: {ex}")
            continue
        if arr.ndim != 2:
            continue
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = mask_box(mp)
            if b is not None and shp == arr.shape[:2]:
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
            gts[alias[name_of[cid]]][uid].append(
                (b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0))

        raw = {n: [] for n in PROMPTS}
        with torch.inference_mode(mode=not a.dry):
            for ty in positions(H, a.tile, stride):
                for tx in positions(W, a.tile, stride):
                    sub = img[ty:ty + a.tile, tx:tx + a.tile]
                    if sub.shape != (a.tile, a.tile):
                        p = np.zeros((a.tile, a.tile), np.uint8)
                        p[:sub.shape[0], :sub.shape[1]] = sub
                        sub = p
                    inp = make_batch(M, sub, dev)
                    if a.dry:
                        if n_tiles == 0:
                            names = [q.query_text for q in inp.find_queries] \
                                if hasattr(inp, "find_queries") else PROMPTS
                            print(f"      배치 통과 · 질의 순서 {names}")
                        got = fake_out(a.tile, rng)
                    else:
                        out = model(inp)
                        got = read_out(out, a.thr,
                                       verbose=(a.check and n_tiles == 0))
                    n_tiles += 1
                    for n, lst in got.items():
                        for b in lst:
                            # 타일 좌표를 뒤에 붙인다. nms() 와 저장은 [:4] 와
                            # [4] 만 쓰므로 길이가 늘어도 안전하다.
                            # 왜 남기나: 타일마다 점수를 독립적으로 매겨서
                            # 서로 비교가 안 되는 문제(종괴 mAP 회귀의 원인 중
                            # 하나)를 실험하려면 어느 타일에서 나왔는지가 있어야
                            # 한다. 없이 저장했다가 추론 83분을 다시 쓸 뻔했다.
                            raw[n].append((b[0] + tx, b[1] + ty,
                                           b[2] + tx, b[3] + ty, b[4], tx, ty))
        for n in PROMPTS:
            for b in nms(raw[n], a.nms):
                dets[n].append(dict(img=uid, box=b[:4], score=b[4]))
            if a.save_raw:
                # 합치기 전. 점수 상위만 남긴다 — 전부 남기면 파일이 감당이 안 된다.
                for b in sorted(raw[n], key=lambda x: -x[4])[:a.raw_topk]:
                    raws[n].append(dict(img=uid, box=b[:4], score=b[4],
                                        tile=[b[5], b[6]] if len(b) > 6 else None))
        done += 1
        if a.check and i == 1:
            print(f"      {uid}  유방 {W}x{H}  타일 "
                  f"{len(positions(H,a.tile,stride))}x{len(positions(W,a.tile,stride))}")
            for n in PROMPTS:
                print(f"      {n:14s} 합치기 전 {len(raw[n]):5d} -> "
                      f"후 {len(nms(raw[n], a.nms)):4d}   정답 {len(gts[n][uid])}")
        if i % 5 == 0 or i == len(uids):
            el = time.time() - t0
            print(f"\r  {i}/{len(uids)}  타일 {n_tiles:,}  "
                  f"{el/60:.1f}분 · 남은 {el/i*(len(uids)-i)/60:.0f}분   ",
                  end="", flush=True)
    print()

    if a.check and not a.dry:
        print("\n  구조 확인 완료. --check 를 빼고 돌려라.")
        return
    if a.dry:
        print("\n  --dry 는 가짜 검출을 썼다. 아래 지표는 값이 아니라 "
              "계산 경로가 도는지만 보여준다.")

    print(f"\n  영상 {done}장 · 타일 {n_tiles:,} (영상당 {n_tiles/max(1,done):.1f})")

    for name in PROMPTS:
        g = {u: v for u, v in gts[name].items() if v}
        n_gt = sum(len(v) for v in g.values())
        if not n_gt:
            continue
        print(f"\n{'='*74}\n{name}   정답 {n_gt}건 / 영상 {len(g)}장 "
              f"(전체 {done}장)\n{'='*74}")
        for label, fn in ((f"IoU>{a.iou:.1f}",
                           lambda p, q: 1.0 if iou(p, q) >= a.iou else 0.0),
                          ("중심 명중",
                           lambda p, q: 1.0 if center_in(p, q) else 0.0)):
            curve = froc(dets[name], n_gt, done, fn, g)
            print(f"\n  ── {label} ──")
            print("    영상당 오탐    민감도    임계값")
            for t in FP_POINTS:
                s, sc = at_fp(curve, t)
                print(f"      {t:4.2f}         {s:6.1%}    "
                      f"{f'{sc:.3f}' if sc is not None else '—'}")
            if curve:
                print(f"    (검출 {len(curve)}개 · 최대 "
                      f"{max(s for _, s, _ in curve):.1%})")

    # 저장은 지표를 찍은 뒤에 한다. 순서를 반대로 두었다가 저장이 실패해
    # 83분치 추론 결과를 한 줄도 못 남긴 적이 있다. 저장이 깨져도 지표는 남는다.
    if a.save_json:
        try:
            p = Path(a.save_json)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({n: dets[n] for n in dets}, default=float))
            print(f"\n  검출 저장 -> {p}")
        except Exception as e:
            print(f"\n  ! 검출 저장 실패: {type(e).__name__}: {e}")
            print("    지표는 위에 남아 있다. 저장만 다시 하면 된다.")

    if a.save_raw:
        try:
            p = Path(a.save_raw)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({n: raws[n] for n in raws}, default=float))
            tot = sum(len(v) for v in raws.values())
            print(f"  합치기 전 저장 -> {p}   박스 {tot:,}개 "
                  f"({p.stat().st_size/2**20:.0f}MB)")
        except Exception as e:
            print(f"\n  ! 합치기 전 저장 실패: {type(e).__name__}: {e}")

    print(f"\n{'='*74}")
    print("기준선")
    print("=" * 74)
    print("  1008 축소 전체 영상 · 전체 미세조정 838M · 에폭 20")
    print("    종괴 57.3%   석회 18.6%     오탐 1개/영상 · 중심 명중")
    print("    종괴 61.3%   석회 37.3%     오탐 4개/영상")
    print("  석회가 오르고 종괴가 유지되면 조치가 먹은 것이다.")


if __name__ == "__main__":
    main()
