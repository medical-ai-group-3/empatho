#!/usr/bin/env python3
"""
MRI(경로 C) 1차 시험 학습 — 종양 위치(MAMA-MIA) + 유방 밀도(Duke) + 양성/악성 병변(AMBL)
build_coco_from_npy.py 로 만든 2D COCO 데이터셋을 사용한다.

초음파 학습 코드(train_us_lora.py)는 참고만 하고 import 하지 않는다 (팀 방침 — 모달리티별 독립 스크립트).
동결된 MedSAM3 병합본 위에 MRI 전용 LoRA를 새로 얹어 5개 클래스(tumor/breast/dense tissue/
benign lesion/malignant lesion)를 텍스트 쿼리로 동시에 학습한다.

데이터셋 간 규모 불균형(MAMA-MIA 5.9만 : Duke 1.6만 : AMBL 0.4만 장 수준)이 커서,
배치 구성 시 파일명 접두사(mamamia_/duke_/ambl_)로 소스를 구분해 균형 샘플링한다.

  python3 train_mri_lora.py --config configs/mri_lora.yaml
"""

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
import torch.multiprocessing
import yaml
from PIL import Image as PILImage
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset, Sampler
from torchvision.transforms import v2
from tqdm import tqdm

import pycocotools.mask as mask_utils


def load_config(path):
    with open(path) as f:
        return yaml.safe_load(f)


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


# /dev/shm 용량이 작은 컨테이너/서버 환경 대응.
# 기본 전략(file_descriptor)은 워커가 텐서를 공유할 때 /dev/shm 파일을 쓰는데,
# 여기서 "Resource temporarily unavailable"이 났었다. file_system 전략은
# 파일시스템 임시경로를 쓰므로 shm 용량과 무관하게 동작한다 - num_workers를
# 다시 정상적으로(0이 아니게) 쓸 수 있게 해줌 (속도 핵심).
torch.multiprocessing.set_sharing_strategy("file_system")


# ── MedSAM3 저장소 import (구조/LoRA 로직만 가져다 씀, 학습 루프는 독립) ───────────
def import_medsam3(repo_root: str):
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


# ── 소스 태그 판별 (파일명 접두사) ───────────────────────────────────────────
SOURCE_TAGS = ("mamamia", "duke", "ambl")

# 사진 한 장에 담기는 객체(GT) 개수 상한. dense tissue처럼 파편이 수십 개인
# 사진이 배치에 걸리면 그 한 장이 메모리를 몰아서 먹어 OOM을 유발한다.
MAX_OBJECTS_PER_IMAGE = 20

# [6차 학습 신규, 2026-09-29] 캐시(.pt)는 이미지당 약 14MB라 디스크가 금방 찬다(coco_2d 393GB,
# 2026-09-29 여유 467GB). 여유가 이 값 미만이면 캐시 쓰기를 건너뛴다(학습은 계속, 매번 PNG 재계산).
CACHE_MIN_FREE_GB = 50


# 헷갈리기 쉬운(hard negative) 클래스 짝. 사진에 왼쪽 클래스가 있으면
# 오른쪽 클래스를 "없다" 질문으로 우선 추가한다. 없는 게 없는 상황(예: tumor만
# 있는 MAMA-MIA 사진에서 malignant lesion도 애초에 이 소스엔 안 나옴)이어도
# "없다"고 답하는 연습 자체가 목적이라 문제없다.
CONFUSION_MAP = {
    # [2차 학습 후 수정] "benign lesion": ["malignant lesion"] 제거함.
    # 실측 결과: benign 있는 이미지 256장, malignant 있는 이미지 731장(거의 3배 차이).
    # 대칭으로 서로를 negative로 붙였더니, 원래도 적은 benign 쪽이 malignant의
    # "여긴 없다" 신호(731장 분)에 압도돼 benign 성능이 오히려 악화됨(F1 0.080->0.034).
    # malignant는 negative로 덕을 크게 봤으니(F1 0.108->0.327) 그 방향은 유지하고,
    # benign 쪽만 이 경쟁 관계에서 빼서 "자기 정체성"만 순수하게 배우게 함.
    "malignant lesion": ["benign lesion"],
    "breast": ["dense tissue"],
    "dense tissue": ["breast"],
    "tumor": ["malignant lesion", "dense tissue"],
}

