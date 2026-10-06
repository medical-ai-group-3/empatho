"""간호 → 유방외과 인계를 오더에 남긴다(exam_order.handed_at · handed_to).

예전에는 보내기가 patient.primary_staff 만 바꿔서 「이번 방문을 보냈나」가
어디에도 남지 않았다 — 간호 대기 줄은 브라우저 localStorage 로 가렸고,
재진 환자는 보내기 전부터 유방외과 대기에 떴다.

기존 행은 비워 둔다. 언제 누구에게 보냈는지 남은 흔적이 없다.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_backfill_specimen_accession_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="examorder",
            name="handed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="examorder",
            name="handed_to",
            field=models.ForeignKey(
                blank=True,
                db_column="handed_to",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="core.staff",
            ),
        ),
    ]
