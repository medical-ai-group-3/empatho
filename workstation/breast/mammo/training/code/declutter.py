#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""작업 폴더에서 묵은 파일을 치운다 — **참조 확인을 먼저 한다.**

왜 지워도 되나
  전부 커밋했다. 작업 폴더에서 치워도 되돌릴 수 있다.

      git checkout -- docs/            # 통째로
      git checkout -- <파일>           # 한 개

  .bak* 만 예외다 — .gitignore 에 걸려 git 에 없다. 대신 그것들이
  보관하던 «고치기 전 상태»는 이제 커밋 이력이 대신한다.

무엇을 «살아 있는 참조»로 보나  — 3판에서 규칙을 하나로 정리했다

      지울 후보가 부르는 것은 참조가 아니다

  옛 패치가 "원본은 boundary.md.bak12" 라고 찍는다고 그 사본이 살아
  있는 것이 아니다. 그 패치 자체가 지울 대상이기 때문이다. 서로 붙들면
  아무것도 안 지워진다. 자기 자신도 당연히 안 센다.

  정리 도구(declutter · tidy · survey_disk)도 뺀다. 설명에 파일 이름을
  적어 뒀을 뿐 읽지는 않는다.

  그래서 «살아 있는 곳»은 = 코드·문서 전체 − 지울 후보 − 정리 도구.
  걸리면 어느 파일이 부르는지 이름까지 찍는다.

문서(--docs)는 이름을 글자 그대로 적어 남긴다
  KEEP_DOCS 에 적힌 것만 남고 나머지 .md 는 후보가 된다. 계약서가
  실수로 날아가지 않도록 «지울 목록»이 아니라 «남길 목록»으로 적었다.

묶음
  --baks       *.bak* 사본
  --patches    patch_*.py            이미 적용됐다
  --dumps      docs 의 측정 찌꺼기
  --logs       queue · train 로그
  --strays     뿌리에 흩어진 스크립트
  --docs       지나간 기록 문서       계약·근거 문서는 남는다

사용
  python3 training/code/declutter.py --all-list
  python3 training/code/declutter.py --baks --patches --logs --strays
  python3 training/code/declutter.py --baks --patches --logs --strays --go
