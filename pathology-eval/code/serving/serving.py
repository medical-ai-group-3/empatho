"""
sTIL 파이프라인 서빙 래퍼.

서버 담당자 인터페이스:

    from serving import load_model, predict

    bundle = load_model(config)        # 서버 기동 시 1회 (모델 4종 로드, 수십 초 걸림)
    result = predict(bundle, image)    # 요청마다 (이미지 1장 -> dict)

`image` 는 파일 경로(str/Path), RGB ndarray(H,W,3 uint8), 또는 PIL.Image.

내부적으로 `code/stil_inference_pipeline.py` 의 로직을 그대로 재사용한다
(중복 구현 없음). 파이프라인 상세·한계는 `docs/stil_pipeline_limitations.md` 참고.

CLI (단독 실행, 이미지 1장 자가 테스트용 — 서버 코드는 위 API 를 직접 import 할 것)

    python3 serving.py --image a.png

주의:
  - torch 를 cupy 보다 먼저 import 해야 한다. cupy(12.x wheel)는 torch 가 올려둔
    nvidia-cuda-runtime-cu12 의 libcudart.so.12 에 의존한다. 이 모듈은 순서를 지킨다.
  - Virchow2 는 gated HF 모델. 최초 로드 시 ~/.cache/huggingface 에 없으면
    HF_TOKEN(또는 `huggingface-cli login`)이 필요하다. MANIFEST.md 참고.
  - ⚠ 체크포인트 경로 4종이 전부 `~/models/cellvitpp/...` 로 하드코딩돼 있다
    (DEFAULT_CONFIG, 아래) — 이 서버 특정 계정의 홈 디렉터리 기준이며 다른 서버에서는
    거의 확실히 존재하지 않는다. 배포 시 반드시 `config` 로 4개 경로(tissue_checkpoint,
    cell_head, cellvit_path) 를 덮어쓰고 `CELLVIT_REPO` 환경변수로 CellViT-plus-plus
    패키지 위치를 지정할 것. 안 하면 load_model() 이 FileNotFoundError/RuntimeError 로
    바로 실패한다(조용히 잘못된 걸 로드하지는 않음). 전체 목록·이유는 MANIFEST.md §2.
  - ⚠ predict() 가 돌려주는 stil_percent 는 절대값이 아니다 — 임상 육안 TIL 스코어 대비
    ~12배 낮게 나오도록 검증됐다(캘리브 안 된 상태). 화면에 그대로 노출하지 말 것.
    자세한 사유·캘리브 계수는 반환 dict 의 필드별 주석과 `docs/stil_pipeline_limitations.md`
    §2-6, §2-8 참고.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import torch  # cupy 보다 먼저 (libcudart.so.12 로드 순서)
import torch.nn.functional as F
from PIL import Image

_CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../code
# CellViT-plus-plus 패키지 위치. 서버에서 다르면 CELLVIT_REPO 환경변수로 지정.
# (stil_inference_pipeline / extract_socket2_tokens 도 ~/models/cellvitpp 를 하드코딩하지만
#  여기서 먼저 유효 경로를 sys.path 에 넣으므로 cellvit import 는 이 경로로 해결된다.)
_REPO_ROOT = os.environ.get("CELLVIT_REPO", os.path.expanduser("~/models/cellvitpp"))
for _p in (_CODE_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if not os.path.isdir(os.path.join(_REPO_ROOT, "cellvit")):
    raise RuntimeError(
        f"CellViT-plus-plus 패키지를 찾을 수 없음: {_REPO_ROOT}\n"
        f"  CellViT-plus-plus 체크아웃을 여기에 두거나 CELLVIT_REPO 환경변수로 지정하세요.")

import extract_socket2_tokens as e2  # noqa: E402  (DEDUP_RADIUS 등 모듈 상수 조정용)
import stil_inference_pipeline as sip  # noqa: E402
from cellvit.inference.postprocessing_cupy import DetectionCellPostProcessorCupy  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 기본 설정 — 모든 값은 config 로 덮어쓸 수 있다. 서버에서 바꿀 만한 것:
#   경로 4종(체크포인트), gpu, fp16, 임계값들.
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG: dict = {
    # --- 체크포인트 경로 (MANIFEST.md 의 checksums 와 일치해야 함) ---
    "tissue_checkpoint": os.path.expanduser(
        "~/models/cellvitpp/logs_local/virchow2_linear_tand/best_head.pth"),
    "cell_head":         os.path.expanduser(
        "~/pathology-eval/candidates/socket2/model_best.pth"),
    "cellvit_path":      os.path.join(_REPO_ROOT, "checkpoints", "CellViT-SAM-H-x40-AMP.pth"),
    # Virchow2 인코더는 timm 이 HF 허브에서 받음 (파일 경로 아님)
    "virchow2_hf_repo":  "paige-ai/Virchow2",

    # --- 실행 환경 ---
    "gpu": 0,                 # cuda:N (GPU 전용 — CellViT-SAM-H + cupy postproc)
    "fp16": False,            # True 면 가중치 half — 저VRAM(공유 GPU) 환경용
    "batch_size": 4,          # 큰 이미지 타일 추론 배치. OOM 시 낮추면 됨(자동 폴백도 있음)

    # --- 조정 가능한 임계값 (MANIFEST.md §4) ---
    "til_threshold": 0.5,     # P(TIL) >= 이 값이면 면역세포로 카운트
    "nc_ratio": 1.5,          # 핵면적 -> 세포면적 보정계수 (한계 2-1)
    "mpp": 0.5,               # µm/px. sTIL 비율엔 무관, µm² 환산·sanity 용
    # --- 1.1.0 (09-28) 조직분할 타일링 · 면역세포 영역 분자 ---
    #   tissue_tile: 크롭을 224 로 통째로 줄이지 않고 원본 배율 타일(반 겹침)로
    #     판정 → 로짓 평균 → bilinear 확대. 0 이면 1.0.0 처럼 축소 1장.
    #     BCSS 151장(큰 ROI): 간질 Dice 0.548 → 0.762, 순위상관 0.63 → 0.76.
    #     ⚠ BCSS 124장은 TIGER 와 같은 환자·영역(학습에 조각으로 들어감). 처음 본 27장만:
    #       순위상관 0.66 → 0.70, 평균오차 14.6 → 13.4 (핵 면적식 → 1.1.0).
    #   til_region_radius_um: 분자를 핵 면적 × nc_ratio 대신 「간질 안 면역세포
    #     주변 반경 r 영역」 면적으로 잰다(병리의 면적 단위 판단에 맞춤). 0 이면 1.0.0 식.
    #     BCSS: 반경 4µm 평균오차 10.9 · 6µm 11.3 (핵 면적식 16.2) → 5µm.
    #   면적 분자는 MC 구간을 내지 않는다(stil_interval_* = None).
    "tissue_tile": 224,
    "til_region_radius_um": 5.0,
    # --- 1.2.0 (09-29) 유리 가리기 ---
    #   빈 유리 · 큰 내강이 간질로 칠해져 분모가 부풀었다(학습 크롭은 작고 조직으로
    #   꽉 차 있어 유리를 거의 못 봤다). 밝고(max RGB ≥ v) · 채도가 낮고(≤ s) ·
    #   **결이 없는**(9×9 밝기 표준편차 ≤ sd) 픽셀 덩어리 가운데 min_um2 이상만
    #   기타(0)로 덮어쓴다.
    #   ⚠ 결 조건이 핵심이다. 밝기 · 채도만 보면(220/0.10) 성긴 간질(부종성 ·
    #     림프구가 흩어진 곳)이 통째로 유리로 잡혔다 — BCSS GT 간질의 0.85%,
    #     눈으로 보면 TIL 이 있는 간질이 지워졌다. 유리는 섬유도 핵도 없이 매끈하다.
    #   BCSS 151장(0.5 µm/px): 235/0.06/sd4/8000 → GT 간질 0.007% · 종양 0.001% · 림프 0%.
    #   glass_min_um2 = 0 이면 끈다.
    "glass_v_min": 235,
    "glass_s_max": 0.06,
    "glass_sd_max": 4.0,
    "glass_min_um2": 8000.0,
    "mc_samples": 50,         # MC Dropout 반복 횟수 (0 이면 구간 계산 안 함)
    "mc_drop_rate": 0.5,      # 소켓2 헤드 학습 시 drop_rate (= 0.5, 바꾸지 말 것)
    "mc_ci": 95.0,            # 신뢰구간 % -> 2.5/97.5 백분위수
    "dedup_radius": 10.0,     # 타일 경계 중복 세포 제거 반경 (px, 원본해상도)
    "tile_overlap": 64,       # 큰 이미지 타일링 overlap (px)
    "pair_dist": 15.0,        # (학습 전용 상수, 추론엔 미사용) GT 페어링 거리

    # --- 반환 옵션 ---
    "return_tissue_mask": True,   # False 면 result["tissue_mask"] = None (페이로드 절감)
    "verify_checksums": True,     # load_model 시 체크포인트 sha256 확인 (2.7G 파일 포함, ~15s)
}

TISSUE_MASK_LEGEND = {0: "other", 1: "tumor", 2: "stroma"}

# model_version 에 박히는 파이프라인 정의 버전. 로직/공식이 바뀌면 올린다.
PIPELINE_VERSION = "stil-serving-1.2.0"


# ─────────────────────────────────────────────────────────────────────────────
def _sha256(path: str, quick: bool = False) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        if quick:  # 앞 8MB 만 (대용량 파일 빠른 식별용)
            h.update(f.read(8 << 20))
            return "quick8m:" + h.hexdigest()
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit(repo_dir: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", repo_dir, "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def _virchow2_hf_revision(repo: str) -> dict:
    """HF 캐시에서 Virchow2 스냅샷 revision 과 safetensors sha256 을 뽑는다."""
    info = {"repo": repo, "revision": None, "model_safetensors_sha256": None}
    cache = Path(os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface"))) / "hub"
    d = cache / f"models--{repo.replace('/', '--')}"
    snaps = d / "snapshots"
    if snaps.is_dir():
        revs = sorted(snaps.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        if revs:
            info["revision"] = revs[0].name
            st = revs[0] / "model.safetensors"
            if st.exists():
                info["model_safetensors_sha256"] = _sha256(str(st.resolve()))
    return info


def _resolve_config(config: dict | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if config:
        unknown = set(config) - set(DEFAULT_CONFIG)
        if unknown:
            raise ValueError(f"알 수 없는 config 키: {sorted(unknown)}")
        cfg.update(config)
    return cfg


def _gpu_mem_mb(device: str) -> dict:
    if not device.startswith("cuda"):
        return {}
    idx = int(device.split(":")[1]) if ":" in device else 0
    free, total = torch.cuda.mem_get_info(idx)
    return {
        "device": device,
        "allocated_mb": round(torch.cuda.memory_allocated(idx) / 1e6, 1),
        "reserved_mb": round(torch.cuda.memory_reserved(idx) / 1e6, 1),
        "free_mb": round(free / 1e6, 1),
        "total_mb": round(total / 1e6, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
def load_model(config: dict | None = None) -> dict:
    """모델 4종(Virchow2 + linear_tand head + CellViT-SAM-H + weighted classifier)을
    메모리에 올리고 bundle(dict) 을 돌려준다. 서버 기동 시 1회만 호출.

    Raises:
        FileNotFoundError: 체크포인트 누락
        ValueError: config.verify_checksums=True 인데 sha256 불일치, 또는 알 수 없는 키
    """
    cfg = _resolve_config(config)
    t0 = time.perf_counter()

    if int(cfg["gpu"]) < 0 or not torch.cuda.is_available():
        raise RuntimeError(
            "이 파이프라인은 GPU 전용입니다 (CellViT-SAM-H + cupy postproc). "
            "CUDA 가용 GPU 와 config['gpu'] >= 0 이 필요합니다.")
    device = f"cuda:{int(cfg['gpu'])}"

    # 조정 가능 모듈 상수 주입 (extract_socket2_tokens 는 상수를 전역으로 씀)
    e2.DEDUP_RADIUS = float(cfg["dedup_radius"])
    e2.OVERLAP = int(cfg["tile_overlap"])
    e2.PAIR_DIST = float(cfg["pair_dist"])

    # --- 체크포인트 존재 확인 ---
    ckpt_paths = {
        "tissue_head": cfg["tissue_checkpoint"],
        "cell_classifier": cfg["cell_head"],
        "cellvit_sam": cfg["cellvit_path"],
    }
    missing = [f"{k}={v}" for k, v in ckpt_paths.items() if not Path(v).is_file()]
    if missing:
        raise FileNotFoundError("체크포인트 누락: " + "; ".join(missing))

    # --- sha256 (선택) ---
    EXPECTED_SHA = {  # MANIFEST.md / checksums.sha256 와 동일
        "tissue_head": "eacbd8de14a1bbfe0c536597d41546c6b6f95c94ef1fdd565f7e136e60f9a730",
        "cell_classifier": "e54f5c8ec452bd5afd2ebf3490cf8775e304ba17e311f8c7441b3fb07e5e7bfe",
        "cellvit_sam": "356418f19d9d478f164c7a31f85274584fefaa02355815c09f52346c658c8ec4",
    }
    checkpoints_meta = {}
    for k, v in ckpt_paths.items():
        sha = _sha256(v, quick=not cfg["verify_checksums"])
        if cfg["verify_checksums"] and sha != EXPECTED_SHA[k]:
            raise ValueError(
                f"체크포인트 sha256 불일치 [{k}] {v}\n  기대 {EXPECTED_SHA[k]}\n  실제 {sha}")
        checkpoints_meta[k] = {"path": v, "bytes": Path(v).stat().st_size, "sha256": sha}

    # --- 모델 로드 (Virchow2 -> tissue head -> CellViT-SAM-H -> classifier) ---
    tissue_model, mean, std, image_size = sip.load_tissue_model(
        cfg["tissue_checkpoint"], device, fp16=bool(cfg["fp16"]))

    cellvit, _ = e2.load_model(cfg["cellvit_path"], int(cfg["gpu"]) if device != "cpu" else 0)
    if cfg["fp16"]:
        cellvit.half()
    if device == "cpu":
        cellvit.to("cpu")

    postproc = DetectionCellPostProcessorCupy(wsi=None, nr_types=e2.NR_TYPES)

    do_mc = int(cfg["mc_samples"]) > 0
    head = sip.load_cell_classifier(
        cfg["cell_head"], device, mc_dropout=do_mc, drop_rate=float(cfg["mc_drop_rate"]))

    model_version = {
        "pipeline_version": PIPELINE_VERSION,
        "pipeline_git_commit": _git_commit(_CODE_DIR),
        "cellvit_pkg_git_commit": _git_commit(_REPO_ROOT),
        "torch": torch.__version__,
        "device": device,
        "fp16": bool(cfg["fp16"]),
        "checkpoints": checkpoints_meta,
        "virchow2_hf": _virchow2_hf_revision(cfg["virchow2_hf_repo"]),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }

    bundle = {
        "cfg": cfg,
        "device": device,
        "do_mc": do_mc,
        "tissue_model": tissue_model,
        "tissue_norm": (mean, std, image_size),
        "cellvit": cellvit,
        "postproc": postproc,
        "head": head,
        "model_version": model_version,
        "load_seconds": round(time.perf_counter() - t0, 1),
        "gpu_mem_after_load": _gpu_mem_mb(device),
    }
    return bundle


# ─────────────────────────────────────────────────────────────────────────────
def _to_pil_and_np(image) -> tuple[Image.Image, np.ndarray]:
    if isinstance(image, (str, Path)):
        pil = Image.open(image).convert("RGB")
    elif isinstance(image, Image.Image):
        pil = image.convert("RGB")
    elif isinstance(image, np.ndarray):
        arr = image
        if arr.ndim == 2:
            arr = np.stack([arr] * 3, -1)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        pil = Image.fromarray(arr[:, :, :3], "RGB")
    else:
        raise TypeError(f"지원하지 않는 image 타입: {type(image)} (경로/ndarray/PIL 만)")
    return pil, np.asarray(pil, dtype=np.uint8)


def _glass_mask(img_np: np.ndarray, mpp: float, v_min: int, s_max: float,
                min_um2: float, sd_max: float = 4.0) -> np.ndarray:
    """빈 유리 · 큰 내강 — 밝고 채도 낮은 픽셀의 큰 덩어리. (H,W) bool.

    원본 픽셀로 판정하므로 타일 모양으로 각지지 않는다. 결(9×9 표준편차)이
    있는 곳은 성긴 간질이라 뺀다. 3×3 열기로 잡티를 떼고 min_um2 보다 작은
    덩어리(지방 틈 · 핵 주변 빈틈)는 남긴다.
    """
    mx = img_np.max(2)
    diff = mx.astype(np.int16) - img_np.min(2)
    raw = (mx >= v_min) & (diff <= (s_max * mx.astype(np.float32)))
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY).astype(np.float32)
    mu = cv2.blur(gray, (9, 9))
    var = cv2.blur(gray * gray, (9, 9)) - mu * mu
    raw = (raw & (var <= sd_max * sd_max)).astype(np.uint8)
    del gray, mu, var
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(raw, 8)
    keep = st[:, cv2.CC_STAT_AREA] >= min_um2 / (mpp * mpp)
    keep[0] = False
    return keep[lab]


def _starts(L: int, T: int) -> list[int]:
    if L <= T:
        return [0]
    xs = list(range(0, L - T + 1, T // 2))
    return xs if xs[-1] == L - T else xs + [L - T]


@torch.inference_mode()
def _tissue_mask_tiled(model, pil, mean, std, image_size, device, tile, batch=64):
    """원본 배율 tile px 타일 · 반 겹침 → 칸 로짓(16x16)을 타일 크기로 bilinear →
    겹친 자리 평균 → argmax. 반환 (H,W) uint8 0/1/2.
    작은 크롭은 흰 배경으로 채워 타일 1장이 된다."""
    W, H = pil.size
    PW, PH = max(W, tile), max(H, tile)
    pad = Image.new("RGB", (PW, PH), (255, 255, 255))
    pad.paste(pil)
    mt = torch.tensor(mean).view(3, 1, 1)
    st = torch.tensor(std).view(3, 1, 1)
    dtype = next(model.parameters()).dtype
    pos = [(x, y) for y in _starts(PH, tile) for x in _starts(PW, tile)]
    acc = torch.zeros(3, PH, PW, device=device)
    cnt = torch.zeros(1, PH, PW, device=device)
    for i in range(0, len(pos), batch):
        b = pos[i:i + batch]
        t = torch.stack([
            (torch.from_numpy(np.array(pad.crop((x, y, x + tile, y + tile))
                                       .resize((image_size, image_size), Image.BILINEAR)))
             .permute(2, 0, 1).float() / 255.0 - mt) / st
            for x, y in b]).to(device, dtype)
        lg = F.interpolate(model(t).float(), size=(tile, tile), mode="bilinear", align_corners=False)
        for (x, y), l in zip(b, lg):
            acc[:, y:y + tile, x:x + tile] += l
            cnt[:, y:y + tile, x:x + tile] += 1
    return (acc / cnt)[:, :H, :W].argmax(0).cpu().numpy().astype(np.uint8)


@torch.inference_mode()
def predict(bundle: dict, image, *, return_tissue_mask: bool | None = None) -> dict:
    """이미지 1장 -> sTIL 결과 dict. 스레드 안전하지 않음(단일 워커/큐 가정).

    반환 키: stil_percent, stil_interval_low, stil_interval_high, stil_mc_mean,
      stil_mc_std, mc_samples, tsr_tumor_percent, tsr_stroma_percent, stroma_status,
      n_cells_total, n_cells_til, n_cells_til_stromal, tumor_area_px, stroma_area_px,
      immune_nucleus_area_px, immune_cell_area_px, img_w, img_h, mpp, nc_ratio,
      til_threshold, tissue_mask, tissue_mask_legend, predict_seconds, model_version
      — 화면 노출 시 주의할 필드는 아래 return dict 옆 주석 참고
      (특히 stil_percent 절대값, stil_interval_* 의 "신뢰구간" 오독 위험).

    ⚠ tissue_mask 는 numpy ndarray(H,W) 라 그대로 JSON 직렬화가 안 된다.
      호출부에서 .tolist() 로 변환하거나 pop 해서 별도 저장할 것 — 필요 없으면
      애초에 predict(..., return_tissue_mask=False) 로 요청해 페이로드도 줄이는 편이 낫다.
    """
    cfg = bundle["cfg"]
    device = bundle["device"]
    do_mc = bundle["do_mc"]
    mean, std, image_size = bundle["tissue_norm"]
    tissue_model, cellvit, postproc, head = (
        bundle["tissue_model"], bundle["cellvit"], bundle["postproc"], bundle["head"])
    thr = float(cfg["til_threshold"])
    nc_ratio = float(cfg["nc_ratio"])
    want_mask = cfg["return_tissue_mask"] if return_tissue_mask is None else return_tissue_mask

    t0 = time.perf_counter()
    pil, img_np = _to_pil_and_np(image)
    H, W = img_np.shape[:2]

    # 1) 조직분할 -> 간질/종양 마스크 (소켓1)
    tile = int(cfg["tissue_tile"])
    if tile > 0:
        mask = _tissue_mask_tiled(tissue_model, pil, mean, std, image_size, device, tile)
    else:
        mask, _pred16 = sip.tissue_stroma_mask(
            tissue_model, pil, mean, std, image_size, device, W, H)
    # 1-1) 유리 가리기 (1.2.0) — 간질 · 종양으로 칠해진 빈 유리를 기타로
    glass_px = stroma_on_glass_px = 0
    if float(cfg["glass_min_um2"]) > 0:
        g = _glass_mask(img_np, float(cfg["mpp"]), int(cfg["glass_v_min"]),
                        float(cfg["glass_s_max"]), float(cfg["glass_min_um2"]),
                        float(cfg["glass_sd_max"]))
        glass_px = int(g.sum())
        stroma_on_glass_px = int((g & (mask == sip.STROMA_CLASS_IDX)).sum())
        mask[g] = 0
        del g
    stroma_area_px = int((mask == sip.STROMA_CLASS_IDX).sum())
    tumor_area_px = int((mask == sip.TUMOR_CLASS_IDX).sum())
    stroma_ok = stroma_area_px > 0

    # 2) TSR (사양서 Q6 미확정 -> 두 관점 다)
    tsr_denom = tumor_area_px + stroma_area_px
    tsr_tumor = (tumor_area_px / tsr_denom * 100) if tsr_denom > 0 else None
    tsr_stroma = (stroma_area_px / tsr_denom * 100) if tsr_denom > 0 else None

    # 3) 세포 검출 + 분류 (소켓2). 점추정은 dropout off.
    if do_mc:
        head.dropout.eval()
    cells, T_kept = sip.detect_and_classify(
        img_np, cellvit, postproc, head, device, int(cfg["batch_size"]), return_tokens=True)
    immune = [c for c in cells if c["p_til"] >= thr]
    intra = [c for c in immune
             if mask[min(int(c["cy"]), H - 1), min(int(c["cx"]), W - 1)] == sip.STROMA_CLASS_IDX]
    immune_nuc_px = float(sum(c["area_px"] for c in intra))
    immune_cell_px = immune_nuc_px * nc_ratio

    stil_nucleus_percent = (immune_cell_px / stroma_area_px * 100) if stroma_ok else None
    radius_um = float(cfg["til_region_radius_um"])
    immune_region_px = None
    if radius_um > 0 and stroma_ok:
        r_px = max(1, int(round(radius_um / float(cfg["mpp"]))))
        disk = np.zeros((H, W), np.uint8)
        for c in intra:
            cv2.circle(disk, (int(c["cx"]), int(c["cy"])), r_px, 1, -1)
        immune_region_px = int(((disk > 0) & (mask == sip.STROMA_CLASS_IDX)).sum())
        stil_percent = immune_region_px / stroma_area_px * 100
        do_mc = False   # 면적 분자는 MC 구간을 내지 않는다
    else:
        stil_percent = stil_nucleus_percent

    # 4) MC Dropout v1: 소켓2 분류 불확실성 -> stil 구간 (조직분할 불확실성은 제외; 한계 2-8)
    stil_lo = stil_hi = stil_mc_mean = stil_mc_std = None
    if do_mc and stroma_ok and T_kept is not None and len(cells) > 0:
        ci_lo, ci_hi = (100 - cfg["mc_ci"]) / 2, 100 - (100 - cfg["mc_ci"]) / 2
        head.dropout.train()
        mc_p = sip.mc_ptil_samples(head, T_kept, int(cfg["mc_samples"]))  # (S, N)
        areas = np.array([c["area_px"] for c in cells], dtype=np.float64)
        yy = np.clip([int(c["cy"]) for c in cells], 0, H - 1)
        xx = np.clip([int(c["cx"]) for c in cells], 0, W - 1)
        in_stroma = (mask[yy, xx] == sip.STROMA_CLASS_IDX)
        num_px = (areas[None, :] * (mc_p >= thr) * in_stroma[None, :]).sum(axis=1)
        stil_s = num_px * nc_ratio / stroma_area_px * 100
        stil_lo, stil_hi = (float(x) for x in np.percentile(stil_s, [ci_lo, ci_hi]))
        stil_mc_mean, stil_mc_std = float(stil_s.mean()), float(stil_s.std())
        head.dropout.eval()

    def _r(x, n=2):
        return round(x, n) if x is not None else None

    return {
        # ⚠ stil_percent 는 화면·소견문에서 'AI 계측값'으로만 표시. 보정계수 적용 금지
        #   (크롭 값에 곱하면 100% 초과). 임상 sTIL 은 병리의 직접 입력
        #   (specimen.stil_calibrated, stil_source='manual').
        "stil_percent": _r(stil_percent),
        # 1.1.0 — stil_percent 는 면역세포 주변 영역 기준. 1.0.0 식(핵 면적 × nc_ratio)은 참고로 남긴다
        "stil_nucleus_percent": _r(stil_nucleus_percent),
        "immune_region_area_px": immune_region_px,
        "til_region_radius_um": radius_um,
        "tissue_tile": tile,
        # ⚠ "신뢰구간"으로 표기 금지 — 소켓2 분류기 재현성 하한일 뿐, 조직분할·검출·
        #   캘리브레이션 불확실성은 미포함(§2-8). UI 라벨은 "재현성 범위" 등으로.
        "stil_interval_low": _r(stil_lo),
        "stil_interval_high": _r(stil_hi),
        "stil_mc_mean": _r(stil_mc_mean),         # 참고용 — 점추정(stil_percent)과 다른 축
        "stil_mc_std": _r(stil_mc_std, 3),        # 참고용 — 위와 동일 주의
        "mc_samples": int(cfg["mc_samples"]) if do_mc else 0,

        "tsr_tumor_percent": _r(tsr_tumor),
        "tsr_stroma_percent": _r(tsr_stroma),

        "stroma_status": "ok" if stroma_ok else "absent",
        "n_cells_total": len(cells),
        "n_cells_til": len(immune),
        "n_cells_til_stromal": len(intra),
        "tumor_area_px": tumor_area_px,
        "stroma_area_px": stroma_area_px,
        # 1.2.0 — 유리로 판정해 기타로 덮은 면적과, 그중 모델이 간질로 칠했던 면적.
        #   stroma_on_glass_px / (stroma_area_px + stroma_on_glass_px) 가 크면
        #   분할이 유리를 간질로 많이 읽은 크롭이다(신뢰도 판단에 쓸 수 있다)
        "glass_area_px": glass_px,
        "stroma_on_glass_px": stroma_on_glass_px,
        "immune_nucleus_area_px": _r(immune_nuc_px, 1),
        "immune_cell_area_px": _r(immune_cell_px, 1),

        "img_w": W, "img_h": H,
        "mpp": float(cfg["mpp"]),
        "nc_ratio": nc_ratio,
        "til_threshold": thr,

        # ⚠ numpy ndarray(H,W) uint8 0/1/2 — JSON 직렬화 전에 반드시 pop 하거나
        #   .tolist() 로 변환할 것(그대로 json.dumps 하면 TypeError). 필요 없으면
        #   predict(..., return_tissue_mask=False) 로 애초에 안 받는 게 낫다.
        "tissue_mask": (mask if want_mask else None),
        "tissue_mask_legend": TISSUE_MASK_LEGEND,

        "predict_seconds": round(time.perf_counter() - t0, 2),
        "model_version": bundle["model_version"],
    }


# ────────────────────────────── CLI ──────────────────────────────
# 이미지 1장을 단독으로 돌려볼 때 쓴다(자가 테스트/디버깅용). 서버 코드는 이 CLI 를
# 거치지 않고 load_model()/predict() 를 직접 import 해서 쓴다(모듈 상단 docstring 참고).
def main():
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--image", default=None,
                    help="이미지 경로. 생략하면 랜덤 이미지로 파이프라인만 자가 테스트")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "infer_out"))
    ap.add_argument("--gpu", type=int, default=DEFAULT_CONFIG["gpu"])
    ap.add_argument("--fp16", action="store_true",
                    default=bool(int(os.getenv("FP16", "0"))),
                    help="저VRAM(공유 GPU) 모드 — 가중치 half")
    ap.add_argument("--no-verify-checksums", dest="verify_checksums",
                    action="store_false", default=True,
                    help="체크포인트 sha256 확인 생략(로딩 ~15s 단축)")
    ap.add_argument("--til-threshold", type=float, default=None)
    ap.add_argument("--mc-samples", type=int, default=None,
                    help="MC Dropout 반복 횟수(0 이면 구간 계산 안 함)")
    ap.add_argument("--no-tissue-mask", dest="return_tissue_mask",
                    action="store_false", default=True,
                    help="tissue_mask PNG 저장 생략(페이로드/시간 절감)")
    a = ap.parse_args()

    cfg = {"gpu": a.gpu, "fp16": a.fp16, "verify_checksums": a.verify_checksums}
    if a.til_threshold is not None:
        cfg["til_threshold"] = a.til_threshold
    if a.mc_samples is not None:
        cfg["mc_samples"] = a.mc_samples

    if a.image:
        img_path = Path(a.image).resolve()
        if not img_path.exists():
            sys.exit(f"없는 경로: {img_path}")
        image, stem = img_path, img_path.stem
    else:
        rng = np.random.default_rng(0)
        image = rng.integers(160, 230, (1024, 1024, 3), dtype=np.uint8)
        stem = "self_test"

    print("모델이 로딩 중 입니다.")
    b = load_model(cfg)
    print(f"로딩 완료. {b['load_seconds']}s  {b['gpu_mem_after_load']}")

    r = predict(b, image, return_tissue_mask=a.return_tissue_mask)

    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # tissue_mask 는 numpy 라 JSON 직렬화 전에 반드시 뺀다(위 predict() docstring 참고).
    mask = r.pop("tissue_mask", None)
    if mask is not None:
        mask_path = out_dir / f"{stem}_tissue_mask.png"
        Image.fromarray((mask * 120).astype(np.uint8)).save(mask_path)  # 0/1/2 -> 보기 좋게 스케일
        r["tissue_mask_png"] = mask_path.name

    json_path = out_dir / f"{stem}.json"
    json_path.write_text(
        json.dumps({k: v for k, v in r.items() if k != "model_version"},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"stil_percent {r['stil_percent']} (⚠ 비보정 — 절대값 아님, §2-6)"
          f"  ·  재현성범위 [{r['stil_interval_low']}, {r['stil_interval_high']}] (신뢰구간 아님, §2-8)")
    print(f"  세포 {r['n_cells_total']}개 (TIL {r['n_cells_til']}개, 간질내 {r['n_cells_til_stromal']}개)"
          f"  ·  간질상태 {r['stroma_status']}")
    print(f"  TSR 종양 {r['tsr_tumor_percent']}% · 간질 {r['tsr_stroma_percent']}%")
    print(f"  {json_path}")
    if mask is not None:
        print(f"  {mask_path}")


if __name__ == "__main__":
    main()
