"""에러 코드 카탈로그와 그 코드로 던지는 예외.

근거 — CDSS_API_명세서_v3 §1-4. 명세의 25 개가 SPEC_ERRORS 에 그대로 있다.

    raise ApiError("SPECIMEN_NOT_BOUND")

카탈로그에 없는 코드는 여기서 KeyError 로 막힌다 — 오타로 만들어진 코드가
클라이언트까지 흘러가면 처리되지 않는 분기가 생긴다.

INFRA_ERRORS 는 명세 밖이다. 명세가 예상하지 못한 상황(잡히지 않은 예외)에도
봉투는 씌워져야 해서 둔다. 늘릴 때는 팀에 알린다.
"""

from dataclasses import dataclass

from rest_framework.exceptions import APIException


@dataclass(frozen=True)
class ErrorSpec:
    code: str
    status: int
    message: str
    note: str = ""


def _spec(code, status, message, note=""):
    return ErrorSpec(code=code, status=status, message=message, note=note)


# 명세서 §1-4 의 25 개. 순서도 문서 그대로 둔다 — 대조하기 쉽게.
SPEC_ERRORS = [
    _spec("EXAM_PURPOSE_REQUIRED", 422, "exam_purpose 없이 오더를 만들 수 없습니다.",
          "비면 생성 거부 — 감사지표 산출 불가"),
    _spec("AI_LOCKED_BEFORE_FIRST_READ", 403, "1차 판정을 저장하기 전에는 AI 결과를 볼 수 없습니다.",
          "자동화 편향 방지"),
    _spec("BIRADS3_NOT_ALLOWED_IN_SCREENING", 422, "선별 판독에서는 범주 3 을 쓸 수 없습니다.",
          "선별 단계에 3 선택지 자체가 없다"),
    _spec("BIRADS3_CONDITION_FAILED", 422, "범주 3 부여 조건 3 개를 채우지 못했습니다.",
          "정밀검사 선행 · 진단 목적 · 촉지 없음"),
    _spec("BIRADS_SUBCATEGORY_NOT_FOR_MRI", 422, "MRI 판정에는 4a · 4b · 4c 를 쓸 수 없습니다.",
          "ACR BI-RADS — MRI 세분화 미제공"),
    _spec("BINDING_ROLE_FORBIDDEN", 403, "검체 바인딩은 간호 · 유방외과만 할 수 있습니다.",
          "09-09 팀 확정 — 유방외과가 채취하고 간호가 라벨링·바인딩한다"),
    _spec("SPECIMEN_NOT_BOUND", 409, "병변에 연결되지 않은 검체는 접수할 수 없습니다.",
          "Hard Stop — 사후 복원 불가 · specimen.lesion_id NOT NULL"),
    _spec("DISPOSITION_ROLE_ONLY_SURGERY", 403, "불일치 해소 처분은 유방외과만 할 수 있습니다.",
          "UC-19 단독 권한"),
    _spec("UNLOCK_ROLE_ONLY_SURGERY", 403, "열람 잠금 해제는 유방외과만 할 수 있습니다.",
          "SYS-5 단독 권한"),
    _spec("UNLOCK_CONDITION_NOT_MET", 409, "해제 조건 3 개를 모두 채우지 못했습니다.",
          "확정 · 대조 종결 · 설명 완료 (AND)"),
    _spec("REPORT_LOCKED", 409, "잠금 상태인 리포트는 열람할 수 없습니다.", "SYS-5"),
    _spec("ASSESSMENT_FINALIZED", 409, "확정된 판정은 직접 고칠 수 없습니다.",
          "개정은 amend → superseded_by"),
    _spec("STUDY_REJECTED", 409, "반려된 검사에는 판독할 수 없습니다.", "SYS-6 · 재촬영 경로로"),
    _spec("VALIDATION_ERROR", 400, "요청 값이 올바르지 않습니다.", "필수 필드 누락 · 타입 불일치"),
    _spec("UNAUTHENTICATED", 401, "인증이 필요합니다.", "토큰 없음 · 만료"),
    _spec("ROLE_FORBIDDEN", 403, "이 작업을 할 권한이 없습니다.", "§15 권한 매트릭스"),
    _spec("NOT_FOUND", 404, "대상을 찾을 수 없습니다."),
    _spec("RATE_LIMITED", 429, "요청이 많아 잠시 후 다시 시도해야 합니다.", "추론 큐 과부하"),
    _spec("INFERENCE_FAILED", 500, "추론 서버가 응답하지 못했습니다.", "run_status=failed 로 기록"),
    _spec("TICKET_EXPIRED", 401, "전송 티켓이 만료되었습니다.", "유효기간 5 분 · 재발급 후 재시도"),
    _spec("TICKET_SCOPE_MISMATCH", 403, "티켓 범위 밖의 리소스입니다.",
          "권한 판정은 Django 가 단독으로 한다"),
    _spec("CHECKSUM_MISMATCH", 409, "업로드된 바이트가 checksum 과 다릅니다.",
          "무결성 증명 실패 — 커밋 거부"),
    _spec("UPSTREAM_LLM_UNAVAILABLE", 503, "리포트 서술 생성 서버가 응답하지 못했습니다.",
          "리포트는 content_json 만으로 발급된다"),
    _spec("PYRAMID_NOT_READY", 409, "타일 피라미드가 아직 만들어지지 않았습니다.",
          "build_status 와 진행률을 함께 반환"),
    _spec("TILE_OUT_OF_RANGE", 404, "없는 줌 레벨 또는 타일 좌표입니다.", "level_count 범위 밖"),
]

