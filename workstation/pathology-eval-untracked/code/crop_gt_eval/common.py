"""crop_gt_eval 공용: 경로, val 281장 split 재현, socket2 학습셋 표시, GT 로딩.

기존 파일은 import 만 한다 (remap_tissue_masks / stil_inference_pipeline /
extract_socket2_tokens / test_single_image). 수정 금지.

⚠ ~/data/tiger/tiger 는 자기참조 심볼릭 링크 — 여기서는 tissue-cells/ 아래를
   glob(비재귀)로만 읽는다. 재귀 탐색/링크 따라가기 금지.
"""
from __future__ import annotations

import csv
import json
import os
import random
import sys
from pathlib import Path

import numpy as np
import torch  # cupy 보다 먼저 (serving.py 와 동일: libcudart.so.12 로드 순서)
from PIL import Image

HERE = Path(__file__).resolve().parent                  # .../code/crop_gt_eval
CODE_DIR = HERE.parent                                  # .../code
CELLVIT_REPO = os.environ.get("CELLVIT_REPO", os.path.expanduser("~/models/cellvitpp"))
for _p in (str(CODE_DIR), CELLVIT_REPO):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import remap_tissue_masks as rtm  # noqa: E402  (REMAP, SEED, VAL_RATIO — main() 은 호출 안 함)

RESULTS = HERE / "results"
TIGER = Path.home() / "data/tiger"
SRC = TIGER / "tissue-cells"                             # images/, masks/, tiger-coco.json
COCO_JSON = SRC / "tiger-coco.json"
# socket2(세포분류 헤드) 학습 split. v1(이미지 단위 셔플) fold_0/train.csv 가
# 조직분할 val 281장과 242장 겹침 → 다른 PC 에서 확인한 사실과 일치 (v2 는 240).
SOCKET2_TRAIN_CSV = TIGER / "cellvit_detection/splits/fold_0/train.csv"

TISSUE_CKPT = os.path.expanduser("~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth")
CELL_HEAD = os.path.expanduser("~/pathology-eval/candidates/socket2/model_best.pth")
CELLVIT_CKPT = os.path.join(CELLVIT_REPO, "checkpoints", "CellViT-SAM-H-x40-AMP.pth")

EXPECTED_N_VAL = 281
EXPECTED_N_OVERLAP = 242
MPP = 0.5                    # TIGER µm/px — 밀도 단위(/mm²) 환산용
MATCH_RADIUS = 15.0          # px
TIL_THR = 0.5
CLASS_NAMES = ("other", "tumor", "stroma")

_REMAP_LUT = np.zeros(256, dtype=np.uint8)
for _k, _v in rtm.REMAP.items():
    _REMAP_LUT[_k] = _v


def strip_png(name: str) -> str:
    # Path.stem 은 TCGA 이름 속 '.' (DX1.224EDA43...) 에서 잘리므로 쓰지 않는다.
    name = os.path.basename(name)
    return name[:-4] if name.endswith(".png") else name


def val_stems() -> list[str]:
    """remap_tissue_masks.main() 의 split 을 그대로 재현 (sorted -> Random(42).shuffle -> 15%).
    반환은 보기 좋게 정렬한 281개 stem."""
    stems = sorted(p.stem for p in (SRC / "images").glob("*.png"))  # 원본과 동일 식 (.stem)
    random.Random(rtm.SEED).shuffle(stems)
    n_val = int(len(stems) * rtm.VAL_RATIO)
    return sorted(stems[:n_val])


def socket2_train_stems() -> set[str]:
    with open(SOCKET2_TRAIN_CSV) as f:
        return {strip_png(r[0]) for r in csv.reader(f) if r}


def check_split() -> tuple[list[str], set[str]]:
    """281장 / 겹침 242장 재현 확인 후 (val_stems, socket2_train) 반환. 불일치면 중단."""
    val = val_stems()
    s2 = socket2_train_stems()
    n_ov = len(set(val) & s2)
    print(f"[split] tissue val = {len(val)} (기대 {EXPECTED_N_VAL}), "
          f"socket2 학습셋과 겹침 = {n_ov} (기대 {EXPECTED_N_OVERLAP}), 미사용 = {len(val) - n_ov}")
    if len(val) != EXPECTED_N_VAL or n_ov != EXPECTED_N_OVERLAP:
        sys.exit("[split] 재현 실패 — 중단")
    return val, s2


