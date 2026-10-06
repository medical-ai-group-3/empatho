#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""판독 실측 2회차 — 꼬리가 왜 긴가, 워커를 몇 개 띄울 수 있나.

1회차에서 두 가지가 남았다.

  ① 중앙 5.63초인데 95퍼가 12.24초다. 두 배 넘게 벌어진다.
     병변 수가 0~21개였다. 서술어 모델은 **병변 하나마다** 조각을 오려
     돌리므로, 꼬리가 병변 수 때문일 가능성이 크다.

     이게 왜 중요한가
       잡음이면 재시도로 넘어간다. 병변 수면 **다시 넣어도 똑같이 느리다.**
       재시도가 답이 아니라는 뜻이고, 타임아웃을 넉넉히 잡아야 한다.
       그리고 병변 수에 상한이 있으면 **최악값이 정해진다.**

  ② GPU 여유가 11,666 → 772MB 로 떨어졌다.
     사실이면 판독 워커를 1개밖에 못 띄운다. 그러면 요청이 겹칠 때
     줄을 서고, 기다리는 시간이 「추론 시간」이 아니라
     「앞에 밀린 것 + 내 것」이 된다. API 를 비동기로 짜야 하는 근거다.

     다만 mem_get_info 의 여유값에는 **torch 할당자가 붙들고만 있는
     캐시**가 섞여 있다. 진짜 필요량은 max_memory_allocated 를 봐야 안다.

⚠ 두 번째 워커를 실제로 띄워 보지 않는다
  지금 GPU 를 다른 팀이 쓰고 있다. 11GB 를 더 잡으려다 실패하면
  **남의 학습이 같이 죽는다.** 그건 우리가 결정할 일이 아니다.
  이 스크립트는 메모리를 **더 잡지 않고** 이미 쓴 양의 최대치만 읽는다.

사용
  python3 training/code/measure_capacity.py            # 40장
  python3 training/code/measure_capacity.py --n 60
