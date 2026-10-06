#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""「병변 위치를 잘 보여주는가」를 잰다 — 상자 모양을 고집하지 않고.

왜 이걸 만드나
  IoU 0.3 은 **상자를 전제한 지표**다. 우리가 실제로 답해야 하는 것은
  「표시한 자리에 병변이 있나」와 「엉뚱하게 넓은 데를 가리키지 않나」다.
  둘은 다른 질문이고, 지금 석회에서 갈린다.

      미세석회   중심 명중 63.7%  ·  IoU 42.1%   ← 21%p 가 상자 크기에서 날아감
      종괴       중심 명중 66.0%  ·  IoU 64.5%   ← 거의 같음. 상자가 멀쩡하다

  미세석회는 낱알이 아니라 **군집**이 병변이다. 정답 상자는 군집 전체를
  감싼다. 검출기가 낱알마다 작은 상자를 그리면 중심은 맞고 IoU 는 틀린다.
  그렇다면 근처 검출을 묶어 군집으로 보여주는 것이 맞다.

무엇을 재나

  ① 크기 진단 — 중심이 맞은 검출만 골라 정답 대비 크기를 본다.
     **작아서 틀리는지 커서 틀리는지**가 여기서 갈린다. 이 한 가지로
     다음에 할 일이 정해진다.

  ② 표시 방식 비교 — 같은 검출에서 표시 영역을 다르게 만들어 재점수한다.
       box      상자 그대로 (기준선)
       cluster  같은 종류 검출을 가까운 것끼리 묶어 합집합 상자로 (--gaps)
       grow     각 상자를 배율만큼 키운다 (--grows)
     군집은 검출 수를 줄인다. 표시가 적어지므로 **오탐 축이 유리해진다** —
     그건 눈속임이 아니라 실제로 화면에 뜨는 표시가 줄어든 것이다.

  ③ 표시 부담 — 표시 영역 넓이 / 조직 상자 넓이.
     이게 없으면 ②가 무의미하다. 유방 전체를 감싸면 IoU 도 중심도 만점이
     나오는데 화면에서는 아무것도 안 알려주는 것이다. **넓게 그려서 얻은
     점수인지 제대로 그려서 얻은 점수인지**를 이 값이 가른다.

  ※ 여기서 IoU 는 여전히 상자끼리 잰다. 정답이 상자로 주어지기 때문이다.
    화소 마스크로 재려면 마스크를 다시 읽어야 하고, 그건 「군집으로 묶는
    것이 맞는가」를 먼저 답한 뒤에 할 일이다.

사용
  python3 training/code/show_eval.py \\
      archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json

  두 번째 실행부터는 정답을 캐시에서 읽어 DICOM 을 다시 안 읽는다.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402
import score_dets as S                                        # noqa: E402

PROMPTS = S.PROMPTS


# ─────────────────────────── 정답 (캐시) ───────────────────────────
def get_gt(split, clip, pad, n, cache):
    p = Path(cache)
    if p.is_file():
        j = json.loads(p.read_text())
        if j.get("split") == split and j.get("clip") == clip \
                and j.get("pad") == pad and j.get("n") == n:
            gts = {k: {u: [tuple(b) for b in v] for u, v in d.items()}
                   for k, d in j["gts"].items()}
            origin = {u: tuple(v) for u, v in j["origin"].items()}
            print(f"  정답 캐시 사용 — {p}  (영상 {j['done']}장)")
            return gts, origin, j["done"]
        print(f"  캐시 설정이 다르다. 다시 만든다 — {p}")

    gts, origin, done, skipped = S.build_gt(split, clip, pad, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "split": split, "clip": clip, "pad": pad, "n": n,
        "done": done, "skipped": skipped,
        "gts": {k: {u: [list(b) for b in v] for u, v in d.items()}
                for k, d in gts.items()},
        "origin": {u: list(v) for u, v in origin.items()},
    }, ensure_ascii=False))
    print(f"  정답 {done}장 (버린 것 {skipped}장) · 캐시 저장 {p}")
    return gts, origin, done


