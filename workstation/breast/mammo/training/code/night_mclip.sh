#!/usr/bin/env bash
# Mammo-CLIP 머리가 나오면 이어서 전이 확인 → 재점수 → 채점까지 간다.
#
# 왜 사슬로 거는가
#   세 단계가 전부 GPU 인데 사람이 자는 8시간 동안 첫 단계만 돌고 멈추면
#   하루를 버린다. 앞 단계 결과가 나쁘더라도 뒤를 돌린다 — 최종 판정은
#   어차피 FROC 이고, 밤에는 GPU 가 공짜다.
#
# 안전장치
#   · 머리 파일이 나오고 **학습이 끝난 뒤**에 다음으로 간다 (pgrep 확인)
#   · 3시간 안에 안 나오면 포기하고 왜 그런지 남긴다
#   · GPU 가 필요한 두 단계는 queue_gpu.sh 로 걸어 남의 작업과 안 겹치게 한다
#   · 출력 디렉터리를 archive/outputs/mclip 으로 갈라 둔다
#     — SAM3 재점수 파일과 이름이 같아서 안 가르면 덮어쓴다
#   · 모든 경로가 절대 경로다 (백본 세우는 중에 cwd 가 바뀐다)
#
# 쓰는 법
#   cd ~/workspace/breast/mammo
#   nohup bash training/code/night_mclip.sh > docs/night_mclip.log 2>&1 &
#
#   아침에   tail -c 3000 docs/night_mclip.log

set -u

R="$HOME/workspace/breast/mammo"
C="$R/training/code"
HEAD="$R/training/ckpt/binary_head_mclip.pt"
DETS="$R/archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json"
GTC="$R/docs/show_gt_cache.json"
OUT="$R/archive/outputs/mclip"
export MIN_FREE_MB="${MIN_FREE_MB:-8000}"

say() { echo; echo "=== $(date '+%m-%d %H:%M') · $*"; }

say "머리를 기다린다 — $HEAD"
for i in $(seq 1 360); do            # 30초 × 360 = 3시간
    if [ -f "$HEAD" ] && ! pgrep -f "train_binary.py.*mclip" > /dev/null; then
        break
    fi
    sleep 30
done

if [ ! -f "$HEAD" ]; then
    say "머리가 안 나왔다. 여기서 멈춘다."
    echo "  docs/queue_mclip.log 끝을 볼 것:"
    tail -c 1500 "$R/docs/queue_mclip.log" 2>/dev/null
    exit 2
fi
say "머리를 찾았다 ($(du -h "$HEAD" | cut -f1))"
python3 - "$HEAD" <<'PY'
import sys, torch
ck = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
a = ck.get("args") or {}
print(f"  특징 {ck['feat_dim']}차원 · 학습 AUC {ck.get('auc'):.4f}")
print(f"  백본 {a.get('mclip') or 'SAM3 (!! 갈아끼우기가 안 먹었다)'}")
if int(ck["feat_dim"]) == 16384:
    print("  !! 16,384 차원이면 SAM3 다. 뒤 단계는 의미가 없다.")
PY

# ── 전이 확인 — 학습한 문제가 아니라 실전 문제로 잰다 ────────────────
say "전이 확인"
bash "$C/queue_gpu.sh" mclip_transfer "$C" -- \
    python3 check_binary_transfer.py \
        --head "$HEAD" --dets "$DETS" --gt-cache "$GTC" \
    || { say "전이 확인이 실패했다"; exit 3; }

# ── 재점수 — 앞 결과와 무관하게 돌린다. 최종 판정은 FROC 이다 ─────────
say "재점수 (앞 결과와 무관하게 돌린다 — 최종 판정은 FROC 이다)"
mkdir -p "$OUT"
bash "$C/queue_gpu.sh" mclip_rescore "$C" -- \
    python3 rescore_binary.py \
        --head "$HEAD" --dets "$DETS" --gt-cache "$GTC" \
        --thr-ref "$R/docs/score_dets.json" \
        --cache "$R/docs/rescore_mclip_probs.json" \
        --out-dir "$OUT" \
    || { say "재점수가 실패했다"; exit 4; }

# ── 채점 — GPU 안 쓴다 ──────────────────────────────────────────────
say "채점 (GPU 안 쓴다)"
cd "$R" || exit 5
python3 "$C/score_dets.py" "$DETS" "$OUT"/*.json \
    --ref "$R/docs/merge_tissue.json" \
    --save "$R/docs/score_dets_mclip.json" \
    || { say "채점이 실패했다"; exit 6; }

say "다 끝났다"
echo
echo "아침에 볼 것 — 판정 칸만 뽑는다"
cat <<'EOF'
  cd ~/workspace/breast/mammo
  python3 - <<'PY'
import json
d = json.load(open("docs/score_dets_mclip.json"))
print(f"{'파일':<34}{'종류':<15}{'1개':>8}{'2개':>8}{'4개':>8}{'max':>8}")
for f, r in d.items():
    for k, v in r.items():
        c = v.get("center", {})
        g = lambda t: c.get(str(t), c.get(t, float('nan')))
        print(f"{f[-34:]:<34}{k:<15}{g(1.0):>8.3f}{g(2.0):>8.3f}"
              f"{g(4.0):>8.3f}{c.get('max', float('nan')):>8.3f}")
PY
EOF
echo
echo "  ① bin000 줄이 원본과 같은가"
echo "  ② 2개 칸이 미세석회 77.5 · 종괴 76.7 을 넘었는가"
