# 처방 약 · 복약 기록 두 표. 0019_prescription 의 Prescription 에 매달린다 —
# 그 표는 건드리지 않는다. 왜 content(jsonb) 만으로는 안 되는지는
# core/models.py 의 PrescriptionDrug 머리말에 적었다.
#
# ⚠ makemigrations 는 notification_type 의 CHECK 도 같이 넣으려 했다. 이 브랜치가
#   건드린 것이 아니라 **전부터 밀려 있던 것**이라 여기서 뺐다. 그쪽 담당이
#   따로 한 줄로 내는 편이 되돌리기 쉽다.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_personal_note"),
    ]

    operations = [
        migrations.CreateModel(
            name="MedicationLog",
            fields=[
                ("log_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("slot_time", models.CharField(max_length=5)),
                ("taken_at", models.DateTimeField(auto_now_add=True)),
                ("taken_on", models.DateField()),
            ],
            options={
                "verbose_name": "복약 기록",
                "verbose_name_plural": "복약 기록",
                "db_table": "medication_log",
            },
        ),
        migrations.CreateModel(
            name="PrescriptionDrug",
            fields=[
                ("drug_id", models.BigAutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("ingredient", models.CharField(blank=True, max_length=200, null=True)),
                ("dose", models.CharField(max_length=50)),
                ("times", models.JSONField(default=list)),
                ("days", models.IntegerField()),
                ("purpose", models.CharField(blank=True, max_length=250, null=True)),
                ("how", models.TextField(blank=True, null=True)),
                ("watch", models.TextField(blank=True, null=True)),
            ],
            options={
                "verbose_name": "처방 약",
                "verbose_name_plural": "처방 약",
                "db_table": "prescription_drug",
            },
        ),
        migrations.AddField(
            model_name="medicationlog",
            name="patient",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="medication_logs",
                to="core.patient",
            ),
        ),
        migrations.AddField(
            model_name="prescriptiondrug",
            name="prescription",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="drugs",
                to="core.prescription",
            ),
        ),
        migrations.AddField(
            model_name="medicationlog",
            name="drug",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="logs",
                to="core.prescriptiondrug",
            ),
        ),
        migrations.AddConstraint(
            model_name="prescriptiondrug",
            constraint=models.CheckConstraint(
                condition=models.Q(("days__gte", 1)), name="prescription_drug_days_ck"
            ),
        ),
        migrations.AddConstraint(
            model_name="medicationlog",
            constraint=models.UniqueConstraint(
                fields=("drug", "taken_on", "slot_time"), name="medication_log_slot_uq"
            ),
        ),
    ]