# 명세 밖. 늘릴 때는 팀에 알린다.
# 아래 둘은 Go 와 주고받는 자리(내부 콜백 · 티켓 발급)에서 쓴다 — 명세 §1-4 는
# 공개 API 의 계약이고 그 두 경로는 거기 없다.
INFRA_ERRORS = [
    _spec("INTERNAL_ERROR", 500, "서버에서 처리하지 못했습니다.",
          "잡히지 않은 예외 — 봉투를 유지하려고 둔다. 명세 §1-4 에는 없다"),
    _spec("TARGET_NOT_FOUND", 422, "가리키는 대상이 없습니다.",
          "scope_id 의 study · specimen · report 가 없다. 재시도해도 같다"),
    _spec("UNSUPPORTED_PURPOSE", 422, "아직 받을 수 없는 purpose 입니다.",
          "담을 칸이 없다 — prescription_pdf 는 처방 표가 MVP 밖이다"),
    # 원무 · 영상의학과 API 에서 쓴다. 명세 §1-4 에 없어 여기 둔다 — 명세에 넣으면 위로 옮기고
    # test_errors.py 의 표에도 더한다.
    _spec("ALREADY_CONFIRMED", 409, "이미 확정된 오더입니다."),
    _spec("ALREADY_ASSIGNED", 409, "다른 선생님이 이미 맡았습니다."),
    # 09-16 일운님 · 다희님 협의 — 수술 결정 기록(PATCH /assessments/{id}/decision)
    # 단독 권한. 명세 §1-4 25개엔 없어 여기 둔다.
    _spec("DECISION_ROLE_ONLY_SURGERY", 403, "수술 결정 기록은 유방외과만 할 수 있습니다."),
    # 09-18 일운님 지적 · 팀 확정 — MATRIX 칸(study/assessment/specimen_pathology:U)
    # 만으로는 관리자 격자 조정이나 staff.extra_permissions 로 다른 부서가
    # 판독·확진을 확정할 길이 열린다. IsRole 로 부서 자체를 잠근다.
    # 명세 §1-4 25개엔 없어 여기 둔다.
    _spec("FINALIZE_ROLE_ONLY_RADIOLOGY", 403, "판독 확정 · 임시저장 · 정정은 영상의학과만 할 수 있습니다."),
    _spec("FINALIZE_ROLE_ONLY_PATHOLOGY", 403, "확진 확정 · 임시저장 · 정정은 병리과만 할 수 있습니다."),
]

# 명세 밖. 영상의학과 라우터 인계 문서(2026-09) 재설계로 추가.
# 문서 화면 ③ 판독 통합조회의 서버 가드 — SPEC_ERRORS 25개엔 없던 케이스라
# 여기 따로 둔다. 늘릴 때는 팀에 알린다.
HANDOVER_ERRORS = [
    _spec("STUDY_NOT_READ_READY", 409, "업로드된 영상이 없어 판독을 시작할 수 없습니다.",
          "study 에 storage_object 가 하나도 없다 — Go 웹훅 대기 중"),
]

SPEC_CODES = frozenset(e.code for e in SPEC_ERRORS)
INFRA_CODES = frozenset(e.code for e in INFRA_ERRORS)

ERRORS = {e.code: e for e in SPEC_ERRORS + INFRA_ERRORS + HANDOVER_ERRORS}


def spec_for(code):
    """코드에 맞는 ErrorSpec. 카탈로그에 없으면 KeyError."""
    try:
        return ERRORS[code]
    except KeyError:
        raise KeyError(
            "에러 코드 %r 이 카탈로그에 없다. core/api/errors.py 에 먼저 넣을 것." % code
        ) from None


class ApiError(APIException):
    """명세 §1-4 의 코드로 던지는 예외.

    DRF 의 APIException 을 상속해 DRF 의 예외 경로를 그대로 탄다.
    봉투로 바꾸는 것은 envelope.api_exception_handler 가 한다.
    """

    def __init__(self, code, message=None, details=None):
        spec = spec_for(code)
        self.code = spec.code
        self.status_code = spec.status
        self.message = message or spec.message
        self.details = details
        super().__init__(detail=self.message, code=spec.code)

    def __str__(self):
        return "%s(%s): %s" % (self.code, self.status_code, self.message)
