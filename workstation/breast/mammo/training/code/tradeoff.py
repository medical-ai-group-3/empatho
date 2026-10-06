#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""맞바꿈 곡선 — 문턱을 올리면 무엇을 얻고 무엇을 잃나.

두 쪽을 한 표에 놓는다
    얻는 것   정상 유방(VinDr 75검사)이 조용해진다
    잃는 것   병변(CBIS test)을 놓친다

  둘 중 하나만 보면 반드시 틀린 결론이 나온다. 정상 쪽만 보면 아무것도
  안 찾는 모델이 제일 좋아 보이고, 병변 쪽만 보면 지금 문턱이 제일 좋아
  보인다. **같이 놓아야 판단이 된다.**

왜 새로 재지 않나
  eval_mammo_det.froc() 가 이미 (오탐, 민감도, 문턱) 곡선 **전체**를 만든다.
  docs/score_dets.json 은 그 곡선에서 다섯 점만 떠 놓은 것이라 0.57 에서
  끊긴다. 곡선을 그대로 읽으면 어느 문턱에서든 값이 나온다.

  정답 만드는 경로는 score_dets.build_gt 를 **그대로 불러 쓴다.**
  검출 파일의 상자가 조직 상자 기준이라 그 경로를 다시 짜면 어긋난다.

⚠ 이 표의 민감도는 «검출 단계» 다
  최종 수치(조직검사 대상의 66.7%)는 여기에 서술어 단계를 곱한 값이다.
  검출에서 놓친 것은 서술어가 되살릴 수 없으므로 이 표가 **상한**이다.

⚠ 두 자료가 다르다
  민감도는 CBIS(스캔 필름 · 조직검사 확정 사례), 정상은 VinDr(디지털 ·
  베트남 검진)에서 왔다. 점수 분포가 자료마다 다를 수 있으므로 같은
  문턱값이 두 자료에서 같은 뜻이라는 보장은 없다. **이 표는 방향을 보는
  것이지 소수점을 정하는 것이 아니다.**

사용
  python3 training/code/tradeoff.py                    # 정답 만들기 포함 (수 분)
  python3 training/code/tradeoff.py --no-cache         # 정답 캐시 무시
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "archive" / "outputs"
CODE = Path(__file__).resolve().parent
sys.path.insert(0, str(CODE))

import eval_mammo_det as E                                    # noqa: E402
import score_dets as S                                        # noqa: E402

DETS = OUT / "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json"
NORM = OUT / "normal_dets.jsonl"
CACHE = OUT / "gt_cache_test.json"
NOW = {"calcification": 0.448, "mass": 0.462}
GRID = [0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def build_or_load(split, clip, pad, use_cache):
    """정답은 DICOM 을 다 읽어야 해서 몇 분 걸린다. 한 번 만들고 캐시한다."""
    if use_cache and CACHE.is_file():
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        if d.get("split") == split and d.get("clip") == clip and d.get("pad") == pad:
            gts = {k: defaultdict(list, {u: [tuple(b) for b in v]
                                         for u, v in kv.items()})
                   for k, kv in d["gts"].items()}
            print(f"  정답 캐시를 썼다 — {CACHE.name} (영상 {d['done']}장)")
            return gts, set(d["keep"]), d["done"]
        print("  캐시의 설정이 달라 다시 만든다.")

    print("  정답을 만든다 — DICOM 을 전부 읽으므로 몇 분 걸린다.")
    gts, origin, done, skipped = S.build_gt(split, clip, pad, 0)
    keep = set(origin)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({
        "split": split, "clip": clip, "pad": pad, "done": done,
        "keep": sorted(keep),
        "gts": {k: {u: [list(b) for b in v] for u, v in kv.items()}
                for k, kv in gts.items()},
    }, ensure_ascii=False), encoding="utf-8")
    print(f"  영상 {done}장 · 건너뛴 것 {skipped}장 → 캐시 {CACHE.name}")
    return gts, keep, done


