# -*- coding: utf-8 -*-
"""문진 — 문항 정의 파일과 답변 검증.

문항을 표가 아니라 버전 붙인 yaml 로 둔다. 선택지 id 가 고정이라 과거 답변의
뜻이 바뀌지 않는다.
"""

from django.test import SimpleTestCase, TestCase

from core.api import questionnaire as q
from core.api.errors import ApiError
from core.models import Account, ExamOrder, Patient, Staff


class FormDefinitionTests(SimpleTestCase):
    def test_판을_읽는다(self):
        self.assertEqual(q.form()["form_version"], "v2")

    def test_네_묶음_문항이_들어_있다(self):
        """증상 · 호르몬 · 임신 · 과거력."""
        codes = set(q.form()["questions"])
        self.assertLessEqual(
            {"lump", "nipple_discharge", "breast_pain",
             "menstrual_status", "hrt", "oral_contraceptive",
             "parity", "breastfeeding",
             "benign_breast_disease", "cancer_history", "family_history"},
            codes)

    def test_옛_판도_그대로_읽힌다(self):
        """v1 파일을 지우지 않는다 — 그 판으로 받은 답을 읽어야 한다."""
        self.assertEqual(q.form("v1")["form_version"], "v1")
        self.assertIn("has_symptom", q.form("v1")["questions"])

    def test_선택지에_id_와_문구가_둘_다_있다(self):
        options = q.form()["questions"]["menstrual_status"]["options"]
        self.assertEqual(set(options), {"active", "natural_menopause", "induced"})
        self.assertTrue(all(text for text in options.values()))

    def test_화면용_문항은_켜진_것만_준다(self):
        for item in q.active_questions():
            self.assertIn("code", item)
            self.assertTrue(item["options"])

    def test_없는_판을_찾으면_막힌다(self):
        with self.assertRaises(ApiError) as caught:
            q.form("v99")
        self.assertEqual(caught.exception.code, "INTERNAL_ERROR")


class ValidateTests(SimpleTestCase):
    def test_답변을_감싸_돌려준다(self):
        got = q.validate({"lump": "left"})
        self.assertEqual(got, {"form_version": "v2",
                               "answers": {"lump": "left"}})

    def test_form_version_은_서버가_찍는다(self):
        # 앱이 보낸 값이 있어도 무시한다 — 옛 앱이 새 문항에 옛 판을 붙이는 것을
        # 막을 방법이 그것뿐이다.
        got = q.validate({"lump": "none"})
        self.assertEqual(got["form_version"], "v2")
        self.assertNotIn("form_version", got["answers"])

    def test_덜_채워도_통과한다(self):
        # 간호가 나중에 보완하는 경로(§3.12)가 있다
        self.assertEqual(q.validate({})["answers"], {})

    def test_모르는_문항은_막힌다(self):
        with self.assertRaises(ApiError) as caught:
            q.validate({"없는문항": "yes"})
        self.assertEqual(caught.exception.code, "VALIDATION_ERROR")
        self.assertIn("없는문항", caught.exception.details["unknown_code"])

    def test_모르는_선택지는_막힌다(self):
        with self.assertRaises(ApiError) as caught:
            q.validate({"menstrual_status": "아무거나"})
        problem = caught.exception.details["unknown_option"][0]
        self.assertEqual(problem["code"], "menstrual_status")
        self.assertIn("natural_menopause", problem["allowed"])

    def test_객체가_아니면_막힌다(self):
        for bad in ("문자열", ["목록"], 3, None):
            with self.assertRaises(ApiError):
                q.validate(bad)

    def test_여러_문제를_한_번에_알려준다(self):
        with self.assertRaises(ApiError) as caught:
            q.validate({"없는문항": "x", "menstrual_status": "틀린값"})
        self.assertIn("unknown_code", caught.exception.details)
        self.assertIn("unknown_option", caught.exception.details)


class StorageTests(TestCase):
    """진실은 exam_order, patient 는 최신 1건 캐시."""

    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        staff = Staff.objects.create(
            account=Account.objects.create(login_id="nur1", role="nursing",
                                           is_active=True),
            full_name="이간호")
        cls.order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=staff)

    def test_방문마다_한_벌이라_이력이_남는다(self):
        second = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="us",
            exam_purpose="diagnostic", ordered_by=self.order.ordered_by)

        self.order.questionnaire = q.validate({"lump": "none"})
        self.order.save()
        second.questionnaire = q.validate({"lump": "left"})
        second.save()

        # 예전 구조에서는 덮어써서 첫 번째가 사라졌다
        self.assertEqual(self.order.questionnaire["answers"]["lump"], "none")
        self.assertEqual(second.questionnaire["answers"]["lump"], "left")

    def test_patient_는_최신_것을_들고_있는다(self):
        answered = q.validate({"lump": "left"})
        self.order.questionnaire = answered
        self.order.save()
        self.patient.questionnaire = answered
        self.patient.save()

        self.patient.refresh_from_db()
        self.assertEqual(self.patient.questionnaire, self.order.questionnaire)

    def test_저장된_판을_나중에_읽을_수_있다(self):
        self.order.questionnaire = q.validate({"menstrual_status": "natural_menopause"})
        self.order.save()
        self.order.refresh_from_db()
        stored = self.order.questionnaire
        # 판이 있어야 그때 문항 뜻을 되짚을 수 있다
        self.assertEqual(stored["form_version"], "v2")
        self.assertEqual(
            q.form(stored["form_version"])["questions"]["menstrual_status"]
            ["options"][stored["answers"]["menstrual_status"]], "자연 폐경했다")

    def test_v1_로_받은_옛_답도_그_판으로_읽힌다(self):
        """판을 올려도 과거 문진의 뜻이 바뀌지 않는다 — 이 설계의 요점이다.
        v1 로 저장된 행은 DB 에 남아 있을 수 있다(앱이 먼저 올라가기 전에
        받은 것)."""
        self.order.questionnaire = q.validate({"menopause_status": "post"},
                                              version="v1")
        self.order.save()
        self.order.refresh_from_db()
        stored = self.order.questionnaire

        self.assertEqual(stored["form_version"], "v1")
        self.assertEqual(
            q.form(stored["form_version"])["questions"]["menopause_status"]
            ["options"][stored["answers"]["menopause_status"]], "폐경 후")
