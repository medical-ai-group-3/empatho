"""문진 v2 와, 문진이 화면까지 닿는 두 자리.

⚠ 2026-09-28 — 화면이 읽는데 서버가 안 주던 칸 둘을 메웠다. 둘 다 오류가
  안 나고 **조용히 빈칸**이 되던 종류라, 눈으로 보기 전에는 몰랐다.

    patient.family_history   유방외과 목록·결정 화면의 가족력 칩
    assigned_to_name         영상의학·병리 목록의 담당자 이름
"""
from django.test import TestCase
from rest_framework.test import APIClient

from core import models, serializers
from core.api import questionnaire as qm


class QuestionnaireV2Tests(TestCase):
    def test_지금_판은_v2_다(self):
        self.assertEqual(qm.CURRENT_VERSION, "v2")
        self.assertEqual(qm.form()["form_version"], "v2")

    def test_옛_판을_지우지_않았다(self):
        """그 판으로 받은 답을 읽어야 한다."""
        self.assertEqual(qm.form("v1")["form_version"], "v1")
        self.assertIn("family_history", qm.form("v1")["questions"])

    def test_v1_의_family_history_가_v2_에서도_같은_뜻이다(self):
        """코드도 선택지 id 도 안 바꿨다 — 바꾸면 옛 답의 뜻이 달라진다."""
        old = qm.form("v1")["questions"]["family_history"]["options"]
        new = qm.form("v2")["questions"]["family_history"]["options"]

        self.assertEqual(set(old), set(new))

    def test_모르는_선택지는_막는다(self):
        from core.api.errors import ApiError

        with self.assertRaises(ApiError):
            qm.validate({"lump": "없는값"})

    def test_덜_채운_것은_통과한다(self):
        """간호가 나중에 보완하는 경로가 있다."""
        out = qm.validate({"lump": "left"})

        self.assertEqual(out["form_version"], "v2")
        self.assertEqual(out["answers"], {"lump": "left"})


class PatientFamilyHistoryTests(TestCase):
    """화면은 patient.family_history 를 평평한 칸으로 읽는다 — 값은 문진
    JSON 안에 있다. 서버가 꺼내서 **한글로** 내려준다(화면이 값을 그대로
    찍는 자리라 날것을 주면 「가족력 · yes」가 뜬다)."""

    def _patient(self, questionnaire):
        p = models.Patient.objects.create(patient_number="P-FH-%s" % id(questionnaire),
                                          sex="F")
        p.questionnaire = questionnaire
        p.save(update_fields=["questionnaire"])
        return p

    def _read(self, p):
        return serializers.PatientSerializer(p).data["family_history"]

    def test_답을_한글로_내려준다(self):
        p = self._patient({"form_version": "v2",
                           "answers": {"family_history": "yes"}})

        self.assertEqual(self._read(p), "있다")

    def test_옛_판_답도_그_판으로_읽는다(self):
        p = self._patient({"form_version": "v1",
                           "answers": {"family_history": "unknown"}})

        self.assertEqual(self._read(p), "모른다")

    def test_문진이_없으면_비운다(self):
        """화면이 H.some() 으로 걸러 칩을 안 그린다."""
        for q in (None, {}, {"answers": {}}, {"answers": {"family_history": "zzz"}}):
            with self.subTest(str(q)[:30]):
                self.assertIsNone(self._read(self._patient(q)))


class AssignedToNameTests(TestCase):
    """assigned_to 는 FK 라 번호로만 나갔다. 목록은 이름을 찍는다."""

    def setUp(self):
        account = models.Account.objects.create(login_id="rad_assign", role="radiology",
                                                account_status="active", is_active=True)
        self.staff = models.Staff.objects.create(account=account, full_name="김영상",
                                                 staff_number="S-RAD-9")
        self.patient = models.Patient.objects.create(patient_number="P-ASSIGN-1", sex="F")

    def _order(self, **kw):
        """⚠ exam_order_requested_fields_ck — ordered 로 세우려면 modality ·
        exam_purpose · ordered_by 가 다 있어야 한다."""
        return models.ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.staff, **kw)

    def test_검사_오더에_담당자_이름이_실린다(self):
        order = self._order(assigned_to=self.staff)

        data = serializers.ExamOrderSerializer(order).data
        self.assertEqual(data["assigned_to_name"], "김영상")
        self.assertEqual(data["assigned_to"], self.staff.pk)   # 번호도 그대로 남는다

    def test_안_집힌_오더는_비어_있다(self):
        self.assertIsNone(
            serializers.ExamOrderSerializer(self._order()).data["assigned_to_name"])

    def test_검체에도_실린다(self):
        # 검체는 병변에 매달린다 — 병변은 검사가, 검사는 오더가 낳는다
        study = models.Study.objects.create(patient=self.patient,
                                            exam_order=self._order(), modality="mammo")
        lesion = models.Lesion.objects.create(patient=self.patient, study=study)
        specimen = models.Specimen.objects.create(patient=self.patient, lesion=lesion,
                                                  specimen_label="S-ASSIGN-1",
                                                  accession_status="bound",
                                                  assigned_to=self.staff)

        self.assertEqual(
            serializers.SpecimenSerializer(specimen).data["assigned_to_name"], "김영상")