# ─────────────────────────── 표시 영역 만들기 ───────────────────────────
def union(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def gap_of(a, b):
    """두 상자 사이의 빈 거리. 겹치면 0."""
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return max(dx, dy)


def clusterize(dets, gap):
    """같은 영상·같은 종류 안에서 가까운 상자를 단일 연결로 묶는다.

    군집 하나가 표시 하나가 된다. 점수는 군집 안 최대값을 쓴다 —
    화면에 뜰지 말지는 그 군집에서 가장 확신하는 검출이 정하는 것이 맞다.
    """
    by_img = defaultdict(list)
    for d in dets:
        by_img[str(d["img"])].append(d)

    out = []
    for uid, lst in by_img.items():
        boxes = [tuple(map(float, d["box"])) for d in lst]
        scores = [float(d["score"]) for d in lst]
        parent = list(range(len(lst)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(lst)):
            for j in range(i + 1, len(lst)):
                if gap_of(boxes[i], boxes[j]) <= gap:
                    a, b = find(i), find(j)
                    if a != b:
                        parent[a] = b

        groups = defaultdict(list)
        for i in range(len(lst)):
            groups[find(i)].append(i)
        for members in groups.values():
            b = boxes[members[0]]
            for m in members[1:]:
                b = union(b, boxes[m])
            out.append({"img": uid, "box": list(b),
                        "score": max(scores[m] for m in members),
                        "n_merged": len(members)})
    return out


def grow(dets, k):
    """상자를 중심 기준으로 k 배 키운다. 개수는 그대로다."""
    out = []
    for d in dets:
        x0, y0, x1, y1 = map(float, d["box"])
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        w, h = (x1 - x0) * k / 2.0, (y1 - y0) * k / 2.0
        out.append({"img": str(d["img"]), "box": [cx - w, cy - h, cx + w, cy + h],
                    "score": float(d["score"]), "n_merged": 1})
    return out


# ─────────────────────────── 채점 ───────────────────────────
def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def score_mode(dets, g, n_gt, done, origin, iou_thr, fp_points):
    """center · iou 를 작동점별로. 표시 부담도 같은 작동점에서 낸다."""
    row = {"n_show": len(dets)}
    for label, fn in (("center", lambda p, q: 1.0 if E.center_in(p, q) else 0.0),
                      ("iou", lambda p, q, t=iou_thr:
                       1.0 if E.iou(p, q) >= t else 0.0)):
        curve = E.froc(dets, n_gt, done, fn, g)
        row[label] = {t: E.at_fp(curve, t)[0] for t in fp_points}
        row[label]["max"] = max((s for _, s, _ in curve), default=0.0)
        row[label + "_thr"] = {t: E.at_fp(curve, t)[1] for t in fp_points}

    # 표시 부담 — center 곡선의 임계값을 기준으로 남는 표시만 센다
    burden = {}
    for t in fp_points:
        thr = row["center_thr"][t]
        if thr is None:
            burden[t] = float("nan")
            continue
        fr = []
        for d in dets:
            if float(d["score"]) < thr:
                continue
            o = origin.get(str(d["img"]))
            if not o:
                continue
            crop = float(o[2]) * float(o[3])
            if crop > 0:
                fr.append(area(tuple(map(float, d["box"]))) / crop)
        burden[t] = float(np.median(fr)) * 100.0 if fr else float("nan")
    row["burden"] = burden
    return row


# ─────────────────────────── 출력 ───────────────────────────
def fmt(v, w=7, p=1):
    if v is None or (isinstance(v, float) and v != v):
        return " " * (w - 1) + "-"
    return f"{v:>{w}.{p}f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dets")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--cache", default="docs/show_gt_cache.json")
    ap.add_argument("--gaps", default="0,40,80,160,320",
                    help="군집으로 묶을 최대 빈 거리(화소)")
    ap.add_argument("--grows", default="1.5,2.0,3.0",
                    help="상자 확대 배율")
    a = ap.parse_args()

    fp_points = list(getattr(E, "FP_POINTS", [0.25, 0.5, 1.0, 2.0, 4.0]))

    print("=" * 96)
    print("병변 위치를 잘 보여주는가 — 상자 모양을 고집하지 않고")
    print("=" * 96)
    gts, origin, done = get_gt(a.split, a.clip, a.pad, a.n, a.cache)
    raw = json.loads(Path(a.dets).read_text())
    keep = set(origin)
    print(f"  검출 파일 {Path(a.dets).name}")

    for kind in PROMPTS:
        g = {u: v for u, v in gts[kind].items() if v}
        n_gt = sum(len(v) for v in g.values())
        dets = [d for d in raw.get(kind, []) if str(d["img"]) in keep]
        if not n_gt or not dets:
            continue

        print("\n" + "=" * 96)
        print(f"▪ {kind}   정답 {n_gt:,}건 · 검출 {len(dets):,}개 · 영상 {done}장")
        print("=" * 96)

        # ── ① 크기 진단 ──────────────────────────────────────────
        rw, rh, ra = [], [], []
        for d in dets:
            b = tuple(map(float, d["box"]))
            for q in g.get(str(d["img"]), ()):
                if E.center_in(b, q):
                    gw, gh = q[2] - q[0], q[3] - q[1]
                    if gw > 0 and gh > 0:
                        rw.append((b[2] - b[0]) / gw)
                        rh.append((b[3] - b[1]) / gh)
                        ra.append(area(b) / (gw * gh))
                    break
        print("\n① 크기 진단 — 중심이 맞은 검출만. 정답 대비 배율")
        if ra:
            print(f"   {'':12}{'25퍼':>9}{'중앙':>9}{'75퍼':>9}{'평균':>9}   n={len(ra):,}")
            for nm, v in (("가로", rw), ("세로", rh), ("넓이", ra)):
                q = np.percentile(v, [25, 50, 75])
                print(f"   {nm:12}{q[0]:>9.2f}{q[1]:>9.2f}{q[2]:>9.2f}"
                      f"{np.mean(v):>9.2f}")
            m = float(np.median(ra))
            if m < 0.5:
                print("   → **작게 그린다.** 군집으로 묶거나 키우면 나아질 여지가 있다.")
            elif m > 2.0:
                print("   → **크게 그린다.** 묶는 것은 역효과다. 좁히는 쪽을 봐야 한다.")
            else:
                print("   → 크기는 대체로 맞다. IoU 손실은 위치 어긋남 쪽이다.")
        else:
            print("   중심이 맞은 검출이 없다.")

        # ── ②③ 표시 방식 비교 ────────────────────────────────────
        modes = [("box", dets)]
        for gp in [float(x) for x in a.gaps.split(",") if x.strip()]:
            modes.append((f"cluster {gp:g}px", clusterize(dets, gp)))
        for k in [float(x) for x in a.grows.split(",") if x.strip()]:
            modes.append((f"grow x{k:g}", grow(dets, k)))

        hdr = "".join(f"{t:>7g}" for t in fp_points)
        print(f"\n② 표시 방식별 재현율 · center 기준")
        print(f"   {'방식':<16}{'표시수':>9}{hdr}{'최대':>8}")
        rows = {}
        for name, dd in modes:
            r = score_mode(dd, g, n_gt, done, origin, a.iou, fp_points)
            rows[name] = r
            cells = "".join(fmt(100 * r["center"][t]) for t in fp_points)
            print(f"   {name:<16}{r['n_show']:>9,}{cells}"
                  f"{100*r['center']['max']:>8.1f}")

        print(f"\n   같은 것 · IoU>{a.iou} 기준")
        print(f"   {'방식':<16}{'표시수':>9}{hdr}{'최대':>8}")
        for name, _ in modes:
            r = rows[name]
            cells = "".join(fmt(100 * r["iou"][t]) for t in fp_points)
            print(f"   {name:<16}{r['n_show']:>9,}{cells}"
                  f"{100*r['iou']['max']:>8.1f}")

        print(f"\n③ 표시 부담 — 표시 하나의 넓이 / 조직 상자 넓이 (중앙값 %)")
        print(f"   {'방식':<16}{'':>9}{hdr}")
        for name, _ in modes:
            r = rows[name]
            cells = "".join(fmt(r["burden"][t], p=2) for t in fp_points)
            print(f"   {name:<16}{'':>9}{cells}")

    print("\n" + "=" * 96)
    print("읽는 법")
    print("=" * 96)
    print("""  · ① 이 먼저다. '작게 그린다' 면 군집·확대가 통할 자리이고,
    '크기는 맞다' 면 IoU 손실이 위치 어긋남이라 이 스크립트로는 못 고친다.

  · ② 에서 볼 것은 IoU 표다. center 는 묶어도 크게 안 변한다 —
    중심이 이미 맞고 있었기 때문이다. **묶어서 IoU 가 오르면 그게 답이다.**

  · ③ 없이 ② 만 보면 안 된다. 유방 전체를 감싸면 ② 는 만점이 나오는데
    화면에서는 아무것도 안 알려준다. 표시 하나가 조직 넓이의 몇 %인지가
    '제대로 가리키는가' 를 가른다. 사람이 눈으로 훑을 수 있는 크기여야 한다.

  · '표시수' 가 줄면 오탐 축이 유리해지는데 이건 눈속임이 아니다.
    화면에 실제로 뜨는 표시가 줄어든 것이고, 그게 군집으로 묶는 이유다.""")


if __name__ == "__main__":
    main()