# [B안] breast+dense tissue가 둘 다 있는 사진(Duke)처럼, 서로가 서로의 헷갈리는
# 상대인데 둘 다 이미 positive라 CONFUSION_MAP 1순위로 못 채우는 경우를 위한 보강 매핑.
# "조직구조류"(breast/dense tissue)엔 "병변류"(tumor/benign/malignant) 중 하나를 우선 배정.
# 지금 오탐율이 제일 심한 게 병변 계열(90%대)이라, 아예 상관없는 클래스 대신
# 이 계열을 명시적으로 "없다"고 배우게 하는 게 실제 문제 해결에 더 직접적이다.
FALLBACK_CONFUSION_MAP = {
    "breast": ["malignant lesion", "benign lesion", "tumor"],
    "dense tissue": ["malignant lesion", "benign lesion", "tumor"],
}

ALL_CLASSES = ["tumor", "breast", "dense tissue", "benign lesion", "malignant lesion"]


def pick_negative_classes(present_classes: set, rng: random.Random, max_negatives: int = 1) -> list:
    """negative 클래스를 고른다.
    [메모리 제약으로 캡 적용] 원래는 positive 개수만큼(1:1)이 원칙이지만,
    서버 GPU가 공유 자원이라 여유가 부족할 때는 사진당 negative를 max_negatives개로
    제한한다 - Duke처럼 positive가 2개(breast+dense tissue)인 사진에서 쿼리가
    4개까지 늘어나 메모리 증가폭이 컸던 것을 완화하기 위함.
    1순위: CONFUSION_MAP의 직접 헷갈리는 상대
    2순위: FALLBACK_CONFUSION_MAP (병변류 우선)
    3순위: 남은 클래스 중 무작위"""
    absent = [c for c in ALL_CLASSES if c not in present_classes]
    if not absent:
        return []

    # [명시적 제외] benign lesion만 있을 땐 malignant lesion을 negative 후보에서
    # 아예 뺀다 - 3순위(무작위)에서 우연히 다시 뽑히는 걸 막기 위함(1순위 매핑만
    # 지워서는 부족함). malignant가 있을 때 benign을 negative로 쓰는 건 그대로 유지.
    if "benign lesion" in present_classes and "malignant lesion" not in present_classes:
        absent = [c for c in absent if c != "malignant lesion"]
        if not absent:
            return []

    n_needed = min(len(present_classes), max_negatives)
    picked = []

    for p in present_classes:
        for candidate in CONFUSION_MAP.get(p, []):
            if candidate in absent and candidate not in picked:
                picked.append(candidate)
                if len(picked) >= n_needed:
                    return picked

    for p in present_classes:
        for candidate in FALLBACK_CONFUSION_MAP.get(p, []):
            if candidate in absent and candidate not in picked:
                picked.append(candidate)
                if len(picked) >= n_needed:
                    return picked

    remaining = [c for c in absent if c not in picked]
    rng.shuffle(remaining)
    while len(picked) < n_needed and remaining:
        picked.append(remaining.pop())

    return picked


def source_tag_of(file_name: str) -> str:
    for tag in SOURCE_TAGS:
        if file_name.startswith(tag):
            return tag
    return "unknown"


