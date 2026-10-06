#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""발표에 쓸 예시 그림을 고르고 그린다 — 잘 된 것만 고르지 않는다.

무엇을 고르나
  성공 사례만 붙이면 발표에서 바로 걸린다. 작동점이 «종류당 오탐 2개» 라
  **헛표시가 영상당 평균 3.87개 뜬다는 것이 실측값**이다. 그 화면을 안
  보여주면 숫자와 그림이 따로 논다.

  그래서 네 갈래로 뽑는다.

    clean    정답을 다 찾고 헛표시 0 — 제일 좋은 날
    typical  정답을 찾고 헛표시 1~2 — **실제로 대부분 이 모습이다**
    miss     정답을 못 찾음 — 한계를 말할 때
    fp       정답이 없는 자리에만 표시 — 헛표시가 어떻게 생겼나

그리는 규칙은 서빙과 같게
  미세석회는 **표식**, 종괴는 **상자**. 09-05 에 정한 그대로다.
  상자로 그리면 병변이 실제보다 작다고 주장하는 그림이 되므로 여기서도 안 한다.

  정답 = **노랑** · 맞은 검출 = 파랑 · 헛표시 = 주황

  정답은 검출과 거의 겹치므로 **10화소 바깥으로 넓혀** 그린다. 안 그러면
  둘이 포개져 하나만 보인다. 범례도 그림 안에 넣는다 — 발표 화면에서
  «어느 색이 정답인가» 를 매번 설명할 수는 없다.

좌표계
  검출 파일의 상자는 **조직 상자 기준**이다. 그림도 조직 상자를 잘라서
  그리므로 변환이 없다. 파일에 박힌 frame 을 확인하고 다르면 멈춘다.

GPU 를 안 쓴다.

