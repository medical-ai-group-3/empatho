#!/usr/bin/env bash
# GPU 가 빌 때까지 기다렸다가 eval_end2end 를 돌린다.
#
# 왜 필요한가
#   GPU 를 다른 사람과 같이 쓴다. 지금 31.36GB 중 2.3MB 만 남아 있어 모델을
#   올리는 단계에서 죽는다. 사람이 nvidia-smi 를 들여다보고 있을 수는 없다.
#
# 어떻게 쓰나  (nohup 으로 걸어 두면 접속을 끊어도 살아 있다)
#   cd ~/workspace/breast/mammo
#   nohup bash training/code/queue_e2e.sh \
#       archive/outputs/tile_dets_wbf03_tissue_t30.json \
#       > docs/queue_e2e.log 2>&1 &
#
#   여러 개를 주면 앞에서부터 차례로 돌린다. 매번 GPU 가 비기를 다시 기다린다.
#
#   진행 보기   tail -f docs/queue_e2e.log
#   결과        docs/e2e_<파일이름>.txt
#   그만두기    kill %1     (또는 pkill -f queue_e2e.sh)
#
# 조절
#   MIN_FREE_MB   이만큼 비어야 시작한다 (기본 12000)
#                 서술어 백본이 840M 이라 올리는 데만 3GB 대고, 여유가 없으면
#                 중간에 죽어서 그때까지 쓴 시간이 날아간다. 넉넉히 잡는다.
#   MAX_WAIT_MIN  이만큼 기다려도 안 비면 포기한다 (기본 720 = 12시간)
#   POLL_SEC      확인 간격 (기본 60)

set -u

MIN_FREE_MB="${MIN_FREE_MB:-12000}"
MAX_WAIT_MIN="${MAX_WAIT_MIN:-720}"
POLL_SEC="${POLL_SEC:-60}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"   # …/mammo
CODE="$ROOT/training/code"
DOCS="$ROOT/docs"
mkdir -p "$DOCS"

if [ "$#" -lt 1 ]; then
    echo "쓰는 법: bash training/code/queue_e2e.sh <검출.json> [<검출.json> …]"
    exit 2
fi

stamp() { date "+%Y-%m-%d %H:%M:%S"; }

# 가장 많이 비어 있는 GPU 번호와 여유(MB)를 돌려준다.
best_gpu() {
    nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits 2>/dev/null \
        | sort -t, -k2 -n -r | head -1 | tr -d ' '
}

wait_gpu() {
    local waited=0
    while :; do
        local row idx free
        row="$(best_gpu)"
        if [ -z "$row" ]; then
            echo "[$(stamp)] nvidia-smi 를 못 읽는다. 그냥 진행한다."
            echo ""
            return 0
        fi
        idx="${row%%,*}"
        free="${row##*,}"
        if [ "$free" -ge "$MIN_FREE_MB" ]; then
            echo "[$(stamp)] GPU $idx 여유 ${free}MB — 시작한다" >&2
            echo "$idx"
            return 0
        fi
        if [ "$waited" -ge "$MAX_WAIT_MIN" ]; then
            echo "[$(stamp)] ${MAX_WAIT_MIN}분 기다렸는데 안 빈다 (최대 여유 ${free}MB). 그만둔다." >&2
            return 1
        fi
        # 몇 분마다 한 번만 찍는다. 매분 찍으면 기록이 쓸데없이 길어진다.
        if [ $(( waited % 10 )) -eq 0 ]; then
            echo "[$(stamp)] 대기 ${waited}분 · 최대 여유 ${free}MB (필요 ${MIN_FREE_MB}MB)" >&2
        fi
        sleep "$POLL_SEC"
        waited=$(( waited + (POLL_SEC + 59) / 60 ))
    done
}

echo "=============================================================="
echo " eval_end2end 예약 실행"
echo "   필요 여유  ${MIN_FREE_MB}MB · 최대 대기 ${MAX_WAIT_MIN}분 · 확인 ${POLL_SEC}초"
echo "   대상 $# 개"
echo "=============================================================="

rc_all=0
for det in "$@"; do
    # 상대경로를 지금 굳힌다. eval_end2end 는 training/code 에서 돌려야
    # crop_rule.json 을 찾는다 — 거기서 상대경로는 다른 곳을 가리킨다.
    if [ ! -f "$det" ]; then
        echo "[$(stamp)] ! 없는 파일: $det — 건너뛴다"
        rc_all=1
        continue
    fi
    abs="$(cd "$(dirname "$det")" && pwd)/$(basename "$det")"
    name="$(basename "$det" .json)"
    log="$DOCS/e2e_${name}.txt"

    echo ""
    echo "--------------------------------------------------------------"
    echo "[$(stamp)] $name"
    if ! idx="$(wait_gpu)"; then
        rc_all=1
        break
    fi

    start=$(date +%s)
    (
        cd "$CODE" || exit 1
        if [ -n "$idx" ]; then export CUDA_VISIBLE_DEVICES="$idx"; fi
        export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
        python eval_end2end.py --dets "$abs"
    ) > "$log" 2>&1
    rc=$?
    took=$(( ($(date +%s) - start) / 60 ))

    if [ "$rc" -eq 0 ]; then
        echo "[$(stamp)] 끝남 (${took}분) -> $log"
        # 끝단 수치만 뽑아 여기에도 남긴다. 기록 파일을 안 열어도 보이게.
        grep -E "합계|미세석회|종괴" "$log" | tail -12
    else
        echo "[$(stamp)] ! 실패 (종료코드 $rc, ${took}분) -> $log"
        tail -15 "$log"
        rc_all=1
    fi
done

echo ""
echo "[$(stamp)] 전부 끝났다 (종료코드 $rc_all)"
exit "$rc_all"
