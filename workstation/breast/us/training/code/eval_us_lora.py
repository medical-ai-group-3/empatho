#!/usr/bin/env python3
"""
초음파 LoRA 평가 — lesion 분할 Dice / IoU.

  python3 us/code/eval_us_lora.py --split valid
  python3 us/code/eval_us_lora.py --split valid --sweep
  python3 us/code/eval_us_lora.py --split valid --visualize 20
  python3 us/code/eval_us_lora.py --split test          # 외부검증, 최종 1회
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import yaml
from PIL import Image as PILImage, ImageDraw
from scipy import ndimage
from torchvision.transforms import v2

import pycocotools.mask as mask_utils

from model_io import (load_config, import_medsam3, move_to_device, _unwrap,  # noqa: E402
                      build_model, load_heads, load_pixel_decoder,
                      pred_union, run_one_query)
from heads import (
    BIRADS_MIN, NUM_GRADES, GradingHeads, coral_decode,
    normalize_birads, normalize_pathology,
)

US_ROOT = Path(__file__).resolve().parent.parent
from model_io import CLASS_NAME  # noqa: E402,F401
SWEEP_THRESHOLDS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def check_bundle(ckpt_dir, tag, need_pd):
    """LoRA · 헤드 · 픽셀 디코더가 같은 epoch 인지 확인한다.

    개별 저장이라 하나만 갱신되고 나머지가 이전 epoch 으로 남는 사고가 가능하다.
    학습은 셋이 모두 성공했을 때만 매니페스트를 쓰므로, 그 존재와 내용으로 판별한다.
    """
    man = Path(ckpt_dir) / f"us_{tag}_manifest.json"
    if not man.exists():
        print(f"  ! 매니페스트 없음 ({man.name}) — 세 파일의 짝을 확인할 수 없다.")
        print("    매니페스트 도입 이전 체크포인트이거나, 저장이 중간에 실패한 것이다.")
        return None
    meta = json.loads(man.read_text())
    files = meta.get("files", {})
    if need_pd and "pd" not in files:
        sys.exit(f"✗ {tag} 묶음에 픽셀 디코더가 없다 — 설정은 교체를 요구하는데 "
                 f"체크포인트는 원본 디코더로 학습된 것이다")
    print(f"체크포인트 묶음 — epoch {meta.get('epoch')} · run {meta.get('run')} "
          f"· {meta.get('saved_at')}")
    return meta


def decode_gt_union(anns, h, w):
    """정답은 원본 해상도 그대로 union. 리사이즈하지 않는다."""
    union = np.zeros((h, w), dtype=bool)
    for ann in anns:
        seg = ann.get("segmentation")
        if not seg:
            continue
        if isinstance(seg, dict):
            m = mask_utils.decode(seg)
        else:
            rles = mask_utils.frPyObjects(seg, h, w)
            m = mask_utils.decode(mask_utils.merge(rles))
        union |= m.astype(bool)
    return union


def dice_iou(pred, gt):
    p, g = pred.astype(bool), gt.astype(bool)
    inter = np.logical_and(p, g).sum()
    ps, gs = p.sum(), g.sum()
    union = ps + gs - inter
    dice = (2.0 * inter / (ps + gs)) if (ps + gs) > 0 else 1.0
    iou = (inter / union) if union > 0 else 1.0
    return float(dice), float(iou)


@torch.no_grad()
def overlay(pil, mask, color, alpha=0.45):
    base = np.asarray(pil.convert("RGB")).astype(np.float32)
    tint = np.zeros_like(base)
    tint[:] = color
    m = mask[..., None].astype(np.float32) * alpha
    return PILImage.fromarray((base * (1 - m) + tint * m).astype(np.uint8))


def save_triptych(pil, gt, pred, dice, iou, out_path):
    panels = [pil.convert("RGB"),
              overlay(pil, gt, (46, 204, 113)),
              overlay(pil, pred, (231, 76, 60))]
    w, h = pil.size
    canvas = PILImage.new("RGB", (w * 3 + 20, h + 24), (255, 255, 255))
    for i, p in enumerate(panels):
        canvas.paste(p, (i * (w + 10), 24))
    ImageDraw.Draw(canvas).text(
        (4, 6), f"{out_path.stem}  Dice {dice:.3f}  IoU {iou:.3f}"
                f"  |  원본 / 정답(초록) / 예측(빨강)", fill=(0, 0, 0))
    canvas.save(out_path)


def infer_one(model, M, split_dir, info, transform, R, device, threshold,
              mask_threshold, anns, heads=None):
    pil = PILImage.open(split_dir / info["file_name"]).convert("RGB")
    ow, oh = pil.size
    t = transform(pil.resize((R, R), PILImage.BILINEAR))
    out = run_one_query(model, M, t, R, oh, ow, device)
    scores = out["pred_logits"][0].sigmoid().amax(dim=-1)
    ml = out.get("pred_masks", None)
    ml = ml[0] if ml is not None else None

    # 등급: score 최대 쿼리 = Dice 를 재는 마스크를 만든 그 쿼리
    grade = malig = None
    pb = None                     # 경계 확률 3개 — 저장해 두면 임계값 재조정을
    if heads is not None:         # GPU 없이 CSV 계산만으로 무제한 반복할 수 있다
        q = out.get("queries")
        if q is not None:
            cl, mg = heads(q[0, int(scores.argmax())].float()[None])
            grade = int(coral_decode(cl)[0])
            malig = float(torch.sigmoid(mg)[0].detach())
            pb = torch.sigmoid(cl)[0].detach().tolist()
    keep = torch.where(scores > threshold)[0]
    pred = pred_union(ml, keep, oh, ow, mask_threshold)
    gt = decode_gt_union(anns, oh, ow)
    return pil, gt, pred, scores, ml, keep, ow, oh, grade, malig, pb


def evaluate(cfg, model, M, device, split_dir, threshold, mask_threshold,
             sweep=False, max_images=None, heads=None):
    with open(split_dir / "_annotations.coco.json") as f:
        coco = json.load(f)
    images = {im["id"]: im for im in coco["images"]}
    img_to_anns = defaultdict(list)
    for a in coco["annotations"]:
        img_to_anns[a["image_id"]].append(a)

    R = cfg["data"]["resolution"]
    transform = v2.Compose([
        v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
        v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
    ])

    image_ids = list(images)[:max_images] if max_images else list(images)
    rows = []
    sweep_acc = {t: [] for t in SWEEP_THRESHOLDS} if sweep else None
    gt_multi = 0

    for n, img_id in enumerate(image_ids):
        info = images[img_id]
        anns = img_to_anns.get(img_id, [])
        pil, gt, pred, scores, ml, keep, ow, oh, grade, malig, pb = infer_one(
            model, M, split_dir, info, transform, R, device,
            threshold, mask_threshold, anns, heads)

        if gt.any() and ndimage.label(gt)[1] >= 2:
            gt_multi += 1

        if n == 0:
            print("\n[진단] 첫 이미지")
            if ml is not None:
                mn, mx = ml.min().item(), ml.max().item()
                kind = "로짓" if (mn < 0.0 or mx > 1.0) else "확률(!)"
                print(f"  pred_masks {tuple(ml.shape)}  값 {mn:.3f}~{mx:.3f} → {kind}")
            print(f"  score {scores.min().item():.4f}~{scores.max().item():.4f}"
                  f"   원본 {ow}x{oh}\n")

        dice, iou = dice_iou(pred, gt)
        gt_area_px, pred_area_px = int(gt.sum()), int(pred.sum())
        row = dict(file_name=info["file_name"], dice=dice, iou=iou,
                   n_kept=int(keep.numel()), max_score=float(scores.max()),
                   # ① 면적 — >1 과대예측, <1 과소예측. worst 패턴을 이미지 없이 집계
                   gt_area_px=gt_area_px, pred_area_px=pred_area_px,
                   area_ratio=round(pred_area_px / max(gt_area_px, 1), 4),
                   # ② 원본 크기 — 1008² 정사각화가 종횡비를 얼마나 왜곡했는지
                   orig_w=ow, orig_h=oh, aspect_ratio=round(ow / oh, 4))
        if heads is not None and anns:
            row["gt_grade"] = normalize_birads(anns[0]["birads"]) if "birads" in anns[0] else -1
            row["pred_grade"] = grade if grade is not None else -1
            row["gt_malig"] = normalize_pathology(anns[0])
            row["pred_malig"] = round(malig, 4) if malig is not None else -1
            for j, name in enumerate(("p_gt2", "p_gt3", "p_gt4")):
                row[name] = round(pb[j], 6) if pb else -1
        rows.append(row)

        if sweep:
            for t in SWEEP_THRESHOLDS:
                p = pred_union(ml, torch.where(scores > t)[0], oh, ow, mask_threshold)
                sweep_acc[t].append(dice_iou(p, gt)[0])

        if (n + 1) % 50 == 0:
            print(f"  ... {n + 1}/{len(image_ids)}")

    return rows, sweep_acc, gt_multi


def report(split, label, rows, threshold, mask_threshold, gt_multi):
    d = np.array([r["dice"] for r in rows])
    i = np.array([r["iou"] for r in rows])
    empty = sum(1 for r in rows if r["pred_area_px"] == 0)
    zero = int((d == 0).sum())

    print(f"\n[{split}] {label} {len(rows)}장")
    print(f"  Dice   {d.mean():.3f}  (median {np.median(d):.3f}, std {d.std():.3f})")
    print(f"  IoU    {i.mean():.3f}  (median {np.median(i):.3f}, std {i.std():.3f})")
    print(f"  threshold {threshold}   mask-threshold {mask_threshold}")
    print()
    print(f"  마스크가 비어있는 예측     {empty}장")
    print(f"  연결 성분 2개 이상인 정답   {gt_multi}장")
    print()
    q = np.percentile(d, [10, 25, 50, 75, 90])
    print("  Dice 분위수  p10 {:.3f}  p25 {:.3f}  p50 {:.3f}  p75 {:.3f}  p90 {:.3f}"
          .format(*q))
    print(f"  Dice = 0     {zero}장 ({100 * zero / len(rows):.1f}%)")
    if empty:
        nz = d[[r["pred_area_px"] > 0 for r in rows]]
        print(f"  빈 예측 제외 Dice {nz.mean():.3f}  (n={len(nz)})")


def report_grades(split, rows):
    """등급 지표. 분할 지표(Dice·IoU)는 report() 가 따로 찍는다 —
    헤드 추가가 분할을 해쳤는지 두 블록을 나란히 보면 된다."""
    g = np.array([r["gt_grade"] for r in rows if r.get("gt_grade", -1) > 0])
    p_ = np.array([r["pred_grade"] for r in rows if r.get("gt_grade", -1) > 0])
    if not len(g):
        return

    print(f"\n  [등급 — BI-RADS {'·'.join(str(BIRADS_MIN + i) for i in range(NUM_GRADES))}]")
    print(f"  등급 정확도     {(g == p_).mean():.3f}")
    print(f"  ±1 이내 일치율  {(np.abs(g - p_) <= 1).mean():.3f}")
    print(f"  평균 절대오차   {np.abs(g - p_).mean():.3f}")

    print("\n  경계별 정확도")
    for k in range(BIRADS_MIN, BIRADS_MIN + NUM_GRADES - 1):
        gt_b, pr_b = (g > k), (p_ > k)
        n_pos = int(gt_b.sum())
        if n_pos in (0, len(gt_b)):
            print(f"    P(y>{k})   측정 불가 — 정답이 한쪽뿐 (양성 {n_pos}/{len(gt_b)})")
        else:
            print(f"    P(y>{k})   {(gt_b == pr_b).mean():.3f}   (양성 {n_pos}/{len(gt_b)})")

    grades = list(range(BIRADS_MIN, BIRADS_MIN + NUM_GRADES))
    print("\n  혼동 행렬 (행=정답, 열=예측)")
    print("        " + "".join(f"{c:>7d}" for c in grades) + "     계")
    for r_ in grades:
        row = [int(((g == r_) & (p_ == c)).sum()) for c in grades]
        print(f"    {r_:2d}  " + "".join(f"{v:>7d}" for v in row) + f"  {sum(row):>6d}")
    print("     계  " + "".join(f"{int((p_ == c).sum()):>7d}" for c in grades)
          + f"  {len(g):>6d}")

    gm = np.array([r["gt_malig"] for r in rows if "gt_malig" in r])
    pm = np.array([r["pred_malig"] for r in rows if "pred_malig" in r])
    if len(gm) and 0 < gm.sum() < len(gm):
        order = np.argsort(pm)
        ranks = np.empty(len(pm))
        ranks[order] = np.arange(1, len(pm) + 1)
        n1, n0 = gm.sum(), len(gm) - gm.sum()
        auc = (ranks[gm == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
        print(f"\n  악성 확률 AUC   {auc:.3f}  (참고값 — 화면 비노출)")
        print("    BUS-BRA 악성 32.4% vs 실제 검진 발견율 0.6%, 약 50배 차이라")
        print("    확률의 절대값은 신뢰할 수 없다. 순위 지표만 본다.")

    if split == "test":
        print("\n  ※ BrEaST(test)는 등급 분포가 train 과 크게 다르다")
        print("     train  2:30%  3:25%  4:37%  5:8%")
        print("     test   2:0%   3:6%   4:70%  5:23%")
        print("     분할 외부검증에는 쓸 수 있으나 등급 성능의 직접 비교는 어렵다.")
        print("     4a/4b/4c 는 4 로 접었고, BI-RADS 2 가 없어 P(y>2) 는 측정 불가다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(US_ROOT / "configs" / "us_lora.yaml"))
    ap.add_argument("--weights", default=str(US_ROOT / "ckpt" / "us_lora_best.pt"))
    ap.add_argument("--split", default="valid", choices=["valid", "test"])
    ap.add_argument("--pd", default=None,
                    help="픽셀 디코더 가중치 (기본: ckpt/us_pd_best.pt)")
    ap.add_argument("--heads", default=None,
                    help="등급 헤드 가중치 (기본: ckpt/us_heads_best.pt, 없으면 분할만)")
    ap.add_argument("--no-heads", action="store_true", help="등급 평가 생략")
    ap.add_argument("--no-lora", action="store_true",
                    help="US LoRA 가중치를 싣지 않고 병합본 단독으로 평가 (기준선)")
    ap.add_argument("--threshold", type=float, default=0.5, help="검출 score 컷오프")
    ap.add_argument("--mask-threshold", type=float, default=0.5,
                    help="sigmoid 후 마스크 확률 컷오프 (SAM3 공식값 0.5)")
    ap.add_argument("--sweep", action="store_true", help="threshold 비교. valid 전용")
    ap.add_argument("--visualize", type=int, default=0, metavar="N")
    ap.add_argument("--visualize-pick", default="worst",
                    choices=["worst", "best", "first", "random"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--dump-csv", default=None)
    ap.add_argument("--max-images", type=int, default=None)
    args = ap.parse_args()

    if args.sweep and args.split == "test":
        sys.exit("✗ --sweep 은 valid 전용. test 에 맞춰 threshold 를 고르면\n"
                 "  외부 검증의 의미가 사라진다.")

    # import_medsam3 가 os.chdir 하므로 먼저 절대경로로 확정
    cfg_path = Path(args.config).resolve()
    weights = Path(args.weights).resolve()
    cfg = load_config(cfg_path)
    root = Path(cfg["data"]["root"]).resolve()
    split_dir = (root / cfg["data"]["val_split"]) if args.split == "valid" else root / "test"
    out_cfg = cfg.get("output", {})
    heads_path = Path(args.heads).resolve() if args.heads else (
        US_ROOT / "ckpt" / out_cfg.get("best_heads_name", "us_heads_best.pt"))
    pd_path = Path(args.pd).resolve() if args.pd else (
        US_ROOT / "ckpt" / out_cfg.get("best_pd_name", "us_pd_best.pt"))
    tag = args.split + ("_nolora" if args.no_lora else "")
    out_dir = Path(args.out).resolve() if args.out else US_ROOT / "eval_out" / tag
    csv_path = Path(args.dump_csv).resolve() if args.dump_csv else None

    need = (cfg_path, split_dir) if args.no_lora else (cfg_path, weights, split_dir)
    for p in need:
        if not p.exists():
            sys.exit(f"✗ 없는 경로: {p}")

    label = "BUS-BRA" if args.split == "valid" else "BrEaST"
    variant = "병합본 단독 (LoRA 없음)" if args.no_lora else "US LoRA"
    print("=" * 70)
    print(f"초음파 평가 — {CLASS_NAME} 분할 · {variant}")
    print("=" * 70)
    print(f"설정   {cfg_path}")
    print(f"가중치 {'—' if args.no_lora else weights}")
    print(f"대상   {split_dir}  ({label})")
    if args.split == "test":
        print("\n  ※ 외부 검증용. 이 결과에 맞춰 threshold 를 다시 고르지 말 것.\n")

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    need_pd = cfg.get("pixel_decoder", {}).get("block_type", "original") != "original"
    if not args.no_lora:
        check_bundle(weights.parent, "last" if "last" in weights.name else "best", need_pd)

    model = build_model(cfg, weights, M, device, load_lora=not args.no_lora)
    if not args.no_lora:
        load_pixel_decoder(model, pd_path, cfg, device)
    heads = None if (args.no_heads or args.no_lora) else load_heads(heads_path, cfg, device)

    rows, sweep_acc, gt_multi = evaluate(
        cfg, model, M, device, split_dir,
        threshold=args.threshold, mask_threshold=args.mask_threshold,
        sweep=args.sweep, max_images=args.max_images, heads=heads)

    print("\n" + "=" * 70)
    report(args.split, f"{label} · {variant}", rows,
           args.threshold, args.mask_threshold, gt_multi)
    if heads is not None:
        report_grades(args.split, rows)

    if sweep_acc:
        print("\n  [threshold sweep — valid]")
        print("    thr     Dice   Dice=0")
        for t in SWEEP_THRESHOLDS:
            v = np.array(sweep_acc[t])
            print(f"    {t:.1f}   {v.mean():.3f}   {int((v == 0).sum()):4d}장")

    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"\n표본별 기록 {csv_path}")

    if args.visualize:
        order = {
            "worst": sorted(range(len(rows)), key=lambda k: rows[k]["dice"]),
            "best": sorted(range(len(rows)), key=lambda k: -rows[k]["dice"]),
            "first": list(range(len(rows))),
            "random": list(np.random.default_rng(42).permutation(len(rows))),
        }[args.visualize_pick]
        pick = order[:args.visualize]

        out_dir.mkdir(parents=True, exist_ok=True)
        with open(split_dir / "_annotations.coco.json") as f:
            coco = json.load(f)
        by_name = {im["file_name"]: im for im in coco["images"]}
        img_to_anns = defaultdict(list)
        for a in coco["annotations"]:
            img_to_anns[a["image_id"]].append(a)

        R = cfg["data"]["resolution"]
        transform = v2.Compose([
            v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ])
        for rank, k in enumerate(pick):
            r = rows[k]
            info = by_name[r["file_name"]]
            pil, gt, pred, *_ = infer_one(
                model, M, split_dir, info, transform, R, device,
                args.threshold, args.mask_threshold, img_to_anns.get(info["id"], []))
            save_triptych(pil, gt, pred, r["dice"], r["iou"],
                          out_dir / f"{rank:02d}_{Path(r['file_name']).stem}.png")
        print(f"\n비교 이미지 {len(pick)}장 ({args.visualize_pick}) {out_dir}")

    print("=" * 70)


if __name__ == "__main__":
    main()