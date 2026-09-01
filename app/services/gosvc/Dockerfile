# 세 실행파일을 한 이미지에 담고 실행할 때 고른다.
# 따로 만들면 같은 의존성을 세 번 받는다.
FROM golang:1.24-alpine AS build
WORKDIR /src
# 의존성만 먼저 받는다 — 코드만 고쳤을 때 이 층을 다시 안 받는다
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# CGO 를 끈다. alpine 에 붙일 C 라이브러리가 없고, 정적으로 나와야
# scratch 에 가까운 바닥 이미지에 그냥 얹을 수 있다.
ENV CGO_ENABLED=0
RUN go build -trimpath -ldflags="-s -w" -o /out/ ./cmd/...

FROM alpine:3.20
# HTTPS 로 Django·Garage 를 부르므로 루트 인증서가 필요하다.
# 없으면 x509: certificate signed by unknown authority 로 콜백이 전부 죽는다.
RUN apk add --no-cache ca-certificates tzdata && \
    adduser -D -u 10001 gosvc && \
    mkdir -p /var/tmp/gw-spool && chown gosvc /var/tmp/gw-spool
COPY --from=build /out/ /usr/local/bin/
USER gosvc
ENV TZ=Asia/Seoul
# 실행할 것은 compose 에서 고른다: file-gateway · llm-proxy · notify
ENTRYPOINT ["/usr/local/bin/file-gateway"]
