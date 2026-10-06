#!/usr/bin/env python3
"""
초음파(경로 B) 1차 시험 학습 — BUS-BRA lesion 분할.

동결된 MedSAM3 병합본 위에 새 LoRA 를 얹어 분할만 학습한다.
MedSAM3 저장소는 수정하지 않고 import 로만 사용한다.

모달리티별 디렉터리 구조 (breast/us/) 안에서 동작한다. 어느 위치에서 실행하든
--config 기본값과 로그 경로는 이 파일 위치를 기준으로 잡히므로 cd 가 필요 없다.

  breast/us/
    code/train_us_lora.py   ← 이 파일
    configs/us_lora.yaml    ← --config 기본값
    data/{train,valid,test}
    ckpt/                   ← us_lora_{best,last}.pt
    logs/                   ← us_lora_<타임스탬프>.log

  python3 us/code/train_us_lora.py

로그는 셸 리다이렉트 없이 us/logs/us_lora_<타임스탬프>.log 로 자동 저장된다.
진행 상황은 tail -f us/logs/us_lora_latest.log 로 볼 수 있다.
"""

import argparse
import atexit
import io
import json
import os
import random
import socket
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from PIL import Image as PILImage
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import v2
from tqdm import tqdm

import pycocotools.mask as mask_utils

# 이 컨테이너의 /dev/shm 은 64MB 뿐이다. 1008² 배치 하나가 24MB 이상이라
# DataLoader 워커를 쓰면 배치를 넘기지 못하고 죽는다(file_system 전략도
# 결국 /dev/shm 에 파일을 만들어 동일하게 실패한다).
# → configs 의 num_workers 는 0 이어야 한다. 아래에서 값을 검사한다.
SHM_LIMIT_NOTE = "/dev/shm 64MB 제약 — num_workers 는 0 이어야 한다"

# 1차 학습 실측 (BUS-BRA valid 374장, threshold 0.5). 헤드를 얹은 뒤
# 분할이 무너지지 않는지 매 epoch 이 값과 비교한다.
SEG_BASELINE = 0.898

# breast/us/ — code/ 의 상위. configs·data·ckpt·logs 가 모두 이 아래에 나란히 있다.
# CWD 가 아니라 이 파일 위치 기준이라 어디서 실행하든 경로가 흔들리지 않는다.
US_ROOT = Path(__file__).resolve().parent.parent

# valid Dice 계산은 eval_us_lora 의 함수를 그대로 쓴다. 여기서 다시 구현하면
# 학습 중 지표와 평가 스크립트 숫자가 갈린다.
# (import_medsam3 이 os.chdir 하기 전, 모듈 로드 시점에 끝나야 한다)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_us_lora import (                                          # noqa: E402
    decode_gt_union, dice_iou, pred_union, run_one_query,
)
from heads import (                                                 # noqa: E402
    GradingHeads, compute_pos_weights, coral_decode, coral_loss,
    normalize_birads, normalize_pathology,
)
import unet_pixel_decoder as UPD                                    # noqa: E402


# ── 실행별 로그 파일 ─────────────────────────────────────────────────────────
# 셸에서 `> train.log 2>&1` 로 넘기면 나중 실행이 앞 실행 로그를 통째로 덮어쓴다
# (실제로 이 스크립트 실행이 MRI 18시간치 로그를 지웠다). 스크립트가 스스로
# 타임스탬프 붙은 파일을 만들어 셸 명령에 의존하지 않게 한다.
#
# tqdm 진행바는 '\r' 로 같은 줄을 계속 덮어쓴다. 콘솔에는 그대로 흘리되
# 파일에는 각 줄의 마지막 상태만 남긴다 — 예전 train.log 는 154KB 중
# 대부분이 진행바 중간 프레임이라 epoch 요약을 찾기 어려웠다.

class _Tee(io.TextIOBase):
    def __init__(self, stream, fh, lock):
        self.stream = stream
        self.fh = fh
        self.lock = lock
        self._pending = ""

    def write(self, s):
        self.stream.write(s)
        self.stream.flush()
        with self.lock:
            self._pending += s
            while True:
                i = self._pending.find("\n")
                if i < 0:
                    break
                line, self._pending = self._pending[:i], self._pending[i + 1:]
                self.fh.write(line.rsplit("\r", 1)[-1] + "\n")   # 마지막 갱신만
            # 개행 없이 '\r' 로만 갱신되는 진행바(leave=False)가 버퍼를
            # 무한정 키우지 않도록 미완성 줄도 마지막 조각만 들고 있는다
            if "\r" in self._pending:
                self._pending = self._pending.rsplit("\r", 1)[-1]
            self.fh.flush()
        return len(s)

    def flush(self):
        self.stream.flush()
        with self.lock:
            self.fh.flush()

    def drain(self):
        """개행 없이 끝난 마지막 줄을 흘려보낸다."""
        with self.lock:
            if self._pending.strip():
                self.fh.write(self._pending.rsplit("\r", 1)[-1] + "\n")
            self._pending = ""
            self.fh.flush()

    # tqdm 등이 원본 스트림의 성질을 물어본다
    def isatty(self):
        return self.stream.isatty()

    def fileno(self):
        return self.stream.fileno()

    def writable(self):
        return True

    @property
    def encoding(self):
        return getattr(self.stream, "encoding", "utf-8")