# ── 데이터셋 ────────────────────────────────────────────────────────────────
class MRICocoDataset(Dataset):
    """<root>/<split>/_annotations.coco.json + 같은 폴더의 PNG.
    build_coco_from_npy.py 산출물 전용 (R=조영전,G=조영후,B=차분 3채널 PNG, 클래스 5종)."""

    def __init__(self, root, split, resolution, M, use_negative_sampling=False, negative_seed=42, max_negatives=1,
                 ann_name="_annotations.coco.json"):
        self.M = M
        self.use_negative_sampling = use_negative_sampling
        self.max_negatives = max_negatives
        self._neg_rng = random.Random(negative_seed)
        self.split_dir = Path(root) / split
        self.resolution = resolution

        # [6차] ann_name — add_tumor_negative_slices.py가 만든 _annotations_tumorneg.coco.json을
        # 고를 수 있게. 기본값이면 기존과 동일.
        ann_file = self.split_dir / ann_name
        if not ann_file.exists():
            raise FileNotFoundError(ann_file)
        with open(ann_file) as f:
            coco = json.load(f)

        self.images = {im["id"]: im for im in coco["images"]}
        self.image_ids = sorted(self.images)
        self.categories = {c["id"]: c["name"] for c in coco["categories"]}

        self.img_to_anns = defaultdict(list)
        for a in coco["annotations"]:
            self.img_to_anns[a["image_id"]].append(a)

        # [메모리 안정화] 객체(annotation) 수가 너무 많은 사진(dense tissue 파편 등)은
        # batch에 걸리면 메모리가 튀어 OOM을 유발함 - 통째로 제외.
        # 데이터가 65k+장으로 충분해서, 일부 사진 통째로 빼도 손실이 미미하고
        # 일부만 잘라내는 것보다 "완전한 정답만 학습"이라 데이터 품질도 더 낫다.
        before_n = len(self.image_ids)
        self.image_ids = [
            iid for iid in self.image_ids
            if len(self.img_to_anns.get(iid, [])) <= MAX_OBJECTS_PER_IMAGE
        ]
        excluded_n = before_n - len(self.image_ids)
        if excluded_n:
            print(f"  [{split}] 객체 {MAX_OBJECTS_PER_IMAGE}개 초과 사진 {excluded_n}장 제외 "
                  f"({before_n} -> {len(self.image_ids)})")

        # 태스크 균형 샘플러가 쓸 소스별 인덱스 목록
        self.source_tags = [source_tag_of(self.images[iid]["file_name"]) for iid in self.image_ids]

        # [4차 학습 신규] AMBL 안에서 benign/malignant 노출 빈도 격차(256장 vs 731장, 약 3배)를
        # 좁히기 위해, 이미지별로 어떤 병변류가 있는지 미리 계산해둠 - 샘플러가 이걸로
        # AMBL 내부에서도 한 번 더 균형샘플링하게 함.
        self.ambl_subclass = []
        for iid, tag in zip(self.image_ids, self.source_tags):
            if tag != "ambl":
                self.ambl_subclass.append(None)
                continue
            classes_here = {self.categories.get(a["category_id"]) for a in self.img_to_anns.get(iid, [])}
            has_benign = "benign lesion" in classes_here
            has_malignant = "malignant lesion" in classes_here
            if has_benign and has_malignant:
                self.ambl_subclass.append("both")
            elif has_benign:
                self.ambl_subclass.append("benign")
            elif has_malignant:
                self.ambl_subclass.append("malignant")
            else:
                self.ambl_subclass.append("neither")

        # [5차 학습 신규] mamamia 안에서도 기관(ISPY1/ISPY2/NACT/DUKE)별 표본 수가 크게
        # 다름(오늘 배치 스모크테스트에서 DUKE·ISPY1 계열 tumor 오탐이 유독 심했음 확인).
        # AMBL 내부 균형샘플링과 같은 방식으로, mamamia 안에서도 기관별 균형을 맞춘다.
        import re as _re
        self.mamamia_subsource = []
        for iid, tag in zip(self.image_ids, self.source_tags):
            if tag != "mamamia":
                self.mamamia_subsource.append(None)
                continue
            fn = self.images[iid]["file_name"]
            m = _re.match(r"mamamia_([A-Za-z]+)", fn)
            self.mamamia_subsource.append(m.group(1).upper() if m else "UNKNOWN")

        self.transform = v2.Compose([
            v2.ToImage(),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ])

        # /dev/shm 64MB 제약으로 num_workers=0(단일 프로세스) 강제 상태.
        # PIL resize + 마스크 폴리곤->인터폴레이트를 매 스텝 반복하는 게
        # 단일 프로세스에서 제일 비싼 부분이라, 리사이즈된 이미지 텐서를
        # 디스크 캐시(.pt)로 한 번만 만들어두고 이후엔 로드만 한다.
        self.cache_dir = self.split_dir / f"_cache_{resolution}"
        self.cache_dir.mkdir(exist_ok=True)

        counts = defaultdict(int)
        for t in self.source_tags:
            counts[t] += 1
        print(f"  [{split}] 이미지 {len(self.image_ids)} · 어노테이션 {len(coco['annotations'])} "
              f"· 카테고리 {list(self.categories.values())}")
        print(f"           소스별 이미지 수: {dict(counts)}")
        n_tneg = sum(1 for iid in self.image_ids if self.images[iid].get("tumor_negative"))
        if n_tneg:
            print(f"           tumor 음성 슬라이스(MAMA-MIA 종양 없는 슬라이스): {n_tneg}장")

    def __len__(self):
        return len(self.image_ids)

    def _cache_has_room(self):
        try:
            st = os.statvfs(self.cache_dir)
            return st.f_bavail * st.f_frsize / 1e9 >= CACHE_MIN_FREE_GB
        except OSError:
            return False

    def __getitem__(self, idx):
        M = self.M
        R = self.resolution
        img_id = self.image_ids[idx]
        info = self.images[img_id]

        cache_path = self.cache_dir / f"{img_id}.pt"
        if cache_path.exists():
            cached = torch.load(cache_path, weights_only=False)
            image_tensor = cached["image_tensor"]
            objects = cached["objects"]
            class_names = cached["class_names"]
        else:
            pil = PILImage.open(self.split_dir / info["file_name"]).convert("RGB")
            orig_w, orig_h = pil.size
            pil = pil.resize((R, R), PILImage.BILINEAR)
            image_tensor = self.transform(pil)

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
                    except Exception as e:
                        print(f"  ! mask 처리 실패 img={img_id} ann={i}: {e}")

                objects.append(M["Object"](
                    bbox=box, area=(box[2] * box[3]).item(), object_id=i, segment=segment
                ))

            # [6차] tumor 음성 슬라이스는 정답 마스크가 없어 재계산이 싸다 — 캐시 안 씀(디스크 절약).
            # 그 외에도 디스크 여유가 CACHE_MIN_FREE_GB 미만이면 캐시 쓰기를 건너뛴다.
            if not info.get("tumor_negative") and self._cache_has_room():
                torch.save({"image_tensor": image_tensor, "objects": objects, "class_names": class_names},
                           cache_path)

        image_obj = M["Image"](data=image_tensor, objects=objects, size=(R, R))

        by_class = defaultdict(list)
        for obj, name in zip(objects, class_names):
            by_class[name.lower()].append(obj.object_id)
        if info.get("tumor_negative"):
            # [6차 학습 신규] MAMA-MIA 종양 없는 슬라이스 — "object"가 아니라 "tumor"를 묻고
            # 정답 없음으로 가르친다. 서빙은 모든 슬라이스에 tumor를 묻는데, 기존 학습엔 이런
            # 사례가 없어서 종양 없는 슬라이스 오탐이 컸다(40명 분석: 순수 오탐 72%가 정답에서
            # 10슬라이스 넘게 떨어진 슬라이스). 아래 negative sampling이 CONFUSION_MAP["tumor"]로
            # 다른 "없음" 쿼리를 하나 더 붙일 수 있다(기존 종양 슬라이스와 같은 규칙).
            assert not by_class, f"tumor_negative 이미지에 정답이 있음: img={img_id}"
            by_class["tumor"] = []
        elif not by_class:
            by_class["object"] = []

        # [negative sampling, 1:1] 사진에 실제 있는 클래스만 물어보면
        # "없다"고 답하는 법을 모델이 영영 못 배운다(오탐율 90%대의 원인).
        # 사진에 있는 클래스 수만큼, 헷갈리는 상대 클래스를 "정답 없음" 쿼리로 추가.
        if self.use_negative_sampling and by_class and "object" not in by_class:
            present = set(by_class.keys())
            negatives = pick_negative_classes(present, self._neg_rng, max_negatives=self.max_negatives)
            for neg_cls in negatives:
                if neg_cls not in by_class:  # 혹시 이미 있으면 덮어쓰지 않음
                    by_class[neg_cls] = []  # 빈 리스트 = "이 사진엔 없다"는 정답

        meta = M["InferenceMetadata"](
            coco_image_id=img_id, original_image_id=img_id, original_category_id=0,
            original_size=(R, R), object_id=-1, frame_index=-1,
        )
        queries = [
            M["FindQueryLoaded"](
                query_text=text, image_id=0, object_ids_output=ids,
                is_exhaustive=True, query_processing_order=0, inference_metadata=meta,
            )
            for text, ids in by_class.items()
        ]

        return M["Datapoint"](find_queries=queries, images=[image_obj], raw_images=[None])


