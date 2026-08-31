"""
소켓2(CellViT++ TIL 이진분류) 학습용 셀 토큰 캐시를 오프라인 추출.

배경: experiment_cell_classifier.py 의 DetectionDataset 경로가 input_shape=[512,512]로
CenterCrop 하면서 큰 이미지(>512px)의 셀 ~83%를 버림. trainer 의 get_cellvit_result
(토큰 추출용 2차 검출)도 같은 512 crop 을 받으므로, detect_all_cells_binary 를 고쳐도
큰 이미지 TIL 이 토큰을 못 받음.

해결: sliding-window(타일링)로 토큰을 오프라인 추출해서 trainer 의 디스크 캐시
({dataset_path}/cache/{hash}.h5) 를 직접 만든다. hash 는 config 문자열 기반이라
(trainer_cell_classifier._calculate_hashes) 미리 계산 가능. 학습은 기존 config 그대로
돌리면 캐시를 발견하고 CellViT 추론을 건너뛴다.

  - 최장변 <= 512px: trainer 와 동일한 변환(중앙 pad -> CenterCrop 512) + 단일 추론
    -> 토큰이 기존과 동일 (작은 이미지 회귀 없음)
  - 최장변 >  512px: 원본 해상도 512x512 타일링(overlap 64) -> 타일별 검출/토큰 ->
    좌표 합침 -> 타일 경계 중복 제거 -> 라벨 CSV와 15px 페어링

사용:
  python extract_socket2_tokens.py --filelist .../splits/fold_0/train.csv --out .../cache/<train_hash>.h5
  python extract_socket2_tokens.py --filelist .../splits/fold_0/val.csv   --out .../cache/<val_hash>.h5
"""
import argparse
import csv
import hashlib
import math
import os
import sys
from pathlib import Path

import albumentations as A
import cv2
import h5py
import numpy as np
import torch
import torch.nn.functional as F
from albumentations.pytorch import ToTensorV2
from einops import rearrange
from PIL import Image

REPO_ROOT = os.path.expanduser("~/models/cellvitpp")
sys.path.insert(0, REPO_ROOT)

from cellvit.models.cell_segmentation.cellvit_sam import CellViTSAM
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy
from cellvit.utils.tools import unflatten_dict
from cellvit.training.utils.tools import pair_coordinates

INPUT_SHAPE = 512
TILE = 512
OVERLAP = 64
PAIR_DIST = 15.0
DEDUP_RADIUS = 10.0
PATCH_SIZE = 16
NR_TYPES = 6  # trainer 는 6-class PanNuke postproc 를 씀 (nr_types=6)

MEAN = (0.5, 0.5, 0.5)
STD = (0.5, 0.5, 0.5)


def dataset_hashes(dataset_path, cellvit_path, train_filelist, val_filelist, normalize_stains_train=False):
    """trainer_cell_classifier._calculate_hashes 와 동일한 규칙."""
    def h(s):
        return hashlib.sha256(s.encode("utf-8")).hexdigest()
    train = h(f"{dataset_path}_{train_filelist}_{cellvit_path}_stain_{normalize_stains_train}_train")
    val = h(f"{dataset_path}_{val_filelist}_{cellvit_path}_stain_{normalize_stains_train}_val")
    return train, val


def load_model(model_path, gpu):
    device = f"cuda:{gpu}"
    ckpt = torch.load(model_path, map_location="cpu", weights_only=False)
    run_conf = unflatten_dict(ckpt["config"], ".")
    model = CellViTSAM(
        model_path=None,
        num_nuclei_classes=run_conf["data"]["num_nuclei_classes"],
        num_tissue_classes=run_conf["data"]["num_tissue_classes"],
        vit_structure=run_conf["model"]["backbone"],
    )
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval().to(device)
    return model, device


# trainer 와 동일한 <=512 검증 변환 (get_transforms, detectiondataset + list input_shape)
SMALL_TF = A.Compose(
    [
        A.PadIfNeeded(INPUT_SHAPE, INPUT_SHAPE, border_mode=cv2.BORDER_CONSTANT, value=(255, 255, 255)),
        A.CenterCrop(INPUT_SHAPE, INPUT_SHAPE, always_apply=True),
        A.Normalize(mean=MEAN, std=STD),
        ToTensorV2(),
    ],
    keypoint_params=A.KeypointParams(format="xy", remove_invisible=True, label_fields=["kp_types"]),
)

TILE_TF = A.Compose(
    [
        A.PadIfNeeded(
            TILE, TILE, position="top_left", border_mode=cv2.BORDER_CONSTANT, value=(255, 255, 255)
        ),
        A.Normalize(mean=MEAN, std=STD),
        ToTensorV2(),
    ]
)


