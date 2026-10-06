#!/usr/bin/env bash
# GPU 가 빌 때까지 기다렸다가 아무 명령이나 돌린다.
#
# queue_e2e.sh 를 일반화한 것이다. GPU 를 다른 사람과 같이 쓰므로 사람이
# nvidia-smi 를 들여다보고 있을 수 없고, 여러 실험을 순서대로 걸어 둬야 한다.
#
# 쓰는 법
#   bash queue_gpu.sh <라벨> <작업디렉터리> -- <명령...>
#
#   nohup 으로 걸면 접속을 끊어도 살아 있다.
#     cd ~/workspace/breast/mammo
#     nohup bash training/code/queue_gpu.sh val training/code -- \
#         python eval_mammo_det.py --split val \
#             --save-json ../../archive/outputs/tile_dets_val.json \
#         > docs/queue_val.log 2>&1 &
#
#   여러 개를 순서대로 돌리려면 한 줄에 && 로 잇지 말고 각각 nohup 으로
#   걸되 **하나씩** 건다. 동시에 걸면 서로 OOM 을 낸다.
#
#   진행 보기   tail -f docs/queue_val.log
#   그만두기    pkill -f "queue_gpu.sh val"
#
# 조절 (앞에 붙인다)
#   MIN_FREE_MB=8000 nohup bash ...
#     기본 12000. 이만큼 비어야 시작한다. 모자라면 모델 올리다 죽어서
#     그때까지 쓴 시간이 날아간다.
#   MAX_WAIT_MIN  기본 720 (12시간)
#   POLL_SEC      기본 60

set -u

MIN_FREE_MB="${MIN_FREE_MB:-12000}"
MAX_WAIT_MIN="${MAX_WAIT_MIN:-720}"
POLL_SEC="${POLL_SEC:-60}"

if [ "$#" -lt 3 ]; then
    echo "쓰는 법: bash queue_gpu.sh <라벨> <작업디렉터리> -- <명령...>"
    exit 2
fi
LABEL="$1"; shift
WORKDIR="$1"; shift
if [ "$1" != "--" ]; then
    echo "세 번째 인자는 -- 여야 한다. 받은 것: $1"
    exit 2
fi
shift
if [ "$#" -lt 1 ]; then
    echo "-- 뒤에 돌릴 명령이 없다."
    exit 2
fi
if [ ! -d "$WORKDIR" ]; then
    echo "작업디렉터리가 없다: $WORKDIR"
    exit 2
fi

stamp() { date "+%Y-%m-%d %H:%M:%S"; }

best_gpu() {
    nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null \
        | sort -t, -k2 -n -r | head -1 | tr -d ' '
}

echo "=============================================================="
echo " GPU 예약 실행 — $LABEL"
echo "   필요 여유 ${MIN_FREE_MB}MB · 최대 대기 ${MAX_WAIT_MIN}분"
echo "   작업 디렉터리 $WORKDIR"
echo "   명령 $*"
echo "=============================================================="

waited=0
idx=""
while :; do
    row="$(best_gpu)"
    if [ -z "$row" ]; then
        echo "[$(stamp)] nvidia-smi 를 못 읽는다. 그냥 진행한다."
        break
    fi
    idx="${row%%,*}"
    free="${row##*,}"
    if [ "$free" -ge "$MIN_FREE_MB" ]; then
        echo "[$(stamp)] GPU $idx 여유 ${free}MB — 시작한다"
        break
    fi
    if [ "$waited" -ge "$MAX_WAIT_MIN" ]; then
        echo "[$(stamp)] ${MAX_WAIT_MIN}분 기다렸는데 안 빈다 (최대 여유 ${free}MB). 그만둔다."
        exit 1
    fi
    # 몇 분마다 한 번만 찍는다. 매분 찍으면 기록이 쓸데없이 길어진다.
    if [ $(( waited % 10 )) -eq 0 ]; then
        echo "[$(stamp)] 대기 ${waited}분 · 최대 여유 ${free}MB (필요 ${MIN_FREE_MB}MB)"
    fi
    sleep "$POLL_SEC"
    waited=$(( waited + (POLL_SEC + 59) / 60 ))
done

start=$(date +%s)
(
    cd "$WORKDIR" || exit 1
    if [ -n "$idx" ]; then export CUDA_VISIBLE_DEVICES="$idx"; fi
    # 공유 GPU 에서 남은 자리가 조각나 있으면 총량이 충분해도 큰 덩어리
    # 하나를 못 잡는다. OOM 메시지가 직접 권하는 설정이다.
    export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
    "$@"
)
rc=$?
took=$(( ($(date +%s) - start) / 60 ))
if [ "$rc" -eq 0 ]; then
    echo "[$(stamp)] $LABEL 끝남 (${took}분)"
else
    echo "[$(stamp)] ! $LABEL 실패 (종료코드 $rc, ${took}분)"
fi
exit "$rc"
