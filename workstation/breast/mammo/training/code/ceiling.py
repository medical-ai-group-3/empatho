#!/usr/bin/env python
"""
서술어로 도달 가능한 진짜 최대치를 잰다 — 그리고 정답지를 바꿔서도 잰다.

왜 필요한가
  '정답 서술어를 넣어도 77.3%' 라고 보고했는데, 그 숫자는 두 가지가 섞여 있다.

    (a) 우리 점수표가 최적이 아니라서 틀리는 몫   — 고칠 수 있다
    (b) 서술어가 같은데 정답이 다른 몫             — 어떤 점수표로도 못 고친다

  (b) 만 남긴 값이 서술어 방식의 진짜 한계다. 조합마다 가장 흔한 정답을
  고르는 것이 최선이므로, 그 최빈값을 다 더하면 계산된다.

  진짜 한계가 77.3% 근처면 점수표는 이미 최적이고, 더 올리려면 서술어 밖의
  정보(영상)가 필요하다. 한참 위면 점수표를 고쳐서 더 가져올 수 있다.

낙관적 상한을 피한다
  같은 데이터에서 최빈값을 정하고 같은 데이터에서 채점하면 실제보다 높게
  나온다. 드문 조합일수록 심하다. 그래서 두 값을 함께 낸다.

    학습 분할에서 정한 최적 매핑 -> 학습 분할 정확도    낙관적 상한
    학습 분할에서 정한 최적 매핑 -> 테스트 분할 정확도  실제 기대치

정답지를 세 가지로 잰다
  등급        판독의가 매긴 BI-RADS. 사람 의견이고 우리가 못 보는 정보가 섞여 있다
  조직검사    등급을 4 이상 / 미만으로 접은 것. 우리가 실제로 보고하는 판단이다
  병리        조직을 떼서 확인한 결과. 의견이 아니라 사실이다

  '판독의를 얼마나 잘 흉내내나' 와 '실제 악성을 얼마나 잘 골라내나' 는
  다른 질문이다. 후자가 임상적으로 더 의미 있다.

무엇을 안 하나
  데이터 라벨을 고치지 않는다. 우리 예측에 맞춰 정답을 바꾸면 채점이
  무의미해진다. 이미 데이터에 있는 다른 정답지를 쓸 뿐이다.

사용
  python3 ceiling.py --labels ~/workspace/breast/labels/labels
  python3 ceiling.py --labels ... --top 20
"""

import argparse
import contextlib
import glob
import io
import os
import sys
from collections import Counter, defaultdict

try:
    import pandas as pd
except ImportError:
    sys.exit("pandas 가 없다")


def load_rules():
    """
    validate_rules 에서 점수표와 판정 함수를 그대로 가져온다.
    복사하면 한쪽만 고쳐졌을 때 조용히 어긋난다.

    그 파일은 최상위에서 인자를 파싱할 수 있으므로 argv 를 잠시 비우고,
    출력도 삼킨다. 고쳐진 판이든 아니든 동작한다.
    """
    argv = sys.argv
    sys.argv = [argv[0]]
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            import validate_rules as VR
    except SystemExit as e:
        sys.exit(f"validate_rules 를 못 읽었다: {e}")
    finally:
        sys.argv = argv
    for name in ("level_mass", "level_calc", "LEVEL_TO_CAT", "FOLD"):
        if not hasattr(VR, name):
            sys.exit(f"validate_rules 에 {name} 이 없다")
    return VR


def read_split(labels, kind, split):
    fs = sorted(glob.glob(os.path.join(labels, f"labels_{kind}_{split}*.csv")))
    if not fs:
        return None
    return pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)


def to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_bin(v):
    """병리 라벨을 0/1 로. 표기가 여러 가지일 수 있다."""
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in ("1", "TRUE", "MALIGNANT", "M", "YES"):
        return 1
    if s in ("0", "FALSE", "BENIGN", "B", "NO"):
        return 0
    try:
        f = float(s)
        return int(f > 0.5)
    except ValueError:
        return None


