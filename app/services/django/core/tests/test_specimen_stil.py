# -*- coding: utf-8 -*-
"""sTIL(임상 수치) 표시 방식 변경 — 09-28 결정.

병리의가 검체 단위로 직접 입력하는 stil_calibrated 를 draft/finalize
요청 바디로 받는다. AI 원시값(stil_percent, AiResult.result 안)은 이
칸을 안 건드린다 — 병리의 입력과 AI 계측값은 척도가 다르다.

    저장   Specimen.stil_calibrated, 값이 오면 stil_source="manual"
    응답   SpecimenSerializer 에 stil_calibrated · stil_source 그대로 노출
    권한   draft/finalize 둘 다 CanFinalizePathologyRead(병리과 단독)
    stil_level  계산 안 함 — null 로 남는다
"""
from datetime import date
from unittest.mock import patch

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


class SpecimenStilTests(TestCase):
    def setUp(self):
        self.pathology_account = Account.objects.create(
            login_id="stil-pathology-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.pathology_account, staff_number="PAT-STIL-001", full_name="sTIL 테스트",
        )
        self.radiology_account = Account.objects.create(
            login_id="stil-radiology-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-STIL-001", full_name="sTIL 무관 테스트",
        )

        self.patient = Patient.objects.create(patient_number="P-STIL-001")
        PatientPii.objects.create(
            patient=self.patient, name="sTIL테스트환자", birth_date=date(1985, 3, 3),
            phone="010-7777-0001",
        )
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="diagnostic", ordered_by=self.pathology_account.staff,
        )
        study = Study.objects.create(patient=self.patient, exam_order=order, modality="mammo")
        lesion = Lesion.objects.create(patient=self.patient, study=study)
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=lesion, accession_status="bound",
            collected_at="2026-09-20T00:00:00Z",
        )
        self.client = _client_for(self.pathology_account)

    # ── 저장 ────────────────────────────────────────────────────

    def test_draft_saves_stil_calibrated_and_sets_manual_source(self):
        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"b_category": "b4", "diagnosis": "malignant", "stil_calibrated": "42.5"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        # ⚠ 모델 필드가 decimal_places=2 라(레거시 컬럼) 응답·저장 값은
        # 항상 소수 2자리로 나온다 — 입력은 1자리로 검증되지만 표시 자릿수는
        # 다르다. 입력 계약(소수 1자리)은 위의 범위 검증 테스트가 잡는다.
        self.assertEqual(data["stil_calibrated"], "42.50")
        self.assertEqual(data["stil_source"], "manual")
        self.assertIsNone(data["stil_level"])   # 계산하지 않는다

        self.specimen.refresh_from_db()
        self.assertEqual(str(self.specimen.stil_calibrated), "42.50")
        self.assertEqual(self.specimen.stil_source, "manual")
        self.assertIsNone(self.specimen.stil_level)

    def test_finalize_saves_stil_calibrated_and_sets_manual_source(self):
        response = self.client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"b_category": "b5", "diagnosis": "malignant", "finding_note": "확정",
             "stil_calibrated": "10.0"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["stil_calibrated"], "10.00")
        self.assertEqual(data["stil_source"], "manual")

    def test_stil_calibrated_omitted_does_not_touch_existing_value(self):
        self.specimen.stil_calibrated = "30.0"
        self.specimen.stil_source = "manual"
        self.specimen.save()

        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"b_category": "b3", "diagnosis": "benign"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.specimen.refresh_from_db()
        self.assertEqual(str(self.specimen.stil_calibrated), "30.00")
        self.assertEqual(self.specimen.stil_source, "manual")

    # ── 범위 검증 ────────────────────────────────────────────────

    def test_stil_calibrated_above_100_rejected(self):
        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"stil_calibrated": "100.1"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_stil_calibrated_negative_rejected(self):
        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"stil_calibrated": "-0.1"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_stil_calibrated_boundary_values_accepted(self):
        for value in ("0", "100", "0.0", "100.0"):
            response = self.client.put(
                f"/api/v1/specimens/{self.specimen.pk}/draft",
                {"stil_calibrated": value}, format="json",
            )
            self.assertEqual(response.status_code, 200, value)

    def test_stil_calibrated_two_decimal_places_rejected(self):
        # 프론트 계약은 소수 1자리다 — 2자리는 거부한다.
        response = self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"stil_calibrated": "42.55"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    # ── 권한 ────────────────────────────────────────────────────

    def test_non_pathology_role_cannot_draft(self):
        other_client = _client_for(self.radiology_account)
        response = other_client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"stil_calibrated": "20.0"}, format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_non_pathology_role_cannot_finalize(self):
        other_client = _client_for(self.radiology_account)
        response = other_client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"b_category": "b5", "diagnosis": "malignant", "stil_calibrated": "20.0"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    # ── AI 재분석이 값을 안 건드리는지 ────────────────────────────

    @patch("core.views.pathology.run_inference")
    def test_ai_reanalysis_does_not_overwrite_manual_stil(self, mock_run_inference):
        self.client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"stil_calibrated": "55.5"}, format="json",
        )
        StorageObject.objects.create(specimen=self.specimen, bucket="b", object_key="k1")

        response = self.client.post(
            f"/api/v1/specimens/{self.specimen.pk}/ai-results", {}, format="json",
        )
        self.assertEqual(response.status_code, 202)

        self.specimen.refresh_from_db()
        self.assertEqual(str(self.specimen.stil_calibrated), "55.50")
        self.assertEqual(self.specimen.stil_source, "manual")

        # AI 결과 자체는 stil_percent 같은 원시값을 result JSON 안에 담을 뿐,
        # Specimen 행을 건드리는 코드가 없다 — 있었다면 위 값이 바뀌었을 것.
        self.assertTrue(AiResult.objects.filter(specimen=self.specimen).exists())
