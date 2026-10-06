#!/usr/bin/env python
"""
맘모 파일을 ~/workspace/breast/mammo 로 모은다.

왜 링크를 쓰는가
  train_mammo.py 는 백본을 상대 경로로 찾는다.

      from merge_medsam3 import load_merged_model   # 같은 폴더
      from lora_layers import LoRALinear            # 같은 폴더
      CKPT = "ckpt/medsam3_merged.pt"               # 실행 위치 기준

  스크립트만 옮기면 백본을 못 찾아 죽는다. 그렇다고 sam3(19M)와 병합본(3.4G)을
  복사하면 사본이 둘이 되어 더 나쁘다. 그래서 코드는 진짜로 옮기고 백본 쪽은
  링크만 건다. 실체는 MedSAM3 에 하나만 남는다.

  라벨과 인덱스 경로는 이미 절대경로(Path.home()/...)라 손댈 필요가 없다.

안전장치
  · 기본은 계획 출력만. 실제로 옮기려면 --go
  · 목적지에 파일이 이미 있으면 건너뛴다 (덮어쓰지 않는다)
  · 다른 파트 폴더(data · train · us · labels)는 절대 건드리지 않는다
  · 삭제는 --clean 을 따로 줘야 하고, 명시한 목록만 지운다

사용
  python3 organize_mammo.py              계획만 본다
  python3 organize_mammo.py --go         옮기고 링크를 건다
  python3 organize_mammo.py --clean      삭제 후보를 보여준다
  python3 organize_mammo.py --clean --go 실제로 지운다
"""

import argparse, os, shutil, sys
from pathlib import Path

HOME = Path.home()
SRC = HOME / "workspace/MedSAM3"
DST = HOME / "workspace/breast/mammo"
RULES_SRC = HOME / "workspace/breast/code"

# 다른 파트가 쓰는 곳. 어떤 경우에도 건드리지 않는다.
FORBIDDEN = [HOME / "workspace/breast/data",
             HOME / "workspace/breast/train",
             HOME / "workspace/breast/us",
             HOME / "workspace/breast/labels"]

# ── 옮길 것: 맘모 전용 코드 ────────────────────────────────────
MOVE_CODE = [
    "train_mammo.py", "train_joint.py", "mammo_data.py", "eval_e2e.py",
    "build_roi_index.py", "check_preproc.py", "summarize_ckpts.py",
    "variance_check.py", "vindr_urls.py",
    "probe_vb.py", "probe_vindr.py", "probe_backbone.py",
    "check_roi.py", "inspect_lora.py", "check_descriptors.py",
    "normalize_labels.py",
]

# ── 옮길 것: 규칙표 (--with-rules 일 때만) ─────────────────────
MOVE_RULES = ["validate_rules.py", "tune_rules.py", "crosscheck_vindr.py"]

# ── 링크할 것: 백본 인프라. 실체는 MedSAM3 에 남는다 ───────────
LINK = ["merge_medsam3.py", "lora_layers.py", "sam3", "ckpt", "configs"]

# ── 삭제 후보 (--clean) ───────────────────────────────────────
#   전부 '기각된 실험의 산출물' 이거나 '재생성 가능한 중간물' 이다.
CLEAN = [
    (SRC / "ckpt/feat", "*grid6*", "격자 6x6 기각 — 재생성 6분"),
    (SRC / "ckpt", "*_head_pw100.pt", "pos_weight 기각 — 재생성 12초"),
    (SRC, "__pycache__", "파이썬 캐시 — 자동 재생성"),
    (DST, "__pycache__", "파이썬 캐시 — 자동 재생성"),
    (RULES_SRC, "*.bak", "구버전 백업"),
]


def guard(p: Path):
    """다른 파트 폴더 안이면 즉시 중단한다."""
    rp = p.resolve()
    for f in FORBIDDEN:
        try:
            rp.relative_to(f.resolve())
        except ValueError:
            continue
        sys.exit(f"중단: {p} 는 다른 파트 폴더({f.name}) 안이다. 건드리지 않는다.")


def human(n):
    for u in ("B", "K", "M", "G"):
        if n < 1024 or u == "G":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024


def size_of(p: Path):
    if p.is_symlink() or p.is_file():
        return p.stat().st_size if p.exists() else 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def do_move(names, src, dst, go, label):
    print(f"\n■ 이동 — {label}")
    n_ok = n_skip = 0
    for name in names:
        s, d = src / name, dst / name
        if not s.exists():
            continue
        guard(s)
        if d.exists():
            print(f"    건너뜀  {name:26s} (목적지에 이미 있다)")
            n_skip += 1
            continue
        print(f"    {'옮김' if go else '옮길 것'}  {name:26s} {human(size_of(s)):>8s}")
        if go:
            shutil.move(str(s), str(d))
        n_ok += 1
    if n_ok == 0 and n_skip == 0:
        print("    해당 없음")
    return n_ok


def do_link(go):
    print(f"\n■ 링크 — 백본 인프라 (실체는 MedSAM3 에 남는다)")
    for name in LINK:
        s, d = SRC / name, DST / name
        if not s.exists():
            print(f"    ! 없음   {name}  — MedSAM3 에 있어야 한다")
            continue
        if d.exists() or d.is_symlink():
            tgt = os.readlink(d) if d.is_symlink() else "(실파일)"
            print(f"    건너뜀  {name:20s} 이미 있다 -> {tgt}")
            continue
        print(f"    {'링크' if go else '링크할 것'}  {name:20s} -> {s}")
        if go:
            d.symlink_to(s)


