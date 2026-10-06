#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""정상 유방에 이 시스템이 무슨 말을 하는지 잰다.

한 번도 안 본 것
  지금까지 낸 수치는 전부 병변이 있는 영상에서 나왔다. CBIS 는 조직검사가
  확정된 사례만 모아 놓은 자료라 정상 영상이 0장이다.

  검진에서는 대부분이 정상이다. 거기서 계속 「조직검사 권고」가 나오면
  시스템을 못 쓴다. 이 스크립트가 그 값을 낸다.

재는 것 넷
    ① 조용한 비율        검출이 하나도 없는 비율
    ② 나오면 몇 개        영상당 검출 수 (종류별)
    ③ 조직검사 권고 비율  BI-RADS 4 이상이 뜨는 비율
    ④ **검사 단위** 위 셋  4장 중 하나만 울려도 재소환이다

  ④ 가 검진에서 뜻이 있는 값이다. ① 만 보면 실제보다 좋아 보인다 —
  사진당 20%면 검사당은 1 − 0.8⁴ = 59% 다.

비싼 일과 싼 일을 나눈다
  추론은 300장에 한 시간쯤 걸린다. 분석은 몇 초다. 그래서 추론 결과를
  jsonl 로 한 줄씩 남기고, 분석은 --report 로 몇 번이든 다시 돈다.

  ⚠ 이어서 돈다. 이미 있는 줄은 건너뛴다. 끊겨도 처음부터 안 한다.

덤 — 시야 대조가 처음으로 실제로 돈다
  VinDr 표에 laterality · view_position 이 있다. 그 값을 view_code 로 넘기면
  DICOM 태그와 대조된다. CBIS 는 태그가 비어 있어서 view_conflict 검사가
  **한 번도 발동할 수 없었다.** 여기서 처음 돈다.

사용
  python3 training/code/score_normals.py                # 추론 (이어서)
  python3 training/code/score_normals.py --report       # 표만 다시