def curve_of(kind, gts, keep, done):
    raw = json.loads(DETS.read_text(encoding="utf-8"))
    g = {u: v for u, v in gts[kind].items() if v}
    n_gt = sum(len(v) for v in g.values())
    d = [x for x in raw.get(kind, []) if str(x["img"]) in keep]
    fn = (lambda p, q: 1.0 if E.center_in(p, q) else 0.0)
    return E.froc(d, n_gt, done, fn, g), n_gt


def sens_at(curve, t):
    """문턱 t 에서의 민감도. 곡선 항목은 (오탐, 민감도, 문턱) 이다."""
    v = [s for _f, s, th in curve if th is not None and th >= t]
    return max(v) if v else 0.0


def fp_at(curve, t):
    v = [(th, f) for f, _s, th in curve if th is not None and th >= t]
    return min(v)[1] if v else 0.0


def normals(t):
    """VinDr 정상 쪽 — 문턱 t 에서 사진·검사 단위."""
    last = {}
    for line in NORM.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            last[r["image_id"]] = r
    recs = [r for r in last.values() if "error" not in r]
    fire = defaultdict(bool)
    biop = defaultdict(bool)
    n_img_fire = 0
    for r in recs:
        k = [l for l in r["lesions"] if l["score"] >= t]
        if k:
            n_img_fire += 1
            fire[r["study_id"]] = True
        else:
            fire.setdefault(r["study_id"], False)
        if any(l["biopsy"] for l in k):
            biop[r["study_id"]] = True
        else:
            biop.setdefault(r["study_id"], False)
    ns = len(fire) or 1
    return {"img": n_img_fire / len(recs) * 100,
            "recall": sum(fire.values()) / ns * 100,
            "biopsy": sum(biop.values()) / ns * 100,
            "n_img": len(recs), "n_st": ns}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--no-cache", action="store_true")
    a = ap.parse_args()

    for p in (DETS, NORM):
        if not p.is_file():
            sys.exit(f"[중단] 없는 파일: {p}")

    print("=" * 86)
    print("맞바꿈 곡선 — 문턱을 올리면 얻는 것과 잃는 것")
    print("=" * 86)

    gts, keep, done = build_or_load(a.split, a.clip, a.pad, not a.no_cache)
    cur, ngt = {}, {}
    for k in ("calcification", "mass"):
        cur[k], ngt[k] = curve_of(k, gts, keep, done)
    print(f"  CBIS {a.split} — 병변 석회 {ngt['calcification']}건 · "
          f"종괴 {ngt['mass']}건")
    nn = normals(0.0)
    print(f"  VinDr 정상 — 영상 {nn['n_img']}장 · 검사 {nn['n_st']}건")

    # ── 본표 ───────────────────────────────────────────────────
    print("\n" + "=" * 86)
    print("  " + " " * 6 + "── 잃는 것 (CBIS 병변) ──    ── 얻는 것 (VinDr 정상) ──")
    print("=" * 86)
    print(f"  {'문턱':>6}{'석회':>9}{'종괴':>9}{'영상당오탐':>12}"
          f"{'│':>4}{'사진울림':>10}{'검사재소환':>12}{'조직검사':>10}")
    rows = []
    for t in GRID:
        sc = sens_at(cur["calcification"], t) * 100
        sm = sens_at(cur["mass"], t) * 100
        fp = fp_at(cur["calcification"], t) + fp_at(cur["mass"], t)
        n = normals(t)
        rows.append((t, sc, sm, fp, n))
        mark = "  ← 지금" if t == 0.45 else ""
        print(f"  {t:>6.2f}{sc:>8.1f}%{sm:>8.1f}%{fp:>12.2f}"
              f"{'│':>4}{n['img']:>9.1f}%{n['recall']:>11.1f}%"
              f"{n['biopsy']:>9.1f}%{mark}")

    # ── 사람 말로 ──────────────────────────────────────────────
    print("\n" + "-" * 86)
    print("사람 수로 바꾸면 — 병변 100건, 정상 여성 100명 기준")
    print("-" * 86)
    print(f"\n  {'문턱':>6}{'석회 찾음':>11}{'종괴 찾음':>11}"
          f"{'정상인데 부름':>15}{'정상인데 조직검사':>19}")
    for t, sc, sm, _fp, n in rows:
        print(f"  {t:>6.2f}{sc:>10.0f}건{sm:>10.0f}건"
              f"{n['recall']:>14.0f}명{n['biopsy']:>18.0f}명")

    # ── 읽는 법 ────────────────────────────────────────────────
    print("""
─────────────────────────────────────────────────────────────────────────
읽는 법
─────────────────────────────────────────────────────────────────────────

  ⚠ 왼쪽 민감도는 **검출 단계**다. 최종 수치는 여기에 서술어 단계를
    곱한 값이라 더 낮다. 검출에서 놓친 것은 서술어가 못 되살리므로
    이 표가 **상한**이다.

  ⚠ 두 쪽 자료가 다르다. 민감도는 CBIS(스캔 필름 · 조직검사 확정),
    정상은 VinDr(디지털 · 베트남 검진)다. 같은 문턱값이 두 자료에서
    같은 뜻이라는 보장이 없다. **방향을 보는 표이지 소수점을 정하는
    표가 아니다.**

  볼 것 — 「정상인데 부름」이 실제 검진 수준(10명 안팎)까지 내려가는
  문턱에서 「찾음」이 몇 건 남는가. 그 값이 이 시스템이 검진 선별에
  쓰일 수 있는지를 정한다.""")

    # ── 결론을 숫자로 ──────────────────────────────────────────
    ok = [r for r in rows if r[4]["recall"] <= 10.0]
    print("\n" + "=" * 86)
    if ok:
        t, sc, sm, _fp, n = ok[0]
        print(f"정상 재소환 10% 이하가 되는 첫 문턱  {t:.2f}")
        print("=" * 86)
        print(f"""
  거기서 검출 민감도는 석회 {sc:.1f}% · 종괴 {sm:.1f}% 다.
  지금({rows[0][1]:.1f}% · {rows[0][2]:.1f}%) 에서
  석회 {sc-rows[0][1]:+.1f}%p · 종괴 {sm-rows[0][2]:+.1f}%p 다.""")
        if sc < 40 or sm < 40:
            print("""
  ▶ **검진 선별에는 못 쓴다.** 정상을 조용하게 만들면 병변의 절반 넘게
    놓친다. 이 시스템은 판독의가 이미 보고 있는 영상에 표시를 얹는
    **판독 보조**로 자리를 잡아야 한다.

    그렇게 자리를 잡으면 지금 문턱이 틀린 값이 아니다 — 표시가 여러 개
    뜨는 것을 전제로 쓰는 물건이기 때문이다.""")
        else:
            print("""
  ▶ 검진 작동점이 존재한다. 다만 위 두 경고(단계 · 자료 차이) 때문에
    이 값을 그대로 쓰면 안 되고, 같은 자료에서 다시 확인해야 한다.""")
    else:
        print("정상 재소환 10% 이하가 되는 문턱이 격자 안에 없다")
        print("=" * 86)

    print("""
■ 다음에 할 수 있는 것

  ① 정상 쪽 문턱만 따로 두기 — 검출은 지금대로 하고, **화면 표시만**
     두 단으로 나눈다. 낮은 점수는 「참고」, 높은 점수는 「확인 필요」.
     아무것도 안 버리므로 민감도를 잃지 않는다.

  ② 종류별로 문턱을 다르게 — 정상에서 종괴가 영상당 1.70, 석회가 0.60
     이다. 세 배 차이라 한 값으로 묶을 이유가 없다.

  ③ 같은 자료에서 다시 재기 — VinDr 양성 검사로 민감도를 재면 위
     ⚠ 두 번째가 사라진다. VinDr 양성은 이미 받아 놨다(443장).""")


if __name__ == "__main__":
    main()