def start_run_log(tag, log_dir=None, extra=None):
    """stdout/stderr 를 실행별 로그 파일로 복제하고 그 경로를 돌려준다.

    logs/<tag>_latest.log 심링크도 갱신하므로
    `tail -f us/logs/us_lora_latest.log` 로 붙을 수 있다.

    기본 위치는 code/ 옆이 아니라 그 상위인 breast/us/logs/ 다.
    """
    log_dir = Path(log_dir) if log_dir else US_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now()
    path = log_dir / f"{tag}_{started:%Y%m%d_%H%M%S}.log"
    n = 1
    while path.exists():                      # 같은 초에 두 번 떠도 덮어쓰지 않는다
        n += 1
        path = log_dir / f"{tag}_{started:%Y%m%d_%H%M%S}_{n}.log"

    fh = open(path, "w", encoding="utf-8")
    lock = threading.Lock()

    fh.write("=" * 70 + "\n")
    fh.write(f"run      {tag}\n")
    fh.write(f"started  {started:%Y-%m-%d %H:%M:%S}\n")
    fh.write(f"host     {socket.gethostname()}  pid {os.getpid()}\n")
    fh.write(f"cwd      {Path.cwd()}\n")
    fh.write(f"cmd      {' '.join(sys.argv)}\n")
    for k, v in (extra or {}).items():
        fh.write(f"{k:8s} {v}\n")
    fh.write("=" * 70 + "\n")
    fh.flush()

    out_tee, err_tee = _Tee(sys.stdout, fh, lock), _Tee(sys.stderr, fh, lock)
    sys.stdout, sys.stderr = out_tee, err_tee

    latest = log_dir / f"{tag}_latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(path.name)
    except OSError:
        pass                                  # 심링크 안 되는 FS 면 그냥 넘어간다

    def _finish():
        out_tee.drain()
        err_tee.drain()
        ended = datetime.now()
        with lock:
            fh.write("=" * 70 + "\n")
            fh.write(f"ended    {ended:%Y-%m-%d %H:%M:%S}  (소요 {ended - started})\n")
            fh.flush()
            fh.close()
        sys.stdout, sys.stderr = out_tee.stream, err_tee.stream

    atexit.register(_finish)
    return path


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# ── MedSAM3 저장소 import ────────────────────────────────────────────────────
def import_medsam3(repo_root: str):
    """
    저장소 코드는 상대경로(sam3/assets/...)를 하드코딩하므로 cwd 를 옮긴다.
    설정의 경로는 전부 절대경로라 영향이 없다.
    """
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)

    from merge_medsam3 import load_merged_model
    from lora_layers import LoRAConfig, apply_lora_to_model, count_parameters, save_lora_weights
    from sam3.model.model_misc import SAM3Output
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata, Object,
    )
    from sam3.train.loss.loss_fns import CORE_LOSS_KEY, Boxes, IABCEMdetr, Masks
    from sam3.train.loss.sam3_loss import Sam3LossWrapper
    from sam3.train.matcher import BinaryHungarianMatcherV2, BinaryOneToManyMatcher

    # merge_medsam3 가 import 시점에 TF32 를 끈다(병합 검산용). 학습에서는 되돌린다.
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    return dict(
        load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
        apply_lora_to_model=apply_lora_to_model, count_parameters=count_parameters,
        save_lora_weights=save_lora_weights, SAM3Output=SAM3Output,
        collate_fn_api=collate_fn_api, Datapoint=Datapoint, FindQueryLoaded=FindQueryLoaded,
        Image=Image, InferenceMetadata=InferenceMetadata, Object=Object,
        CORE_LOSS_KEY=CORE_LOSS_KEY, Boxes=Boxes, IABCEMdetr=IABCEMdetr, Masks=Masks,
        Sam3LossWrapper=Sam3LossWrapper,
        BinaryHungarianMatcherV2=BinaryHungarianMatcherV2,
        BinaryOneToManyMatcher=BinaryOneToManyMatcher,
    )