"""

import argparse
from pathlib import Path

ROOT = Path.home() / "workspace/breast/mammo"

LIVE_GLOBS = ["training/code/*.py", "training/code/*.sh",
              "training/*.py", "*.py", "*.sh",
              "docs/*.md", "training/*.md", "*.md",
              "training/configs/*.yaml"]

# 정리 도구. 파일 이름을 «설명»으로 적을 뿐 읽지 않는다.
TOOLS = {"declutter.py", "tidy.py", "survey_disk.py"}

NEVER = {"crop_rule.json", "latest.log"}

# ── 남길 문서 — 지금 살아 있는 계약·근거 ──────────────────────────
#    여기 없는 .md 는 --docs 에서 후보가 된다.
KEEP_DOCS = {
    "README.md",                    # 어느 폴더의 것이든
    "mammo_api.md",                 # 응답 계약. detail 키 목록의 원본
    "boundary.md",                  # 경계와 결정
    "evidence_text.md",             # 판독문 문안 규칙
    "screening_limit.md",           # 정상 유방과 한계
    "serving_capacity.md",          # 판독 속도·용량
    "results_for_presentation.md",  # 발표 근거
    "mobile_spec.md",               # 앱 화면
}


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:,.0f}{u}" if u == "B" else f"{n:,.1f}{u}"
        n /= 1024


def link_targets():
    keep = set()
    for p in ROOT.rglob("*"):
        if p.is_symlink():
            keep.add(p)
            try:
                keep.add(p.resolve())
            except OSError:
                pass
    return keep


def collect():
    g = {}
    g["baks"] = ("*.bak* 사본",
                 sorted(p for p in ROOT.rglob("*")
                        if p.is_file() and not p.is_symlink()
                        and ".bak" in p.name and ".git/" not in str(p)))
    g["patches"] = ("이미 적용된 patch_*.py",
                    sorted(p for p in (ROOT / "training/code").glob("patch_*.py")
                           if p.name not in TOOLS))
    dumps = []
    for pat in ("docs/*.txt", "docs/*.json"):
        dumps += [p for p in ROOT.glob(pat) if p.is_file()]
    g["dumps"] = ("docs 의 측정 찌꺼기", sorted(dumps))

    logs = [p for p in ROOT.glob("docs/*.log") if p.is_file()]
    for d in ("training/logs", "training12/logs"):
        logs += [p for p in (ROOT / d).glob("*.log")
                 if p.is_file() and not p.is_symlink()]
    g["logs"] = ("queue · train 로그", sorted(logs))

    g["strays"] = ("뿌리에 흩어진 스크립트",
                   sorted(p for p in ROOT.glob("*.py")
                          if p.is_file() and p.name not in TOOLS))

    mds = []
    for pat in ("docs/*.md", "training/*.md", "*.md"):
        mds += [p for p in ROOT.glob(pat)
                if p.is_file() and p.name not in KEEP_DOCS]
    g["docs"] = ("지나간 기록 문서 (계약·근거는 제외했다)", sorted(set(mds)))
    return g


def load_live(cands):
    """살아 있는 곳 = 코드·문서 − 지울 후보 − 정리 도구."""
    out = {}
    for gl in LIVE_GLOBS:
        for p in ROOT.glob(gl):
            if not p.is_file() or p.is_symlink():
                continue
            if p in cands or p.name in TOOLS or ".bak" in p.name:
                continue
            try:
                out[p] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    groups = collect()
    for k in groups:
        ap.add_argument(f"--{k}", action="store_true")
    ap.add_argument("--all-list", action="store_true")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    picked = [k for k in groups if getattr(a, k)]

    print("=" * 78)
    print("작업 폴더 정리" + ("   [지운다]" if a.go and picked else "   [보기만 한다]"))
    print("=" * 78)

    cands = {p for _t, fs in groups.values() for p in fs}
    live = load_live(cands)
    protected = link_targets()
    print(f"\n  지울 후보 {len(cands)}개를 뺀 «살아 있는 곳» {len(live)}개에서"
          f" 이름을 찾는다.")
    print(f"  심볼릭 링크와 그 대상 {len(protected)}개는 후보에서 뺀다.")

    todo, grand = [], 0
    for key, (title, files) in groups.items():
        on = key in picked
        keep, drop = [], []
        for p in files:
            why = None
            if p.name in NEVER:
                why = "이름으로 보호"
            elif p in protected:
                why = "링크 대상"
            else:
                for lp, text in live.items():
                    if p.name in text:
                        why = f"{lp.name} 가 부른다"
                        break
            (keep if why else drop).append((p, why))

        sz = sum(p.stat().st_size for p, _ in drop)
        print(f"\n■ {title}   [--{key}]" + ("   ← 켜짐" if on else ""))
        print(f"  전체 {len(files)}개 · 남길 것 {len(keep)}개 · "
              f"지울 후보 {len(drop)}개 ({human(sz)})")
        for p, why in keep:
            print(f"    남김   {p.relative_to(ROOT)}   ← {why}")
        show = drop if (a.all_list or len(drop) <= 12) else drop[:10]
        for p, _ in show:
            print(f"    지움   {p.relative_to(ROOT)}")
        if len(show) < len(drop):
            print(f"    …      그 밖에 {len(drop)-len(show)}개 "
                  f"(--all-list 로 전부 본다)")
        if on:
            todo += [p for p, _ in drop]
            grand += sz

    if not picked:
        print("\n  아무 묶음도 안 켰다. 예:")
        print("    python3 training/code/declutter.py --baks --patches")
        return

    print(f"\n  켠 묶음에서 지울 것 {len(todo)}개 · {human(grand)}")
    if not a.go:
        print("  --go 를 줘야 실제로 지운다. 지금은 보기만 했다.")
        return

    n = 0
    for p in todo:
        try:
            p.unlink()
            n += 1
        except Exception as e:
            print(f"  실패 {p} — {e}")
    print(f"\n  {n}개 지웠다.")
    print("""
  확인

    cd ~/workspace/breast/mammo
    git status --short | wc -l
    ls docs/ | head -30
    ls training/code/ | head -40

  «D» 는 git 안에 그대로 있다는 뜻이다. 되돌리려면

    git checkout -- docs/

  치운 상태를 확정하려면

    git add -A && git commit -m "정리: 적용된 패치·측정 찌꺼기·로그·기록 문서"
""")


if __name__ == "__main__":
    main()
