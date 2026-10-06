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
    # amend(정정)는 없다 — 확정 사양서 §8-2, 확정 후 오류는 새 검체로 처리한다.
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
    "pathology": PATHOLOGY_PERMS + COMMON_PERMS,
    "radiology": RADIOLOGY_PERMS + COMMON_PERMS,
    "reception": RECEPTION_PERMS + COMMON_PERMS,
    # 09-27 원무과가 간호과로 합쳐졌다 — 간호는 원무 화면 권한도 다 갖는다
    # (permissions.py 의 _merge_reception_into_nursing 과 짝)
    "nursing": NURSING_PERMS + RECEPTION_PERMS + COMMON_PERMS,
    "surgery": BREAST_PERMS + COMMON_PERMS,
    "admin": ADMIN_PERMS,
}


def perms_for_role(role):
    # 공통 권한은 ROLE_PERMS 에 비관리자 역할만 포함한다. ADMIN_PERMS 는
    # report.view.all 없이 유지하며, Django admin 접근은 core/admin.py 에서
    # 별도로 막는다.
    return ROLE_PERMS.get(role, [])


def perms_for(account):
    """소속 과 + 추가 과(staff.extra_depts)의 화면 권한을 합친다.

    ⚠ **admin 은 합칠 수 없다.** extra_depts_of 가 줄 수 있는 과만 남기고,
      거기에 admin 은 없다. 관리자 문(admin.console.open)은 부서로 열리는
      것이 아니라 role='admin' 으로만 열린다.

    차례를 지킨다 — 소속 과의 권한이 앞이다. 화면이 순서를 보지는 않지만
    로그에 찍힐 때 「무엇이 본래 것이고 무엇이 더한 것인가」가 보인다.
    """
    from .permissions import extra_depts_of      # 순환 import 를 피해 여기서

    out = list(perms_for_role(getattr(account, "role", None)))
    seen = set(out)
    for dept in extra_depts_of(account):
        for perm in ROLE_PERMS.get(dept, []):
            if perm not in seen:
                seen.add(perm)
                out.append(perm)
    return out