def crop_ids(val: list[str]) -> dict[str, str]:
    """stem 은 공백·대괄호·쉼표를 포함해서 결과 파일명엔 v000 형식 id 를 쓴다."""
    return {s: f"v{i:03d}" for i, s in enumerate(val)}


def load_image(stem: str) -> Image.Image:
    return Image.open(SRC / "images" / f"{stem}.png").convert("RGB")


def load_gt_mask(stem: str) -> np.ndarray:
    """7-class 원본 라벨맵 -> REMAP 3-class (0 기타/1 종양/2 간질), 원본 해상도."""
    raw = np.array(Image.open(SRC / "masks" / f"{stem}.png"))
    return _REMAP_LUT[raw]


def gt16(mask3: np.ndarray, grid: int = 16) -> np.ndarray:
    """학습/평가 때와 같은 16x16 GT: PIL NEAREST 리샘플 (train_virchow2_linear_head.TissueSegDataset)."""
    return np.array(Image.fromarray(mask3).resize((grid, grid), Image.NEAREST))


def load_gt_points() -> dict[str, np.ndarray]:
    """tiger-coco.json bbox 중심 -> {stem: (N,2) float [x,y]}. 점 없는 이미지는 (0,2)."""
    coco = json.loads(COCO_JSON.read_text())
    id2stem = {im["id"]: strip_png(im["file_name"]) for im in coco["images"]}
    pts: dict[str, list] = {s: [] for s in id2stem.values()}
    for a in coco["annotations"]:
        x, y, w, h = a["bbox"]
        pts[id2stem[a["image_id"]]].append((x + w / 2.0, y + h / 2.0))
    return {s: np.asarray(v, dtype=np.float64).reshape(-1, 2) for s, v in pts.items()}


def dice(pred: np.ndarray, gt: np.ndarray, cls: int) -> float:
    """크롭 단위 Dice. GT·예측 모두 해당 클래스가 없으면 정의 불가 -> NaN."""
    p, g = pred == cls, gt == cls
    denom = int(p.sum()) + int(g.sum())
    return float("nan") if denom == 0 else 2.0 * int((p & g).sum()) / denom


class PooledDice:
    """evaluate_socket1_dice.DiceAccumulator 와 같은 식: 전체 누적 (2I+eps)/(P+T+eps).
    (그 모듈은 학습 후보 6종을 import 해서 무거워 식만 동일하게 둔다.)"""

    def __init__(self, n: int = 3):
        self.i = np.zeros(n)
        self.p = np.zeros(n)
        self.t = np.zeros(n)

    def update(self, pred: np.ndarray, gt: np.ndarray):
        for c in range(len(self.i)):
            pc, tc = pred == c, gt == c
            self.i[c] += (pc & tc).sum()
            self.p[c] += pc.sum()
            self.t[c] += tc.sum()

    def dice(self, eps: float = 1e-6) -> np.ndarray:
        return (2 * self.i + eps) / (self.p + self.t + eps)


def gpu_guard(min_free_gb: float, fp16: bool, gpu: int = 0) -> None:
    """모델 로드 직전 여유 VRAM 확인. 부족하면 fp16 권고, fp16 인데도 부족하면 중단."""
    if not torch.cuda.is_available():
        sys.exit("CUDA GPU 없음")
    free, total = torch.cuda.mem_get_info(gpu)
    free_gb = free / 2**30
    print(f"[GPU] cuda:{gpu} 여유 {free_gb:.1f} / {total / 2**30:.1f} GiB, "
          f"필요 추정 {min_free_gb:.1f} GiB, fp16={fp16}")
    if free_gb < min_free_gb:
        if fp16:
            sys.exit("[GPU] --fp16 으로도 여유 메모리 부족 — 실행 중단 (팀 추론 서버 보호)")
        sys.exit("[GPU] 여유 메모리 부족 — --fp16 으로 다시 실행하세요")
