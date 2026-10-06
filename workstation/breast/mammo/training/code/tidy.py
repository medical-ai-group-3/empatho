#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""자리 정리 — 묶음별로, 하나씩 켜서 지운다.

  기본은 **보기만** 한다. --go 를 줘야 지운다.
  그리고 묶음마다 따로 켜야 한다. 한 번에 다 지우는 스위치는 없다.

  지울 것을 **글자 그대로 적어 두었다.** 별표(*)로 훑지 않는다 —
  훑다가 심볼릭 링크를 밟으면 링크 너머 3.4GB 백본이 날아간다.
  이 스크립트는 심볼릭 링크를 만나면 건드리지 않고 넘어간다.

묶음
  --binary     취소한 이진 게이트 실험      약 3.4GB
  --normals    정상 유방 원본 영상          약 5.2GB
  --rejected   기각된 학습 회차의 가중치    약 344MB
  --olddets    옛 검출 덤프                 약 830MB
  --baseline   기준선 체크포인트            9.3GB   ← 발표 뒤에

절대 안 지우는 것 (목록에 아예 없다)
  medsam3/ 아래 심볼릭 링크 다섯
  training/ckpt/last_lora.pt          서빙 검출기
  training/ckpt/best_lora.pt
  training/ckpt/last_state.pt
  서술어 넷  mammo_{calc,mass}_trunk_..._{lora,head}.pt
  archive/outputs/tile_dets_last.json  지금 쓰는 검출 덤프
  archive/outputs/normal_dets.jsonl    정상 유방 채점 결과
  archive/outputs/vindr_normal_*.csv/.txt
  ~/workspace/breast/train · us        다른 팀

사용
  python3 training/code/tidy.py                       # 전부 보기
  python3 training/code/tidy.py --binary --normals    # 지울 것 확인
  python3 training/code/tidy.py --binary --normals --go