# ── 데이터셋 ────────────────────────────────────────────────────────────────
class USCocoDataset(Dataset):
    """<root>/<split>/_annotations.coco.json + 같은 폴더의 이미지."""

    def __init__(self, root, split, resolution, M, seed_aug=42):
        self.M = M
        self.split_dir = Path(root) / split
        self.resolution = resolution

        ann_file = self.split_dir / "_annotations.coco.json"
        if not ann_file.exists():
            raise FileNotFoundError(ann_file)
        with open(ann_file) as f:
            coco = json.load(f)

        self.images = {im["id"]: im for im in coco["images"]}
        self.image_ids = sorted(self.images)
        self.categories = {c["id"]: c["name"] for c in coco["categories"]}

        self.all_anns = coco["annotations"]          # pos_weight 산출용
        self.img_to_anns = defaultdict(list)
        for a in coco["annotations"]:
            self.img_to_anns[a["image_id"]].append(a)

        self.to_t = v2.Compose([v2.ToImage(), v2.ToDtype(torch.float32, scale=True)])
        self.norm = v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5])
        self.transform = v2.Compose([self.to_t, self.norm])   # 평가 경로가 쓴다

        # 증강은 학습 split 에서만. 원본 사진을 미리 늘려 저장하는 방식이 아니라
        # 배치마다 즉석 변환이라 train/valid 로 같은 사진의 변형이 새어갈 수 없다.
        # (환자 단위 분할도 실측 확인 — train 850명 / valid 212명, 겹침 0명)
        self.augment = False
        self.aug_rng = random.Random(seed_aug)

        print(f"  [{split}] 이미지 {len(self.image_ids)} · 어노테이션 "
              f"{len(coco['annotations'])} · 카테고리 {list(self.categories.values())}")

    def __len__(self):
        return len(self.image_ids)

    # ── 증강 ────────────────────────────────────────────────────────────
    # 초음파는 좌우 반전만 한다. 상하 반전은 물리를 깨뜨린다 — 후방음영은
    # 언제나 병변 '아래'에 생기므로 뒤집으면 없는 현상이 된다.
    # 회전도 같은 이유로 ±10° 로 제한한다.
    # 기하 변환은 이미지와 마스크에 동일하게 적용하고, bbox 는 변환된
    # 마스크에서 다시 계산한다 — 따로 변환하면 셋이 어긋난다.

    def _sample_aug(self):
        r = self.aug_rng
        return {
            "hflip": r.random() < 0.5,
            "affine": (dict(angle=r.uniform(-10, 10), scale=r.uniform(0.9, 1.1),
                            translate=[int(r.uniform(-0.05, 0.05) * self.resolution),
                                       int(r.uniform(-0.05, 0.05) * self.resolution)],
                            shear=[0.0, 0.0]) if r.random() < 0.7 else None),
            "photo": ((r.uniform(-0.08, 0.08), r.uniform(0.85, 1.15))
                      if r.random() < 0.5 else None),
        }

    def _apply_geom(self, t, params, mask):
        import torchvision.transforms.v2.functional as TF
        if params["hflip"]:
            t = TF.hflip(t)
        if params["affine"]:
            interp = (TF.InterpolationMode.NEAREST if mask
                      else TF.InterpolationMode.BILINEAR)
            t = TF.affine(t, interpolation=interp, **params["affine"])
        return t

    @staticmethod
    def _box_from_mask(seg, R):
        ys, xs = torch.where(seg)
        x0, x1 = int(xs.min()), int(xs.max()) + 1
        y0, y1 = int(ys.min()), int(ys.max()) + 1
        return torch.tensor([(x0 + x1) / 2 / R, (y0 + y1) / 2 / R,
                             (x1 - x0) / R, (y1 - y0) / R], dtype=torch.float32)

    def __getitem__(self, idx):
        M = self.M
        R = self.resolution
        img_id = self.image_ids[idx]
        info = self.images[img_id]

        pil = PILImage.open(self.split_dir / info["file_name"]).convert("RGB")
        orig_w, orig_h = pil.size
        pil = pil.resize((R, R), PILImage.BILINEAR)
        image_tensor = self.to_t(pil)
        aug_params = self._sample_aug() if self.augment else None
        if aug_params and aug_params["photo"]:
            b, c = aug_params["photo"]
            image_tensor = (image_tensor * c + b).clamp(0, 1)
        if aug_params:
            image_tensor = self._apply_geom(image_tensor, aug_params, mask=False)
        image_tensor = self.norm(image_tensor)

        objects, class_names = [], []
        for i, ann in enumerate(self.img_to_anns.get(img_id, [])):
            bbox = ann.get("bbox")
            if bbox is None:
                continue
            class_names.append(self.categories.get(ann.get("category_id", 0), "object"))

            x, y, w, h = bbox
            box = torch.tensor(
                [(x + w / 2) / orig_w, (y + h / 2) / orig_h, w / orig_w, h / orig_h],
                dtype=torch.float32,
            )

            segment = None
            seg = ann.get("segmentation")
            if seg:
                try:
                    if isinstance(seg, dict):
                        m = mask_utils.decode(seg)
                    else:
                        rles = mask_utils.frPyObjects(seg, orig_h, orig_w)
                        m = mask_utils.decode(mask_utils.merge(rles))
                    m = torch.from_numpy(m).float()[None, None]
                    m = torch.nn.functional.interpolate(m, size=(R, R), mode="nearest")
                    segment = m.squeeze() > 0.5
                    if aug_params:
                        segment = self._apply_geom(
                            segment[None].float(), aug_params, mask=True)[0] > 0.5
                        if segment.any():
                            box = self._box_from_mask(segment, R)
                        else:
                            aug_params = None      # 병변이 잘려나가면 증강을 버린다
                except Exception as e:
                    print(f"  ! mask 처리 실패 img={img_id} ann={i}: {e}")

            objects.append(M["Object"](
                bbox=box, area=(box[2] * box[3]).item(), object_id=i, segment=segment
            ))

        image_obj = M["Image"](data=image_tensor, objects=objects, size=(R, R))

        by_class = defaultdict(list)
        for obj, name in zip(objects, class_names):
            by_class[name.lower()].append(obj.object_id)
        if not by_class:
            by_class["object"] = []

        meta = M["InferenceMetadata"](
            coco_image_id=img_id, original_image_id=img_id, original_category_id=0,
            original_size=(orig_h, orig_w), object_id=-1, frame_index=-1,
        )
        queries = [
            M["FindQueryLoaded"](
                query_text=text, image_id=0, object_ids_output=ids,
                is_exhaustive=True, query_processing_order=0, inference_metadata=meta,
            )
            for text, ids in by_class.items()
        ]

        # raw_images(PIL 원본)는 비디오 추론 경로에서만 쓰인다. 학습에는 불필요하고
        # 워커→메인 전송량만 키우므로 싣지 않는다.
        dp = M["Datapoint"](find_queries=queries, images=[image_obj])

        # 등급 헤드 정답. 이미지당 어노 1개가 실측된 전제(1495/1495)라 첫 어노에서
        # 읽는다. 없으면 -1 로 두고 손실 계산에서 제외한다.
        anns = self.img_to_anns.get(img_id, [])
        grade = normalize_birads(anns[0]["birads"]) if anns and "birads" in anns[0] else -1
        malig = normalize_pathology(anns[0]) if anns else -1
        return dp, {"grade": grade, "malig": malig}


def move_to_device(obj, device):
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, list):
        return [move_to_device(x, device) for x in obj]
    if isinstance(obj, tuple):
        return tuple(move_to_device(x, device) for x in obj)
    if isinstance(obj, dict):
        return {k: move_to_device(v, device) for k, v in obj.items()}
    if hasattr(obj, "__dataclass_fields__"):
        for f in obj.__dataclass_fields__:
            setattr(obj, f, move_to_device(getattr(obj, f), device))
        return obj
    return obj


