#!/usr/bin/env python
"""
실행 간 변동 측정 — 같은 설정을 N 번 돌려 흩어짐을 잰다.

왜 필요한가
  train_mammo.py 에는 torch.manual_seed 호출이 없다. --seed 는 검증 분할과
  셔플 순서(numpy)만 정하고, 헤드 가중치 초기화는 torch 전역 RNG 를 쓴다.
  따라서 완전히 같은 명령을 두 번 돌려도 결과가 다르다.

  이걸 모르면 모든 A/B 비교가 위험하다. pos_weight 상한 실험에서 F1 이
  0.012 벌어졌지만 실제로 바뀐 가중치는 클래스 하나가 1.8% 뿐이었다.
  그 차이가 개선인지 잡음인지 가르려면 잡음의 크기를 알아야 한다.

무엇을 출력하는가
  검증 최고 · 마지막 에폭 테스트 F1 · top1 의 평균/표준편차/범위.
  그리고 '이 정도 차이는 잡음이다' 라고 말할 수 있는 기준선을 준다.

★ 이 스크립트는 기준선 체크포인트를 안 건드린다. --out 으로 임시 경로에
  저장하고 끝나면 지운다.
"""

import argparse, re, statistics, subprocess, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRAIN = HERE / "train_mammo.py"

RE_BEST = re.compile(r"검증 최고 \S+ ([\d.]+)\s+\(ep (\d+)\)")
RE_LAST = re.compile(r"마지막 에폭 테스트\s+F1\[([^\]]*)\]\s+top1\[([^\]]*)\]")
RE_SEL = re.compile(r"그 시점 테스트\s+F1\[([^\]]*)\]\s+top1\[([^\]]*)\]")


def parse_kv(blob):
    """'overall 0.623  calctype 0.559' -> {'overall': 0.623, ...}"""
    out = {}
    for k, v in re.findall(r"(\w+)\s+([\d.]+)", blob):
        out[k] = float(v)
    return out


def parse_run(text):
    r = {}
    m = RE_BEST.search(text)
    if m:
        r["val_best"] = float(m.group(1))
        r["val_ep"] = int(m.group(2))
    m = RE_LAST.search(text)
    if m:
        r["last_f1"] = parse_kv(m.group(1))
        r["last_top1"] = parse_kv(m.group(2))
    m = RE_SEL.search(text)
    if m:
        r["sel_f1"] = parse_kv(m.group(1))
        r["sel_top1"] = parse_kv(m.group(2))
    return r


