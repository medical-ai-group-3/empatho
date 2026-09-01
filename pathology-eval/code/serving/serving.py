"""
sTIL 파이프라인 서빙 래퍼.

서버 담당자 인터페이스:

    from serving import load_model, predict

    bundle = load_model(config)        # 서버 기동 시 1회 (모델 4종 로드, 수십 초 걸림)
    result = predict(bundle, image)    # 요청마다 (이미지 1장 -> dict)

`image` 는 파일 경로(str/Path), RGB ndarray(H,W,3 uint8), 또는 PIL.Image.

내부적으로 `code/stil_inference_pipeline.py` 의 로직을 그대로 재사용한다
(중복 구현 없음). 파이프라인 상세·한계는 `docs/stil_pipeline_limitations.md` 참고.

주의:
  - torch 를 cupy 보다 먼저 import 해야 한다. cupy(12.x wheel)는 torch 가 올려둔
    nvidia-cuda-runtime-cu12 의 libcudart.so.12 에 의존한다. 이 모듈은 순서를 지킨다.
  - Virchow2 는 gated HF 모델. 최초 로드 시 ~/.cache/huggingface 에 없으면
    HF_TOKEN(또는 `huggingface-cli login`)이 필요하다. MANIFEST.md 참고.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch  # cupy 보다 먼저 (libcudart.so.12 로드 순서)
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
PIPELINE_VERSION = "stil-serving-1.0.0"


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


@torch.inference_mode()
def predict(bundle: dict, image, *, return_tissue_mask: bool | None = None) -> dict:
    """이미지 1장 -> sTIL 결과 dict. 스레드 안전하지 않음(단일 워커/큐 가정).

    반환 키: stil_percent, stil_interval_low, stil_interval_high, stil_mc_mean,
      stil_mc_std, mc_samples, tsr_tumor_percent, tsr_stroma_percent, stroma_status,
      n_cells_total, n_cells_til, n_cells_til_stromal, tumor_area_px, stroma_area_px,
      immune_nucleus_area_px, immune_cell_area_px, img_w, img_h, mpp, nc_ratio,
      til_threshold, tissue_mask, tissue_mask_legend, predict_seconds, model_version
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
    mask, _pred16 = sip.tissue_stroma_mask(
        tissue_model, pil, mean, std, image_size, device, W, H)
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

    stil_percent = (immune_cell_px / stroma_area_px * 100) if stroma_ok else None

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
        "stil_percent": _r(stil_percent),
        "stil_interval_low": _r(stil_lo),
        "stil_interval_high": _r(stil_hi),
        "stil_mc_mean": _r(stil_mc_mean),
        "stil_mc_std": _r(stil_mc_std, 3),
        "mc_samples": int(cfg["mc_samples"]) if do_mc else 0,

        "tsr_tumor_percent": _r(tsr_tumor),
        "tsr_stroma_percent": _r(tsr_stroma),

        "stroma_status": "ok" if stroma_ok else "absent",
        "n_cells_total": len(cells),
        "n_cells_til": len(immune),
        "n_cells_til_stromal": len(intra),
        "tumor_area_px": tumor_area_px,
        "stroma_area_px": stroma_area_px,
        "immune_nucleus_area_px": _r(immune_nuc_px, 1),
        "immune_cell_area_px": _r(immune_cell_px, 1),

        "img_w": W, "img_h": H,
        "mpp": float(cfg["mpp"]),
        "nc_ratio": nc_ratio,
        "til_threshold": thr,

        "tissue_mask": (mask if want_mask else None),          # (H,W) uint8 0/1/2
        "tissue_mask_legend": TISSUE_MASK_LEGEND,

        "predict_seconds": round(time.perf_counter() - t0, 2),
        "model_version": bundle["model_version"],
    }


if __name__ == "__main__":  # 간단 자가 테스트: python serving.py [이미지경로]
    import json

    cfg = {"fp16": bool(int(os.getenv("FP16", "0"))), "verify_checksums": False}
    b = load_model(cfg)
    print(f"load_model OK  {b['load_seconds']}s  {b['gpu_mem_after_load']}")
    img = sys.argv[1] if len(sys.argv) > 1 else None
    if img is None:
        rng = np.random.default_rng(0)
        img = rng.integers(160, 230, (1024, 1024, 3), dtype=np.uint8)
    r = predict(b, img, return_tissue_mask=False)
    print(json.dumps({k: v for k, v in r.items() if k != "model_version"},
                     ensure_ascii=False, indent=2))
