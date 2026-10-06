"""검사의 촬영 시각을 메운다.

`Study.performed_at` 을 채우는 코드가 아무 데도 없었다. 읽는 곳은 넷인데
(목록 정렬 · 나이 계산 · 타임라인의 「촬영」 줄 · 유방외과 뷰어의 모달리티
탭) 쓰는 곳이 없어서, 09-23 기준 검사 36 건이 전부 NULL 이었다. 그래서
유방외과 환자 상세의 뷰어가 「촬영한 검사가 없습니다」로 남아 있었다.

새로 만드는 검사는 StudyStartView 가 찍는다(촬영 시작 = 그 호출). 이미
있는 것은 그 시각을 모르지만, 행이 만들어진 때가 곧 촬영 시작이다 —
같은 호출에서 함께 생긴 값이라 지어낸 시각이 아니다. created_at 을 옮긴다.

**비어 있는 것만 채운다.** 사람이 관리자 화면에서 손으로 넣어 둔 값이
있으면 그대로 둔다.
"""

from django.db import migrations


def fill(apps, schema_editor):
    Study = apps.get_model("core", "Study")
    rows = Study.objects.filter(performed_at__isnull=True).only("pk", "created_at")
    for study in rows:
        study.performed_at = study.created_at
    Study.objects.bulk_update(rows, ["performed_at"])


def unfill(apps, schema_editor):
    """되돌리기는 하지 않는다.

    어느 것이 이 마이그레이션이 채운 값이고 어느 것이 사람이 넣은
    값인지 구분할 표시를 남기지 않았다. 되돌리면 손으로 넣은 값까지
    지운다 — 아무것도 안 하는 편이 낫다.
    """


class Migration(migrations.Migration):

    dependencies = [("core", "0021_prescription_drug")]

    operations = [migrations.RunPython(fill, unfill)]