"""

import argparse
import shutil
from pathlib import Path

HOME = Path.home()
ROOT = HOME / "workspace/breast/mammo"
VINDR = HOME / "workspace/breast/data/vindr"

GROUPS = {
    "binary": (
        "취소한 이진 게이트 실험",
        "서빙이 안 쓴다(infer_mammo·serve_mammo 에 mammoclip 참조 없음). "
        "결과는 docs/score_dets_binary.json · rescore_binary_probs.json 에 남는다. "
        "Mammo-CLIP 은 다시 받을 수 있다.",
        [ROOT / "ckpt/mammoclip/b5-model-best-epoch-7.tar",
         ROOT / "data/binary_feats.npz",
         ROOT / "data/binary_feats2.npz",
         ROOT / "data/binary_feats_mclip.npz",
         ROOT / "training/ckpt/binary_head.pt",
         ROOT / "training/ckpt/binary_head2.pt",
         ROOT / "training/ckpt/binary_head_mclip.pt"],
    ),
    "normals": (
        "정상 유방 원본 영상 (VinDr BI-RADS 1)",
        "채점이 끝났고 결과가 archive/outputs/normal_dets.jsonl 에 있다. "
        "다시 받을 목록도 vindr_normal_urls.txt 에 있다. 7시간 53분 걸린다.",
        [VINDR / "normal"],
    ),
    "rejected": (
        "기각된 학습 회차의 가중치",
        "에폭 12는 실시했고 **과적합으로 기각**했다. 에폭 6은 에폭 8로 넘어갔다. "
        "결론은 문서에, 학습 로그는 git 에 남는다. 가중치만 지운다.",
        [ROOT / "training12/ckpt/best_lora.pt",
         ROOT / "training12/ckpt/last_lora.pt",
         ROOT / "training12/ckpt/last_state.pt",
         ROOT / "training/ckpt/ep6/best_lora.pt",
         ROOT / "training/ckpt/ep6/last_lora.pt",
         ROOT / "training/ckpt/ep6/last_state.pt"],
    ),
    "olddets": (
        "옛 검출 덤프",
        "지금 쓰는 tile_dets_last.json 은 남긴다. 아래는 지난 설정의 것이다 — "
        "다시 만들려면 평가를 돌려야 하지만, 그 설정으로 돌아갈 일이 없다.",
        [ROOT / "archive/outputs/tile_dets_ov504.json",
         ROOT / "archive/outputs/tile_dets_train600.json",
         ROOT / "archive/outputs/tile_raw_ov504.json",
         ROOT / "archive/outputs/tile_raw_ep6.json",
         ROOT / "archive/outputs/tile_dets_wbf02_tissue.json",
         ROOT / "archive/outputs/tile_dets_wbf02_tissue_norm.json"],
    ),
    "baseline": (
        "기준선 체크포인트 (전체 미세조정)",
        "⚠ **발표 뒤에 지우길 권한다.** LoRA 와 비교하는 대조군이고, "
        "「왜 LoRA 냐」가 발표의 핵심 논거다. 숫자(종괴 57.3% · 석회 18%대)는 "
        "문서에 있지만, 다시 평가할 수 있는 것은 이 파일뿐이다.",
        [ROOT / "runs/det_run/checkpoints/checkpoint.pt"],
    ),
}


def human(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:,.0f}{u}" if u == "B" else f"{n:,.1f}{u}"
        n /= 1024


def size_of(p: Path):
    if p.is_symlink():
        return None                      # 링크는 세지도 지우지도 않는다
    if p.is_file():
        return p.stat().st_size
    if p.is_dir():
        t = 0
        for q in p.rglob("*"):
            if q.is_symlink() or not q.is_file():
                continue
            try:
                t += q.stat().st_size
            except OSError:
                pass
        return t
    return None


def main():
    ap = argparse.ArgumentParser()
    for g in GROUPS:
        ap.add_argument(f"--{g}", action="store_true")
    ap.add_argument("--go", action="store_true", help="실제로 지운다")
    a = ap.parse_args()

    picked = [g for g in GROUPS if getattr(a, g)]

    print("=" * 78)
    print("자리 정리" + ("   [지운다]" if a.go and picked else "   [보기만 한다]"))
    print("=" * 78)

    grand = 0
    todo = []
    for g, (title, why, paths) in GROUPS.items():
        on = g in picked
        print(f"\n■ {title}   [--{g}]" + ("   ← 켜짐" if on else ""))
        print(f"  {why}")
        sub = 0
        for p in paths:
            if p.is_symlink():
                print(f"  {'링크':>10}  {p}   ← 건드리지 않는다")
                continue
            sz = size_of(p)
            if sz is None:
                print(f"  {'없음':>10}  {p}")
                continue
            sub += sz
            print(f"  {human(sz):>10}  {p}")
            if on:
                todo.append(p)
        print(f"  {'―' * 8}  묶음 합계 {human(sub)}")
        if on:
            grand += sub

    if not picked:
        print("\n  아무 묶음도 안 켰다. 예:")
        print("    python3 training/code/tidy.py --binary --normals")
        return

    print(f"\n  켠 묶음에서 비울 자리 {human(grand)} · 대상 {len(todo)}개")
    if not a.go:
        print("  --go 를 줘야 실제로 지운다. 지금은 보기만 했다.")
        return

    print()
    freed = 0
    for p in todo:
        if p.is_symlink():
            print(f"  건너뜀(링크) {p}")
            continue
        sz = size_of(p) or 0
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.chmod(0o644)           # 읽기 전용으로 잠근 것이 있다
                p.unlink()
        except Exception as e:
            print(f"  실패 {p} — {e}")
            continue
        freed += sz
        print(f"  지웠다 {human(sz):>10}  {p}")

    print(f"\n  비운 자리 {human(freed)}")
    print("""
  확인

    df -h ~/workspace
    python3 training/code/survey_disk.py --top 15
""")


if __name__ == "__main__":
    main()
