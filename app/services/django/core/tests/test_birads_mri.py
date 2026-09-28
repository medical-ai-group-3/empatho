# -*- coding: utf-8 -*-
"""MRI BI-RADS — 세분 없는 「4」.

ACR BI-RADS MRI 는 4 를 4a · 4b · 4c 로 나누지 않는다.
  MRI         0 · 1 · 2 · 3 · 4 · 5 · 6
  맘모 · 초음파  0 · 1 · 2 · 3 · 4a · 4b · 4c · 5 · 6
임시저장 · 확정 · 정정 세 자리가 모두 이 규칙으로 막는다(services/birads.py).
"""
from datetime import date

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core import tasks
from core.api.auth import issue_access
from core.models import (
    Account,
    Assessment,
    DiscordanceFlag,
    ExamOrder,
    Lesion,
    Patient,
    PatientPii,
    Specimen,
    Staff,
    Study,
)
from core.services import birads, discordance


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class _Base(TestCase):
    def setUp(self):
        self.account = Account.objects.create(
            login_id="radiology-birads-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=self.account, staff_number="RAD-B-001",
                             full_name="영상 등급 테스트")
        self.patient = Patient.objects.create(patient_number="P-BIRADS-001", sex="F")
        PatientPii.objects.create(patient=self.patient, name="등급테스트환자",
                                  birth_date=date(1980, 1, 1), phone="010-0000-0000")
        self.client_ = _client_for(self.account)

    def _study(self, modality):
        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality=modality,
            exam_purpose="diagnostic", ordered_by=self.account.staff,
        )
        return Study.objects.create(patient=self.patient, exam_order=order,
                                    modality=modality)

    def _draft(self, study, category, note="소견"):
        return self.client_.put(
            f"/api/v1/studies/{study.pk}/assessment/draft",
            {"finding_note": note, "category": category}, format="json")

    def _finalize(self, study):
        return self.client_.patch(f"/api/v1/studies/{study.pk}/finalize", {}, format="json")

    def _amend(self, assessment, category):
        return self.client_.post(
            f"/api/v1/assessments/{assessment.pk}/amend",
            {"decision_reason": "재검토", "category": category, "finding_note": "정정"},
            format="json")


class MriDraftFinalizeTests(_Base):
    def test_mri_draft_and_finalize_with_4(self):
        study = self._study("mri")
        r = self._draft(study, "4")
        self.assertEqual(r.status_code, 200, r.content)
        r = self._finalize(study)
        self.assertEqual(r.status_code, 200, r.content)
        final = Assessment.objects.get(study=study, read_stage="final")
        self.assertEqual(final.category, "4")

    def test_mri_all_allowed_values(self):
        study = self._study("mri")
        for cat in ["0", "1", "2", "3", "4", "5", "6"]:
            self.assertEqual(self._draft(study, cat).status_code, 200, cat)

    def test_mri_subcategory_rejected_on_draft(self):
        study = self._study("mri")
        for cat in ["4a", "4b", "4c"]:
            r = self._draft(study, cat)
            self.assertEqual(r.status_code, 422, cat)
            self.assertEqual(r.json()["error"]["code"], "BIRADS_SUBCATEGORY_NOT_FOR_MRI")
        self.assertFalse(Assessment.objects.filter(study=study).exists())

    def test_mri_legacy_subcategory_draft_blocked_on_finalize(self):
        # 규칙 이전에 저장된 임시저장 — 확정으로 못 올린다
        study = self._study("mri")
        Assessment.objects.create(study=study, read_stage="draft", category="4b")
        r = self._finalize(study)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "BIRADS_SUBCATEGORY_NOT_FOR_MRI")
        self.assertFalse(Assessment.objects.filter(study=study, read_stage="final").exists())

    def test_mri_draft_without_category_still_allowed(self):
        study = self._study("mri")
        self.assertEqual(self._draft(study, None).status_code, 200)


class NonMriTests(_Base):
    def test_mammo_plain_4_rejected(self):
        study = self._study("mammo")
        r = self._draft(study, "4")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("4a", r.json()["error"]["message"])

    def test_us_plain_4_rejected(self):
        study = self._study("us")
        self.assertEqual(self._draft(study, "4").status_code, 400)

    def test_mammo_subcategory_still_ok(self):
        study = self._study("mammo")
        for cat in ["4a", "4b", "4c"]:
            self.assertEqual(self._draft(study, cat).status_code, 200, cat)
        self.assertEqual(self._finalize(study).status_code, 200)

    def test_unknown_category_rejected(self):
        study = self._study("mammo")
        self.assertEqual(self._draft(study, "7").status_code, 400)


