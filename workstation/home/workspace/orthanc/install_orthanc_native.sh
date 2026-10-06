#!/bin/bash
# EMPATHO — systemd/Docker/TUN이 없는 컨테이너 환경용 Orthanc 네이티브 설치
set -e

echo "[1/5] Orthanc + DICOMweb 플러그인 설치"
sudo apt-get update -qq
sudo apt-get install -y orthanc orthanc-dicomweb

echo "[2/5] 기본 서비스 자동기동 시도 정지 (systemd 없어서 실패하는 게 정상)"
sudo systemctl stop orthanc 2>/dev/null || true
sudo systemctl disable orthanc 2>/dev/null || true

echo "[3/5] 우리 설정 파일로 교체"
sudo cp /etc/orthanc/orthanc.json /etc/orthanc/orthanc.json.bak
sudo cp "$(dirname "$0")/orthanc.json" /etc/orthanc/orthanc.json

echo "[4/5] 로그·데이터 디렉터리 권한 확인"
sudo mkdir -p /var/lib/orthanc/db
sudo chown -R orthanc:orthanc /var/lib/orthanc/db 2>/dev/null || true

echo "[5/5] Orthanc 수동 기동 (systemd 없으므로 nohup 백그라운드 실행)"
LOG_DIR="$(dirname "$0")/logs"
mkdir -p "$LOG_DIR"
sudo -u orthanc nohup Orthanc /etc/orthanc/orthanc.json > "$LOG_DIR/orthanc.log" 2>&1 &
sleep 2

echo ""
echo "orthanc.json의 RegisteredUsers 계정/비번을 실제 값으로 바꾼 뒤 이 스크립트를 다시 실행하거나,"
echo "start_orthanc.sh 로 기동 확인하십시오 (계정/비번을 물어봅니다)."
echo "로그: tail -f $LOG_DIR/orthanc.log"
