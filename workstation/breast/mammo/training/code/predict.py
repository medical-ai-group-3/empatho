#!/usr/bin/env python
"""
맘모그램 한 장 → 병변 위치 · 서술어 · BI-RADS · 조직검사 여부.

이게 '제품' 이다. 나머지 스크립트는 채점 도구다.
  eval_mammo_det.py    598장을 훑어 FROC 을 낸다
  eval_end2end.py      598장을 훑어 끝단 민감도를 낸다
  predict.py           사진 한 장을 넣으면 답을 준다   ← 이 파일

가중치를 인자로 받는다
  검출기도 서술어도 경로만 바꾸면 갈아끼워진다. 지금은 에폭 6 이 기본값이고,
  에폭 12 학습이 끝나면 --det 만 바꾸면 된다. 구조를 다시 짜지 않는다.
  이게 이 파일을 지금 만드는 이유다 — 개선될 때마다 파이프라인을 새로
  꿰맞추면 매번 같은 실수를 반복한다.

무엇을 하는가
  1. DICOM 을 읽고 유방 영역을 잘라낸다
  2. 원본 해상도 1008 타일로 훑어 박스를 찾는다 (종류별 상위 --topk 개)
  3. 박스마다 '마스크 상자 + 20px' 규칙으로 조각을 만든다
     (measure_crop.py 로 잰 값. CBIS ROI 조각과 같은 자르기다)
  4. 종류에 맞는 서술어 모델에 넣어 축별 서술어를 얻는다
  5. 규칙표로 BI-RADS 등급과 조직검사 여부를 낸다

메모리
  검출기와 서술어를 동시에 올리면 GPU 를 많이 쓴다. 기본은 순차 모드다 —
  검출을 끝내고 검출기를 내린 뒤 서술어를 올린다. 학습이 도는 중에도
  돌릴 수 있게 하려는 것이다. --keep-loaded 로 끄면 여러 장을 빠르게 돈다.

읽는 사람에게
  이 출력은 판독 보조다. 진단이 아니다. CBIS 는 조직검사가 확정된 사례만
  모은 집합이라 여기서 나온 확률·등급은 검진 상황의 값이 아니다.

사용
  python3 predict.py --image /path/to/image.dcm
  python3 predict.py --image ... --overlay out.png --json out.json
  python3 predict.py --image ... --det ../ckpt/last_lora.pt --topk 3
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import cv2
    import numpy as np
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_e2e import (build_model, find_rules, import_rules,   # noqa: E402
                      level_of, to_category, to_category_fine,
                      to_onehot, max_category)
from eval_end2end import (KIND_OF, BIOPSY_CUT, crop_to_tensor,  # noqa: E402
                          expand, load_rule)
from eval_mammo_det import (PROMPTS, RES, build, import_medsam3,  # noqa: E402
                            make_batch, nms, read_out)
# 합치는 함수는 실험 스크립트와 같은 것을 쓴다. 복사하면 한쪽만 고쳐졌을 때
# 시연 화면과 측정치가 조용히 어긋난다.
from mammo_io import WAYS, filter_tissue, merge_boxes_one      # noqa: E402
from make_tiles import norm8, positions, tissue_bbox, tissue_mask  # noqa: E402
from mammo_data import axis_slices, load_schema                 # noqa: E402
from make_tiles import mask_box                                 # noqa: E402
from paths import CKPT, MEDSAM3, RAW_CBIS, ROI_INDEX            # noqa: E402
from train_mammo import SCHEMA, pool_feats                      # noqa: E402

AXIS_KO = {"shape": "모양", "margin": "경계", "finding": "소견",
           "calctype": "형태", "calcdist": "분포"}
KIND_KO = {"mass": "종괴", "calcification": "미세석회"}
# 문자열 키다. birads 가 "4a" 같은 값이라 정수 키로는 안 걸린다.
GRADE_KO = {"1": "정상", "2": "양성", "3": "양성 추정",
            "4a": "낮은 악성 의심", "4b": "중등도 악성 의심",
            "4c": "높은 악성 의심", "5": "악성 강력 의심"}


def find_gt(img_path):
    """
    이 영상의 정답 병변 상자를 인덱스에서 찾는다. 없으면 빈 목록.

    왜 필요한가
      검출 결과만 그리면 맞았는지 틀렸는지 볼 방법이 없다. 첫 시연에서
      박스 4개가 한 자리에 몰려 나왔는데 정답이 없어 판단을 못 했다.
      정답을 같이 그리면 그 자리에서 답이 나온다.
    """
    import pandas as pd
    uid = None
    for part in Path(img_path).parts:
        if part.count(".") > 5:            # DICOM 시리즈 UID 처럼 생긴 것
            uid = part
    if uid is None:
        return []
    out = []
    for kind in ("mass", "calc"):
        for split in ("test", "train"):
            csv = ROI_INDEX / f"roi_index_{kind}_{split}.csv"
            if not csv.is_file():
                continue
            df = pd.read_csv(csv)
            hit = df[df["image_path"].astype(str).str.contains(uid, na=False)]
            for r in hit.to_dict("records"):
                mp = str(r.get("mask_file") or "").strip()
                if not mp or not Path(mp).is_file():
                    continue
                b, _ = mask_box(mp)
                if b is None:
                    continue
                out.append(dict(kind=kind, box=[float(v) for v in b],
                                assessment=r.get("assessment"),
                                pathology=r.get("pathology_raw"),
                                split=split))
    return out


def read_image(path):
    """DICOM 이면 pydicom, 아니면 cv2. 둘 다 2차원 배열로 돌려준다."""
    p = Path(path)
    if p.suffix.lower() in (".dcm", ".dicom") or not p.suffix:
        import pydicom
        arr = pydicom.dcmread(str(p)).pixel_array
    else:
        arr = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
    if arr is None:
        sys.exit(f"영상을 못 읽었다: {p}")
    if arr.ndim == 3:
        arr = arr[..., 0]
    if arr.ndim != 2:
        sys.exit(f"2차원이 아니다: {arr.shape}")
    return arr


# ─────────────────────── 1~2. 검출 ───────────────────────
@torch.no_grad()
def detect(a, M, arr):
    """유방 전체를 타일로 훑어 박스를 찾는다. 좌표는 원본 기준으로 돌려준다."""
    u8 = norm8(arr, a.clip)
    tmask = tissue_mask(u8)
    tb = tissue_bbox(tmask, a.pad)
    if tb is None:
        return {n: [] for n in PROMPTS}, None
    cx0, cy0, cx1, cy1 = tb
    img = u8[cy0:cy1, cx0:cx1]
    tsub = tmask[cy0:cy1, cx0:cx1] > 0      # 박스를 거를 때 쓴다
    H, W = img.shape[:2]
    stride = max(1, a.tile - a.overlap)

    # 후처리는 서빙과 **같은 함수**를 쓴다. 여기에 다시 구현하면 또 갈라진다.
    from infer_mammo import _depth_at, _depth_map, _in_any, _tile_grid
    from infer_mammo import DEFAULTS as _D
    keep_tiles = None
    if getattr(a, "tile_frac", 0):
        keep_tiles = [g for g in _tile_grid(tsub, a.tile, stride)
                      if g[4] >= a.tile_frac]
        print(f"  타일 조직 {a.tile_frac:.0%} 미만 제외 → "
              f"{len(keep_tiles)}장 남음")
    depth = _depth_map(tsub)

    dev = torch.device("cuda")
    model = build(a, M, dev)

    raw = {n: [] for n in PROMPTS}
    n_tiles = 0
    t0 = time.time()
    ys, xs = positions(H, a.tile, stride), positions(W, a.tile, stride)
    print(f"  유방 {W}x{H} · 타일 {len(ys)}x{len(xs)} = {len(ys)*len(xs)}장")
    with torch.inference_mode():
        for ty in ys:
            for tx in xs:
                sub = img[ty:ty + a.tile, tx:tx + a.tile]
                if sub.shape != (a.tile, a.tile):
                    p = np.zeros((a.tile, a.tile), np.uint8)
                    p[:sub.shape[0], :sub.shape[1]] = sub
                    sub = p
                got = read_out(model(make_batch(M, sub, dev)), a.thr)
                n_tiles += 1
                for n, lst in got.items():
                    for b in lst:
                        raw[n].append((b[0] + tx, b[1] + ty,
                                       b[2] + tx, b[3] + ty, b[4]))
    print(f"  {n_tiles}타일 · {time.time()-t0:.0f}초")

    out = {}
    for n in PROMPTS:
        # 겹친 박스를 합친다. 기본은 wbf — 2026-08-31 에 확정한 운영점이다.
        #   점수 최고 하나만 남기는 NMS 보다 서술어 단계가 더 잘 판단한다
        #   (석회 서술어 몫 91.6% -> 96.8%, 종괴 73.5% -> 75.9%).
        #   찾는 병변 수는 거의 안 변하고 박스가 정확해지는 효과다.
        # 조직 밖 박스를 먼저 버린다 — 합치기 '전' 이다.
        #
        #   시연에서 'RCC' 각인 글자 위, 피부 마커(금속 구슬) 위, 영상 가장자리
        #   공기 영역에 박스가 붙었다. 대비가 극단적이라 검출기가 끌린다.
        #   tissue_mask 로 조직 영역을 이미 계산하고 있었는데 박스를 그것으로
        #   거르지 않고 있었다.
        #
        #   합친 뒤에 거르면 각인 박스가 이미 덩어리에 섞여 가중평균 좌표를
        #   오염시킨 뒤다. 그래서 앞으로 옮겼다. merge_boxes.py 도 같은 순서다.
        #   공짜는 아니다 — 정탐도 조금 버린다(종괴 AR100 0.317 -> 0.308,
        #   석회 오탐 4개/영상 민감도 84.2% -> 83.3%). 오탐이 훨씬 많이 줄어
        #   순이득이라 쓴다.
        cand, n_out = filter_tissue(raw[n], tsub, a.tissue_frac)
        if n_out:
            print(f"      {KIND_KO.get(n, n):8s} 조직 밖 {n_out:,}개 제외 "
                  f"(박스 면적의 {a.tissue_frac:.0%} 미만이 조직)")

        merged = merge_boxes_one(cand, a.merge, a.nms)

        # 타일 조직 필터 — 조직이 거의 없는 타일에서 나온 검출을 버린다.
        # 공기가 아니라 **유방 경계선** 오탐을 지운다. 합치기 뒤에 건다 —
        # 측정을 그 순서로 했다(석회 57.9->62.1 · 종괴 56.4->60.5).
        if keep_tiles is not None:
            n_thin = len(merged)
            merged = [b for b in merged if _in_any(b, keep_tiles)]
            n_thin -= len(merged)
            if n_thin:
                print(f"      {KIND_KO.get(n, n):8s} 얇은 타일 {n_thin:,}개 제외")

        # 깊이 가중 — 경계에 붙은 것을 눌러 순위를 바꾼다. 버리지는 않는다.
        # λ 는 측정된 깊이 분리도(석회 8.2% · 종괴 19.3%)에 1.8 을 곱한 값이다.
        lam = (a.depth_lambda if getattr(a, "depth_lambda", None) is not None
               else float((_D.get("depth_lambda") or {}).get(n, 0.0)))
        if lam > 0:
            merged = [(b[0], b[1], b[2], b[3],
                       b[4] * (1.0 - lam + lam * _depth_at(depth, b)))
                      for b in merged]
            merged.sort(key=lambda b: -b[4])   # topk 가 정렬을 전제한다

        # 종류별 점수 임계값. 이게 없으면 --topk 가 점수와 무관하게 박스를
        # 강제로 내놓는다. 석회가 없는 영상에도 석회 박스가 뜨고, 서술어는
        # 그 조각을 학습 데이터 최다 조합(다형성+군집성)으로 밀고, 규칙표는
        # 그걸 BI-RADS 4 로 보낸다. 결과적으로 어떤 영상을 넣어도 '조직검사
        # 권고' 가 나온다 — 시연 6장이 전부 그랬고 그중 정답 등급 2 인 것도
        # 조직검사로 갔다. 성능이 아니라 구조 문제였다.
        #
        # 운영값은 infer_mammo.DEFAULTS 에 있다. 여기에 숫자를 다시 적지 않는다.
        # 위 후처리가 점수 척도를 내리므로 임계값도 그에 맞춰 뽑은 값이어야
        # 한다 — score_dets.py 의 '운영에 넣을 점수 임계값' 표.
        # (0.25개/영상 지점의 종괴 임계값 0.822 는 모델 점수 상한 0.816 보다
        #  높아서 종괴 검출이 0건이 된다. 그 값을 쓰면 안 된다.)
        cut = a.score_calc if n == "calcification" else a.score_mass
        kept = [b for b in merged if b[4] >= cut]
        n_drop = len(merged) - len(kept)
        if a.topk:
            kept = kept[:a.topk]
        if n_drop:
            print(f"      {KIND_KO.get(n, n):8s} 점수 {cut:.3f} 미만 "
                  f"{n_drop:,}개 제외 · 남은 {len(kept)}개")

        # 유방 영역 좌표 -> 원본 좌표. 자르기와 표시가 모두 원본 기준이다.
        out[n] = [(b[0] + cx0, b[1] + cy0, b[2] + cx0, b[3] + cy0, b[4])
                  for b in kept]

    del model
    if not a.keep_loaded:
        torch.cuda.empty_cache()      # 서술어를 올릴 자리를 만든다
    return out, tb


# ─────────────────── 3~5. 서술어 · 등급 ───────────────────
def descriptors_of(onehot, cols, slices):
    """{'calctype__PLEOMORPHIC': 1} -> {'calctype': 'PLEOMORPHIC'}"""
    out = {}
    for ax, (s, e) in slices.items():
        for c in cols[s:e]:
            if onehot.get(c):
                out[ax] = c.split("__", 1)[1]
    return out


@torch.no_grad()
def describe(a, R, arr, dets, rule, schema):
    """종류별로 모델을 하나씩 올려 박스마다 서술어와 등급을 낸다."""
    device = "cuda"
    lesions = []
    for name in PROMPTS:
        boxes = dets.get(name) or []
        if not boxes:
            continue
        kind = KIND_OF[name]
        ck = Path(a.calc if kind == "calc" else a.mass).expanduser()
        if not ck.is_file():
            print(f"  ! {kind} 서술어 체크포인트 없음: {ck} — 건너뛴다")
            continue
        ext, head, cfg = build_model(str(ck), device)
        cols, slices = cfg["cols"], axis_slices(schema, kind)

        crops, keep = [], []
        for b in boxes:
            e = expand(b[:4], rule, kind, arr.shape)
            if e is None:
                continue
            crops.append(crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                        cfg["size"], cfg["pad"], cfg["clip"]))
            keep.append((b, e))
        for i in range(0, len(crops), a.batch):
            x = torch.stack(crops[i:i + a.batch]).to(device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logit = head(pool_feats(ext(x), cfg["pool"], cfg["levels"],
                                        cfg["grid"]))
            probs = torch.sigmoid(logit.float()).cpu().numpy()
            for k, p in enumerate(probs):
                b, e = keep[i + k]
                oh = to_onehot(p, cols, slices, a.thr_desc, a.always)
                d = descriptors_of(oh, cols, slices)
                lv = level_of(R, kind, oh)
                cat = to_category(R, lv)          # 정수. biopsy 판정용
                cat_s = to_category_fine(R, lv)   # 문자열. 표시·저장용
                lesions.append(dict(
                    kind=name, box=[float(v) for v in b[:4]],
                    score=float(b[4]), crop=[int(v) for v in e],
                    descriptors=d,
                    birads=cat_s,
                    biopsy=bool(cat is not None and cat >= BIOPSY_CUT)))
        del ext, head
        if not a.keep_loaded:
            torch.cuda.empty_cache()
    lesions.sort(key=lambda x: -x["score"])
    for i, l in enumerate(lesions, 1):
        l["id"] = i
    return lesions


# ─────────────────────── 출력 ───────────────────────
def report(path, arr, lesions):
    # 성능 숫자는 infer_mammo.PERF 한 곳에서만 관리한다.
    # 여기에 숫자를 다시 적으면 또 갈라진다 — 실제로 그랬다.
    from infer_mammo import PERF as _PERF
    print("\n" + "=" * 74)
    print(f"판독 보조 결과   {Path(path).name}   {arr.shape[1]}x{arr.shape[0]}")
    print("=" * 74)
    if not lesions:
        print("  임계값을 넘는 병변 없음")
        print("\n  ※ 병변이 없다는 뜻이 아니라, 이 모델이 임계값 이상으로")
        print("    확신하는 것이 없다는 뜻이다. --score-calc / --score-mass 를")
        print("    낮추면 더 나오지만 오탐도 같이 는다.")
        return dict(n_lesions=0, max_birads=None, biopsy=False)
    for l in lesions:
        print(f"\n  [{l['id']}] {KIND_KO.get(l['kind'], l['kind'])}"
              f"   점수 {l['score']:.3f}")
        x0, y0, x1, y1 = [int(v) for v in l["box"]]
        print(f"      위치   ({x0}, {y0}) ~ ({x1}, {y1})"
              f"   {x1-x0}x{y1-y0}px")
        if l["descriptors"]:
            for ax, v in l["descriptors"].items():
                print(f"      {AXIS_KO.get(ax, ax):6s} {v}")
        else:
            print("      서술어 없음 — 등급을 낼 수 없다")
        g = l["birads"]
        print(f"      BI-RADS {g if g is not None else '—'}"
              f"  {GRADE_KO.get(g, '') if g is not None else ''}")
        print(f"      판단   {'조직검사 권고' if l['biopsy'] else '추적 관찰'}")

    grades = [l["birads"] for l in lesions if l["birads"] is not None]
    s = dict(n_lesions=len(lesions),
             max_birads=max_category(grades),
             biopsy=any(l["biopsy"] for l in lesions))
    print("\n" + "-" * 74)
    print(f"  영상 단위   병변 {s['n_lesions']}건 · 최고 등급 "
          f"{s['max_birads'] if s['max_birads'] is not None else '—'} · "
          f"{'조직검사 권고' if s['biopsy'] else '추적 관찰'}")
    print("\n  ※ 판독 보조다. 진단이 아니다. 이 모델은 조직검사가 확정된 사례로")
    print("    학습·평가됐으므로 검진 상황의 확률과는 다르다.")
    print(f"  ※ 실측 성능: 조직검사 대상 병변의 {_PERF['e2e']}% 를 스스로 찾아 판단한다")
    print("    (위치를 알려주면 90.0%). 놓친 병변이 이 화면에 안 나온다.")
    print(f"    미세석회 {_PERF['e2e_calc']}% · 종괴 {_PERF['e2e_mass']}%. "
          f"{_PERF['n_images']}명 · 에폭 {_PERF['epoch']} · {_PERF['setting']} 기준.")
    return s


def draw(arr, lesions, out, gts=()):
    im = cv2.cvtColor(norm8(arr, 99.9), cv2.COLOR_GRAY2BGR)
    h = im.shape[0]
    th = max(2, h // 700)
    fs = max(0.8, h / 2200)
    # 정답을 먼저 굵게 그린다. 검출 박스가 그 위에 겹쳐 보이도록.
    for g in gts:
        x0, y0, x1, y1 = [int(v) for v in g["box"]]
        cv2.rectangle(im, (x0, y0), (x1, y1), (0, 255, 0), th * 2)
        lab = f"GT {KIND_KO.get('calcification' if g['kind']=='calc' else 'mass')}"
        if g.get("assessment") == g.get("assessment"):
            lab += f" B{int(g['assessment'])}"
        cv2.putText(im, lab, (x0 + 3, max(20, y1 + int(30 * fs))),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 255, 0), th, cv2.LINE_AA)
    for l in lesions:
        # display 가 있으면 그것을 그린다. 미세석회는 크기를 주장하지 않는
        # 표식이라 검출 상자를 그리면 화면이 틀린 크기를 말하게 된다.
        d = l.get("display") or {}
        x0, y0, x1, y1 = [int(v) for v in (d.get("box") or l["box"])]
        # 조직검사 권고는 빨강, 추적은 노랑 — 흑백 영상 위에서 둘 다 보인다
        col = (0, 0, 255) if l["biopsy"] else (0, 200, 255)
        cv2.rectangle(im, (x0, y0), (x1, y1), col, th)
        g = l["birads"]
        lab = (f"#{l['id']} {KIND_KO.get(l['kind'], l['kind'])}"
               f" B{g if g is not None else '?'} {l['score']:.2f}")
        (tw, tt), _ = cv2.getTextSize(lab, cv2.FONT_HERSHEY_SIMPLEX, fs, th)
        cv2.rectangle(im, (x0, max(0, y0 - tt - 8)), (x0 + tw + 6, y0), col, -1)
        cv2.putText(im, lab, (x0 + 3, max(tt, y0 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th, cv2.LINE_AA)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), im)
    print(f"  표시 이미지 -> {out}   ({im.shape[1]}x{im.shape[0]})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True, help="DICOM 또는 PNG/JPG")
    # 가중치 — 개선되면 여기만 바꾼다
    ap.add_argument("--det", default=str(CKPT / "last_lora.pt"))
    ap.add_argument("--calc", default=str(CKPT / "mammo_calc_trunk_last_grid4_pad0_clip999_lora.pt"))
    ap.add_argument("--mass", default=str(CKPT / "mammo_mass_trunk_last_grid4_pad0_clip999_lora.pt"))
    ap.add_argument("--rule", default="crop_rule.json")
    ap.add_argument("--margin", type=float, default=None)
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--repo", default=str(MEDSAM3))
    # 검출
    ap.add_argument("--topk", type=int, default=2,
                    help="종류당 표시할 박스 수. 실측한 운영점은 2다")
    ap.add_argument("--tile", type=int, default=RES)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--thr", type=float, default=0.05,
                    help="타일 단계에서 후보로 받을 최소 점수. 낮게 두고 "
                         "아래 --score-* 로 최종 판단한다")
    # 종류별 최종 임계값 — infer_mammo.DEFAULTS 에서 읽는다.
    # 에폭 6 FROC 의 오탐 **1개/영상** 지점이고, 조직타일 필터와
    # 깊이 가중을 넣은 뒤 다시 뽑은 값이다(score_dets.py 의 임계값 표).
    #   0.5개/영상을 원하면 석회 0.636 · 종괴 0.801
    #   1.0개/영상을 원하면 석회 0.594 · 종괴 0.767  (민감도는 오르고 오탐도 는다)
    # 운영점은 infer_mammo.DEFAULTS 한 곳에만 둔다. 여기에 숫자를 적으면
    # 서빙과 CLI 가 또 갈라진다 — 실제로 그랬다.
    from infer_mammo import DEFAULTS as _D
    ap.add_argument("--score-calc", type=float, default=_D["score_calc"])
    ap.add_argument("--score-mass", type=float, default=_D["score_mass"])
    ap.add_argument("--tile-frac", type=float, default=_D["tile_frac"],
                    help="조직 비율이 이 값 미만인 타일에서 나온 검출을 버린다. "
                         "0 이면 안 거른다")
    ap.add_argument("--depth-lambda", type=float, default=None,
                    help="깊이 가중 세기. 안 주면 종류별 기본값 "
                         "(석회 0.15 · 종괴 0.35)")
    ap.add_argument("--tissue-frac", type=float, default=0.5,
                    help="박스 면적 중 조직이 차지해야 하는 최소 비율. "
                         "0 이면 안 거른다")
    ap.add_argument("--nms", type=float, default=0.3,
                    help="겹친 박스를 한 덩어리로 묶는 IoU 문턱")
    ap.add_argument("--merge", default="wbf", choices=list(WAYS),
                    help="덩어리를 하나로 만드는 방식. wbf 가 확정 운영점이다")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    # 서술어
    ap.add_argument("--thr-desc", type=float, default=0.5)
    ap.add_argument("--always", default="shape,margin,calctype,calcdist")
    ap.add_argument("--batch", type=int, default=2)
    # LoRA 구성 — 학습과 같아야 한다
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--target-modules",
                    default="q_proj,k_proj,v_proj,out_proj,qkv,proj,fc1,fc2,"
                            "linear1,linear2")
    ap.add_argument("--vision", type=int, default=1)
    ap.add_argument("--text", type=int, default=0)
    ap.add_argument("--detr-enc", type=int, default=1)
    ap.add_argument("--detr-dec", type=int, default=1)
    ap.add_argument("--mask-dec", type=int, default=0)
    # 출력
    ap.add_argument("--json", default="")
    ap.add_argument("--overlay", default="")
    ap.add_argument("--no-gt", action="store_true",
                    help="정답 상자를 찾지도 그리지도 않는다")
    ap.add_argument("--keep-loaded", action="store_true",
                    help="모델을 안 내린다. 여러 장 돌릴 때 빠르지만 메모리를 더 쓴다")
    a = ap.parse_args()
    a.lora = a.det                      # eval_mammo_det.build 가 쓰는 이름
    a.always = {s.strip() for s in a.always.split(",") if s.strip()}

    # chdir 뒤에 상대경로가 깨진다. 지금 굳혀둔다.
    img_path = str(Path(a.image).expanduser().resolve())
    for k in ("json", "overlay"):
        if getattr(a, k):
            setattr(a, k, str(Path(getattr(a, k)).expanduser().resolve()))
    rule = load_rule(a.rule, a.margin)

    print("=" * 74)
    print("맘모그램 판독 보조 — 검출 → 서술어 → BI-RADS → 조직검사 여부")
    print("=" * 74)
    print(f"  영상    {img_path}")
    print(f"  검출기  {Path(a.det).name}   합치기 {a.merge}@{a.nms:g} · "
          f"종류당 상한 {a.topk or '없음'}")
    print(f"  임계값  석회 {a.score_calc:.3f} · 종괴 {a.score_mass:.3f}"
          "   (오탐 1개/영상 지점 · 후처리 반영 후 재산출)")
    print(f"  서술어  {Path(a.calc).name} · {Path(a.mass).name}")

    arr = read_image(img_path)
    gts = [] if a.no_gt else find_gt(img_path)
    if gts:
        print(f"  정답    병변 {len(gts)}건 — " + " · ".join(
            f"{KIND_KO.get('calcification' if g['kind']=='calc' else 'mass')}"
            f"(등급 {g['assessment']}, {g['pathology']})" for g in gts))
    elif not a.no_gt:
        print("  정답    인덱스에서 못 찾았다 — 검출만 그린다")
    R = import_rules(a.rules)
    schema = load_schema(SCHEMA)
    M = import_medsam3(a.repo)          # 여기서 cwd 가 바뀐다

    print("\n[1/2] 병변 찾기")
    dets, tb = detect(a, M, arr)
    for n in PROMPTS:
        print(f"      {KIND_KO.get(n, n):8s} {len(dets.get(n) or [])}건")

    print("\n[2/2] 성질 기술 · 등급")
    lesions = describe(a, R, arr, dets, rule, schema)

    # 표시 영역을 서빙과 같은 함수로 정한다. 여기서 따로 만들면
    # 시연 화면과 서빙 화면이 달라진다.
    # mm 은 CLI 에 없다. 원래 크기를 안 냈으므로 잃는 것은 없다.
    from infer_mammo import DEFAULTS, add_display
    add_display(lesions, tb, None, DEFAULTS)

    summary = report(img_path, arr, lesions)

    if a.overlay:
        draw(arr, lesions, a.overlay, gts)
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(dict(
            image=img_path, size=[int(arr.shape[0]), int(arr.shape[1])],
            tissue_bbox=[int(v) for v in tb] if tb else None,
            weights=dict(detector=str(a.det), calc=str(a.calc), mass=str(a.mass)),
            settings=dict(topk=a.topk, score_threshold=a.thr, nms=a.nms,
                          crop=rule.get("mode"), margin_px=rule.get("margin_px")),
            ground_truth=gts, lesions=lesions, summary=summary),
            indent=2, ensure_ascii=False))
        print(f"  결과 -> {a.json}")


if __name__ == "__main__":
    main()
