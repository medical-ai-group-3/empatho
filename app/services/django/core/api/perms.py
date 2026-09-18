"""화면 권한 키 — {과}.{화면}.{동작} 형태. 프론트 메뉴/버튼 on-off 용.

값의 근거는 hospital/perm.js 의 CATALOG(deptPerms · RECEPTION · BREAST ·
ADMIN · NURSING) 다. hospital/nav.js 의 화면별 need 는 그 카탈로그의
부분집합(화면 진입 가능 여부만)이라 그대로 옮기면 버튼 권한이 빠진다.
"""

PATHOLOGY_PERMS = [
    "pathology.queue.view", "pathology.queue.assign",
    "pathology.upload.view", "pathology.upload.send",
    "pathology.ai.run", "pathology.ai.view",
    "pathology.read.view", "pathology.read.draft", "pathology.read.finalize",
    "pathology.list.view",
    "pathology.amend.view", "pathology.amend.save",
]

RADIOLOGY_PERMS = [
    "radiology.queue.view", "radiology.queue.assign",
    "radiology.upload.view", "radiology.upload.send",
    "radiology.ai.run", "radiology.ai.view",
    "radiology.read.view", "radiology.read.draft", "radiology.read.finalize",
    "radiology.list.view",
    "radiology.amend.view", "radiology.amend.save",
    "radiology.retake", "radiology.lesion.add", "radiology.lesion.fp",
]

# 원무과 — perm.js 의 RECEPTION 상수 그대로. 다섯 장 틀을 안 쓴다.
RECEPTION_PERMS = [
    "reception.intake.view",
    "reception.patient.search",
    "reception.patient.create",
    "reception.checkin",
    "reception.patients.view",
    "reception.patient.edit",
    "reception.reserve",
    "reception.requests.view",
    "reception.confirm",
]

# 간호과 — perm.js 의 NURSING 상수 + specimen.bind(간호·유방외과 공용
# 검체 바인딩 팝업, 단독 권한 클래스 CanBindSpecimen 과 짝).
NURSING_PERMS = [
    "nursing.waiting.view",
    "nursing.waiting.assign",
    "nursing.followup.view",
    "nursing.followup.create",
    "nursing.followup.call",
    "specimen.bind",
]

# 유방외과 — perm.js 의 BREAST 상수 + specimen.bind. account.role 값은
# "surgery" 다(nav.js 라우팅 키 "breast" 와 다르다 — STAFF_DEPTS 참고).
BREAST_PERMS = [
    "breast.waiting.view",
    "breast.exam.order",
    "breast.review.view",
    "breast.decision.view",
    "breast.decision.save",
    "breast.report.unlock",
    "breast.discordance.view",
    "breast.discordance.dispose",
    "specimen.bind",
]

# 관리자 — perm.js 의 ADMIN 상수. 문 하나만 연다, 안쪽은 Django admin 이
# auth_user 권한으로 따로 본다.
ADMIN_PERMS = [
    "admin.console.open",
]

COMMON_PERMS = ["report.view.all"]

ROLE_PERMS = {
    "pathology": PATHOLOGY_PERMS,
    "radiology": RADIOLOGY_PERMS,
    "reception": RECEPTION_PERMS,
    "nursing": NURSING_PERMS,
    "surgery": BREAST_PERMS,
    "admin": ADMIN_PERMS,
}


def perms_for_role(role):
    return ROLE_PERMS.get(role, []) + COMMON_PERMS
