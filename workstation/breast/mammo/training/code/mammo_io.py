#!/usr/bin/env python
"""
모델 적재 · 전처리 공통 모듈 — 서빙과 평가가 함께 쓴다.

초음파 파트의 model_io.py 와 같은 자리다. 원래 이 함수들은 평가 스크립트
안에 흩어져 있었고(eval_mammo_det · merge_boxes · eval_end2end), 서빙이
그것들을 부르면 평가 의존성(pycocotools · 정답 로더 · FROC)이 서버까지
딸려간다. 서빙에 필요한 것만 여기로 모았다.

의존성 — torch · numpy · cv2 · pydicom · pandas(train_mammo 경유)
         pycocotools 를 안 쓴다.

주의 — import_medsam3() 은 내부에서 os.chdir 한다.
       호출 전에 모든 경로를 절대경로로 확정할 것.
       서빙에서는 infer_mammo.load_model() 이 끝나고 원래 폴더로 되돌린다.

여기 있는 함수를 고치면 서빙과 평가가 같이 바뀐다. 그게 목적이다 —
복사해 두면 한쪽만 고쳐졌을 때 시연 화면과 측정치가 조용히 어긋난다.
"""

import contextlib
import os
import sys
from pathlib import Path

# 조각화 완화. CUDA 할당자가 이 값을 초기화 때 읽으므로 torch 사용 전에
# 걸어야 한다. 실측에서 1.90GiB 가 "예약됐지만 미사용" 으로 놀다가
# 1.60GiB 할당이 실패했다 — OOM 메시지가 직접 권하는 설정이다.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_tiles import norm8, positions, tissue_bbox, tissue_mask  # noqa: E402,F401
from paths import BASE_CFG, BASE_CKPT                              # noqa: E402

RES = 1008                     # RoPE 표가 이 크기로 미리 계산돼 있다
# 질의는 이름 정렬 순으로 만든다 — 학습 데이터셋과 같은 순서여야 한다
PROMPTS = sorted(("mass", "calcification"))
KIND_OF = {"mass": "mass", "calcification": "calc"}
BIOPSY_CUT = 4                 # 4·5 = 조직검사, 1·2·3 = 추적


# ────────────────────────── MedSAM3 ──────────────────────────
def import_medsam3(repo_root):
    """
    주의: 내부에서 os.chdir 한다. SAM 3 가 자기 자산을 상대경로로 찾기 때문이다
    ('sam3/assets/bpe_simple_vocab_16e6.txt.gz'). 호출 전에 경로를 절대경로로
    확정할 것.
    """
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)
    from lora_layers import (LoRAConfig, apply_lora_to_model, count_parameters,
                             load_lora_weights)
    from merge_medsam3 import load_merged_model
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata)
    from sam3.train.matcher import BinaryHungarianMatcherV2
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    return dict(load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
                apply_lora_to_model=apply_lora_to_model,
                count_parameters=count_parameters,
                load_lora_weights=load_lora_weights,
                collate_fn_api=collate_fn_api, Datapoint=Datapoint,
                FindQueryLoaded=FindQueryLoaded, Image=Image,
                InferenceMetadata=InferenceMetadata,
                BinaryHungarianMatcherV2=BinaryHungarianMatcherV2)


def move_to_device(o, dev):
    """
    중첩된 것까지 전부 옮긴다.

    얕게 옮기면 find_queries 안의 기하 프롬프트 텐서가 CPU 에 남고,
    geometry_encoder 가 그것을 곱하는 순간 '두 장치' 오류로 죽는다.
    """
    if torch.is_tensor(o):
        return o.to(dev)
    if isinstance(o, (list, tuple)):
        return type(o)(move_to_device(x, dev) for x in o)
    if isinstance(o, dict):
        return {k: move_to_device(v, dev) for k, v in o.items()}
    if hasattr(o, "__dataclass_fields__"):
        for f in o.__dataclass_fields__:
            setattr(o, f, move_to_device(getattr(o, f), dev))
        return o
    return o


