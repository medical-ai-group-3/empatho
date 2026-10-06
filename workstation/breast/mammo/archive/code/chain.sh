#!/usr/bin/env bash
# 기준선 학습이 끝나면 -> 평가 -> 타일 학습 순으로 이어 붙인다.
#
# 왜
#   기준선이 끝나는 시각에 사람이 없으면 GPU 가 논다. 이어 붙이면 그 시간을
#   안 버린다.
#
# 중간에 멈추는 조건
#   기준선이 에폭 19까지 못 갔으면 멈춘다. 도중에 죽은 학습을 기준선이라고
#   부르면 아침에 잘못된 것과 비교하게 된다. 실패는 실패로 남겨야 한다.
#
# 안 하는 것
#   기준선을 다시 시작하지 않는다. 이미 도는 것을 기다리기만 한다.
#
# 사용
#   nohup bash chain.sh > chain.log 2>&1 &
#   tail -f chain.log

set -u
cd "$HOME/workspace/breast/mammo" || exit 1

TRAIN_LOG=det_train.log
TILE_LOG=det_tile_train.log
EVAL_LOG=eval_base.log
CKPT=det_run/checkpoints/checkpoint.pt
TILE_CFG=configs/mammo/mammo_det_tile.yaml
WANT_EPOCH=19          # max_epochs 20 -> 마지막 에폭 번호
POLL=120
MAX_WAIT=$((6 * 3600))

now() { date '+%F %T'; }
say() { echo "$(now)  $*"; }

say "이어붙이기 시작"

# ── 1. 기준선이 끝날 때까지 기다린다 ────────────────────────────────────
PID=$(pgrep -f "train.py -c configs/mammo/mammo_det.yaml" | head -1)
if [ -z "$PID" ]; then
    say "기준선 학습 프로세스가 안 보인다 — 이미 끝났다고 보고 확인으로 넘어간다"
else
    say "기준선 PID $PID 기다린다"
    WAITED=0
    while kill -0 "$PID" 2>/dev/null; do
        sleep "$POLL"
        WAITED=$((WAITED + POLL))
        if [ $((WAITED % 1800)) -lt "$POLL" ]; then
            say "대기 중 $((WAITED / 60))분   $(tail -1 $TRAIN_LOG | grep -o 'Train Epoch: \[[0-9]*\]\[[0-9]*/[0-9]*\]')"
        fi
        if [ "$WAITED" -ge "$MAX_WAIT" ]; then
            say "! $((MAX_WAIT / 3600))시간을 넘겼다 — 중단한다"
            exit 2
        fi
    done
    say "기준선 프로세스 종료"
fi

# ── 2. 끝까지 갔는지 확인한다 ───────────────────────────────────────────
LAST=$(grep -o 'Train Epoch: \[[0-9]*\]' "$TRAIN_LOG" | tail -1 | tr -dc '0-9')
say "로그의 마지막 에폭: ${LAST:-없음}"
if [ -z "$LAST" ] || [ "$LAST" -lt "$WANT_EPOCH" ]; then
    say "! 에폭 $WANT_EPOCH 에 못 미친다 — 기준선이 완주하지 못했다."
    say "  중단한다. 덜 학습된 것을 기준선으로 쓰면 비교가 무의미하다."
    tail -5 "$TRAIN_LOG"
    exit 3
fi
if [ ! -f "$CKPT" ]; then
    say "! 체크포인트가 없다: $CKPT"
    exit 3
fi
say "완주 확인 · 체크포인트 $(du -h $CKPT | cut -f1)"

# ── 3. 기준선 평가 ──────────────────────────────────────────────────────
say "기준선 평가 시작 -> $EVAL_LOG"
if ! python3 eval_det.py --save-json base_dets.json > "$EVAL_LOG" 2>&1; then
    say "! 평가가 실패했다 — 타일 학습은 시작하지 않는다"
    tail -20 "$EVAL_LOG"
    exit 4
fi
say "평가 완료"
echo "────────── FROC 요약 ──────────"
grep -E "^(mass|calcification|  ── |      [0-9])" "$EVAL_LOG" | head -40
echo "───────────────────────────────"

# ── 4. GPU 가 비었는지 확인하고 타일 학습 시작 ──────────────────────────
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
say "GPU 여유 ${FREE}MiB"
if [ "${FREE:-0}" -lt 20000 ]; then
    say "! 여유가 부족하다 — 누가 GPU 를 쓰고 있다. 타일 학습은 수동으로 시작해라"
    exit 5
fi
if [ ! -f "sam3/train/$TILE_CFG" ]; then
    say "! 타일 설정이 없다: sam3/train/$TILE_CFG"
    exit 5
fi

say "타일 학습 시작 -> $TILE_LOG"
nohup python3 -u sam3/train/train.py -c "$TILE_CFG" --use-cluster \
    > "$TILE_LOG" 2>&1 &
TPID=$!
say "타일 PID $TPID"

# ── 5. 시작 관문 — 첫 배치가 나오는지 본다 ─────────────────────────────
for i in $(seq 1 30); do
    sleep 20
    if ! kill -0 "$TPID" 2>/dev/null; then
        say "! 타일 학습이 죽었다"
        tail -30 "$TILE_LOG"
        exit 6
    fi
    if grep -q "Train Epoch" "$TILE_LOG" 2>/dev/null; then
        say "관문 통과 — 첫 배치 확인"
        grep -m1 "Train Epoch" "$TILE_LOG"
        break
    fi
done
if ! grep -q "Train Epoch" "$TILE_LOG" 2>/dev/null; then
    say "! 10분 안에 첫 배치가 안 나왔다 — 살아 있지만 일을 안 한다. 확인해라"
    tail -20 "$TILE_LOG"
    exit 6
fi

# ── 6. 조용히 멈추는 실패를 감시한다 ────────────────────────────────────
say "진행 감시 시작 (5분마다, 10회 연속 조용하면 정지 판정)"
QUIET=0
PREV=$(stat -c %s "$TILE_LOG")
while kill -0 "$TPID" 2>/dev/null; do
    sleep 300
    SIZE=$(stat -c %s "$TILE_LOG")
    UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits | head -1)
    GROW=$((SIZE - PREV)); PREV=$SIZE
    if [ "$GROW" -gt 0 ] || [ "${UTIL:-0}" -ge 20 ]; then
        QUIET=0
    else
        QUIET=$((QUIET + 1))
        say "조용함 ${QUIET}/10   로그 +${GROW}B   GPU ${UTIL}%"
        if [ "$QUIET" -ge 10 ]; then
            say "! 50분간 진행이 없다 — 정지로 판정한다. 프로세스는 살아 있다."
            tail -5 "$TILE_LOG"
            exit 7
        fi
    fi
done

say "타일 학습 종료"
tail -3 "$TILE_LOG"
say "다음: python3 eval_det_tiled.py  로 타일 모델을 평가하고 기준선과 비교해라"