"""

import argparse
import statistics as st
import sys
import time
from pathlib import Path

try:
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402
import infer_mammo as M                                       # noqa: E402

MB = 2 ** 20


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def pct(v, q):
    v = sorted(v)
    if not v:
        return float("nan")
    return v[min(len(v) - 1, int(round((len(v) - 1) * q)))]


def free_mb():
    if not torch.cuda.is_available():
        return None
    return torch.cuda.mem_get_info()[0] / MB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--views", type=int, default=4)
    a = ap.parse_args()

    if not torch.cuda.is_available():
        die("GPU 가 없다. 이 측정은 GPU 에서만 뜻이 있다.")

    print("=" * 78)
    print("판독 실측 2회차 — 병변 수 · 메모리")
    print("=" * 78)

    other = 32607 - free_mb()          # 우리가 아직 아무것도 안 올렸다
    print(f"  시작 시점 GPU 여유 {free_mb():,.0f}MB "
          f"(다른 프로세스가 약 {other:,.0f}MB 쓰는 중)")

    ents = E.load_gt(a.split)
    uids = sorted(ents)[:a.n + a.warmup]
    if not uids:
        die("영상을 못 찾았다.")
    files = [str(ents[u]["dcm"]) for u in uids]

    print("\n■ 적재")
    torch.cuda.reset_peak_memory_stats()
    bundle = M.load_model()
    load_alloc = torch.cuda.memory_allocated() / MB
    print(f"  적재 직후 실제 점유 {load_alloc:,.0f}MB")

    print(f"\n■ 재는 중 — {len(files)}장")
    rows = []                                   # (병변수, 초)
    for i, f in enumerate(files, 1):
        img = Path(f).read_bytes()
        t = time.time()
        try:
            r = M.predict(bundle, img, name=Path(f).name)
        except Exception as e:
            print(f"\n  ! {Path(f).name[:30]} {type(e).__name__}: {e}")
            continue
        w = time.time() - t
        if i > a.warmup and isinstance(r, dict):
            rows.append((len(r.get("lesions") or []), w))
        print(f"\r    {i}/{len(files)}", end="", flush=True)
    print()

    if len(rows) < 10:
        die(f"잰 것이 {len(rows)}장뿐이다.")

    peak_alloc = torch.cuda.max_memory_allocated() / MB
    peak_resv = torch.cuda.max_memory_reserved() / MB
    free_before = free_mb()
    torch.cuda.empty_cache()
    free_after = free_mb()

    # ── ① 병변 수와 시간 ───────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"① 꼬리가 왜 긴가 — 병변 수와 시간  (사진 {len(rows)}장)")
    print("=" * 78)

    bins = [(0, 0), (1, 2), (3, 5), (6, 10), (11, 99)]
    print(f"\n  {'병변 수':<10}{'사진':>6}{'중앙':>9}{'최대':>9}")
    base = None
    for lo, hi in bins:
        v = [s for n, s in rows if lo <= n <= hi]
        if not v:
            continue
        m = st.median(v)
        if base is None:
            base = m
        lab = f"{lo}개" if lo == hi else f"{lo}~{hi}개"
        print(f"  {lab:<10}{len(v):>6}{m:>9.2f}{max(v):>9.2f}   (초)")

    ns = [n for n, _ in rows]
    ss = [s for _, s in rows]
    # 기울기 — 병변 1개가 몇 초를 더 쓰나 (최소제곱)
    mn, ms = st.mean(ns), st.mean(ss)
    den = sum((n - mn) ** 2 for n in ns)
    slope = (sum((n - mn) * (s - ms) for n, s in rows) / den) if den else 0.0
    icept = ms - slope * mn
    print(f"\n  병변 0개일 때의 바탕 시간   {icept:5.2f}초")
    print(f"  병변 1개마다 더 드는 시간   {slope:5.2f}초")
    print(f"  실제 병변 수 최대 {max(ns)}개 → 예상 {icept + slope*max(ns):.1f}초 "
          f"· 실측 최대 {max(ss):.1f}초")

    if slope > 0.15:
        print(f"""
  ▶ 꼬리는 **병변 수** 때문이다. 잡음이 아니다.

    같은 사진을 다시 넣어도 똑같이 느리다 — **재시도로 못 넘긴다.**
    타임아웃을 짧게 잡으면 «병변이 많은 사진»만 골라서 죽인다.
    그건 정확히 놓치면 안 되는 사진이다.""")
    else:
        print("""
  ▶ 병변 수로는 설명이 안 된다. 다른 원인이 있다 —
    GPU 를 같이 쓰는 다른 작업의 간섭일 가능성이 크다.""")

    # ── ② 메모리 ──────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("② 워커를 몇 개 띄울 수 있나")
    print("=" * 78)
    print(f"""
  실제로 필요한 양  {peak_alloc:>8,.0f}MB   ← 이것이 워커 1개의 몸값
  할당자가 붙든 양  {peak_resv:>8,.0f}MB   (캐시 포함 · 반납 가능)
  캐시 반납 전 여유 {free_before:>8,.0f}MB
  캐시 반납 후 여유 {free_after:>8,.0f}MB""")

    if peak_resv > peak_alloc * 1.3:
        print(f"""
  ▶ 1회차의 «여유 772MB» 는 과장이었다. 그 중 {peak_resv-peak_alloc:,.0f}MB 는
    torch 가 캐시로 붙들고 있던 것이고 반납된다.""")

    total = 32607.0
    room = total - other - peak_alloc
    n_fit = int(room // peak_alloc)
    print(f"""
  카드 전체 {total:,.0f}MB
   − 다른 팀 {other:,.0f}MB
   − 워커 1개 {peak_alloc:,.0f}MB
   = 남는 것 {room:,.0f}MB  →  워커를 {n_fit}개 **더** 띄울 수 있다""")

    if n_fit < 1:
        print(f"""
  ▶ **워커는 1개다.** 요청이 겹치면 줄을 서야 한다.

    그러면 기다리는 시간이 「추론 시간」이 아니라
    「앞에 밀린 것 × {pct(ss,.95)*a.views:.0f}초 + 내 것」이 된다.
    검사 3건이 같이 오면 세 번째는 시작도 못 한 채 {pct(ss,.95)*a.views*2:.0f}초를 기다린다.

    ▶ 판독 API 를 **동기로 붙들면 안 된다.** 202 + 작업 ID 로 돌려주고
      폴링이나 콜백으로 받아야 한다. HTTP 를 {pct(ss,.95)*a.views:.0f}초씩 붙들고 있으면
      게이트웨이 기본 타임아웃(보통 30~60초)에 먼저 잘린다.""")
    else:
        print(f"""
  ▶ 워커를 {n_fit+1}개까지 띄울 수 있다 — 다만 **다른 팀이 지금만큼만 쓸 때**다.
    저쪽이 늘리면 우리가 OOM 으로 죽는다. 여유를 한 칸 두는 것이 맞다.""")

    print(f"""
  ⚠ 다른 팀 {other:,.0f}MB 는 «지금» 값이다. 이 숫자가 바뀌면 결론도 바뀐다.
    발표 자료에는 「카드를 공유하는 조건에서 워커 1개」로 적는 것이 안전하다.""")

    # ── 타임아웃 ──────────────────────────────────────────────
    p95 = pct(ss, .95)
    print("\n" + "-" * 78)
    print("타임아웃 — 세 겹으로 나눈다")
    print("-" * 78)
    print(f"""
  ① 워커가 사진 1장에 무는 시간   {p95*2:>5.0f}초   (95퍼 {p95:.1f}초 × 2)
     넘으면 그 사진만 버리고 다음으로 간다.

  ② 작업 1건(검사)이 끝나야 하는 시간 {p95*a.views*2:>5.0f}초   (× 사진 {a.views}장)
     넘으면 작업을 실패로 적고 큐에서 뺀다.

  ③ 클라이언트가 기다리는 시간     **두지 않는다**
     202 로 즉시 돌려주므로 붙들 연결이 없다. 대신 큐 깊이에 상한을 두고
     넘치면 503 으로 거절한다 — 무한정 쌓이면 뒤에 온 요청이
     ②를 넘겨 전부 실패한다.

  ⚠ 큐 깊이 상한을 정하려면 «몇 분까지 기다려도 되나» 를 알아야 한다.
    이건 측정이 아니라 팀이 정할 값이다.""")


if __name__ == "__main__":
    main()
