#!/usr/bin/env python3
"""
배포 후 제일 먼저 돌리는 점검. 되는지 안 되는지 바로 알려준다.

    파일 → 의존성 → 모델 로드 → 샘플 추론 → JSON 스키마

    python3 healthcheck.py
    python3 healthcheck.py --image /경로/샘플.png     실제 이미지로
    python3 healthcheck.py --skip-infer               파일·의존성만 (GPU 불필요)
"""

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OK, NG, WARN = "  ✓", "  ✗", "  !"
fails, warns = [], []


def ok(msg):
    print(f"{OK} {msg}")


def ng(msg):
    print(f"{NG} {msg}")
    fails.append(msg)


def warn(msg):
    print(f"{WARN} {msg}")
    warns.append(msg)


def section(t):
    print(f"\n── {t}")


# ── 1. 파일 ────────────────────────────────────────────────────────────────
def check_files(cfg_path):
    section("1. 파일")
    need = [
        ("code/infer_us.py", None), ("code/model_io.py", None),
        ("code/heads.py", None), ("code/shape_metrics.py", None),
        ("code/unet_pixel_decoder.py", None),
        ("ckpt/us_lora_best.pt", 60e6), ("ckpt/us_pd_best.pt", 5e6),
        ("ckpt/us_heads_ensemble.pt", 10e3),
        ("configs/us_lora.yaml", None),
    ]
    for rel, minsize in need:
        p = HERE / rel
        if not p.exists():
            ng(f"{rel} 없음")
        elif p.stat().st_size == 0:
            ng(f"{rel} 가 0바이트 — 저장이 중간에 실패한 파일이다")
        elif minsize and p.stat().st_size < minsize:
            ng(f"{rel} 가 너무 작다 ({p.stat().st_size/1e6:.1f} MB)")
        else:
            ok(f"{rel}  {p.stat().st_size/1e6:.1f} MB")

    man = HERE / "ckpt" / "us_best_manifest.json"
    if man.exists():
        m = json.loads(man.read_text())
        ok(f"매니페스트  epoch {m.get('epoch')} · run {m.get('run')}")
    else:
        warn("us_best_manifest.json 없음 — 체크포인트 짝을 확인할 수 없다")
    return cfg_path.exists()


# ── 2. 설정 경로 ───────────────────────────────────────────────────────────
def check_config(cfg_path):
    section("2. 설정 경로")
    import yaml
    cfg = yaml.safe_load(cfg_path.read_text())
    for key in ("checkpoint", "merge_lora_config", "medsam3_repo"):
        p = Path(cfg["model"][key])
        (ok if p.exists() else ng)(f"model.{key}  {p}")
    ck = Path(cfg["output"]["ckpt_dir"])
    if ck.resolve() == (HERE / "ckpt").resolve():
        ok(f"output.ckpt_dir  {ck}")
    else:
        warn(f"output.ckpt_dir 가 이 폴더가 아니다 — {ck}")

    repo = Path(cfg["model"]["medsam3_repo"])
    for rel in ("sam3", "lora_layers.py", "merge_medsam3.py"):
        (ok if (repo / rel).exists() else ng)(f"MedSAM3/{rel}")
    return cfg


# ── 3. 의존성 ──────────────────────────────────────────────────────────────
def check_deps():
    section("3. 의존성")
    import importlib
    for mod, label in [("torch", "torch"), ("torchvision", "torchvision"),
                       ("numpy", "numpy"), ("yaml", "PyYAML"),
                       ("PIL", "Pillow"), ("cv2", "opencv"),
                       ("iopath", "iopath"), ("pycocotools", "pycocotools")]:
        try:
            m = importlib.import_module(mod)
            ok(f"{label}  {getattr(m, '__version__', '')}")
        except ImportError:
            ng(f"{label} 없음 — requirements.txt 참조")
    try:
        import torch
        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            ok(f"CUDA  {torch.cuda.get_device_name(0)}  여유 {free/1e9:.1f} / {total/1e9:.1f} GB")
            if free < 7e9:
                warn("VRAM 여유가 7 GB 미만이다 — 추론 peak 이 약 6.5 GB 다")
        else:
            warn("CUDA 를 쓸 수 없다 — CPU 로는 매우 느리다")
    except Exception as e:
        ng(f"CUDA 확인 실패: {e}")


