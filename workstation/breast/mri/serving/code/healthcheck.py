#!/usr/bin/env python3
"""
MRI 서빙 자가진단 — 배포 후 가장 먼저 돌릴 것.

파일 존재 · 의존성 · 경로 · GPU 여유를 점검하고, --pre-npy/--post-npy를 주면
실제 preprocess_raw_to_volume()/load_model()/predict()까지 돌려서 시간을 잰다.

★ 2026-09-04 변경 — dataset_tag 폐지에 맞춰 테스트 인자를 --volume-npy(1개)에서
  --pre-npy/--post-npy(원본 두 개, 리샘플링 전)로 바꿨다. tumor/density를 한
  volume에서 만드는 구조가 됐으므로 원본부터 돌리는 편이 실제 서빙 경로와 더
  가깝다. Garage 점검 절(구 5절)은 Go 파생물 게이트웨이 점검으로 교체했다.

사용법:
    python3 healthcheck.py
    python3 healthcheck.py --pre-npy /경로/pre.npy --post-npy /경로/post.npy
        (⚠ 여기 npy는 리샘플링 전 원본 배열이어야 한다 — sitk 없이 빠르게 테스트하려면
         이 스크립트를 --pre-path/--post-path로 원본 파일 자체를 받게 확장할 것)
"""

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "code"))