def stat_line(name, vals, width=11):
    if not vals:
        return f"  {name:<20s}  (없음)"
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    lo, hi = min(vals), max(vals)
    return (f"  {name:<20s}{mean:>{width}.4f}{sd:>{width}.4f}"
            f"{lo:>{width}.4f}{hi:>{width}.4f}{hi-lo:>{width}.4f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["mass", "calc"], required=True)
    ap.add_argument("--n", type=int, default=5, help="반복 횟수")
    ap.add_argument("--seed", type=int, default=0,
                    help="고정한다. 분할까지 바꾸면 다른 변동이 섞인다")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--extra", default="",
                    help="train_mammo.py 로 그대로 넘길 추가 인자. "
                         "예: --extra '--pw-max 100'")
    ap.add_argument("--keep", action="store_true", help="임시 체크포인트를 안 지운다")
    a = ap.parse_args()

    base = ["python3", "-u", str(TRAIN), "--kind", a.kind, "--cache",
            "--no-pad", "--pool", "grid", "--grid", "4",
            "--seed", str(a.seed), "--epochs", str(a.epochs)]
    if a.extra:
        base += a.extra.split()

    print("=" * 78)
    print(f"실행 간 변동 측정 — {a.kind} · {a.n}회 반복")
    print("=" * 78)
    print(f"  명령  {' '.join(base[2:])}")
    print(f"  ★ --seed {a.seed} 고정 = 검증 분할과 셔플이 매번 동일하다.")
    print(f"    그래도 결과가 흩어진다면 그것은 헤드 초기값 때문이다.")
    print()

    runs, tmp_paths = [], []
    t0 = time.time()
    for i in range(1, a.n + 1):
        out = Path(f"ckpt/_var_{a.kind}_{i}.pt")
        tmp_paths.append(out)
        cmd = base + ["--out", str(out)]
        print(f"  [{i}/{a.n}] 실행 중 ...", end="", flush=True)
        t1 = time.time()
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            print(" 실패")
            print(p.stdout[-2000:])
            print(p.stderr[-2000:])
            sys.exit(f"{i}회차에서 실패했다")
        r = parse_run(p.stdout)
        if "val_best" not in r or "last_f1" not in r:
            print(" 파싱 실패")
            print(p.stdout[-1500:])
            sys.exit("출력 형식이 예상과 다르다")
        runs.append(r)
        print(f" {time.time()-t1:5.0f}s   검증 {r['val_best']:.4f} (ep {r['val_ep']:2d})"
              f"   마지막 테스트 F1 {r['last_f1']['overall']:.4f}"
              f"  top1 {r['last_top1']['mean']:.4f}")

    print(f"\n  총 {time.time()-t0:.0f}s")

    # ── 회차별 표 ──────────────────────────────────────────────
    axes = [k for k in runs[0]["last_f1"] if k != "overall"]
    print("\n" + "=" * 78)
    print("회차별")
    print("=" * 78)
    hdr = (f"  {'회차':<6s}{'검증최고':>10s}{'ep':>5s}{'테스트F1':>11s}{'top1평균':>11s}"
           + "".join(f"{ax[:9]:>11s}" for ax in axes))
    print(hdr)
    for i, r in enumerate(runs, 1):
        row = (f"  {i:<6d}{r['val_best']:>10.4f}{r['val_ep']:>5d}"
               f"{r['last_f1']['overall']:>11.4f}{r['last_top1']['mean']:>11.4f}")
        row += "".join(f"{r['last_f1'].get(ax, float('nan')):>11.4f}" for ax in axes)
        print(row)

    # ── 통계 ───────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("흩어짐")
    print("=" * 78)
    print(f"  {'지표':<20s}{'평균':>11s}{'표준편차':>11s}{'최소':>11s}"
          f"{'최대':>11s}{'범위':>11s}")
    print("  " + "-" * 74)
    print(stat_line("검증 최고", [r["val_best"] for r in runs]))
    print(stat_line("마지막 테스트 F1", [r["last_f1"]["overall"] for r in runs]))
    print(stat_line("마지막 top1 평균", [r["last_top1"]["mean"] for r in runs]))
    for ax in axes:
        print(stat_line(f"  F1 {ax}", [r["last_f1"][ax] for r in runs
                                       if ax in r["last_f1"]]))
    eps = [r["val_ep"] for r in runs]
    print(f"\n  선택된 에폭  {sorted(eps)}   (범위 {max(eps)-min(eps)})")

    # ── 판정 기준 ──────────────────────────────────────────────
    f1s = [r["last_f1"]["overall"] for r in runs]
    sd = statistics.stdev(f1s) if len(f1s) > 1 else 0.0
    rng = max(f1s) - min(f1s)
    print("\n" + "=" * 78)
    print("이 수치를 어떻게 쓰는가")
    print("=" * 78)
    print(f"  같은 설정을 {a.n}회 돌렸을 때 테스트 F1 이 {rng:.4f} 만큼 흩어졌다.")
    print(f"  표준편차 {sd:.4f}.")
    print()
    print(f"  앞으로 A/B 비교에서:")
    print(f"    차이 < {2*sd:.3f}  (2σ)   -> 잡음과 구분 불가. 개선이라 말하면 안 된다")
    print(f"    차이 > {3*sd:.3f}  (3σ)   -> 실재할 가능성이 높다")
    print(f"    그 사이            -> 반복 측정이 필요하다")
    print()
    print(f"  ※ 이건 헤드 초기값만의 변동이다. 검증 분할까지 바꾸면 더 커진다.")
    print(f"    LoRA 경로는 학습 시간이 길어 이 방식으로 재기 어렵다 —")
    print(f"    헤드 경로의 변동을 하한으로 삼아라.")

    if not a.keep:
        for p in tmp_paths:
            if p.exists():
                p.unlink()
        print(f"\n  임시 체크포인트 {len(tmp_paths)}개 삭제")
    else:
        print(f"\n  임시 체크포인트 유지: {[str(p) for p in tmp_paths]}")


if __name__ == "__main__":
    main()
