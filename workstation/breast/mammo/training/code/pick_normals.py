#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""VinDr 에서 정상 검사를 골라 내려받을 목록을 만든다. 받지는 않는다.

왜 필요한가
  지금까지 낸 수치는 전부 **병변이 있는 영상**에서 나왔다. CBIS 는 조직검사가
  확정된 사례만 모아 놓은 자료라 정상 영상이 아예 없다(598장 중 0장).

  그래서 모르는 것이 하나 있다 —
  **병변이 없는 유방에 이 시스템이 뭐라고 하는가.**

  검진에서는 대부분이 정상이다. 거기서 계속 「BI-RADS 4c · 조직검사 권고」가
  나오면 못 쓴다. 한 번도 확인한 적이 없다.

사진이 아니라 검사를 뽑는다
  검진에서 문제가 되는 건 「이 사진이 조용한가」가 아니라
  **「이 여성이 재소환되는가」**다. 4장 중 하나만 울려도 부른다.

  사진당 오탐률이 20%면 검사당은 1 − 0.8⁴ = 59% 다. **세 배 차이다.**
  사진 단위로만 재면 실제보다 훨씬 좋아 보인다.

  그래서 검사를 통째로(4장) 뽑는다. 그러면 둘 다 낼 수 있다.

BI-RADS 2 를 섞지 않는다
  VinDr 는 BI-RADS 3 이상에만 병변을 표시한다. **BI-RADS 2 는 양성 소견이
  실제로 있는데 표시가 없다.** 그걸 정상으로 놓고 재면 모델이 맞게 찾은 것을
  오탐으로 세게 된다.

  기본은 BI-RADS 1 만이다. 2 는 --birads 로 따로 뽑아 따로 잰다.

  ⚠ 한 검사의 **네 장이 전부** 해당 등급이어야 한다. 한쪽 유방만 정상인
    검사가 섞이면 반대쪽 병변을 오탐으로 세게 된다.

밀도는 VinDr 분포 그대로 둔다
  VinDr 는 밀도 C 가 76% 다(베트남 검진 인구). 균등하게 맞추면 실제 인구와
  다른 수치가 나온다. 비례로 뽑고 **밀도별로 따로 보고한다.**

  밀도 A 는 전체에 100장뿐이라 비례로는 한두 장이다. 거기서는 아무 말도
  못 한다 — 그건 그대로 적으면 된다.

사용
  python3 training/code/pick_normals.py                    # 75건 = 300장
  python3 training/code/pick_normals.py --studies 100
  python3 training/code/pick_normals.py --birads "BI-RADS 2" --out-tag b2
