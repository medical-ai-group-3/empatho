#!/usr/bin/env python
"""
검출기 평가 — 병변을 얼마나 찾아내고 위치를 얼마나 잘 잡는가.

무엇을 재나
  1. FROC   영상당 오탐 개수별 민감도.  맘모 CAD 의 표준 지표다.
            "오탐 1개를 허용하면 병변의 몇 %를 찾는가" 로 읽는다.
  2. 크기별 재현율   작은 병변만 놓치는지, 크기와 무관하게 놓치는지.
            다음에 어느 지렛대를 당길지를 이 표가 지목한다.
  3. 종류별   종괴와 석회를 따로. 둘은 난이도가 다르다.

명중 판정을 두 가지로 낸다
  IoU        박스가 얼마나 겹치는가.  엄격한 기준.
  중심 명중   예측 박스의 중심이 정답 박스 안에 있는가.
            임상 CAD 는 이 쪽에 가깝다 — 판독의에게 "여기 보세요" 를
            알려주는 것이 목적이라 정확한 경계는 덜 중요하다.
  둘 다 보고한다. 하나만 보면 그림이 왜곡된다.

모델은 학습 설정 그대로 만든다
  hydra 로 mammo_det.yaml 의 trainer.model 을 그대로 instantiate 한다.
  학습 때와 같은 방법으로 만들어야 가중치가 맞는다.

사용
  python3 eval_det.py --check                    # 3장만, 구조 확인
  python3 eval_det.py                            # 전체
  python3 eval_det.py --ckpt det_run/checkpoints/checkpoint.pt
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

import os                                              # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA, MEDSAM3, RUNS                   # noqa: E402

DET = DATA / "det"
CFG_NAME = "configs/mammo/mammo_det.yaml"
DEF_CKPT = RUNS / "det_run/checkpoints/checkpoint.pt"


def _setup_repo():
    """
    sam3 · hydra 설정은 MedSAM3 저장소 안에 있고, 저장소 코드가 상대경로를
    쓴다. 재배치 전에는 이 파일이 그 위치에 있어서 그냥 됐지만 지금은
    training/code/ 에 있다. 명시적으로 붙인다.
    """
    repo = str(MEDSAM3.resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    if Path.cwd().resolve() != Path(repo):
        os.chdir(repo)

# 범주 이름이 곧 텍스트 프롬프트다 (COCO 변환 때 그렇게 넣었다)
PROMPTS = {1: "mass", 2: "calcification"}

# FROC 를 읽을 지점 — 영상당 허용 오탐 개수
FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)


# ────────────────────────────── 기하 ──────────────────────────────
def iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def center_in(pred, gt):
    """예측 박스의 중심이 정답 박스 안에 있는가 — 임상 CAD 관행."""
    cx, cy = (pred[0] + pred[2]) / 2, (pred[1] + pred[3]) / 2
    return gt[0] <= cx <= gt[2] and gt[1] <= cy <= gt[3]


# ────────────────────────── 모델 · 추론 ──────────────────────────
def build_model(ckpt_path, device, with_seg=True):
    """
    학습 설정 그대로 만들고 학습된 가중치를 얹는다.

    with_seg 를 켜는 이유
      학습은 enable_segmentation=false 로 했다. 박스만 쓰니 분할 머리가 필요 없었다.
      그런데 추론 프로세서(Sam3Processor)는 pred_masks 가 있다고 가정한다.
      그래서 구조는 분할 머리를 포함해 만들고, 학습된 가중치를 얹은 뒤
      분할 머리는 초기값 그대로 둔다. 우리는 박스만 읽으므로 무해하다.
    """
    _setup_repo()
    from hydra import compose, initialize_config_module
    from hydra.utils import instantiate
    from sam3.train.utils.train_utils import register_omegaconf_resolvers

    try:
        register_omegaconf_resolvers()
    except Exception:
        pass                       # 이미 등록돼 있으면 넘어간다

    with initialize_config_module(config_module="sam3.train", version_base=None):
        cfg = compose(config_name=CFG_NAME)
    print(f"  설정 {CFG_NAME}")

    if with_seg:
        from omegaconf import OmegaConf
        OmegaConf.set_struct(cfg, False)
        old = cfg.scratch.get("enable_segmentation")
        cfg.scratch.enable_segmentation = True
        print(f"  분할 머리 포함해 구성  (학습 설정은 {old})")

    model = instantiate(cfg.trainer.model, _recursive_=True)
    n = sum(p.numel() for p in model.parameters())
    print(f"  모델 {type(model).__name__}  {n/1e6:.1f}M")

    obj = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
    sd = obj.get("model", obj)
    missing, unexpected = model.load_state_dict(sd, strict=False)
    seg_missing = [k for k in missing if k.startswith("segmentation_head")]
    bad = [k for k in missing
           if "num_batches" not in k and not k.startswith("segmentation_head")]
    print(f"  가중치 {len(sd)}개 로드   빠짐 {len(bad)} · 예상밖 {len(unexpected)}")
    if seg_missing:
        print(f"    분할 머리 {len(seg_missing)}개는 초기값 — 박스만 읽으므로 무해하다")
    if bad[:3]:
        print(f"    ! 빠진 것 예: {bad[:3]}")
    if unexpected[:3]:
        print(f"    ! 예상밖 예: {unexpected[:3]}")
    if bad:
        sys.exit("  ! 분할 머리 외에 빠진 가중치가 있다 — 설정과 체크포인트가 안 맞는다.")

    ep = obj.get("epoch")
    print(f"  저장 시점  에폭 {ep}")
    return model.to(device).eval()


def extract_boxes(res, W, H):
    """반환 구조에서 (x0,y0,x1,y1,score) 목록을 꺼낸다."""
    def np_(x):
        return x.detach().cpu().numpy() if torch.is_tensor(x) else np.asarray(x)

    if not isinstance(res, dict):
        return []
    boxes = next((np_(res[k]) for k in ("boxes", "pred_boxes", "bbox") if k in res), None)
    if boxes is None or len(boxes) == 0:
        return []
    scores = next((np_(res[k]) for k in ("scores", "confidence", "pred_scores")
                   if k in res), None)
    if scores is None:
        scores = np.ones(len(boxes), dtype=np.float32)
    scores = np.asarray(scores).reshape(-1)[:len(boxes)]

    out = []
    for b, s in zip(np.asarray(boxes).reshape(len(boxes), -1)[:, :4], scores):
        x0, y0, x1, y1 = [float(v) for v in b]
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        # 정규화 좌표로 보이면 화면 크기를 곱한다
        if max(x1, y1) <= 1.5:
            x0, x1 = x0 * W, x1 * W
            y0, y1 = y0 * H, y1 * H
        out.append((x0, y0, x1, y1, float(s)))
    return out


# ────────────────────────────── 평가 ──────────────────────────────
def froc(dets, n_gt, n_img, hit_fn, gts_by_img):
    """
    점수 내림차순으로 훑으며 (영상당 오탐, 민감도) 곡선을 만든다.
    정답 하나는 한 번만 맞힌 것으로 센다 — 같은 병변에 박스 3개를 쳐도 1건이다.
    """
    dets = sorted(dets, key=lambda d: -d["score"])
    matched = set()
    tp = fp = 0
    curve = []
    for d in dets:
        gts = gts_by_img.get(d["img"], [])
        best, bi = 0.0, -1
        for gi, g in enumerate(gts):
            if (d["img"], gi) in matched:
                continue
            v = hit_fn(d["box"], g)
            if v > best:
                best, bi = v, gi
        if bi >= 0 and best > 0:
            matched.add((d["img"], bi))
            tp += 1
        else:
            fp += 1
        curve.append((fp / max(1, n_img), tp / max(1, n_gt), d["score"]))
    return curve


def at_fp(curve, target):
    """오탐이 target 이하인 구간의 최대 민감도와 그때 임계값."""
    best = (0.0, None)
    for f, s, sc in curve:
        if f <= target and s > best[0]:
            best = (s, sc)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(DEF_CKPT))
    ap.add_argument("--det", default=str(DET))
    ap.add_argument("--split", default="test", help="images/ 아래 폴더 이름")
    ap.add_argument("--ann", default="val.json")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--thr", type=float, default=0.05,
                    help="이 점수 미만은 버린다. FROC 를 그리려면 낮게 둔다")
    ap.add_argument("--iou", type=float, default=0.3,
                    help="IoU 명중 기준 (임상 CAD 는 느슨한 편이다)")
    ap.add_argument("--n", type=int, default=0, help="영상 수 제한 (0=전체)")
    ap.add_argument("--check", action="store_true", help="3장만 돌려 구조 확인")
    ap.add_argument("--no-seg", action="store_true",
                    help="분할 머리 없이 구성 (프로세서가 마스크를 안 찾을 때)")
    ap.add_argument("--save-json", default="", help="검출 결과를 저장할 경로")
    a = ap.parse_args()

    det = Path(a.det)
    ann_path = det / "annotations" / a.ann
    img_dir = det / "images" / a.split
    for p in (ann_path, img_dir):
        if not p.exists():
            sys.exit(f"없다: {p}")

    print("=" * 74)
    print("검출기 평가")
    print("=" * 74)
    print(f"  체크포인트 {a.ckpt}")
    coco = json.loads(ann_path.read_text(encoding="utf-8"))
    cats = {c["id"]: c["name"] for c in coco["categories"]}
    imgs = {im["id"]: im for im in coco["images"]}
    gt_by = defaultdict(lambda: defaultdict(list))     # img_id -> cat -> [box]
    for an in coco["annotations"]:
        x, y, w, h = an["bbox"]
        gt_by[an["image_id"]][an["category_id"]].append((x, y, x + w, y + h))
    print(f"  영상 {len(imgs)}장 · 주석 {len(coco['annotations'])}건 · 범주 {cats}")

    model = build_model(a.ckpt, a.device, with_seg=not a.no_seg)

    from PIL import Image
    from sam3.model.sam3_image_processor import Sam3Processor
    proc = Sam3Processor(model, device=a.device, confidence_threshold=a.thr)

    ids = sorted(imgs)
    if a.check:
        ids = ids[:3]
    elif a.n:
        ids = ids[:a.n]

    print(f"\n■ 추론  {len(ids)}장 x {len(PROMPTS)}프롬프트")
    dets = {c: [] for c in PROMPTS}
    import time
    t0 = time.time()
    for i, iid in enumerate(ids, 1):
        im = imgs[iid]
        p = img_dir / im["file_name"]
        if not p.is_file():
            continue
        pil = Image.open(p).convert("RGB")
        W, H = pil.size
        for cid, prompt in PROMPTS.items():
            # 프롬프트마다 state 를 새로 만든다.
            # set_text_prompt 이 state 를 소비해서 두 번째 호출이 깨진다
            # (KeyError: 'img_batch_all_stages') — 실측으로 확인했다.
            state = proc.set_image(pil)
            if i == 1 and cid == min(PROMPTS):
                gh, gw = state.get("original_height"), state.get("original_width")
                print(f"    첫 영상 {W}x{H}   프로세서가 읽은 크기 {gw}x{gh}")
                if (gh, gw) != (H, W):
                    sys.exit("    ! 프로세서가 크기를 잘못 읽었다 — 입력 형식 문제다")
            try:
                res = proc.set_text_prompt(prompt, state)
            except Exception as e:
                print(f"    ! {prompt} 실패: {type(e).__name__}: {e}")
                continue
            if a.check and i == 1:
                keys = list(res.keys()) if isinstance(res, dict) else type(res)
                print(f"    '{prompt}' 반환 키: {keys}")
            for b in extract_boxes(res, W, H):
                dets[cid].append(dict(img=iid, box=b[:4], score=b[4]))
        if i % 25 == 0 or i == len(ids):
            el = time.time() - t0
            print(f"\r    {i}/{len(ids)}   {el:.0f}s 경과 · "
                  f"남은 {el/i*(len(ids)-i):.0f}s   ", end="", flush=True)
    print()

    if a.check:
        for cid, prompt in PROMPTS.items():
            print(f"  {prompt}: 박스 {len(dets[cid])}개")
            for d in dets[cid][:3]:
                print(f"    {tuple(round(v,1) for v in d['box'])}  점수 {d['score']:.3f}")
        print("\n  구조 확인 완료. --check 를 빼고 전체를 돌려라.")
        return

    if a.save_json:
        Path(a.save_json).write_text(json.dumps(
            {str(c): dets[c] for c in dets}, default=float), encoding="utf-8")
        print(f"  검출 결과 저장 -> {a.save_json}")

    # ── 지표 ───────────────────────────────────────────────────────────
    n_img = len(ids)
    for cid, prompt in PROMPTS.items():
        gts = {iid: gt_by[iid][cid] for iid in ids if gt_by[iid][cid]}
        n_gt = sum(len(v) for v in gts.values())
        if n_gt == 0:
            continue
        print(f"\n{'='*74}")
        print(f"{prompt}   정답 병변 {n_gt}건 / 영상 {len(gts)}장   "
              f"(전체 {n_img}장 중)")
        print("=" * 74)

        for label, fn in (("IoU>%.1f" % a.iou,
                           lambda p, g: 1.0 if iou(p, g) >= a.iou else 0.0),
                          ("중심 명중",
                           lambda p, g: 1.0 if center_in(p, g) else 0.0)):
            curve = froc(dets[cid], n_gt, n_img, fn, gts)
            print(f"\n  ── {label} ──")
            print(f"    영상당 오탐    민감도    임계값")
            for t in FP_POINTS:
                s, sc = at_fp(curve, t)
                scs = f"{sc:.3f}" if sc is not None else "—"
                print(f"      {t:4.2f}         {s:6.1%}    {scs}")
            if curve:
                print(f"    (전체 검출 {len(curve)}개 · "
                      f"최대 민감도 {max(s for _, s, _ in curve):.1%})")

        # ── 크기별 ────────────────────────────────────────────────────
        areas = [( (g[2]-g[0])*(g[3]-g[1]), iid, gi )
                 for iid, gl in gts.items() for gi, g in enumerate(gl)]
        if len(areas) >= 6:
            areas.sort()
            k = len(areas) // 3
            bands = [("작은 1/3", areas[:k]), ("중간 1/3", areas[k:2*k]),
                     ("큰 1/3", areas[2*k:])]
            # 오탐 1개/영상 지점의 임계값으로 고정해 크기별 재현율을 본다
            curve = froc(dets[cid], n_gt, n_img,
                         lambda p, g: 1.0 if center_in(p, g) else 0.0, gts)
            _, sc = at_fp(curve, 1.0)
            sc = sc if sc is not None else 0.0
            keep = [d for d in dets[cid] if d["score"] >= sc]
            print(f"\n  ── 크기별 재현율 (중심 명중 · 오탐 1개/영상 지점) ──")
            print(f"    구간        병변수   화면비율 중앙   재현율")
            for name, band in bands:
                hit = 0
                for ar, iid, gi in band:
                    g = gts[iid][gi]
                    if any(d["img"] == iid and center_in(d["box"], g) for d in keep):
                        hit += 1
                im = imgs[band[0][1]]
                med = np.median([ar for ar, _, _ in band]) / (im["width"]*im["height"]) * 100
                print(f"    {name:10s} {len(band):5d}   {med:10.2f}%   {hit/len(band):8.1%}")
            print(f"\n    작은 쪽만 낮으면 → 해상도·스케일 문제")
            print(f"    전 구간 낮으면   → 특징이 맘모를 모른다 (백본 적응 필요)")


if __name__ == "__main__":
    main()
