# -*- coding: utf-8 -*-
"""09-18 백엔드 대조 종합 — 다희님 담당 항목.

③ SpecimenSerializer 에 patient_name·age·sex 추가
⑤ PATCH /exam-orders/{id}/confirm 응답이 배열(many=True)이던 것을 단일
   객체로 — 프론트가 done.exam_order_id 를 객체로 읽는데 배열이라 조용히
   undefined 였다
⑨ StudyViewSet 에 검색(?q=)·정렬(?ordering=)·품질 필터 추가. 기본은
   quality_status='rejected' 를 뺀다(재촬영 대상이라 판독 목록에 안 섞임)
"""
from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    ExamOrder,
    Lesion,
    Patient,
    PatientPii,
    Specimen,
    Staff,
    Study,
)


class SpecimenSerializerPatientFieldsTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="pathology-specimen-fields-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=self.account, staff_number="PAT-200", full_name="병리 필드 테스트")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient = Patient.objects.create(patient_number="P-SPEC-FIELD-001", sex="female")
        PatientPii.objects.create(
            patient=self.patient, name="검체필드환자", birth_date=date(1990, 6, 1),
            phone="010-4321-1234",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.account.staff,
        )
        self.study = Study.objects.create(patient=self.patient, exam_order=self.order, modality="mammo")
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="bound",
            collected_at=datetime(2020, 6, 1, tzinfo=dt_timezone.utc),
        )

    def test_specimen_detail_includes_patient_name_age_sex(self):
        response = self.client.get(f"/api/v1/specimens/{self.specimen.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["patient_name"], "검체필드환자")
        self.assertEqual(data["age"], 30)
        self.assertEqual(data["sex"], "female")

    def test_specimen_queue_includes_patient_name_age_sex(self):
        response = self.client.get("/api/v1/specimens/queue")
        self.assertEqual(response.status_code, 200)
        row = response.json()["data"]["results"][0]
        self.assertEqual(row["patient_name"], "검체필드환자")
        self.assertEqual(row["age"], 30)
        self.assertEqual(row["sex"], "female")


class ExamOrderConfirmResponseShapeTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="reception-confirm-shape-test", role="reception",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=self.account, staff_number="REC-200", full_name="원무 confirm 테스트")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient = Patient.objects.create(patient_number="P-CONFIRM-001")
        PatientPii.objects.create(
            patient=self.patient, name="컨펌환자", birth_date=date(1995, 1, 1),
            phone="010-1234-5678",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="requested",
        )

    def test_confirm_returns_single_object_not_array(self):
        response = self.client.patch(
            f"/api/v1/exam-orders/{self.order.pk}/confirm",
            {"scheduled_at": "2026-10-01T09:00:00Z"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertNotIsInstance(data, list)
        self.assertEqual(data["exam_order_id"], self.order.pk)
        self.assertEqual(data["order_status"], "scheduled")


class StudyViewSetFilteringTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="radiology-study-filter-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=self.account, staff_number="RAD-200", full_name="영상 필터 테스트")
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient_a = Patient.objects.create(patient_number="P-FILTER-A")
        PatientPii.objects.create(
            patient=self.patient_a, name="가나다환자", birth_date=date(1980, 1, 1),
            phone="010-1111-0001",
        )
        self.patient_b = Patient.objects.create(patient_number="P-FILTER-B")
        PatientPii.objects.create(
            patient=self.patient_b, name="마바사환자", birth_date=date(1980, 1, 1),
            phone="010-1111-0002",
        )

        def make_study(patient, quality_status, performed_at):
            order = ExamOrder.objects.create(
                patient=patient, order_status="ordered", modality="mammo",
                exam_purpose="screening", ordered_by=self.account.staff,
            )
            return Study.objects.create(
                patient=patient, exam_order=order, modality="mammo",
                quality_status=quality_status, performed_at=performed_at,
            )

        self.accepted_a = make_study(
            self.patient_a, "accepted", datetime(2026, 1, 1, tzinfo=dt_timezone.utc),
        )
        self.accepted_b = make_study(
            self.patient_b, "accepted", datetime(2026, 2, 1, tzinfo=dt_timezone.utc),
        )
        self.rejected_a = make_study(
            self.patient_a, "rejected", datetime(2026, 3, 1, tzinfo=dt_timezone.utc),
        )

    def _ids(self, response):
        return [row["study_id"] for row in response.json()["data"]["results"]]

    def test_rejected_excluded_by_default(self):
        response = self.client.get("/api/v1/studies/")
        self.assertEqual(response.status_code, 200)
        ids = self._ids(response)
        self.assertIn(self.accepted_a.pk, ids)
        self.assertIn(self.accepted_b.pk, ids)
        self.assertNotIn(self.rejected_a.pk, ids)

    def test_status_param_can_still_reach_rejected(self):
        response = self.client.get("/api/v1/studies/?status=rejected")
        ids = self._ids(response)
        self.assertEqual(ids, [self.rejected_a.pk])

    def test_search_by_patient_name(self):
        response = self.client.get("/api/v1/studies/?q=가나다")
        ids = self._ids(response)
        self.assertEqual(ids, [self.accepted_a.pk])

    def test_ordering_by_performed_at_ascending(self):
        response = self.client.get("/api/v1/studies/?ordering=performed_at")
        ids = self._ids(response)
        self.assertEqual(ids, [self.accepted_a.pk, self.accepted_b.pk])

    def test_ordering_default_is_most_recent_first(self):
        response = self.client.get("/api/v1/studies/")
        ids = self._ids(response)
        self.assertEqual(ids, [self.accepted_b.pk, self.accepted_a.pk])