"""

import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import RAW_VINDR                                   # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "archive" / "outputs"
BREAST_CSV = OUT / "vindr_breast_level.csv"
OLD_MANIFEST = OUT / "vindr_manifest.csv"
BASE_URL = "https://physionet.org/files/vindr-mammo/1.0.0/images"
WANT_VIEWS = {("L", "CC"), ("L", "MLO"), ("R", "CC"), ("R", "MLO")}
CODE = {("L", "CC"): "LCC", ("L", "MLO"): "LMLO",
        ("R", "CC"): "RCC", ("R", "MLO"): "RMLO"}


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def avg_image_mb():
    """이미 받은 것으로 한 장 크기를 잰다 — 짐작하지 않는다."""
    d = Path(RAW_VINDR)
    if not d.is_dir():
        return None
    f = [p for p in d.rglob("*") if p.suffix.lower() in (".dicom", ".dcm")]
    if not f:
        return None
    return sum(p.stat().st_size for p in f) / len(f) / 2**20


def allocate(counts, total):
    """비례 배분. 최대잉여법 — 반올림으로 합이 어긋나지 않게."""
    s = sum(counts.values())
    if s == 0:
        return {}
    raw = {k: total * v / s for k, v in counts.items()}
    out = {k: int(v) for k, v in raw.items()}
    rest = total - sum(out.values())
    for k, _ in sorted(raw.items(), key=lambda kv: -(kv[1] - int(kv[1]))):
        if rest <= 0:
            break
        out[k] += 1
        rest -= 1
    return {k: min(v, counts[k]) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--birads", default="BI-RADS 1")
    ap.add_argument("--split", default="test")
    ap.add_argument("--studies", type=int, default=75)
    ap.add_argument("--out-tag", default="normal")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    if not BREAST_CSV.is_file():
        die(f"유방 단위 표가 없다: {BREAST_CSV}\n"
            "  wget 으로 받아 archive/outputs 에 둘 것.")

    rows = list(csv.DictReader(open(BREAST_CSV, encoding="utf-8")))
    print("=" * 78)
    print(f"VinDr 정상 검사 고르기 — {a.birads} · {a.split}")
    print("=" * 78)
    print(f"  표 전체 {len(rows):,}행")

    # ── 검사 단위로 묶는다 ──────────────────────────────────────
    by_study = defaultdict(list)
    for r in rows:
        if r["split"] == a.split:
            by_study[r["study_id"]].append(r)
    print(f"  {a.split} 검사 {len(by_study):,}건")

    # 이미 점수를 낸 검사는 뺀다 — 겹치면 「새로 본 것」이 아니게 된다
    used = set()
    if OLD_MANIFEST.is_file():
        used = {x["study_id"]
                for x in csv.DictReader(open(OLD_MANIFEST, encoding="utf-8"))}

    # 이미 디스크에 있는 것도 빼려면 알아야 한다
    have = set()
    d = Path(RAW_VINDR)
    if d.is_dir():
        have = {p.stem for p in d.rglob("*")
                if p.suffix.lower() in (".dicom", ".dcm")}

    # ── 거른다. **왜 걸렀는지 센다** ────────────────────────────
    drop = Counter()
    ok = {}
    for sid, rs in by_study.items():
        if sid in used:
            drop["이미 점수를 낸 검사"] += 1
            continue
        if any(x["breast_birads"] != a.birads for x in rs):
            drop[f"{a.birads} 이 아닌 유방이 섞임"] += 1
            continue
        pick = {}
        for x in rs:
            key = (x["laterality"].strip().upper()[:1],
                   x["view_position"].strip().upper())
            if key in WANT_VIEWS:
                # 같은 시야가 여러 장이면 image_id 순으로 하나만 — 결정적으로
                if key not in pick or x["image_id"] < pick[key]["image_id"]:
                    pick[key] = x
        if set(pick) != WANT_VIEWS:
            drop["네 시야가 다 있지 않음"] += 1
            continue
        if any(x["image_id"] in have for x in pick.values()):
            drop["이미 디스크에 있음"] += 1
            continue
        dens = Counter(x["breast_density"] for x in pick.values())
        ok[sid] = {"rows": pick, "density": max(sorted(dens), key=dens.get)}

    print(f"\n  쓸 수 있는 검사 {len(ok):,}건")
    for k, v in drop.most_common():
        print(f"    뺀 것 — {k:<28} {v:,}건")

    if len(ok) < a.studies:
        print(f"\n  ⚠ 쓸 수 있는 것이 {len(ok)}건뿐이다. 요청 {a.studies}건보다 적다.")
        a.studies = len(ok)
    if not ok:
        die("고를 것이 없다.")

    # ── 밀도 비례로 뽑는다 ──────────────────────────────────────
    pool = defaultdict(list)
    for sid, v in ok.items():
        pool[v["density"]].append(sid)
    counts = {k: len(v) for k, v in pool.items()}
    quota = allocate(counts, a.studies)

    rng = random.Random(a.seed)
    chosen = []
    for dens in sorted(pool):
        ids = sorted(pool[dens])
        rng.shuffle(ids)
        chosen += ids[:quota.get(dens, 0)]
    chosen.sort()

    print(f"\n  {'밀도':<12}{'있는 검사':>10}{'뽑은 검사':>10}{'비율':>8}")
    for dens in sorted(counts):
        n = quota.get(dens, 0)
        print(f"  {dens:<12}{counts[dens]:>10,}{n:>10}"
              f"{counts[dens]/len(ok)*100:>7.1f}%")
    thin = [d for d in sorted(counts) if quota.get(d, 0) < 5]
    if thin:
        print(f"\n  ⚠ {', '.join(thin)} 는 뽑힌 검사가 5건 미만이다.")
        print("    그 구간은 수치를 내지 말 것 — 표본이 없다는 사실만 적는다.")

    # ── 목록을 쓴다 ─────────────────────────────────────────────
    OUT.mkdir(parents=True, exist_ok=True)
    man = OUT / f"vindr_{a.out_tag}_manifest.csv"
    urls = OUT / f"vindr_{a.out_tag}_urls.txt"
    dest = Path(RAW_VINDR) / a.out_tag

    n_img = 0
    with open(man, "w", newline="", encoding="utf-8") as fh, \
            open(urls, "w", encoding="utf-8") as uh:
        w = csv.writer(fh)
        w.writerow(["study_id", "image_id", "laterality", "view_position",
                    "view_code", "breast_birads", "breast_density", "path"])
        for sid in chosen:
            v = ok[sid]
            for key in sorted(WANT_VIEWS):
                x = v["rows"][key]
                p = dest / f"{x['image_id']}.dicom"
                w.writerow([sid, x["image_id"], key[0], key[1], CODE[key],
                            x["breast_birads"], x["breast_density"], str(p)])
                uh.write(f"{BASE_URL}/{sid}/{x['image_id']}.dicom\n")
                n_img += 1

    mb = avg_image_mb()
    gb = (mb * n_img / 1024) if mb else None
    print(f"\n  검사 {len(chosen)}건 · 영상 {n_img}장")
    print(f"    {man.relative_to(REPO)}")
    print(f"    {urls.relative_to(REPO)}")
    if gb:
        print(f"\n  예상 용량 {gb:.1f}GB  (이미 받은 것 평균 {mb:.1f}MB/장 기준)")

    print(f"""
받는 명령 — **디스크부터 보고**

  df -h ~/workspace | tail -1

  mkdir -p {dest}
  wget -nv -c -P {dest} -i {urls.relative_to(REPO)}

  -c 는 끊겨도 이어받는다. -nv 는 한 줄씩만 찍는다.
  ~/.netrc 의 PhysioNet 자격증명을 wget 이 알아서 쓴다 —
  **화면에 자격증명이 찍히면 안 된다.**

  받은 뒤 확인

  ls {dest} | wc -l        # {n_img} 이어야 한다""")

    print("""
⚠ 이 목록으로 무엇을 재는지

  ① 검출 0건 비율      정상 영상에서 아무 말도 안 하는 비율
  ② 영상당 검출 수      나오면 몇 개나 (종류별)
  ③ 그 중 조직검사 권고  BI-RADS 4 이상이 뜨는 비율
  ④ **검사 단위** ①~③  4장 중 하나라도 울리면 재소환이다

  ④ 가 검진에서 실제로 뜻이 있는 값이다. ① 만 보면 실제보다 좋아 보인다.""")


if __name__ == "__main__":
    main()
