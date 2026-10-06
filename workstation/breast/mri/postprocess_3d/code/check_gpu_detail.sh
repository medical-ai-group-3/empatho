#!/usr/bin/env bash
# GPU를 정확히 누가/무엇이 쓰고 있는지 자세히 확인

echo "===================================================================="
echo "1. 기본 요약"
echo "===================================================================="
nvidia-smi --query-gpu=memory.used,memory.total,memory.free,utilization.gpu,temperature.gpu,power.draw --format=csv,noheader

echo ""
echo "===================================================================="
echo "2. 프로세스별 사용량 (PID, 프로세스명, 사용 메모리)"
echo "===================================================================="
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null
if [ $? -ne 0 ] || [ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)" ]; then
    echo "(조회 권한 없음 또는 실행 중인 GPU 프로세스 없음)"
fi

echo ""
echo "===================================================================="
echo "3. 각 프로세스가 누구(어느 사용자) 소유인지"
echo "===================================================================="
PIDS=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null)
if [ -z "$PIDS" ]; then
    echo "(확인할 프로세스 없음)"
else
    for pid in $PIDS; do
        if [ -d "/proc/$pid" ]; then
            owner=$(ps -o user= -p "$pid" 2>/dev/null)
            cmd=$(ps -o cmd= -p "$pid" 2>/dev/null | cut -c1-100)
            start=$(ps -o lstart= -p "$pid" 2>/dev/null)
            echo "PID $pid"
            echo "  소유자: $owner"
            echo "  명령어: $cmd"
            echo "  시작시각: $start"
            echo ""
        else
            echo "PID $pid : 이미 종료됨(권한 문제로 nvidia-smi에만 남아있을 수 있음)"
        fi
    done
fi

echo "===================================================================="
echo "4. nvidia-smi 전체 화면 (표 형태, 참고용)"
echo "===================================================================="
nvidia-smi
