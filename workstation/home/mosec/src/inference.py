import io

import numpy as np
from PIL import Image

from . import config
from .models.base import SegmentationModel

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

_REFERENCE_STAIN_MATRIX = np.array([
    [0.5626, 0.2159],
    [0.7201, 0.8012],
    [0.4062, 0.5581],
])
_REFERENCE_MAX_CONCENTRATION = np.array([1.9705, 1.0308])
_OD_BACKGROUND_THRESHOLD = 0.15
_OD_ARTIFACT_THRESHOLD = 4.0

IGNORE = 255


def _rgb_to_od(image: np.ndarray) -> np.ndarray:
    image = image.astype(np.float64)
    image = np.clip(image, 1, 255)
    return -np.log(image / 255.0)


def _od_to_rgb(od: np.ndarray) -> np.ndarray:
    rgb = 255.0 * np.exp(-od)
    return np.clip(rgb, 0, 255).astype(np.uint8)


def compute_tissue_mask(rgb_uint8_hwc: np.ndarray) -> np.ndarray:
    h, w, _ = rgb_uint8_hwc.shape
    od = _rgb_to_od(rgb_uint8_hwc).reshape(-1, 3)
    return np.any(od > _OD_BACKGROUND_THRESHOLD, axis=1).reshape(h, w)


def _estimate_stain_matrix(image: np.ndarray, angular_percentile: float = 99.0) -> np.ndarray:
    od = _rgb_to_od(image).reshape(-1, 3)
    max_od = od.max(axis=1)
    tissue_mask = (max_od > _OD_BACKGROUND_THRESHOLD) & (max_od < _OD_ARTIFACT_THRESHOLD)
    od_tissue = od[tissue_mask]
    if od_tissue.shape[0] < 10:
        raise ValueError("조직으로 판단되는 픽셀이 너무 적음 (배경만 있는 이미지일 가능성)")
    _, eigvecs = np.linalg.eigh(np.cov(od_tissue.T))
    plane = eigvecs[:, [2, 1]]
    projected = od_tissue.dot(plane)
    phi = np.arctan2(projected[:, 1], projected[:, 0])
    min_phi = np.percentile(phi, 100 - angular_percentile)
    max_phi = np.percentile(phi, angular_percentile)
    v_min = plane.dot(np.array([np.cos(min_phi), np.sin(min_phi)]))
    v_max = plane.dot(np.array([np.cos(max_phi), np.sin(max_phi)]))
    if v_min[0] > v_max[0]:
        stain_matrix = np.stack([v_min, v_max], axis=1)
    else:
        stain_matrix = np.stack([v_max, v_min], axis=1)
    return stain_matrix / np.linalg.norm(stain_matrix, axis=0, keepdims=True)


def _get_concentrations(image: np.ndarray, stain_matrix: np.ndarray) -> np.ndarray:
    od = _rgb_to_od(image).reshape(-1, 3)
    concentrations, *_ = np.linalg.lstsq(stain_matrix, od.T, rcond=None)
    return concentrations.T


def macenko_normalize(image: np.ndarray) -> np.ndarray:
    h, w, c = image.shape
    assert c == 3, "RGB 3채널 이미지여야 함"
    source_stain_matrix = _estimate_stain_matrix(image)
    concentrations = _get_concentrations(image, source_stain_matrix)
    source_max_conc = np.maximum(np.percentile(concentrations, 99, axis=0), 1e-6)
    scaled_concentrations = concentrations * (_REFERENCE_MAX_CONCENTRATION / source_max_conc)
    normalized_od = scaled_concentrations.dot(_REFERENCE_STAIN_MATRIX.T)
    return _od_to_rgb(normalized_od.reshape(h, w, 3))


def decode_and_stain_normalize(image_bytes: bytes):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    raw_uint8 = np.asarray(img, dtype=np.uint8)
    try:
        normalized_uint8 = macenko_normalize(raw_uint8)
    except ValueError:
        normalized_uint8 = raw_uint8
    return raw_uint8, normalized_uint8


def _normalize_pixels_chw(rgb_uint8_hwc: np.ndarray) -> np.ndarray:
    arr = rgb_uint8_hwc.astype(np.float32) / 255.0
    chw = arr.transpose(2, 0, 1)
    return (chw - _MEAN) / _STD