# ── 4. 모델 로드 + 추론 ────────────────────────────────────────────────────
def check_infer(cfg_path, image):
    section("4. 모델 로드")
    sys.path.insert(0, str(HERE / "code"))
    import os
    cwd0 = os.getcwd()
    from infer_us import load_model, predict

    t0 = time.time()
    bundle = load_model(str(cfg_path))
    ok(f"로드 완료  {time.time()-t0:.1f} 초")
    if os.getcwd() != cwd0:
        ng("작업 디렉토리가 바뀐 채로 돌아왔다 — os.chdir 복귀 실패")
    else:
        ok("작업 디렉토리 보존")
    hm = bundle.get("heads_meta") or {}
    n = hm.get("n_seeds")
    if n and n > 1:
        ok(f"등급 헤드 앙상블 {n}개 (p={hm.get('p_exp')})")
    else:
        warn("등급 헤드가 앙상블이 아니다 — 확정 설정은 앙상블이다(README)")

    import torch
    if torch.cuda.is_available():
        ok(f"VRAM 로딩 후  {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    section("5. 샘플 추론")
    if image:
        img = Path(image)
        if not img.exists():
            ng(f"이미지 없음: {img}")
            return
    else:
        from PIL import Image as PILImage
        import numpy as np
        rng = np.random.default_rng(0)
        base = rng.integers(30, 90, (351, 274), dtype=np.uint8)
        base[120:200, 90:180] = rng.integers(90, 160, (80, 90), dtype=np.uint8)
        img = PILImage.fromarray(base)
        warn("샘플 이미지가 없어 합성 영상으로 점검한다 "
             "(형식만 확인 — 결과값은 의미 없다). --image 로 실제 영상을 줄 것")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()
    r = predict(bundle, img)
    dt = time.time() - t0
    ok(f"추론 완료  {dt*1000:.0f} ms")
    if torch.cuda.is_available():
        ok(f"VRAM 추론 peak  {torch.cuda.max_memory_allocated()/1e9:.2f} GB")

    section("6. 결과 JSON")
    mask = r.pop("_mask", None)
    if mask is None:
        ng("_mask 키가 없다")
    else:
        ok(f"마스크 {mask.shape} · {int(mask.sum())} px  (_mask 는 JSON 직전에 제거할 것)")

    top = ["file", "image", "lesion_found", "score", "n_detections", "mask_from",
           "mask_area_px", "mask_reliability", "grade", "shape",
           "orientation_label", "polygons", "params"]
    miss = [k for k in top if k not in r]
    (ok if not miss else ng)(f"최상위 키 {len(top)-len(miss)}/{len(top)}"
                             + (f" — 누락 {miss}" if miss else ""))

    g = r.get("grade") or {}
    for k in ("display", "value", "is_range", "confidence", "boundary_p"):
        if k not in g:
            ng(f"grade.{k} 없음")
    if g.get("confidence") not in ("높음", "보통", "낮음", None):
        ng(f"grade.confidence 값이 이상하다: {g.get('confidence')}")

    rel = r.get("mask_reliability") or {}
    if rel.get("level") not in ("높음", "보통", "낮음"):
        ng(f"mask_reliability.level 값이 이상하다: {rel.get('level')}")

    sh = r.get("shape")
    if sh and sh.get("unit") != "px":
        ng("shape.unit 이 px 가 아니다")

    try:
        json.dumps(r, ensure_ascii=False)
        ok("json.dumps 직렬화 성공")
    except TypeError as e:
        ng(f"직렬화 실패: {e}")

    print()
    print(f"  BI-RADS {g.get('display')} · 확신도 {g.get('confidence')}"
          f" · 마스크 신뢰도 {rel.get('level')} · 검출 {r.get('n_detections')}개")
    if sh:
        print(f"  크기 {sh.get('max_diameter_px')} px · {sh.get('area_px')} px²"
              f" · {r.get('orientation_label')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "configs" / "us_lora.yaml"))
    ap.add_argument("--image", default=None, help="점검에 쓸 초음파 영상")
    ap.add_argument("--skip-infer", action="store_true", help="파일·의존성만 (GPU 불필요)")
    a = ap.parse_args()

    print("=" * 70)
    print("초음파 추론 서빙 — 배포 점검")
    print("=" * 70)

    cfg_path = Path(a.config).resolve()
    if not check_files(cfg_path):
        ng(f"설정 파일 없음: {cfg_path}")
    else:
        check_config(cfg_path)
    check_deps()

    if not a.skip_infer and not fails:
        try:
            check_infer(cfg_path, a.image)
        except Exception as e:
            ng(f"추론 중 예외: {type(e).__name__}: {e}")
    elif fails:
        print("\n  앞 단계에서 실패가 있어 추론은 건너뛴다")

    print()
    print("=" * 70)
    if fails:
        print(f"✗ 실패 {len(fails)}건 — 배포 불가")
        for f in fails:
            print(f"    · {f}")
    else:
        print("✓ 전부 통과 — 서빙 가능")
    if warns:
        print(f"\n! 경고 {len(warns)}건")
        for w in warns:
            print(f"    · {w}")
    print("=" * 70)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
