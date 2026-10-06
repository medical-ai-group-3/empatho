#!/usr/bin/env python
"""
타일 학습 설정을 만든다 — 그리고 그 전에 범주 번호를 기준선과 맞춘다.

두 가지를 한다

1. 범주 번호 교정
   기존 det/       1 = mass          2 = calcification
   새   det_tile/   1 = calcification 2 = mass          (만들 때 어긋났다)

   각자 안에서는 일관돼서 지금은 안 깨진다. 문제는 나중이다. 평가기를 잘못
   겨누면 종류가 조용히 뒤바뀌어 '석회 62% · 종괴 6.8%' 같은 그럴듯한 오답이
   나온다. 영상은 그대로 두고 주석의 번호만 바꾼다.

2. 설정 생성
   경로를 det -> det_tile 로 옮기고, 학습 예산을 스텝 수로 맞춘다.

왜 텍스트로 고치나
   설정 객체를 순회하면 값을 꺼내는 순간 OmegaConf 가 ${times:...} 같은
   사용자 정의 리졸버를 계산하려 든다. 그 리졸버는 학습 코드가 실행 시점에
   등록하므로 여기서는 없다. 바꿀 것이 경로 치환과 스칼라 몇 개뿐이라
   텍스트로 다루는 편이 안전하고 서식도 보존된다.

왜 에폭이 아니라 스텝으로 맞추나
   타일은 7,813장, 기준선은 2,220장이다. 같은 20에폭을 돌리면 계산량이
   3.5배가 되어 개선이 데이터 때문인지 학습량 때문인지 못 가린다.

     기준선   20에폭 x 2,220 = 44,400 스텝
     타일     N에폭  x 7,813 = 같은 수준

   타일 쪽이 데이터를 덜 반복하게 되는데 그건 타일에 불리한 조건이다.
   불리한 조건에서 이기면 결론이 더 강해진다.

사용
  python3 make_tile_cfg.py                 # 무엇을 바꿀지만 보여준다
  python3 make_tile_cfg.py --go
"""

import argparse
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

try:
    from omegaconf import OmegaConf
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

HOME = Path.home()
MAMMO = HOME / "workspace/breast/mammo"
BASE_CFG = MAMMO / "sam3/train/configs/mammo/mammo_det.yaml"
OUT_CFG = MAMMO / "sam3/train/configs/mammo/mammo_det_tile.yaml"
BASE_DIR = MAMMO / "det"
TILE_DIR = MAMMO / "det_tile"

# 기준선의 규칙 — 여기에 맞춘다
WANT = {"mass": 1, "calcification": 2}


# ── 1. 범주 번호 교정 ────────────────────────────────────────────────────

def fix_cats(go):
    print("=" * 76)
    print("1. 범주 번호를 기준선과 맞춘다")
    print("=" * 76)
    for split in ("train", "val"):
        p = TILE_DIR / "annotations" / f"{split}.json"
        if not p.is_file():
            print(f"  ! 없다: {p}")
            continue
        d = json.loads(p.read_text())
        cur = {c["name"]: c["id"] for c in d["categories"]}
        print(f"\n  {p.name}   현재 {cur}")
        if cur == WANT:
            print("    이미 맞다 — 건너뛴다")
            continue
        missing = set(WANT) - set(cur)
        if missing:
            print(f"    ! 이름이 다르다: {sorted(missing)} — 손대지 않는다")
            continue

        remap = {cur[n]: WANT[n] for n in WANT}
        before = {}
        for an in d["annotations"]:
            before[an["category_id"]] = before.get(an["category_id"], 0) + 1
        for an in d["annotations"]:
            an["category_id"] = remap[an["category_id"]]
        d["categories"] = [{"id": i, "name": n}
                           for n, i in sorted(WANT.items(), key=lambda x: x[1])]
        after = {}
        for an in d["annotations"]:
            after[an["category_id"]] = after.get(an["category_id"], 0) + 1

        name_of = {v: k for k, v in WANT.items()}
        for old, new in sorted(remap.items()):
            print(f"    {old} -> {new}   {name_of[new]:14s} {before.get(old,0):,}건")
        # 뒤바뀜은 조용한 오류라 총량과 종류별 수를 검산한다
        if sum(before.values()) != sum(after.values()):
            sys.exit("    ! 병변 총수가 달라졌다 — 중단한다")
        for old, new in remap.items():
            if before.get(old, 0) != after.get(new, 0):
                sys.exit(f"    ! {old}->{new} 개수가 안 맞는다 — 중단한다")
        if go:
            shutil.copy2(p, Path(str(p) + ".bak"))
            p.write_text(json.dumps(d))
            print(f"    저장  (원본은 {p.name}.bak)")


