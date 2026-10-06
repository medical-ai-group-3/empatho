#!/usr/bin/env python3
"""
헤드 전용 재학습을 위한 특징 캐싱.

분할 LoRA·픽셀 디코더를 동결한 채 train/valid 전 이미지의 쿼리 임베딩(256차원)을
한 번만 뽑아 저장한다. 이후 헤드 실험은 이 캐시만 읽으므로 GPU 없이 수 초에 끝난다.

추출 규칙 — score 최대 쿼리의 임베딩.
  train_us_lora.py 의 학습 루프는 헝가리안 매처가 고른 쿼리를 쓰지만,
  검증(val_dice_pass:695)과 추론(eval_us_lora)은 score argmax 쿼리를 쓴다.
  헤드가 실제로 서빙되는 조건은 후자이므로 여기서는 argmax 로 통일한다.
  기존의 train/serve 불일치를 없애는 쪽이다.

  python3 cache_features.py --config configs/us_lora.yaml
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image as PILImage
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_us_lora as T
import eval_us_lora as E


@torch.no_grad()
def cache_split(model, M, ds, device, split):
    feats, grades, maligs, names, scores = [], [], [], [], []
    skipped = 0

    for img_id in tqdm(ds.image_ids, desc=f"  {split}"):
        info = ds.images[img_id]
        anns = ds.img_to_anns.get(img_id, [])
        if not anns or "birads" not in anns[0]:
            skipped += 1
            continue

        pil = PILImage.open(ds.split_dir / info["file_name"]).convert("RGB")
        ow, oh = pil.size
        t = ds.transform(pil.resize((ds.resolution, ds.resolution), PILImage.BILINEAR))

        out = E.run_one_query(model, M, t, ds.resolution, oh, ow, device)
        q = out.get("queries")
        if q is None:
            skipped += 1
            continue
        sc = out["pred_logits"][0].sigmoid().amax(dim=-1)
        i = int(sc.argmax())

        feats.append(q[0, i].float().cpu())
        scores.append(float(sc[i]))
        grades.append(T.normalize_birads(anns[0]["birads"]))
        maligs.append(T.normalize_pathology(anns[0]))
        names.append(info["file_name"])

    if skipped:
        print(f"  ! {split}: 라벨/쿼리 없어 건너뜀 {skipped}장")

    return {
        "feat": torch.stack(feats),                                   # (N, 256)
        "grade": torch.tensor(grades, dtype=torch.long),              # 2~5
        "malig": torch.tensor(maligs, dtype=torch.float32),           # 0/1
        "score": torch.tensor(scores, dtype=torch.float32),
        "file_name": names,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/us_lora.yaml")
    ap.add_argument("--weights", default=None, help="기본: <ckpt_dir>/us_lora_best.pt")
    ap.add_argument("--pd", default=None, help="기본: <ckpt_dir>/us_pd_best.pt")
    ap.add_argument("--out", default=None, help="기본: <ckpt_dir>/features_best.pt")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = T.load_config(cfg_path)
    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    weights = Path(args.weights) if args.weights else ckpt_dir / "us_lora_best.pt"
    pd_path = Path(args.pd) if args.pd else ckpt_dir / "us_pd_best.pt"
    out_path = Path(args.out) if args.out else ckpt_dir / "features_best.pt"

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    print("=" * 70)
    print("특징 캐싱 — 분할 LoRA·픽셀 디코더 동결")
    print("=" * 70)

    # train 쪽 딕셔너리에는 load_lora_weights 가 없고(학습은 새로 주입한다),
    # eval 쪽에는 Object·SAM3Output 이 없다. 둘을 합쳐야 양쪽 함수를 다 쓸 수 있다.
    repo = cfg["model"]["medsam3_repo"]
    M = {**T.import_medsam3(repo), **E.import_medsam3(repo)}
    model = E.build_model(cfg, weights, M, device)
    E.load_pixel_decoder(model, pd_path, cfg, device)
    model.eval()
    for p in model.parameters():
        p.requires_grad = False

    root, R = cfg["data"]["root"], cfg["data"]["resolution"]
    print()
    train_ds = T.USCocoDataset(root, cfg["data"]["train_split"], R, M)
    val_ds = T.USCocoDataset(root, cfg["data"]["val_split"], R, M)

    print()
    payload = {
        "train": cache_split(model, M, train_ds, device, "train"),
        "valid": cache_split(model, M, val_ds, device, "valid"),
        "meta": {
            "lora": str(weights), "pd": str(pd_path), "config": str(cfg_path),
            "rule": "score argmax query embedding",
        },
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, out_path)

    print()
    print("=" * 70)
    for s in ("train", "valid"):
        d = payload[s]
        g = d["grade"]
        dist = "  ".join(f"{k}: {int((g == k).sum()):>4}" for k in (2, 3, 4, 5))
        print(f"  [{s}] {tuple(d['feat'].shape)}   등급분포  {dist}")
        print(f"        악성 {int(d['malig'].sum())} / {len(g)}"
              f"   score 중앙값 {float(d['score'].median()):.3f}")
    print(f"\n저장 {out_path}  ({out_path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()