def apply_softmax_reorder(pred):
    pred["nuclei_binary_map"] = F.softmax(pred["nuclei_binary_map"], dim=1).permute(0, 2, 3, 1)
    pred["nuclei_type_map"] = F.softmax(pred["nuclei_type_map"], dim=1).permute(0, 2, 3, 1)
    pred["hv_map"] = pred["hv_map"].permute(0, 2, 3, 1)
    return pred


def tokens_for_cells(cell_dict, tokens_chw):
    """trainer.extract_tokens 와 동일 (patch_size 16 -> rescaling_factor 1)."""
    out = []
    for cell in cell_dict.values():
        bb = np.array(cell["bbox"], dtype=np.float64) / PATCH_SIZE
        bb[0, :] = np.floor(bb[0, :])
        bb[1, :] = np.ceil(bb[1, :])
        bb = bb.astype(np.int64)
        gh, gw = tokens_chw.shape[1], tokens_chw.shape[2]
        r0, r1 = max(0, bb[0, 0]), min(gh, max(bb[1, 0], bb[0, 0] + 1))
        c0, c1 = max(0, bb[0, 1]), min(gw, max(bb[1, 1], bb[0, 1] + 1))
        ct = tokens_chw[:, r0:r1, c0:c1]
        out.append(torch.mean(rearrange(ct, "D H W -> (H W) D"), dim=0).float().cpu().numpy())
    return out


@torch.inference_mode()
def infer(model, postproc, batch, device):
    with torch.autocast(device_type="cuda", dtype=torch.float16):
        pred = model.forward(batch.to(device), retrieve_tokens=True)
    pred = apply_softmax_reorder(pred)
    _, cell_dicts = postproc.post_process_batch(pred)
    toks = pred["tokens"]  # (B, D, H/16, W/16)
    return cell_dicts, toks


def process_small(img_np, gt_xy, gt_types, model, postproc, device):
    kp = [(float(x), float(y)) for x, y in gt_xy]
    t = SMALL_TF(image=img_np, keypoints=kp, kp_types=list(gt_types))
    img_t = t["image"].unsqueeze(0)
    true_c = np.array(t["keypoints"], dtype=np.float64)
    true_types = list(t["kp_types"])

    cell_dicts, toks = infer(model, postproc, img_t, device)
    cd = cell_dicts[0]
    pred_c = np.array([v["centroid"] for v in cd.values()], dtype=np.float64)
    cell_tokens = tokens_for_cells(cd, toks[0])
    return _pair(true_c, true_types, pred_c, cell_tokens)


def _tile_starts(length, tile, overlap):
    if length <= tile:
        return [0]
    step = tile - overlap
    s = list(range(0, length - tile + 1, step))
    if s[-1] != length - tile:
        s.append(length - tile)
    return s


def process_large(img_np, gt_xy, gt_types, model, postproc, device, batch_size):
    H, W = img_np.shape[:2]
    xs = _tile_starts(W, TILE, OVERLAP)
    ys = _tile_starts(H, TILE, OVERLAP)

    tensors, metas = [], []
    for y0 in ys:
        for x0 in xs:
            crop = img_np[y0 : y0 + TILE, x0 : x0 + TILE]
            ch, cw = crop.shape[:2]
            tensors.append(TILE_TF(image=crop)["image"])
            metas.append((x0, y0, cw, ch))

    raw = []  # (gx, gy, edge_margin, token)
    for i in range(0, len(tensors), batch_size):
        chunk = tensors[i : i + batch_size]
        try:
            batch = torch.stack(chunk)
            cell_dicts, toks = infer(model, postproc, batch, device)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            cell_dicts, toks = [], None
            for tt in chunk:
                cd, tk = infer(model, postproc, tt.unsqueeze(0), device)
                cell_dicts += cd
                toks = tk if toks is None else torch.cat([toks, tk], 0)
        for j, cd in enumerate(cell_dicts):
            x0, y0, cw, ch = metas[i + j]
            l_int, t_int = x0 > 0, y0 > 0
            r_int, b_int = x0 + TILE < W, y0 + TILE < H
            ctoks = tokens_for_cells(cd, toks[j])
            for (cell, tok) in zip(cd.values(), ctoks):
                cx, cy = cell["centroid"]
                if cx > cw or cy > ch:
                    continue
                gx, gy = x0 + cx, y0 + cy
                if not (0 <= gx <= W and 0 <= gy <= H):
                    continue
                m = [1e9]
                if l_int: m.append(cx)
                if t_int: m.append(cy)
                if r_int: m.append(cw - cx)
                if b_int: m.append(ch - cy)
                raw.append((gx, gy, min(m), tok))

    raw.sort(key=lambda r: -r[2])
    kept_xy, kept_tok = [], []
    for gx, gy, _, tok in raw:
        if all(math.hypot(gx - kx, gy - ky) > DEDUP_RADIUS for kx, ky in kept_xy):
            kept_xy.append((gx, gy))
            kept_tok.append(tok)

    true_c = np.array([(float(x), float(y)) for x, y in gt_xy], dtype=np.float64)
    pred_c = np.array(kept_xy, dtype=np.float64)
    return _pair(true_c, list(gt_types), pred_c, kept_tok)