class SourceBalancedSampler(Sampler):
    """MAMA-MIA(종양)/Duke(밀도)/AMBL(보조) 데이터 규모 차이(대략 15:4:1)를 완화하기 위해
    매 스텝 소스 셋 중 무작위로 하나 골라 그 소스 안에서만 샘플링한다.
    -> 배치 단위가 아니라 에폭 전체 샘플 등장 빈도를 소스 간 균등에 가깝게 맞춘다.

    [4차 학습] AMBL을 뽑았을 때, 그 안에서도 benign/malignant을 한 번 더 균형샘플링.
    [5차 학습 신규] mamamia를 뽑았을 때, 그 안에서도 기관(ISPY1/ISPY2/NACT/DUKE)을
    한 번 더 균형샘플링. 배치 스모크테스트(2026-08-31)에서 DUKE·ISPY1 계열 tumor
    오탐이 유독 심했던 것에 대한 대응 - mamamia 표본이 압도적으로 커도(5만+장)
    소스 내부는 기관별로 여전히 불균형했을 가능성."""

    def __init__(self, source_tags, ambl_subclass=None, mamamia_subsource=None, seed=42):
        self.by_source = defaultdict(list)
        for idx, tag in enumerate(source_tags):
            self.by_source[tag].append(idx)
        self.sources = [t for t in self.by_source if self.by_source[t]]
        self.n = len(source_tags)
        self.rng = random.Random(seed)

        self.ambl_by_subclass = None
        if ambl_subclass is not None and "ambl" in self.by_source:
            grouped = defaultdict(list)
            for idx in self.by_source["ambl"]:
                sub = ambl_subclass[idx]
                grouped[sub].append(idx)
            # benign/malignant만 균형 대상. both/neither는 각자 있는 만큼만 사용(둘 다 이미 배정된 셈).
            self.ambl_by_subclass = {k: v for k, v in grouped.items() if k in ("benign", "malignant") and v}

        self.mamamia_by_subsource = None
        if mamamia_subsource is not None and "mamamia" in self.by_source:
            grouped = defaultdict(list)
            for idx in self.by_source["mamamia"]:
                sub = mamamia_subsource[idx]
                if sub:
                    grouped[sub].append(idx)
            self.mamamia_by_subsource = {k: v for k, v in grouped.items() if v}

    def __iter__(self):
        for _ in range(self.n):
            src = self.rng.choice(self.sources)
            if src == "ambl" and self.ambl_by_subclass:
                sub = self.rng.choice(list(self.ambl_by_subclass.keys()))
                yield self.rng.choice(self.ambl_by_subclass[sub])
            elif src == "mamamia" and self.mamamia_by_subsource:
                sub = self.rng.choice(list(self.mamamia_by_subsource.keys()))
                yield self.rng.choice(self.mamamia_by_subsource[sub])
            else:
                yield self.rng.choice(self.by_source[src])

    def __len__(self):
        return self.n


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

    print("\n[1/3] 병합본 로드 (모든 모달리티 공유 동결 베이스)")
    print(f"      파일   {ckpt}")
    print(f"      크기   {ckpt.stat().st_size / 1e9:.2f} GB")

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

    print("\n[2/3] MRI 전용 LoRA 주입 (rank={} alpha={}) — 맘모/초음파 LoRA와 별개".format(
        cfg["lora"]["rank"], cfg["lora"]["alpha"]))

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
        sys.exit(1)
    print("      ✓ 정상 — 동결된 인코더 위에서 MRI LoRA만 학습된다")


