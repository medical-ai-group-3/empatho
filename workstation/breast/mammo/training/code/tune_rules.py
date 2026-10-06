#!/usr/bin/env python
"""
규칙표 조정 — 학습 분할에서만 튜닝한다. 테스트는 절대 읽지 않는다.

배경
  종단 평가에서 두 가지가 드러났다.

  calc  규칙표가 등급 4 로 쏠린다. 정답 서술어를 넣어도 등급 3 은 20.8%,
        5 는 32.5% 밖에 못 낸다.
  mass  정답 서술어를 넣어도 조직검사 민감도가 85.2% 에서 막힌다.
        놓친 36건의 대부분이 '실제 4 를 3 으로 내린' 것이다.
        임상에서 요구하는 수준은 90% 이상이다.

  둘 다 규칙표의 기준점 문제이지 모델 문제가 아니다. 여기서 다룬다.

무엇을 하는가
  기준점 표를 좌표상승법으로 조정한다. 한 번에 한 항목씩 최적값을 찾고,
  개선이 없을 때까지 반복한다.

목적함수 (--obj)
  clinical  ★ 임상 운영점. --min-sens 이상의 조직검사 민감도를 만족하는
            조합 중에서 특이도를 최대화한다. 제약 미달 구간에서는 민감도를
            10배 무겁게 본다. 등급 하나하나가 아니라 '조직검사를 할 것인가'
            라는 실제 결정을 기준으로 삼는다.
  balanced  등급별 재현율의 평균.
  exact     정확 일치율. 참고용으로만.

  정확도만 쓰면 '전부 4 로 찍기' 가 최적해가 되어 지금 문제가 그대로 남는다.
  clinical 도 민감도만 보면 같은 함정에 빠지므로 제약 충족 후에는 특이도만
  올리도록 사전식(lexicographic) 으로 짰다.

파레토 전선 (--sweep-sens)
  목표 민감도를 여러 개 훑어 각각의 최적 특이도를 보여준다. 운영점은
  기술적 최적이 아니라 임상적 선택이므로, 하나를 고르는 대신 선택지를
  펼쳐 놓는 것이 맞다.

★ 이 스크립트는 파일을 고치지 않는다. 제안만 출력한다.
★ 테스트 분할은 열지 않는다. 확정 후 eval_e2e.py 로 딱 한 번 확인해라.

주의 — 이건 공짜가 아니다
  규칙표의 값어치는 '임상 근거로 만들어진 해석 가능한 표' 라는 데 있다.
  데이터에 맞춰 값을 흔들면 그만큼 '끼워 맞춘 모델' 에 가까워진다.
  --lock 으로 임상적으로 확실한 항목은 고정해 두고 돌리는 것을 권한다.
  그리고 제안된 표가 임상 의미를 뒤집지 않는지 반드시 눈으로 확인해라.
  (이전에 최적화가 제안한 6개 변경 중 3개가 임상 의미를 뒤집어 기각했다.)
"""

import argparse, sys
from pathlib import Path

import numpy as np

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 필요")

def find_rules():
    """
    규칙표 위치를 찾는다. 스크립트와 같은 폴더를 가장 먼저 본다 — 파일을 옮겨도
    따라오게 하려는 것이다. 없으면 알려진 옛 경로를 차례로 확인한다.
    경로를 코드에 박아두면 폴더를 정리할 때마다 스크립트가 깨진다.
    """
    here = Path(__file__).resolve().parent
    for c in (here / "validate_rules.py",
              Path.home() / "workspace/breast/mammo/validate_rules.py",
              Path.home() / "workspace/breast/code/validate_rules.py"):
        if c.exists():
            return c
    return here / "validate_rules.py"      # 없으면 여기서 찾다 에러를 낸다


DEF_RULES = None   # find_rules() 로 대체. 아래 argparse 에서 부른다
DEF_LABELS = Path.home() / "workspace/breast/labels/labels"

BIOPSY_CUT = 4      # 4 이상 = 조직검사, 3 이하 = 추적


def import_rules(path):
    sys.path.insert(0, str(Path(path).parent))
    saved = sys.argv
    sys.argv = [str(path)]
    try:
        import validate_rules as R
    finally:
        sys.argv = saved
    return R


def to_category(R, lv):
    if lv is None:
        return np.nan
    cat = R.LEVEL_TO_CAT.get(lv)
    return R.FOLD.get(cat, np.nan) if cat is not None else np.nan


def predict(R, kind, rows):
    fn = R.level_mass if kind == "mass" else R.level_calc
    out = []
    for r in rows:
        res = fn(r)
        lv = res[0] if isinstance(res, tuple) else res
        out.append(to_category(R, lv))
    return np.array(out, dtype=float)


