#!/usr/bin/env python
"""
sTIL 서빙 헬스체크. 서버 기동 후 / 오케스트레이터 readiness probe 로 사용.

단계:
  1. 체크포인트 파일 존재 (+ --verify-checksums 면 sha256 대조)
  2. load_model() 성공
  3. 더미 이미지 1장으로 predict() 실행 -> 필수 키·타입 검증
  4. GPU 메모리 사용량 리포트

종료 코드: 0 = 정상, 1 = 실패.

사용:
  python healthcheck.py                    # fp32, 체크섬 검증 O
  python healthcheck.py --fp16             # 저VRAM
  python healthcheck.py --gpu 1 --no-verify-checksums --quiet
  python healthcheck.py --image some.png   # 실제 이미지로
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback

import numpy as np

import serving  # 같은 디렉터리


REQUIRED_KEYS = {
    "stil_percent", "stil_interval_low", "stil_interval_high", "stil_mc_mean",
    "stil_mc_std", "mc_samples", "tsr_tumor_percent", "tsr_stroma_percent",
    "stroma_status", "n_cells_total", "n_cells_til", "n_cells_til_stromal",
    "tumor_area_px", "stroma_area_px", "img_w", "img_h", "tissue_mask_legend",
    "predict_seconds", "model_version",
}


def _log(msg: str, quiet: bool = False):
    if not quiet:
        print(msg, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--no-verify-checksums", dest="verify", action="store_false",
                    help="2.7G CellViT 파일 sha256 스킵 (빠름)")
    ap.add_argument("--mc-samples", type=int, default=10, help="헬스체크는 적게 (기본 10)")
    ap.add_argument("--image", default=None, help="더미 대신 실제 이미지 경로")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    report: dict = {"ok": False, "stage": None, "steps": {}}
    t_start = time.perf_counter()

    # ── 1. 체크포인트 존재 ──────────────────────────────────────────────
    report["stage"] = "checkpoints"
    cfg = {
        "gpu": args.gpu, "fp16": args.fp16, "verify_checksums": args.verify,
        "mc_samples": args.mc_samples,
    }
    from pathlib import Path
    paths = {
        "tissue_head": serving.DEFAULT_CONFIG["tissue_checkpoint"],
        "cell_classifier": serving.DEFAULT_CONFIG["cell_head"],
        "cellvit_sam": serving.DEFAULT_CONFIG["cellvit_path"],
    }
    ckpt_step = {}
    all_present = True
    for k, p in paths.items():
        exists = Path(p).is_file()
        size = Path(p).stat().st_size if exists else 0
        ckpt_step[k] = {"path": p, "exists": exists, "bytes": size}
        all_present &= exists
        _log(f"[1/4] {k:16s} {'OK ' if exists else 'MISSING'} {p} ({size/1e6:.1f} MB)", args.quiet)
    report["steps"]["checkpoints"] = ckpt_step
    if not all_present:
        report["error"] = "체크포인트 파일 누락"
        return _finish(report, t_start, args)

    # ── 2. load_model ──────────────────────────────────────────────────
    report["stage"] = "load_model"
    try:
        t0 = time.perf_counter()
        bundle = serving.load_model(cfg)
        report["steps"]["load_model"] = {
            "seconds": round(time.perf_counter() - t0, 1),
            "device": bundle["device"],
            "model_version": bundle["model_version"],
            "gpu_mem_after_load_mb": bundle["gpu_mem_after_load"],
        }
        _log(f"[2/4] load_model OK  {report['steps']['load_model']['seconds']}s  "
             f"device={bundle['device']}", args.quiet)
    except Exception as e:
        report["error"] = f"load_model 실패: {e}"
        report["traceback"] = traceback.format_exc()
        return _finish(report, t_start, args)

    # ── 3. predict (더미 또는 실제 이미지) ─────────────────────────────
    report["stage"] = "predict"
    try:
        if args.image:
            image = args.image
        else:
            rng = np.random.default_rng(1234)
            # H&E 비슷하게: 밝은 배경 + 보라 얼룩 (실제 세포 검출은 거의 0 이어도 정상)
            image = rng.integers(150, 235, (1024, 1024, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        result = serving.predict(bundle, image, return_tissue_mask=True)
        dt = time.perf_counter() - t0

        missing = REQUIRED_KEYS - set(result)
        if missing:
            raise AssertionError(f"predict 반환에 키 누락: {sorted(missing)}")
        if result["stroma_status"] not in ("ok", "absent"):
            raise AssertionError(f"stroma_status 이상: {result['stroma_status']}")
        tm = result["tissue_mask"]
        if not (isinstance(tm, np.ndarray) and tm.shape == (result["img_h"], result["img_w"])):
            raise AssertionError("tissue_mask shape 이상")
        if not set(np.unique(tm)).issubset({0, 1, 2}):
            raise AssertionError(f"tissue_mask 값 이상: {np.unique(tm)}")
        # stil 은 stroma_status=ok 일 때만 숫자
        if result["stroma_status"] == "ok" and result["stil_percent"] is None:
            raise AssertionError("stroma_status=ok 인데 stil_percent=None")

        report["steps"]["predict"] = {
            "seconds": round(dt, 2),
            "result_sample": {k: v for k, v in result.items()
                              if k not in ("tissue_mask", "model_version")},
        }
        _log(f"[3/4] predict OK  {dt:.2f}s  stil={result['stil_percent']} "
             f"CI[{result['stil_interval_low']},{result['stil_interval_high']}] "
             f"cells={result['n_cells_total']} stroma={result['stroma_status']}", args.quiet)
    except Exception as e:
        report["error"] = f"predict 실패: {e}"
        report["traceback"] = traceback.format_exc()
        return _finish(report, t_start, args)

    # ── 4. GPU 메모리 리포트 ──────────────────────────────────────────
    report["stage"] = "gpu_report"
    try:
        import torch
        gpu = {}
        if bundle["device"].startswith("cuda"):
            idx = int(bundle["device"].split(":")[1])
            free, total = torch.cuda.mem_get_info(idx)
            gpu = {
                "device_name": torch.cuda.get_device_name(idx),
                "allocated_mb": round(torch.cuda.memory_allocated(idx) / 1e6, 1),
                "reserved_mb": round(torch.cuda.memory_reserved(idx) / 1e6, 1),
                "max_allocated_mb": round(torch.cuda.max_memory_allocated(idx) / 1e6, 1),
                "free_mb": round(free / 1e6, 1),
                "total_mb": round(total / 1e6, 1),
            }
        else:
            gpu = {"device": "cpu"}
        report["steps"]["gpu_report"] = gpu
        _log(f"[4/4] GPU  allocated={gpu.get('allocated_mb','-')}MB  "
             f"reserved={gpu.get('reserved_mb','-')}MB  "
             f"max_allocated={gpu.get('max_allocated_mb','-')}MB  "
             f"free={gpu.get('free_mb','-')}MB", args.quiet)
    except Exception as e:
        report["error"] = f"gpu_report 실패: {e}"
        return _finish(report, t_start, args)

    report["ok"] = True
    report["stage"] = "done"
    return _finish(report, t_start, args)


def _finish(report: dict, t_start: float, args) -> int:
    report["total_seconds"] = round(time.perf_counter() - t_start, 1)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=str))
    elif not args.quiet:
        if report["ok"]:
            print(f"\n✅ HEALTHCHECK PASS  ({report['total_seconds']}s)")
        else:
            print(f"\n❌ HEALTHCHECK FAIL @ stage={report['stage']}: {report.get('error')}")
            if report.get("traceback"):
                print(report["traceback"])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
