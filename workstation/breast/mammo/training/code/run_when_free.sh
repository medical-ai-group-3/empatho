#!/usr/bin/env bash
# GPU 에 자리가 날 때까지 기다렸다 명령을 돌린다.
#
# 왜 필요한가
#   GPU 를 다른 사람과 같이 쓴다. eval_vindr 이 02:40 에 OOM 으로 죽었는데
#   그때 우리가 쓰던 건 4.43GB 뿐이었다 — 31.36GB 중 936MB 만 남아 있었고
#   나머지는 다른 작업이 쓰고 있었다. 우리 코드 문제가 아니다.
#
#   자리가 없을 때 바로 죽는 대신 기다렸다 시작한다. 밤에 걸어두면
#   상대 작업이 끝나는 순간 알아서 돈다.
#
# 쓰는 법
#   ./run_when_free.sh 8 python3 -u eval_vindr.py --save-json ../../archive/outputs/vindr_dets.json
#   nohup ./run_when_free.sh 8 python3 -u eval_vindr.py > ../logs/eval_vindr.log 2>&1 &
#
#   첫 인자가 필요한 여유(GB). 우리 추론은 6GB 상주 + 순전파 여유가 필요해서
#   8 정도가 적당하다. 나머지 인자가 실행할 명령이다.
#
# 남의 작업을 죽이지 않는다. 기다리기만 한다.

set -u

NEED_GB="${1:?첫 인자로 필요한 여유 GB 를 줘라  (예: 8)}"
shift
[ $# -gt 0 ] || { echo "실행할 명령이 없다"; exit 2; }

INTERVAL="${INTERVAL:-60}"      # 몇 초마다 볼까
MAX_WAIT="${MAX_WAIT:-21600}"   # 최대 대기(초). 기본 6시간

free_mb() {
  nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null \
    | head -1 | tr -d ' '
}

command -v nvidia-smi >/dev/null || { echo "nvidia-smi 가 없다"; exit 3; }

need_mb=$(( NEED_GB * 1024 ))
waited=0

echo "필요한 여유 ${NEED_GB}GB (${need_mb}MB) · ${INTERVAL}초마다 확인 · 최대 $((MAX_WAIT/3600))시간"
while :; do
  now=$(free_mb)
  if [ -z "$now" ]; then
    echo "nvidia-smi 를 못 읽었다. ${INTERVAL}초 뒤 다시."
  elif [ "$now" -ge "$need_mb" ]; then
    echo "$(date '+%H:%M:%S')  여유 $((now/1024))GB — 시작한다"
    break
  else
    # 누가 쓰고 있는지 같이 찍는다. 내 작업이면 내가 정리하면 되고,
    # 남의 작업이면 기다리는 수밖에 없다.
    printf '%s  여유 %sMB / 필요 %sMB — 대기 %d분\n' \
      "$(date '+%H:%M:%S')" "$now" "$need_mb" $((waited/60))
    if [ $((waited % 600)) -eq 0 ]; then
      nvidia-smi --query-compute-apps=pid,used_memory \
                 --format=csv,noheader 2>/dev/null \
        | sed 's/^/    쓰는 중: /'
    fi
  fi
  sleep "$INTERVAL"
  waited=$(( waited + INTERVAL ))
  if [ "$waited" -ge "$MAX_WAIT" ]; then
    echo "$((MAX_WAIT/3600))시간을 기다렸는데 자리가 안 났다. 그만둔다."
    exit 4
  fi
done

# 조각화 완화 — OOM 메시지가 직접 권하는 설정이다
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
exec "$@"
