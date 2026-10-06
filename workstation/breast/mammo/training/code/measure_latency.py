#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""맘모 판독이 실제로 얼마나 걸리나 — 소켓 타임아웃을 정하려고.

왜
  소켓 타임아웃 값이 아직 미정이다. 짐작으로 정하면 둘 중 하나가 된다.
    너무 짧으면  멀쩡한 판독이 끊긴다
    너무 길면    죽은 요청을 붙들고 앞이 막힌다

  **서빙 경로 그대로** 재야 한다. 평가 스크립트로 재면 배치·전처리가 달라
  실제와 다른 값이 나온다. 그래서 infer_mammo.predict() 를 그대로 부른다.

무엇을 재나
    적재      모델이 올라오는 시간 (요청마다 드는 것이 아니다)
    사진 1장  predict() 한 번 — 이게 타임아웃의 근거
    검사 1건  **사진 1장 × 4** — 맘모는 CC·MLO 양측 4장이다

  마지막이 중요하다. DB 스키마 v8 에서 ai_result 가 사진 1장에 1행이고
  맘모는 study 당 4행이 생긴다. **소켓이 검사 1건에 4번 호출된다.**
  검사 단위로 타임아웃을 잡으면 4배를 봐야 한다.

조심할 것
  GPU 를 다른 팀과 같이 쓴다. 남이 학습을 돌리는 중이면 값이 늘어난다.
  그래서 잴 때 GPU 여유를 같이 기록하고, **한가할 때와 바쁠 때 두 번**
  재는 것이 맞다. 한 번만 재고 정하면 바쁠 때 전부 끊긴다.

  첫 두 번은 버린다 — CUDA 커널이 처음 도는 값이라 실제와 다르다.

사용
  python3 training/code/measure_latency.py            # 40장
  python3 training/code/measure_latency.py --n 100
