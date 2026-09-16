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
    "drf_spectacular",
    "corsheaders",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # 맨 앞에 가깝게 둔다 — 뒤쪽 미들웨어가 던지는 예외의 응답에도 trace_id 가
    # 붙어야 한다.
    "core.api.trace.TraceIdMiddleware",
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
    # 인증 주체는 auth_user 가 아니라 core.account 다 (core/api/auth.py).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.api.auth.AccountJWTAuthentication",
    ],
    # 기본은 잠금. 여는 것은 뷰가 명시한다 — 빠뜨렸을 때 열려 있는 것보다 낫다.
    "DEFAULT_PERMISSION_CLASSES": [
        "core.api.permissions.IsAuthenticatedAccount",
    ],
    # 명세서 §1-2 봉투 — 성공은 렌더러가, 실패는 예외 핸들러가 씌운다.
    "DEFAULT_RENDERER_CLASSES": [
        "core.api.envelope.EnvelopeJSONRenderer",
    ],
    "EXCEPTION_HANDLER": "core.api.envelope.api_exception_handler",
    # 명세서 §1-1: ?page=1&page_size=20 → {count, next, previous, results}
    "DEFAULT_PAGINATION_CLASS": "core.api.envelope.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# 명세서 §1-1 「직원 토큰과 환자 토큰의 스코프를 절대 섞지 않는다」.
# 스코프는 account.role 에서 유도한다 — 발급하는 쪽이 임의로 정하지 못한다.
#
# SECRET 을 따로 두는 이유 — SECRET_KEY 를 돌리면 세션·CSRF 도 같이 끊긴다.
# 토큰만 무효화하고 싶을 때가 있다.
JWT = {
    "SECRET": os.environ.get("JWT_SECRET") or SECRET_KEY,
    "ALGORITHM": "HS256",
    "ISSUER": os.environ.get("JWT_ISSUER", "empatho-cdss"),
    "ACCESS_TTL_MIN": int(os.environ.get("JWT_ACCESS_TTL_MIN", "30")),
    "REFRESH_TTL_DAYS": int(os.environ.get("JWT_REFRESH_TTL_DAYS", "14")),
}

# Go → Django 내부 콜백(명세 21장)의 서명 키. conf/gosvc.env 의 CALLBACK_SECRET
# 과 **같은 값**이어야 한다. 어긋나면 콜백이 401 로 조용히 거절된다.
# 비어 있으면 콜백을 아예 받지 않는다 — 설정 누락을 통과로 취급하지 않는다.
CALLBACK_SECRET = os.environ.get("CALLBACK_SECRET", "")
# Go 가 nonce 를 안 보내서 시간 창이 재전송을 막는 유일한 수단이다.
CALLBACK_TIMESTAMP_TOLERANCE_SEC = int(
    os.environ.get("CALLBACK_TIMESTAMP_TOLERANCE_SEC", "300"))

# 전송 티켓(명세 19-1)의 서명 키. Django 가 서명하고 Go 가 검증한다 —
# CALLBACK_SECRET 과 방향이 반대이고 **절대 같은 값이면 안 된다**.
# core/apps.py 의 시스템 검사가 같은 값을 막는다.
TICKET_KEY = os.environ.get("TICKET_KEY", "")

# purpose 별 유효기간. 읽기는 Go 가 nonce 소진을 빼서 재사용될 수 있으므로
# 짧게 잡는다 — 그게 replay 방어를 대신한다.
_TICKET_TTL_DEFAULT = {
    "tile": 900,             # 뷰어 한 세션
    "download": 120,         # 받는 즉시 끝나고 환자 자료다
    "dicom_upload": 300,
    "wsi_upload": 300,
    "derived_upload": 300,
    "report_pdf": 300,
    # 리포트 서버가 문장을 만드는 동안 열려 있어야 한다.
    # llm-proxy 의 REPORT_TIMEOUT 이 2 분이라 그보다 넉넉하게 둔다.
    "report_narrative": 300,
    # 알림 스트림을 **여는 데만** 쓴다. 연결은 그 뒤로 계속 열려 있고
    # 티켓은 붙을 때 한 번만 검사된다. 끊겨 다시 붙으면 새로 받아야 한다 —
    # notify 는 nonce 를 소진한다(Go 의 NewVerifier 에 reusable 이 없다).
    "notify": 300,
}
TICKET_TTL_SEC = {
    p: int(os.environ.get("TICKET_TTL_%s" % p.upper(), d))
    for p, d in _TICKET_TTL_DEFAULT.items()
}

# 업로드 상한. 0 이면 Go 가 제한 없이 받는다 — 반드시 값을 넣는다.
_TICKET_MAX_BYTES_DEFAULT = {
    "dicom_upload": 200 * 1024 ** 2,
    "wsi_upload": 8 * 1024 ** 3,        # WSI 는 수 GB 다
    "derived_upload": 512 * 1024 ** 2,
    "report_pdf": 32 * 1024 ** 2,
    "download": 0,                       # 읽기라 상한이 의미 없다
    "tile": 0,
}
TICKET_MAX_BYTES = {
    p: int(os.environ.get("TICKET_MAX_BYTES_%s" % p.upper(), d))
    for p, d in _TICKET_MAX_BYTES_DEFAULT.items()
}

SPECTACULAR_SETTINGS = {
    "TITLE": "EMPATHO CDSS API",
    "DESCRIPTION": "유방암 검진 CDSS — 공통 규약은 CDSS_API_명세서_v3 §1 을 따른다.",
    # API 판이다. 배포 판(빌드 버전)을 넣지 않는다 — 인증 없이 열려 있어서
    # 밖에서 어느 판이 떠 있는지 알면 취약점 탐색의 단서가 된다.
    "VERSION": "v1",
    "SERVE_INCLUDE_SCHEMA": False,      # 스키마 자신을 문서에 싣지 않는다
    "SCHEMA_PATH_PREFIX": "/api/v1",
    # 응답에 봉투가 씌워지므로 스키마도 같이 감싼다. 안 하면 문서와 실제가 다르다.
    "POSTPROCESSING_HOOKS": ["core.api.schema.wrap_responses"],
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