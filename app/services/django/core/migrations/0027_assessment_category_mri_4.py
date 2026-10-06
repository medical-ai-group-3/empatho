# MRI 판정 등급 「4」(세분 없음)를 BI-RADS 선택지에 더한다.
# choices 만 바뀐다 — assessment.category 에는 DB CheckConstraint 가 없어
# 스키마 변경은 없다. 모달리티별 허용 값 검증은 core/services/birads.py.
#
# ⚠ 손으로 쓴 것이다. makemigrations 는 notification_type_ck 변경(따로
#   대기 중)을 같이 묶으려 해서 그 부분은 빼 두었다.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0026_examorder_complete_visit'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assessment',
            name='category',
            field=models.CharField(blank=True, choices=[('0', '0'), ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'), ('4a', '4a'), ('4b', '4b'), ('4c', '4c'), ('5', '5'), ('6', '6')], max_length=10, null=True),
        ),
    ]
