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
    # "django.contrib.admin" 대신이다. admin.site 를 우리 것으로 바꿔
    # 제목 · 색 · 사이드바 묶음을 준다 (core/adminsite.py).
    # 사이드바는 base_site.html 에 넣는다 — 그 한 장만 덮는다.
    "core.adminsite.EmpathoAdminConfig",
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
        # ⚠ **DIRS 가 APP_DIRS 보다 먼저 찾아진다.** core 가 INSTALLED_APPS
        #   에서 admin 앱보다 아래라, 여기 없으면 admin/base_site.html 을
        #   Django 것이 먼저 잡아 사이드바와 CSS 가 안 붙는다.
        "DIRS": [BASE_DIR / "core" / "templates"],
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

# DB 에는 UTC 로 저장되고 표시할 때만 KST 로 바뀐다.
# ⚠ 시각 컬럼은 **반드시 timestamptz** 여야 한다. 아니면 저장할 때마다 9시간씩
#   밀린다 — 2026-09-02 에 106개 컬럼을 고쳤다(db/migrations/2026-09-02-timestamptz.sql).
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

# ── nginx 뒤에서 HTTPS 를 쓸 때 ────────────────────────────────────
#
# **기본은 꺼져 있다.** 켜는 것은 conf/web.env 한 줄이고, 코드는 안 고친다.
#
#   DJANGO_BEHIND_TLS_PROXY=True
#
# 왜 필요한가 — Django 는 nginx 뒤에 있어서 자기에게 오는 요청을 http 로
# 본다. 그러면 Secure 쿠키를 「https 가 아니니」 하며 **안 내려보낸다.**
# nginx 가 X-Forwarded-Proto 를 붙이고(conf/nginx/default.conf) Django 가
# 그것을 믿게 하는 줄이 아래다. **둘 중 하나만 있으면 로그인이 안 된다.**
#
# 이 헤더를 믿어도 되는 이유 — nginx 가 proxy_set_header 로 **덮어쓴다.**
# 바깥에서 보낸 X-Forwarded-Proto 는 거기서 버려진다. nginx 를 안 거치고
# Django 가 직접 열려 있으면 이 가정이 깨지므로, 그때는 켜지 말 것.
BEHIND_TLS_PROXY = os.environ.get("DJANGO_BEHIND_TLS_PROXY", "False") == "True"

if BEHIND_TLS_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Django admin 세션과 CSRF 쿠키도 HTTPS 에서만 오가게 한다.
    # (refresh 토큰 쿠키는 뷰가 secure=True 를 직접 준다)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ⚠ SECURE_SSL_REDIRECT 는 **켜지 않는다.** 되돌림은 nginx 80 구역이 이미
#   한다. Django 까지 하면 두 번 튕기고, 무엇보다 compose 의 healthcheck 가
#   http 로 부르는 자리까지 301 이 되어 **멀쩡한 컨테이너가 unhealthy** 로
#   뜬다. 같은 이유로 nginx 도 /nginx-health 만 80 에 남겨 둔다.

# CSRF 신뢰 출처. **스킴까지 적어야 한다** (https://example.org).
#
# Django admin 처럼 폼을 POST 하는 자리가 여기 없으면 403 CSRF 로 막힌다.
# API 는 JWT 라 상관없지만 admin 은 세션·CSRF 로 돈다 — feature/backend 의
# /admin-session 흐름이 그 위에서 돈다.
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

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

# 스코프는 account.role 에서 유도한다 — 발급하는 쪽이 임의로 못 정한다(명세 §1-1).
# SECRET 이 따로인 이유 — SECRET_KEY 를 돌리면 세션·CSRF 까지 끊긴다.
JWT = {
    "SECRET": os.environ.get("JWT_SECRET") or SECRET_KEY,
    "ALGORITHM": "HS256",
    "ISSUER": os.environ.get("JWT_ISSUER", "empatho-cdss"),
    "ACCESS_TTL_MIN": int(os.environ.get("JWT_ACCESS_TTL_MIN", "30")),
    "REFRESH_TTL_DAYS": int(os.environ.get("JWT_REFRESH_TTL_DAYS", "14")),
}

# Django admin 세션을 받을 auth_user. 관리자가 여럿이어도 이 하나를 같이 쓴다.
# 비밀번호는 아무도 몰라도 된다 — POST /api/v1/admin-session 만이 세션을 만든다.
# ⚠ 그래서 **누가 고쳤는지 안 남는다.** 승인 이력도 마찬가지다(approved_by 는 NULL).
# ⚠ 비상용 superuser 를 따로 둘 것 — API 가 죽으면 여기로도 못 들어간다.
ADMIN_AUTH_USER = os.environ.get("ADMIN_AUTH_USER", "cdss_admin")

