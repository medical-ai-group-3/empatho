# -*- coding: utf-8 -*-
"""09-28 권한 조정 (제품 책임자 승인) — 표 신설 없음.

  followup            유방외과 R → CR  — POST /followups/new
  discordance_review  영상의학 CU → CRU(own_only) — GET /discordances?assessed_by=me
  consent             간호 · 원무 R    — GET /patients/{id}/consents

(병리 확정 알림의 ref_type="specimen" 은 test_flow_0928_rad_path 쪽.)

TestCase 라 Postgres 가 있어야 돈다.
"""
from datetime import date

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core import models
from core.api import permissions as perm
from core.api.auth import issue_access


def _staff(login, role):
    acc = models.Account.objects.create(login_id=login, role=role,
                                        account_status="active", is_active=True)
    staff = models.Staff.objects.create(account=acc, staff_number=login.upper(),
                                        full_name=login)
    return acc, staff


def _client(acc):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(acc))
    return c


def _data(r):
    return r.json()["data"]


def _rows(r):
    rows = _data(r)
    return rows.get("results", rows) if isinstance(rows, dict) else rows


class MatrixDiffTests(SimpleTestCase):
    def test_유방외과는_추적_회차를_만들고_읽지만_고치지_않는다(self):
        rule = perm.rule_for("followup", perm.SURGERY)
        self.assertEqual(rule.actions, "CR")
        self.assertFalse(rule.own_only)

    def test_영상의학은_자기_판독의_불일치만_읽는다(self):
        rule = perm.rule_for("discordance_review", perm.RADIOLOGY)
        self.assertEqual(set(rule.actions), {"C", "R", "U"})
        self.assertTrue(rule.own_only)

    def test_동의는_간호_원무만_읽는다(self):
        for role in (perm.NURSING, perm.RECEPTION):
            rule = perm.rule_for("consent", role)
            self.assertEqual(rule.actions, "R", role)
            self.assertFalse(rule.own_only, role)
        for role in (perm.RADIOLOGY, perm.PATHOLOGY, perm.SURGERY):
            self.assertEqual(perm.rule_for("consent", role).actions, "", role)
        # 환자 쪽은 그대로
        self.assertEqual(perm.rule_for("consent", perm.PATIENT).actions, "CR")


class _Base(TestCase):
    def setUp(self):
        self.surg_acc, self.surg = _staff("surg-p0928", "surgery")
        self.nur_acc, self.nur = _staff("nur-p0928", "nursing")
        self.rec_acc, self.rec = _staff("rec-p0928", "reception")
        self.rad_acc, self.rad = _staff("rad-p0928", "radiology")
        self.rad2_acc, self.rad2 = _staff("rad2-p0928", "radiology")
        self.path_acc, self.path = _staff("path-p0928", "pathology")
        self.patient = models.Patient.objects.create(
            patient_number="P-P0928-1", primary_staff=self.surg, sex="female")
        models.PatientPii.objects.create(patient=self.patient, name="권한환자",
                                         birth_date=date(1980, 1, 1), phone="010-0000-0928")