class AmendTests(_Base):
    def _final(self, study, category):
        return Assessment.objects.create(study=study, read_stage="final",
                                         category=category, finalized_at=timezone.now())

    def test_mri_amend_to_4_ok(self):
        study = self._study("mri")
        old = self._final(study, "3")
        r = self._amend(old, "4")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["category"] if "category" in r.json()
                         else r.json()["data"]["category"], "4")

    def test_mri_amend_to_4b_rejected(self):
        study = self._study("mri")
        old = self._final(study, "3")
        r = self._amend(old, "4b")
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "BIRADS_SUBCATEGORY_NOT_FOR_MRI")
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)

    def test_mammo_amend_to_4_rejected(self):
        study = self._study("mammo")
        old = self._final(study, "3")
        r = self._amend(old, "4")
        self.assertEqual(r.status_code, 400)
        old.refresh_from_db()
        self.assertIsNone(old.superseded_by_id)


class MriDiscordanceTests(TestCase):
    """MRI 4 · 5 는 맘모 4a~4c · 5 와 같이 「영상 의심」이다."""

    def setUp(self):
        self.patient = Patient.objects.create(patient_number="D-MRI-001", sex="F")
        order = ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                         modality="mri", exam_purpose="diagnostic")
        self.study = Study.objects.create(patient=self.patient, exam_order=order,
                                          modality="mri", read_status="finalized")
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)

    def _assess(self, category):
        return Assessment.objects.create(study=self.study, lesion=self.lesion,
                                         read_stage="final", category=category,
                                         finalized_at=timezone.now())

    def _specimen(self, b_category):
        return Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, specimen_label="S-D-MRI-001",
            specimen_type="cnb", guidance_route="mri", accession_status="accessioned",
            b_category=b_category, finalized_at=timezone.now())

    def test_mri_4_with_benign_flags_rule1(self):
        self._assess("4")
        flag = discordance.evaluate(self.patient, self._specimen("b2"))
        self.assertIsNotNone(flag)
        self.assertEqual(flag.violated_rule, "rule1")
        self.assertEqual(flag.review_note, "영상 의심(BI-RADS 4) · 병리 B2 — 위양성 검토")

    def test_mri_5_with_benign_flags_rule1(self):
        self._assess("5")
        flag = discordance.evaluate(self.patient, self._specimen("b1"))
        self.assertIsNotNone(flag)
        self.assertEqual(flag.violated_rule, "rule1")

    def test_mri_4_with_malignant_does_not_flag(self):
        self._assess("4")
        self.assertIsNone(discordance.evaluate(self.patient, self._specimen("b5")))
        self.assertEqual(DiscordanceFlag.objects.count(), 0)

    def test_mri_3_with_malignant_flags_rule2(self):
        self._assess("3")
        flag = discordance.evaluate(self.patient, self._specimen("b5"))
        self.assertEqual(flag.violated_rule, "rule2")


class RankTests(TestCase):
    def test_plain_4_between_3_and_5(self):
        self.assertGreater(birads.rank("4"), birads.rank("3"))
        self.assertLess(birads.rank("4"), birads.rank("5"))

    def test_plain_4_sits_with_4b(self):
        self.assertEqual(birads.rank("4"), birads.rank("4b"))
        self.assertGreater(birads.rank("4"), birads.rank("4a"))
        self.assertLess(birads.rank("4"), birads.rank("4c"))

    def test_task_helpers_accept_plain_4(self):
        self.assertEqual(tasks._birads(4), "4")
        self.assertEqual(tasks._birads("BI-RADS 4"), "4")
        self.assertGreater(tasks._birads_rank(4), tasks._birads_rank("3"))
        self.assertEqual(tasks._birads_rank(4), tasks._birads_rank("4b"))

    def test_suspicious_set(self):
        for v in ["4", "4a", "4b", "4c", "5"]:
            self.assertTrue(birads.is_suspicious(v), v)
        for v in ["0", "1", "2", "3", "6", None, ""]:
            self.assertFalse(birads.is_suspicious(v), v)
