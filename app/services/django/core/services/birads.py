"""BI-RADS 판정 등급 — 모달리티별 허용 값 · 의심 여부 · 비교 순서.

── MRI 는 4 를 세분하지 않는다 ─────────────────────────────────
  ACR BI-RADS MRI 에는 4a · 4b · 4c 가 없다. MRI 판정은 0 · 1 · 2 · 3 ·
  4 · 5 · 6 이고, 맘모 · 초음파는 4 를 반드시 4a · 4b · 4c 로 적는다.
  그래서 "4" 는 MRI 에서만, "4a~4c" 는 MRI 가 아닌 곳에서만 받는다.

── 비교 순서(rank) ──────────────────────────────────────────────
  "4" 는 4b 와 같은 자리에 둔다. 한 검사 안에서 4 와 4a~4c 가 섞일 일은
  없다(모달리티가 갈린다). 섞이는 것은 모달리티를 건너 「가장 높은 등급」을
  고를 때뿐인데, 세분 없는 4 는 4a~4c 전체(2~95%)를 덮으므로 가운데인
  4b 로 본다 — 4a 보다 낮게 두면 MRI 의 의심 소견이 맘모 4a 에 밀리고,
  4c 보다 높게 두면 근거 없이 올라간다. 같은 자리면 먼저 온 쪽이 남는다.
"""

from .. import models
from ..api.errors import ApiError

# 판정 등급이 「의심」인 값. 대조(discordance) · 다음 단계 안내가 같이 쓴다.
SUSPICIOUS = frozenset({"4", "4a", "4b", "4c", "5"})

_RANK = {"0": 0, "1": 1, "2": 2, "3": 3,
         "4a": 4, "4": 5, "4b": 5, "4c": 6,
         "5": 7, "6": 8}


def normalize(value):
    """코드표 값으로 맞춘다. 모르는 값 · 빈 값은 None."""
    if value is None or isinstance(value, bool):
        return None
    s = str(value).strip().lower().replace("bi-rads", "").replace("birads", "").strip()
    return s if s in models.BIRADS_CATEGORY else None


def rank(value):
    """등급 비교 열쇠. 코드표 밖 값은 가장 낮다(-1)."""
    b = normalize(value)
    return _RANK[b] if b is not None else -1


def is_suspicious(value):
    return normalize(value) in SUSPICIOUS


def validate_for_study(study, category):
    """판독 임시저장 · 확정 · 정정에서 등급을 검사의 모달리티와 견준다.

    빈 값(None · "")은 여기서 막지 않는다 — 임시저장은 등급 없이도 된다.
    ⚠ 코드표 밖 값은 VALIDATION_ERROR. 모델 choices 가 폼 검증일 뿐이라
      DB 는 아무 문자열이나 받는다.
    """
    if category is None or category == "":
        return
    if category not in models.BIRADS_CATEGORY:
        raise ApiError("VALIDATION_ERROR",
                       f"BI-RADS 등급 「{category}」 은(는) 없는 값입니다.")
    modality = (study.modality or "").lower()
    if modality == "mri":
        if category in models.BIRADS_SUBCATEGORY_4:
            raise ApiError("BIRADS_SUBCATEGORY_NOT_FOR_MRI")
    elif category == "4":
        raise ApiError("VALIDATION_ERROR",
                       "유방촬영 · 초음파 판정은 4 를 4a · 4b · 4c 중 하나로 골라야 합니다.")
