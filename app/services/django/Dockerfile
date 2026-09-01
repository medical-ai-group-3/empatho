# CDSS 백엔드 — compose.app.yml 의 web 서비스가 이 이미지를 쓴다.
FROM python:3.12-slim

# .pyc 를 남기지 않고 로그를 버퍼 없이 흘린다.
# 버퍼링을 두면 docker logs 에 늦게 떠서 배포 실패를 늦게 안다.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# requirements 를 먼저 넣어야 코드만 고쳤을 때 설치 레이어가 캐시된다.
# psycopg2-binary 는 wheel 로 들어오므로 컴파일러를 깔 필요가 없다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# whitenoise 가 서빙할 admin 정적 파일을 모아 둔다.
# DB 에 붙지 않으므로 빌드 단계에서 돌아간다 — postgres 가 없어도 된다.
RUN python manage.py collectstatic --noinput

# 루트로 돌리지 않는다. collectstatic 이 만든 staticfiles 도 같이 넘긴다.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

# gunicorn 은 정적 파일을 서빙하지 않는다 — 그건 whitenoise 가 맡는다(settings.py).
# 접근 로그를 stdout 으로 보내야 docker logs 에 남는다.
CMD ["gunicorn", "cdss_backend.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--access-logfile", "-"]