"""

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "archive" / "outputs"
sys.path.insert(0, str(Path(__file__).resolve().parent))


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def load_manifest(p):
    if not p.is_file():
        die(f"목록이 없다: {p}\n  pick_normals.py 를 먼저 돌릴 것.")
    return list(csv.DictReader(open(p, encoding="utf-8")))


# ────────────────────────────── 추론 ──────────────────────────────
def run(rows, jl, limit, settle):
    import infer_mammo as M

    # ⚠ **성공한 것만** 「이미 한 것」이다.
    #   실패를 이어달리기에 넣으면 일시적 실패가 영구 결손이 된다.
    #   받는 중인 파일을 읽어 터진 적이 있고, 그 2장은 영영 안 나올 뻔했다.
    done = set()
    if jl.is_file():
        for line in jl.open(encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:                              # noqa: BLE001
                continue
            if "error" not in r:
                done.add(r["image_id"])
    todo = [r for r in rows if r["image_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"  전체 {len(rows)}장 · 성공한 것 {len(done)} · 이번에 {len(todo)}장")
    if not todo:
        print("  할 것이 없다.")
        return

    # 받는 중인 파일을 걸러 낸다. wget 은 최종 이름으로 바로 쓰기 때문에
    # **반쯤 받은 파일도 존재는 한다.** 존재만 보면 잘린 화소를 읽고 터진다.
    now = time.time()
    absent = [r for r in todo if not Path(r["path"]).is_file()]
    fresh = [r for r in todo
             if Path(r["path"]).is_file()
             and now - Path(r["path"]).stat().st_mtime < settle]
    todo = [r for r in todo
            if Path(r["path"]).is_file()
            and now - Path(r["path"]).stat().st_mtime >= settle]
    if absent:
        print(f"  아직 안 받은 것 {len(absent)}장 — 건너뛴다")
    if fresh:
        print(f"  방금 쓰인 것 {len(fresh)}장 — **받는 중일 수 있어 건너뛴다** "
              f"(최근 {settle}초)")
    if not todo:
        die("지금 돌릴 것이 없다. 다운로드가 끝난 뒤 다시 돌릴 것 — 이어서 간다.")

    bundle = M.load_model(verbose=False)
    t0 = time.time()
    with jl.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(todo, 1):
            try:
                res = M.predict(bundle, r["path"], name=r["image_id"] + ".dicom",
                                view_code=r["view_code"])
            except Exception as e:                          # noqa: BLE001
                rec = {"image_id": r["image_id"], "study_id": r["study_id"],
                       "density": r["breast_density"],
                       "view_csv": r["view_code"], "error":
                       f"{type(e).__name__}: {e}"[:200]}
            else:
                rec = {
                    "image_id": r["image_id"], "study_id": r["study_id"],
                    "density": r["breast_density"], "view_csv": r["view_code"],
                    "view_tag": (res.get("dicom") or {}).get("view_code"),
                    "abstained": res["summary"]["abstained"],
                    "n_lesions": res["summary"]["n_lesions"],
                    "max_birads": res["summary"]["max_birads"],
                    "biopsy": res["summary"]["biopsy"],
                    "elapsed": res["elapsed_sec"],
                    "lesions": [
                        {"kind": l["kind"], "score": l["score"],
                         "birads": l["birads"], "biopsy": l["biopsy"],
                         "box": l["box"], "evidence_id": l.get("evidence_id"),
                         "omit": l.get("evidence_id_omitted_reason")}
                        for l in res["lesions"]],
                }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            el = time.time() - t0
            eta = el / i * (len(todo) - i)
            print(f"\r    {i}/{len(todo)}  {el/60:.1f}분 경과 · "
                  f"남은 {eta/60:.0f}분", end="", flush=True)
    print()


# ────────────────────────────── 분석 ──────────────────────────────
def pct(n, d):
    return f"{n/d*100:5.1f}%" if d else "    -"


def report(jl):
    if not jl.is_file():
        die(f"결과가 없다: {jl}")
    # 같은 영상이 여러 줄일 수 있다 — 실패했다가 나중에 성공한 경우.
    # **마지막 줄이 이긴다.** 안 그러면 한 장을 실패와 성공 양쪽으로 센다.
    last = {}
    for x in jl.open(encoding="utf-8"):
        if not x.strip():
            continue
        try:
            r = json.loads(x)
        except Exception:                                  # noqa: BLE001
            continue
        last[r["image_id"]] = r
    recs = list(last.values())
    err = [r for r in recs if "error" in r]
    recs = [r for r in recs if "error" not in r]
    if not recs:
        die("성공한 것이 없다.")

    print("=" * 78)
    print(f"정상 유방(BI-RADS 1)에서 무슨 말을 하나 — 영상 {len(recs)}장")
    print("=" * 78)
    if err:
        print(f"\n  ⚠ 아직 성공 못 한 것 {len(err)}장 — 다시 돌리면 재시도한다")
        for k, v in Counter(r["error"].split(":")[0] for r in err).most_common():
            print(f"      {k} {v}")

    # ── 사진 단위 ────────────────────────────────────────────────
    n = len(recs)
    quiet = sum(1 for r in recs if r["n_lesions"] == 0)
    biop = sum(1 for r in recs if r["biopsy"])
    print(f"\n■ 사진 단위 ({n}장)")
    print(f"  조용함 (검출 0건)        {quiet:4d}   {pct(quiet, n)}")
    print(f"  뭔가 나옴                {n-quiet:4d}   {pct(n-quiet, n)}")
    print(f"  조직검사 권고까지 감      {biop:4d}   {pct(biop, n)}   ← 제일 나쁜 것")

    les = [l for r in recs for l in r["lesions"]]
    kc = Counter(l["kind"] for l in les)
    print(f"\n  검출 총 {len(les)}건 · 영상당 평균 {len(les)/n:.2f}건")
    for k, v in kc.most_common():
        print(f"      {k:16s} {v:4d}   영상당 {v/n:.2f}")
    print("      (CBIS 작동점은 «종류당 영상당 오탐 2개» 였다. 그건 병변이")
    print("       있는 영상에서 잰 값이고, 여기 값과 같을 이유가 없다.)")

    nz = Counter(r["n_lesions"] for r in recs)
    print("\n  영상당 검출 수 분포")
    for k in sorted(nz):
        print(f"      {k:2d}건  {nz[k]:4d}  {'█' * int(nz[k]/n*50)}")

    bc = Counter(r["max_birads"] for r in recs if r["max_birads"])
    if bc:
        print("\n  나온 최고 등급")
        for k in sorted(bc, key=str):
            print(f"      {str(k):6s} {bc[k]:4d}   {pct(bc[k], n)}")

    # ── 검사 단위 ────────────────────────────────────────────────
    st = defaultdict(list)
    for r in recs:
        st[r["study_id"]].append(r)
    full = {k: v for k, v in st.items() if len(v) == 4}
    print(f"\n■ 검사 단위 ({len(full)}건 · 4장이 다 있는 것만)")
    if full:
        sq = sum(1 for v in full.values() if all(r["n_lesions"] == 0 for r in v))
        sb = sum(1 for v in full.values() if any(r["biopsy"] for r in v))
        print(f"  네 장 다 조용함          {sq:4d}   {pct(sq, len(full))}")
        print(f"  하나라도 울림 (재소환)    {len(full)-sq:4d}   "
              f"{pct(len(full)-sq, len(full))}")
        print(f"  조직검사 권고            {sb:4d}   {pct(sb, len(full))}")
        print("""
  ⚠ 검사 단위가 검진에서 뜻이 있는 값이다. 4장 중 하나만 울려도 그 여성은
    다시 불려 온다. 사진 단위만 보면 실제보다 좋아 보인다.""")

    # ── 밀도별 ──────────────────────────────────────────────────
    print("\n■ 밀도별 (사진 단위)")
    dg = defaultdict(list)
    for r in recs:
        dg[r["density"]].append(r)
    print(f"  {'밀도':<12}{'사진':>6}{'조용함':>9}{'조직검사':>9}{'영상당 검출':>12}")
    for d in sorted(dg):
        v = dg[d]
        q = sum(1 for r in v if r["n_lesions"] == 0)
        b = sum(1 for r in v if r["biopsy"])
        m = sum(r["n_lesions"] for r in v) / len(v)
        mark = "  ← 표본 부족" if len(v) < 20 else ""
        print(f"  {d:<12}{len(v):>6}{pct(q, len(v)):>9}{pct(b, len(v)):>9}"
              f"{m:>12.2f}{mark}")

    # ── 시야 대조 ────────────────────────────────────────────────
    print("\n■ 시야 대조 — DICOM 태그와 VinDr 표가 맞나")
    tag = Counter(r.get("view_tag") for r in recs)
    same = sum(1 for r in recs if r.get("view_tag") == r["view_csv"])
    none = sum(1 for r in recs if r.get("view_tag") is None)
    diff = n - same - none
    print(f"  태그를 읽음              {n-none:4d} / {n}")
    print(f"  표와 같음                {same:4d}")
    print(f"  표와 다름                {diff:4d}"
          + ("   ← **확인할 것**" if diff else ""))
    om = Counter(l["omit"] for r in recs for l in r["lesions"] if l["omit"])
    if om:
        print("  이름표를 못 붙인 사유")
        for k, v in om.most_common():
            print(f"      {k} {v}")
    elif les:
        print(f"  이름표 정상 부착 {sum(1 for l in les if l['evidence_id'])}"
              f" / {len(les)}")

    print(f"""
