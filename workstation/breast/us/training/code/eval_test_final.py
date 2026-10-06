#!/usr/bin/env python3
"""
확정 설정으로 test(BrEaST 197장)를 **한 번만** 평가한다.

이 스크립트는 외부 검증 전용이다. 결과로 설정을 바꾸지 않는다 —
바꾸면 test 가 더 이상 독립 기준선이 아니게 된다.

확정 설정 (전부 valid 에서 결정, 2026-08-28)
    분할      us_lora_best.pt + us_pd_best.pt (동결)
    등급 헤드  캐시된 train 특징으로 재학습, pos_weight 지수 p=0.25, 악성 보조입력 없음
              seed 10개의 확률을 평균한다
    임계값     t2=0.50  t3=0.50  t4=0.45
    확신도     min|p-0.5|  경계 0.10 / 0.30
    구간 표기  pred == 5 는 항상 "4~5" 로 표기 (안 (나))
    마스크     argmax 쿼리 하나만 사용 (안 (B)) — 등급과 같은 쿼리를 가리키게 한다.
              valid 실측에서 합집합(안 C) 대비 Dice +0.0074 · p10 +0.0232 · 빈예측 1→0

BrEaST 특성
    BI-RADS 2 가 0장이라 P(y>2) 경계는 측정 불가하다.
    라벨이 4a/4b/4c 로 세분돼 있어 normalize_birads 가 4 로 합친다.
    악성 라벨 필드명이 'pathology' 가 아니라 'classification' 이다.

  python3 eval_test_final.py --config configs/us_lora.yaml
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image as PILImage
from torchvision.transforms import v2
from tqdm import tqdm

import pycocotools.mask as mu

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_us_lora import (load_config, import_medsam3, build_model,       # noqa: E402
                          load_pixel_decoder, run_one_query, pred_union,
                          decode_gt_union, dice_iou)
from heads import normalize_birads, normalize_pathology                   # noqa: E402
from train_heads_grid import Heads, fit                                   # noqa: E402
from shape_metrics import shape_metrics                                   # noqa: E402

T2, T3, T4 = 0.50, 0.50, 0.45
CONF_LO, CONF_HI = 0.10, 0.30
N_SEEDS = 10

# valid 확정 수치 — 비교용 (us/docs/experiments.md 10-4)
# 안 (B) 마스크 기준. 등급 지표는 마스크 출처와 무관하다(등급은 argmax 쿼리에서만 나온다).
VALID = {"dice": 0.9102, "iou": 0.8432, "p10": 0.8351, "empty": 0,
         "acc": 0.5321, "w1": 0.9412, "screen": 0.6979,
         "r": {2: 0.640, 3: 0.476, 4: 0.393, 5: 0.889}}


def auc(s, y):
    s, y = np.asarray(s, float), np.asarray(y)
    pos, neg = s[y == 1], s[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    r = np.argsort(np.argsort(np.concatenate([pos, neg]))) + 1
    return (r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)
    ck = Path(cfg["output"]["ckpt_dir"])
    out_csv = Path(args.out) if args.out else ck.parent / "eval_out" / "test_final.csv"

    print("=" * 78)
    print("test(BrEaST) 최종 평가 — 외부 검증, 1회 한정")
    print("=" * 78)
    print(f"  임계값   t2={T2} t3={T3} t4={T4}")
    print(f"  확신도   {CONF_LO} / {CONF_HI}")
    print(f"  구간     pred == 5 는 항상 '4~5'")
    print(f"  헤드     p=0.25 · aux=False · seed {N_SEEDS}개 확률 평균")

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    M = import_medsam3(cfg["model"]["medsam3_repo"])
    model = build_model(cfg, ck / "us_lora_best.pt", M, device)
    load_pixel_decoder(model, ck / "us_pd_best.pt", cfg, device)
    model.eval()
    for p_ in model.parameters():
        p_.requires_grad = False

    R = cfg["data"]["resolution"]
    sd = Path(cfg["data"]["root"]) / "test"
    d = json.load(open(sd / "_annotations.coco.json"))
    imgs = {i["id"]: i for i in d["images"]}
    anns = {a["image_id"]: a for a in d["annotations"]}
    tf = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True),
                     v2.Normalize(mean=[.5] * 3, std=[.5] * 3)])

    print(f"\n[1/3] 분할 + 특징 추출  ({len(imgs)}장)")
    rows, feats = [], []
    with torch.no_grad():
        for iid, im in tqdm(sorted(imgs.items()), desc="  test"):
            a = anns.get(iid)
            if a is None:
                continue
            pil = PILImage.open(sd / im["file_name"]).convert("RGB")
            ow, oh = pil.size
            out = run_one_query(model, M, tf(pil.resize((R, R), PILImage.BILINEAR)),
                                R, oh, ow, device)
            sc = out["pred_logits"][0].sigmoid().amax(-1)
            qi = int(sc.argmax())
            n_det = int((sc > 0.5).sum())
            # 안 (B) — 마스크도 argmax 쿼리 하나만. 합집합(안 C)이 아니다.
            pm = np.asarray(pred_union(out["pred_masks"][0],
                                       torch.tensor([qi], device=sc.device), oh, ow, 0.5))
            gt = decode_gt_union([a], oh, ow)
            dc, iu = dice_iou(pm, gt)
            sm = shape_metrics(pm)
            feats.append(out["queries"][0, qi].float().cpu())
            rows.append(dict(file_name=im["file_name"], dice=dc, iou=iu,
                             score=float(sc[qi]), area_px=int(pm.sum()),
                             n_detections=n_det,
                             gt_grade=normalize_birads(a["birads"]),
                             gt_birads_raw=str(a["birads"]),
                             gt_malig=normalize_pathology(a),
                             n_components=(sm or {}).get("n_components", 0),
                             hw_ratio=(sm or {}).get("height_width_ratio")))

    feats = torch.stack(feats)
    dice = np.array([r["dice"] for r in rows])
    iou = np.array([r["iou"] for r in rows])
    gt = np.array([r["gt_grade"] for r in rows])
    mal = np.array([r["gt_malig"] for r in rows])

    print(f"\n[2/3] 등급 헤드 재학습 ({N_SEEDS} seed) 후 확률 평균")
    cache = torch.load(ck / "features_best.pt", map_location="cpu", weights_only=False)
    probs = []
    for s in range(N_SEEDS):
        _, st = fit(cache["train"], cache["valid"], 0.25, False, s, device)
        h = Heads(feats.shape[1], aux=False)
        h.load_state_dict({k: v.cpu() for k, v in st.items()})
        h.eval()
        with torch.no_grad():
            probs.append(torch.sigmoid(h(feats)[0]).numpy())
    p = np.mean(probs, axis=0)

    pred = 2 + (p[:, 0] > T2) + (p[:, 1] > T3) + (p[:, 2] > T4)
    amb = np.abs(p - 0.5).min(axis=1)
    conf = np.where(amb >= CONF_HI, "높음", np.where(amb >= CONF_LO, "보통", "낮음"))
    band = pred == 5                                     # 안 (나)
    screen_ok = np.where(band, np.isin(gt, [4, 5]), gt == pred)

    for r, q, c, b, pp in zip(rows, pred, conf, band, p):
        r.update(pred_grade=int(q), conf=c, band_45=bool(b),
                 p_gt2=round(float(pp[0]), 6), p_gt3=round(float(pp[1]), 6),
                 p_gt4=round(float(pp[2]), 6))

    print("\n[3/3] 결과")
    print("=" * 78)
    print(f"■ 분할  (n={len(rows)})")
    print(f"    Dice {dice.mean():.4f}   IoU {iou.mean():.4f}   "
          f"p10 {np.percentile(dice, 10):.4f}   빈 예측 {int((dice == 0).sum())}장")
    print(f"    중앙값 Dice {np.median(dice):.4f} · p25 {np.percentile(dice, 25):.4f} "
          f"· p75 {np.percentile(dice, 75):.4f}")
    print(f"    valid 대비   Dice {dice.mean() - VALID['dice']:+.4f}   "
          f"IoU {iou.mean() - VALID['iou']:+.4f}   p10 {np.percentile(dice,10)-VALID['p10']:+.4f}")

    print(f"\n■ 등급 경계  (BI-RADS 2 가 0장이라 P(y>2) 는 측정 불가)")
    for k, nm in ((1, "P(y>3)"), (2, "P(y>4)")):
        y = (gt > k + 2).astype(int)
        t = (T3, T4)[k - 1]
        yh = (p[:, k] > t).astype(int)
        print(f"    {nm}   AUC {auc(p[:, k], y):.3f}   "
              f"정확도 {(yh == y).mean():.4f}   "
              f"민감도 {yh[y == 1].mean() if (y==1).any() else float('nan'):.3f}   "
              f"특이도 {1 - yh[y == 0].mean() if (y==0).any() else float('nan'):.3f}   "
              f"(양성 {int(y.sum())}/{len(y)})")

    print(f"\n■ 3×3 혼동행렬 (BI-RADS 3·4·5)")
    G = [3, 4, 5]
    print("          " + "".join(f"{q:>7}" for q in G) + f"{'계':>8}{'recall':>9}")
    for g in G:
        n = int((gt == g).sum())
        cells = "".join(f"{int(((gt == g) & (pred == q)).sum()):>7}" for q in G)
        oth = int(((gt == g) & (~np.isin(pred, G))).sum())
        rec = int(((gt == g) & (pred == g)).sum()) / max(n, 1)
        print(f"      {g}   {cells}{n:>8}{rec:>9.3f}" + (f"   (3·4·5 밖 {oth})" if oth else ""))
    inG = np.isin(gt, G)
    print(f"    3·4·5 내 정확도 {(gt[inG] == pred[inG]).mean():.4f}   "
          f"±1 {np.mean(np.abs(gt[inG] - pred[inG]) <= 1):.4f}")
    print(f"    전체 정확도 {(gt == pred).mean():.4f}   "
          f"±1 {np.mean(np.abs(gt - pred) <= 1):.4f}   "
          f"(valid: acc {VALID['acc']:.4f} · ±1 {VALID['w1']:.4f})")

    print(f"\n■ 화면 표기 기준 적중률   {screen_ok.mean():.4f}"
          f"   (valid {VALID['screen']:.4f}, 차이 {screen_ok.mean()-VALID['screen']:+.4f})")
    print(f"    '4~5' 구간 {int(band.sum())}장 ({band.mean():.1%})"
          f" · 그 중 실제 4·5 {np.isin(gt[band], [4, 5]).mean() if band.any() else float('nan'):.3f}")
    print(f"    확신도  " + " · ".join(
        f"{c} {int((conf == c).sum())}장({(conf == c).mean():.1%}, 적중 {screen_ok[conf == c].mean():.3f})"
        for c in ("높음", "보통", "낮음") if (conf == c).any()))

    print(f"\n■ 참고")
    print(f"    악성 판별 AUC (P(y>4))  {auc(p[:, 2], mal):.3f}")
    print(f"    마스크 연결성분 2개 이상  "
          f"{sum(1 for r in rows if r['n_components'] > 1)}장")
    raw = {}
    for r in rows:
        raw.setdefault(r["gt_birads_raw"], []).append(r["dice"])
    print(f"    원본 라벨별 Dice  " + " · ".join(
        f"{k}: {np.mean(v):.3f}(n={len(v)})" for k, v in sorted(raw.items())))

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    cols = list(rows[0].keys())
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"\n표본별 기록 {out_csv}")
    print("=" * 78)
    print("※ 이 결과로 설정을 바꾸지 않는다 — 바꾸면 독립 기준선이 사라진다.")


if __name__ == "__main__":
    main()