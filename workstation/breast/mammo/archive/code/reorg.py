#!/usr/bin/env python
"""
맘모 파트를 초음파 파트와 같은 구조로 재배치한다 — 옮기기만 하고 지우지 않는다.

맞출 대상 (초음파 실제 구조)
  us/
    docs/       experiments.md · results_for_presentation.md
    training/   README.md · code/ · configs/ · ckpt/
    serving/    README.md · code/ · configs/ · ckpt/ · healthcheck.py
    archive/

맘모 목표
  mammo/
    medsam3/     MedSAM3 연결 (심볼릭 링크 5개)
    docs/        보고서 · 일지 · 기획서 정정
    training/    code/ · configs/ · ckpt/ · logs/
    data/        det · det_tile · det_tile1008
    runs/        det_run (기준선 · 전체 미세조정)
    archive/     code/ · logs/ · outputs/   끝난 갈래

왜 medsam3/ 를 따로 두나
  지금 mammo/configs 와 mammo/ckpt 는 MedSAM3 를 가리키는 링크다.
  초음파에서는 같은 이름이 '학습 설정' 과 '학습 결과' 를 뜻한다.
  이름이 같고 뜻이 다르면 통합이 아니다. 연결을 medsam3/ 안으로 밀어 넣어
  두 이름을 초음파와 같은 뜻으로 비운다.

  링크 다섯 개가 전부 절대경로라 하위 폴더로 옮겨도 가리키는 곳이 안 바뀐다.
  (상대경로였으면 옮기는 순간 끊어진다 — 확인하고 진행한다)

안 하는 것
  아무것도 지우지 않는다. 분류가 애매한 파일은 archive 가 아니라
  training/code 로 보낸다 — 잘못 묻어두는 것보다 낫다.
  목록에 없는 파일은 옮기지 않고 이름만 알려준다.

사용
  python3 reorg.py              # 무엇이 어디로 갈지만
  python3 reorg.py --go
  python3 reorg.py --verify     # 옮긴 뒤 링크와 import 확인
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
MAMMO = HOME / "workspace/breast/mammo"

LINKS = ["ckpt", "configs", "sam3", "lora_layers.py", "merge_medsam3.py"]

DIRS = ["medsam3", "docs", "training/code", "training/configs", "training/ckpt",
        "training/logs", "data", "runs", "archive/code", "archive/logs",
        "archive/outputs"]

# 지금 파이프라인에서 쓰는 것
ACTIVE = [
    # 검출 — 통합 구조
    "train_mammo_det.py", "probe_unified.py",
    "eval_det.py", "eval_det_tiled.py", "eval_map.py",
    "make_tiles.py", "verify_tiles.py",
    # 서술어 — 현행 산출물
    "train_mammo.py", "train_joint.py", "eval_e2e.py",
    "validate_rules.py", "tune_rules.py", "ceiling.py",
    "mammo_data.py", "build_roi_index.py", "report_gen.py",
    # 운영
    "cleanup.py", "chain.sh",
]

# 결론이 난 갈래 — 기록은 남기되 현행 코드와 섞지 않는다
ARCHIVE_CODE = [
    # 맘모클립: 측정하고 기각
    "train_mclip.py", "eval_mclip.py", "probe_mammoclip.py",
    # 통합형 체크포인트: 통합 구조에서는 분리형만 쓴다
    "fuse_qkv.py",
    # 하이드라 학습 설정: 통합 구조에서는 안 쓴다
    "make_train_cfg.py", "make_tile_cfg.py", "run_det.sh",
    # 축소 데이터 생성: 타일로 대체
    "make_coco.py", "check_coco.py",
    # 제로샷 탐색: 불가로 종료
    "sam3_box_probe.py",
    # 진단: 결론이 났거나 후속 도구로 대체
    "check_calc_signal.py", "check_calc_scale.py",
    "probe_vindr.py", "crosscheck_vindr.py", "variance_check.py",
    "organize_mammo.py", "vindr_pick.py",
]

DOCS = ["작업보고서_0827.md", "작업보고서_0828.md", "작업일지_0828.md",
        "기획서_정정요청.md", "README.md"]

DATA_DIRS = ["det", "det_tile", "det_tile1008"]
RUN_DIRS = ["det_run"]

# 산출물 — 재생성 가능하지만 지금은 남긴다
OUTPUTS = ["base_dets.json", "det_preds.json",
           "vindr_manifest.csv", "vindr_manifest_pos.csv",
           "vindr_urls.txt", "vindr_urls_pos.txt", "vindr_urls_neg.txt"]


def plan():
    """(원본, 대상) 목록. 존재하는 것만."""
    p = []
    for n in LINKS:
        s = MAMMO / n
        if s.is_symlink():
            p.append((s, MAMMO / "medsam3" / n))
    for n in ACTIVE:
        s = MAMMO / n
        if s.exists():
            p.append((s, MAMMO / "training/code" / n))
    for n in ARCHIVE_CODE:
        s = MAMMO / n
        if s.exists():
            p.append((s, MAMMO / "archive/code" / n))
    for n in DOCS:
        s = MAMMO / n
        if s.exists():
            p.append((s, MAMMO / "docs" / n))
    for n in DATA_DIRS:
        s = MAMMO / n
        if s.is_dir() and not s.is_symlink():
            p.append((s, MAMMO / "data" / n))
    for n in RUN_DIRS:
        s = MAMMO / n
        if s.is_dir() and not s.is_symlink():
            p.append((s, MAMMO / "runs" / n))
    for n in OUTPUTS:
        s = MAMMO / n
        if s.exists():
            p.append((s, MAMMO / "archive/outputs" / n))
    for s in sorted(MAMMO.glob("*.log")):
        p.append((s, MAMMO / "archive/logs" / s.name))
    # 학습 결과는 training 아래로
    d = MAMMO / "det_lora_run"
    if d.is_dir():
        for sub, dst in (("ckpt", "training/ckpt"), ("logs", "training/logs")):
            q = d / sub
            if q.is_dir():
                for f in sorted(q.iterdir()):
                    p.append((f, MAMMO / dst / f.name))
    return p


def leftovers(moved):
    src = {s for s, _ in moved}
    known = set(DIRS) | {"medsam3", "docs", "training", "data", "runs",
                         "archive", "det_lora_run", "__pycache__"}
    out = []
    for f in sorted(MAMMO.iterdir()):
        if f in src or f.name in known:
            continue
        out.append(f)
    return out


def verify():
    print("=" * 74)
    print("검증")
    print("=" * 74)
    ok = True
    md = MAMMO / "medsam3"
    for n in LINKS:
        p = md / n
        if not p.is_symlink():
            print(f"  ✗ 링크가 아니다: {p}")
            ok = False
            continue
        tgt = Path(os.readlink(p))
        good = p.resolve().exists()
        print(f"  {'✓' if good else '✗'} {n:18s} -> {tgt}")
        ok &= good

    print("\n  import 확인 (medsam3/ 에서)")
    code = ("import sys; sys.path.insert(0,'.');"
            "import sam3, lora_layers, merge_medsam3;"
            "print('  ✓ sam3 · lora_layers · merge_medsam3')")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(md),
                       capture_output=True, text=True)
    print(r.stdout.rstrip() or f"  ✗ {r.stderr.strip().splitlines()[-1:]}")
    ok &= (r.returncode == 0)

    print("\n  데이터")
    for n in DATA_DIRS:
        p = MAMMO / "data" / n
        m = p / "annotations"
        print(f"  {'✓' if m.is_dir() else '·'} data/{n}"
              + (f"   주석 {len(list(m.glob('*.json')))}개" if m.is_dir() else " (없음)"))

    print("\n  병합본")
    for n in ("medsam3_merged.pt", "medsam3_merged_fused.pt"):
        p = md / "ckpt" / n
        print(f"  {'✓' if p.is_file() else '·'} {n}"
              + (f"  {p.stat().st_size/1e9:.2f}GB" if p.is_file() else ""))

    print("\n" + ("  전부 통과" if ok else "  ! 문제가 있다 — 위를 확인해라"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    if not MAMMO.is_dir():
        sys.exit(f"없다: {MAMMO}")
    if a.verify:
        sys.exit(0 if verify() else 1)

    print("=" * 74)
    print("맘모 파트 재배치" + ("" if a.go else "   [무엇이 어디로 갈지만]"))
    print("=" * 74)

    # 링크가 절대경로인지 먼저 본다 — 상대경로면 옮기는 순간 끊어진다
    print("\n■ 심볼릭 링크")
    bad = []
    for n in LINKS:
        s = MAMMO / n
        if not s.is_symlink():
            print(f"  · {n:18s} 링크가 아니다 — 건너뛴다")
            continue
        t = os.readlink(s)
        absolute = Path(t).is_absolute()
        print(f"  {'✓' if absolute else '✗'} {n:18s} -> {t}")
        if not absolute:
            bad.append(n)
    if bad:
        sys.exit(f"\n✗ 상대경로 링크가 있다: {bad}\n"
                 "  옮기면 끊어진다. 절대경로로 다시 만든 뒤 진행해라.")

    p = plan()
    groups = {}
    for s, d in p:
        groups.setdefault(d.parent.relative_to(MAMMO).as_posix(), []).append(s.name)

    print(f"\n■ 이동 계획   {len(p)}건")
    for k in sorted(groups):
        v = groups[k]
        print(f"\n  {k}/   ({len(v)}개)")
        for n in v[:14]:
            print(f"    {n}")
        if len(v) > 14:
            print(f"    ... 외 {len(v)-14}개")

    left = leftovers(p)
    if left:
        print(f"\n■ 목록에 없어 안 옮기는 것   {len(left)}개")
        for f in left[:20]:
            kind = "폴더" if f.is_dir() else "파일"
            print(f"    {kind}  {f.name}")
        print("    분류를 정하면 목록에 넣겠다. 그전까지는 제자리에 둔다.")

    if not a.go:
        print("\n" + "=" * 74)
        print("--go 를 붙여야 실제로 옮긴다. 아무것도 지우지 않는다.")
        print("=" * 74)
        return

    print("\n■ 실행")
    for d in DIRS:
        (MAMMO / d).mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for s, d in p:
        try:
            d.parent.mkdir(parents=True, exist_ok=True)
            if d.exists() or d.is_symlink():
                print(f"  · 이미 있다, 건너뜀: {d.relative_to(MAMMO)}")
                continue
            shutil.move(str(s), str(d))     # 링크는 링크째로 옮겨진다
            n_ok += 1
        except Exception as e:
            print(f"  ✗ {s.name}: {type(e).__name__}: {e}")
    print(f"  옮김 {n_ok}/{len(p)}")

    d = MAMMO / "det_lora_run"
    if d.is_dir() and not any(d.rglob("*")):
        d.rmdir()
        print("  빈 det_lora_run 정리")

    print()
    verify()

    print("\n" + "=" * 74)
    print("다음")
    print("=" * 74)
    print("  스크립트의 경로 상수를 새 구조에 맞춰야 한다.")
    print("    ckpt/...        ->  medsam3/ckpt/...")
    print("    configs/...     ->  medsam3/configs/...")
    print("    det_tile1008    ->  data/det_tile1008")
    print("  그리고 --repo 기본값이 mammo/medsam3 를 가리켜야 한다.")
    print("  고친 스크립트를 받아서 training/code/ 에 넣어라.")


if __name__ == "__main__":
    main()