■ 이 값을 어떻게 읽나

  이 수치는 **VinDr 정상 검사 {len(full)}건**에서 나왔다. CBIS 로 잰 것과
  다른 자료·다른 인구(베트남 검진)이고, 밀도 C 가 대부분이다.

  ⚠ 「정상에서 오탐이 이만큼」이라고 쓸 때 반드시 함께 적을 것 —
    작동점을 CBIS 의 «종류당 오탐 2개» 로 잡았다는 사실. 그 작동점은
    **병변이 있는 영상**을 기준으로 고른 것이라 검진 인구에 맞춰 고른
    값이 아니다. 여기 수치가 나쁘면 모델이 아니라 작동점을 다시 봐야 한다.""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(OUT / "vindr_normal_manifest.csv"))
    ap.add_argument("--jsonl", default=str(OUT / "normal_dets.jsonl"))
    ap.add_argument("--limit", type=int, default=0, help="이번에 몇 장만")
    ap.add_argument("--settle", type=int, default=90,
                    help="이 초 안에 쓰인 파일은 받는 중으로 보고 건너뛴다")
    ap.add_argument("--report", action="store_true", help="추론 없이 표만")
    a = ap.parse_args()

    jl = Path(a.jsonl)
    if a.report:
        report(jl)
        return

    rows = load_manifest(Path(a.manifest))
    print("=" * 78)
    print("정상 유방 추론")
    print("=" * 78)
    run(rows, jl, a.limit, a.settle)
    print()
    report(jl)


if __name__ == "__main__":
    main()