사용
  python3 training/code/pick_examples.py                    # 후보만 보기
  python3 training/code/pick_examples.py --render --n 3     # 갈래마다 3장씩 그리기
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])
KO = {"calcification": "미세석회", "mass": "종괴"}
THR = {"calcification": 0.448, "mass": 0.462}       # 확정 운영점
# BGR — 노랑 · 파랑 · 주황. 초록과 파랑은 서로 너무 가까워 겹치면 안 보인다.
C_GT, C_TP, C_FP = (60, 220, 255), (235, 170, 60), (60, 130, 245)
GT_PAD = 10          # 정답을 이만큼 넓혀 그린다 — 검출을 감싸게


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def legend(img):
    """그림 안 범례. 발표에서 색을 매번 설명할 수 없다."""
    x, y = 18, 18
    for c, t in ((C_GT, "Ground truth"), (C_TP, "Detected"),
                 (C_FP, "False mark")):
        cv2.rectangle(img, (x, y), (x + 26, y + 16), c, -1)
        cv2.putText(img, t, (x + 34, y + 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        y += 26


def draw(img, box, color, kind, thick=3, pad=0):
    """서빙과 같은 규칙 — 미세석회는 표식, 종괴는 상자."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    if kind == "calcification":
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        r = max(14, int(max(x1 - x0, y1 - y0) * 0.6))
        cv2.circle(img, (cx, cy), r, color, thick)
        cv2.line(img, (cx - r - 10, cy), (cx - r + 4, cy), color, thick)
        cv2.line(img, (cx + r - 4, cy), (cx + r + 10, cy), color, thick)
    else:
        cv2.rectangle(img, (x0, y0), (x1, y1), color, thick)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/"
                            "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--out", default="docs/examples")
    ap.add_argument("--n", type=int, default=3, help="갈래마다 몇 장")
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()

    print("=" * 84)
    print("발표용 예시 고르기 — 잘 된 것만 고르지 않는다")
    print("=" * 84)

    src = rp(a.dets)
    raw = json.loads(src.read_text())
    frame = raw.get("frame")
    if frame and frame != "tissue_crop":
        die(f"이 파일의 frame 이 {frame} 이다. 이 스크립트는 조직 상자 기준을 전제한다.")
    origin = {u: tuple(v) for u, v in (raw.get("origin") or {}).items()}
    print(f"  검출 {src.name} · frame={frame or '(안 박힘)'}")
    print(f"  임계값 석회 {THR['calcification']} · 종괴 {THR['mass']}")

    # ── 정답 ────────────────────────────────────────────────────
    ents = E.load_gt(a.split)
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}

    by = {k: {} for k in PROMPTS}
    for k in PROMPTS:
        for d in raw.get(k, []):
            if float(d["score"]) >= THR[k]:
                by[k].setdefault(str(d["img"]), []).append(d)

    rows = []
    print("\n  영상별로 세는 중 (DICOM 을 읽는다)")
    uids = sorted(ents)
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            continue
        if arr.ndim != 2:
            continue
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = E.mask_box(mp)
            if b is not None and shp == arr.shape[:2]:
                boxes.append((alias[name_of[cid]], b))
        if not boxes:
            continue
        if uid in origin:
            cx0, cy0, w, h = origin[uid]
        else:
            tb = E.tissue_bbox(E.tissue_mask(E.norm8(arr, a.clip)), a.pad)
            if tb is None:
                continue
            cx0, cy0, w, h = tb[0], tb[1], tb[2] - tb[0], tb[3] - tb[1]
        gt = {k: [] for k in PROMPTS}
        for k, b in boxes:
            gt[k].append((b[0] - cx0, b[1] - cy0, b[2] - cx0, b[3] - cy0))

        tp, fp, miss = [], [], []
        for k in PROMPTS:
            hit = set()
            for d in by[k].get(uid, []):
                q = tuple(map(float, d["box"]))
                j = next((n for n, g in enumerate(gt[k]) if E.center_in(q, g)), None)
                if j is None:
                    fp.append((k, q, float(d["score"])))
                else:
                    hit.add(j)
                    tp.append((k, q, float(d["score"])))
            miss += [(k, g) for n, g in enumerate(gt[k]) if n not in hit]

        n_gt = sum(len(gt[k]) for k in PROMPTS)
        if not tp and not fp and not miss:
            continue
        if miss and not tp:
            bucket = "miss"
        elif not miss and not fp:
            bucket = "clean"
        elif not miss and len(fp) <= 2:
            bucket = "typical"
        elif not tp and fp:
            bucket = "fp"
        else:
            bucket = "mixed"
        rows.append(dict(uid=uid, dcm=str(e["dcm"]), crop=(cx0, cy0, w, h),
                         gt=gt, tp=tp, fp=fp, miss=miss, n_gt=n_gt,
                         bucket=bucket,
                         score=max([s for _, _, s in tp], default=0.0)))
        if i % 50 == 0 or i == len(uids):
            print(f"\r    {i}/{len(uids)}", end="", flush=True)
    print()

    # ── 후보 ────────────────────────────────────────────────────
    order = ["clean", "typical", "miss", "fp", "mixed"]
    desc = {"clean": "정답 다 찾고 헛표시 0",
            "typical": "정답 찾고 헛표시 1~2  ← 실제로 대부분 이 모습",
            "miss": "정답을 못 찾음",
            "fp": "정답 자리엔 없고 헛표시만",
            "mixed": "찾은 것도 놓친 것도 있음"}
    print(f"\n  {'갈래':<10}{'영상':>7}   설명")
    for b in order:
        n = sum(1 for r in rows if r["bucket"] == b)
        print(f"  {b:<10}{n:>7,}   {desc[b]}")

    picks = []
    for b in order[:4]:
        c = [r for r in rows if r["bucket"] == b]
        c.sort(key=lambda r: -r["score"] if b != "miss" else -r["n_gt"])
        picks += c[:a.n]

    print(f"\n  {'갈래':<9}{'영상':<26}{'정답':>5}{'맞음':>5}{'헛것':>5}{'놓침':>5}{'최고점':>8}")
    for r in picks:
        print(f"  {r['bucket']:<9}{r['uid'][:26]:<26}{r['n_gt']:>5}"
              f"{len(r['tp']):>5}{len(r['fp']):>5}{len(r['miss']):>5}"
              f"{r['score']:>8.3f}")

    if not a.render:
        print("\n  --render 를 줘야 그림을 그린다. 지금은 고르기만 했다.")
        return

    # ── 그리기 ──────────────────────────────────────────────────
    od = rp(a.out)
    od.mkdir(parents=True, exist_ok=True)
    # 지난 판을 먼저 비운다. 갈래·영상이 바뀌면 이름이 달라져서 옛 그림이
    # 남고, 발표 자료에 옛것과 새것이 섞이면 알아볼 방법이 없다.
    old = sorted(od.glob("*.png"))
    for q in old:
        q.unlink()
    if old:
        print(f"\n  지난 그림 {len(old)}장을 지웠다")
    print(f"\n■ 그리는 중 -> {od}")
    caps = []
    for r in picks:
        arr = pydicom.dcmread(r["dcm"]).pixel_array
        cx0, cy0, w, h = r["crop"]
        u8 = E.norm8(arr, a.clip)[cy0:cy0 + h, cx0:cx0 + w]
        img = cv2.cvtColor(u8, cv2.COLOR_GRAY2BGR)
        for k in PROMPTS:
            for g in r["gt"][k]:
                draw(img, g, C_GT, k, 2, GT_PAD)
        for k, q, _s in r["tp"]:
            draw(img, q, C_TP, k, 3)
        for k, q, _s in r["fp"]:
            draw(img, q, C_FP, k, 2)
        legend(img)
        sc = a.width / img.shape[1]
        img = cv2.resize(img, (a.width, int(img.shape[0] * sc)),
                         interpolation=cv2.INTER_AREA)
        out = od / f"{r['bucket']}_{r['uid'][:40]}.png"
        cv2.imwrite(str(out), img)
        caps.append(f"{out.name}\n"
                    f"  {desc[r['bucket']]}\n"
                    f"  정답 {r['n_gt']} · 맞음 {len(r['tp'])} · "
                    f"헛표시 {len(r['fp'])} · 놓침 {len(r['miss'])}\n")
        print(f"  {out.name}")

    (od / "caption.txt").write_text(
        "발표용 예시 — 노랑 정답 · 파랑 맞은 검출 · 주황 헛표시\n"
        "정답은 10화소 넓혀 그렸다 (검출과 겹쳐서 안 보이는 것을 막으려고)\n"
        "미세석회는 표식, 종괴는 상자 (서빙과 같은 규칙)\n"
        "작동점 종류당 오탐 2개 · 임계값 석회 0.448 · 종괴 0.462\n\n"
        + "\n".join(caps), encoding="utf-8")
    print(f"\n  설명은 {od/'caption.txt'} 에 적어 뒀다.")
    print("""
  ※ typical 갈래를 반드시 한 장은 넣을 것. 헛표시가 없는 그림만 붙이면
    «영상당 3.87개» 라는 실측값과 그림이 따로 논다. 발표에서 바로 걸린다.""")


if __name__ == "__main__":
    main()
