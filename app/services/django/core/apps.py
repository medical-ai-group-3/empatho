from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Warning, register


class CoreConfig(AppConfig):
    name = "core"

    def ready(self):
        register(check_signing_keys)
        # drf-spectacular 확장은 클래스가 정의될 때 등록된다. 이 모듈을 아무도
        # 안 부르면 Swagger 에 Authorize 버튼이 안 생기고 경고만 뜬다.
        from .api import schema        # noqa: F401


def check_signing_keys(app_configs, **kwargs):
    """서명 키 둘이 서로 다른지 본다.

    TICKET_KEY        Django 서명 → Go 검증   (JWT HS256)
    CALLBACK_SECRET   Go 서명 → Django 검증   (HMAC over ts + "." + body)

    방향이 반대라 같은 값을 쓰면 안 된다. 같으면 Go 에게 준 티켓의 서명 재료로
    Django 로 오는 콜백을 위조할 수 있다 — 티켓은 클라이언트가 들고 다닌다.

    기동 때 잡는다. 첫 요청에서 알게 되면 이미 늦다.
    """
    ticket = getattr(settings, "TICKET_KEY", "")
    callback = getattr(settings, "CALLBACK_SECRET", "")
    problems = []

    if ticket and callback and ticket == callback:
        problems.append(Error(
            "TICKET_KEY 와 CALLBACK_SECRET 이 같은 값이다.",
            hint="방향이 반대인 키다. .env 에서 서로 다른 값으로 나눠 넣을 것.",
            id="core.E001"))
    if not ticket:
        problems.append(Warning(
            "TICKET_KEY 가 비어 있다 — 전송 티켓을 발급할 수 없다.",
            hint="conf/gosvc.env 의 TICKET_KEY 와 같은 값을 넣을 것.",
            id="core.W001"))
    if not callback:
        problems.append(Warning(
            "CALLBACK_SECRET 이 비어 있다 — Go 콜백을 받지 않는다.",
            hint="conf/gosvc.env 의 CALLBACK_SECRET 과 같은 값을 넣을 것.",
            id="core.W002"))
    return problems
