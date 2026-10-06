#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""맞바꿈 곡선 — **양쪽 다 VinDr** 로. 자료가 섞인 문제를 없앤다.

앞 표의 구멍
  tradeoff.py 는 민감도를 CBIS(스캔 필름 · 조직검사 확정 사례)에서,
  정상을 VinDr(디지털 · 베트남 검진)에서 가져왔다. **같은 문턱값이 두
  자료에서 같은 뜻이라는 보장이 없다.** 발표에서 반드시 나올 질문이다.

  VinDr 양성 443장이 이미 디스크에 있고 검출도 이미 계산돼 있다
  (archive/outputs/vindr_dets.json). 그걸로 민감도를 재면 양쪽이 같은
  자료가 되고 그 질문이 사라진다.

경로를 score_vindr 와 똑같이 간다
  검출 파일의 점수는 **후처리 전** 값이다. 우리 운영점은
  「조직 타일 30% + 깊이 가중(CBIS λ)」을 씌운 뒤의 점수라, 그 두 가지를
  똑같이 씌워야 문턱값이 비교된다. 그래서 score_vindr 의 함수를 그대로
  불러 쓴다 — 다시 짜면 좌표가 어긋난다.

    · read_dicom 으로 읽는다 (MONOCHROME1 을 뒤집는다)
    · 조직 상자로 자르고 자른 영상 기준 좌표로 둔다
    · 타일 격자는 자른 영상 위 (0,0) 부터
    · 깊이 가중 λ 는 CBIS 에서 온 값 그대로 (석회 0.15 · 종괴 0.35)

  ⚠ vindr_dets_scaled.json 이 아니라 **vindr_dets.json** 을 쓴다.
    정상 쪽은 infer_mammo.predict() 로 배율 없이 돌렸다. 섞으면 안 된다.

사용
  python3 training/code/tradeoff_vindr.py            # 화소 읽기 포함 (수 분)
  python3 training/code/tradeoff_vindr.py --no-cache
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

CODE = Path(__file__).resolve().parent
REPO = CODE.parents[1]
OUT = REPO / "archive" / "outputs"
sys.path.insert(0, str(CODE))

import eval_vindr as V                                        # noqa: E402
import score_vindr as SV                                      # noqa: E402
from eval_det import center_in, froc                          # noqa: E402