def tile_image(rgb_uint8_hwc: np.ndarray, raw_uint8_hwc: np.ndarray = None, tile_size: int = None, stride: int = None, min_tissue_ratio: float = None):
    tile_size = tile_size or config.TILE_SIZE
    stride = stride or config.TILE_STRIDE
    min_tissue_ratio = config.MIN_TISSUE_RATIO if min_tissue_ratio is None else min_tissue_ratio
    ref_uint8_hwc = raw_uint8_hwc if raw_uint8_hwc is not None else rgb_uint8_hwc
    h, w, _ = rgb_uint8_hwc.shape
    hp, wp = max(h, tile_size), max(w, tile_size)
    if (hp, wp) != (h, w):
        pad_spec = ((0, hp - h), (0, wp - w), (0, 0))
        rgb_uint8_hwc = np.pad(rgb_uint8_hwc, pad_spec, mode="edge")
        ref_uint8_hwc = np.pad(ref_uint8_hwc, pad_spec, mode="edge")
    ys = _tile_starts(hp, tile_size, stride)
    xs = _tile_starts(wp, tile_size, stride)
    tiles = []
    for y in ys:
        for x in xs:
            od = _rgb_to_od(ref_uint8_hwc[y:y + tile_size, x:x + tile_size]).reshape(-1, 3)
            tissue_ratio = np.any(od > _OD_BACKGROUND_THRESHOLD, axis=1).mean()
            if tissue_ratio < min_tissue_ratio:
                continue
            model_tile = rgb_uint8_hwc[y:y + tile_size, x:x + tile_size]
            tiles.append((y, x, _normalize_pixels_chw(model_tile)))
    if not tiles:
        raise ValueError("조직으로 판단되는 타일이 하나도 없음 (배경 이미지일 가능성)")
    return tiles


def build_mc_batch(image_chw: np.ndarray, n: int) -> np.ndarray:
    return np.repeat(image_chw[np.newaxis, ...], n, axis=0)


def run_mc_dropout(model: SegmentationModel, image_chw: np.ndarray, n: int = None) -> np.ndarray:
    n = n or config.MC_DROPOUT_N
    batch = build_mc_batch(image_chw, n)
    logits = model.predict_logits(batch)
    masks = np.argmax(logits, axis=1).astype(np.uint8)
    return masks


def reassemble_masks(tile_results, canvas_shape: tuple, tile_size: int = None, fill_value: int = 0) -> np.ndarray:
    tile_size = tile_size or config.TILE_SIZE
    h, w = canvas_shape
    n = tile_results[0][2].shape[0]
    canvas = np.full((n, h, w), fill_value, dtype=np.uint8)
    for y, x, tile_masks in tile_results:
        if tile_masks.shape[0] != n:
            raise ValueError(
                f"타일마다 MC 샘플 수(N)가 달라짐: {n} vs {tile_masks.shape[0]} (y={y}, x={x})"
            )
        canvas[:, y:y + tile_size, x:x + tile_size] = tile_masks
    return canvas


def _softmax(logits: np.ndarray, axis: int) -> np.ndarray:
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=axis, keepdims=True)


def run_mc_dropout_tiled(
    model: SegmentationModel,
    rgb_uint8_hwc: np.ndarray,
    raw_uint8_hwc: np.ndarray = None,
    n: int = None,
    tile_size: int = None,
    stride: int = None,
    batch: int = 8,
) -> np.ndarray:
    n = n or config.MC_DROPOUT_N
    tile_size = tile_size or config.TILE_SIZE
    stride = stride or config.TILE_STRIDE
    h, w, _ = rgb_uint8_hwc.shape
    hp, wp = max(h, tile_size), max(w, tile_size)
    tiles = tile_image(rgb_uint8_hwc, raw_uint8_hwc=raw_uint8_hwc, tile_size=tile_size, stride=stride)
    ref = raw_uint8_hwc if raw_uint8_hwc is not None else rgb_uint8_hwc
    tissue_mask = compute_tissue_mask(ref)
    preds = np.empty((n, h, w), dtype=np.uint8)
    for k in range(n):
        prob_sum = np.zeros((config.NUM_CLASSES, hp, wp), dtype=np.float32)
        count = np.zeros((hp, wp), dtype=np.float32)
        for i in range(0, len(tiles), batch):
            chunk = tiles[i:i + batch]
            tile_batch = np.stack([tile_chw for _, _, tile_chw in chunk])
            logits = model.predict_logits(tile_batch)
            probs = _softmax(logits, axis=1)
            for (y, x, _), tile_prob in zip(chunk, probs):
                prob_sum[:, y:y + tile_size, x:x + tile_size] += tile_prob
                count[y:y + tile_size, x:x + tile_size] += 1.0
        prob_avg = prob_sum / np.maximum(count, 1.0)
        preds[k] = prob_avg[:, :h, :w].argmax(axis=0).astype(np.uint8)
        preds[k][~tissue_mask] = IGNORE
    return preds