# ── followup: 유방외과 CR ─────────────────────────────────────
class SurgeryFollowupCreateTests(_Base):
    BODY = {"round_no": 1, "due_at": "2026-12-01T00:00:00Z"}

    def _post(self, acc):
        return _client(acc).post("/api/v1/followups/new",
                                 {"patient_id": self.patient.pk, **self.BODY}, format="json")

    def test_유방외과가_자기_환자_회차를_만든다(self):
        r = self._post(self.surg_acc)
        self.assertEqual(r.status_code, 201, r.content)
        fu = models.Followup.objects.get(pk=_data(r)["followup_id"])
        self.assertEqual(fu.patient_id, self.patient.pk)
        self.assertEqual(fu.status, "open")
        self.assertEqual(fu.round_no, 1)
        self.assertEqual(fu.created_by_id, self.surg_acc.pk)
        self.assertEqual(fu.updated_by_id, self.surg_acc.pk)

    def test_간호도_그대로_만든다(self):
        self.assertEqual(self._post(self.nur_acc).status_code, 201)

    def test_병리는_403(self):
        self.assertEqual(self._post(self.path_acc).status_code, 403)

    def test_유방외과는_통화_기록_종료를_못_한다(self):
        fu = models.Followup.objects.create(patient=self.patient, round_no=1, status="open")
        r = _client(self.surg_acc).patch(f"/api/v1/followups/{fu.pk}/call",
                                         {"call_result": "연결"}, format="json")
        self.assertEqual(r.status_code, 403)
        r = _client(self.surg_acc).patch(f"/api/v1/followups/{fu.pk}/",
                                         {"closed_reason": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_유방외과는_목록을_읽는다(self):
        self._post(self.surg_acc)
        r = _client(self.surg_acc).get(f"/api/v1/followups/?patient={self.patient.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(_rows(r)), 1)


# ── discordance_review: 영상의학 R(본인 판독만) ─────────────────
class RadiologyDiscordanceTests(_Base):
    def setUp(self):
        super().setUp()
        order = models.ExamOrder.objects.create(
            patient=self.patient, modality="us", exam_purpose="diagnostic",
            order_status="completed", ordered_by=self.surg, ordered_at=timezone.now())
        self.study = models.Study.objects.create(patient=self.patient, exam_order=order,
                                                 modality="us", read_status="finalized")
        self.lesion = models.Lesion.objects.create(patient=self.patient, study=self.study,
                                                   modality="us", label="US-1")
        self.mine = self._flag(self.rad, "4a", "b2", closed=True)
        self.theirs = self._flag(self.rad2, "5", "b2")

    def _flag(self, reader, category, b_category, closed=False):
        a = models.Assessment.objects.create(
            study=self.study, lesion=self.lesion, read_stage="final", category=category,
            assessed_by=reader, finalized_at=timezone.now())
        sp = models.Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, specimen_label=f"S-P0928-{models.Specimen.objects.count() + 1}",
            specimen_type="core_needle", accession_status="accessioned",
            b_category=b_category, diagnosis="benign")
        return models.DiscordanceFlag.objects.create(
            lesion=self.lesion, specimen=sp, assessment=a, violated_rule="rule1",
            flag_status="sev1", flagged_at=timezone.now(),
            disposition_type="rebiopsy" if closed else None,
            closed_at=timezone.now() if closed else None)

    def _get(self, acc, qs=""):
        return _client(acc).get("/api/v1/discordances" + qs)

    def test_assessed_by_me_는_내_판독만(self):
        r = self._get(self.rad_acc, "?assessed_by=me")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([x["discordance_id"] for x in _rows(r)], [self.mine.pk])

    def test_파라미터_없어도_서버가_내_것만_준다(self):
        r = self._get(self.rad_acc)
        self.assertEqual({x["discordance_id"] for x in _rows(r)}, {self.mine.pk})
        # 남의 번호를 넣어도 내 것 밖으로 못 나간다
        r = self._get(self.rad_acc, f"?assessed_by={self.rad2.pk}")
        self.assertEqual(_rows(r), [])
        r = self._get(self.rad2_acc)
        self.assertEqual({x["discordance_id"] for x in _rows(r)}, {self.theirs.pk})

    def test_표시용_칸이_있다(self):
        row = _rows(self._get(self.rad_acc, "?assessed_by=me"))[0]
        expect = {
            "patient_id": self.patient.pk, "patient_name": "권한환자",
            "patient_number": "P-P0928-1", "modality": "us", "category": "4a",
            "b_category": "b2", "violated_rule": "rule1", "flag_status": "sev1",
            "disposition_type": "rebiopsy", "assessed_by": self.rad.pk,
        }
        for k, v in expect.items():
            self.assertEqual(row[k], v, k)
        self.assertIsNotNone(row["flagged_at"])
        self.assertIsNotNone(row["closed_at"])

    def test_유방외과는_전부_본다(self):
        r = self._get(self.surg_acc)
        self.assertEqual({x["discordance_id"] for x in _rows(r)},
                         {self.mine.pk, self.theirs.pk})
        r = self._get(self.surg_acc, f"?assessed_by={self.rad2.pk}")
        self.assertEqual({x["discordance_id"] for x in _rows(r)}, {self.theirs.pk})

    def test_잘못된_assessed_by_는_400(self):
        self.assertEqual(self._get(self.surg_acc, "?assessed_by=bad").status_code, 400)

    def test_간호는_여전히_403(self):
        self.assertEqual(self._get(self.nur_acc).status_code, 403)

    def test_영상의학은_처분하지_못한다(self):
        r = _client(self.rad_acc).patch(
            f"/api/v1/discordances/{self.theirs.pk}/dispose",
            {"disposition_type": "no_action", "disposition_reason": "x"}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_목록_쿼리_수가_행_수와_무관하다(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as one:
            self._get(self.surg_acc)
        for i in range(3):
            self._flag(self.rad, "4b", "b2")
        with CaptureQueriesContext(connection) as many:
            self._get(self.surg_acc)
        self.assertEqual(len(one), len(many))


# ── consent: 간호 · 원무 R ───────────────────────────────────
class PatientConsentTests(_Base):
    def setUp(self):
        super().setUp()
        self.pat_acc = models.Account.objects.create(
            login_id="pat-p0928", role="patient", account_status="active", is_active=True)
        self.patient.account = self.pat_acc
        self.patient.save()
        now = timezone.now()
        self.c1 = models.Consent.objects.create(
            account=self.pat_acc, doc_type="terms", doc_version="1.0", doc_sha256="a" * 64,
            agreed=True, agreed_at=now, channel="app")
        self.c2 = models.Consent.objects.create(
            account=self.pat_acc, doc_type="marketing", doc_version="1.0", doc_sha256="b" * 64,
            agreed=True, agreed_at=now, channel="app", withdrawn_at=now)

    def _get(self, acc, patient=None):
        return _client(acc).get(f"/api/v1/patients/{(patient or self.patient).pk}/consents")

    def test_간호가_읽는다(self):
        r = self._get(self.nur_acc)
        self.assertEqual(r.status_code, 200, r.content)
        rows = _data(r)
        self.assertEqual({x["consent_id"] for x in rows}, {self.c1.pk, self.c2.pk})
        row = next(x for x in rows if x["consent_id"] == self.c2.pk)
        self.assertEqual(set(row), {"consent_id", "doc_type", "doc_version", "agreed",
                                    "agreed_at", "withdrawn_at", "channel"})
        self.assertEqual(row["doc_type"], "marketing")
        self.assertTrue(row["agreed"])
        self.assertIsNotNone(row["withdrawn_at"])

    def test_원무도_읽는다(self):
        self.assertEqual(self._get(self.rec_acc).status_code, 200)

    def test_계정_없는_환자는_빈_목록(self):
        p = models.Patient.objects.create(patient_number="P-P0928-NOACC")
        r = self._get(self.nur_acc, p)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(_data(r), [])

    def test_다른_의료진은_403(self):
        for acc in (self.surg_acc, self.rad_acc, self.path_acc):
            self.assertEqual(self._get(acc).status_code, 403, acc.role)

    def test_없는_환자는_404(self):
        r = _client(self.nur_acc).get("/api/v1/patients/999999/consents")
        self.assertEqual(r.status_code, 404)

    def test_간호는_쓰지_못한다(self):
        r = _client(self.nur_acc).post(f"/api/v1/patients/{self.patient.pk}/consents",
                                       {}, format="json")
        self.assertIn(r.status_code, (403, 405))

    def test_환자는_남의_것을_못_본다(self):
        other = models.Account.objects.create(
            login_id="pat2-p0928", role="patient", account_status="active", is_active=True)
        self.assertEqual(self._get(other).status_code, 403)
