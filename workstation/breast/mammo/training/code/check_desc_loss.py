#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""서술어 쪽 10%p 손실이 «모델» 탓인가 «규칙표» 탓인가 — GPU 안 쓴다.

지금 손실 구조
    90.0% ──검출 −18.3%p──▶ 71.7% ──박스 −1.5%p──▶ 70.2%
      └─ 서술어가 이미 −10.0%p 를 먹고 시작한다

  검출 −18.3%p 에는 열 번 달려들어 두 번 이겼다.
  서술어 −10.0%p 에는 **한 번도 안 달려들었다.**

  「위치를 알려주면 90.0%」의 나머지 10%p 가 어디서 오는지 아직 모른다.
  세 갈래일 수 있다.

    ① 모델이 서술어를 틀린다           — 고치려면 GPU
    ② 서술어는 맞는데 규칙표가 낮게 준다 — **고치는 데 GPU 가 안 든다**
    ③ 규칙표가 그 조합을 아예 못 받는다  — 〃 (판정 불가)

  ②③ 이 크면 표 몇 줄 고쳐서 가져올 수 있다. 그래서 이것부터 잰다.

무엇을 재나
  인덱스 CSV 에 **정답 서술어가 컬럼으로 들어 있다**(shape__OVAL 등).
  그걸 규칙표에 그대로 넣어 본다. 모델을 안 거치므로 나오는 값이
  **서술어 방식의 천장**이다.

    천장이 90% 근처   → 규칙표는 이미 최선. 남은 건 모델 몫이고 GPU 가 든다
    천장이 한참 위     → 규칙표가 흘리고 있다. 표를 고치면 공짜로 가져온다

반대쪽도 같이 잰다 — 이걸 빼먹으면 안 된다
  놓친 것을 잡으려고 규칙을 풀면 **양성 아닌 병변까지 조직검사로 올라간다.**
  그 대가를 같이 안 재면 「개선」이 아니라 문턱을 내린 것에 불과하다.
  깊이 재점수 때와 같은 규율이다.

기준
  조직검사 대상 = 인덱스의 assessment ≥ 4 (eval_end2end 와 같은 정의)
  규칙표 통과   = level_of → to_category 가 4 이상

GPU 를 안 쓴다. 영상을 한 장도 안 읽는다. 몇 초면 끝난다.

사용
  python3 training/code/check_desc_loss.py
  python3 training/code/check_desc_loss.py --top 25
