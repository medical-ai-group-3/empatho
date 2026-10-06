#!/usr/bin/env python3
"""
초음파 추론 — 이미지 한 장 → 병변 마스크 · 폴리곤 · 형태 지표 · BI-RADS 등급.

서빙용 API 와 CLI 를 겸한다.

    from infer_us import load_model, predict
    bundle = load_model("configs/us_lora.yaml")      # 프로세스당 한 번 (2~3분)
    result = predict(bundle, "a.png")               # 요청마다 (수백 ms)

CLI

    python3 infer_us.py --image a.png

주의 — load_model 은 내부에서 os.chdir 한다(MedSAM3 저장소가 상대경로를 하드코딩).
기본값은 로드가 끝나면 원래 작업 디렉토리로 되돌린다. 되돌리지 않으려면
keep_cwd=True 를 준다. 자세한 내용은 docs/serving_handover.md 참조.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image as PILImage
from torchvision.transforms import v2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_io import (load_config, import_medsam3, build_model,          # noqa: E402
                      load_grading_heads, load_pixel_decoder,
                      run_one_query, pred_union)
from shape_metrics import (extract_polygons, shape_metrics,              # noqa: E402
                           orientation_label, mask_reliability)

US_ROOT = Path(__file__).resolve().parent.parent

# 확정 설정. config 의 inference 블록이나 predict(**over) 로 덮어쓸 수 있다.
# t2·t3·t4 와 conf_* 는 운영 정책 영역이다 — 선택지는 README 참조.
DEFAULTS = {
    "threshold": 0.5,          # 어느 쿼리를 병변으로 볼지
    "mask_threshold": 0.5,     # 어느 화소를 병변으로 볼지
    "polygon_epsilon": 0.5,    # 폴리곤 단순화 허용 오차(px). 키우면 경계 요철이 사라진다
    "single_query": True,      # 마스크도 argmax 쿼리 하나만 사용 (안 B)
    "t2": 0.50, "t3": 0.50, "t4": 0.45,   # CORAL 경계 임계값
    "conf_lo": 0.10, "conf_hi": 0.30,     # 확신도 3단계 경계
}


def _merge_defaults(cfg):
    d = dict(DEFAULTS)
    d.update(cfg.get("inference", {}) or {})
    return d


# ────────────────────────────── 로딩 ──────────────────────────────
def load_model(config, weights=None, heads=None, pd=None, device=None,
               keep_cwd=False):
    """모델을 한 번 올려 두고 재사용한다. 반환값을 predict() 에 넘긴다.

    가중치 경로를 생략하면 <ckpt_dir>/us_{lora_best,pd_best,heads_ensemble}.pt 를 쓴다.
    ⚠ 내부에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩). 기본은 끝나고 되돌린다.
    """
    cwd0 = os.getcwd()
    cfg_path = Path(config).resolve()
    cfg = load_config(cfg_path)
    ck = Path(cfg["output"]["ckpt_dir"])

    w = Path(weights).resolve() if weights else ck / "us_lora_best.pt"
    # 확정 설정은 앙상블이다. us_heads_best.pt 는 기각된 조인트 학습 헤드이므로
    # 기본값으로 쓰지 않는다(docs/experiments.md 6절·10-4).
    h = Path(heads).resolve() if heads else ck / "us_heads_ensemble.pt"
    p = Path(pd).resolve() if pd else ck / "us_pd_best.pt"
    for q in (cfg_path, w):
        if not Path(q).exists():
            raise FileNotFoundError(q)

    dev = device or ("cuda" if torch.cuda.is_available() else "cpu")
    try:
        M = import_medsam3(cfg["model"]["medsam3_repo"])     # 여기서 os.chdir 한다
        # 디코더를 먼저 교체한 뒤 LoRA 를 싣는다 — 순서가 바뀌면 디코더가 무작위로 남는다
        model = build_model(cfg, w, M, dev, load_lora=False)
        load_pixel_decoder(model, p, cfg, dev)
        M["load_lora_weights"](model, str(w))
        hd = load_grading_heads(h, cfg, dev)
        model.eval()
    finally:
        if not keep_cwd:
            os.chdir(cwd0)

    return {
        "model": model, "heads": hd, "M": M, "cfg": cfg, "device": dev,
        "resolution": cfg["data"]["resolution"],
        "params": _merge_defaults(cfg),
        # ⚠ mean/std 0.5 는 바꾸지 말 것 — LoRA·디코더가 이 전처리로 학습됐다.
        #   정규화 방식을 바꾸려면 재학습이 필요하다(README).
        "transform": v2.Compose([
            v2.ToImage(),
            v2.ToDtype(torch.float32, scale=True),
            v2.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5]),
        ]),
        "paths": {"config": str(cfg_path), "lora": str(w),
                  "heads": str(h), "pixel_decoder": str(p)},
        "heads_meta": (hd.meta if hd is not None else None),
    }


# ────────────────────────────── 추론 ──────────────────────────────
def _confidence(p, lo, hi):
    """가장 애매한 경계까지의 거리로 3단계. 등급 확신도이며 마스크 신뢰도와는 별개 축."""
    a = float(np.abs(np.asarray(p) - 0.5).min())
    return ("높음" if a >= hi else "보통" if a >= lo else "낮음"), round(a, 4)


@torch.no_grad()
def predict(bundle, image, **over):
    """image 는 경로 · PIL.Image · numpy 아무거나. over 로 파라미터를 요청 단위로 덮어쓴다.

    반환 dict 의 스키마는 ../README.md. ⚠ result["_mask"] 는 numpy 라 JSON 직전에 제거할 것.
    """
    P = dict(bundle["params"]); P.update({k: v for k, v in over.items() if v is not None})
    M, model, heads = bundle["M"], bundle["model"], bundle["heads"]
    dev, R = bundle["device"], bundle["resolution"]

    if isinstance(image, (str, Path)):
        name, pil = Path(image).name, PILImage.open(image).convert("RGB")
    elif isinstance(image, PILImage.Image):
        name, pil = None, image.convert("RGB")
    else:
        name, pil = None, PILImage.fromarray(np.asarray(image)).convert("RGB")
    ow, oh = pil.size

    out = run_one_query(model, M, bundle["transform"](pil.resize((R, R), PILImage.BILINEAR)),
                        R, oh, ow, dev)
    scores = out["pred_logits"][0].sigmoid().amax(-1)
    keep = torch.where(scores > P["threshold"])[0]
    n_det = int(keep.numel())
    qi = int(scores.argmax())

    # 마스크도 argmax 쿼리 하나만 — 등급과 같은 쿼리를 가리키게 한다.
    idx = torch.tensor([qi], device=scores.device) if P["single_query"] else keep
    mask = np.asarray(pred_union(out["pred_masks"][0], idx, oh, ow, P["mask_threshold"]))

    grade, pb, malig, conf, amb = None, None, None, None, None
    if heads is not None:
        # HeadBundle.probs 가 이미 확률을 돌려준다 — sigmoid 를 다시 걸지 않는다
        cl, mg = heads.probs(out["queries"][0, qi].float()[None])
        pb = [round(v, 6) for v in cl[0].tolist()]
        # 확정 임계값으로 직접 디코딩한다 — coral_decode 는 0.5 고정이라 쓰지 않는다
        grade = 2 + int(pb[0] > P["t2"]) + int(pb[1] > P["t3"]) + int(pb[2] > P["t4"])
        malig = round(float(mg[0]), 6)
        conf, amb = _confidence(pb, P["conf_lo"], P["conf_hi"])

    # pred == 5 는 항상 "4~5" 구간으로 표기한다. 근거는 README.
    band = grade == 5 if grade is not None else False
    shape = shape_metrics(mask)
    poly = extract_polygons(mask, epsilon=P["polygon_epsilon"])
    rel = mask_reliability(float(scores[qi]), n_det)

    return {
        "file": name,
        "image": {"width": ow, "height": oh},
        "lesion_found": bool(mask.sum() > 0),
        "score": round(float(scores[qi]), 6),
        "n_detections": n_det,
        "mask_from": "argmax_query" if P["single_query"] else "union_of_queries",
        "mask_area_px": int(mask.sum()),
        "mask_reliability": rel,
        "grade": {
            "display": ("4~5" if band else (str(grade) if grade is not None else None)),
            "value": grade,
            "is_range": bool(band),
            "confidence": conf,
            "ambiguity": amb,
            "boundary_p": pb,           # [P(y>2), P(y>3), P(y>4)]
            "malignancy": malig,        # 참고값 — 화면 비노출
        },
        "shape": shape,
        "orientation_label": orientation_label(shape),
        "polygons": poly,
        "params": {k: P[k] for k in
                   ("threshold", "mask_threshold", "polygon_epsilon", "single_query",
                    "t2", "t3", "t4", "conf_lo", "conf_hi")},
        "_mask": mask,                  # JSON 직렬화 전에 제거할 것
    }


# ────────────────────────────── CLI ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(US_ROOT / "configs" / "us_lora.yaml"))
    ap.add_argument("--weights", default=None)
    ap.add_argument("--heads", default=None)
    ap.add_argument("--pd", default=None)
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", default=str(US_ROOT / "infer_out"))
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--mask-threshold", type=float, default=None)
    ap.add_argument("--polygon-epsilon", type=float, default=None)
    ap.add_argument("--all-queries", dest="single_query", action="store_false", default=None,
                    help="마스크를 검출 쿼리 전부의 합집합으로 (기본은 argmax 하나)")
    a = ap.parse_args()

    img_path = Path(a.image).resolve()
    out_dir = Path(a.out).resolve()
    if not img_path.exists():
        sys.exit(f"없는 경로: {img_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("모델이 로딩 중 입니다.")
    bundle = load_model(a.config, a.weights, a.heads, a.pd)
    print("로딩 완료.")

    r = predict(bundle, img_path, threshold=a.threshold,
                mask_threshold=a.mask_threshold, polygon_epsilon=a.polygon_epsilon,
                single_query=a.single_query)

    mask = r.pop("_mask")
    mask_path = out_dir / f"{img_path.stem}_mask.png"
    PILImage.fromarray((mask * 255).astype(np.uint8)).save(mask_path)
    r["mask_png"] = mask_path.name

    json_path = out_dir / f"{img_path.stem}.json"
    json_path.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")

    g, s = r["grade"], r["shape"]
    print(f"BI-RADS {g['display']}  ·  확신도 {g['confidence']}"
          f"  ·  병변 {'있음' if r['lesion_found'] else '없음'}  ·  score {r['score']:.3f}")
    if s:
        print(f"  크기 {s['max_diameter_px']}px(최대직경) · {s['area_px']}px²(면적)"
              f"   ※ 픽셀 단위 — mm 아님")
        print(f"  종횡비 {s['height_width_ratio']}  ({r['orientation_label']})")
        print(f"  볼록성 {s['solidity']} · 경계 불규칙도 {s['boundary_irregularity']}"
              f" · 원형도 {s['circularity']}")
    print(f"  마스크 신뢰도 {r['mask_reliability']['level']}"
          + (f" ({r['mask_reliability']['reason']})" if r["mask_reliability"]["reason"] else "")
          + f"   검출 {r['n_detections']}개")
    if r["mask_reliability"]["dim_shape_metrics"]:
        print("  ! 형태 지표는 화면에서 흐리게 처리할 것 — 마스크가 부정확할 수 있다")
    if r["polygons"]["n_components"] > 1:
        print(f"  ! 마스크가 {r['polygons']['n_components']}조각"
              f" (표시 제외 {r['polygons']['dropped_specks']}개)")
    print(f"  {mask_path}")
    print(f"  {json_path}")


if __name__ == "__main__":
    main()