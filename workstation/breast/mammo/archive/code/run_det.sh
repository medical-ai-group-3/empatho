#!/usr/bin/env bash
# SAM3 검출 학습 — GPU 여유를 기다려 시작하고, 진행을 계속 감시한다.
#
# 왜 감시가 필요한가
#   지난 실행은 시작에는 성공했지만 첫 배치에서 교착에 빠졌다.
#   데이터 로더 작업자가 죽었는데 본 프로세스는 계속 기다려서,
#   프로세스는 살아 있고 GPU 메모리도 잡은 채 8시간을 아무것도 안 했다.
#   '살아 있다'와 '일하고 있다'는 다르다. 둘 다 봐야 한다.
#
# 무엇을 보나
#   로그가 자라는가  +  GPU 사용률이 있는가
#   둘 다 없는 상태가 STALL 분 이어지면 정지로 판정하고 알린다.
#
# 사용
#   bash run_det.sh                  # 20GB 나면 시작, 10분 정지 시 경고
#   bash run_det.sh 24000            # 24GB 이상일 때 시작
#   bash run_det.sh 20000 300 15     # 확인주기 300초, 정지판정 15회
#
# 중단
#   pkill -f "sam3/train/train.py"

set -u

NEED=${1:-20000}          # 시작에 필요한 여유 메모리 (MiB)
EVERY=${2:-300}           # 확인 주기 (초)
STALL=${3:-10}            # 이 횟수만큼 연속으로 조용하면 정지로 본다
CFG=configs/mammo/mammo_det.yaml
LOG=det_train.log

cd "$HOME/workspace/breast/mammo" || exit 1

if [ ! -f "sam3/train/$CFG" ]; then
  echo "설정이 없다: sam3/train/$CFG"
  echo "  python3 make_train_cfg.py --drop-missing --go --out sam3/train/$CFG"
  exit 1
fi

gpu_free() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1; }
gpu_util() { nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1; }
now()      { date '+%F %T'; }

export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

echo "$(now)  대기 시작 — 여유 ${NEED}MiB 이상을 기다린다"
while true; do
  FREE=$(gpu_free)
  if [ -z "$FREE" ]; then
    echo "$(now)  nvidia-smi 실패 — ${EVERY}초 후 재시도"; sleep "$EVERY"; continue
  fi
  [ "$FREE" -ge "$NEED" ] && { echo "$(now)  여유 ${FREE}MiB — 시작한다"; break; }
  echo "$(now)  여유 ${FREE}MiB / 필요 ${NEED}MiB — 대기"
  sleep "$EVERY"
done

echo "$(now)  학습 시작  로그 $LOG"
nohup python3 -u sam3/train/train.py -c "$CFG" --use-cluster 0 --num-gpus 1 \
  > "$LOG" 2>&1 &
PID=$!
echo "PID $PID"

# ── 1단계: 시작 관문 (2분) ────────────────────────────────────────────────
echo
echo "── 시작 관문 ──"
GATE=0
for _ in $(seq 1 24); do
  sleep 5
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "$(now)  프로세스가 종료됐다 — 로그 끝부분:"; tail -30 "$LOG"; exit 1
  fi
  if grep -qi "Trainable parameters" "$LOG" 2>/dev/null; then
    grep -i "Loading pretrained checkpoint\|Trainable parameters\|Non-Trainable" "$LOG" \
      | sed 's/^/  /'
    GATE=1; break
  fi
done
[ "$GATE" = 1 ] && echo "$(now)  관문 통과" || echo "$(now)  관문 줄이 아직 안 나왔다 (계속 지켜본다)"

# ── 2단계: 진행 감시 ─────────────────────────────────────────────────────
#   '살아 있다'로는 부족하다. 로그가 자라거나 GPU 가 일해야 진행이다.
echo
echo "── 진행 감시 (${EVERY}초마다, ${STALL}회 연속 조용하면 정지 판정) ──"
LAST=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
QUIET=0
MOVED=0

while true; do
  sleep "$EVERY"

  if ! kill -0 "$PID" 2>/dev/null; then
    echo "$(now)  프로세스 종료. 로그 끝부분:"
    tail -25 "$LOG"
    if ls det_run/checkpoints/* >/dev/null 2>&1; then
      echo "$(now)  체크포인트가 있다 — 최소 한 번은 저장됐다:"
      ls -lh det_run/checkpoints/ | sed 's/^/  /'
    else
      echo "$(now)  체크포인트 없음"
    fi
    exit 0
  fi

  SIZE=$(stat -c %s "$LOG" 2>/dev/null || echo 0)
  UTIL=$(gpu_util); UTIL=${UTIL:-0}
  GROW=$((SIZE - LAST))
  LAST=$SIZE

  if [ "$GROW" -gt 0 ] || [ "$UTIL" -ge 20 ]; then
    QUIET=0; MOVED=1
    echo "$(now)  진행 중  로그 +${GROW}B  GPU ${UTIL}%"
    tail -1 "$LOG" | sed 's/^/      /'
  else
    QUIET=$((QUIET + 1))
    echo "$(now)  조용함 ${QUIET}/${STALL}  (로그 +0B, GPU ${UTIL}%)"
    if [ "$QUIET" -ge "$STALL" ]; then
      echo
      echo "$(now)  ! 정지로 판정한다."
      echo "  프로세스는 살아 있지만 로그도 안 자라고 GPU 도 안 쓴다."
      echo "  지난번과 같은 데이터 로더 교착일 수 있다."
      echo "  로그 끝부분:"
      tail -20 "$LOG" | sed 's/^/    /'
      echo
      echo "  멈추려면:  pkill -f \"sam3/train/train.py\""
      exit 2
    fi
  fi
done