# ── 모델 ────────────────────────────────────────────────────────────────────
def build_model(cfg, M, device):
    ckpt = Path(cfg["model"]["checkpoint"]).resolve()
    merge_cfg = Path(cfg["model"]["merge_lora_config"]).resolve()
    if not ckpt.exists():
        sys.exit(f"✗ 병합본이 없다: {ckpt}")

    print("\n[1/3] 병합본 로드")
    print(f"      파일   {ckpt}")
    print(f"      크기   {ckpt.stat().st_size / 1e9:.2f} GB")
    print(f"      구조   {merge_cfg}")
    print("      경로   load_merged_model(load_from_hf=False) — HuggingFace 다운로드 없음")

    model = M["load_merged_model"](str(ckpt), str(merge_cfg), device=device)

    # load_merged_model 내부(build_with_lora)가 eval_mode=True로 모델을 만들기 때문에
    # sam3_image.py의 self.matcher 가 None 으로 남는다(model_builder.py: "if not eval_mode"
    # 조건에서만 matcher 생성). merge_medsam3.py는 건드리지 않고 여기서 직접 꽂아준다.
    # forward() 내부의 _compute_matching 이 이 matcher(외부 loss용 matcher와는 별개 인스턴스)를 쓴다.
    if getattr(model, "matcher", None) is None:
        from sam3.train.matcher import BinaryHungarianMatcherV2
        model.matcher = BinaryHungarianMatcherV2(
            focal=True, cost_class=2.0, cost_bbox=5.0, cost_giou=2.0,
            alpha=0.25, gamma=2, stable=False,
        )
        print("      ! model.matcher 가 None 이라 직접 주입함 (eval_mode=True로 병합된 탓)")

    meta = torch.load(str(ckpt), map_location="cpu", mmap=True).get("meta", {})
    if meta:
        print(f"      메타   base={meta.get('base')} lora={meta.get('lora')} "
              f"merged_layers={meta.get('merged_layers')}")

    print("\n[2/3] 학습용 LoRA 주입 (rank={} alpha={})".format(
        cfg["lora"]["rank"], cfg["lora"]["alpha"]))
    print("      MHA 교체 0건이 정상 — 병합본은 이미 MultiheadAttentionLoRA 구조다")

    lc = cfg["lora"]
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=lc["rank"], alpha=lc["alpha"], dropout=lc["dropout"],
        target_modules=lc["target_modules"],
        apply_to_vision_encoder=lc["apply_to_vision_encoder"],
        apply_to_text_encoder=lc["apply_to_text_encoder"],
        apply_to_geometry_encoder=lc["apply_to_geometry_encoder"],
        apply_to_detr_encoder=lc["apply_to_detr_encoder"],
        apply_to_detr_decoder=lc["apply_to_detr_decoder"],
        apply_to_mask_decoder=lc["apply_to_mask_decoder"],
    ))
    return model.to(device)


def check_trainable(model, M, cfg):
    c = M["count_parameters"](model)
    total, train, pct = c["total_parameters"], c["trainable_parameters"], c["trainable_percentage"]
    lo = cfg["training"]["trainable_pct_min"]
    hi = cfg["training"]["trainable_pct_max"]

    print("\n[3/3] 학습 가능 파라미터")
    print(f"      전체       {total:,}")
    print(f"      학습 대상  {train:,}")
    print(f"      비율       {pct:.3f}%   (정상 범위 {lo}~{hi}%)")

    if not (lo <= pct <= hi):
        print("\n✗ 비율이 정상 범위를 벗어났다. 학습을 시작하지 않는다.")
        print("  확인할 것 — 동결이 적용됐는지, LoRA target_modules 가 맞는지,")
        print("             apply_to_* 플래그가 의도대로인지")
        sys.exit(1)
    print("      ✓ 정상 — 동결된 인코더 위에서 LoRA 만 학습된다")


def build_loss(M):
    """가중치는 MedSAM3 저장소 학습 스크립트의 값을 그대로 쓴다(임의 조정 없음)."""
    matcher = M["BinaryHungarianMatcherV2"](
        cost_class=2.0, cost_bbox=5.0, cost_giou=2.0, focal=True
    )
    loss_fns = [
        M["Boxes"](weight_dict={"loss_bbox": 5.0, "loss_giou": 2.0}),
        M["IABCEMdetr"](
            pos_weight=10.0,
            weight_dict={"loss_ce": 20.0, "presence_loss": 20.0},
            pos_focal=False, alpha=0.25, gamma=2, use_presence=True, pad_n_queries=200,
            weak_loss=False,
        ),
        M["Masks"](
            weight_dict={"loss_mask": 200.0, "loss_dice": 10.0},
            focal_alpha=0.25, focal_gamma=2.0, compute_aux=False,
        ),
    ]
    wrapper = M["Sam3LossWrapper"](
        loss_fns_find=loss_fns,
        matcher=matcher,
        o2m_matcher=M["BinaryOneToManyMatcher"](alpha=0.3, threshold=0.4, topk=4),
        o2m_weight=2.0,
        use_o2m_matcher_on_o2m_aux=False,
        normalization="local",
        normalize_by_valid_object_num=False,
    )
    return matcher, wrapper


def _unwrap(obj):
    """새 형식은 {"state":..., "meta":...}, 옛 형식은 state_dict 그대로."""
    if isinstance(obj, dict) and "state" in obj and "meta" in obj:
        return obj["state"], obj["meta"]
    return obj, None