def collect(df, kind, VR):
    """행마다 (조합 서명, 규칙표 예측 등급, 등급 정답, 병리 정답)."""
    fn = VR.level_mass if kind == "mass" else VR.level_calc
    out, skipped = [], 0
    for r in df.to_dict("records"):
        lv, sig, _ = fn(r)
        act = to_int(r.get("assessment"))
        if lv is None or act is None:
            skipped += 1
            continue
        out.append(dict(
            sig=f"{kind}|{sig}",
            rule=VR.FOLD[VR.LEVEL_TO_CAT[lv]],
            grade=act,
            path=to_bin(r.get("malignant")),
        ))
    return out, skipped


# ── 채점 ─────────────────────────────────────────────────────────────────

def fit_best(rows, key):
    """조합마다 가장 흔한 정답을 고른다 — 어떤 매핑도 이보다 나을 수 없다."""
    g = defaultdict(Counter)
    for r in rows:
        if r[key] is not None:
            g[r["sig"]][r[key]] += 1
    return {s: c.most_common(1)[0][0] for s, c in g.items() if c}


def apply_best(rows, best, key, fallback):
    hit = miss = unseen = 0
    for r in rows:
        if r[key] is None:
            continue
        p = best.get(r["sig"])
        if p is None:
            p = fallback
            unseen += 1
        hit += int(p == r[key])
        miss += int(p != r[key])
    n = hit + miss
    return (hit / n if n else 0.0), n, unseen


def score_rule(rows, key, conv):
    hit = n = 0
    for r in rows:
        if r[key] is None:
            continue
        n += 1
        hit += int(conv(r["rule"]) == r[key])
    return (hit / n if n else 0.0), n


