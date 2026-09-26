"""일회성 — 병리과 큐 확인용 테스트 검체를 하나 만든다.

09-27 다희님 요청. 직접 실행용 스크립트다 — 마이그레이션에 안 넣는다.
마이그레이션에 넣으면 배포마다(로컬 포함 모든 환경에서) 매번 다시
만들려고 시도하게 된다. 이건 딱 한 번, 필요할 때 사람이 손으로 돌리는
자리다.

    python manage.py seed_pathology_queue_test_specimen

만드는 것
    환자        이름에 "테스트"가 들어간다 — 실제 환자와 안 헷갈리게.
                patient_number 도 TEST- 접두사를 쓴다.
    영상 이력   ExamOrder + Study(모달리티 mammo, performed_at 과거 시각) —
                PatientTimelineView 가 "촬영" 줄로 낸다. 이 환자한테
                검체 말고 다른 이력이 있어야 한다는 요청이라 필요했다.
    병변        Lesion — specimen.lesion_id 가 NOT NULL 이라(Hard Stop,
                사후에 못 붙인다) 검체보다 먼저 있어야 한다.
    검체        accession_status="bound", assigned_to=None — 아직 아무도
                안 집은 상태. collected_at 을 채워서 이 검체 자체도
                "검체 채취" 줄로 타임라인에 잡힌다(그래서 이력이 최소
                두 줄 — 촬영 + 검체 채취).

exam_order 는 requested_fields_ck 때문에 ordered_by(Staff)가 있어야
한다 — 실행 시점에 있는 영상의학과 직원 아무나 쓴다. 하나도 없으면
멈추고 알려준다(테스트 데이터를 반쯤 만들어 놓고 죽는 것보다 낫다).

이 명령은 **몇 번을 돌려도 안전하다** — 부를 때마다 새 환자를 새로
만든다(멱등이 아니다, 의도적이다: "그 테스트 검체 하나"가 아니라 확인이
필요할 때마다 새로 하나씩 만드는 자리라서). 지울 때는 화면이나 admin 에서
방금 나온 patient_number 로 찾아 지우면 된다 — 여기서 자동으로 안 지운다.
"""

import random
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import models


class Command(BaseCommand):
    help = "병리과 큐(GET /specimens/queue) 확인용 테스트 검체 1건을 만든다."

    def handle(self, *args, **options):
        suffix = random.randint(1000, 9999)

        ordered_by = models.Staff.objects.filter(account__role="radiology").first()
        if ordered_by is None:
            raise CommandError(
                "영상의학과 직원(Staff)이 하나도 없다 — exam_order.ordered_by 를 "
                "채울 사람이 없어서 멈춘다. 계정을 하나 만든 뒤 다시 돌릴 것."
            )

        now = timezone.now()
        past_study_at = now - timedelta(days=14)
        past_collected_at = now - timedelta(days=1)

        patient = models.Patient.objects.create(
            patient_number=f"TEST-PATH-Q-{suffix}",
            sex="여",
            birth_year=1979,
            first_visited_at=past_study_at,
        )
        models.PatientPii.objects.create(
            patient=patient,
            name=f"테스트환자{suffix}",   # ⚠ 이름에 "테스트" — 실제 환자와 구분용
            birth_date="1979-05-14",
            phone=f"010-0000-{suffix}",
        )

        # ── 다른 이력 하나 — 이전 촬영 (타임라인의 "촬영" 줄) ──────────
        order = models.ExamOrder.objects.create(
            patient=patient,
            modality="mammo",
            exam_purpose="screening",
            order_status="completed",
            ordered_by=ordered_by,
            ordered_at=past_study_at,
            scheduled_at=past_study_at,
            visited_at=past_study_at,
        )
        study = models.Study.objects.create(
            patient=patient,
            exam_order=order,
            modality="mammo",
            performed_at=past_study_at,
        )

        # ── 병변 — 검체가 매달릴 자리 ──────────────────────────────────
        lesion = models.Lesion.objects.create(
            patient=patient,
            study=study,
            label="테스트 병변",
        )

        # ── 확인 대상 검체 — bound · 미집기 ────────────────────────────
        specimen = models.Specimen.objects.create(
            patient=patient,
            lesion=lesion,
            specimen_label=f"S-TEST-Q-{suffix}",
            specimen_type="core_needle",
            guidance_route="ultrasound",
            collected_at=past_collected_at,
            accession_status="bound",
            assigned_to=None,
            clinical_note="병리과 큐 확인용 테스트 검체 — 실제 환자 아님.",
        )

        self.stdout.write(self.style.SUCCESS(
            "테스트 검체를 만들었다:\n"
            f"  patient_id       = {patient.pk}  ({patient.patient_number})\n"
            f"  환자 이름        = {patient.pii.name}\n"
            f"  specimen_id      = {specimen.pk}  ({specimen.specimen_label})\n"
            f"  accession_status = {specimen.accession_status}\n"
            f"  assigned_to      = {specimen.assigned_to}\n"
            f"  study_id(이력용) = {study.pk}  (performed_at={study.performed_at})\n"
            "\n"
            "확인할 곳:\n"
            f"  GET /api/v1/specimens/queue?status=bound&assigned=none"
            f" 에 specimen_id={specimen.pk} 가 떠야 한다\n"
            f"  GET /api/v1/patients/{patient.pk}/timeline 에 "
            "\"촬영\" · \"검체 채취\" 두 줄이 있어야 한다\n"
        ))
