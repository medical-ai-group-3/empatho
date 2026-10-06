#!/bin/bash
# EMPATHO — 워크스테이션에서 실행. Orthanc를 Tailscale 사설망으로만 노출한다.
set -e

echo "[1/4] Docker 확인"
if ! command -v docker &> /dev/null; then
  echo "Docker가 없습니다. 설치 중..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "→ 재로그인 후 이 스크립트를 다시 실행하세요."
  exit 0
fi

echo "[2/4] Orthanc 컨테이너 기동"
docker compose up -d

echo "[3/4] Tailscale 설치"
if ! command -v tailscale &> /dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo tailscale up

echo "[4/4] 방화벽 — Tailscale 인터페이스에서만 Orthanc 포트 개방"
sudo ufw allow in on tailscale0 to any port 8042,4242 proto tcp
sudo ufw status

echo ""
echo "완료. 워크스테이션의 Tailscale IP 확인:"
tailscale ip -4
echo ""
echo "팀원 각자 기기에도 Tailscale 설치 + 같은 tailnet 로그인 필요."
echo "접속 테스트: curl -u <계정>:<비밀번호> http://<위 IP>:8042/system"