def block(title, tr, te, key, conv, top, note=""):
    print("\n" + "=" * 74)
    print(title)
    if note:
        print("  " + note)
    print("=" * 74)

    best = fit_best(tr, key)
    vals = [r[key] for r in tr if r[key] is not None]
    if not vals:
        print("  정답이 없다 — 건너뛴다")
        return
    fb = Counter(vals).most_common(1)[0][0]

    r_tr, n_tr = score_rule(tr, key, conv)
    r_te, n_te = score_rule(te, key, conv) if te else (None, 0)
    b_tr, _, _ = apply_best(tr, best, key, fb)
    b_te, _, uns = apply_best(te, best, key, fb) if te else (None, 0, 0)

    print(f"  {'':22s} {'학습':>10s} {'테스트':>10s}")
    print("  " + "-" * 46)
    print(f"  {'현재 점수표':22s} {r_tr:9.1%} "
          + (f"{r_te:9.1%}" if r_te is not None else f"{'—':>10s}"))
    print(f"  {'조합별 최적 매핑':22s} {b_tr:9.1%} "
          + (f"{b_te:9.1%}" if b_te is not None else f"{'—':>10s}"))
    print("  " + "-" * 46)
    print(f"  {'되찾을 수 있는 몫':22s} {b_tr-r_tr:+9.1%} "
          + (f"{b_te-r_te:+9.1%}" if b_te is not None else f"{'—':>10s}"))
    print(f"\n  건수  학습 {len(tr):,} · 테스트 {n_te:,}   조합 {len(best):,}개")
    if te and uns:
        print(f"  ! 테스트에만 있는 조합 {uns}건 — 전체 최빈값으로 대체했다")

    # 못 고치는 몫
    tot = sum(sum(c.values()) for c in
              [Counter(r[key] for r in tr if r["sig"] == s and r[key] is not None)
               for s in best])
    g = defaultdict(Counter)
    for r in tr:
        if r[key] is not None:
            g[r["sig"]][r[key]] += 1
    irr = sum(sum(c.values()) - c.most_common(1)[0][1] for c in g.values())
    n_all = sum(sum(c.values()) for c in g.values())
    if n_all:
        print(f"  서술어가 같은데 정답이 갈리는 몫 {irr:,}/{n_all:,} "
              f"({irr/n_all:.1%}) — 어떤 매핑으로도 못 고친다")

    # ── 어느 줄을 고치면 얼마나 버나 ───────────────────────────────────
    rows_by = defaultdict(list)
    for r in tr:
        if r[key] is not None:
            rows_by[r["sig"]].append(r)
    gain = []
    for s, rs in rows_by.items():
        cur = sum(1 for r in rs if conv(r["rule"]) == r[key])
        bst = sum(1 for r in rs if best[s] == r[key])
        if bst > cur:
            gain.append((bst - cur, len(rs), s,
                         conv(rs[0]["rule"]), best[s],
                         Counter(r[key] for r in rs).most_common(4)))
    gain.sort(reverse=True)
    if gain:
        print(f"\n  ── 지금 점수표가 최빈값과 다른 조합 (상위 {top}) ──")
        for d, n, s, now, bst, dist in gain[:top]:
            dd = " ".join(f"{k}:{v}" for k, v in dist)
            print(f"    +{d:<4} n={n:<5} 현재 {now} -> 최적 {bst}   [{dd}]")
            print(f"           {s.split('|',1)[1]}")
    else:
        print("\n  점수표가 모든 조합에서 이미 최빈값을 고르고 있다")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="labels")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    VR = load_rules()

    print("=" * 74)
    print("서술어로 어디까지 갈 수 있나")
    print("=" * 74)

    tr, te, skip = [], [], 0
    for kind in ("mass", "calc"):
        for split, bag in (("train", tr), ("test", te)):
            df = read_split(a.labels, kind, split)
            if df is None:
                print(f"  ! 없음: labels_{kind}_{split}*.csv")
                continue
            rows, sk = collect(df, kind, VR)
            bag += rows
            skip += sk
            print(f"  {kind:5s} {split:5s}  {len(rows):,}건"
                  + (f"  (서술어·등급 없어 제외 {sk})" if sk else ""))
    if not tr:
        sys.exit("\n학습 분할을 못 읽었다. --labels 경로를 확인해라")

    n_path = sum(1 for r in tr if r["path"] is not None)
    print(f"\n  병리 라벨이 있는 행  학습 {n_path:,}/{len(tr):,}")

    block("정답지 1 — 등급 (판독의가 매긴 BI-RADS)",
          tr, te, "grade", lambda p: p, a.top,
          "판독의 의견이다. 크기·이전 촬영·병력 등 서술어에 없는 정보가 섞여 있다")

    for r in tr + te:
        r["biopsy"] = int(r["grade"] >= 4) if r["grade"] is not None else None
    block("정답지 2 — 조직검사 여부 (등급을 4 이상 / 미만으로 접음)",
          tr, te, "biopsy", lambda p: int(p >= 4), a.top,
          "우리가 실제로 보고하는 판단이다. 등급이 틀려도 판단은 같을 수 있다")

    if n_path:
        block("정답지 3 — 병리 (조직을 떼서 확인한 결과)",
              tr, te, "path", lambda p: int(p >= 4), a.top,
              "의견이 아니라 사실이다. '판독의 흉내' 가 아니라 '악성 골라내기' 를 잰다")

    print("\n" + "=" * 74)
    print("읽는 법")
    print("=" * 74)
    print("  조합별 최적 매핑 = 서술어만 보고 도달할 수 있는 최대치다.")
    print("  그 위는 서술어에 없는 정보가 있어야 한다 — 영상, 크기, 이전 촬영.")
    print()
    print("  되찾을 수 있는 몫이 테스트에서도 크면")
    print("    -> 점수표를 고치는 것이 싸고 확실한 개선이다. 위 목록대로 고친다.")
    print("  1~2%p 수준이면")
    print("    -> 점수표는 이미 최적에 가깝다. 더 올리려면 영상 정보를 넣어야 한다.")
    print()
    print("  ! 학습 값은 낙관적이다. 같은 데이터에서 최빈값을 정하고 채점하기")
    print("    때문이다. 테스트 값을 실제 기대치로 읽어라.")
    print()
    print("  ! 목록의 '최적' 을 그대로 베끼지 마라. 임상적으로 거꾸로인 제안이")
    print("    섞인다. 선형 분포를 낮추라는 제안을 앞서 거부한 것과 같은 이유다.")


if __name__ == "__main__":
    main()
