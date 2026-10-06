#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CC·MLO 두 시야가 서로를 확인해 주는가 — 재기만 한다. 아직 안 만든다.

착상
  판독의는 사진 한 장으로 판정하지 않는다. 진짜 병변은 **CC 와 MLO 양쪽에
  다 보이고**, 조직이 겹쳐서 생긴 헛것은 한쪽에서만 보인다. 우리 검출기는
  사진 한 장씩만 본다 — 파트너 시야는 검출기가 **원리적으로 못 보는** 정보다.

  이진 분류기가 실패한 이유가 여기 걸린다. 분류기는 검출기와 같은 동결
  백본을 썼다. 특징이 같으니 새 정보가 아니었다. 성공한 둘(조직 마스크 ·
  유방 깊이)은 바깥에서 온 정보였다. 파트너 사진은 확실히 바깥이다.

1판에서 틀린 것 둘 — 둘 다 고쳤다

  ① **자의 단위가 틀렸다.**
     허용오차를 5~20 으로 줬는데 mm 를 생각하고 잡은 값이었다. 그런데 이
     자료의 DICOM 에는 화소 간격이 하나도 없어서(0/598장) 그 값이 그대로
     **화소**로 쓰였다. 병변의 유두거리 중앙값이 2,764화소니 허용오차
     15화소는 0.5% — 사실상 「같은 자리」를 요구한 것이다.

     실측 짝보유율 21~25%가 우연히 걸릴 확률(20개 × 40/5000 ≈ 16%)과
     거의 같았다. **정탐도 오탐도 순전히 우연을 재고 있었다.**

     → 절대 화소(100·200·300·400)와 유방 크기로 나눈 상대값(0.02~0.15)
       두 벌로 잰다. 화소 간격이 없어도 CC·MLO 는 같은 디지털화에서 나오니
       쌍 안에서는 화소가 비교 가능하다.

  ② **우연 수준을 안 쟀다.**
     허용오차를 키우면 정탐도 오탐도 짝보유율이 100%로 가서 아무것도 안
     갈린다. 「짝을 얼마나 갖나」가 아니라 **「엉뚱한 사진과 견줬을 때보다
     얼마나 더 갖나」**를 재야 한다.

     → 뒤섞음 대조군을 넣었다. 진짜 파트너 대신 **남의 유방**의 같은 시야
       사진과 견준다. 판정은 이 차이로 한다.

         실질차이 = (정탐: 진짜 − 뒤섞음) − (오탐: 진짜 − 뒤섞음)

순서 — 재고 나서 쓴다
  깊이 재점수에서 쓴 규율 그대로다. 안 갈리면 여기서 끝낸다.

짝 맞추는 자 — 유두로부터의 거리
  유방은 CC 와 MLO 에서 다르게 눌리지만 **유두-병변 거리는 대체로 보존된다.**
  판독에서 쓰는 표준 근사다. 유두는 조직 마스크에서 「흉벽에서 가장 먼
  조직 점」으로 잡는다.

GPU 를 안 쓴다. DICOM 을 영상당 한 번 읽고 캐시한다.

사용
  python3 training/code/check_twoview.py --recache     # 1판 캐시가 있으면 필요
  python3 training/code/check_twoview.py
