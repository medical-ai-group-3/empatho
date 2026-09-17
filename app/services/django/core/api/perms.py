"""화면 권한 키 — {과}.{화면}.{동작} 형태. 프론트 메뉴/버튼 on-off 용."""

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

COMMON_PERMS = ["report.view.all"]

ROLE_PERMS = {
    "pathology": PATHOLOGY_PERMS + COMMON_PERMS,
    "radiology": RADIOLOGY_PERMS + COMMON_PERMS,
    # 다른 부서(원무·간호·유방외과)는 필요해지면 추가
}


def perms_for_role(role):
    return ROLE_PERMS.get(role, []) + COMMON_PERMS