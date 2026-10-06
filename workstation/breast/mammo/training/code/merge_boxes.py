#!/usr/bin/env python
"""
겹침 합치는 방식을 바꿔 본다 — 추론을 다시 하지 않는다. GPU 를 안 쓴다.

왜
  타일 하나에서 나온 박스를 영상 좌표로 되돌리면, 이웃 타일이 같은 병변을
  겹쳐 본 박스들이 함께 쌓인다. 지금은 NMS 로 그중 점수가 가장 높은 하나만
  남긴다. 그런데 타일 경계에 걸친 병변은 그 하나가 '잘린 박스' 일 수 있다.
  종괴는 200~600px 인데 타일 겹침이 256px 라 자주 걸린다.

  세 측정이 같은 곳을 가리킨다.
    · 종괴 AP75  0.088 -> 0.022     박스가 정답과 덜 맞는다
    · 종괴가 낮은 오탐 구간에서 약하다
    · 끝단에서 박스 때문에 4.4%p 를 잃는다 (종괴 서술어는 윤곽의 기하를 본다)

무엇을 비교하나
  nms     지금 방식. 덩어리에서 점수 최고 박스 하나.
  union   덩어리를 감싸는 최소 사각형. 잘린 박스들이 합쳐져 온전해진다.
          대신 오탐끼리 뭉치면 박스가 쓸데없이 커진다.
  wbf     점수로 가중한 좌표 평균. union 과 nms 의 중간.
          (Weighted Boxes Fusion. 점수는 덩어리 최고값을 그대로 쓴다 —
           덩어리 크기로 점수를 올리면 순위가 바뀌어 비교가 흐려진다.)

  덩어리 묶는 IoU 문턱도 같이 훑는다. 지금 값은 0.3 이다.

주의
  합치기 전 파일은 영상·종류당 상위 300개까지만 담겨 있다(--raw-topk).
  오탐 4개/영상 구간은 영상당 4개꼴이라 온전히 덮이지만, 최대 재현율
  구간(영상당 1,000개)은 잘려 있다. 곡선 끝은 읽지 마라.

  박스에 타일 번호가 없다. 그래서 '타일 간 점수 보정' 은 여기서 못 한다 —
  다음 평가부터 --save-raw 가 타일 좌표를 같이 남긴다.

사용
  python3 merge_boxes.py --raw ../../archive/outputs/tile_raw_ep6.json
  python3 merge_boxes.py --raw ... --iou-sweep 0.2,0.3,0.5 --out ../../docs/merge.json
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_det import at_fp, center_in, froc, iou              # noqa: E402,F401
# 합치는 방식은 서빙과 같은 구현을 쓴다 — 여기서 실험해 고른 wbf 가 그대로
# 시연에 나가야 한다. 복사본을 두면 한쪽만 고쳐진다 (mammo_io.py 머리말).
from mammo_io import (PROMPTS, WAYS, cluster,                 # noqa: E402,F401
                      m_nms, m_union, m_wbf)
from make_tiles import norm8, tissue_bbox, tissue_mask        # noqa: E402
# tile_map 은 pycocotools 를 요구하므로 여기서 부르지 않는다. 정답을 만들 때만
# 필요하고, predict.py 는 이 파일에서 합치는 함수만 가져다 쓴다 —
# 시연 스크립트가 COCO 의존성 때문에 죽으면 안 된다.

FP_POINTS = (0.25, 0.5, 1.0, 2.0, 4.0)
CID_NAME = {1: "mass", 2: "calcification"}


def merge(raw_by_img, way, thr, stats=None):
    """{uid: [(x0,y0,x1,y1,s)]} -> [dict(img,box,score)]"""
    fn = WAYS[way]
    out = []
    for uid, boxes in raw_by_img.items():
        for grp in cluster(boxes, thr):
            if stats is not None:
                stats.append(len(grp))
            b = fn(grp)
            out.append(dict(img=uid, box=list(b[:4]), score=float(b[4])))
    return out


def show_clusters(by, thr):
    """
    합칠 거리가 있는지 먼저 본다.

    덩어리가 거의 다 크기 1 이면 union 이든 wbf 든 nms 와 같은 답을 낸다.
    그러면 이 실험은 '효과 없음' 이 아니라 '해당 없음' 이고, 박스 품질은
    다른 방법으로 고쳐야 한다. 표를 다 뽑고 나서 알면 늦다.
    """
    print(f"\n  덩어리 크기 분포  (문턱 {thr:g})")
    print(f"    {'종류':14s}{'덩어리':>9s}{'크기1':>9s}{'2~3':>8s}"
          f"{'4+':>8s}{'최대':>7s}")
    print("    " + "-" * 56)
    any_merge = False
    for n in PROMPTS:
        sizes = [len(g) for boxes in by[n].values() for g in cluster(boxes, thr)]
        if not sizes:
            continue
        s = np.array(sizes)
        one = int((s == 1).sum())
        print(f"    {n:14s}{len(s):>9,}{one:>9,}"
              f"{int(((s >= 2) & (s <= 3)).sum()):>8,}"
              f"{int((s >= 4).sum()):>8,}{int(s.max()):>7d}")
        if one < 0.95 * len(s):
            any_merge = True
    if not any_merge:
        print("    ! 거의 전부 크기 1 이다. 이 문턱에서는 합칠 것이 없어")
        print("      union·wbf 가 nms 와 같은 답을 낸다.")
    return any_merge


# ─────────────────────── 정답 ───────────────────────
def get_gt(uids, split, clip, pad, cache):
    """
    정답을 한 번만 만든다. DICOM 을 598장 읽으므로 10~15분이다.
    전략마다 다시 만들면 그 시간이 전략 수만큼 곱해진다.
    """
    p = Path(cache) if cache else None
    if p and p.is_file():
        d = json.loads(p.read_text())
        print(f"  정답 캐시 사용  {p}  (영상 {len(d['idmap'])}장)")
        return d["gt"], d["idmap"]
    print("  정답 재구성 — DICOM 을 읽는다. 10~15분.")
    import tile_map                      # pycocotools 는 여기서만 필요하다
    gt, idmap = tile_map.build(uids, split, clip, pad)
    if p:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(gt=gt, idmap=idmap)))
        print(f"  캐시 저장 -> {p}   (다음 실행은 즉시)")
    return gt, idmap


def get_tissue(by, uids, clip, pad, cache):
    """
    박스마다 '면적 중 조직이 차지하는 비율' 을 잰다. {uid: {종류: [비율,...]}}

    왜
      시연에서 검출 박스가 'RCC' 각인 글자, 피부 마커(금속 구슬), 영상
      가장자리 공기 영역에 붙는 것을 봤다. 대비가 극단적이라 검출기가 끌린다.
      tissue_mask 로 조직 영역을 이미 계산하고 있었는데 박스를 그것으로
      거르지 않고 있었다. 그래서 지금까지의 오탐 수치가 부풀려져 있다.
      얼마나인지를 재는 것이 이 함수의 목적이다.

    순서
      합치기 '전' 에 거른다. 각인 박스가 덩어리에 섞이면 가중평균 좌표를
      오염시킨다. (predict.py 도 같은 순서로 맞췄다.)

    비율은 원본 박스 순서대로 저장한다 — 원본 파일이 고정이라 순서가 안 변한다.
    DICOM 을 598장 읽으므로 10~20분. 캐시하면 다음부터 즉시다.
    """
    p = Path(cache) if cache else None
    if p and p.is_file():
        d = json.loads(p.read_text())
        if d.get("n_box") == sum(len(v) for n in by for v in by[n].values()):
            print(f"  조직 비율 캐시 사용  {p}")
            return d["frac"]
        print(f"  ! 캐시의 박스 수가 다르다 — 다시 잰다")
    import pydicom
    from eval_mammo_det import load_gt
    ents = load_gt("test")
    out, done = {}, 0
    print("  조직 비율 측정 — DICOM 을 읽는다. 10~20분.")
    for uid in uids:
        e = ents.get(uid)
        if e is None:
            continue
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            continue
        if arr.ndim != 2:
            continue
        m = tissue_mask(norm8(arr, clip))
        tb = tissue_bbox(m, pad)
        if tb is None:
            continue
        cx0, cy0, cx1, cy1 = tb
        sub = m[cy0:cy1, cx0:cx1] > 0        # 검출 좌표와 같은 기준
        h, w = sub.shape
        per = {}
        for n in PROMPTS:
            fr = []
            for b in by[n].get(uid, []):
                x0, y0 = max(0, int(b[0])), max(0, int(b[1]))
                x1, y1 = min(w, int(b[2])), min(h, int(b[3]))
                fr.append(float(sub[y0:y1, x0:x1].mean())
                          if x1 > x0 and y1 > y0 else 0.0)
            per[n] = fr
        out[uid] = per
        done += 1
        if done % 25 == 0:
            print(f"\r    {done}/{len(uids)}   ", end="", flush=True)
    print(f"\r    {done}장 완료          ")
    if p:
        p.write_text(json.dumps(dict(
            n_box=sum(len(v) for n in by for v in by[n].values()), frac=out)))
        print(f"  캐시 저장 -> {p}")
    return out


def apply_tissue(by, frac, thr):
    """조직 비율이 문턱 미만인 박스를 버린다. 종류별 제외 수를 돌려준다."""
    drop = {n: 0 for n in PROMPTS}
    for n in PROMPTS:
        for uid, boxes in list(by[n].items()):
            f = (frac.get(uid) or {}).get(n)
            if not f or len(f) != len(boxes):
                continue                      # 못 잰 영상은 손대지 않는다
            keep = [b for b, v in zip(boxes, f) if v >= thr]
            drop[n] += len(boxes) - len(keep)
            by[n][uid] = keep
    return drop


def froc_gt_from(gt_dict, idmap):
    rev = {v: k for k, v in idmap.items()}
    out = {n: defaultdict(list) for n in PROMPTS}
    for a in gt_dict["annotations"]:
        uid = rev.get(a["image_id"])
        if uid is None:
            continue
        x, y, w, h = a["bbox"]
        out[CID_NAME[a["category_id"]]][uid].append((x, y, x + w, y + h))
    return out


# ─────────────────────── 채점 ───────────────────────
def score_one(dets, gt, n_img, iou_hit):
    g = {u: v for u, v in gt.items() if v}
    n_gt = sum(len(v) for v in g.values())
    if not n_gt:
        return None
    res = {}
    for label, fn in (("center", lambda p, q: 1.0 if center_in(p, q) else 0.0),
                      ("iou", lambda p, q: 1.0 if iou(p, q) >= iou_hit else 0.0)):
        curve = froc(dets, n_gt, n_img, fn, g)
        res[label] = {t: at_fp(curve, t)[0] for t in FP_POINTS}
        res[label]["max"] = max((s for _, s, _ in curve), default=0.0)
    res["n_det"] = len(dets)
    return res


def coco_map(dets_by_name, gt_dict, idmap):
    """AP75 가 이 실험의 핵심 지표다 — 박스가 얼마나 딱 맞는지를 본다."""
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError:
        return None
    import contextlib
    import io
    tmp = Path(".merge_gt.json")
    tmp.write_text(json.dumps(gt_dict))
    out = {}
    with contextlib.redirect_stdout(io.StringIO()):
        gt = COCO(str(tmp))
        rows = []
        for name, lst in dets_by_name.items():
            cid = 1 if name == "mass" else 2
            for d in lst:
                iid = idmap.get(d["img"])
                if iid is None:
                    continue
                x0, y0, x1, y1 = d["box"]
                if x1 <= x0 or y1 <= y0:
                    continue
                rows.append(dict(image_id=iid, category_id=cid,
                                 bbox=[x0, y0, x1 - x0, y1 - y0],
                                 score=d["score"]))
        if not rows:
            tmp.unlink(missing_ok=True)
            return None
        dt = gt.loadRes(rows)
        for name, cid in (("mass", 1), ("calcification", 2)):
            E = COCOeval(gt, dt, "bbox")
            E.params.imgIds = sorted(idmap.values())
            E.params.catIds = [cid]
            E.evaluate(); E.accumulate(); E.summarize()
            out[name] = dict(mAP=float(E.stats[0]), AP50=float(E.stats[1]),
                             AP75=float(E.stats[2]), AR100=float(E.stats[8]))
    tmp.unlink(missing_ok=True)
    return out


# ─────────────────────── 본체 ───────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True, help="--save-raw 로 저장한 합치기 전 박스")
    ap.add_argument("--ways", default="nms,union,wbf")
    # 낮은 쪽까지 훑는다.
    #   타일 경계에 좌우로 잘린 종괴 두 조각의 IoU 를 손으로 계산해 보니
    #   0.143 이었다. 현행 문턱 0.3 으로는 애초에 안 묶인다 — 둘 다 살아남아
    #   따로 검출로 세어진다. 그러니 0.3 에서 union 을 해봐야 nms 와 같다.
    #   합칠 거리가 있으려면 문턱을 훨씬 낮춰야 한다. 대신 낮추면 서로 다른
    #   병변까지 뭉칠 위험이 생기므로 훑어서 정한다.
    ap.add_argument("--iou-sweep", default="0.05,0.1,0.2,0.3",
                    help="덩어리를 묶는 IoU 문턱. 쉼표로 여러 개")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou-hit", type=float, default=0.3)
    ap.add_argument("--gt-cache", default="merge_gt_cache.json")
    ap.add_argument("--tissue-frac", type=float, default=0.0,
                    help="박스 면적 중 조직 비율이 이 값 미만이면 버린다. "
                         "0 이면 안 거른다. 운영값은 0.5")
    ap.add_argument("--tissue-cache", default="merge_tissue_cache.json")
    ap.add_argument("--limit", type=int, default=0, help="영상 수 제한 (빠른 확인용)")
    ap.add_argument("--no-map", action="store_true", help="mAP 를 건너뛴다 (빠르다)")
    ap.add_argument("--out", default="")
    # 고른 방식으로 만든 검출을 저장한다. eval_end2end.py 가 그대로 읽는다.
    # 방식과 문턱을 하나씩만 준 경우에만 저장한다 — 12가지를 다 저장하면
    # 파일이 수백 MB 이고, 어느 것을 쓴 결과인지도 흐려진다.
    ap.add_argument("--save-dets", default="",
                    help="합친 검출을 JSON 으로 저장 (--ways·--iou-sweep 를 "
                         "하나씩만 준 경우에만)")
    a = ap.parse_args()

    print("=" * 76)
    print("겹침 합치는 방식 비교 — 추론 없이, CPU 로")
    print("=" * 76)

    raw = json.loads(Path(a.raw).expanduser().resolve().read_text())
    by = {n: defaultdict(list) for n in PROMPTS}
    for name, lst in raw.items():
        if name not in by:
            continue
        for d in lst:
            b = [float(v) for v in d["box"]]
            by[name][d["img"]].append((b[0], b[1], b[2], b[3], float(d["score"])))
    uids = sorted({u for n in by for u in by[n]})
    if a.limit:
        uids = uids[:a.limit]
        for n in by:
            by[n] = {u: v for u, v in by[n].items() if u in set(uids)}
    tot = sum(len(v) for n in by for v in by[n].values())
    print(f"  합치기 전 박스 {tot:,}개 · 영상 {len(uids)}장")
    print(f"  ! 영상·종류당 상위 300개까지만 담긴 파일이다. 오탐 4개/영상")
    print(f"    구간은 온전하지만 곡선 끝(최대 재현율)은 잘려 있다.")

    if a.tissue_frac > 0:
        frac = get_tissue(by, uids, a.clip, a.pad, a.tissue_cache)
        drop = apply_tissue(by, frac, a.tissue_frac)
        left = sum(len(v) for n in by for v in by[n].values())
        print(f"  조직 필터 {a.tissue_frac:.0%} — 제외 "
              + " · ".join(f"{n} {drop[n]:,}" for n in PROMPTS)
              + f"   (전체 {tot:,} -> {left:,})")

    gt_dict, idmap = get_gt(uids, a.split, a.clip, a.pad, a.gt_cache)
    fgt = froc_gt_from(gt_dict, idmap)
    n_img = len(idmap)
    for n in PROMPTS:
        print(f"  정답  {n:14s} {sum(len(v) for v in fgt[n].values()):4d}건 / "
              f"{len([1 for v in fgt[n].values() if v])}장")

    ways = [w.strip() for w in a.ways.split(",") if w.strip() in WAYS]
    thrs = [float(t) for t in a.iou_sweep.split(",") if t.strip()]
    results = {}

    # 채점하기 전에 합칠 거리가 있는지 본다. 없으면 표를 뽑을 이유가 없다.
    print("\n" + "=" * 76)
    print("먼저 — 합칠 것이 있는가")
    print("=" * 76)
    live = [t for t in thrs if show_clusters(by, t)]
    if not live:
        print("\n  어느 문턱에서도 합칠 것이 없다. 잘린 박스가 서로 안 겹친다는")
        print("  뜻이고, 박스 품질은 합치기 방식이 아니라 다른 데서 고쳐야 한다.")
        print("  (타일 겹침을 늘리거나, 병변이 타일 가운데 오도록 훑는 식)")
        return
    if len(live) < len(thrs):
        print(f"\n  합칠 것이 있는 문턱만 채점한다: "
              f"{', '.join(f'{t:g}' for t in live)}")
        thrs = live

    for thr in thrs:
        for way in ways:
            key = f"{way}@{thr:g}"
            t0 = time.time()
            dets = {n: merge(by[n], way, thr) for n in PROMPTS}
            r = {}
            for n in PROMPTS:
                s = score_one(dets[n], fgt[n], n_img, a.iou_hit)
                if s:
                    r[n] = s
            if not a.no_map:
                m = coco_map(dets, gt_dict, idmap)
                if m:
                    for n in m:
                        r.setdefault(n, {})["map"] = m[n]
            results[key] = r
            print(f"  {key:12s} 완료 ({time.time()-t0:.0f}초 · 박스 "
                  f"{sum(len(v) for v in dets.values()):,}개)")
            if a.save_dets and len(ways) == 1 and len(thrs) == 1:
                p = Path(a.save_dets).expanduser().resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(json.dumps(dets, default=float))
                print(f"    검출 저장 -> {p}   ({p.stat().st_size/2**20:.0f}MB)")
                print(f"    eval_end2end.py --dets {p} 로 끝단을 다시 잰다")

    # ── 표 ──
    for n in PROMPTS:
        print("\n" + "=" * 76)
        print(f"{n}   FROC 민감도 (중심 명중)")
        print("=" * 76)
        print(f"  {'방식':12s}" + "".join(f"{f'{t}FP':>9s}" for t in FP_POINTS)
              + f"{'검출수':>10s}")
        print("  " + "-" * 62)
        for k, v in results.items():
            if n not in v or "center" not in v[n]:
                continue
            c = v[n]["center"]
            print(f"  {k:12s}" + "".join(f"{c[t]:8.1%} " for t in FP_POINTS)
                  + f"{v[n]['n_det']:>10,}")

        print(f"\n  IoU>{a.iou_hit:.1f} 명중 (박스 정확도까지 요구)")
        print(f"  {'방식':12s}" + "".join(f"{f'{t}FP':>9s}" for t in FP_POINTS))
        print("  " + "-" * 52)
        for k, v in results.items():
            if n not in v or "iou" not in v[n]:
                continue
            c = v[n]["iou"]
            print(f"  {k:12s}" + "".join(f"{c[t]:8.1%} " for t in FP_POINTS))

        if any("map" in v.get(n, {}) for v in results.values()):
            print(f"\n  COCO   ★ AP75 가 이 실험의 핵심이다")
            print(f"  {'방식':12s}{'mAP':>9s}{'AP50':>9s}{'AP75':>9s}{'AR100':>9s}")
            print("  " + "-" * 48)
            for k, v in results.items():
                m = v.get(n, {}).get("map")
                if m:
                    print(f"  {k:12s}{m['mAP']:9.3f}{m['AP50']:9.3f}"
                          f"{m['AP75']:9.3f}{m['AR100']:9.3f}")

    print("\n" + "=" * 76)
    print("읽는 법")
    print("=" * 76)
    print("  nms@0.3 이 현행이다. 다른 줄이 그보다 나은지만 보면 된다.")
    print("  종괴에서 AP75 와 'IoU 명중' 이 올라가면 성공이다 — 박스가 정답과")
    print("  더 맞는다는 뜻이고, 끝단에서 서술어가 잃던 몫이 줄어든다.")
    print("  중심 명중은 거의 안 변할 수 있다. 위치는 원래 맞히고 있었다.")
    print("\n  union 이 오탐 구간에서 나빠지면 오탐끼리 뭉쳐 박스가 커진 것이다.")
    print("  그 경우 wbf 나 더 높은 문턱(0.5)을 봐라.")
    print("\n  ! 좋아진 방식이 있어도 그것만으로 끝단 수치가 확정되지는 않는다.")
    print("    eval_end2end.py 를 그 방식으로 만든 검출로 다시 돌려야 한다.")

    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n  -> {a.out}")


if __name__ == "__main__":
    main()