"""

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])
SIDE_RE = re.compile(r"\b(LEFT|RIGHT)\b", re.I)
VIEW_RE = re.compile(r"\b(CC|MLO)\b", re.I)
PAT_RE = re.compile(r"(P[_-]\d+)", re.I)
CACHE_VER = 2                       # reach 가 늘어서 1판 캐시와 안 맞는다


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def auc(score, label):
    """정탐을 위로 올리는 능력. 라벨이 한쪽뿐이면 nan."""
    s, y = np.asarray(score, float), np.asarray(label, float)
    n1, n0 = y.sum(), (1 - y).sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(s)
    r = np.empty(len(s), float)
    r[order] = np.arange(1, len(s) + 1)
    # 동점은 평균 순위로. 짝이 없는 것이 전부 0 이라 동점이 아주 많다 —
    # 여기를 안 맞추면 AUC 가 통째로 틀어진다.
    ss = s[order]
    i = 0
    while i < len(ss):
        j = i
        while j + 1 < len(ss) and ss[j + 1] == ss[i]:
            j += 1
        if j > i:
            r[order[i:j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


# ── [1] 짝 맞추기 ──────────────────────────────────────────────────
def read_index(split):
    """인덱스 CSV 에서 uid -> (환자, 좌우, 시야)."""
    meta, cols_seen = {}, None
    for kind in E.CAT:
        csv = E.ROI_INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            continue
        df = pd.read_csv(csv)
        if cols_seen is None:
            cols_seen = list(df.columns)
        for r in df.to_dict("records"):
            path = str(r.get("image_path", ""))
            uid = path.strip().split("/")[-2] if "/" in path else ""
            if not uid:
                continue
            pat = str(r.get("patient_id") or "").strip()
            if not pat:
                m = PAT_RE.search(path)
                pat = m.group(1).upper() if m else ""
            side = str(r.get("side") or r.get("laterality") or "").strip().upper()
            if side not in ("LEFT", "RIGHT"):
                m = SIDE_RE.search(path)
                side = m.group(1).upper() if m else ""
            view = str(r.get("view") or r.get("image_view") or "").strip().upper()
            if view not in ("CC", "MLO"):
                m = VIEW_RE.search(path)
                view = m.group(1).upper() if m else ""
            if pat and side and view:
                meta[uid] = (pat, side, view)
    return meta, cols_seen


# ── [2] 유두 ───────────────────────────────────────────────────────
def nipple(mask):
    """흉벽에서 가장 먼 조직 점. 흉벽은 조직이 붙어 있는 세로 모서리."""
    m = mask > 0
    if not m.any():
        return None, None, None
    H, W = m.shape
    edge = max(1, W // 20)
    wall = "left" if m[:, :edge].sum() >= m[:, -edge:].sum() else "right"
    cols = np.where(m.any(axis=0))[0]
    if not len(cols):
        return None, None, None
    far = cols.max() if wall == "left" else cols.min()
    lo, hi = ((max(0, far - edge), far + 1) if wall == "left"
              else (far, min(W, far + edge)))
    ys = np.where(m[:, lo:hi].any(axis=1))[0]
    if not len(ys):
        return None, None, None
    nx, ny = float(far), float(np.median(ys))
    # 유방이 얼마나 멀리 뻗어 있나 — 상대 허용오차의 분모. 8화소마다 훑는다.
    yy, xx = np.nonzero(m[::8, ::8])
    if not len(xx):
        return None, None, None
    d = np.hypot(xx * 8 - nx, yy * 8 - ny)
    return (nx, ny), wall, float(np.percentile(d, 99))


def build_cache(split, clip, pad, cache, recache):
    cp = rp(cache)
    if cp.is_file() and not recache:
        j = json.loads(cp.read_text())
        if j.get("ver") == CACHE_VER:
            print(f"  캐시 사용 — {cp}  (영상 {len(j['img']):,}장)")
            return j
        print("  캐시가 1판이라 다시 만든다 (reach 가 늘었다)")
    ents = E.load_gt(split)
    uids = sorted(ents)
    name_of = {v: k for k, v in E.CAT.items()}
    alias = {"calc": "calcification", "mass": "mass"}
    img, skipped = {}, 0
    print(f"  DICOM 읽는 중 — {len(uids):,}장 (GPU 안 쓴다)")
    for i, uid in enumerate(uids, 1):
        e = ents[uid]
        try:
            arr = pydicom.dcmread(str(e["dcm"])).pixel_array
        except Exception:
            skipped += 1
            continue
        if arr.ndim != 2:
            skipped += 1
            continue
        boxes = []
        for cid, mp in e["masks"]:
            b, shp = E.mask_box(mp)
            if b is not None and shp == arr.shape[:2]:
                boxes.append((alias[name_of[cid]], b))
        if not boxes:
            skipped += 1
            continue
        u8 = E.norm8(arr, clip)
        mask = E.tissue_mask(u8)
        tb = E.tissue_bbox(mask, pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        nip, wall, reach = nipple(mask[cy0:cy1, cx0:cx1])
        if nip is None or not reach:
            skipped += 1
            continue
        # 정답도 조직 상자 기준으로. 검출 파일과 같은 기준이라야 같은 자로 잰다.
        g = defaultdict(list)
        for k, b in boxes:
            g[k].append([float(b[0] - cx0), float(b[1] - cy0),
                         float(b[2] - cx0), float(b[3] - cy0)])
        img[uid] = {"nipple": list(nip), "wall": wall, "reach": reach,
                    "gt": dict(g)}
        if i % 25 == 0 or i == len(uids):
            print(f"\r    {i}/{len(uids)}", end="", flush=True)
    print()
    if skipped:
        print(f"  건너뛴 영상 {skipped}장")
    j = {"ver": CACHE_VER, "split": split, "clip": clip, "pad": pad, "img": img}
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(j, ensure_ascii=False, default=float))
    print(f"  캐시 저장 -> {cp}")
    return j


def dist(nip, box):
    cx = (float(box[0]) + float(box[2])) / 2.0
    cy = (float(box[1]) + float(box[3])) / 2.0
    return float(np.hypot(cx - nip[0], cy - nip[1]))


def pct(v):
    if not len(v):
        return "—"
    q = np.percentile(v, [5, 50, 95])
    return f"5퍼 {q[0]:7.1f} · 중앙 {q[1]:7.1f} · 95퍼 {q[2]:7.1f}"


def hit(r, plist, tol, rel):
    """파트너에 허용오차 안의 검출이 있으면 그 최고 점수, 없으면 0."""
    best = 0.0
    for pr_px, pr_rel, ps in plist:
        if abs((pr_rel if rel else pr_px) - r) <= tol:
            best = max(best, ps)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/"
                            "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--split", default="test")
    ap.add_argument("--cache", default="docs/twoview_cache.json")
    ap.add_argument("--recache", action="store_true")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--tol-px", default="100,200,300,400")
    ap.add_argument("--tol-rel", default="0.02,0.05,0.10,0.15")
    ap.add_argument("--shuffles", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    print("=" * 92)
    print("CC·MLO 두 시야 일치 — 재기만 한다 (2판: 자를 맞추고 뒤섞음 대조군을 넣었다)")
    print("=" * 92)

    # ── [1] 짝 ──────────────────────────────────────────────────
    print("\n■ [1] 짝이 얼마나 있나")
    meta, _cols = read_index(a.split)
    if not meta:
        die("인덱스에서 환자·좌우·시야를 하나도 못 뽑았다.")
    cj = build_cache(a.split, a.clip, a.pad, a.cache, a.recache)
    img = cj["img"]
    have = [u for u in img if u in meta]

    breast = defaultdict(dict)
    for u in have:
        p, s, v = meta[u]
        breast[(p, s)][v] = u
    partner, view_of = {}, {u: meta[u][2] for u in have}
    for _b, vs in breast.items():
        if "CC" in vs and "MLO" in vs:
            partner[vs["CC"]] = vs["MLO"]
            partner[vs["MLO"]] = vs["CC"]
    print(f"  영상 {len(img):,}장 · 환자 {len({p for p, _ in breast}):,}명 · "
          f"유방 {len(breast):,}개")
    print(f"  **짝이 있는 영상 {len(partner):,}/{len(have):,}장 "
          f"({len(partner)/max(1,len(have)):.1%})**")
    if not partner:
        die("짝이 하나도 없다.")

    # ── [2] 유두 ────────────────────────────────────────────────
    print("\n■ [2] 유두를 제대로 잡았나 — 짝 맞추는 자가 여기 달렸다")
    walls = defaultdict(int)
    for u in have:
        walls[img[u]["wall"]] += 1
    print(f"  흉벽 방향 {dict(walls)}  (한쪽으로 쏠리면 잘못 잡은 것이다)")
    reach = np.array([img[u]["reach"] for u in have])
    print(f"  유방이 뻗은 거리(화소)      {pct(reach)}")
    gd = defaultdict(list)
    for u in have:
        for k, bs in img[u]["gt"].items():
            for b in bs:
                gd[k].append(dist(img[u]["nipple"], b))
    for k in PROMPTS:
        print(f"  정답 병변의 유두거리 {k:<15} {pct(np.array(gd[k]))}")
    med = float(np.median(np.concatenate([np.array(gd[k]) for k in PROMPTS
                                          if gd[k]])))
    print(f"\n  ※ 병변 유두거리 중앙값이 {med:,.0f}화소다. 1판이 쓴 허용오차 "
          f"15는 이 자의 {15/med:.2%} — 우연만 쟀다.")

    # ── 검출을 영상별로 정리 ─────────────────────────────────────
    raw = json.loads(rp(a.dets).read_text())
    pinfo = {k: defaultdict(list) for k in PROMPTS}   # kind -> uid -> [(px,rel,score)]
    byimg = {k: defaultdict(list) for k in PROMPTS}
    for k in PROMPTS:
        for d in raw.get(k, []):
            byimg[k][str(d["img"])].append(d)
        for u, ds in byimg[k].items():
            if u not in img:
                continue
            nip, rc = img[u]["nipple"], img[u]["reach"]
            for d in sorted(ds, key=lambda x: -float(x["score"]))[:a.topk]:
                r = dist(nip, d["box"])
                pinfo[k][u].append((r, r / rc, float(d["score"])))

    # 뒤섞음 대조군 — 남의 유방, 같은 시야. 시야를 맞춰야 거리 분포가 견줄 만하다.
    rnd = random.Random(a.seed)
    pool = defaultdict(list)
    for u in partner:
        pool[view_of[u]].append(u)

    rows = []          # (kind, r_px, r_rel, score, tp, 진짜목록, [뒤섞음목록…])
    for k in PROMPTS:
        for u in partner:
            if u not in img or partner[u] not in img:
                continue
            pu = partner[u]
            real = pinfo[k].get(pu, [])
            cand = pool[view_of[pu]]
            shufs = []
            for _ in range(a.shuffles):
                for _try in range(20):
                    v = cand[rnd.randrange(len(cand))]
                    if v != pu and v != u and meta[v][0] != meta[u][0]:
                        shufs.append(pinfo[k].get(v, []))
                        break
            nip, rc = img[u]["nipple"], img[u]["reach"]
            gt = img[u]["gt"].get(k, [])
            for d in sorted(byimg[k].get(u, []),
                            key=lambda x: -float(x["score"]))[:a.topk]:
                r = dist(nip, d["box"])
                rows.append((k, r, r / rc, float(d["score"]),
                             any(E.center_in(d["box"], g) for g in gt),
                             real, shufs))
    print(f"\n  견줄 검출 {len(rows):,}개 (짝이 있는 영상의 상위 {a.topk}개)")

    # ── [3] 갈리는가 ────────────────────────────────────────────
    def block(title, tols, rel):
        print(f"\n■ [3{'b' if rel else 'a'}] {title}")
        print(f"  {'종류':<15}{'허용오차':>9}{'정탐진짜':>10}{'정탐뒤섞':>10}"
              f"{'오탐진짜':>10}{'오탐뒤섞':>10}{'실질차이':>10}")
        out = {}
        for k in PROMPTS:
            sub = [r for r in rows if r[0] == k]
            for t in tols:
                got = {True: [], False: []}
                shf = {True: [], False: []}
                for r in sub:
                    x = r[2] if rel else r[1]
                    got[r[4]].append(1.0 if hit(x, r[5], t, rel) > 0 else 0.0)
                    if r[6]:
                        shf[r[4]].append(float(np.mean(
                            [1.0 if hit(x, s, t, rel) > 0 else 0.0
                             for s in r[6]])))
                m = lambda v: float(np.mean(v)) if v else float("nan")
                tr, ts = m(got[True]), m(shf[True])
                fr, fs = m(got[False]), m(shf[False])
                real = (tr - ts) - (fr - fs)
                out[k] = max(out.get(k, -9), real)
                print(f"  {k:<15}{t:>9}{tr:>10.1%}{ts:>10.1%}"
                      f"{fr:>10.1%}{fs:>10.1%}{real:>+10.1%}")
        return out

    g1 = block("절대 거리(화소)", [float(x) for x in a.tol_px.split(",")], False)
    g2 = block("유방 크기로 나눈 상대 거리",
               [float(x) for x in a.tol_rel.split(",")], True)

    # ── [4] 연속값 AUC ──────────────────────────────────────────
    print("\n■ [4] 연속값으로 — 「파트너의 짝 최고점수」가 정탐을 가르는가")
    print("  검출 점수 단독 AUC 는 0.7461 이었다. 그보다 나은 값이 나와야")
    print("  섞을 값어치가 있고, 뒤섞음보다 나아야 새 정보다.")
    print(f"\n  {'종류':<15}{'허용오차':>9}{'AUC 진짜':>10}{'AUC 뒤섞':>10}"
          f"{'차이':>9}{'검출점수와 곱해':>16}")
    g3 = {}
    for k in PROMPTS:
        sub = [r for r in rows if r[0] == k]
        if not sub:
            continue
        y = np.array([1.0 if r[4] else 0.0 for r in sub])
        ds = np.array([r[3] for r in sub])
        for t in [float(x) for x in a.tol_rel.split(",")]:
            fr = np.array([hit(r[2], r[5], t, True) for r in sub])
            fs = np.array([float(np.mean([hit(r[2], s, t, True) for s in r[6]]))
                           if r[6] else 0.0 for r in sub])
            ar, as_ = auc(fr, y), auc(fs, y)
            g3[k] = max(g3.get(k, -9), ar - as_)
            print(f"  {k:<15}{t:>9}{ar:>10.4f}{as_:>10.4f}"
                  f"{ar-as_:>+9.4f}{auc(ds*(1+fr), y):>16.4f}")
        print(f"  {'':15}{'(검출점수 단독)':>9}{auc(ds, y):>10.4f}")

    # ── 판단 ────────────────────────────────────────────────────
    print("\n" + "=" * 92)
    print("판단")
    print("=" * 92)
    print(f"  {'종류':<15}{'실질차이(절대)':>16}{'실질차이(상대)':>16}{'AUC 이득':>12}")
    ok = []
    for k in PROMPTS:
        print(f"  {k:<15}{g1.get(k, float('nan')):>+16.1%}"
              f"{g2.get(k, float('nan')):>+16.1%}{g3.get(k, float('nan')):>+12.4f}")
        if max(g1.get(k, -9), g2.get(k, -9)) > 0.03 or g3.get(k, -9) > 0.02:
            ok.append(k)
    if not ok:
        print("\n  안 갈린다. 여기서 접는다 — 재점수를 만들 값어치가 없다.")
        print("  자를 고치고 우연 수준까지 빼고 봤는데도 남는 것이 없으면,")
        print("  두 시야는 이 검출기의 오탐을 걸러 주지 못한다는 뜻이다.")
        print("  다음 후보는 Mammo-CLIP 재점수다(다른 가중치 · 다른 학습자료).")
    else:
        print(f"\n  {ok} 에서 갈린다. 만들 값어치가 있다.")
        print("  다음은 재점수 파일을 만들어 **같은 오탐 지점의 재현율**로 판정한다 —")
        print("  분류기 때와 같다. AUC 가 올라도 FROC 이 안 오를 수 있다.")
    print("\n  ※ 이 스크립트는 아무 파일도 안 고친다. 재기만 한다.")


if __name__ == "__main__":
    main()