DETS = OUT / "vindr_dets.json"
NORM = OUT / "normal_dets.jsonl"
CACHE = OUT / "vindr_pos_cache.json"
GRID = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
TILE_FRAC = 0.30                       # 운영점
LAM = SV.CBIS_LAMBDA                   # {"calcification":0.15, "mass":0.35}


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def prepare(raws, clip, pad, tile, stride, iou_thr):
    """화소를 한 번 읽어 검출마다 깊이와 타일 통과 여부를 매긴다."""
    imgs = {}
    for ext in ("*.dicom", "*.dcm", "*.DCM"):
        for f in V.RAW_VINDR.rglob(ext):
            imgs[f.stem] = f
    if not imgs:
        die("VinDr DICOM 을 못 찾았다.")
    gt = V.load_gt(str(V.LABELS / "finding_annotations.csv"), set(imgs))

    used = set()
    for n in V.PROMPTS:
        used |= {str(x["img"]) for x in raws.get(n, [])}
    uids = sorted(u for u in gt if u in used and u in imgs)
    print(f"  검출 파일의 영상 {len(used):,}장 · 정답과 이어지는 것 {len(uids):,}장")
    if len(uids) < 0.9 * len(used):
        die("이어지는 영상이 너무 적다 — 정답 경로가 다르다.")

    pos = {n: defaultdict(list) for n in V.PROMPTS}
    for n in V.PROMPTS:
        for i, d in enumerate(raws.get(n, [])):
            pos[n][str(d["img"])].append(i)
    dep = {n: np.full(len(raws.get(n, [])), np.nan) for n in V.PROMPTS}
    tok = {n: np.zeros(len(raws.get(n, [])), bool) for n in V.PROMPTS}
    gts = {n: defaultdict(list) for n in V.PROMPTS}
    done, skipped = 0, 0

    print("  화소 읽는 중 (영상당 한 번)")
    for i, iid in enumerate(uids, 1):
        arr, _mm, _ph = V.read_dicom(imgs[iid])
        if arr is None:
            skipped += 1
            continue
        u8 = V.norm8(arr, clip)
        tmask = V.tissue_mask(u8)
        tb = V.tissue_bbox(tmask, pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        tsub = tmask[cy0:cy1, cx0:cx1] > 0
        import cv2
        dist = cv2.distanceTransform(tsub.astype(np.uint8), cv2.DIST_L2, 5)
        mx = float(dist.max())
        depth = dist / mx if mx > 0 else dist

        for name, b in gt[iid]:
            gts[name][iid].append((b[0] - cx0, b[1] - cy0,
                                   b[2] - cx0, b[3] - cy0))
        tiles = [x for x in SV.grid_of(tsub, tile, stride) if x[4] >= TILE_FRAC]
        for n in V.PROMPTS:
            for j in pos[n].get(iid, ()):
                b = raws[n][j]["box"]
                dep[n][j] = SV.depth_at(depth, b)
                tok[n][j] = SV.in_any(b, tiles)
        done += 1
        if i % 20 == 0 or i == len(uids):
            print(f"\r    {i}/{len(uids)}", end="", flush=True)
    print()
    print(f"  채점 대상 {done}장" + (f" · 못 읽은 것 {skipped}장" if skipped else ""))
    return gts, dep, tok, done


def cache_save(gts, dep, tok, done):
    CACHE.write_text(json.dumps({
        "done": done,
        "gts": {n: {u: [list(b) for b in v] for u, v in kv.items()}
                for n, kv in gts.items()},
        "dep": {n: [None if np.isnan(x) else float(x) for x in v]
                for n, v in dep.items()},
        "tok": {n: [bool(x) for x in v] for n, v in tok.items()},
    }, ensure_ascii=False), encoding="utf-8")


def cache_load():
    d = json.loads(CACHE.read_text(encoding="utf-8"))
    gts = {n: defaultdict(list, {u: [tuple(b) for b in v] for u, v in kv.items()})
           for n, kv in d["gts"].items()}
    dep = {n: np.array([np.nan if x is None else x for x in v], float)
           for n, v in d["dep"].items()}
    tok = {n: np.array(v, bool) for n, v in d["tok"].items()}
    return gts, dep, tok, d["done"]


def sens_at(curve, t):
    v = [s for _f, s, th in curve if th is not None and th >= t]
    return max(v) if v else 0.0


def normals_at(t):
    last = {}
    for line in NORM.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            last[r["image_id"]] = r
    recs = [r for r in last.values() if "error" not in r]
    fire, biop = defaultdict(bool), defaultdict(bool)
    nf = 0
    for r in recs:
        k = [l for l in r["lesions"] if l["score"] >= t]
        if k:
            nf += 1
            fire[r["study_id"]] = True
        else:
            fire.setdefault(r["study_id"], False)
        if any(l["biopsy"] for l in k):
            biop[r["study_id"]] = True
        else:
            biop.setdefault(r["study_id"], False)
    ns = len(fire) or 1
    return {"img": nf / len(recs) * 100,
            "recall": sum(fire.values()) / ns * 100,
            "biopsy": sum(biop.values()) / ns * 100,
            "n_img": len(recs), "n_st": ns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--tile", type=int, default=1008)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()
    stride = max(1, a.tile - a.overlap)

    for p in (DETS, NORM):
        if not p.is_file():
            die(f"없는 파일: {p}")

    print("=" * 86)
    print("맞바꿈 곡선 — 양쪽 다 VinDr")
    print("=" * 86)
    print(f"  검출 파일 {DETS.name}  (배율 없음 — 정상 쪽과 같은 조건)")
    print(f"  후처리    조직 타일 {TILE_FRAC:.0%} + 깊이 가중 {LAM}")

    raws = json.loads(DETS.read_text(encoding="utf-8"))
    if not a.no_cache and CACHE.is_file():
        gts, dep, tok, done = cache_load()
        print(f"  캐시를 썼다 — {CACHE.name} (영상 {done}장)")
    else:
        gts, dep, tok, done = prepare(raws, a.clip, a.pad, a.tile, stride, a.iou)
        cache_save(gts, dep, tok, done)
        print(f"  캐시 저장 -> {CACHE.name}")

    # 후처리를 씌운 검출로 곡선을 만든다
    cur, ngt = {}, {}
    for n in V.PROMPTS:
        g = {u: v for u, v in gts[n].items() if v}
        ngt[n] = sum(len(v) for v in g.values())
        d = []
        for j, x in enumerate(raws.get(n, [])):
            if not tok[n][j]:
                continue                      # 조직 타일 필터에서 버려진 것
            z = dep[n][j]
            L = float(LAM.get(n, 0.0))
            y = dict(x)
            if L > 0 and not np.isnan(z):
                y["score"] = float(x["score"]) * (1.0 - L + L * float(z))
            d.append(y)
        fn = (lambda p, q: 1.0 if center_in(p, q) else 0.0)
        cur[n] = froc(d, ngt[n], done, fn, g)
        print(f"  {n:<14} 정답 {ngt[n]:,}건 · 후처리 통과 검출 {len(d):,}건")

    nn = normals_at(0.0)
    print(f"  VinDr 정상 — 영상 {nn['n_img']}장 · 검사 {nn['n_st']}건")

    print("\n" + "=" * 86)
    print("  " + " " * 4 + "── 잃는 것 (VinDr 양성) ──   ── 얻는 것 (VinDr 정상) ──")
    print("=" * 86)
    print(f"  {'문턱':>6}{'석회':>9}{'종괴':>9}"
          f"{'│':>5}{'사진울림':>10}{'검사재소환':>12}{'조직검사':>10}")
    rows = []
    for t in GRID:
        sc = sens_at(cur["calcification"], t) * 100
        sm = sens_at(cur["mass"], t) * 100
        n = normals_at(t)
        rows.append((t, sc, sm, n))
        mark = "  ← 지금" if t == 0.45 else ""
        print(f"  {t:>6.2f}{sc:>8.1f}%{sm:>8.1f}%"
              f"{'│':>5}{n['img']:>9.1f}%{n['recall']:>11.1f}%"
              f"{n['biopsy']:>9.1f}%{mark}")

    print("\n" + "-" * 86)
    print("사람 수로 — 병변 100건, 정상 여성 100명")
    print("-" * 86)
    print(f"\n  {'문턱':>6}{'석회 찾음':>11}{'종괴 찾음':>11}"
          f"{'정상인데 부름':>15}{'정상인데 조직검사':>19}")
    for t, sc, sm, n in rows:
        print(f"  {t:>6.2f}{sc:>10.0f}건{sm:>10.0f}건"
              f"{n['recall']:>14.0f}명{n['biopsy']:>18.0f}명")

    print("""
─────────────────────────────────────────────────────────────────────────
이 표에 남은 경고와 사라진 경고
─────────────────────────────────────────────────────────────────────────

  ✓ **사라졌다** — 자료가 섞였다는 문제. 양쪽 다 VinDr 다.
    같은 장비 · 같은 인구 · 같은 전처리에서 나온 점수라 문턱값이
    양쪽에서 같은 뜻이다.

  ⚠ **남았다** — 이 민감도는 검출 단계다. 최종 수치는 여기에 서술어
    단계를 곱한 값이라 더 낮다. 이 표가 상한이다.

  ⚠ **남았다** — VinDr 양성은 BI-RADS 3 이상에 표시가 붙은 자료다.
    표시가 없는 양성 병변(BI-RADS 2)은 정답에 없으므로, 그걸 찾은
    검출이 오탐으로 세어졌을 수 있다. 민감도는 과소평가가 아니지만
    오탐은 과대평가일 수 있다.""")

    ok = [r for r in rows if r[3]["recall"] <= 10.0]
    print("\n" + "=" * 86)
    if ok:
        t, sc, sm, n = ok[0]
        print(f"정상 재소환 10% 이하가 되는 첫 문턱  {t:.2f}")
        print("=" * 86)
        print(f"\n  거기서 검출 민감도 석회 {sc:.1f}% · 종괴 {sm:.1f}%"
              f"  (지금 {rows[0][1]:.1f}% · {rows[0][2]:.1f}%)")
        if max(sc, sm) < 40:
            print("""
  ▶ **같은 자료로 재도 검진 선별에는 못 쓴다.**
    앞 표(CBIS 민감도 + VinDr 정상)의 결론이 자료가 섞여서 나온 것이
    아니라는 뜻이다. 이제 이 문장을 근거를 대고 말할 수 있다.""")
    else:
        print("정상 재소환 10% 이하가 되는 문턱이 격자 안에 없다")
        print("=" * 86)


if __name__ == "__main__":
    main()
