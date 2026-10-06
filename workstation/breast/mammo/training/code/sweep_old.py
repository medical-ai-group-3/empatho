#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""안 쓰는 것들을 골라 낸다 — 기본은 «보여주기만» 이다.

지우는 것은 되돌릴 수 없다. 그래서 이 스크립트는
  ① 갈래를 나눠 보여주고
  ② 갈래를 **명시적으로 고를 때만** 지우고
  ③ 지키기로 한 것은 갈래를 골라도 안 건드린다.

절대 안 건드리는 것 — 골라도 안 지운다
    medsam3/ 아래 전부          심볼릭 링크가 3.4GB 백본을 가리킨다
    *.pt · *.pth · *.tar        가중치
    ~/workspace/breast/train    MRI 팀
    ~/workspace/breast/us       초음파 팀
    ~/workspace/breast/data     공용
    mammo 저장소 바깥 전부
    아래 KEEP 목록              확정 운영점과 그 재료

갈래
    --logs       큐 · 채점 로그 (docs/*.log)
    --bakdata    검출 파일 백업 (*.json.bak) — **원본이 살아 있는 것만**
    --bakcode    코드 · 문서 백업 (*.py.bak · *.md.bak) — 진짜 안전망
    --detsweep   버려진 후처리 실험 검출 파일
    --images     docs · archive 에 남은 옛 그림 (docs/examples 는 제외)
    --pyc        __pycache__

  백업을 둘로 나눈 이유
    오늘 stamp_frame 이 검출 파일 53개에 키를 «더하기만» 했고 채점이
    그대로인 것을 확인했다. 그 .bak 은 살아 있는 파일에서 키 몇 개를 뺀
    것이라 **잃는 정보가 없다**(399MB 중 대부분).

    반면 코드·문서 백업은 되돌릴 유일한 길이고 크기도 작다. 따로 둔다.

  ⚠ 살아 있는 원본이 없는 .bak 은 갈래를 골라도 안 지운다 — 그게 마지막
    사본일 수 있다.

사용
  python3 training/code/sweep_old.py                       # 다 보여주기만
  python3 training/code/sweep_old.py --logs --pyc --apply  # 고른 갈래만
"""

import argparse
import os
import re
import sys
from pathlib import Path

HOME = Path.home()
REPO = HOME / "workspace/breast/mammo"

# 다른 팀 · 백본 — 갈래를 골라도 손대지 않는다
FORBID = [HOME / "workspace/breast/train",
          HOME / "workspace/breast/us",
          HOME / "workspace/breast/data",
          REPO / "medsam3"]

# 확정 운영점과 그 재료 — 지우면 발표 수치를 다시 못 만든다
KEEP = {
    "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json",   # 확정 운영점
    "tile_dets_wbf03_tissue.json",                             # 후처리 이전
    "tile_dets_train600.json",                                 # 어려운 음성 재료
}
KEEP_RE = [
    re.compile(r"vindr", re.I),          # 외부 검증
    re.compile(r"_val\.json$"),          # 검증 split
]

# ⚠ pw 는 «숫자» 로 끝나는 것만 잡는다. \w* 로 두면 t30_pwmix_... 까지
#   먹어서 **확정 운영점 파일을 지운다.** KEEP 이 막아 주긴 하지만
#   한 겹에 기대면 안 된다.
SWEEP_RE = re.compile(
    r"tile_dets_wbf03_tissue_"
    r"(t\d+(norm)?|norm"
    r"|t30_(pg|pw|xd)\d+"
    r"|t30_(xgate|xratio)"
    r"|t30_pwmix_calc015_mass035_(bin|tv|cut)\w*)\.json$")


def size(p):
    try:
        return p.stat().st_size
    except OSError:
        return 0


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:,.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def protected(p):
    try:
        rp = p.resolve()
    except OSError:
        return True
    if p.is_symlink():
        return True
    if p.suffix in (".pt", ".pth", ".tar"):
        return True
    for f in FORBID:
        try:
            if rp == f.resolve() or f.resolve() in rp.parents:
                return True
        except OSError:
            pass
    try:
        REPO.resolve() in rp.parents or rp == REPO.resolve()
    except OSError:
        return True
    if REPO.resolve() not in rp.parents:
        return True
    if p.name in KEEP or any(r.search(p.name) for r in KEEP_RE):
        return True
    return False


def gather():
    out = {"logs": [], "bakdata": [], "bakcode": [], "detsweep": [],
           "images": [], "pyc": []}
    docs, arch = REPO / "docs", REPO / "archive" / "outputs"

    if docs.is_dir():
        for p in docs.glob("*.log"):
            out["logs"].append(p)
    for base in (REPO / "training" / "code", docs, arch):
        if base.is_dir():
            for p in base.rglob("*"):
                if not (p.is_file() and ".bak" in p.name):
                    continue
                live = Path(str(p).split(".bak")[0])
                if not live.is_file():
                    continue          # 살아 있는 원본이 없다 — 마지막 사본일 수 있다
                (out["bakdata"] if live.suffix == ".json"
                 else out["bakcode"]).append(p)
    if arch.is_dir():
        for p in arch.glob("*.json"):
            if SWEEP_RE.search(p.name):
                out["detsweep"].append(p)
    # 옛 그림 — 지금 쓰는 docs/examples 는 뺀다 (pick_examples 가 관리한다)
    keep_dir = (REPO / "docs" / "examples").resolve()
    for base in (docs, arch):
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix.lower() not in (".png", ".jpg", ".jpeg"):
                continue
            try:
                if keep_dir == p.parent.resolve():
                    continue
            except OSError:
                continue
            out["images"].append(p)
    for p in REPO.rglob("__pycache__"):
        if p.is_dir() and "medsam3" not in str(p):
            out["pyc"] += [q for q in p.rglob("*") if q.is_file()]
    return {k: sorted(set(v)) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    for k in ("logs", "bakdata", "bakcode", "detsweep", "images", "pyc"):
        ap.add_argument(f"--{k}", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", action="store_true", help="파일 이름도 전부")
    a = ap.parse_args()

    if not REPO.is_dir():
        sys.exit(f"[중단] 저장소가 없다: {REPO}")

    print("=" * 80)
    print(f"안 쓰는 것 골라 내기 — {REPO}")
    print("=" * 80)

    found = gather()
    chosen = [k for k in found if getattr(a, k)]

    print(f"\n  {'갈래':<12}{'파일':>8}{'크기':>12}   설명")
    tips = {"logs": "큐 · 채점 로그",
            "bakdata": "검출 파일 백업 — 원본이 살아 있다. 지워도 안전",
            "bakcode": "코드 · 문서 백업 — **되돌릴 유일한 길**",
            "detsweep": "버려진 후처리 실험 검출 파일",
            "images": "옛 그림 — 지금 쓰는 docs/examples 는 뺐다",
            "pyc": "__pycache__"}
    total = 0
    for k, ps in found.items():
        ok = [p for p in ps if not protected(p)]
        n = sum(size(p) for p in ok)
        if getattr(a, k):
            total += n
        mark = " ←고름" if getattr(a, k) else ""
        print(f"  {k:<12}{len(ok):>8,}{human(n):>12}   {tips[k]}{mark}")
        if a.list and ok:
            for p in ok[:200]:
                print(f"      {p.relative_to(REPO)}  {human(size(p))}")
            if len(ok) > 200:
                print(f"      … {len(ok)-200}개 더")

    kept = sum(1 for ps in found.values() for p in ps if protected(p))
    print(f"\n  지키기로 해서 목록에서 뺀 것 {kept}개 "
          "(가중치 · 심볼릭 링크 · 확정 운영점 · 다른 팀)")

    if not chosen:
        print("""
  갈래를 하나도 안 골랐다. 아무것도 안 지운다.

  이름을 다 보려면   --list
  지우려면           갈래를 고르고 --apply

    python3 training/code/sweep_old.py --pyc --logs --bakdata --apply

  ⚠ --bakcode 는 지금 지우지 말 것. infer_mammo · mammo_api ·
    results_for_presentation 을 오늘 고쳤고 그 .bak 이 되돌릴 유일한
    길이다. 크기도 작으니 며칠 지나 확실해진 뒤에.

  ⚠ --detsweep 은 버려진 실험 파일이라 지워도 되지만, 그 파일로 낸 수치가
    docs/score_dets*.json 에 남아 있는지 먼저 확인할 것. 남아 있으면
    파일이 없어도 발표 수치를 설명할 수 있다.""")
        return

    print(f"\n  고른 갈래 {chosen} · 합계 {human(total)}")
    if not a.apply:
        print("  --apply 를 줘야 실제로 지운다. 지금은 보여주기만 했다.")
        return

    gone, freed = 0, 0
    for k in chosen:
        for p in found[k]:
            if protected(p):
                continue
            s = size(p)
            try:
                os.remove(p)
                gone += 1
                freed += s
            except OSError as e:
                print(f"  ! 못 지움 {p.name}: {e}")
    print(f"\n  지웠다 — 파일 {gone:,}개 · {human(freed)}")


if __name__ == "__main__":
    main()
