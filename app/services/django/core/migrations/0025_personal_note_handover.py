from django.db import migrations, models


class Migration(migrations.Migration):
    """personal_note.note_type 에 handover(인계 사항)를 더한다.

    인계 사항은 과 홈의 「인계 사항」 칸이 쓴다. 전에는 브라우저에만 남아
    같은 과 다른 사람에게 안 보였다(09-27). 선택지만 늘 뿐 칸은 그대로다.
    """

    dependencies = [
        ("core", "0024_examorder_handoff"),
    ]

    # ⚠ 제약(personal_note_type_ck)도 같은 목록을 본다 — 선택지만 늘리면
    #   DB 가 handover 를 CHECK 위반으로 막는다. 지우고 다시 건다
    operations = [
        migrations.RemoveConstraint(model_name="personalnote", name="personal_note_type_ck"),
        migrations.AddConstraint(
            model_name="personalnote",
            constraint=models.CheckConstraint(
                condition=models.Q(("note_type__in", ["todo", "sticky", "handover"])),
                name="personal_note_type_ck",
            ),
        ),
        migrations.AlterField(
            model_name="personalnote",
            name="note_type",
            field=models.CharField(
                choices=[("todo", "todo"), ("sticky", "sticky"), ("handover", "handover")],
                max_length=10,
            ),
        ),
    ]