def build_detector(M, lora_path, device, rank=16, alpha=32,
                   target_modules=("q_proj", "k_proj", "v_proj", "out_proj",
                                   "qkv", "proj", "fc1", "fc2",
                                   "linear1", "linear2"),
                   vision=True, text=False, detr_enc=True, detr_dec=True,
                   mask_dec=False, verbose=True):
    """
    학습과 같은 방식으로 세운다 — 병합본 + 같은 LoRA 설정 + 학습된 가중치.
    한 글자라도 다르면 성능이 아니라 구성 오류를 재게 된다.
    """
    model = M["load_merged_model"](str(BASE_CKPT), str(BASE_CFG), device=device)
    if getattr(model, "matcher", None) is None:
        model.matcher = M["BinaryHungarianMatcherV2"](
            focal=True, cost_class=2.0, cost_bbox=5.0, cost_giou=2.0,
            alpha=0.25, gamma=2, stable=False)
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=rank, alpha=alpha, dropout=0.0,
        target_modules=list(target_modules),
        apply_to_vision_encoder=bool(vision),
        apply_to_text_encoder=bool(text),
        apply_to_geometry_encoder=False,
        apply_to_detr_encoder=bool(detr_enc),
        apply_to_detr_decoder=bool(detr_dec),
        apply_to_mask_decoder=bool(mask_dec)))
    lp = Path(lora_path).expanduser().resolve()
    if not lp.is_file():
        raise FileNotFoundError(f"학습된 LoRA 가 없다: {lp}")
    M["load_lora_weights"](model, str(lp))
    if verbose:
        c = M["count_parameters"](model)
        print(f"  검출기  {lp.name}  LoRA 자리 "
              f"{c['trainable_parameters']:,} ({c['trainable_percentage']:.3f}%)")
    return model.to(device).eval()


def build_descriptor(ckpt_path, device, verbose=True):
    """
    서술어 모델(특징 추출기 + 헤드)을 복원한다. 반환 (ext, head, meta).
    학습 때 쓴 전처리 설정이 체크포인트 안에 들어 있으므로 그것을 그대로 쓴다.
    """
    # 여기서 부른다 — 서버가 안 쓰는 경로까지 미리 끌어오지 않는다
    from train_mammo import (CFG, CKPT, FeatExtractor, inject_lora,
                             load_merged_model, make_head)
    d = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
    a = d.get("args", {}) or {}
    meta = dict(kind=d["kind"], cols=d["cols"],
                src=a.get("src", "trunk"), levels=a.get("levels", "last"),
                pool=a.get("pool", "grid"), grid=int(a.get("grid", 4)),
                size=int(a.get("size", 1008)), pad=not a.get("no_pad", False),
                clip=a.get("clip", 99.9), epoch=d.get("epoch"),
                test_f1=d.get("test_f1"))
    from paths import medsam3_cwd
    with medsam3_cwd():          # SAM 3 토크나이저가 자산을 상대경로로 찾는다
        full = load_merged_model(a.get("ckpt", CKPT), CFG, device=device)
    vb = full.backbone.vision_backbone
    del full
    for p in vb.parameters():
        p.requires_grad = False
    ext = FeatExtractor(vb, meta["src"])
    if d.get("lora"):
        inject_lora(ext.net, int(a.get("rank", 16)), int(a.get("alpha", 32)),
                    {"qkv", "proj", "fc1", "fc2"})
        ext = ext.to(device)
        _, unexpected = ext.load_state_dict(d["lora"], strict=False)
        if unexpected:
            raise RuntimeError(f"체크포인트에 모델이 모르는 키: {unexpected[:5]}")
    else:
        ext = ext.to(device)
    head = make_head(len(d["cols"]), int(d["feat_dim"])).to(device)
    head.load_state_dict(d["head"])
    ext.eval(); head.eval()
    if verbose:
        print(f"  서술어  {Path(ckpt_path).name}  kind={meta['kind']} "
              f"ep{meta['epoch']} F1 {meta['test_f1']}")
    return ext, head, meta


