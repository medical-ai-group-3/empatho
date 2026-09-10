#!/bin/sh
set -e

# 바인드 마운트는 Windows 쪽 권한이 그대로 와서 ssh 가 키를 거부한다
# (Permissions 0777 are too open). 복사해서 좁힌다.
cp /ws/key /tmp/k
chmod 600 /tmp/k

# -L 앞의 0.0.0.0 이 없으면 이 컨테이너 안에서만 열려서
# web·llm-proxy 가 못 붙는다.
#
# ServerAliveInterval 이 없으면 죽은 연결을 오래 붙들고 있는다.
# 컨테이너는 살아 있는데 터널만 끊긴 상태가 되어 자동 복구가 안 걸린다.
#
#   8001   추론 FastAPI  — Celery 워커가 판독을 부른다
#   8002   리포트 서버   — 소견문
exec ssh -N -i /tmp/k \
  -o UserKnownHostsFile=/ws/known_hosts \
  -o StrictHostKeyChecking=yes \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=20 \
  -o ServerAliveCountMax=3 \
  -L 0.0.0.0:8001:127.0.0.1:8001 \
  -L 0.0.0.0:8002:127.0.0.1:8002 \
  -p "${WS_PORT}" "${WS_USER}@${WS_HOST}"
