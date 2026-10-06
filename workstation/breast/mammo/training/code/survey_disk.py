#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""무엇이 자리를 차지하는지 훑는다. **아무것도 지우지 않는다.**

왜 훑기부터 하나
  이 저장소는 원격이 없다. 지운 것은 못 되돌린다. 그리고 medsam3/ 아래
  심볼릭 링크를 잘못 건드리면 3.4GB 짜리 베이스 가중치가 날아간다.

  그래서 이 스크립트는 **읽기만 한다.** 지우는 것은 목록을 보고 따로 정한다.

절대 건드리지 않는 것 — 이 스크립트도, 나중에 지울 때도
  medsam3/ 아래 심볼릭 링크   ckpt · configs · sam3 · lora_layers.py
                              merge_medsam3.py
                              → 링크를 지우면 원본이 날아간다
  training/ckpt/last_lora.pt  **서빙이 쓰는 검출기다**
  서술어 체크포인트 둘         calc · mass
  ~/workspace/breast/train    MRI — 다른 팀
  ~/workspace/breast/us       초음파 — 다른 팀

사용
  python3 training/code/survey_disk.py
  python3 training/code/survey_disk.py --top 40
"""

import argparse
import os
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / "workspace/breast/mammo"
VINDR = Path.home() / "workspace/breast/data/vindr"

# 서빙과 재현에 필요한 것. 후보에서 무조건 뺀다.
KEEP_NAMES = {"last_lora.pt"}
KEEP_HINTS = ("_lora.pt",)          # 서술어 체크포인트


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:,.0f}{u}" if u == "B" else f"{n:,.1f}{u}"
        n /= 1024


def classify(p: Path, rel: str):
    name = p.name
    if ".bak" in name:
        return "백업 (.bak*)"
    if "__pycache__" in rel or name.endswith(".pyc"):
        return "파이썬 캐시"
    if rel.startswith("training/ckpt"):
        return "체크포인트"
    if rel.startswith("archive/outputs"):
        return "출력물 (archive/outputs)"
    if rel.startswith("archive"):
        return "기타 archive"
    if rel.startswith("docs"):
        return "문서"
    if rel.startswith("training/code"):
        return "코드"
    if name.startswith("patch_") and name.endswith(".py"):
        return "코드"
    if rel.startswith(".git/"):
        return "git 내부"
    return "기타"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    if not ROOT.is_dir():
        raise SystemExit(f"[중단] 없는 폴더: {ROOT}")

    print("=" * 78)
    print(f"자리 차지 현황 — {ROOT}")
    print("**아무것도 지우지 않는다. 보기만 한다.**")
    print("=" * 78)

    # ── 디스크 여유 ────────────────────────────────────────────────
    print("\n■ 디스크")
    try:
        out = subprocess.run(["df", "-h", str(ROOT)], capture_output=True,
                             text=True, timeout=20).stdout.strip()
        for line in out.splitlines():
            print("  " + line)
    except Exception as e:
        print(f"  못 읽었다: {e}")

    # ── 훑기 ───────────────────────────────────────────────────────
    files = []
    links = []
    for dirpath, dirnames, filenames in os.walk(ROOT, followlinks=False):
        d = Path(dirpath)
        # 심볼릭 링크로 된 폴더는 들어가지 않는다 — 남의 원본이다
        dirnames[:] = [x for x in dirnames if not (d / x).is_symlink()]
        for x in dirnames:
            if (d / x).is_symlink():
                links.append(d / x)
        for fn in filenames:
            p = d / fn
            if p.is_symlink():
                links.append(p)
                continue
            try:
                sz = p.stat().st_size
            except OSError:
                continue
            files.append((sz, p))

    # walk 가 건너뛴 링크는 위에서 못 잡으니 한 번 더 본다
    for p in ROOT.rglob("*"):
        if p.is_symlink() and p not in links:
            links.append(p)

    total = sum(s for s, _ in files)
    print(f"\n■ 합계   파일 {len(files):,}개 · {human(total)}")

    # ── 분류별 ─────────────────────────────────────────────────────
    cat = defaultdict(lambda: [0, 0])
    for sz, p in files:
        rel = str(p.relative_to(ROOT))
        c = classify(p, rel)
        cat[c][0] += sz
        cat[c][1] += 1
    print("\n■ 분류별")
    for c, (sz, n) in sorted(cat.items(), key=lambda kv: -kv[1][0]):
        print(f"  {human(sz):>10}  {n:>6,}개  {c}")

    # ── 큰 파일 ────────────────────────────────────────────────────
    print(f"\n■ 큰 파일 {a.top}개")
    for sz, p in sorted(files, key=lambda t: -t[0])[:a.top]:
        rel = str(p.relative_to(ROOT))
        keep = p.name in KEEP_NAMES or any(h in p.name for h in KEEP_HINTS)
        mark = "  ← 보존" if keep else ""
        print(f"  {human(sz):>10}  {rel}{mark}")

    # ── 심볼릭 링크 ────────────────────────────────────────────────
    print(f"\n■ 심볼릭 링크 {len(links)}개 — **하나도 지우지 말 것**")
    for p in sorted(set(links)):
        try:
            tgt = os.readlink(p)
        except OSError:
            tgt = "?"
        alive = "" if p.exists() else "   ⚠ 대상 없음"
        print(f"  {p.relative_to(ROOT)}  ->  {tgt}{alive}")

    # ── 지워도 될 법한 것 (합계만) ─────────────────────────────────
    print("\n■ 지울 후보 — **합계만 낸다. 지우지 않는다**")
    cand = defaultdict(lambda: [0, 0])
    for sz, p in files:
        rel = str(p.relative_to(ROOT))
        if rel.startswith(".git/"):
            continue
        if p.name in KEEP_NAMES or any(h in p.name for h in KEEP_HINTS):
            continue
        if ".bak" in p.name:
            cand["백업 (.bak*)"][0] += sz
            cand["백업 (.bak*)"][1] += 1
        elif "__pycache__" in rel or p.name.endswith(".pyc"):
            cand["파이썬 캐시"][0] += sz
            cand["파이썬 캐시"][1] += 1
    for c, (sz, n) in sorted(cand.items(), key=lambda kv: -kv[1][0]):
        print(f"  {human(sz):>10}  {n:>6,}개  {c}")
    if not cand:
        print("  없다")

    # ── git ────────────────────────────────────────────────────────
    print("\n■ git — 커밋 안 된 것이 있으면 .bak 을 지우면 안 된다")
    try:
        st = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=30)
        if st.returncode != 0:
            print("  git 저장소가 아니거나 못 읽었다")
        else:
            lines = [l for l in st.stdout.splitlines() if l.strip()]
            mod = [l for l in lines if not l.startswith("??")]
            unt = [l for l in lines if l.startswith("??")]
            print(f"  고쳤는데 커밋 안 한 것 {len(mod)}개 · "
                  f"추적 안 되는 것 {len(unt)}개")
            for l in mod[:15]:
                print("    " + l)
            if len(mod) > 15:
                print(f"    … 그 밖에 {len(mod)-15}개")
    except Exception as e:
        print(f"  못 읽었다: {e}")

    # ── VinDr 정상 영상 ────────────────────────────────────────────
    print("\n■ VinDr (맘모 팀 것) — 크기만 본다")
    if VINDR.is_dir():
        try:
            out = subprocess.run(["du", "-sh", str(VINDR)], capture_output=True,
                                 text=True, timeout=120).stdout.strip()
            print("  " + (out or "?"))
            for sub in sorted(p for p in VINDR.iterdir() if p.is_dir()):
                o = subprocess.run(["du", "-sh", str(sub)], capture_output=True,
                                   text=True, timeout=120).stdout.strip()
                print("    " + (o or "?"))
        except Exception as e:
            print(f"  못 읽었다: {e}")
    else:
        print("  없다")

    print("""
======================================================================
  여기까지가 현황이다. **아무것도 안 지웠다.**
  목록을 보고 무엇을 지울지 정한 다음에 지운다.
======================================================================""")


if __name__ == "__main__":
    main()