"""

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_e2e import find_rules, import_rules, level_of, to_category  # noqa: E402
from mammo_data import label_columns, load_schema                     # noqa: E402
from paths import ROI_INDEX                                           # noqa: E402

BIOPSY_CUT = 4
KINDS = ("calc", "mass")
KO = {"calc": "미세석회", "mass": "종괴"}
# 지금 실측치 — 나란히 놓고 봐야 천장과의 거리가 보인다
NOW = {"calc": 98.1, "mass": 82.7}


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def pct(a, b):
    return 100.0 * a / b if b else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--schema", default="")
    ap.add_argument("--rules", default="")
    ap.add_argument("--top", type=int, default=15,
                    help="떨어뜨리는 서술어 조합을 몇 개까지 보일지")
    a = ap.parse_args()

    print("=" * 86)
    print("서술어 손실 분해 — 규칙표 천장을 먼저 잰다 (GPU 안 씀)")
    print("=" * 86)

    rp = Path(a.rules) if a.rules else find_rules()
    R = import_rules(rp)
    print(f"  규칙표 {rp}")

    if a.schema:
        sp = Path(a.schema)
    else:
        from train_mammo import SCHEMA
        sp = Path(SCHEMA)
    if not sp.is_file():
        die(f"스키마가 없다: {sp}")
    schema = load_schema(sp)
    print(f"  스키마 {sp}")

    rows_all = {}
    for kind in KINDS:
        csv = ROI_INDEX / f"roi_index_{kind}_{a.split}.csv"
        if not csv.is_file():
            die(f"인덱스가 없다: {csv}")
        df = pd.read_csv(csv)
        cols = label_columns(schema, kind)
        miss = [c for c in cols if c not in df.columns]
        if miss:
            die(f"{kind} 인덱스에 라벨 컬럼이 없다: {miss[:5]}")
        if "assessment" not in df.columns:
            die(f"{kind} 인덱스에 assessment 가 없다 — 조직검사 대상을 못 정한다")
        rows_all[kind] = (df, cols)
        print(f"  인덱스 {csv.name}  {len(df):,}행 · 라벨 {len(cols)}칸")

    # ── 규칙표에 정답 서술어를 그대로 넣는다 ─────────────────────────
    res = {}
    for kind, (df, cols) in rows_all.items():
        out = []
        for r in df.to_dict("records"):
            g = r.get("assessment")
            try:
                g = int(g)
            except (TypeError, ValueError):
                g = None
            onehot = {c: 1 for c in cols if int(r.get(c) or 0) == 1}
            cat = to_category(R, level_of(R, kind, onehot))
            out.append(dict(row=r, gt=g, cat=cat, onehot=onehot,
                            combo=tuple(sorted(onehot))))
        res[kind] = out

    # ── [1] 천장 ─────────────────────────────────────────────────
    print("\n" + "=" * 86)
    print("[1] 규칙표 천장 — 정답 서술어를 그대로 넣으면 어디까지 가나")
    print("=" * 86)
    print("  모델을 안 거친 값이다. 모델이 완벽해도 이 위로는 못 간다.\n")
    print(f"  {'종류':<10}{'조직검사 대상':>13}{'규칙표 통과':>12}"
          f"{'판정 불가':>11}{'천장':>9}{'지금':>9}{'남은 여지':>11}")
    ceil = {}
    for kind in KINDS:
        need = [d for d in res[kind] if d["gt"] is not None and d["gt"] >= BIOPSY_CUT]
        ok = [d for d in need if d["cat"] is not None and d["cat"] >= BIOPSY_CUT]
        none_ = [d for d in need if d["cat"] is None]
        c = pct(len(ok), len(need))
        ceil[kind] = c
        print(f"  {KO[kind]:<10}{len(need):>13,}{len(ok):>12,}"
              f"{len(none_):>11,}{c:>8.1f}%{NOW[kind]:>8.1f}%"
              f"{c - NOW[kind]:>+10.1f}p")

    print("\n  읽는 법")
    print("    천장 − 지금 = **모델을 고쳐서 가져올 수 있는 몫** (GPU 필요)")
    print("    100 − 천장 = **규칙표가 흘리는 몫** (표를 고치면 GPU 없이)")

    # ── [2] 규칙표가 떨어뜨리는 조합 ──────────────────────────────
    print("\n" + "=" * 86)
    print("[2] 규칙표가 떨어뜨리는 조합 — 정답 서술어인데 4 미만으로 나온 것")
    print("=" * 86)
    for kind in KINDS:
        need = [d for d in res[kind] if d["gt"] is not None and d["gt"] >= BIOPSY_CUT]
        bad = [d for d in need
               if d["cat"] is None or d["cat"] < BIOPSY_CUT]
        if not bad:
            print(f"\n  {KO[kind]} — 떨어지는 것이 없다. 규칙표는 이미 최선이다.")
            continue
        cnt = Counter(d["combo"] for d in bad)
        catof = {}
        for d in bad:
            catof.setdefault(d["combo"], d["cat"])
        print(f"\n  {KO[kind]} — {len(bad)}건이 떨어진다 "
              f"(조직검사 대상 {len(need)}건 중 {pct(len(bad), len(need)):.1f}%)")
        print(f"    {'건수':>5}{'규칙표':>8}   서술어 조합")
        for combo, n in cnt.most_common(a.top):
            c = catof[combo]
            cs = "판정불가" if c is None else str(c)
            txt = " · ".join(x.split("__", 1)[-1] for x in combo) or "(전부 비었음)"
            print(f"    {n:>5}{cs:>8}   {txt[:66]}")
        if len(cnt) > a.top:
            print(f"    … 조합 {len(cnt) - a.top}종 더")

    # ── [3] 반대쪽 대가 ──────────────────────────────────────────
    print("\n" + "=" * 86)
    print("[3] 반대쪽 — 규칙표가 «올려» 버리는 것")
    print("=" * 86)
    print("  놓친 것을 잡으려고 규칙을 풀면 이쪽이 같이 는다.")
    print("  이 대가를 같이 안 재면 개선이 아니라 문턱을 내린 것이다.\n")
    print(f"  {'종류':<10}{'추적 대상(3↓)':>15}{'규칙표가 4↑':>13}{'비율':>9}")
    for kind in KINDS:
        low = [d for d in res[kind] if d["gt"] is not None and d["gt"] < BIOPSY_CUT]
        up = [d for d in low if d["cat"] is not None and d["cat"] >= BIOPSY_CUT]
        print(f"  {KO[kind]:<10}{len(low):>15,}{len(up):>13,}"
              f"{pct(len(up), len(low)):>8.1f}%")

    # ── [4] 놓친 것의 성격 ───────────────────────────────────────
    print("\n" + "=" * 86)
    print("[4] 떨어진 것들이 어떤 병변인가 — 임상적으로 얼마나 아픈 손실인가")
    print("=" * 86)
    for kind in KINDS:
        need = [d for d in res[kind] if d["gt"] is not None and d["gt"] >= BIOPSY_CUT]
        bad = [d for d in need if d["cat"] is None or d["cat"] < BIOPSY_CUT]
        if not bad:
            continue
        print(f"\n  {KO[kind]}  (떨어진 {len(bad)}건)")
        for col, lab in (("malignant", "악성 여부"), ("subtlety", "발견 난이도"),
                         ("assessment", "정답 등급"), ("density", "유방 밀도")):
            if col not in bad[0]["row"]:
                continue
            c_bad = Counter(str(d["row"].get(col)) for d in bad)
            c_all = Counter(str(d["row"].get(col)) for d in need)
            keys = sorted(c_all, key=lambda k: -c_all[k])[:6]
            body = " · ".join(
                f"{k} {pct(c_bad.get(k, 0), c_all[k]):.0f}%({c_bad.get(k,0)}/{c_all[k]})"
                for k in keys)
            print(f"    {lab:<10} {body}")
        print("    (칸마다 «그 값을 가진 병변 중 몇 %가 떨어졌나» 다. "
              "고르게 퍼져 있으면 특정 유형 문제가 아니다)")

    # ── 판단 ────────────────────────────────────────────────────
    print("\n" + "=" * 86)
    print("판단")
    print("=" * 86)
    slack = {k: 100.0 - ceil[k] for k in KINDS}
    for kind in KINDS:
        print(f"  {KO[kind]:<10} 천장 {ceil[kind]:5.1f}%  ·  "
              f"규칙표가 흘리는 몫 {slack[kind]:4.1f}%p  ·  "
              f"모델이 흘리는 몫 {ceil[kind]-NOW[kind]:4.1f}%p")
    worst = max(slack, key=slack.get)
    if slack[worst] < 2.0:
        print("\n  규칙표는 이미 최선이다. 남은 손실은 전부 모델 몫이라")
        print("  고치려면 GPU 가 든다. **여기서 접고 마무리로 가는 것을 권한다.**")
    else:
        print(f"\n  {KO[worst]} 에서 규칙표가 {slack[worst]:.1f}%p 를 흘린다.")
        print("  [2] 표의 조합들이 고칠 대상이다. **다만 [3] 의 대가를 같이 볼 것** —")
        print("  올라가는 쪽이 더 크면 그건 개선이 아니라 문턱을 내린 것이다.")
    print("\n  ※ 이 스크립트는 아무 파일도 안 고친다. 재기만 한다.")


if __name__ == "__main__":
    main()