# 「추론 대기」 기준. 검사가 섰는데 이만큼 지나도록 ai_result 가 없으면 막힌 것이다.
# 짧으면 도는 중인 것까지 세어 늘 빨간 숫자가 되고, 그러면 아무도 안 본다.
ADMIN_INFERENCE_WAIT_MIN = int(os.environ.get("ADMIN_INFERENCE_WAIT_MIN", "30"))

# admin 「서버 상태」가 찔러 보는 곳. compose 의 서비스 이름이다 — 찌르는 쪽이
# 브라우저가 아니라 web 컨테이너라, 도커망 안에서 이름으로 닿는다. 로컬에서
# Django 를 직접 띄우면 이름이 안 풀려 전부 실패로 보인다. env 로 덮는다
# (GW_BASE=http://127.0.0.1:8091).
#
# TCP 연결만 본다. health 경로가 서비스마다 달라서 경로를 넣으면 살아 있는데도
# 404 로 죽은 것처럼 보인다. 「듣고 있는가」까지가 여기서 볼 수 있는 것이다.
#
# tunnel 은 없다 — 포트를 호스트에 안 내보내서 찌를 자리가 없다.
ADMIN_PROBES = {
    "file-gateway": os.environ.get("GW_BASE", "http://file-gateway:8091"),
    "llm-proxy": os.environ.get("LLM_BASE", "http://llm-proxy:8090"),
    "notify": os.environ.get("NOTIFY_BASE", "http://notify:8092"),
    "garage (S3)": os.environ.get("GARAGE_BASE", "http://garage:3900"),
    "orthanc (PACS)": os.environ.get("ORTHANC_BASE", "http://orthanc:8042"),
}

# 연결 하나를 기다리는 시간.
ADMIN_PROBE_TIMEOUT_SEC = float(os.environ.get("ADMIN_PROBE_TIMEOUT_SEC", "1.5"))

# 화면 전체의 마감. 위 값만으로는 안 지켜진다 —
#   · 이름 조회(getaddrinfo)는 소켓 타임아웃 밖이라 실패에 2~3초가 든다
#   · celery 는 브로커에 다시 걸어 보느라 7초 넘게 잡아먹는다
# 그래서 전부 한꺼번에 돌리고 여기서 끊는다. 못 끝낸 것은 「시간 초과」로 낸다.
ADMIN_PROBE_DEADLINE_SEC = float(os.environ.get("ADMIN_PROBE_DEADLINE_SEC", "4"))

# 상태 화면이 스스로 다시 뜨는 간격. 열어 두고 보는 화면이라 새로고침을 손으로
# 누르게 두면 죽은 것을 한참 뒤에 안다. 짧게 잡으면 그만큼 자주 찌른다.
ADMIN_STATUS_REFRESH_SEC = int(os.environ.get("ADMIN_STATUS_REFRESH_SEC", "30"))

# Go → Django 내부 콜백(명세 21장)의 서명 키. conf/gosvc.env 의 CALLBACK_SECRET
# 과 **같은 값**이어야 한다. 어긋나면 콜백이 401 로 조용히 거절된다.
# 비어 있으면 콜백을 아예 받지 않는다 — 설정 누락을 통과로 취급하지 않는다.
CALLBACK_SECRET = os.environ.get("CALLBACK_SECRET", "")

# 안내 챗봇(G-L2)이 부르는 곳. 브라우저는 /api/v1/chat 을 부르고 Django 가
# 여기를 부른다 — 대화는 서버 간 호출이라 위의 CALLBACK_SECRET 으로 서명한다.
#
# 도커망 안 이름이다. 비면 대화만 503 이 되고 나머지는 영향이 없다.
LLM_BASE = os.environ.get("LLM_BASE", "http://llm-proxy:8090")
# 모델이 답을 쓰는 동안 기다린다. gosvc 의 CHAT_TIMEOUT(기본 3분)보다
# 넉넉해야 한다 — 짧으면 Go 는 답을 만들었는데 여기서 먼저 끊는다.
LLM_TIMEOUT_SEC = int(os.environ.get("LLM_TIMEOUT_SEC", "240"))
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
CELERY_TASK_SOFT_TIME_LIMIT = 1200
CELERY_TASK_TIME_LIMIT = 1320

# 일이 끝나면 큐에서 삭제, 기본값은 꺼내자마자 삭제 
# 워커가 중간에 죽으면 그 일이 전부 사라짐 
CELERY_TASK_ACKS_LATE = True