def metrics(pred, gt, lo=2, hi=5, cut=BIOPSY_CUT):
    ok = ~np.isnan(pred)
    exact = float((pred[ok] == gt[ok]).mean()) * 100 if ok.any() else 0.0
    within1 = float((np.abs(pred[ok] - gt[ok]) <= 1).mean()) * 100 if ok.any() else 0.0
    rec = {}
    for c in range(lo, hi + 1):
        is_c = gt == c
        n = int(is_c.sum())
        if n:
            rec[c] = 100.0 * float(((pred == c) & is_c).sum()) / n
    bal = float(np.mean(list(rec.values()))) if rec else 0.0

    # ── 조직검사 판단 (이진) ─────────────────────────────────
    # 6단계 등급은 4a/4b 혼동까지 오답으로 센다. 임상에서 갈리는 결정은
    # '조직검사를 할 것인가' 하나다. assessment 0 은 '추가 촬영 필요' 라
    # 조직검사 여부를 물을 수 없으므로 제외한다.
    okb = ok & ~np.isnan(gt) & (gt >= 1)
    p, g = pred[okb] >= cut, gt[okb] >= cut
    n2 = int(okb.sum())
    tp = int((p & g).sum());  fn_ = int((~p & g).sum())
    fp = int((p & ~g).sum()); tn = int((~p & ~g).sum())

    def r(x, d):
        return 100.0 * x / d if d else float("nan")

    return dict(exact=exact, within1=within1, balanced=bal, recall=rec,
                unevaluable=int((~ok).sum()),
                sens=r(tp, tp + fn_), spec=r(tn, tn + fp),
                acc2=r(tp + tn, n2), prev=r(tp + fn_, n2),
                tp=tp, tn=tn, fp=fp, fn=fn_, n2=n2)


def show(tag, m):
    r = "  ".join(f"{c}:{v:5.1f}%" for c, v in sorted(m["recall"].items()))
    print(f"  {tag:14s} 정확 {m['exact']:5.1f}%   ±1 {m['within1']:5.1f}%   "
          f"균형 {m['balanced']:5.1f}%")
    print(f"  {'':14s} 등급별  {r}")
    print(f"  {'':14s} 조직검사  정확 {m['acc2']:5.1f}%   "
          f"민감 {m['sens']:5.1f}%   특이 {m['spec']:5.1f}%"
          f"   (FN {m['fn']} · FP {m['fp']})")


def restore(tables, orig):
    """표를 원본으로 되돌린다. R 모듈의 dict 를 제자리에서 고친다."""
    for name, tbl, _ in tables:
        tbl.clear()
        tbl.update(orig[name])


def coord_ascent(tables, locked, score_fn, iters, verbose=True):
    """좌표상승법. 한 번에 한 항목씩 최적값으로 옮긴다."""
    cur = score_fn()
    for it in range(1, iters + 1):
        improved = False
        for name, tbl, rng in tables:
            for key in list(tbl.keys()):
                if key in locked:
                    continue
                keep = tbl[key]
                best_v, best_s = keep, cur
                for v in rng:
                    if v == keep:
                        continue
                    tbl[key] = v
                    s = score_fn()
                    if s > best_s + 1e-9:
                        best_v, best_s = v, s
                tbl[key] = best_v
                if best_v != keep:
                    if verbose:
                        print(f"    {name}[{key}]  {keep} -> {best_v}"
                              f"   점수 {cur:.2f} -> {best_s:.2f}")
                    cur, improved = best_s, True
        if not improved:
            if verbose:
                print(f"    {it}회차에서 개선 없음 — 수렴")
            break
    return cur


def n_changed(tables, orig):
    return sum(1 for name, tbl, _ in tables
               for k, v in tbl.items() if orig[name][k] != v)


