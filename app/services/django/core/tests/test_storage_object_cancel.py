# -*- coding: utf-8 -*-
"""PATCH /storage-objects/{id}/cancel — 업로드 취소(조건부 soft-delete).

분석(AiResult) 시작 전에는 취소가 되고, 시작 후에는 409 다. study 소유
(영상의학과)와 specimen 소유(병리과) 둘 다 같은 경로 하나를 쓴다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    AiResult,
    ExamOrder,
    Lesion,
    Patient,
    PatientPii,
    Specimen,
    Staff,
    StorageObject,
    Study,
)


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class StorageObjectCancelPathologyTests(TestCase):
    """specimen 소유 파일 — 병리과만 취소할 수 있다."""

    def setUp(self):
        self.pathology_account = Account.objects.create(
            login_id="cancel-path-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.pathology_account, staff_number="PAT-CANCEL-001",
            full_name="병리 취소 테스트",
        )
        self.radiology_account = Account.objects.create(
            login_id="cancel-path-test-rad", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-CANCEL-001",
            full_name="영상 취소 테스트",
        )

        self.patient = Patient.objects.create(patient_number="P-CANCEL-001")
        PatientPii.objects.create(
            patient=self.patient, name="취소테스트환자", birth_date=date(1990, 1, 1),
            phone="010-1111-2222",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="diagnostic", ordered_by=self.radiology_account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="bound",
            collected_at="2026-09-01T00:00:00Z",
        )
        self.storage_object = StorageObject.objects.create(
            specimen=self.specimen, bucket="b", object_key="k1",
        )
        self.client = _client_for(self.pathology_account)

    def test_a_cancel_succeeds_before_analysis(self):
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "잘못 올림"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.storage_object.refresh_from_db()
        self.assertIsNotNone(self.storage_object.deleted_at)
        self.assertEqual(self.storage_object.deleted_by, self.pathology_account)
        self.assertEqual(self.storage_object.delete_reason, "잘못 올림")

    def test_a_cancel_without_reason_still_succeeds(self):
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {}, format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_b_cancel_after_analysis_is_409(self):
        AiResult.objects.create(
            patient=self.patient, specimen=self.specimen,
            source_object=self.storage_object, run_status="queued",
        )
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "뒤늦게 취소"}, format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"],
                         "CANCEL_NOT_ALLOWED_AFTER_ANALYSIS")
        self.storage_object.refresh_from_db()
        self.assertIsNone(self.storage_object.deleted_at)

    def test_c_cancelled_file_excluded_from_upload_list(self):
        self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "잘못 올림"}, format="json",
        )
        response = self.client.get(f"/api/v1/specimens/{self.specimen.pk}/upload")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["uploads"], [])

    def test_c_cancelled_file_excluded_from_analysis_target(self):
        from unittest.mock import patch as mock_patch

        self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "잘못 올림"}, format="json",
        )
        with mock_patch("core.views.pathology.run_inference") as mock_run_inference:
            response = self.client.post(
                f"/api/v1/specimens/{self.specimen.pk}/ai-results", {}, format="json",
            )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["data"], [])
        mock_run_inference.delay.assert_not_called()

    def test_other_department_cannot_cancel(self):
        other_client = _client_for(self.radiology_account)
        response = other_client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "권한 없음"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.storage_object.refresh_from_db()
        self.assertIsNone(self.storage_object.deleted_at)

    def test_cancelling_already_cancelled_file_is_404(self):
        self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "1차 취소"}, format="json",
        )
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "2차 취소"}, format="json",
        )
        self.assertEqual(response.status_code, 404)


class StorageObjectCancelRadiologyTests(TestCase):
    """study 소유 파일 — 영상의학과만 취소할 수 있다."""

    def setUp(self):
        self.radiology_account = Account.objects.create(
            login_id="cancel-rad-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-CANCEL-100",
            full_name="영상 취소 테스트2",
        )
        self.pathology_account = Account.objects.create(
            login_id="cancel-rad-test-path", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.pathology_account, staff_number="PAT-CANCEL-100",
            full_name="병리 취소 테스트2",
        )

        self.patient = Patient.objects.create(patient_number="P-CANCEL-100")
        PatientPii.objects.create(
            patient=self.patient, name="영상취소테스트환자", birth_date=date(1991, 2, 2),
            phone="010-3333-4444",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.radiology_account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        self.storage_object = StorageObject.objects.create(
            study=self.study, bucket="b", object_key="rk1",
        )
        self.client = _client_for(self.radiology_account)

    def test_a_cancel_succeeds_before_analysis(self):
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "잘못 올림"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.storage_object.refresh_from_db()
        self.assertIsNotNone(self.storage_object.deleted_at)
        self.assertEqual(self.storage_object.deleted_by, self.radiology_account)

    def test_b_cancel_after_analysis_is_409(self):
        AiResult.objects.create(
            patient=self.patient, study=self.study,
            source_object=self.storage_object, run_status="queued",
        )
        response = self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "뒤늦게 취소"}, format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"],
                         "CANCEL_NOT_ALLOWED_AFTER_ANALYSIS")

    def test_c_cancelled_file_excluded_from_upload_list(self):
        self.client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "잘못 올림"}, format="json",
        )
        response = self.client.get(f"/api/v1/radiology/studies/{self.study.pk}/upload")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["storage_objects"], [])

    def test_other_department_cannot_cancel(self):
        other_client = _client_for(self.pathology_account)
        response = other_client.patch(
            f"/api/v1/storage-objects/{self.storage_object.pk}/cancel",
            {"reason": "권한 없음"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
