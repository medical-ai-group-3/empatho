#!/usr/bin/env python
"""
필요 없어진 것을 지운다 — 지우면 안 되는 것은 못 지우게 막고.

왜 스크립트인가
  붙여넣기로 rm 을 돌리다 줄이 엉킨 적이 있다. 그리고 medsam3/ 아래는 전부
  심볼릭 링크라 잘못 건드리면 3.4GB 백본이 날아간다. 지울 것을 이름으로
  지정하고 나머지는 막는다.

세 겹으로 막는다
  1. NEVER — 이름이 여기 있으면 무슨 인자를 줘도 안 지운다
  2. 심볼릭 링크는 절대 안 따라간다. ROOT 밖으로 나가면 거부한다
  3. 최근 --fresh 분 안에 바뀐 파일은 안 지운다 (돌고 있는 작업의 산출물)

돌고 있는 작업 보호
  pgrep 으로 우리 스크립트가 도는지 보고, 도는 게 있으면 그것이 만드는
  파일을 보호 목록에 자동으로 넣는다. eval_vindr.py 가 돌고 있으면
  vindr_dets.json 과 그 .partial.json 을 건드리지 않는다.

사용
  python3 cleanup.py                    # 무엇을 얼마나 지울지만 (기본)
  python3 cleanup.py --go
  python3 cleanup.py --go --keep 0      # 번호본 체크포인트까지 (9.3GB)
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import ARCHIVE, DATA, DOCS, MEDSAM3, ROOT, RUNS, TRAINING  # noqa: E402

# ── 1겹: 이름이 여기 있으면 무슨 인자를 줘도 건너뛴다 ──────────────────
NEVER = {
    "medsam3", "docs", "training", "data", "code", "configs",
    "det", "det_tile1008", "archive", "labels", "ckpt", "logs",
    # 가중치
    "checkpoint.pt",                      # 기준선 재평가에 필요
    "best_lora.pt", "last_lora.pt", "last_state.pt",
    # 확정 수치의 근거가 되는 검출 결과. 발표 문서가 이걸 인용한다.
    "tile_dets_last.json",                # 에폭 6 확정본
    "tile_raw_ep6.json",                  # 합치기 실험의 입력. 다시 만들면 83분
    "base_dets.json",                     # 기준선 — mAP 비교에 쓴다
    "vindr_dets.json",                    # 외부 검증 -14.7%p 의 근거. 20분+
    "vindr_dets_scaled.json",             # 확대 재실험. 40~50분
    # 다시 만들려면 DICOM 을 전부 다시 읽어야 하는 캐시
    "merge_tissue_cache.json", "crop_rule.json",
    # 서빙
    "mammo_io.py", "infer_mammo.py", "serve_mammo.py", "mammo_api.md",
    # 현행 도구 — 이름이 test/check/scan 이라 훑기에 걸리기 쉽다
    "check_serving.py", "scan_vindr.py", "measure_spacing.py",
    "run_when_free.sh", "cleanup.py",
}

# 도는 작업 -> 그것이 쓰는 파일. 돌고 있으면 NEVER 에 자동으로 들어간다.
RUNNING_OUTPUTS = {
    "eval_vindr.py":      ["vindr_dets.json", "vindr_dets.partial.json",
                           "vindr_dets_scaled.json",
                           "vindr_dets_scaled.partial.json",
                           "eval_vindr.log", "eval_vindr_scaled.log",
                           "vindr_redownload.txt"],
    # run_when_free.sh 로 감싸도 argv 에 스크립트 이름이 남아 pgrep 에 잡힌다.
    # 자리를 기다리는 동안에도 보호가 걸린다.
    "check_serving.py":   [],
    "eval_mammo_det.py":  ["tile_dets_last.json", "tile_raw_ep6.json"],
    "train_mammo_det.py": ["last_lora.pt", "last_state.pt", "best_lora.pt"],
    "eval_end2end.py":    ["e2e_calc.json", "e2e_mass.json"],
    "make_tiles.py":      ["det_tile1008"],
    "scan_vindr.py":      ["vindr_redownload.txt"],
    "serve_mammo.py":     [],
}

# ── 이번에 지우기로 한 것 ─────────────────────────────────────────────
# 각 항목: (경로패턴, 왜 지우는가). 이유 없이 목록에 넣지 않는다 —
# 나중에 "이건 왜 지웠지" 가 되면 다시 만들어야 한다.
STALE = [
    ("docs/**/demo*.png",        "시연 그림. 확정 임계값 이전 것이라 지금 결과와 다르다"),
    ("docs/**/demo*.json",       "위와 같은 실행의 결과"),
    ("docs/demo",             "시연 폴더 통째로"),
    ("docs/merge_wbf02.json", "wbf@0.2 실험. 0.3 으로 확정돼 쓸 일이 없다"),
    ("**/tile_dets_wbf02.json", "wbf@0.2 실험 결과"),
    ("**/tile_dets_wbf03.json", "tile_dets_last.json 과 같은 내용의 중간 산출물"),
    ("**/tile_dets_ep0.json",  "에폭 0. 에폭 6 으로 확정됐다"),
    ("training/code/demo.png", "predict.py 시험 찌꺼기. 확정 임계값 이전 그림이다"),
    # 이건 지우는 게 아니라 '반드시 지워야 하는' 것이다.
    ("**/tile_dets_ep12.json",
     "★ 이름이 거짓말이다. 에폭 12 학습은 OOM 으로 죽었고 이 파일은 에폭 6 "
     "가중치로 평가한 결과다(tile_dets_last.json 과 md5 동일). "
     "남겨두면 누군가 '에폭 12 결과' 로 인용한다"),
]

MOVE_TO_ARCHIVE = [
    ("diag_crop.py", "조각 정렬을 진단한 일회용 스크립트. 결론은 문서에 옮겼다"),
    ("reorg.py",     "재배치 완료"),
    # 지우면 안 된다 — 출력물이 아니라 스크립트다. 시연 그림을 다시 만들 때 쓴다.
    ("demo_batch.sh", "시연 그림 생성 스크립트. 이름 때문에 훑기에 걸리지만 "
                      "출력물이 아니라 코드다"),
]

LOG_DIRS = [TRAINING / "logs"]


def du(p: Path) -> int:
    if p.is_symlink() or not p.exists():
        return 0
    if p.is_file():
        return p.stat().st_size
    n = 0
    for d, _, fs in os.walk(p):
        for f in fs:
            q = Path(d) / f
            try:
                if not q.is_symlink():
                    n += q.stat().st_size
            except OSError:
                pass
    return n


def gb(n):
    return f"{n/2**30:.2f}GB" if n >= 2**30 else f"{n/2**20:.1f}MB"


def busy():
    """돌고 있는 우리 작업."""
    out = []
    for pat in RUNNING_OUTPUTS:
        r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True)
        if r.returncode == 0:
            out.append(pat)
    return out


class Guard:
    def __init__(self, never, fresh_sec):
        self.never = set(never)
        self.fresh = fresh_sec

    def check(self, p: Path):
        """(지워도 되나, 안 되면 이유)"""
        if p.is_symlink():
            return False, "심볼릭 링크"
        if p.name in self.never:
            return False, "보호 목록"
        try:
            rel = p.resolve().relative_to(ROOT.resolve())
        except ValueError:
            return False, f"{ROOT} 밖"
        if str(rel).startswith("medsam3"):
            return False, "medsam3 아래 — 공유 저장소다"
        if not p.exists():
            return False, "없음"
        # 3겹: 방금 바뀐 것은 누가 쓰고 있는 중일 수 있다
        try:
            age = time.time() - p.stat().st_mtime
            if age < self.fresh:
                return False, f"{age/60:.0f}분 전에 바뀜 — 쓰는 중일 수 있다"
        except OSError:
            return False, "상태를 못 읽음"
        return True, ""

    def rm(self, p: Path, go):
        ok, why = self.check(p)
        if not ok:
            return 0, why
        n = du(p)
        if go:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
        return n, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=1,
                    help="기준선 번호본 체크포인트를 몇 개 남길까 (개당 9.3GB). "
                         "checkpoint.pt 는 세지 않고 항상 남긴다")
    ap.add_argument("--keep-logs", type=int, default=5)
    ap.add_argument("--fresh", type=int, default=30,
                    help="최근 몇 분 안에 바뀐 파일은 안 지운다")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()

    print("=" * 74)
    print("정리" + ("" if a.go else "   [무엇을 지울지만 본다 — 실제로는 안 지운다]"))
    print("=" * 74)
    try:
        for line in subprocess.run(["df", "-h", str(ROOT)], capture_output=True,
                                   text=True, timeout=10).stdout.splitlines():
            print("  " + line)
    except Exception:
        pass

    never = set(NEVER)
    run = busy()
    if run:
        print(f"\n  ! 돌고 있는 작업: {', '.join(run)}")
        for r in run:
            for f in RUNNING_OUTPUTS[r]:
                never.add(f)
                print(f"      보호 추가  {f}")
        print("    이것들은 못 지운다. 돌려도 안전하다.")
    g = Guard(never, a.fresh * 60)
    print(f"\n  최근 {a.fresh}분 안에 바뀐 파일도 건너뛴다")

    freed = 0

    # ── 1. 이번에 지우기로 한 것 ─────────────────────────────────────
    print("\n■ 낡은 실험 산출물 · 시연 파일")
    hit = 0
    for pat, why in STALE:
        for p in sorted(set(ROOT.glob(pat))):
            n, no = g.rm(p, a.go)
            freed += n
            hit += 1
            try:
                shown = p.relative_to(ROOT)
            except ValueError:
                shown = p
            print(f"  {str(shown)[:44]:46s} {gb(n) if not no else '':>9s}  "
                  f"{no or '지움'}")
            if not no:
                print(f"      └ {why}")
    if not hit:
        print("  해당 없음 — 이미 지웠거나 애초에 없다")

    # ── 2. 시연·시험 흔적 훑기 (자동으로 안 지운다) ──────────────────
    print("\n■ 시연·시험처럼 보이는 것 (이름만 보고 찾았다. 판단은 사람이)")
    sweep = []
    for pat in ("**/demo*", "**/test_*", "**/tmp_*", "**/*_old.*",
                "**/*_bak.*", "**/scratch*", "**/트라이*", "**/실험*"):
        for p in ROOT.glob(pat):
            if p.is_symlink() or "medsam3" in p.parts or "archive" in p.parts:
                continue
            if p.name in never or p.suffix in (".py", ".sh"):
                continue
            sweep.append(p)
    handled = {q for pat, _ in STALE for q in ROOT.glob(pat)}
    sweep = sorted(set(sweep) - handled)
    if sweep:
        for p in sweep[:40]:
            ok, why = g.check(p)
            print(f"  {str(p.relative_to(ROOT))[:50]:52s} {gb(du(p)):>9s}"
                  f"  {'지울 수 있음' if ok else why}")
        if len(sweep) > 40:
            print(f"  … 외 {len(sweep)-40}개")
        print("\n  ※ 자동으로 안 지운다. 지울 것을 정해서 STALE 목록에 넣고 다시 돌려라.")
        print("     이름만으로 판단하면 확정 수치의 근거를 날릴 수 있다.")
    else:
        print("  없음")

    # ── 3. 옮길 것 ───────────────────────────────────────────────────
    print("\n■ archive/code 로 옮길 것 (지우지 않는다 — 기록이다)")
    dst = ARCHIVE / "code"
    for name, why in MOVE_TO_ARCHIVE:
        src = TRAINING / "code" / name
        if not src.is_file():
            continue
        print(f"  {name:26s} → archive/code/   {why}")
        if a.go:
            dst.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst / name))

    # ── 4. 기준선 번호본 체크포인트 ──────────────────────────────────
    print(f"\n■ 기준선 체크포인트 — 번호본은 최근 {a.keep}개만")
    d = RUNS / "det_run" / "checkpoints"
    if d.is_dir():
        fs = sorted([f for f in d.glob("checkpoint_*.pt") if not f.is_symlink()],
                    key=lambda f: f.stat().st_mtime, reverse=True)
        for f in fs[a.keep:]:
            n, why = g.rm(f, a.go)
            freed += n
            print(f"  {f.name:22s} {gb(n):>9s}  {why or '지움'}")
        for f in fs[:a.keep]:
            print(f"  {f.name:22s} {gb(du(f)):>9s}  남김")
        cp = d / "checkpoint.pt"
        if cp.is_file():
            print(f"  {'checkpoint.pt':22s} {gb(du(cp)):>9s}  남김 — 기준선 재평가에 필요")
        if a.keep > 0 and fs:
            print("  번호본도 지우려면 --keep 0  (checkpoint.pt 와 같은 시점의 사본이다)")
    else:
        print("  없음")

    # ── 5. 학습 로그 ─────────────────────────────────────────────────
    print(f"\n■ 학습 로그 — 최근 {a.keep_logs}개만")
    for ld in LOG_DIRS:
        if not ld.is_dir():
            continue
        fs = sorted(ld.glob("train_*.log"),
                    key=lambda f: f.stat().st_mtime, reverse=True)
        for f in fs[a.keep_logs:]:
            n, why = g.rm(f, a.go)
            freed += n
            print(f"  {f.name:32s} {gb(n):>8s}  {why or '지움'}")
        if len(fs) <= a.keep_logs:
            print(f"  {len(fs)}개 — 전부 남긴다")

    # ── 6. 찌꺼기 ────────────────────────────────────────────────────
    print("\n■ 찌꺼기")
    junk = []
    for d0, subs, _ in os.walk(ROOT):
        subs[:] = [s for s in subs
                   if not (Path(d0) / s).is_symlink() and s != "medsam3"]
        if "__pycache__" in subs:
            junk.append(Path(d0) / "__pycache__")
    for pat in ("*.bak", "*.py.bak", "*.pt.tmp", "nohup.out"):
        junk += list(ROOT.rglob(pat))
    # 중간 저장은 '최종본이 이미 있을 때만' 찌꺼기다. pgrep 이 놓친 실행 중
    # 작업의 중간 저장을 날리면 그게 정확히 이 스크립트가 막으려던 사고다.
    for p in ROOT.rglob("*.partial.json"):
        final = p.with_name(p.name.replace(".partial.json", ".json"))
        if final.is_file() and final.stat().st_mtime >= p.stat().st_mtime:
            junk.append(p)
    for p in ROOT.iterdir():          # 재배치로 비어버린 폴더
        if p.is_dir() and not p.is_symlink() and p.name not in never \
                and not any(p.iterdir()):
            junk.append(p)
    tot, n_ok, skipped = 0, 0, []
    for p in sorted(set(junk)):
        n, why = g.rm(p, a.go)
        if why:
            skipped.append((p, why))
        else:
            tot += n
            n_ok += 1
    freed += tot
    print(f"  __pycache__ · .bak · 임시파일 · 빈 폴더  {n_ok}개   {gb(tot)}")
    for p, why in skipped[:5]:
        print(f"    건너뜀  {p.name:34s} {why}")

    # ── 7. 판단이 필요한 것 ──────────────────────────────────────────
    print("\n■ 판단이 필요한 것 (자동으로 안 지운다)")
    opt = [
        (DATA / "det", "구 축소본. 기준선 평가를 다시 돌릴 때 필요하다"),
        (ARCHIVE / "outputs" / "det_preds.json",
         "에폭 4 시점의 옛 검출 결과. base_dets.json(에폭 20)로 대체됐다"),
        (ROOT / "tilecheck", "타일 대조 그림 — 보고서에 쓸 수 있다"),
    ]
    for p, why in opt:
        if p.exists():
            print(f"  {str(p.name):26s} {gb(du(p)):>9s}  {why}")

    # ── 8. 안 건드리는 것 ────────────────────────────────────────────
    print("\n■ 안 건드리는 것")
    for p, why in ((MEDSAM3, "MedSAM3 연결 — 공유 저장소. 지우면 백본 3.4GB 가 날아간다"),
                   (DOCS, "보고서 · 일지 · 발표 자료"),
                   (TRAINING / "code", "현행 코드"),
                   (TRAINING / "ckpt", "학습 결과 LoRA"),
                   (DATA / "det_tile1008", "현행 학습 데이터"),
                   (ARCHIVE / "code", "끝난 갈래 기록"),
                   (ROOT.parent / "train", "MRI 파트 — 다른 사람 작업"),
                   (ROOT.parent / "us", "초음파 파트 — 다른 사람 작업"),
                   (ROOT.parent / "data", "원본 데이터 — 다시 받을 수 없다")):
        mark = "있음" if p.exists() else "없음"
        sz = f"  {gb(du(p))}" if (p.exists() and p.is_relative_to(ROOT)
                                  and p != MEDSAM3) else ""
        print(f"  {mark}  {p.name:14s}{sz:>11s}  {why}")

    print("\n" + "=" * 74)
    print(f"{'확보' if a.go else '확보 예상'}   {gb(freed)}")
    if not a.go:
        print("  --go 를 붙여야 실제로 지운다.")
    print("=" * 74)


if __name__ == "__main__":
    main()