def check(label, ok, detail=""):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}" + (f" — {detail}" if detail else ""))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(HERE / "configs" / "mri_lora.yaml"))
    ap.add_argument("--pre-path", default=None, help="주면 실제 추론까지 실행 (원본 pre, nii.gz/DICOM 폴더) - 필수")
    ap.add_argument("--post-path", default=None,
                     help="원본 post - 선택. 주면 종양+밀도, 없으면 밀도만(2026-09-04 A-5 반영)")
    args = ap.parse_args()

    all_ok = True

    print("=" * 60)
    print("1. 필수 파일 존재 확인")
    print("=" * 60)

    cfg_path = Path(args.config).resolve()
    all_ok &= check("config 파일", cfg_path.exists(), str(cfg_path))

    if cfg_path.exists():
        import yaml
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)

        ckpt = Path(cfg["model"]["checkpoint"])
        all_ok &= check("MedSAM3 병합본(medsam3_merged.pt)", ckpt.exists(), str(ckpt))

        merge_cfg = Path(cfg["model"]["merge_lora_config"])
        all_ok &= check("merge_lora_config", merge_cfg.exists(), str(merge_cfg))

        medsam3_repo = Path(cfg["model"]["medsam3_repo"])
        all_ok &= check("MedSAM3 저장소", medsam3_repo.exists() and (medsam3_repo / "sam3").exists(),
                         str(medsam3_repo))

        ck_dir = Path(cfg["output"]["ckpt_dir"])
        weights = ck_dir / "mri_lora_best.pt"
        all_ok &= check("MRI LoRA 가중치(mri_lora_best.pt)", weights.exists(), str(weights))
    else:
        print("  config 없어서 나머지 파일 점검 생략")
        all_ok = False

    print()
    print("=" * 60)
    print("2. 의존 폴더(같은 mri/ 트리 안, import 대상)")
    print("=" * 60)
    mri_root = HERE.parent  # mri/serving/ 기준 -> mri/
    pp3d = mri_root / "postprocess_3d" / "code"
    preprocess = mri_root / "training" / "code" / "preprocess"

    all_ok &= check("postprocess_3d/code (eval_mri_lora_v3, build_3d_from_predictions_v9, "
                     "compute_stage1_metrics)", pp3d.exists() and
                     (pp3d / "eval_mri_lora_v3.py").exists(), str(pp3d))
    all_ok &= check("postprocess_3d/code/build_mesh_from_mask.py",
                     (pp3d / "build_mesh_from_mask.py").exists(), str(pp3d / "build_mesh_from_mask.py"))
    all_ok &= check("training/code/preprocess (preprocess_mamamia)", preprocess.exists() and
                     (preprocess / "preprocess_mamamia.py").exists(), str(preprocess))
    all_ok &= check("serving/code/normalize.py (2026-09-04 신규 — tumor/density 정규화 분리)",
                     (HERE / "code" / "normalize.py").exists(), str(HERE / "code" / "normalize.py"))

    print()
    print("=" * 60)
    print("3. 파이썬 의존성")
    print("=" * 60)
    for mod in ("torch", "numpy", "SimpleITK", "yaml", "PIL", "scipy", "requests", "skimage"):
        try:
            __import__(mod)
            check(mod, True)
        except ImportError as e:
            all_ok &= check(mod, False, str(e))
    # ⚠ boto3는 더 이상 점검하지 않는다 - derived_io.py가 Garage와 직접 통신하지 않는다(C-4/C-5).

    print()
    print("=" * 60)
    print("4. GPU")
    print("=" * 60)
    try:
        import torch
        has_cuda = torch.cuda.is_available()
        check("CUDA 사용 가능", has_cuda)
        if has_cuda:
            free, total = torch.cuda.mem_get_info()
            free_gb, total_gb = free / 1e9, total / 1e9
            check(f"GPU 메모리", free_gb > 3.0,
                  f"여유 {free_gb:.1f}GB / 전체 {total_gb:.1f}GB")
            if free_gb < 3.0:
                print("    ⚠ 여유가 3GB 미만이면 로딩 자체가 실패할 수 있음 - 다른 프로세스 확인 필요")
    except Exception as e:
        all_ok &= check("GPU 점검", False, str(e))

    print()
    print("=" * 60)
    print("5. Go 파생물 게이트웨이 연결 (2026-09-04 변경 — 구 'Garage 연결' 절)")
    print("=" * 60)
    print("  ⚠ MRI 원본은 더 이상 이 서비스가 직접 받아오지 않는다(C-4) — 앱 서버가")
    print("    파일로 넘긴다. 이 절은 3D 메시 업로드 대상인 Go 게이트웨이만 점검한다.")
    print("  ⚠ 실제 업로드(POST /svc/v1/derived)는 티켓이 있어야 되므로 여기서는 안 함 —")
    print("    /healthz로 게이트웨이가 떠 있는지, 파생물 버킷이 배포에 설정됐는지만 확인.")
    import os
    go_url = os.environ.get("GO_GATEWAY_URL")
    # ⚠ 2026-09-04 수정 — 이 절은 all_ok에 영향을 주지 않는다. Go 게이트웨이는 메시
    # 업로드(부가 기능)용이고 로컬 저장 폴백이 있어서, 여기가 막혀도 실제 추론
    # 테스트(6절)는 정상 진행돼야 한다. 이전 버전은 실수로 all_ok &= 를 걸어놔서
    # 워크스테이션 등 Go가 아예 없는 개발 환경에서 추론 테스트 자체가 막혔었다.
    check("GO_GATEWAY_URL 환경변수", bool(go_url),
          go_url or "(미설정 - 기본값 http://go-gateway:8091 시도, 워크스테이션 단독 테스트라면 정상)")
    try:
        import requests
        base = go_url or "http://go-gateway:8091"  # Go 담당 확인 - GW_ADDR 기본값 :8091
        resp = requests.get(f"{base}/healthz", timeout=3)
        ok = resp.status_code < 500
        check(f"Go 게이트웨이 접속 ({base})", ok, f"status={resp.status_code}")
        if ok:
            body = resp.json()
            derived_bucket = body.get("derived_bucket")
            configured = bool(derived_bucket) and derived_bucket != "(설정 안 됨)"
            check("파생물 버킷(derived_bucket) 배포 설정", configured,
                  f"{derived_bucket!r} — 꺼져있으면 /svc/v1/derived가 조용히 404를 냄(의도된 동작). "
                  f"배포 담당에게 알릴 것(A-2)")
    except Exception as e:
        check("Go 게이트웨이 접속", False,
              f"{e} — 메시 업로드는 나중 문제, 지금은 무시하고 진행해도 됨(로컬 저장 폴백)")

    print()
    print("=" * 60)
    print("결과:", "모두 통과 — 배포 가능" if all_ok else "일부 실패 - 위 항목 확인 필요")
    print("=" * 60)

    if not all_ok:
        print("\n실제 추론 테스트는 위 문제를 먼저 해결한 뒤 진행할 것.")
        sys.exit(1)

    if args.pre_path:
        print("\n" + "=" * 60)
        print(f"6. 실제 추론 테스트 (post {'있음 - tumor+density' if args.post_path else '없음 - density만'})")
        print("=" * 60)
        from infer_mri import load_model, predict, preprocess_raw_to_volume

        print("모델 로딩 중...")
        t0 = time.time()
        bundle = load_model(str(cfg_path))
        load_s = time.time() - t0
        print(f"  로딩 완료: {load_s:.1f}초")

        print("원본 전처리 중 (tumor용 2-phase + density용 1-phase 동시 생성)...")
        t0 = time.time()
        tumor_volume, density_volume, geometry = preprocess_raw_to_volume(
            args.pre_path, args.post_path, return_geometry=True
        )
        prep_s = time.time() - t0
        print(f"  전처리 완료: {prep_s:.1f}초, 슬라이스 {density_volume.shape[1]}장, phases 예정={2 if args.post_path else 1}")

        mesh_out = HERE / "infer_out" / "mesh_healthcheck"
        t0 = time.time()
        r = predict(bundle, tumor_volume, density_volume, patient_id="healthcheck",
                    include_mesh=True, mesh_out_dir=str(mesh_out), geometry=geometry)
        pred_s = time.time() - t0
        print(f"  추론+메시 완료: {pred_s:.1f}초 "
              f"({pred_s/density_volume.shape[1]*1000:.0f}ms/슬라이스, "
              f"정량값만 필요하면 predict(..., include_mesh=False)로 이 시간 단축 가능)")

        if r["tumor"] is not None:
            print(f"  병변 검출: {r['tumor']['lesion_count']}개")
            for lesion in r["tumor"]["lesions"]:
                idx1 = lesion.get("lesion_index", 0) + 1
                mesh = lesion.get("mesh")
                if mesh:
                    print(f"  3D 메시(병변 {idx1}): 정점 {mesh['vertex_count']}개, "
                          f"삼각형 {mesh['triangle_count']}개 -> {mesh.get('stl_path', '(경로 없음)')}")
                else:
                    print(f"  3D 메시(병변 {idx1}): 없음 (centroid 매칭 실패)")
        else:
            print("  tumor: 계산 안 함(post 없음, --post-path 안 줌)")

        print(f"  밀도비율: {r['density']['dense_density_pct']}%")
        for k, label in (("breast_mesh", "breast"), ("dense_tissue_mesh", "dense tissue")):
            mesh = r["density"][k]
            if mesh:
                print(f"  3D 메시({label}): 정점 {mesh['vertex_count']}개, "
                      f"삼각형 {mesh['triangle_count']}개 -> {mesh.get('stl_path', '(경로 없음)')}")
            else:
                print(f"  3D 메시({label}): 없음 (마스크가 비어있음 - 이 경우는 이상 징후일 수 있음)")

        try:
            import torch
            peak_gb = torch.cuda.max_memory_allocated() / 1e9
            print(f"  GPU peak: {peak_gb:.2f}GB")
        except Exception:
            pass

        print("\n실제 추론 정상 작동 확인.")
    else:
        print("\n--pre-path와 --post-path를 함께 주면 실제 전처리/load_model()/predict()까지 테스트합니다.")


if __name__ == "__main__":
    main()