def pack_masks(masks: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, masks=masks)
    return buf.getvalue()


def unpack_masks(data: bytes) -> np.ndarray:
    buf = io.BytesIO(data)
    with np.load(buf) as npz:
        return npz["masks"]


def _tile_starts(size: int, patch: int, stride: int):
    if size <= patch:
        return [0]
    starts = list(range(0, size - patch + 1, stride))
    if starts[-1] != size - patch:
        starts.append(size - patch)
    return starts


from google.cloud import storage

_gcs_client = None


def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        _gcs_client = storage.Client()
    return _gcs_client


def download_gcs_bytes(gcs_path: str) -> bytes:
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"gcs_image_path는 gs://로 시작해야 함: {gcs_path!r}")
    bucket_name, _, blob_name = gcs_path[len("gs://"):].partition("/")
    if not bucket_name or not blob_name:
        raise ValueError(f"gcs_image_path 형식이 잘못됨: {gcs_path!r}")
    client = _get_gcs_client()
    blob = client.bucket(bucket_name).blob(blob_name)
    return blob.download_as_bytes()


_MASK_CLASS_COLORS = {
    0: (230, 25, 75),    # tumor
    1: (60, 180, 75),    # stroma
    2: (255, 225, 25),   # immune
    3: (0, 130, 200),    # necrosis
    4: (128, 128, 128),  # other
}


def consensus_mask(masks: np.ndarray) -> np.ndarray:
    """MC 스택 (N,H,W) -> 다수결 마스크 (H,W).

    worker의 til_conformal.py class_composition()과 동일한 로직 — 과반 득표가
    없는 픽셀(즉 20회 중 절반 이상이 IGNORE였던 픽셀)은 IGNORE로 유지한다.
    프론트엔드 오버레이용 단일 마스크 이미지를 만들기 위해 추가됨 (2026-08-05).
    """
    n_pass = masks.shape[0]
    votes = np.zeros((config.NUM_CLASSES,) + masks.shape[1:], dtype=np.uint16)
    for k in range(n_pass):
        frame = masks[k]
        for idx in range(config.NUM_CLASSES):
            votes[idx] += (frame == idx)
    valid = votes.sum(axis=0) * 2 > n_pass
    consensus = votes.argmax(axis=0).astype(np.uint8)
    consensus[~valid] = IGNORE
    return consensus


def render_mask_png(consensus: np.ndarray) -> bytes:
    """다수결 마스크(H,W) -> 클래스별로 색칠된 RGBA PNG.

    IGNORE(비조직) 픽셀은 완전 투명(alpha=0)으로 처리한다 — 프론트엔드가
    원본 조직 이미지 위에 겹쳐도 배경(비조직 영역)이 안 가려지게 하기 위함.
    """
    h, w = consensus.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for cls, color in _MASK_CLASS_COLORS.items():
        rgb[consensus == cls] = color
    alpha = np.where(consensus == IGNORE, 0, 255).astype(np.uint8)
    rgba = np.dstack([rgb, alpha])
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload_gcs_bytes(gcs_path: str, data: bytes, content_type: str = "image/png") -> None:
    """download_gcs_bytes()의 반대 — 바이트를 GCS에 올린다.

    ⚠️ worker-gcs-reader 서비스 계정은 masks/ 경로에 "생성(create)"만 가능하고
       "삭제(delete)"는 못 한다(최소 권한 원칙). GCS는 기본적으로 업로드를
       "덮어쓰기일 수도 있는 작업"으로 취급해서 delete 권한까지 요구하므로,
       if_generation_match=0으로 "이 이름이 아직 없을 때만 생성"이라고 명시해서
       delete 권한 없이도 순수 생성만으로 처리되게 한다.

       같은 job_id로 이미 한 번 업로드된 적 있으면(재테스트 등) 412 Precondition
       Failed가 나는데, 이미 파일이 있다는 뜻이라 에러로 취급하지 않는다.
    """
    if not gcs_path.startswith("gs://"):
        raise ValueError(f"gcs_path는 gs://로 시작해야 함: {gcs_path!r}")
    bucket_name, _, blob_name = gcs_path[len("gs://"):].partition("/")
    if not bucket_name or not blob_name:
        raise ValueError(f"gcs_path 형식이 잘못됨: {gcs_path!r}")
    client = _get_gcs_client()
    blob = client.bucket(bucket_name).blob(blob_name)
    try:
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
    except Exception as exc:
        if "412" in str(exc) or "Precondition Failed" in str(exc):
            return  # 이미 같은 이름으로 존재함 — 실패가 아니라 "할 필요 없음"
        raise