def save_bundle(tag, ckpt_dir, names, epoch, run_name, M, model,
                heads=None, pd_module=None, optimizer=None, state=None):
    """LoRA · 등급 헤드 · 픽셀 디코더를 한 묶음으로 저장한다.

    셋이 반드시 같은 epoch 것이어야 하는데, 개별 저장은 하나만 성공하고
    나머지가 이전 epoch 으로 남는 사고가 가능하다. 전부 성공했을 때만
    매니페스트를 쓰고, 로드할 때 매니페스트로 짝을 확인한다.

    save_lora_weights 는 lora_A/lora_B 만 저장하므로 (lora_layers.py:519)
    새 픽셀 디코더 2.17M 은 여기서 따로 저장하지 않으면 통째로 사라진다.
    """
    meta = {"epoch": epoch, "run": run_name,
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    ok, written = True, {}

    lora_p = ckpt_dir / names["lora"]
    ok &= atomic_save(lambda q: M["save_lora_weights"](model, q), lora_p)
    written["lora"] = names["lora"]

    if heads is not None:
        hp = ckpt_dir / names["heads"]
        ok &= atomic_save(lambda q: torch.save({"state": heads.state_dict(),
                                                "meta": meta}, q), hp)
        written["heads"] = names["heads"]

    if pd_module is not None:
        pp = ckpt_dir / names["pd"]
        ok &= atomic_save(lambda q: torch.save({"state": pd_module.state_dict(),
                                                "meta": meta}, q), pp)
        written["pd"] = names["pd"]

    if optimizer is not None:
        # 이어받기용. AdamW 모멘텀이 없으면 재개 시점에 실효 학습률이 달라져
        # 일시적 요동이 생긴다. 20.7M 파라미터 × 2 × 4B ≈ 165MB.
        sp = ckpt_dir / names["state"]
        ok &= atomic_save(lambda q: torch.save(
            {"optimizer": optimizer.state_dict(), "meta": meta,
             "train_state": state or {}}, q), sp)
        written["state"] = names["state"]

    man = ckpt_dir / f"us_{tag}_manifest.json"
    if ok:
        meta["files"] = written
        atomic_save(lambda q: Path(q).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)), man)
    else:
        # 하나라도 실패하면 매니페스트를 지운다 — 짝이 깨진 상태를 남기지 않는다
        print(f"  ! {tag} 묶음 저장 실패 — 매니페스트를 제거해 불일치를 표시한다")
        try:
            man.unlink()
        except OSError:
            pass
    return ok


def run_batch(model, matcher, wrapper, M, batch, device, amp_dtype,
              want_queries=False):
    """분할 손실. want_queries=True 면 헤드용 특징도 함께 돌려준다.

    헤드 특징은 매처가 GT 에 매칭한 쿼리의 디코더 임베딩이다.
    matcher 반환은 (batch_idx, src_idx, tgt_idx) 이고 tgt_idx 는 None
    (sam3/train/matcher.py:288). 이미지당 GT 1개라 batch_idx 가 곧 표본 인덱스다.
    """
    inp = move_to_device(batch["input"], device)
    matched_feat, matched_bidx = None, None

    with torch.autocast("cuda", dtype=amp_dtype):
        outputs = model(inp)
        targets = [model.back_convert(t) for t in inp.find_targets]
        for t in targets:
            for k, v in t.items():
                if isinstance(v, torch.Tensor):
                    t[k] = v.to(device)

        SAM3Output = M["SAM3Output"]
        with SAM3Output.iteration_mode(
            outputs, iter_mode=SAM3Output.IterMode.ALL_STEPS_PER_STAGE
        ) as it:
            for stage_outputs, stage_targets in zip(it, targets):
                for out in stage_outputs:
                    out["indices"] = matcher(out, stage_targets)
                    for aux in out.get("aux_outputs", []):
                        aux["indices"] = matcher(aux, stage_targets)
                if want_queries and matched_feat is None:
                    fin = stage_outputs[-1]
                    q = fin.get("queries")
                    if q is not None:
                        bidx, sidx = fin["indices"][0], fin["indices"][1]
                        matched_feat = q[bidx.to(q.device), sidx.to(q.device)]
                        matched_bidx = bidx

        loss_dict = wrapper(outputs, targets)

    seg_loss = loss_dict[M["CORE_LOSS_KEY"]]
    if not want_queries:
        return seg_loss
    # BCE 안정성을 위해 헤드 입력은 fp32 로 올린다
    return seg_loss, (matched_feat.float() if matched_feat is not None else None), matched_bidx