def _pair(true_c, true_types, pred_c, cell_tokens):
    cells = []
    if len(true_c) == 0 or len(pred_c) == 0:
        return cells
    paired, _, _ = pair_coordinates(true_c, pred_c, PAIR_DIST)
    for a, b in paired:
        cells.append(
            {"coords": pred_c[b], "type": int(true_types[a]), "token": cell_tokens[b]}
        )
    return cells


def find_file(dataset_path, stem, sub):
    for split in ("train", "test"):
        p = Path(dataset_path) / split / sub / (stem + (".png" if sub == "images" else ".csv"))
        if p.exists():
            return p
    return None


def write_cache(cells, out_path):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(out_path, "w") as f:
        n = len(cells)
        f.create_dataset("images", shape=(n,), dtype=h5py.string_dtype(), chunks=True, compression="gzip")
        f.create_dataset("coords", shape=(n, 2), dtype=h5py.special_dtype(vlen=np.float64), chunks=True, compression="gzip")
        f.create_dataset("types", shape=(n,), dtype="i", chunks=True, compression="gzip")
        f.create_dataset("tokens", shape=(n,), dtype=h5py.special_dtype(vlen=np.float64))
        for i, c in enumerate(cells):
            f["images"][i] = c["image"]
            f["coords"][i] = np.asarray(c["coords"], dtype=np.float64)
            f["types"][i] = c["type"]
            f["tokens"][i] = np.asarray(c["token"], dtype=np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset_path", default=os.path.expanduser("~/data/tiger/cellvit_detection"))
    ap.add_argument("--model_path", default=os.path.join(REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"))
    ap.add_argument("--filelist", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--batch_size", type=int, default=4)
    args = ap.parse_args()

    model, device = load_model(args.model_path, args.gpu)
    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=NR_TYPES)

    stems = [r[0] for r in csv.reader(open(args.filelist)) if r]
    print(f"{len(stems)} images from {args.filelist}")

    all_cells = []
    n_small = n_large = 0
    stats = {"til": 0, "nontil": 0, "big_til": 0}
    for i, stem in enumerate(stems):
        ip = find_file(args.dataset_path, stem, "images")
        lp = find_file(args.dataset_path, stem, "labels")
        if ip is None or lp is None:
            print(f"  [skip] {stem}")
            continue
        img_np = np.array(Image.open(ip).convert("RGB")).astype(np.uint8)
        H, W = img_np.shape[:2]
        rows = [r for r in csv.reader(open(lp)) if len(r) >= 3]
        gt_xy = [(float(r[0]), float(r[1])) for r in rows]
        gt_types = [int(r[2]) for r in rows]

        big = max(H, W) > INPUT_SHAPE
        if big:
            cells = process_large(img_np, gt_xy, gt_types, model, postproc, device, args.batch_size)
            n_large += 1
        else:
            cells = process_small(img_np, gt_xy, gt_types, model, postproc, device)
            n_small += 1

        for c in cells:
            c["image"] = stem
            if c["type"] == 1:
                stats["til"] += 1
                if big:
                    stats["big_til"] += 1
            else:
                stats["nontil"] += 1
        all_cells.extend(cells)

        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(stems)}  cells={len(all_cells)}  (small={n_small}, tiled={n_large})")

    write_cache(all_cells, args.out)
    print(f"\nSaved {len(all_cells)} cells -> {args.out}")
    print(f"  TIL(1)={stats['til']}  nonTIL(0)={stats['nontil']}  (TIL {stats['til']/max(len(all_cells),1)*100:.1f}%)")
    print(f"  큰 이미지에서 온 TIL: {stats['big_til']}")
    print(f"  단일추론 {n_small}장 / 타일링 {n_large}장")


if __name__ == "__main__":
    main()
