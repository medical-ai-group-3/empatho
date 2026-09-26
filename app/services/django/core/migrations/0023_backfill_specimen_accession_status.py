"""이미 집었는데(assigned_to 있음) accession_status 가 여전히 bound 인
검체를 보정한다.

09-26 이전에는 SpecimenAssignView 가 assigned_to 만 채우고
accession_status·accessioned_at 은 안 건드렸다(2effa0a 이전). 그래서 그
전에 집힌 검체는 확진까지 끝났어도 "전체 환자 목록" 화면에 계속 "접수
대기"(bound)로 남는다 — 09-26 다희님이 specimen_id=40(S-TEST-73,
assigned_to=78)에서 확인했다.

**accessioned_at 은 진짜 집은 시각을 모른다.** 그때 assign 이 쓴 것은
QuerySet.update() 라 auto_now 필드(updated_at)도 안 돈다 — 남은 흔적이
없다. 지어낸 과거 시각을 넣느니 이 마이그레이션이 도는 지금 시각을 그대로
찍는다. 화면이 고치려는 것은 진행상황 상태(접수 완료 여부)이지 시각의
정확도가 아니다 — 0022(study.performed_at 백필)와 달리 여기는 "행이
생긴 때가 곧 사건"이라고 볼 근거 자체가 없다.

**bound 이면서 assigned_to 가 있는 것만** 고친다. accession_status 를
이미 accessioned 로 두는 새 경로(2effa0a 이후 assign)는 그대로 둔다 —
멱등이다, 두 번 돌려도 두 번째는 아무 행도 안 걸린다.
"""

from django.db import migrations
from django.utils import timezone


def fill(apps, schema_editor):
    Specimen = apps.get_model("core", "Specimen")
    rows = list(Specimen.objects.filter(
        accession_status="bound", assigned_to__isnull=False,
    ).only("pk", "accession_status", "accessioned_at"))

    now = timezone.now()
    for specimen in rows:
        specimen.accession_status = "accessioned"
        specimen.accessioned_at = now
    Specimen.objects.bulk_update(rows, ["accession_status", "accessioned_at"])


def unfill(apps, schema_editor):
    """되돌리기는 하지 않는다.

    이 마이그레이션이 고친 행과 원래도 accessioned 였을 행을 구분할
    표시를 안 남겼다 — 0022 와 같은 이유로, 되돌리면 더 나빠진다.
    """


class Migration(migrations.Migration):

    dependencies = [("core", "0022_backfill_study_performed_at")]

    operations = [migrations.RunPython(fill, unfill)]