def atomic_save(save_fn, path):
    """임시 파일에 쓰고 성공했을 때만 교체한다.

    디스크가 가득 차면 torch.save 가 중간에 실패하는데, 그대로 두면
    (a) 0바이트 잘린 파일이 남고 (b) 예외가 프로세스를 죽여 그 epoch 학습이
    통째로 날아간다. 실제로 2026-08-26 epoch 4 에서 그렇게 잃었다.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        save_fn(str(tmp))
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"  ! 체크포인트 저장 실패 {path.name} — {type(e).__name__}: {e}")
        print("    학습은 계속한다. 기존 파일은 그대로 보존됐다.")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


@torch.no_grad()
def val_dice_pass(model, M, ds, device, score_th=0.5, mask_th=0.5, limit=None,
                  heads=None):
    """valid Dice·IoU (+ heads 가 있으면 등급 지표).

    분할 지표는 eval_us_lora.py 와 같은 함수를 쓰므로 숫자가 일치한다.
    등급은 score 최대 쿼리의 임베딩으로 예측한다 — Dice 를 재는 그 마스크를
    만든 쿼리와 같은 인덱스다.
    """
    ids = ds.image_ids[:limit] if limit else ds.image_ids
    dices, ious, gt_g, pr_g = [], [], [], []
    if heads is not None:
        heads.eval()

    for img_id in tqdm(ids, desc="  dice", leave=False):
        info = ds.images[img_id]
        pil = PILImage.open(ds.split_dir / info["file_name"]).convert("RGB")
        ow, oh = pil.size
        t = ds.transform(pil.resize((ds.resolution, ds.resolution), PILImage.BILINEAR))

        out = run_one_query(model, M, t, ds.resolution, oh, ow, device)
        scores = out["pred_logits"][0].sigmoid().amax(dim=-1)
        mlg = out.get("pred_masks", None)
        mlg = mlg[0] if mlg is not None else None

        pred = pred_union(mlg, torch.where(scores > score_th)[0], oh, ow, mask_th)
        anns = ds.img_to_anns.get(img_id, [])
        gt = decode_gt_union(anns, oh, ow)
        d, i = dice_iou(pred, gt)
        dices.append(d)
        ious.append(i)

        if heads is not None and anns and "birads" in anns[0]:
            q = out.get("queries")
            if q is not None:
                feat = q[0, int(scores.argmax())].float()[None]
                cl, _ = heads(feat)
                pr_g.append(int(coral_decode(cl)[0]))
                gt_g.append(normalize_birads(anns[0]["birads"]))

    res = {"dice": float(np.mean(dices)), "iou": float(np.mean(ious))}
    if gt_g:
        g, p = np.array(gt_g), np.array(pr_g)
        res["grade_acc"] = float((g == p).mean())
        res["grade_w1"] = float((np.abs(g - p) <= 1).mean())
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(US_ROOT / "configs" / "us_lora.yaml"),
                    help="기본: breast/us/configs/us_lora.yaml (CWD 무관)")
    ap.add_argument("--log-dir", default=None, help="로그 디렉터리 (기본: breast/us/logs)")
    ap.add_argument("--run-name", default="us_lora", help="로그 파일 접두사 (기본: us_lora)")
    ap.add_argument("--no-log-file", action="store_true", help="콘솔에만 출력")
    ap.add_argument("--dice-gate", type=float, default=0.85,
                    help="best 후보를 val_dice 가 이 값 이상인 epoch 으로 제한 (기본 0.85)")
    ap.add_argument("--best-metric", default="grade_w1",
                    choices=["grade_acc", "grade_w1", "dice"],
                    help="헤드 사용 시 best 선택 기준 (기본 grade_w1). 헤드가 꺼져 있으면 항상 dice")
    ap.add_argument("--resume", action="store_true",
                    help="us_*_last.pt 에서 이어받는다 (LoRA·헤드·디코더·옵티마이저)")
    ap.add_argument("--smoke", type=int, default=None, metavar="N",
                    help="디버그 전용 — train/valid 를 N 배치·N 장으로 줄여 "
                         "로그 형식만 빠르게 확인한다")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()

    log_path = None
    if not args.no_log_file:
        log_path = start_run_log(args.run_name, args.log_dir, extra={"config": cfg_path})

    cfg = load_config(cfg_path)
    tr = cfg["training"]
    if args.smoke:
        tr["num_epochs"] = 1        # 로그 형식 확인용이므로 1 epoch 이면 충분하다
    set_seed(tr["seed"])

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    print("=" * 70)
    print("초음파 LoRA 1차 시험 학습 — lesion 분할")
    print("=" * 70)
    print(f"설정 {cfg_path}")
    print(f"GPU  {torch.cuda.get_device_name(0)}")
    if log_path:
        print(f"로그 {log_path}")

    M = import_medsam3(cfg["model"]["medsam3_repo"])

    model = build_model(cfg, M, device)

    # ④ pixel_decoder 교체. LoRA 주입 뒤에 해야 한다 — LoRA 는 Linear 만 대상이라
    # Conv2d 인 pixel_decoder 와 겹치지 않고, 새 모듈은 requires_grad=True 로 생성돼
    # 그대로 학습 대상이 된다. warm start 로 시작 출력이 원본과 같아 초기 붕괴가 없다.
    pdcfg = cfg.get("pixel_decoder", {})
    pd_module = None
    if pdcfg.get("block_type", "original") != "original":
        print("\n[+] UNet 픽셀 디코더")
        UPD.swap_in(model,
                    block_type=pdcfg["block_type"],
                    warm_start=pdcfg.get("warm_start", True))
        # 저장·로드용 참조. save_lora_weights 가 Conv2d 를 저장하지 않으므로
        # 이 모듈은 반드시 따로 체크포인트에 넣어야 한다.
        _, _, pd_module = UPD.find_pixel_decoder(model)

    check_trainable(model, M, cfg)

    print("\n데이터 적재")
    root, R = cfg["data"]["root"], cfg["data"]["resolution"]
    train_ds = USCocoDataset(root, cfg["data"]["train_split"], R, M)
    val_ds = USCocoDataset(root, cfg["data"]["val_split"], R, M)

    def collate(b):
        dps = [x[0] for x in b]
        out = M["collate_fn_api"](dps, dict_key="input", with_seg_masks=True)
        out["grades"] = torch.tensor([x[1]["grade"] for x in b], dtype=torch.long)
        out["malig"] = torch.tensor([x[1]["malig"] for x in b], dtype=torch.float32)
        return out

    train_loader = DataLoader(
        train_ds, batch_size=tr["batch_size"], shuffle=True, collate_fn=collate,
        num_workers=tr["num_workers"], pin_memory=True, drop_last=True,
    )
    val_loader = DataLoader(
        val_ds, batch_size=tr["batch_size"], shuffle=False, collate_fn=collate,
        num_workers=tr["num_workers"], pin_memory=True,
    )

    if tr["num_workers"] != 0:
        print(f"\n! 경고 — num_workers={tr['num_workers']}. {SHM_LIMIT_NOTE}")
        print("  워커가 배치를 전달하지 못하고 학습이 멈출 수 있다.")

    matcher, wrapper = build_loss(M)

    hcfg = cfg.get("heads", {})
    use_heads = bool(hcfg.get("enabled", False))
    heads = None
    w_seg = w_coral = w_malig = 0.0
    coral_pw = malig_pw = None
    if use_heads:
        heads = GradingHeads(in_dim=hcfg.get("in_dim", 256),
                             hidden=hcfg.get("hidden"),
                             dropout=hcfg.get("dropout", 0.0)).to(device)
        coral_pw, malig_pw = compute_pos_weights(train_ds.all_anns, device)
        w_seg = float(hcfg.get("w_seg", 1.0))
        w_coral = float(hcfg.get("w_coral", 40.0))
        w_malig = float(hcfg.get("w_malig", 60.0))
        nh = sum(p.numel() for p in heads.parameters())
        print(f"\n등급 헤드 활성 — 파라미터 {nh:,}")
        print(f"  손실 가중치  seg {w_seg}  coral {w_coral}  malig {w_malig}")
        print(f"  pos_weight   coral {[round(x, 3) for x in coral_pw.tolist()]}"
              f"  malig {malig_pw.item():.3f}")

    params = [p for p in model.parameters() if p.requires_grad]
    if use_heads:
        params += list(heads.parameters())
    optimizer = AdamW(params, lr=float(tr["learning_rate"]), weight_decay=tr["weight_decay"])
    amp_dtype = getattr(torch, tr["amp_dtype"])
    accum = tr["gradient_accumulation_steps"]

    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    if args.smoke:
        # 스모크 실행이 실제 체크포인트를 덮어쓰면 안 된다
        ckpt_dir = ckpt_dir / "_smoke"
        print(f"\n! --smoke — 체크포인트는 {ckpt_dir} 에만 저장한다")
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    best_path = ckpt_dir / cfg["output"]["best_name"]
    last_path = ckpt_dir / cfg["output"]["last_name"]
    out = cfg["output"]
    ckpt_names = {"lora": out["best_name"],
                  "heads": out.get("best_heads_name", "us_heads_best.pt"),
                  "pd": out.get("best_pd_name", "us_pd_best.pt")}
    ckpt_names_last = {"lora": out["last_name"],
                       "heads": out.get("last_heads_name", "us_heads_last.pt"),
                       "pd": out.get("last_pd_name", "us_pd_last.pt"),
                       "state": out.get("last_state_name", "us_state_last.pt")}

    start_epoch = 0
    if args.resume:
        man = ckpt_dir / "us_last_manifest.json"
        if not man.exists():
            sys.exit(f"✗ 이어받을 매니페스트가 없다: {man}")
        info = json.loads(man.read_text())
        start_epoch = int(info["epoch"])
        print(f"\n[이어받기] epoch {start_epoch} 까지 완료된 지점에서 재개")
        M["load_lora_weights"](model, str(ckpt_dir / ckpt_names_last["lora"]))
        if use_heads:
            st, _ = _unwrap(torch.load(ckpt_dir / ckpt_names_last["heads"],
                                       map_location=device))
            heads.load_state_dict(st)
        if pd_module is not None:
            st, _ = _unwrap(torch.load(ckpt_dir / ckpt_names_last["pd"],
                                       map_location=device))
            pd_module.load_state_dict(st)
        sp = ckpt_dir / ckpt_names_last["state"]
        if sp.exists():
            d = torch.load(sp, map_location=device)
            optimizer.load_state_dict(d["optimizer"])
            ts = d.get("train_state", {})
            best_score = ts.get("best_score", -1.0)
            best_epoch = ts.get("best_epoch", 0)
            best_qualified = ts.get("best_qualified", False)
            prov_dice = ts.get("prov_dice", -1.0)
            best_dice_at = ts.get("best_dice_at", float("nan"))
            oom_total = ts.get("oom_total", 0)
            print(f"           옵티마이저 복원 · best {best_score:.4f} (epoch {best_epoch})")
        else:
            print("           ! 옵티마이저 상태가 없다 — 모멘텀이 0 부터 다시 쌓인다")

    print(f"\n학습 시작 — {tr['num_epochs']} epoch · batch {tr['batch_size']} "
          f"x accum {accum} (유효 {tr['batch_size'] * accum}) · {tr['amp_dtype']}")
    print("=" * 70)

    OOM_MAX_RUN = 20          # 연속 이 횟수를 넘으면 일시적이 아니라고 본다
    oom_total = 0
    best_score, best_epoch = -1.0, 0
    best_qualified = False        # dice 게이트를 통과한 epoch 이 있었나
    prov_dice, best_dice_at = -1.0, float('nan')
    key = 'dice'
    for epoch in range(start_epoch, tr["num_epochs"]):
        model.train()
        if use_heads:
            heads.train()
        losses, seg_run, head_run = [], [], []
        oom_run = 0
        optimizer.zero_grad(set_to_none=True)
        pbar = tqdm(train_loader, desc=f"epoch {epoch + 1}/{tr['num_epochs']}")

        for step, batch in enumerate(pbar):
            # GPU 를 다른 작업과 공유하고 있어서 일시적 OOM 이 실재한다.
            # 그 배치만 버리고 계속 간다 — 6시간짜리를 배치 하나 때문에 잃지 않는다.
            # 연속으로 계속 나면 일시적이 아니므로(배치가 근본적으로 큼) 중단한다.
            try:
                if use_heads:
                    loss, feat, bidx = run_batch(model, matcher, wrapper, M, batch,
                                                 device, amp_dtype, want_queries=True)
                    seg_only = float(loss.detach())
                    loss = w_seg * loss
                    if feat is not None and feat.numel():
                        bi = bidx.to(device)
                        g = batch["grades"].to(device)[bi]
                        m = batch["malig"].to(device)[bi]
                        keep = g >= 0
                        if keep.any():
                            cl, ml = heads(feat[keep])
                            loss = loss + w_coral * coral_loss(cl, g[keep], coral_pw)
                            loss = loss + w_malig * F.binary_cross_entropy_with_logits(
                                ml, m[keep], pos_weight=malig_pw)
                    head_only = float(loss.detach()) - w_seg * seg_only
                else:
                    loss = run_batch(model, matcher, wrapper, M, batch, device, amp_dtype)
                    seg_only, head_only = float(loss.detach()), 0.0
                (loss / accum).backward()
            except torch.OutOfMemoryError:
                oom_run += 1
                oom_total += 1
                optimizer.zero_grad(set_to_none=True)
                del batch
                torch.cuda.empty_cache()
                if oom_run >= OOM_MAX_RUN:
                    print(f"\n✗ OOM {oom_run}회 연속 — 일시적이 아니다. "
                          f"batch_size 를 줄이고 --resume 으로 재개할 것")
                    raise
                pbar.set_postfix_str(f"OOM 건너뜀 {oom_run}/{OOM_MAX_RUN}")
                continue
            oom_run = 0

            if (step + 1) % accum == 0:
                torch.nn.utils.clip_grad_norm_(params, tr["max_grad_norm"])
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)

            losses.append(loss.item())
            seg_run.append(seg_only)
            head_run.append(head_only)
            pbar.set_postfix(loss=f"{loss.item():.4f}",
                             seg=f"{seg_only:.1f}", head=f"{head_only:.1f}")
            if args.smoke and step + 1 >= args.smoke:
                break

        if len(train_loader) % accum:
            torch.nn.utils.clip_grad_norm_(params, tr["max_grad_norm"])
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)

        train_loss = sum(losses) / max(len(losses), 1)

        model.eval()
        val_losses = []
        with torch.no_grad():
            for vstep, batch in enumerate(tqdm(val_loader, desc="  valid", leave=False)):
                if args.smoke and vstep >= args.smoke:
                    break
                val_losses.append(
                    run_batch(model, matcher, wrapper, M, batch, device, amp_dtype).item()
                )
        val_loss = sum(val_losses) / max(len(val_losses), 1)

        t0 = time.time()
        vm = val_dice_pass(model, M, val_ds, device, limit=args.smoke, heads=heads)
        dice_sec = time.time() - t0

        # best 기준. 헤드가 없으면 Dice, 있으면 --best-metric 를
        # "val_dice >= --dice-gate 인 epoch 중에서만" 고른다.
        # 분할이 무너지면 쿼리 임베딩도 나빠져 등급 지표를 믿을 수 없기 때문이다.
        key = "dice" if not use_heads else args.best_metric
        score = vm.get(key, vm["dice"])
        gate = args.dice_gate if use_heads else -1.0
        passed = vm["dice"] >= gate

        peak = torch.cuda.max_memory_allocated() / 1e9
        mark = ""
        if passed and score > best_score:
            best_score, best_epoch, best_qualified = score, epoch + 1, True
            best_dice_at = vm["dice"]
            save_bundle("best", ckpt_dir, ckpt_names, epoch + 1, args.run_name,
                        M, model, heads if use_heads else None, pd_module)
            mark = "  ← best"
        elif not best_qualified and vm["dice"] > prov_dice:
            # 아직 게이트를 통과한 epoch 이 없다. best 파일이 이전 실행 것으로
            # 남아 헷갈리지 않도록, 그때까지는 Dice 최고 epoch 을 잠정 저장한다.
            prov_dice, best_epoch = vm["dice"], epoch + 1
            best_dice_at = vm["dice"]
            save_bundle("best", ckpt_dir, ckpt_names, epoch + 1, args.run_name,
                        M, model, heads if use_heads else None, pd_module)
            mark = "  ← best(잠정)"
        elif use_heads and not passed:
            mark = f"  (게이트 미달 dice<{gate:.2f})"
        save_bundle("last", ckpt_dir, ckpt_names_last, epoch + 1, args.run_name,
                    M, model, heads if use_heads else None, pd_module,
                    optimizer=optimizer,
                    state={"best_score": best_score, "best_epoch": best_epoch,
                           "best_qualified": best_qualified, "prov_dice": prov_dice,
                           "best_dice_at": best_dice_at, "oom_total": oom_total})

        line = (f"epoch {epoch + 1}/{tr['num_epochs']}  "
                f"train {train_loss:.4f}  val_loss {val_loss:.4f}  "
                f"val_dice {vm['dice']:.4f}  val_iou {vm['iou']:.4f}")
        if use_heads:
            line += (f"  grade_acc {vm.get('grade_acc', float('nan')):.4f}"
                     f"  ±1 {vm.get('grade_w1', float('nan')):.4f}"
                     f"  [seg {np.mean(seg_run):.1f} head {np.mean(head_run):.1f}]")
        gs = UPD.gamma_stats(model)
        if gs:                       # light 경로일 때만 — 잔차가 열리는 속도
            line += f"  [gamma max {gs[0]:.4f} mean {gs[1]:.4f}]"
        line += f"  peak {peak:.1f}GB{mark}   (dice {dice_sec:.0f}s)"
        print(line)

        if use_heads and not args.smoke and vm["dice"] < SEG_BASELINE - 0.05:
            print(f"  ! 분할 경고 — val_dice {vm['dice']:.4f} 가 기준선 "
                  f"{SEG_BASELINE:.3f} 대비 0.05 이상 낮다. 헤드 가중치 재검토 필요")

    print("=" * 70)
    if use_heads and not best_qualified:
        print(f"! 게이트 미달 — val_dice >= {args.dice_gate:.2f} 인 epoch 이 없었다.")
        print(f"  best 는 Dice 최고 epoch {best_epoch} (dice {best_dice_at:.4f}) 으로 잠정 저장했다.")
        print("  분할이 무너진 상태라 등급 지표를 신뢰할 수 없다 — 손실 가중치를 재검토할 것.")
    else:
        print(f"완료 — best {key} {best_score:.4f} "
              f"(epoch {best_epoch}, val_dice {best_dice_at:.4f})")
    # 묶음은 lora·heads·pd(·state) 로 나뉘어 저장되므로 매니페스트를 기준으로
    # 실제 파일 존재까지 확인해 보고한다. 하나라도 빠지면 추론이 불가능하다.
    missing = 0
    for tag, names in (("best", ckpt_names), ("last", ckpt_names_last)):
        man = ckpt_dir / f"us_{tag}_manifest.json"
        if not man.exists():
            print(f"  ! [{tag}] 매니페스트 없음 — 묶음이 불완전하다")
            missing += 1
            continue
        print(f"  [{tag}] {man}")
        for kind, fn in names.items():
            p = ckpt_dir / fn
            if p.exists():
                print(f"        {kind:5s} {p}  ({p.stat().st_size / 1e6:.1f} MB)")
            else:
                print(f"        {kind:5s} {p}   ✗ 없음")
                missing += 1
    if missing:
        sys.exit(f"✗ 체크포인트 {missing}개 누락 — 이 묶음으로는 추론할 수 없다")


if __name__ == "__main__":
    main()
