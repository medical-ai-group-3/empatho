# -*- coding: utf-8 -*-
"""주요 표 일곱의 admin 목록이 실제로 그려지는가.

manage.py check 는 필드 **이름**만 본다. 목록을 실제로 뽑으면 select_related
경로가 틀렸거나 display 함수가 None 을 못 받는 것 같은 것이 드러난다 —
그건 관리자가 화면을 열어야 알게 되는 종류다.
"""

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from core.models import (
    AiResult, DiscordanceFlag, ExamOrder, Lesion, Patient, PatientPii, Report,
    Specimen, Study,
)

SEVEN = (Patient, ExamOrder, Study, AiResult, Specimen, DiscordanceFlag, Report)


class TableAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser(
            username="cdss_admin", password="x")

        # 칸이 비어 있어도 목록이 그려져야 한다 — 실제로 대부분의 칸이 흐름
        # 중간에는 NULL 이다
        cls.patient = Patient.objects.create(patient_number="P-ADMIN-1")
        PatientPii.objects.create(patient=cls.patient, name="관리시험",
                                  phone="010-0000-0001")
        cls.order = ExamOrder.objects.create(patient=cls.patient,
                                             order_status="requested")
        cls.study = Study.objects.create(patient=cls.patient,
                                         exam_order=cls.order, modality="mammo")
        # 검체는 병변에서 나온다 — specimen.lesion 이 NOT NULL 이다
        cls.lesion = Lesion.objects.create(patient=cls.patient, study=cls.study)
        cls.specimen = Specimen.objects.create(patient=cls.patient,
                                               lesion=cls.lesion,
                                               specimen_label="S-ADMIN-1",
                                               accession_status="unbound")
        cls.report = Report.objects.create(patient=cls.patient,
                                           study=cls.study)
        # study XOR specimen 이다 (0012 의 ai_result_owner_ck) — 둘 다 주면 막힌다
        cls.ai = AiResult.objects.create(patient=cls.patient, study=cls.study,
                                         run_status="done")
        cls.flag = DiscordanceFlag.objects.create(specimen=cls.specimen)

    def _changelist(self, model, query=""):
        req = RequestFactory().get(f"/admin/core/{model._meta.model_name}/{query}")
        req.user = self.boss
        model_admin = site._registry[model]
        return model_admin, model_admin.get_changelist_instance(req), req

    def test_일곱_표가_전부_손으로_꾸며져_있다(self):
        """기본 등록(ModelAdmin 그대로)이면 목록이 'Patient object (1)' 로만
        나온다. 꾸민 것으로 바뀌었는지 본다."""
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                self.assertIn(model, site._registry)
                self.assertNotEqual(type(site._registry[model]).__name__,
                                    "ModelAdmin", model.__name__)

    def test_목록이_실제로_그려진다(self):
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                model_admin, changelist, req = self._changelist(model)
                rows = list(changelist.get_queryset(req))
                self.assertEqual(len(rows), 1, model.__name__)
                # list_display 의 모든 칸을 실제로 불러 본다
                for name in model_admin.list_display:
                    value = getattr(model_admin, name, None)
                    if callable(value):
                        value(rows[0])          # 여기서 터지면 화면도 터진다
                    else:
                        getattr(rows[0], name)

    def test_환자번호로_찾을_수_있다(self):
        """관리자가 들고 오는 것은 거의 언제나 환자번호다."""
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                _, changelist, req = self._changelist(model, "?q=P-ADMIN-1")
                self.assertEqual(len(list(changelist.get_queryset(req))), 1,
                                 model.__name__)

    def test_환자_이름으로도_찾을_수_있다(self):
        """이름은 patient_pii 에 있다. 목록 칸으로는 안 내보내고 검색으로만 닿게 한다."""
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                _, changelist, req = self._changelist(model, "?q=관리시험")
                self.assertEqual(len(list(changelist.get_queryset(req))), 1,
                                 model.__name__)

    def test_필터가_실제로_건다(self):
        for model in SEVEN:
            model_admin = site._registry[model]
            with self.subTest(model=model.__name__):
                self.assertTrue(model_admin.list_filter, model.__name__)
                _, changelist, req = self._changelist(model)
                # 필터 명세가 틀리면 여기서 예외가 난다
                self.assertIsNotNone(changelist.get_filters(req))

    def test_지우기를_막는다(self):
        """전부 PROTECT 로 얽혀 있어 한 줄을 지우면 어디가 끊길지 화면에서는
        안 보인다. 임상 기록은 지우는 것이 아니라 상태로 물린다."""
        req = RequestFactory().get("/")
        req.user = self.boss
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                self.assertFalse(
                    site._registry[model].has_delete_permission(req),
                    model.__name__)

    def test_감사_칸은_읽기_전용이다(self):
        for model in SEVEN:
            with self.subTest(model=model.__name__):
                ro = site._registry[model].readonly_fields
                for field in ("created_by", "updated_by", "created_at", "updated_at"):
                    self.assertIn(field, ro, f"{model.__name__}.{field}")

    def test_환자_이름이_목록_칸에는_없다(self):
        """개인정보라 목록을 열면 전부 보이는 것과 아는 이름을 쳐서 찾는 것은 다르다.
        환자 표 자신만 예외다 — 거기서는 이름이 그 행의 정체다."""
        for model in SEVEN:
            if model is Patient:
                continue
            with self.subTest(model=model.__name__):
                self.assertNotIn("name", site._registry[model].list_display)