"""

import argparse
import inspect
import statistics as st
import sys
import time
from pathlib import Path

try:
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402
import infer_mammo as M                                       # noqa: E402


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def gpu_free_mb():
    if not torch.cuda.is_available():
        return None
    free, _total = torch.cuda.mem_get_info()
    return free / 2**20


def pct(v, q):
    v = sorted(v)
    if not v:
        return float("nan")
    i = min(len(v) - 1, int(round((len(v) - 1) * q)))
    return v[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=40, help="잴 사진 수")
    ap.add_argument("--warmup", type=int, default=2, help="버릴 앞쪽 횟수")
    ap.add_argument("--views", type=int, default=4,
                    help="검사 1건의 사진 수 (맘모 CC·MLO 양측)")
    ap.add_argument("--mode", choices=("bytes", "path"), default="bytes",
                    help="image 를 무엇으로 넘길지. bytes 가 실제 서빙 형태")
    a = ap.parse_args()

    print("=" * 78)
    print("맘모 판독 소요 시간 — 서빙 경로 그대로")
    print("=" * 78)

    free0 = gpu_free_mb()
    print(f"  GPU 여유 {free0:,.0f}MB" if free0 else "  GPU 없음")
    if free0 is not None and free0 < 6000:
        print("  ⚠ 여유가 적다. 남이 GPU 를 쓰는 중이면 값이 늘어난다.")

    ents = E.load_gt(a.split)
    uids = sorted(ents)[:a.n + a.warmup]
    if not uids:
        die("영상을 못 찾았다.")
    files = [str(ents[u]["dcm"]) for u in uids]
    print(f"  영상 {len(files)}장 (앞 {a.warmup}장은 버린다)")

    # ── 적재 ────────────────────────────────────────────────────
    # serve_mammo.py:166 이 _BUNDLE 을 한 번 만들어 두고 재사용한다.
    # 여기서도 같은 것을 만든다 — 요청마다 드는 비용이 아니다.
    print("\n■ 모델 적재 (load_model)")
    if not hasattr(M, "load_model"):
        die("infer_mammo.load_model 이 없다.")
    t0 = time.time()
    bundle = M.load_model()
    load_s = time.time() - t0
    print(f"  {load_s:.1f}초")

    if not hasattr(M, "predict"):
        die("infer_mammo.predict 가 없다.")
    sig = inspect.signature(M.predict)
    print(f"  predict{sig}")

    # ── 부르는 형태 ────────────────────────────────────────────
    # serve_mammo.py:166  predict(_BUNDLE, data, name=name)   ← data 는 바이트
    # check_serving.py:358 predict(bundle, str(src))          ← 경로 문자열
    #
    # **바이트가 실제 서빙 형태다.** 소켓이 무는 구간이 그것이다.
    # 경로로 재면 파일 읽기가 predict() 안에서 다르게 일어나 실제와 어긋난다.
    print(f"\n■ 재는 중 — image 를 «{a.mode}» 로 넘긴다")
    if a.mode == "bytes":
        print("     (serve_mammo.py:166 과 같은 형태)")
    else:
        print("     ⚠ check_serving 형태다. 서빙은 바이트로 받는다.")

    wall, inner, n_les, read_s = [], [], [], []
    for i, f in enumerate(files, 1):
        tr = time.time()
        img = Path(f).read_bytes() if a.mode == "bytes" else str(f)
        rd = time.time() - tr

        t = time.time()
        try:
            r = M.predict(bundle, img, name=Path(f).name)
        except TypeError as e:
            die(f"부르는 형태가 틀렸다: {e}\n"
                f"  쓴 것: predict(bundle, <{a.mode}>, name=...)\n"
                f"  서명: predict{sig}")
        except Exception as e:
            print(f"\n  ! {Path(f).name[:30]} 실패: {type(e).__name__}: {e}")
            continue
        w = time.time() - t
        if i > a.warmup:
            wall.append(w)
            read_s.append(rd)
            if isinstance(r, dict):
                if "elapsed_sec" in r:
                    inner.append(float(r["elapsed_sec"]))
                n_les.append(len(r.get("lesions") or []))
        print(f"\r    {i}/{len(files)}  {w:.2f}초", end="", flush=True)
    print()

    if len(wall) < 5:
        die(f"잰 것이 {len(wall)}장뿐이다.")

    free1 = gpu_free_mb()

    # ── 결과 ────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"결과 — 사진 {len(wall)}장")
    print("=" * 78)
    print(f"\n  {'':12}{'중앙':>8}{'90퍼':>8}{'95퍼':>8}{'최대':>8}")
    print(f"  {'사진 1장':<12}{st.median(wall):>8.2f}{pct(wall,.90):>8.2f}"
          f"{pct(wall,.95):>8.2f}{max(wall):>8.2f}   (초)")
    if inner:
        print(f"  {'└ 추론만':<12}{st.median(inner):>8.2f}{pct(inner,.90):>8.2f}"
              f"{pct(inner,.95):>8.2f}{max(inner):>8.2f}")
        ov = st.median(wall) - st.median(inner)
        print(f"  {'└ 그 밖':<12}{ov:>8.2f}"
              "                        (읽기 · 전처리 · 응답 만들기)")
    if read_s:
        print(f"  {'└ 파일 읽기':<12}{st.median(read_s):>8.3f}"
              "                        (predict 밖 · 서버는 소켓에서 받는다)")
    p95 = pct(wall, .95)
    print(f"\n  검사 1건 (사진 {a.views}장)  95퍼 기준 "
          f"**{p95 * a.views:.1f}초**")
    if n_les:
        print(f"  병변 수 중앙 {st.median(n_les):.0f}개 "
              f"(0~{max(n_les)})  — 많이 뜰수록 서술어가 오래 걸린다")
    print(f"  모델 적재 {load_s:.1f}초 — 요청마다 드는 것이 아니다")
    if free0 and free1:
        print(f"  GPU 여유 {free0:,.0f} → {free1:,.0f}MB")

    # ── 권고 ────────────────────────────────────────────────────
    per = p95 * 2.0
    study = p95 * a.views * 2.0
    print("\n" + "-" * 78)
    print("타임아웃 제안")
    print("-" * 78)
    print(f"""
  사진 1장   {per:>6.0f}초   (95퍼 {p95:.1f}초 × 2)
  검사 1건   {study:>6.0f}초   (× 사진 {a.views}장)

  95퍼에 2배를 두는 이유
    GPU 를 다른 팀과 같이 쓴다. 남이 학습을 돌리는 중이면 이 값이
    그대로 늘어난다. **한가할 때 잰 값에 여유를 안 두면 바쁠 때
    전부 끊긴다.**

  ⚠ 이 값은 «지금 GPU 상태» 에서 잰 것이다. 바쁠 때 한 번 더 재서
    두 값을 비교하고, 큰 쪽에 여유를 두는 것이 맞다.

  ⚠ 적재 {load_s:.0f}초는 별개다. 서버가 막 뜬 직후 첫 요청은
    이만큼 더 걸린다 — 그 구간은 503 으로 돌려보내고 재시도하게
    돼 있다(mammo_api.md 상태 코드).""")


if __name__ == "__main__":
    main()