def do_clean(go):
    print("\n" + "=" * 74)
    print("삭제 후보")
    print("=" * 74)
    total, targets = 0, []
    for base, pat, why in CLEAN:
        if not base.exists():
            continue
        for p in sorted(base.glob(pat)):
            guard(p)
            if p.is_symlink():          # 링크는 건너뛴다. 실체를 지울 위험이 있다
                print(f"    건너뜀(링크)  {p}")
                continue
            sz = size_of(p)
            total += sz
            targets.append(p)
            print(f"    {human(sz):>8s}  {p.relative_to(HOME)}")
            print(f"    {'':8s}  └ {why}")
    if not targets:
        print("    없음 — 이미 정리되어 있다")
        return
    print(f"\n    합계 {human(total)}  ·  {len(targets)}개")
    if not go:
        print("\n    실제로 지우려면 --clean --go")
        return
    for p in targets:
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    print(f"\n    삭제 완료 {human(total)}")


def verify():
    """옮긴 뒤 실제로 돌아갈 수 있는 상태인지 확인한다."""
    print("\n" + "=" * 74)
    print("검증 — breast/mammo 에서 실행 가능한가")
    print("=" * 74)
    need = [("train_mammo.py", "학습 본체"),
            ("mammo_data.py", "데이터셋"),
            ("merge_medsam3.py", "백본 로더 (링크)"),
            ("lora_layers.py", "LoRA 층 (링크)"),
            ("sam3", "SAM3 구현 (링크)"),
            ("ckpt/medsam3_merged.pt", "병합 백본 (링크 경유)"),
            ("configs/medsam3_v1.yaml", "LoRA 구조 (링크 경유)")]
    ok = True
    for name, why in need:
        p = DST / name
        mark = "OK " if p.exists() else "없음"
        if not p.exists():
            ok = False
        print(f"    [{mark}] {name:28s} {why}")
    lab = HOME / "workspace/breast/labels/labels/label_schema.json"
    idx = HOME / "workspace/breast/labels/index"
    print(f"    [{'OK ' if lab.exists() else '없음'}] {'label_schema.json':28s} 절대경로 — 이동 무관")
    print(f"    [{'OK ' if idx.exists() else '없음'}] {'labels/index/':28s} 절대경로 — 이동 무관")
    print()
    if ok:
        print("    전부 갖춰졌다. 이제 이렇게 돌린다:")
        print(f"      cd {DST}")
        print("      python3 -u eval_e2e.py --ckpt ckpt/mammo_calc_..._lora.pt")
    else:
        print("    ! 빠진 것이 있다. MedSAM3 쪽을 확인해라.")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="실제로 실행한다")
    ap.add_argument("--clean", action="store_true", help="삭제 후보를 다룬다")
    ap.add_argument("--with-rules", action="store_true",
                    help="breast/code 의 규칙표 파일도 옮긴다. "
                         "다른 파트가 참조하면 옮기지 마라")
    a = ap.parse_args()

    print("=" * 74)
    print(f"맘모 파일 정리   {'실행' if a.go else '계획만 (실행하려면 --go)'}")
    print("=" * 74)
    print(f"  원본  {SRC}")
    print(f"  대상  {DST}")
    print(f"  보호  {', '.join(f.name for f in FORBIDDEN)} — 건드리지 않는다")

    if a.clean:
        do_clean(a.go)
        return

    if not DST.exists():
        print(f"\n■ 폴더 생성  {DST}")
        if a.go:
            DST.mkdir(parents=True)
            (DST / "logs").mkdir(exist_ok=True)

    do_move(MOVE_CODE, SRC, DST, a.go, "맘모 전용 코드")

    if a.with_rules:
        do_move(MOVE_RULES, RULES_SRC, DST, a.go, "규칙표 (breast/code 에서)")
        if a.go:
            print("    ★ tune_rules.py 와 crosscheck_vindr.py 의 기본 경로가")
            print("      ~/workspace/breast/code/validate_rules.py 를 가리킨다.")
            print("      옮겼으면 --rules 로 새 경로를 주거나 코드를 고쳐라.")
    else:
        print("\n■ 규칙표 — 옮기지 않음")
        for n in MOVE_RULES:
            p = RULES_SRC / n
            if p.exists():
                print(f"    남김  {n:24s} {RULES_SRC}")
        print("    다른 파트가 참조하지 않는 것이 확실하면 --with-rules")

    # 로그
    logs = sorted(SRC.glob("*.log")) + sorted((SRC / "logs").glob("*.log"))
    if logs:
        print(f"\n■ 로그 {len(logs)}개 -> breast/mammo/logs/")
        if a.go:
            (DST / "logs").mkdir(parents=True, exist_ok=True)
            for p in logs:
                d = DST / "logs" / p.name
                if not d.exists():
                    shutil.move(str(p), str(d))
            print(f"    옮김 {len(logs)}개")
        else:
            print(f"    {', '.join(p.name for p in logs[:6])}"
                  + (" ..." if len(logs) > 6 else ""))
            print("    ★ A~D.log 와 alpha_sweep.log 는 발표 근거다. 지우지 마라")

    do_link(a.go)

    if a.go:
        verify()
    else:
        print("\n" + "=" * 74)
        print("이대로 진행하려면:  python3 organize_mammo.py --go")
        print("그 다음 삭제 후보:  python3 organize_mammo.py --clean")
        print("=" * 74)


if __name__ == "__main__":
    main()
