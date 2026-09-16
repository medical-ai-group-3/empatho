# -*- coding: utf-8 -*-
"""화면 명세 여섯 부서분이 요구한 DB 변경 (0012).

컬럼이 있는지가 아니라 **제약이 실제로 막는지**를 본다. CHECK 은 API 를 안 거치는
admin · Celery 로 들어오는 행도 잡는 마지막 자리라, 코드가 아니라 DB 가 거절하는
것을 확인해야 한다.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.models import (Account, AiResult, Assessment, ExamOrder, Lesion,
                         Patient, Report, Specimen, Staff, Study)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        cls.staff = Staff.objects.create(
            account=Account.objects.create(login_id="rad1", role="radiology",
                                           is_active=True),
            full_name="김판독")
        cls.order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=cls.staff)
        cls.study = Study.objects.create(patient=cls.patient,
                                         exam_order=cls.order, modality="mammo")
        cls.ai = AiResult.objects.create(patient=cls.patient, study=cls.study)
        cls.lesion = Lesion.objects.create(study=cls.study, patient=cls.patient,
                                           ai_result=cls.ai)
        cls.specimen = Specimen.objects.create(
            patient=cls.patient, lesion=cls.lesion, specimen_label="S-0001",
            accession_status="bound")

    def blocked(self):
        """DB 가 거절해야 하는 자리."""
        return self.assertRaises(IntegrityError)


class AccountStatusTests(Base):
    """승인 흐름과 로그인 가능 여부를 나눈다."""

    def test_기본은_승인_대기고_로그인은_막혀_있다(self):
        account = Account.objects.create(login_id="new1", role="nursing")
        self.assertEqual(account.account_status, "pending")
        self.assertFalse(account.is_active)

    def test_직원_가입은_대기_환자_가입은_바로_활성(self):
        staff_acc = Account.objects.create(login_id="nur9", role="nursing",
                                           account_status="pending",
                                           is_active=False)
        patient_acc = Account.objects.create(login_id="pat9", role="patient",
                                             account_status="active",
                                             is_active=True)
        self.assertFalse(staff_acc.is_active)
        self.assertTrue(patient_acc.is_active)

    def test_승인하면_둘_다_바뀐다(self):
        account = Account.objects.create(login_id="new2", role="surgery")
        account.account_status = "active"
        account.is_active = True
        account.save()
        account.refresh_from_db()
        self.assertEqual(account.account_status, "active")
        self.assertTrue(account.is_active)

    def test_거절과_정지가_구분된다(self):
        # 한 칸에 담았으면 둘 다 is_active=False 로 뭉쳤을 것이다
        rejected = Account.objects.create(login_id="r1", role="nursing",
                                          account_status="rejected",
                                          is_active=False)
        suspended = Account.objects.create(login_id="s1", role="nursing",
                                           account_status="suspended",
                                           is_active=False)
        self.assertNotEqual(rejected.account_status, suspended.account_status)

    def test_모르는_상태는_DB_가_막는다(self):
        with self.blocked(), transaction.atomic():
            Account.objects.create(login_id="bad1", role="nursing",
                                   account_status="approved")


class AiResultOwnerTests(Base):
    """주인은 검사 아니면 검체, 정확히 하나."""

    def test_병리_결과는_검체에_붙는다(self):
        result = AiResult.objects.create(patient=self.patient,
                                         specimen=self.specimen)
        self.assertIsNone(result.study_id)
        self.assertEqual(result.specimen_id, self.specimen.pk)

    def test_크롭_여러_장이면_행이_여럿이고_검체가_묶는다(self):
        for _ in range(3):
            AiResult.objects.create(patient=self.patient, specimen=self.specimen)
        self.assertEqual(self.specimen.ai_results.count(), 3)

    def test_주인이_없으면_막힌다(self):
        with self.blocked(), transaction.atomic():
            AiResult.objects.create(patient=self.patient)

    def test_주인이_둘이면_막힌다(self):
        with self.blocked(), transaction.atomic():
            AiResult.objects.create(patient=self.patient, study=self.study,
                                    specimen=self.specimen)

    def test_환자는_여전히_필수다(self):
        with self.blocked(), transaction.atomic():
            AiResult.objects.create(study=self.study)


class ReadStageTests(Base):
    """1차 판독 게이트가 없어져 값이 바뀌었다."""

    def test_판독은_임시저장에서_시작한다(self):
        assessment = Assessment.objects.create(study=self.study,
                                               lesion=self.lesion)
        self.assertEqual(assessment.read_stage, "draft")

    def test_없어진_first_는_막힌다(self):
        with self.blocked(), transaction.atomic():
            Assessment.objects.create(study=self.study, lesion=self.lesion,
                                      read_stage="first")

    def test_검사도_pending_draft_finalized_셋뿐이다(self):
        for value in ("pending", "draft", "finalized"):
            study = Study.objects.create(patient=self.patient,
                                         exam_order=self.order,
                                         modality="us", read_status=value)
            self.assertEqual(study.read_status, value)

    def test_없어진_게이트_값은_막힌다(self):
        for value in ("first_locked", "ai_revealed"):
            with self.blocked(), transaction.atomic():
                Study.objects.create(patient=self.patient,
                                     exam_order=self.order,
                                     modality="us", read_status=value)


class CancelReasonTests(Base):
    """영상의학과가 협진 요청을 돌려보낼 때 사유가 남아야 한다."""

    def cancelled(self, **kw):
        base = {"patient": self.patient, "order_status": "cancelled",
                "modality": "mammo", "exam_purpose": "screening",
                "ordered_by": self.staff}
        base.update(kw)
        return ExamOrder.objects.create(**base)

    def test_의료진이_물리면_사유가_남는다(self):
        order = self.cancelled(cancelled_by=self.staff,
                               cancel_reason="조영제 알러지로 촬영 불가")
        self.assertEqual(order.cancelled_by_id, self.staff.pk)

    def test_사유_없이_물리면_DB_가_막는다(self):
        with self.blocked(), transaction.atomic():
            self.cancelled(cancelled_by=self.staff)

    def test_환자_취소는_사유가_없어도_된다(self):
        order = self.cancelled()
        self.assertIsNone(order.cancelled_by_id)
        self.assertIsNone(order.cancel_reason)

    def test_살아_있는_오더에_사유가_붙으면_막힌다(self):
        with self.blocked(), transaction.atomic():
            ExamOrder.objects.create(
                patient=self.patient, order_status="ordered", modality="mammo",
                exam_purpose="screening", ordered_by=self.staff,
                cancel_reason="이러면 안 된다")

    def test_누가_물렸는지_역할로_갈린다(self):
        # notification.staff_id 로 가르던 방식은 거절 주체가 둘이 되면서 깨졌다
        order = self.cancelled(cancelled_by=self.staff, cancel_reason="사유")
        self.assertEqual(order.cancelled_by.account.role, "radiology")


class AssignTests(Base):
    """선착순 집기 — 비어 있는 것이 큐의 조건이다."""

    def test_안_집은_오더가_큐에_남는다(self):
        self.assertIn(self.order,
                      ExamOrder.objects.filter(assigned_to__isnull=True))

    def test_집으면_큐에서_빠진다(self):
        self.order.assigned_to = self.staff
        self.order.save()
        self.assertNotIn(self.order,
                         ExamOrder.objects.filter(assigned_to__isnull=True))
        self.assertIn(self.order, self.staff.assigned_orders.all())

    def test_검체도_같은_구조다(self):
        self.specimen.assigned_to = self.staff
        self.specimen.save()
        self.assertIn(self.specimen, self.staff.assigned_specimens.all())


class LesionModalityTests(Base):
    """v10 에서 빠져 있던 CHECK."""

    def test_아는_모달리티는_들어간다(self):
        for value in ("mammo", "us", "mri"):
            lesion = Lesion.objects.create(study=self.study,
                                           patient=self.patient, modality=value)
            self.assertEqual(lesion.modality, value)

    def test_병리는_병변_모달리티가_아니다(self):
        # 검체가 병변에 붙지 병변이 병리에서 나지 않는다
        with self.blocked(), transaction.atomic():
            Lesion.objects.create(study=self.study, patient=self.patient,
                                  modality="pathology")

    def test_비어_있어도_된다(self):
        lesion = Lesion.objects.create(study=self.study, patient=self.patient)
        self.assertIsNone(lesion.modality)


class ReportViewTests(Base):
    """유방외과 열람 — 화면은 열람/미열람과 정렬만 쓴다."""

    def make(self):
        return Report.objects.create(patient=self.patient, study=self.study,
                                     report_type="final", audience="clinician")

    def test_조회수가_0_에서_시작한다(self):
        # nullable 이면 F('view_count') + 1 이 NULL 에 더해져 계속 NULL 이다
        self.assertEqual(self.make().view_count, 0)

    def test_조회수를_올릴_수_있다(self):
        from django.db.models import F

        report = self.make()
        Report.objects.filter(pk=report.pk).update(view_count=F("view_count") + 1)
        report.refresh_from_db()
        self.assertEqual(report.view_count, 1)

    def test_미열람은_두_칸이_다_비어_있다(self):
        report = self.make()
        self.assertIsNone(report.last_viewed_at)
        self.assertIsNone(report.last_viewed_by_id)

    def test_열람하면_시각과_사람이_남는다(self):
        report = self.make()
        report.last_viewed_at = timezone.now()
        report.last_viewed_by = self.staff
        report.save()
        report.refresh_from_db()
        self.assertEqual(report.last_viewed_by_id, self.staff.pk)


class SpecimenAmendTests(Base):
    """검체는 물건이라 행을 늘릴 수 없다 — 옛 값을 배열에 민다."""

    def test_정정하면_옛_값이_배열에_쌓인다(self):
        self.specimen.diagnosis = "benign"
        self.specimen.b_category = "b2"
        self.specimen.save()

        self.specimen.amend_history = [{
            "diagnosis": "benign", "b_category": "b2",
            "amend_reason": "면역염색 재확인", "amended_at": "2026-09-15T10:00:00Z"}]
        self.specimen.diagnosis = "malignant"
        self.specimen.b_category = "b5"
        self.specimen.save()
        self.specimen.refresh_from_db()

        self.assertEqual(self.specimen.diagnosis, "malignant")
        self.assertEqual(self.specimen.amend_history[0]["diagnosis"], "benign")

    def test_행이_하나로_유지된다(self):
        # 새 행을 만들면 specimen_label UK 와 discordance_flag 링크가 깨진다
        self.assertEqual(
            Specimen.objects.filter(specimen_label="S-0001").count(), 1)

    def test_의뢰_문구를_담는다(self):
        self.specimen.clinical_note = "좌측 상외측 유방에 만져지는 종괴로 조직검사 의뢰합니다"
        self.specimen.save()
        self.specimen.refresh_from_db()
        self.assertIn("조직검사", self.specimen.clinical_note)


class ReceptionTests(Base):
    """원무 — 초진/재진은 created_at 으로는 안 갈린다."""

    def test_처음_접수하면_찍힌다(self):
        self.assertIsNone(self.patient.first_visited_at)
        self.patient.first_visited_at = timezone.now()
        self.patient.save()
        self.patient.refresh_from_db()
        self.assertIsNotNone(self.patient.first_visited_at)

    def test_앱_가입만_한_환자는_비어_있다(self):
        # 앱을 먼저 가입하고 나중에 오는 경우가 있어 created_at 으로는 어긋난다
        app_only = Patient.objects.create(patient_number="E_2000001")
        self.assertIsNone(app_only.first_visited_at)
        self.assertIsNotNone(app_only.created_at)

    def test_요청의견서를_담는다(self):
        self.order.order_note = "좌측 종괴 의심, 초음파 병행 요청"
        self.order.save()
        self.order.refresh_from_db()
        self.assertIn("초음파", self.order.order_note)