# ────────────────────────── 타일 추론 ──────────────────────────
def make_batch(M, tile_u8, dev):
    """타일 하나에 두 종류 질의를 담아 한 번만 순전파한다."""
    x = torch.from_numpy(tile_u8).float().div_(255.0)
    x = x.unsqueeze(0).repeat(3, 1, 1)          # 학습과 같은 3채널 · 0.5/0.5
    x = (x - 0.5) / 0.5
    img = M["Image"](data=x, objects=[], size=(RES, RES))
    meta = M["InferenceMetadata"](
        coco_image_id=0, original_image_id=0, original_category_id=0,
        original_size=(RES, RES), object_id=-1, frame_index=-1)
    qs = [M["FindQueryLoaded"](query_text=t, image_id=0, object_ids_output=[],
                               is_exhaustive=True, query_processing_order=0,
                               inference_metadata=meta) for t in PROMPTS]
    dp = M["Datapoint"](find_queries=qs, images=[img])
    b = M["collate_fn_api"]([dp], dict_key="input", with_seg_masks=False)
    return move_to_device(b["input"], dev) if dev is not None else b["input"]


def read_out(out, thr, verbose=False):
    """마지막 단계에서 질의별 박스와 점수를 꺼낸다. 반환은 프롬프트 이름별."""
    last = out[-1] if isinstance(out, (list, tuple)) else out
    boxes = last["pred_boxes_xyxy"].detach().float().cpu().numpy()   # (Q,200,4)
    logits = last["pred_logits"].detach().float().cpu().numpy()      # (Q,200,1)
    scores = 1.0 / (1.0 + np.exp(-logits[..., 0]))
    if verbose:                        # eval_mammo_det --check 의 첫 타일 점검
        print(f"      pred_boxes_xyxy {boxes.shape}  "
              f"값 범위 {boxes.min():.3f}~{boxes.max():.3f}  "
              f"점수 {scores.min():.3f}~{scores.max():.3f}")
    out_d = {}
    scale = RES if boxes.max() <= 1.5 else 1.0   # 정규화 좌표면 화면 크기를 곱한다
    for qi, name in enumerate(PROMPTS):
        keep = scores[qi] >= thr
        bs = boxes[qi][keep] * scale
        out_d[name] = [(float(b[0]), float(b[1]), float(b[2]), float(b[3]),
                        float(s)) for b, s in zip(bs, scores[qi][keep])]
    return out_d


# ────────────────────────── 박스 합치기 ──────────────────────────
def iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    w, h = max(0.0, x1 - x0), max(0.0, y1 - y0)
    i = w * h
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def cluster(boxes, thr):
    """
    점수 내림차순으로 훑으며 IoU >= thr 인 박스를 한 덩어리로 묶는다.
    기존 nms() 와 같은 절차다 — 그래서 'nms' 방식이 현행과 정확히 같다.
    """
    b = sorted(boxes, key=lambda x: -x[4])
    used = [False] * len(b)
    out = []
    for i in range(len(b)):
        if used[i]:
            continue
        grp = [b[i]]
        used[i] = True
        for j in range(i + 1, len(b)):
            if not used[j] and iou(b[i][:4], b[j][:4]) >= thr:
                grp.append(b[j])
                used[j] = True
        out.append(grp)
    return out


def m_nms(grp):
    return grp[0]


def m_union(grp):
    a = np.array([g[:4] for g in grp], float)
    return (float(a[:, 0].min()), float(a[:, 1].min()),
            float(a[:, 2].max()), float(a[:, 3].max()), grp[0][4])


def m_wbf(grp):
    """
    점수로 가중한 좌표 평균. 확정 운영점이다 (2026-08-31).
    점수는 덩어리 최고값을 그대로 쓴다 — 덩어리 크기로 점수를 올리면 순위가
    바뀌어 비교가 흐려진다.
    """
    a = np.array([g[:4] for g in grp], float)
    w = np.array([g[4] for g in grp], float)
    if w.sum() <= 0:
        w = np.ones_like(w)
    c = (a * w[:, None]).sum(0) / w.sum()
    return (float(c[0]), float(c[1]), float(c[2]), float(c[3]), grp[0][4])


