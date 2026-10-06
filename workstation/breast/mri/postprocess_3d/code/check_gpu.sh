#!/usr/bin/env bash
# GPU 여유 확인 - 배치 스모크테스트나 학습 시작 전에 먼저 돌릴 것

echo "===================================================================="
echo "GPU 상태"
echo "===================================================================="
nvidia-smi --query-gpu=memory.used,memory.total,memory.free,utilization.gpu --format=csv,noheader,nounits | \
while IFS=',' read -r used total free util; do
    used=$(echo $used | xargs)
    total=$(echo $total | xargs)
    free=$(echo $free | xargs)
    util=$(echo $util | xargs)
    pct=$((used * 100 / total))
    echo "사용중: ${used}MB / ${total}MB  (${pct}%)"
    echo "여유:   ${free}MB"
    echo "사용률: ${util}%"
    echo ""
    if [ "$free" -gt 20000 ]; then
        echo "판정: 여유 충분 (batch=2 시도 가능)"
    elif [ "$free" -gt 10000 ]; then
        echo "판정: 보통 (batch=1 권장)"
    else
        echo "판정: 부족 - 지금은 대기 권장"
    fi
done

echo ""
echo "===================================================================="
echo "실행 중인 프로세스"
echo "===================================================================="
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null || echo "(조회 권한 없음 또는 실행 중 프로세스 없음)"