# ── 2. 설정 생성 ─────────────────────────────────────────────────────────

def budget():
    """기준선과 같은 스텝 수가 되는 에폭 수를 구한다."""
    def n_img(p):
        return len(json.loads(Path(p).read_text())["images"])
    b = n_img(BASE_DIR / "annotations" / "train.json")
    t = n_img(TILE_DIR / "annotations" / "train.json")
    ep = int(OmegaConf.load(BASE_CFG).trainer.max_epochs)   # 정수라 안전하다
    steps = b * ep
    n = max(1, round(steps / t))
    print(f"\n  기준선   {ep}에폭 x {b:,}장 = {steps:,} 스텝")
    print(f"  타일     {n}에폭 x {t:,}장 = {n*t:,} 스텝  "
          f"({(n*t)/steps - 1:+.1%})")
    return n, t


def repath(txt):
    """절대경로만 옮긴다. 'detection' 같은 낱말은 건드리지 않는다."""
    b, t = str(BASE_DIR), str(TILE_DIR)
    # det_run -> det_tile_run  (det 치환보다 먼저)
    txt = txt.replace(f"{MAMMO}/det_run", f"{MAMMO}/det_tile_run")
    # /mammo/det 뒤에 글자나 밑줄이 오지 않을 때만 바꾼다
    txt = re.sub(re.escape(b) + r"(?![_A-Za-z0-9])", t, txt)
    # 타일은 검증 영상을 images/val 에 썼다 (기존은 images/test 였다)
    txt = txt.replace(f"{t}/images/test", f"{t}/images/val")
    return txt


def set_key(txt, key, val):
    """'  key: 숫자' 형태를 바꾼다. 주석이나 문자열은 안 건드린다."""
    pat = re.compile(rf"^(\s*){re.escape(key)}:[ \t]+(-?\d+)\s*$", re.M)
    hits = []

    def sub(m):
        if int(m.group(2)) != val:
            hits.append((key, m.group(2), val))
        return f"{m.group(1)}{key}: {val}"

    return pat.sub(sub, txt), hits


