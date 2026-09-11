"""drf-spectacular 설정 — 봉투 후처리와 인증 스킴.

Swagger 가 실제 응답과 다르게 보이면 여기부터 본다. 스펙 관련은 전부 이 파일에 있다.

두 가지를 한다.
    ① 전 응답 스키마를 봉투로 감싼다. spectacular 는 뷰의 serializer 를 보고
       스키마를 만들기 때문에, 그대로 두면 문서에는 data 만 나오고 실제 응답에는
       success · error · trace_id 가 붙어 서로 다르다.
    ② AccountJWTAuthentication 을 Bearer 스킴으로 알린다. spectacular 는 자기가
       모르는 인증 클래스를 만나면 경고만 내고 건너뛴다 — 그러면 Swagger 에
       Authorize 버튼이 안 생긴다.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from .errors import ERRORS

_ERROR_SCHEMA = {
    "type": "object",
    "nullable": True,
    "properties": {
        "code": {"type": "string", "enum": sorted(ERRORS)},
        "message": {"type": "string"},
        "details": {"nullable": True},
    },
    "required": ["code", "message"],
}


def _wrap(schema):
    return {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "data": schema if schema is not None else {"nullable": True},
            "error": _ERROR_SCHEMA,
            "trace_id": {"type": "string"},
        },
        "required": ["success", "data", "error", "trace_id"],
    }


def wrap_responses(result, generator, request, public):
    """전 응답 스키마를 봉투로 감싼다 — SPECTACULAR_SETTINGS 의 POSTPROCESSING_HOOKS."""
    for path in result.get("paths", {}).values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            for response in operation.get("responses", {}).values():
                for media in (response.get("content") or {}).values():
                    media["schema"] = _wrap(media.get("schema"))
    return result


class AccountJWTScheme(OpenApiAuthenticationExtension):
    """Swagger 의 Authorize 버튼. Bearer {access_token} 를 넣는 자리다."""

    target_class = "core.api.auth.AccountJWTAuthentication"
    name = "accountJWT"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "core.account 기준 토큰. 직원 토큰과 환자 토큰의 스코프는 섞이지 않는다.",
        }
