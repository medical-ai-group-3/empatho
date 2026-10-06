"""유방외과 열람 — 판독 리포트를 유방외과가 마지막으로 연 시각.

영상의학과 · 병리과 목록의 「유방외과 열람」 칸이 읽는다. 전에는 기록하는
곳이 리포트 단건 조회(GET /reports/{id}/)뿐이었는데 유방외과 화면은 목록
(GET /reports/?patient=)만 불러서 기록이 한 번도 안 남았고, 목록 응답에도
그 값이 안 실려 화면이 늘 「미열람」이었다(09-27, 판독 리포트 29건 중 2건).

  mark      유방외과가 한 환자의 리포트 목록을 열면 그 환자 판독 리포트에
            열람 시각 · 사람을 남긴다(views/surgery.py)
  last_seen 검사 · 검체 목록에 얹을 「유방외과가 마지막으로 연 시각」
            (views/radiology.py · views/surgery.py 의 검체 목록)

⚠ 판독 리포트(stage)만 본다. 종합 소견서 · 환자용은 다른 사람이 읽는다.
⚠ last_viewed_by 가 유방외과인 것만 센다 — 다른 과가 단건으로 열면 그
  칸이 덮여 그 리포트는 다시 「미열람」이 된다. 알고 둔 한계다.
"""
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from . import models


def mark(patient_id, staff):
    if staff is None:
        return 0
    return models.Report.objects.filter(patient_id=patient_id, report_type="stage").update(
        last_viewed_at=timezone.now(), last_viewed_by=staff)


def last_seen(by):
    """by 는 "study" 또는 "specimen" — 바깥 행의 pk 로 잇는다."""
    return Subquery(
        models.Report.objects
        .filter(**{by: OuterRef("pk")}, report_type="stage",
                last_viewed_by__account__role="surgery")
        .order_by("-last_viewed_at")
        .values("last_viewed_at")[:1])
