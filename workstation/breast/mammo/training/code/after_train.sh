#!/usr/bin/env bash
# 타일 학습이 끝나면 평가까지 이어서 돌린다.
#
# 왜
#   학습이 6.6시간이라 끝나는 시각에 사람이 없다. 이어 붙이면 아침에
#   결과가 나와 있다.
#
# chain.sh 와 무엇이 다른가
#   chain.sh 는 기준선(전체 미세조정) 흐름이었고 그 역할은 끝났다.
#   이쪽은 통합 구조(동결 + LoRA)용이다. 평가기도 다르다.
#
# 중간에 멈추는 조건
#   학습이 마지막 에폭까지 못 갔으면 멈춘다. 덜 학습된 것을 평가해서
#   기준선과 비교하면 잘못된 결론이 나온다.
#
# 사용
#   nohup bash after_train.sh > after_train.log 2>&1 &
#   tail -f after_train.log

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"          # .../breast/mammo
LOGS="$ROOT/training/logs"
CKPT="$ROOT/training/ckpt"
WANT_EPOCH=5                                # --epochs 6 이면 마지막은 5
POLL=180
MAX_WAIT=$((10 * 3600))

now() { date '+%F %T'; }
say() { echo "$(now)  $*"; }

cd "$HERE" || exit 1
say "이어붙이기 시작   ROOT=$ROOT"

# ── 1. 학습이 끝날 때까지 기다린다 ──────────────────────────────────────
PID=$(pgrep -f "train_mammo_det.py" | head -1)
if [ -z "$PID" ]; then
    say "학습 프로세스가 안 보인다 — 이미 끝났다고 보고 확인으로 넘어간다"
else
    say "학습 PID $PID 기다린다"
    W=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep "$POLL"
        W=$((W + POLL))
        if [ $((W % 1800)) -lt "$POLL" ]; then
            say "대기 $((W / 60))분   $(grep -o '에폭 [0-9]* \[ *[0-9]*/[0-9]*\]' "$LOGS/latest.log" | tail -1)"
        fi
        if [ "$W" -ge "$MAX_WAIT" ]; then
            say "! $((MAX_WAIT / 3600))시간을 넘겼다 — 중단"
            exit 2
        fi
    done
    say "학습 프로세스 종료"
fi

# ── 2. 끝까지 갔는지 확인 ───────────────────────────────────────────────
LAST=$(grep -o '^■ 에폭 [0-9]*' "$LOGS/latest.log" | tail -1 | tr -dc '0-9')
say "마지막으로 끝난 에폭: ${LAST:-없음}"
if [ -z "$LAST" ] || [ "$LAST" -lt "$WANT_EPOCH" ]; then
    say "! 에폭 $WANT_EPOCH 에 못 미친다 — 완주하지 못했다."
    say "  중단한다. 덜 학습된 것을 기준선과 비교하면 결론이 틀어진다."
    tail -5 "$LOGS/latest.log"
    exit 3
fi
for f in best_lora.pt last_lora.pt; do
    if [ ! -f "$CKPT/$f" ]; then
        say "! 가중치가 없다: $CKPT/$f"
        exit 3
    fi
    say "확인  $f  $(du -h "$CKPT/$f" | cut -f1)"
done

# ── 3. 구조 확인부터 (3장) ──────────────────────────────────────────────
say "평가기 구조 확인 (3장)"
if ! python3 eval_mammo_det.py --check > "$LOGS/eval_check.log" 2>&1; then
    say "! 구조 확인 실패 — 전체 평가는 돌리지 않는다"
    tail -25 "$LOGS/eval_check.log"
    exit 4
fi
grep -E "합치기 전|유방|pred_boxes" "$LOGS/eval_check.log" | head -10

# ── 4. 전체 평가 ────────────────────────────────────────────────────────
say "전체 평가 시작 -> $LOGS/eval_tile.log"
if ! python3 eval_mammo_det.py --save-json "$ROOT/archive/outputs/tile_dets.json" \
        > "$LOGS/eval_tile.log" 2>&1; then
    say "! 평가 실패"
    tail -25 "$LOGS/eval_tile.log"
    exit 5
fi
say "평가 완료"
echo "────────── FROC ──────────"
grep -E "^(mass|calcification)|── |^      [0-9]" "$LOGS/eval_tile.log" | head -40
echo "──────────────────────────"

say "다음: python3 eval_map.py --ann <타일 val.json> --dets archive/outputs/tile_dets.json"
say "  그리고 기준선과 나란히 놓아라 — 종괴 57.3% · 석회 18.6% (1FP · 중심 명중)"
