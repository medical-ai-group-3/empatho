"""검체 바인딩 때 병변의 그 순간 모습을 한 줄로 남긴다 — specimen.target_snapshot.

09-28. 병변은 나중에 다시 재거나 정정 판독으로 등급이 바뀔 수 있다. 병리과가
보는 것은 **채취할 때 무엇을 겨냥했나**여서, 바인딩 순간의 값을 글자로 굳혀
둔다(칸이 CharField(250) 하나라 구조체가 아니라 한 줄이다).

    "MRI-1 · 우측 · 12.3mm · BI-RADS 4 · MRI"

빈 칸은 빼고 잇는다. 아무것도 모르면 None.
"""

from .. import models

MODALITY_LABEL = {"mammo": "맘모그래피", "us": "초음파", "mri": "MRI"}
SIDE_LABEL = {"left": "좌측", "right": "우측", "l": "좌측", "r": "우측"}
MAX_LEN = 250


def _fmt_num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f"{f:g}"


def _location(lesion):
    """좌우 · 위치. detail 에 있으면 그것, 초음파는 원본 영상의 laterality,
    MRI 는 detail.quadrant, 맘모는 detail.image(예: L-CC)."""
    detail = lesion.detail if isinstance(lesion.detail, dict) else {}
    parts = []
    side = detail.get("laterality") or detail.get("side")
    if not side and detail.get("source_object"):
        src = models.StorageObject.objects.filter(
            pk=detail.get("source_object")).values_list("laterality", flat=True).first()
        side = src
    if side:
        parts.append(SIDE_LABEL.get(str(side).lower(), str(side)))
    for key in ("location", "quadrant", "clock"):
        val = detail.get(key)
        if val:
            parts.append(str(val))
            break
    else:
        image = detail.get("image")
        if image and not side and isinstance(image, str):
            parts.append(image)
    return " ".join(parts) or None


def _size(lesion):
    mm = lesion.measured_size_mm if lesion.measured_size_mm is not None else lesion.ai_size_mm
    if mm is not None:
        return f"{_fmt_num(mm)}mm"
    px = lesion.measured_size_px if lesion.measured_size_px is not None else lesion.ai_size_px
    if px is not None:
        return f"{_fmt_num(px)}px"
    return None


def _latest_final_birads(lesion):
    """이 병변의 살아 있는(정정으로 대체되지 않은) 최종 판정. 병변 판정이
    없으면 검사 전체 판정(lesion 이 빈 행)으로 내려간다."""
    base = models.Assessment.objects.filter(
        study_id=lesion.study_id, read_stage="final", superseded_by__isnull=True,
    ).exclude(category__isnull=True).order_by("-finalized_at", "-assessment_id")
    row = base.filter(lesion=lesion).first() or base.filter(lesion__isnull=True).first()
    return row.category if row else None


def build(lesion):
    modality = lesion.modality or getattr(lesion.study, "modality", None)
    birads = _latest_final_birads(lesion)
    parts = [
        lesion.label,
        _location(lesion),
        _size(lesion),
        f"BI-RADS {birads.upper()}" if birads else None,
        MODALITY_LABEL.get(modality, modality) if modality else None,
    ]
    text = " · ".join(p for p in parts if p)
    return text[:MAX_LEN] or None
