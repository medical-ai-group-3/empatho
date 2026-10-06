#!/bin/bash
# 컨테이너 재시작되면 Orthanc 프로세스도 죽어있을 것 — 이걸로 다시 띄운다.
# 로그는 wsuser 소유 디렉터리에 쓴다 (/var/log는 sudo -u orthanc 붙여도 리다이렉트는 현재 셸 권한이라 permission denied 남)

LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"

if pgrep -f "Orthanc /etc/orthanc/orthanc.json" > /dev/null; then
  echo "이미 실행 중입니다."
  exit 0
fi

sudo -u orthanc nohup Orthanc /etc/orthanc/orthanc.json > "$LOG_DIR/orthanc.log" 2>&1 &
sleep 2

read -r -p "확인용 계정 입력: " ORTHANC_USER
read -r -s -p "비밀번호 입력: " ORTHANC_PW
echo ""

curl -s -u "$ORTHANC_USER:$ORTHANC_PW" http://localhost:8042/system > /dev/null \
  && echo "기동 성공" \
  || echo "실패 — tail -f $LOG_DIR/orthanc.log 확인"