def build_loss(M, cfg=None):
    """가중치는 기본적으로 MedSAM3 저장소/초음파 스크립트 값을 그대로 따른다.
    [6차 학습 대비, 5차에는 기본값으로 비활성] 병변 모양(형태) 정확도 문제 대응용으로
    loss_mask/loss_dice 비율을 yaml에서 조정할 수 있게 함. 오늘(2026-08-31) DUKE_399
    사례에서 진짜 병변을 모델이 납작하게 왜곡해서 예측하는 걸 확인 - dice 비중을
    올리면 형태(겹침 비율) 쪽에 더 강하게 벌점을 줄 수 있다는 가설.
    ⚠ 5차는 mamamia 하위셋 균형(오탐 대응)만 켜고 이 값은 기본값 유지 권장 -
      두 변경을 동시에 넣으면 5차 결과가 좋아져도 어느 쪽 효과인지 구분 안 됨."""
    cfg = cfg or {}
    loss_cfg = cfg.get("training", {})
    mask_w = loss_cfg.get("loss_mask_weight", 200.0)
    dice_w = loss_cfg.get("loss_dice_weight", 10.0)

    matcher = M["BinaryHungarianMatcherV2"](
        cost_class=2.0, cost_bbox=5.0, cost_giou=2.0, focal=True
    )
    loss_fns = [
        M["Boxes"](weight_dict={"loss_bbox": 5.0, "loss_giou": 2.0}),
        M["IABCEMdetr"](
            pos_weight=10.0,
            weight_dict={"loss_ce": 20.0, "presence_loss": 20.0},
            pos_focal=False, alpha=0.25, gamma=2, use_presence=True, pad_n_queries=200,
        ),
        M["Masks"](
            weight_dict={"loss_mask": mask_w, "loss_dice": dice_w},
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


def run_batch(model, matcher, wrapper, M, batch, device, amp_dtype):
    inp = move_to_device(batch["input"], device)
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

        loss_dict = wrapper(outputs, targets)
    return loss_dict[M["CORE_LOSS_KEY"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/mri_lora.yaml")
    ap.add_argument("--max-steps", type=int, default=None,
                     help="[속도 테스트용] 이 스텝 수만큼만 돌고 자동 종료 (체크포인트 저장 안 함)")
    ap.add_argument("--steps-per-epoch", type=int, default=None,
                     help="[partial epoch] 한 epoch로 칠 스텝 수를 제한. max-steps와 달리 "
                          "정상적으로 검증(val)·체크포인트 저장까지 수행함. "
                          "예: 전체 65036스텝 중 1/4만 돌려면 16259 지정")
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = load_config(cfg_path)
    tr = cfg["training"]
    set_seed(tr["seed"])

    if not torch.cuda.is_available():
        sys.exit("✗ CUDA 가 필요하다")
    device = "cuda"

    print("=" * 70)
    print("MRI LoRA 1차 시험 학습 — 종양분할/유방밀도/양성-악성 병변 (5클래스 텍스트쿼리)")
    print("=" * 70)
    print(f"설정 {cfg_path}")
    print(f"GPU  {torch.cuda.get_device_name(0)}")

    M = import_medsam3(cfg["model"]["medsam3_repo"])

    model = build_model(cfg, M, device)
    check_trainable(model, M, cfg)

    print("\n데이터 적재")
    root, R = cfg["data"]["root"], cfg["data"]["resolution"]
    train_ds = MRICocoDataset(root, cfg["data"]["train_split"], R, M,
                               use_negative_sampling=cfg["training"].get("use_negative_sampling", False),
                               negative_seed=tr["seed"],
                               max_negatives=cfg["training"].get("max_negatives_per_image", 1),
                               ann_name=cfg["data"].get("ann_name", "_annotations.coco.json"))
    # val은 negative 추가 없이 원본 그대로. 단 [6차] ann_name이 tumorneg면 val에도 tumor 음성
    # 슬라이스가 들어가서, val loss가 "종양 없는 슬라이스 오탐"도 반영한다(best 선택 기준).
    val_ds = MRICocoDataset(root, cfg["data"]["val_split"], R, M,
                            ann_name=cfg["data"].get("ann_name", "_annotations.coco.json"))

    def collate(b):
        return M["collate_fn_api"](b, dict_key="input", with_seg_masks=True)

    _ambl_subclass_arg = train_ds.ambl_subclass if cfg["training"].get("balance_ambl_subclass", True) else None
    _mamamia_subsource_arg = train_ds.mamamia_subsource if cfg["training"].get("balance_mamamia_subsource", False) else None
    train_sampler = SourceBalancedSampler(
        train_ds.source_tags, ambl_subclass=_ambl_subclass_arg,
        mamamia_subsource=_mamamia_subsource_arg, seed=tr["seed"]
    )
    train_loader = DataLoader(
        train_ds, batch_size=tr["batch_size"], sampler=train_sampler, collate_fn=collate,
        num_workers=tr["num_workers"], pin_memory=True, drop_last=True,
    )
    val_loader = DataLoader(
        val_ds, batch_size=tr["batch_size"], shuffle=False, collate_fn=collate,
        num_workers=tr["num_workers"], pin_memory=True,
    )

    matcher, wrapper = build_loss(M, cfg)
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = AdamW(params, lr=float(tr["learning_rate"]), weight_decay=tr["weight_decay"])
    amp_dtype = getattr(torch, tr["amp_dtype"])
    accum = tr["gradient_accumulation_steps"]

    ckpt_dir = Path(cfg["output"]["ckpt_dir"])
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    best_path = ckpt_dir / cfg["output"]["best_name"]
    last_path = ckpt_dir / cfg["output"]["last_name"]

    steps_per_epoch = len(train_sampler) // tr["batch_size"]
    if args.steps_per_epoch:
        print(f"\n[partial epoch] 원래 1 epoch={steps_per_epoch}스텝 -> "
              f"{args.steps_per_epoch}스텝만 돌고 검증·저장 (약 {args.steps_per_epoch/steps_per_epoch:.1%})")
        steps_per_epoch = args.steps_per_epoch
    print(f"\n학습 시작 — {tr['num_epochs']} epoch · batch {tr['batch_size']} "
          f"x accum {accum} (유효 {tr['batch_size'] * accum}) · {tr['amp_dtype']} "
          f"· 소스균형샘플러(스텝당 소스 무작위 선택)")
    print("=" * 70)

    best_val = float("inf")
    for epoch in range(tr["num_epochs"]):
        model.train()
        losses = []
        optimizer.zero_grad(set_to_none=True)
        pbar = tqdm(train_loader, total=steps_per_epoch, desc=f"epoch {epoch + 1}/{tr['num_epochs']}")

        for step, batch in enumerate(pbar):
            loss = run_batch(model, matcher, wrapper, M, batch, device, amp_dtype)
            (loss / accum).backward()

            if (step + 1) % accum == 0:
                torch.nn.utils.clip_grad_norm_(params, tr["max_grad_norm"])
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)

            if args.max_steps and (step + 1) >= args.max_steps:
                print(f"\n[속도 테스트] --max-steps {args.max_steps} 도달, 여기서 중단 (저장 안 함)")
                return

            if args.steps_per_epoch and (step + 1) >= args.steps_per_epoch:
                break  # max_steps와 달리 return이 아니라 break -> 아래 검증·저장 정상 진행

            losses.append(loss.item())
            pbar.set_postfix(loss=f"{loss.item():.4f}")

        if len(losses) % accum:
            torch.nn.utils.clip_grad_norm_(params, tr["max_grad_norm"])
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)

        train_loss = sum(losses) / max(len(losses), 1)

        # [안전장치] 검증(val) 도중 연결이 끊기면(오늘 두 번 겪음) 방금 끝난 학습 결과가
        # 통째로 날아갔었다 - 검증 시작 "전"에 먼저 한 번 저장해서 최악의 경우에도
        # 이 지점까지의 학습은 보존되게 한다. val_loss 기준 best는 이 시점엔 모르니
        # last_path에만 임시 저장(검증 끝나면 정상적인 best/last 로직이 다시 덮어씀).
        M["save_lora_weights"](model, str(last_path))
        print(f"  [안전저장] 검증 시작 전 학습 결과 저장함 -> {last_path}")

        model.eval()
        val_losses = []
        with torch.no_grad():
            for batch in tqdm(val_loader, desc="  valid", leave=False):
                val_losses.append(
                    run_batch(model, matcher, wrapper, M, batch, device, amp_dtype).item()
                )
        val_loss = sum(val_losses) / max(len(val_losses), 1)

        peak = torch.cuda.max_memory_allocated() / 1e9
        mark = ""
        if val_loss < best_val:
            best_val = val_loss
            M["save_lora_weights"](model, str(best_path))
            mark = "  ← best"
        M["save_lora_weights"](model, str(last_path))

        print(f"epoch {epoch + 1}/{tr['num_epochs']}  "
              f"train {train_loss:.4f}  val {val_loss:.4f}  "
              f"peak {peak:.1f}GB{mark}")

    print("=" * 70)
    print(f"완료 — best val {best_val:.4f}")
    print(f"  {best_path}")
    print(f"  {last_path}")


if __name__ == "__main__":
    main()