WAYS = {"nms": m_nms, "union": m_union, "wbf": m_wbf}


def filter_tissue(boxes, tsub, frac):
    """
    조직 밖 박스를 버린다. 합치기 '전' 에 부른다.

    시연에서 'RCC' 각인 글자, 피부 마커(금속 구슬), 영상 가장자리 공기 영역에
    박스가 붙었다. 대비가 극단적이라 검출기가 끌린다. 실측으로 전체 박스의
    20.6% 가 조직 밖이었고, 거르니 오탐 1개/영상 기준 민감도가 석회 +7.4%p ·
    종괴 +7.6%p 올랐다.

    합친 뒤에 거르면 각인 박스가 이미 덩어리에 섞여 가중평균 좌표를 오염시킨
    뒤다. 그래서 앞에서 부른다.
    """
    if frac <= 0:
        return boxes, 0
    keep = []
    for b in boxes:
        x0, y0 = max(0, int(b[0])), max(0, int(b[1]))
        x1, y1 = min(tsub.shape[1], int(b[2])), min(tsub.shape[0], int(b[3]))
        if x1 > x0 and y1 > y0 and tsub[y0:y1, x0:x1].mean() >= frac:
            keep.append(b)
    return keep, len(boxes) - len(keep)


def merge_boxes_one(boxes, way, thr):
    """덩어리로 묶어 하나씩 합친다. 점수 내림차순으로 돌려준다."""
    out = [WAYS[way](g) for g in cluster(boxes, thr)]
    out.sort(key=lambda b: -b[4])
    return out


# ────────────────────────── 조각 만들기 ──────────────────────────
def expand_box(box, margin, shape):
    """
    검출 박스를 CBIS ROI 조각과 같은 크기로 넓힌다. 영상 밖은 자른다.

    여백 20px 는 measure_crop.py 로 235건을 실측해 정한 값이다 —
    마스크 상자의 각 변에 20px, 10~90퍼가 20.0~20.0, 상하 표준편차 0.00.
    """
    x0, y0, x1, y1 = [float(v) for v in box]
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    H, W = shape[:2]
    x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
    x1, y1 = min(W, int(round(x1))), min(H, int(round(y1)))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0, y0, x1, y1


def crop_to_tensor(arr, size, pad, clip):
    """
    MammoROIDataset._read_roi + _resize 와 같은 계산.

    데이터셋 객체를 쓰지 않는 이유는 그쪽이 인덱스 CSV 의 행에서 파일을 읽기
    때문이다. 여기는 메모리에 있는 조각을 받는다.
    계산이 같은지는 eval_end2end.verify_preproc() 이 실제 ROI 파일로 확인했다
    (최대 차이 0). 이 함수를 고치면 그 검증을 다시 돌려라.
    """
    a = arr.astype(np.float32)
    if clip and clip < 100:
        lo = float(np.percentile(a, 100.0 - clip))
        hi = float(np.percentile(a, clip))
        if hi <= lo:
            lo, hi = float(a.min()), float(a.max())
        a = np.clip(a, lo, hi)
    else:
        lo, hi = float(a.min()), float(a.max())
    a = (a - lo) / (hi - lo + 1e-8)

    img = torch.from_numpy(a)[None, None]
    if not pad:
        img = F.interpolate(img, size=(size, size), mode="bilinear",
                            align_corners=False)
    else:
        h, w = img.shape[-2:]
        sc = size / max(h, w)
        nh, nw = max(1, int(round(h * sc))), max(1, int(round(w * sc)))
        img = F.interpolate(img, size=(nh, nw), mode="bilinear",
                            align_corners=False)
        ph, pw = size - nh, size - nw
        top, left = ph // 2, pw // 2
        img = F.pad(img, (left, pw - left, top, ph - top), value=0.0)
    return ((img[0].repeat(3, 1, 1)) - 0.5) / 0.5


