"""
CDSS 백엔드 설정.

비밀값은 .env 에서 읽는다 — SECRET_KEY 와 DB 비밀번호를 코드에 두면
git 에 올라가는 순간 재발급해야 한다. .env 는 커밋하지 않는다(.env.example 참조).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # gunicorn 은 정적 파일을 서빙하지 않는다. DEBUG=False 에서 admin CSS 를
    # 이쪽이 대신 준다. SecurityMiddleware 바로 아래여야 한다.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    # CorsMiddleware 는 CommonMiddleware 보다 위에 와야 한다 —
    # 리다이렉트가 먼저 일어나면 CORS 헤더가 붙지 않는다.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "cdss_backend.urls"
WSGI_APPLICATION = "cdss_backend.wsgi.application"

# admin 이 요구한다. admin 을 쓰는 한 지우지 말 것.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "empatho"),
        "USER": os.environ.get("DB_USER", "empatho"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}

# 검사·처방 시각을 다루므로 KST. USE_TZ=True 라 DB 에는 UTC 로 저장되고
# 표시할 때만 KST 로 변환된다.
#
# 이게 성립하려면 시각 컬럼이 timestamptz 여야 한다. timestamp without time
# zone 이면 Django 가 읽은 값이 naive 라 TIME_ZONE 으로 간주되고, 다시 저장할
# 때 UTC 로 변환돼 매번 9시간씩 밀린다. 2026-09-02 에 업무 테이블 106개 컬럼을
# 전부 timestamptz 로 바꿨다 — db/migrations/2026-09-02-timestamptz.sql.
# 새 테이블도 반드시 timestamptz 로 만들 것.
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"          # admin 정적 파일
# collectstatic 이 모으는 곳. whitenoise 가 여기서 읽어 서빙한다.
# 빌드 산출물이라 git 에 올리지 않는다(.gitignore).
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 프론트 오리진. .env 에 쉼표로 구분해 넣는다 (예: http://localhost:5173)
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # 명세서 1-1: ?page=1&page_size=20 → {count, next, previous, results}
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "PAGE_SIZE_QUERY_PARAM": "page_size",
}

# -- CELERY 
# Redis 컨테이너를 브로커로 사용. redis 는 docker 안에 있으니까 찾는다 
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

# 판독은 한 건이 오래걸림. 기본값은 제한이 없이 가지고 있어서 워크스테이션이 멈추면 워커가 영원히 돌고있다 
# soft : 예외를 던짐 = 기권으로 처리
# hard : 예외를 던졌는데 안 끝나면 그냥 kill함 
CELERY_TASK_SOFT_TIME_LIMIT = 840
CELERY_TASK_TIME_LIMIT = 900

# 일이 끝나면 큐에서 삭제, 기본값은 꺼내자마자 삭제 
# 워커가 중간에 죽으면 그 일이 전부 사라짐 
CELERY_TASK_ACKS_LATE = True