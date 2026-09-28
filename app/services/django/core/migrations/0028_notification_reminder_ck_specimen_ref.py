# 알림 두 가지를 한 번에 맞춘다.
#
# 1. notification_type_ck 에 reservation_reminder 를 더한다.
#    모델(NOTIFICATION_TYPE)에는 49b9832 에서 들어갔는데 마이그레이션이 없었다
#    (0027 머리말의 「따로 대기 중」이 이것). DB CHECK 은 0004 의 6 개 그대로라
#    tasks.reservation_reminders 가 만드는 행은 지금 CHECK 에 걸린다.
#    새 목록은 옛 목록의 상위 집합이다 — 기존 행은 옛 CHECK 을 이미 통과했으니
#    AddConstraint 의 검증에서 떨어질 행이 없다. (Postgres 는 AddConstraint 때
#    notification 을 한 번 훑는다. 같은 트랜잭션 안에서 Remove → Add 라
#    CHECK 이 비는 틈은 밖에서 보이지 않는다.)
#
# 2. ref_type 선택지에 specimen 을 더한다(병리 확정 알림이 검체를 가리킨다).
#    ref_type 에는 DB CHECK 이 없어 choices 만 바뀐다 — SQL 이 없다.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_assessment_category_mri_4'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='notification',
            name='notification_type_ck',
        ),
        migrations.AlterField(
            model_name='notification',
            name='notification_type',
            field=models.CharField(choices=[('followup', 'followup'), ('discordance', 'discordance'), ('report_ready', 'report_ready'), ('reservation_requested', 'reservation_requested'), ('reservation_created', 'reservation_created'), ('reservation_changed', 'reservation_changed'), ('reservation_reminder', 'reservation_reminder')], max_length=30),
        ),
        migrations.AlterField(
            model_name='notification',
            name='ref_type',
            field=models.CharField(blank=True, choices=[('assessment', 'assessment'), ('discordance_flag', 'discordance_flag'), ('report', 'report'), ('exam_order', 'exam_order'), ('specimen', 'specimen')], max_length=30, null=True),
        ),
        migrations.AddConstraint(
            model_name='notification',
            constraint=models.CheckConstraint(condition=models.Q(('notification_type__in', ['followup', 'discordance', 'report_ready', 'reservation_requested', 'reservation_created', 'reservation_changed', 'reservation_reminder'])), name='notification_type_ck'),
        ),
    ]
