#!/usr/bin/env bash
# GPU 가 비면 예약한 작업을 순서대로 돌린다.
#
# 왜
#   GPU 를 다른 팀과 나눠 쓴다. 비는 시각을 지키고 있을 수 없고, 비었을 때
#   바로 시작하지 않으면 그 시간이 사라진다.
#
# 어떻게
#   jobs.txt 에 한 줄에 하나씩 명령을 적는다. '#' 로 시작하면 주석이다.
#   작업마다 GPU 여유를 다시 확인한다 — 중간에 다른 팀이 붙을 수 있다.
#   실패하면 멈춘다(기본). 뒤 작업이 앞 결과를 쓰는 경우가 많기 때문이다.
#
# 사용
#   nohup bash gpu_queue.sh > ../logs/queue.log 2>&1 &
#   tail -f ../logs/queue.log
#
#   bash gpu_queue.sh --jobs other.txt --need 20000 --keep-going

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOGS="$ROOT/training/logs"

JOBS="$HERE/jobs.txt"
NEED=20000            # MiB. 학습이 18GB 를 쓰므로 여유를 넉넉히 본다
POLL=300
MAX_WAIT=$((48 * 3600))
KEEP_GOING=0

while [ $# -gt 0 ]; do
    case "$1" in
        --jobs) JOBS="$2"; shift 2 ;;
        --need) NEED="$2"; shift 2 ;;
        --poll) POLL="$2"; shift 2 ;;
        --keep-going) KEEP_GOING=1; shift ;;
        *) echo "모르는 인자: $1"; exit 1 ;;
    esac
done

now() { date '+%F %T'; }
say() { echo "$(now)  $*"; }
free_mib() {
    nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1
}

cd "$HERE" || exit 1
mkdir -p "$LOGS"

if [ ! -f "$JOBS" ]; then
    say "! 작업 목록이 없다: $JOBS"
    exit 1
fi

mapfile -t LINES < <(grep -vE '^\s*(#|$)' "$JOBS")
say "예약 작업 ${#LINES[@]}건   GPU 여유 ${NEED}MiB 이상을 기다린다"
for i in "${!LINES[@]}"; do
    say "  [$((i + 1))] ${LINES[$i]}"
done

wait_gpu() {
    local w=0
    while true; do
        local f
        f=$(free_mib)
        if [ "${f:-0}" -ge "$NEED" ]; then
            say "GPU 여유 ${f}MiB — 시작한다"
            return 0
        fi
        if [ $((w % 3600)) -lt "$POLL" ]; then
            say "대기 $((w / 60))분   여유 ${f}MiB / 필요 ${NEED}MiB"
        fi
        sleep "$POLL"
        w=$((w + POLL))
        if [ "$w" -ge "$MAX_WAIT" ]; then
            say "! $((MAX_WAIT / 3600))시간을 넘겼다 — 중단"
            return 1
        fi
    done
}

OK=0
FAIL=0
for i in "${!LINES[@]}"; do
    n=$((i + 1))
    cmd="${LINES[$i]}"
    name=$(echo "$cmd" | awk '{for(j=1;j<=NF;j++) if($j ~ /\.py$|\.sh$/){print $j; exit}}')
    name=$(basename "${name:-job}" | tr -d ' ')
    log="$LOGS/queue_${n}_${name}.log"

    say ""
    say "══ [$n/${#LINES[@]}] $cmd"
    if ! wait_gpu; then
        exit 2
    fi

    say "실행 -> $log"
    start=$(date +%s)
    if bash -c "$cmd" > "$log" 2>&1; then
        el=$(( ($(date +%s) - start) / 60 ))
        say "완료 (${el}분)"
        tail -25 "$log"
        OK=$((OK + 1))
    else
        el=$(( ($(date +%s) - start) / 60 ))
        say "! 실패 (${el}분)  종료코드 $?"
        tail -30 "$log"
        FAIL=$((FAIL + 1))
        if [ "$KEEP_GOING" -eq 0 ]; then
            say "멈춘다. 뒤 작업이 이 결과를 쓸 수 있다."
            say "무시하고 계속하려면 --keep-going"
            exit 3
        fi
    fi
done

say ""
say "══ 전부 끝났다   성공 $OK · 실패 $FAIL"
