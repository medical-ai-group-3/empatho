# -*- coding: utf-8 -*-
"""09-18 일운님 지적: MATRIX 칸(study/assessment/specimen_pathology:U, report:U)
만으로 판독 확정·잠금해제를 걸면, 관리자가 격자에서 그 칸을 다른 역할에
체크하거나 staff.extra_permissions 로 개인에게 더해주는 순간 엉뚱한
부서도 확정·해제를 할 수 있다. MATRIX 는 그대로 두고 IsRole 을 얹어
부서 자체를 잠근다."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    Assessment,
    ExamOrder,
    Lesion,
    Patient,
    PatientPii,
    Report,
    Specimen,
    Staff,
    Study,
)


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class FinalizeRoleLockTests(TestCase):
    def setUp(self):
        self.radiology_account = Account.objects.create(
            login_id="radiology-lock-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-001", full_name="영상 테스트",
        )
        # study:U 를 개인 그랜트로 받은 원무 계정 — 역할 자체는 reception.
        self.reception_account = Account.objects.create(
            login_id="reception-extra-study-u", role="reception",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.reception_account, staff_number="REC-EXTRA-001",
            full_name="원무 테스트(추가권한)",
            extra_permissions={"study": ["U"], "assessment": ["U", "C"]},
        )

        self.patient = Patient.objects.create(patient_number="P-LOCK-001")
        PatientPii.objects.create(
            patient=self.patient, name="잠금테스트환자", birth_date=date(1992, 2, 2),
            phone="010-8888-8888",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.radiology_account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        self.assessment = Assessment.objects.create(
            study=self.study, read_stage="draft", category="4a",
        )

    def test_reception_with_extra_study_u_still_blocked_from_finalize(self):
        client = _client_for(self.reception_account)
        response = client.patch(f"/api/v1/studies/{self.study.pk}/finalize", {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FINALIZE_ROLE_ONLY_RADIOLOGY")

    def test_reception_with_extra_assessment_u_still_blocked_from_draft(self):
        client = _client_for(self.reception_account)
        response = client.put(
            f"/api/v1/studies/{self.study.pk}/assessment/draft",
            {"finding_note": "x", "category": "4a"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FINALIZE_ROLE_ONLY_RADIOLOGY")

    def test_reception_with_extra_assessment_u_still_blocked_from_amend(self):
        client = _client_for(self.reception_account)
        response = client.post(
            f"/api/v1/assessments/{self.assessment.pk}/amend",
            {"decision_reason": "x", "category": "4b", "finding_note": "y"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FINALIZE_ROLE_ONLY_RADIOLOGY")

    def test_radiology_can_still_draft_and_finalize(self):
        client = _client_for(self.radiology_account)
        r = client.put(
            f"/api/v1/studies/{self.study.pk}/assessment/draft",
            {"finding_note": "우측 mass", "category": "4a"}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        r = client.patch(f"/api/v1/studies/{self.study.pk}/finalize", {}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_upload_review_still_open_regardless_of_finalize_lock(self):
        # 업로드 품질승인은 이번 잠금 대상이 아니다 — 영상의학이면 그대로 열려야 한다.
        client = _client_for(self.radiology_account)
        response = client.patch(
            f"/api/v1/radiology/studies/{self.study.pk}/upload",
            {"quality_status": "accepted"}, format="json",
        )
        self.assertEqual(response.status_code, 200)


class PathologyFinalizeRoleLockTests(TestCase):
    def setUp(self):
        self.pathology_account = Account.objects.create(
            login_id="pathology-lock-test", role="pathology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.pathology_account, staff_number="PAT-001", full_name="병리 테스트",
        )
        self.surgery_account = Account.objects.create(
            login_id="surgery-extra-specimen-u", role="surgery",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.surgery_account, staff_number="SUR-EXTRA-001",
            full_name="유방외과 테스트(추가권한)",
            extra_permissions={"specimen_pathology": ["U", "C"]},
        )

        self.patient = Patient.objects.create(patient_number="P-LOCK-002")
        PatientPii.objects.create(
            patient=self.patient, name="병리잠금테스트", birth_date=date(1975, 5, 5),
            phone="010-7777-9999",
        )
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.pathology_account.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
        )
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="accessioned",
        )

    def test_surgery_with_extra_specimen_u_blocked_from_finalize(self):
        client = _client_for(self.surgery_account)
        response = client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"b_category": "b2", "diagnosis": "benign"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FINALIZE_ROLE_ONLY_PATHOLOGY")

    def test_surgery_with_extra_specimen_u_blocked_from_draft(self):
        client = _client_for(self.surgery_account)
        response = client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"b_category": "b2", "diagnosis": "benign"}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "FINALIZE_ROLE_ONLY_PATHOLOGY")

    def test_pathology_can_still_draft_and_finalize(self):
        client = _client_for(self.pathology_account)
        r = client.put(
            f"/api/v1/specimens/{self.specimen.pk}/draft",
            {"b_category": "b2", "diagnosis": "benign"}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        r = client.patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize",
            {"b_category": "b2", "diagnosis": "benign"}, format="json",
        )
        self.assertEqual(r.status_code, 200)


class ReportUnlockRoleLockTests(TestCase):
    def setUp(self):
        self.surgery_account = Account.objects.create(
            login_id="surgery-unlock-test", role="surgery",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.surgery_account, staff_number="SUR-002", full_name="유방외과 테스트2",
        )
        # report:U 를 개인 그랜트로 받은 간호 계정.
        self.nursing_account = Account.objects.create(
            login_id="nursing-extra-report-u", role="nursing",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.nursing_account, staff_number="NUR-EXTRA-001",
            full_name="간호 테스트(추가권한)",
            extra_permissions={"report": ["U"]},
        )

        self.patient = Patient.objects.create(patient_number="P-LOCK-003")
        PatientPii.objects.create(
            patient=self.patient, name="리포트잠금테스트", birth_date=date(1980, 3, 3),
            phone="010-6666-5555",
        )
        self.report = Report.objects.create(patient=self.patient, lock_status="locked")

    def test_nursing_with_extra_report_u_still_blocked_from_unlock(self):
        client = _client_for(self.nursing_account)
        response = client.patch(
            f"/api/v1/reports/{self.report.pk}/unlock", {}, format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "UNLOCK_ROLE_ONLY_SURGERY")

    def test_unlock_status_still_open_to_nursing(self):
        # unlock-status 는 이번 잠금 대상이 아니다 — R 권한이 있으면 그대로 조회 가능.
        client = _client_for(self.nursing_account)
        response = client.get(f"/api/v1/reports/{self.report.pk}/unlock-status")
        self.assertEqual(response.status_code, 200)
