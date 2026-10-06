#!/usr/bin/env bash
# 지금 도는 평가(에폭 5 · 598장)가 끝나면 에폭 0 을 200장으로 잰다.
#
# 왜 에폭 0 인가
#   검증 손실이 에폭 0 에서 최저였고 그 뒤로 올랐다.
#     에폭 0  5.04    에폭 1  9.24    에폭 2  5.32
#     에폭 3  5.72    에폭 4  6.92    에폭 5  7.15
#   계산량을 맞추려고 정한 6에폭이 이 구조에서는 과했을 수 있다.
#   다만 검증 손실이 낮다고 검출이 좋은 것은 아니다 — 손실에는 박스·분류·
#   존재 여부가 섞여 있고 FROC 은 순위만 본다. 그래서 직접 잰다.
#
# 왜 200장인가
#   598장은 80분이다. GPU 를 다른 팀에 넘겨야 해서 시간이 없다.
#   200장이면 약 28분이고, 에폭 5 결과에서 같은 200장을 뽑아 비교하면
#   표본이 같아 비교가 성립한다 (compare_froc.py 가 그 일을 한다).
#
# 사용
#   nohup bash after_eval.sh > ../logs/after_eval.log 2>&1 &

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOGS="$ROOT/training/logs"
CKPT="$ROOT/training/ckpt"
OUT="$ROOT/archive/outputs"
POLL=120
MAX_WAIT=$((3 * 3600))

now() { date '+%F %T'; }
say() { echo "$(now)  $*"; }

cd "$HERE" || exit 1
say "대기 시작 — 에폭 5 평가가 끝나기를 기다린다"

PID=$(pgrep -f "eval_mammo_det.py.*last_lora" | head -1)
if [ -z "$PID" ]; then
    say "에폭 5 평가 프로세스가 안 보인다 — 이미 끝났다고 본다"
else
    W=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep "$POLL"
        W=$((W + POLL))
        if [ $((W % 1800)) -lt "$POLL" ]; then
            say "대기 $((W / 60))분   $(grep -o '[0-9]*/598' "$LOGS/eval_tile.log" | tail -1)"
        fi
        if [ "$W" -ge "$MAX_WAIT" ]; then
            say "! 3시간을 넘겼다 — 중단"
            exit 2
        fi
    done
    say "에폭 5 평가 종료"
fi

# ── 끝까지 갔는지 확인 ──────────────────────────────────────────────────
if [ ! -s "$OUT/tile_dets_last.json" ]; then
    say "! 검출 결과가 없다: $OUT/tile_dets_last.json"
    say "  평가가 도중에 죽었다. 로그를 봐라."
    tail -20 "$LOGS/eval_tile.log"
    exit 3
fi
if ! grep -q "^calcification" "$LOGS/eval_tile.log"; then
    say "! 지표가 안 나왔다 — 평가가 완주하지 못했다"
    tail -20 "$LOGS/eval_tile.log"
    exit 3
fi
say "확인  tile_dets_last.json  $(du -h "$OUT/tile_dets_last.json" | cut -f1)"

echo "────────── 에폭 5 · 598장 ──────────"
grep -E "^(mass|calcification)|── |^      [0-9]" "$LOGS/eval_tile.log" | head -40
echo "────────────────────────────────────"

# ── 에폭 0 · 200장 ──────────────────────────────────────────────────────
if [ ! -f "$CKPT/best_lora.pt" ]; then
    say "! best_lora.pt 가 없다 — 여기서 끝낸다"
    exit 4
fi

FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
say "GPU 여유 ${FREE}MiB"
if [ "${FREE:-0}" -lt 8000 ]; then
    say "! 여유가 부족하다 — 다른 작업이 붙었다. 에폭 0 평가는 수동으로 해라"
    exit 5
fi

say "에폭 0 평가 시작 (200장) -> $LOGS/eval_tile_ep0.log"
if ! python3 -u eval_mammo_det.py --lora "$CKPT/best_lora.pt" --n 200 \
        --save-json "$OUT/tile_dets_ep0.json" > "$LOGS/eval_tile_ep0.log" 2>&1; then
    say "! 에폭 0 평가 실패"
    tail -25 "$LOGS/eval_tile_ep0.log"
    exit 6
fi
say "에폭 0 평가 완료"
echo "────────── 에폭 0 · 200장 ──────────"
grep -E "^(mass|calcification)|── |^      [0-9]" "$LOGS/eval_tile_ep0.log" | head -40
echo "────────────────────────────────────"

say "다음 (GPU 안 씀):"
say "  python3 compare_froc.py --a $OUT/tile_dets_last.json --b $OUT/tile_dets_ep0.json"
say "  같은 200장으로 두 에폭을 비교한다"