def print_proposal(tables, orig):
    any_change = False
    for name, tbl, _ in tables:
        diffs = {k for k, v in tbl.items() if orig[name][k] != v}
        if not diffs:
            continue
        any_change = True
        print(f"\n{name} = {{")
        for k, v in tbl.items():
            mark = f"    # <- {orig[name][k]} 에서 변경" if k in diffs else ""
            print(f'    "{k}": {v},{mark}')
        print("}")
    if not any_change:
        print("\n  변경 제안 없음 — 현재 표가 이미 이 목적함수의 국소 최적이다.")
    return any_change


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["calc", "mass"], default="calc")
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--labels", default=str(DEF_LABELS))
    ap.add_argument("--obj", choices=["clinical", "balanced", "exact"],
                    default="clinical",
                    help="clinical = 민감도 제약 하 특이도 최대 (기본)")
    ap.add_argument("--min-sens", type=float, default=90.0,
                    help="clinical 목적의 최소 조직검사 민감도 (%%). 기본 90")
    ap.add_argument("--sweep-sens", default="",
                    help="목표 민감도를 여러 개 훑어 파레토 전선을 그린다. "
                         "예: 85,88,90,92,95")
    ap.add_argument("--iters", type=int, default=6)
    ap.add_argument("--lock", default="",
                    help="고정할 항목 (쉼표). 예: FINE_LINEAR_BRANCHING,SPICULATED")
    ap.add_argument("--set", default="", dest="setvals",
                    help="값을 직접 지정한다. 예: "
                         "CALCTYPE_BASE:AMORPHOUS=2,CALCTYPE_BASE:PLEOMORPHIC=4 . "
                         "최적화에 맡기지 않고 임상 지침 값을 박아 결과만 보고 싶을 때 쓴다")
    ap.add_argument("--no-tune", action="store_true",
                    help="좌표상승법을 건너뛴다. --set 과 함께 쓰면 지정값만 평가한다")
    a = ap.parse_args()

    R = import_rules(a.rules)

    # ── 학습 분할만 읽는다 ─────────────────────────────────────
    train_csv = Path(a.labels) / f"labels_{a.kind}_train.csv"
    if not train_csv.exists():
        sys.exit(f"없음: {train_csv}")
    df = pd.read_csv(train_csv)
    if "assessment" not in df.columns:
        sys.exit("assessment 컬럼이 없다")
    rows = df.to_dict("records")
    gt = df["assessment"].to_numpy(float)

    print("=" * 78)
    print(f"규칙표 조정 — {a.kind} · 학습 분할만")
    print("=" * 78)
    print(f"  규칙표 {a.rules}")
    print(f"  라벨   {train_csv.name}   n={len(df)}")
    obj_desc = {
        "clinical": f"민감도 {a.min_sens:.0f}% 이상 제약 하에서 특이도 최대",
        "balanced": "등급별 재현율 평균 — '전부 4로 찍기'를 막는다",
        "exact": "정확 일치율",
    }[a.obj]
    print(f"  목적   {a.obj}  ({obj_desc})")
    print("  ★ 테스트 분할은 읽지 않는다")

    # 조정 대상
    if a.kind == "calc":
        tables = [("CALCTYPE_BASE", R.CALCTYPE_BASE, range(0, 6)),
                  ("CALCDIST_ADJ", R.CALCDIST_ADJ, range(-2, 3))]
    else:
        tables = [("MARGIN_BASE", R.MARGIN_BASE, range(0, 6)),
                  ("SHAPE_ADJ", R.SHAPE_ADJ, range(-1, 3)),
                  ("FINDING_BASE", R.FINDING_BASE, range(0, 6))]
    locked = {x.strip() for x in a.lock.split(",") if x.strip()}
    if locked:
        print(f"  고정   {sorted(locked)}")

    orig = {name: dict(tbl) for name, tbl, _ in tables}
    byname = {name: tbl for name, tbl, _ in tables}

    base_m = metrics(predict(R, a.kind, rows), gt)
    print("\n■ 현재")
    show("현재", base_m)
    print(f"\n  ── 반드시 같이 볼 것 ──")
    print(f"    조직검사 실제 비율 {base_m['prev']:5.1f}%  =  '전부 조직검사' 의 정확도")
    print(f"    (민감도 100% · 특이도 0%). 특이도를 버리면 언제든 도달한다.")

    if a.setvals:
        print("\n■ 지정값 적용")
        for item in a.setvals.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                loc, val = item.split("=")
                tname, key = loc.split(":")
                v = int(val)
            except ValueError:
                sys.exit(f"형식 오류: {item}   (TABLE:KEY=VALUE 이어야 한다)")
            if tname not in byname:
                sys.exit(f"모르는 표: {tname}   가능: {list(byname)}")
            if key not in byname[tname]:
                sys.exit(f"{tname} 에 없는 항목: {key}")
            print(f"    {tname}[{key}]  {byname[tname][key]} -> {v}")
            byname[tname][key] = v
        show("지정값", metrics(predict(R, a.kind, rows), gt))
        orig = {name: dict(tbl) for name, tbl, _ in tables}   # 지정값을 기준으로

    def make_score(min_sens):
        """
        사전식 목적함수.
          제약 충족  ->  10000 + 특이도      (특이도만 겨룬다)
          제약 미달  ->  10*민감도 + 특이도   (민감도가 10배 무겁다)

        미달 구간의 최고점은 10*100 + 100 = 1100 이라 충족 구간의 최저점
        10000 에 한참 못 미친다. 즉 특이도를 100% 갖고 있어도 제약을 어기면
        절대 못 이긴다 — 제약 충족이 절대 우선이다.

        민감도만 최대화하면 '전부 조직검사' 가 최적해가 된다. 제약을 넘긴
        뒤에는 특이도만 겨루게 해서 그 붕괴를 막는다.
        """
        def f():
            m = metrics(predict(R, a.kind, rows), gt)
            if a.obj != "clinical":
                return m[a.obj]
            s, sp = m["sens"], m["spec"]
            if s != s or sp != sp:
                return -1e9
            return (10000.0 + sp) if s >= min_sens else (10.0 * s + sp)
        return f

    # ── 파레토 전선 ────────────────────────────────────────────
    sweep = [float(x) for x in a.sweep_sens.split(",") if x.strip()]
    if sweep:
        print("\n" + "=" * 78)
        print("파레토 전선 — 목표 민감도별 최적 운영점")
        print("=" * 78)
        print(f"  {'목표민감도':>10s}{'달성민감도':>12s}{'특이도':>10s}"
              f"{'조직검사정확도':>15s}{'FN':>6s}{'FP':>6s}{'변경수':>8s}")
        print("  " + "-" * 72)
        print(f"  {'현재':>10s}{base_m['sens']:>11.1f}%{base_m['spec']:>9.1f}%"
              f"{base_m['acc2']:>14.1f}%{base_m['fn']:>6d}{base_m['fp']:>6d}"
              f"{0:>8d}")
        results = []
        for ms in sweep:
            restore(tables, orig)
            coord_ascent(tables, locked, make_score(ms), a.iters, verbose=False)
            m = metrics(predict(R, a.kind, rows), gt)
            nch = n_changed(tables, orig)
            hit = " " if m["sens"] >= ms else "!"
            print(f"  {ms:>9.0f}%{m['sens']:>11.1f}%{hit}{m['spec']:>8.1f}%"
                  f"{m['acc2']:>14.1f}%{m['fn']:>6d}{m['fp']:>6d}{nch:>8d}")
            results.append((ms, m, nch))
        print("\n  ! 표시 = 목표 민감도에 도달하지 못했다. 규칙표 구조상 상한이다.")
        print("\n  운영점은 기술적 최적이 아니라 임상적 선택이다. 하나를 고른 뒤")
        print(f"  --min-sens <값> 으로 다시 돌리면 그 지점의 표 제안이 나온다.")
        restore(tables, orig)
        return

    # ── 단일 목표 ──────────────────────────────────────────────
    if a.no_tune:
        print("\n■ 조정 건너뜀 (--no-tune)")
    else:
        print("\n■ 조정")
        coord_ascent(tables, locked, make_score(a.min_sens), a.iters)

    new_m = metrics(predict(R, a.kind, rows), gt)
    print("\n■ 결과 (학습 분할)")
    show("현재", base_m)
    show("조정 후", new_m)
    print(f"\n  정확 {new_m['exact']-base_m['exact']:+.1f}%p"
          f"   균형 {new_m['balanced']-base_m['balanced']:+.1f}%p"
          f"   민감 {new_m['sens']-base_m['sens']:+.1f}%p"
          f"   특이 {new_m['spec']-base_m['spec']:+.1f}%p")
    if a.obj == "clinical":
        if new_m["sens"] >= a.min_sens:
            print(f"  목표 민감도 {a.min_sens:.0f}% 달성 "
                  f"(놓친 건수 {base_m['fn']} -> {new_m['fn']})")
        else:
            print(f"  ! 목표 민감도 {a.min_sens:.0f}% 미달 ({new_m['sens']:.1f}%). "
                  f"규칙표 구조상 이 이상은 안 올라간다.")
    if new_m["exact"] < base_m["exact"]:
        print("  ! 정확 일치율은 내려갔다. 임상 운영점을 얻는 대신 치른 값이다.")
        print("    6단계 정확도와 조직검사 판단 중 무엇을 보고할지 먼저 정해라.")

    print("\n" + "=" * 78)
    print("제안 — validate_rules.py 에 직접 반영해라 (이 스크립트는 파일을 안 고친다)")
    print("=" * 78)
    print_proposal(tables, orig)

    print("\n" + "=" * 78)
    print("다음")
    print("=" * 78)
    print("  1. 제안된 표가 임상 의미를 뒤집지 않는지 눈으로 확인")
    print("     (기준점이 올라간 서술어가 실제로 더 위험한 소견인가?)")
    print("  2. 위 표를 validate_rules.py 에 반영")
    print(f"  3. python3 validate_rules.py --labels <라벨폴더>   (학습 분할 재확인)")
    print(f"  4. python3 eval_e2e.py --ckpt ckpt/mammo_{a.kind}_..._lora.pt")
    print("     ★ 테스트 확인은 여기서 딱 한 번. 결과를 보고 표를 또 고치면 그때부터")
    print("       테스트셋 선택 편향이 시작된다.")


if __name__ == "__main__":
    main()
