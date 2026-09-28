"""내원 방문(검사 칸이 빈 오더)도 completed 로 닫을 수 있게 한다.

유방외과 「진료 완료」는 이 환자를 데려온 방문 오더(창구 접수 · 내원 처리된
예약 — modality · exam_purpose · ordered_by 가 빈 requested)를 PATCH
/exam-orders/{id}/complete 로 닫는다. 그런데 exam_order_requested_fields_ck
가 「requested · scheduled · cancelled 가 아니면 세 칸이 다 차 있어야 한다」
여서 completed 로 저장하는 순간 IntegrityError(500)가 났다.

visited_at 이 있는(실제로 온) 행에만 completed 를 연다. 안 온 예약을 빈
칸으로 completed 로 만드는 길은 그대로 막힌다. 기존 행은 이미 옛 제약을
지키므로 새 제약에도 맞는다 — 데이터는 안 건드린다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_personal_note_handover"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="examorder",
            name="exam_order_requested_fields_ck",
        ),
        migrations.AddConstraint(
            model_name="examorder",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("order_status__in", ["requested", "scheduled", "cancelled"]),
                    models.Q(("order_status", "completed"), ("visited_at__isnull", False)),
                    models.Q(
                        ("modality__isnull", False),
                        ("exam_purpose__isnull", False),
                        ("ordered_by__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="exam_order_requested_fields_ck",
            ),
        ),
    ]