def make_cfg(go, save_freq, val_freq):
    print("\n" + "=" * 76)
    print("2. 타일 학습 설정")
    print("=" * 76)
    if not BASE_CFG.is_file():
        sys.exit(f"기준 설정이 없다: {BASE_CFG}")

    n_ep, _ = budget()
    src = BASE_CFG.read_text(encoding="utf-8")
    txt = repath(src)

    allhits = []
    for k, v in (("max_epochs", n_ep), ("max_data_epochs", n_ep),
                 ("save_freq", save_freq), ("val_epoch_freq", val_freq)):
        txt, h = set_key(txt, k, v)
        allhits += h

    print("\n  ── 바뀐 줄 ──")
    n_diff = 0
    for line in difflib.unified_diff(src.splitlines(), txt.splitlines(),
                                     lineterm="", n=0):
        if line.startswith(("---", "+++")):
            continue
        print(f"    {line}")
        n_diff += line.startswith(("+", "-"))
    if not n_diff:
        print("    없음 — 이미 바뀐 설정을 읽었거나 경로가 다르다")

    # ── 검산 ───────────────────────────────────────────────────────────
    print("\n  ── 확인 ──")
    bad = []
    if re.search(re.escape(str(BASE_DIR)) + r"(?![_A-Za-z0-9])", txt):
        bad.append("옛 데이터 경로가 남아 있다")
    if f"{MAMMO}/det_tile_run" not in txt:
        bad.append("실험 폴더가 안 바뀌었다")
    for need in (TILE_DIR / "images" / "train",
                 TILE_DIR / "images" / "val",
                 TILE_DIR / "annotations" / "train.json",
                 TILE_DIR / "annotations" / "val.json"):
        ok = need.exists()
        print(f"    {'있음' if ok else '없음':4s}  {need}")
        if not ok:
            bad.append(f"없다: {need}")
    # 설정에 적힌 입력 경로가 실제로 존재하는지 본다 — 오타를 여기서 잡는다.
    # 실험 폴더(det_tile_run)는 출력이라 학습이 만든다. 존재를 요구하면 안 된다.
    runroot = f"{MAMMO}/det_tile_run"
    for m in sorted(set(re.findall(rf"{re.escape(str(TILE_DIR))}\S*", txt))):
        q = m.rstrip("',\"")
        if "${" in q or q.startswith(runroot):
            continue
        ok = Path(q).exists()
        print(f"    {'있음' if ok else '없음':4s}  {q}")
        if not ok:
            bad.append(f"설정이 가리키는데 없다: {q}")
    # 출력 폴더는 만들 수 있는지만 본다
    par = Path(runroot).parent
    print(f"    {'쓰기가능' if par.is_dir() else '상위없음':8s}  {runroot} (출력)")
    if not par.is_dir():
        bad.append(f"실험 폴더를 만들 상위가 없다: {par}")
    if Path(runroot).exists():
        print(f"    ! 이미 있다 — 이전 실험이 있으면 덮어쓸 수 있다. 확인해라")
    if bad:
        for x in bad:
            print(f"    ! {x}")
        sys.exit("\n  중단한다 — 위 문제를 먼저 해결해라")

    try:
        OmegaConf.create(txt)          # 문법이 깨지지 않았는지만 본다
    except Exception as e:
        sys.exit(f"    ! YAML 이 깨졌다: {e}")
    print("    통과")

    if go:
        OUT_CFG.parent.mkdir(parents=True, exist_ok=True)
        OUT_CFG.write_text(txt, encoding="utf-8")
        print(f"\n  -> {OUT_CFG}  ({len(txt.splitlines())}줄)")
    return n_ep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save-freq", type=int, default=2,
                    help="체크포인트 저장 주기 (개당 9.4GB 다)")
    ap.add_argument("--val-freq", type=int, default=3)
    ap.add_argument("--go", action="store_true", help="실제로 쓴다")
    a = ap.parse_args()

    fix_cats(a.go)
    n = make_cfg(a.go, a.save_freq, a.val_freq)

    print("\n" + "=" * 76)
    if not a.go:
        print("확인만 했다. 문제 없으면 --go 로 실행해라.")
    else:
        print("준비 완료. 기준선 학습이 끝난 뒤에 시작해라.")
        print()
        print("  nohup python3 -u sam3/train/train.py \\")
        print("    -c configs/mammo/mammo_det_tile.yaml --use-cluster \\")
        print("    > det_tile_train.log 2>&1 &")
        print()
        print(f"  에폭 {n}개 · 배치 0.6초 기준 약 {n*7813*0.6/3600:.1f}시간")
        print()
        print("  ! 기준선(det_run)이 도는 동안 시작하면 GPU 를 나눠 쓰게 되어")
        print("    둘 다 느려지고 배치 시간이 달라져 비교가 흐려진다. 순서대로.")
    print("=" * 76)


if __name__ == "__main__":
    main()
