# 워크스테이션(추론 서버)으로 나가는 SSH 터널.
#
# 추론·리포트·Ollama 는 워크스테이션에서 127.0.0.1 로만 열려 있다. 앱 서버가
# 그것을 부르려면 SSH 로 들어가 포워딩을 받아야 한다.
#
# 2026-09-09: 이 이미지는 09-02 에 만들어졌지만 Dockerfile 이 저장소에 없어
# 고아 컨테이너로 남아 있었다. docker compose up --remove-orphans 한 번이면
# 사라지고 다시 만들 방법도 없는 상태였다. 그때 함께 11434(Ollama)를 연다.
FROM alpine:3.20

RUN apk add --no-cache openssh-client

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