@contextlib.contextmanager
def _quiet_dicom():
    """
    pydicom 의 VR 경고를 막는다.

    왜 막나 — 경고문이 문제가 된 '값' 을 그대로 찍는다.

        UserWarning: Invalid value for VR UI: '003700f3c960e0b9bca2b8437c3dbf05'

    VinDr 은 UID 를 16진수 해시로 익명화했는데 DICOM 규격상 UID 는 숫자와
    점만 허용이라 441장 전부에서 뜬다. 익명화된 값이라 그 자체는 무해하다.
    문제는 서빙이다 — 실제 검진 영상이 들어오면 요청마다 진짜 UID 가 서버
    로그에 남는다. 우리는 UID 를 응답에만 넣기로 했다.

    화소 데이터가 잘린 파일은 경고가 아니라 예외라 이 필터에 안 걸린다.
    막는 것은 '값을 찍는 형식 경고' 뿐이다.
    """
    import logging
    import warnings
    lg = logging.getLogger("pydicom")
    lv = lg.level
    lg.setLevel(logging.ERROR)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=UserWarning,
                                    module=r"pydicom\..*")
            yield
    finally:
        lg.setLevel(lv)


def _dicom_meta(d):
    ps = getattr(d, "PixelSpacing", None) or getattr(d, "ImagerPixelSpacing", None)
    meta = dict(photometric=str(getattr(d, "PhotometricInterpretation",
                                        "MONOCHROME2")),
                laterality=str(getattr(d, "ImageLaterality", "")
                               or getattr(d, "Laterality", "")) or None,
                view=str(getattr(d, "ViewPosition", "")) or None,
                study_uid=str(getattr(d, "StudyInstanceUID", "")) or None,
                sop_uid=str(getattr(d, "SOPInstanceUID", "")) or None)
    return meta, (float(ps[0]) if ps else None)


def read_mammogram(src):
    """
    DICOM/PNG 를 2차원 배열로 읽는다. MONOCHROME1 이면 뒤집는다.
    반환 (arr, mm, meta)  — mm 은 화소 간격(없으면 None).

    src 는 경로 · bytes · 파일 객체를 받는다. bytes 를 받는 이유는 서빙에서
    업로드를 임시 파일로 떨구지 않기 위해서다 — 검진 영상을 디스크에 남기지
    않는 편이 낫고, 임시 파일 정리를 잊으면 그대로 쌓인다.

    pydicom 의 pixel_array 는 PhotometricInterpretation 을 적용하지 않는다.
    MONOCHROME1 은 '값이 작을수록 밝다' 라 그대로 쓰면 반전된 영상이고,
    조직 마스크가 공기를 조직으로 잡는다. VinDr 441장 중 73장이 그랬다.
    """
    import pydicom

    meta, mm, arr, name = {}, None, None, "<memory>"
    if isinstance(src, (bytes, bytearray, memoryview)) or hasattr(src, "read"):
        import io
        buf = io.BytesIO(bytes(src)) if not hasattr(src, "read") else src
        try:                              # DICOM 인지 아닌지는 열어 보고 정한다
            with _quiet_dicom():
                d = pydicom.dcmread(buf, force=False)
                arr = d.pixel_array
            meta, mm = _dicom_meta(d)
        except Exception:
            buf.seek(0)
            import cv2
            arr = cv2.imdecode(np.frombuffer(buf.read(), np.uint8),
                               cv2.IMREAD_UNCHANGED)
    else:
        p = Path(src)
        name = str(p)
        if p.suffix.lower() in (".dcm", ".dicom") or not p.suffix:
            with _quiet_dicom():
                d = pydicom.dcmread(str(p))
                arr = d.pixel_array
            meta, mm = _dicom_meta(d)
        else:
            import cv2
            arr = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if arr is None:
        raise ValueError(f"영상을 못 읽었다: {name}")
    if meta.get("photometric") == "MONOCHROME1":
        arr = arr.max() - arr
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.ndim != 2:
        raise ValueError(f"2차원이 아니다: {arr.shape}")
    return arr, mm, meta
