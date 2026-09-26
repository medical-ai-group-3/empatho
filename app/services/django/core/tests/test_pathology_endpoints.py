# -*- coding: utf-8 -*-
"""병리과 API 7종 — 접수 대기 큐 → 집기 → 상세 → 업로드 목록 → AI 분석
시작 → 임시저장 → 확정. amend(정정)는 확정 사양서 §8-2 에 따라 없다
(확정 후 오류는 새 검체로 처리한다).

run_inference.delay() 는 mock 한다 — 로컬엔 redis 브로커가 없어
(SpecimenAiResultView 가 .delay() 를 try/except 없이 그대로 부르므로)
진짜로 부르면 ConnectionError 로 요청 자체가 죽는다. 이건 pathology.py
가 아니라 브로커 연결 문제라 여기 테스트 범위 밖이다."""
from datetime import date
from unittest.mock import patch

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


class PathologyEndpointsTests(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="pathology-endpoints-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.account, staff_number="PAT-100", full_name="병리 엔드포인트 테스트",
        )
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(self.account))

        self.patient = Patient.objects.create(patient_number="P-PATH-EP-001")
        PatientPii.objects.create(
            patient=self.patient, name="병리엔드포인트환자", birth_date=date(1988, 4, 4),
            phone="010-2020-3030",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="diagnostic", ordered_by=self.account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="bound",
            collected_at="2026-09-01T00:00:00Z",
        )

    def test_1_queue_lists_unassigned_specimen(self):
        response = self.client.get("/api/v1/specimens/queue?assigned=none")
        self.assertEqual(response.status_code, 200)
        ids = [row["specimen_id"] for row in response.json()["data"]["results"]]
        self.assertIn(self.specimen.pk, ids)

    def test_2_assign_picks_up_specimen(self):
        response = self.client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/assign", {}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.specimen.refresh_from_db()
        self.assertEqual(self.specimen.assigned_to, self.account.staff)

        # 09-26 확인 — 집으면 accession_status 도 accessioned 로 올라간다.
        # 이걸 안 하면 확진까지 끝난 검체도 "전체 환자 목록" 진행상황 칸에
        # 영원히 "접수 대기"(bound)로 남는다.
        self.assertEqual(self.specimen.accession_status, "accessioned")
        self.assertIsNotNone(self.specimen.accessioned_at)

        # 두 번째 집기는 409.
        other = Account.objects.create(
            login_id="pathology-endpoints-test-2", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=other, staff_number="PAT-101", full_name="병리2")
        other_client = APIClient()
        other_client.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(other))
        response = other_client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/assign", {}, format="json",
        )
        self.assertEqual(response.status_code, 409)

    def test_3_detail_returns_specimen(self):
        response = self.client.get(f"/api/v1/specimens/{self.specimen.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["specimen_id"], self.specimen.pk)

    def test_4_upload_list_empty_when_no_crops(self):
        response = self.client.get(f"/api/v1/specimens/{self.specimen.pk}/upload")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["specimen_id"], self.specimen.pk)
        self.assertEqual(response.json()["data"]["uploads"], [])

    @patch("core.views.pathology.run_inference")
    def test_5_ai_results_start_creates_ai_result_per_crop(self, mock_run_inference):
        from core.models import StorageObject

        StorageObject.objects.create(specimen=self.specimen, bucket="b", object_key="k1")
        StorageObject.objects.create(specimen=self.specimen, bucket="b", object_key="k2")

        response = self.client.post(
            f"/api/v1/specimens/{self.specimen.pk}/ai-results", {}, format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(mock_run_inference.delay.call_count, 2)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["specimen"], self.specimen.pk)
            self.assertIsNone(row["study"])

    def test_6_draft_saves_b_category_separately_from_diagnosis(self):
        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"diagnosis": "malignant", "b_category": "b5", "finding_note": "임시 소견"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.specimen.refresh_from_db()
        self.assertEqual(self.specimen.diagnosis, "malignant")
        self.assertEqual(self.specimen.b_category, "b5")
        self.assertIsNone(self.specimen.finalized_at)

    def test_7_finalize_requires_both_diagnosis_and_b_category(self):
        response = self.client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"diagnosis": "malignant"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"diagnosis": "malignant", "b_category": "b5", "finding_note": "확정 소견"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.specimen.refresh_from_db()
        self.assertIsNotNone(self.specimen.finalized_at)

    def test_amend_endpoint_no_longer_exists(self):
        response = self.client.post(
            f"/api/v1/specimens/{self.specimen.pk}/amend",
            {"diagnosis": "benign", "b_category": "b2", "amend_reason": "정정 사유"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    @patch("core.views.pathology.run_inference")
    def test_ai_result_does_not_set_specimen_b_category(self, mock_run_inference):
        # AI 는 양성/악성만 낸다 — b_category 는 사람이 draft/finalize 로만 채운다.
        from core.models import StorageObject

        StorageObject.objects.create(specimen=self.specimen, bucket="b", object_key="k1")
        self.client.post(f"/api/v1/specimens/{self.specimen.pk}/ai-results", {}, format="json")
        self.specimen.refresh_from_db()
        self.assertIsNone(self.specimen.b_category)
