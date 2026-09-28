# -*- coding: utf-8 -*-
"""09-28 진료 흐름 재배치 — 영상의학과 · 병리과 백엔드(B1).

  1  확정된 검사에 임시저장 · 재확정 → 409 STUDY_ALREADY_FINALIZED
  2  StudySerializer 에 order_note · exam_purpose · patient_number
  3  GET /assessments ?assessed_by=me · ?finalized_on= / GET /studies ?assigned=me ·
     ?read_status= · ?modality=
  4  임시저장이 recommendation · recommendation_reason 을 받는다
  5  확정된 검체 draft · finalize → 409 SPECIMEN_ALREADY_FINALIZED,
     남이 집은 검체 → 403 ROLE_FORBIDDEN
  6  병리 draft · finalize 가 조직형 · 등급 · 수용체 · Ki-67 을 받는다
  7  SpecimenSerializer 에 patient_number · bound_by_name, 목록 ?assigned=me ·
     ?finalized=yes|no · ordering=report__last_viewed_at
  8  바인딩이 clinical_note 를 받고 target_snapshot 을 채운다
  9  판독 · 병리 확정 뒤 주치의 알림(report_ready)

notify.send 는 mock 한다 — 진짜로 부르면 notify:8092 로 HTTP 를 쏜다.
"""
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
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
    StorageObject,
    Study,
)


def _account(login_id, role, number, name):
    acc = Account.objects.create(login_id=login_id, role=role,
                                 account_status="active", is_active=True)
    Staff.objects.create(account=acc, staff_number=number, full_name=name)
    return acc


def _client(acc):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(acc))
    return c


def _rows(resp):
    body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else body
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def _data(resp):
    body = resp.json()
    return body.get("data", body) if isinstance(body, dict) else body


def _err(resp):
    return resp.json()["error"]["code"]


class _Base(TestCase):
    def setUp(self):
        self.rad = _account("b1-rad", "radiology", "B1-RAD-1", "영상 B1")
        self.rad2 = _account("b1-rad2", "radiology", "B1-RAD-2", "영상 B1 둘째")
        self.surgeon = _account("b1-sur", "surgery", "B1-SUR-1", "외과 B1")
        self.path = _account("b1-path", "pathology", "B1-PATH-1", "병리 B1")
        self.path2 = _account("b1-path2", "pathology", "B1-PATH-2", "병리 B1 둘째")
        self.nurse = _account("b1-nur", "nursing", "B1-NUR-1", "간호 B1")

        self.patient = Patient.objects.create(
            patient_number="P-B1-001", sex="female",
            primary_staff=self.surgeon.staff)
        PatientPii.objects.create(patient=self.patient, name="흐름환자",
                                  birth_date=date(1980, 1, 1), phone="010-1111-0001")
        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="diagnostic", ordered_by=self.surgeon.staff,
            order_note="좌측 상외측 종괴 촉지", assigned_to=self.rad.staff,
        )
        self.study = Study.objects.create(
            patient=self.patient, exam_order=self.order, modality="mammo",
            performed_at=timezone.now(), density_category="c", density_percent="55.50",
        )


# ── 1 · 4 · 9 영상 판독 ───────────────────────────────────────
class RadiologyFinalizeGuardTests(_Base):
    def _draft(self, body=None, client=None):
        return (client or _client(self.rad)).put(
            f"/api/v1/studies/{self.study.pk}/assessment/draft",
            body or {"finding_note": "소견", "category": "4a"}, format="json")

    def _finalize(self):
        return _client(self.rad).patch(
            f"/api/v1/studies/{self.study.pk}/finalize", {}, format="json")

    def test_draft_refused_after_finalize(self):
        self.assertEqual(self._draft().status_code, 200)
        self.assertEqual(self._finalize().status_code, 200)
        r = self._draft()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(_err(r), "STUDY_ALREADY_FINALIZED")
        self.assertEqual(r.json()["error"]["message"], "확정된 판독은 판독 정정으로 고칩니다.")
        self.study.refresh_from_db()
        self.assertEqual(self.study.read_status, "finalized")   # draft 로 안 돌아갔다
        self.assertFalse(Assessment.objects.filter(study=self.study, read_stage="draft").exists())

    def test_draft_refused_when_live_final_exists_even_if_status_stale(self):
        Assessment.objects.create(study=self.study, read_stage="final", category="3",
                                  finalized_at=timezone.now())
        r = self._draft()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(_err(r), "STUDY_ALREADY_FINALIZED")

    def test_draft_allowed_when_only_superseded_finals(self):
        # superseded 만 있고 살아 있는 final 이 없으면(비정상 데이터) 막지 않는다
        newer = Assessment.objects.create(study=self.study, read_stage="draft", category="3")
        Assessment.objects.create(study=self.study, read_stage="final", category="3",
                                  finalized_at=timezone.now(), superseded_by=newer)
        self.assertEqual(self._draft().status_code, 200)

    def test_refinalize_without_draft_is_409(self):
        self._draft(); self._finalize()
        r = self._finalize()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(_err(r), "STUDY_ALREADY_FINALIZED")

    def test_finalize_without_draft_on_fresh_study_still_400(self):
        r = self._finalize()
        self.assertEqual(r.status_code, 400)
        self.assertEqual(_err(r), "VALIDATION_ERROR")

    def test_amend_path_untouched(self):
        self._draft(); self._finalize()
        final = Assessment.objects.get(study=self.study, read_stage="final")
        r = _client(self.rad).post(
            f"/api/v1/assessments/{final.pk}/amend",
            {"decision_reason": "재검토", "category": "4b", "finding_note": "정정"},
            format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_missing_study_is_404(self):
        r = _client(self.rad).put("/api/v1/studies/999999/assessment/draft",
                                  {"category": "4a"}, format="json")
        self.assertEqual(r.status_code, 404)

    # 4
    def test_draft_accepts_recommendation(self):
        r = self._draft({"finding_note": "소견", "category": "4a",
                         "recommendation": "biopsy",
                         "recommendation_reason": "형태 불규칙"})
        self.assertEqual(r.status_code, 200, r.content)
        a = Assessment.objects.get(study=self.study, read_stage="draft")
        self.assertEqual(a.recommendation, "biopsy")
        self.assertEqual(a.recommendation_reason, "형태 불규칙")
        # 옛 화면(권고 안 보냄)이 다시 저장해도 지우지 않는다
        self._draft({"finding_note": "소견2", "category": "4a"})
        a.refresh_from_db()
        self.assertEqual(a.recommendation, "biopsy")
        # 확정하면 final 행에 그대로 남는다
        self._finalize()
        a.refresh_from_db()
        self.assertEqual((a.read_stage, a.recommendation), ("final", "biopsy"))

    def test_draft_rejects_unknown_recommendation(self):
        r = self._draft({"category": "4a", "recommendation": "whatever"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(_err(r), "VALIDATION_ERROR")

    def test_draft_rejects_long_reason(self):
        r = self._draft({"category": "4a", "recommendation": "biopsy",
                         "recommendation_reason": "x" * 251})
        self.assertEqual(r.status_code, 400)

    # 9
    @patch("core.notify.send")
    def test_finalize_notifies_primary_staff_after_commit(self, send):
        self._draft()
        with self.captureOnCommitCallbacks(execute=True):
            r = self._finalize()
        self.assertEqual(r.status_code, 200)
        final = Assessment.objects.get(study=self.study, read_stage="final")
        send.assert_called_once()
        kw = send.call_args.kwargs
        self.assertEqual(kw["staff"], self.surgeon.staff)
        self.assertEqual(kw["type"], "report_ready")
        self.assertEqual(kw["ref_type"], "assessment")
        self.assertEqual(kw["ref_id"], final.pk)
        self.assertIn("흐름환자", kw["message"])

    @patch("core.notify.send")
    def test_finalize_without_primary_staff_skips_notify(self, send):
        self.patient.primary_staff = None
        self.patient.save()
        self._draft()
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(self._finalize().status_code, 200)
        send.assert_not_called()

    def test_finalize_notification_row_written(self):
        # 진짜 notify.send — 허브 발행은 실패해도 삼키고 행은 남는다
        from core.models import Notification
        self._draft()
        with patch("core.notify.urllib.request.urlopen", side_effect=OSError("no hub")), \
                patch("core.tasks.deliver_external.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self._finalize().status_code, 200)
        note = Notification.objects.get(staff=self.surgeon.staff)
        self.assertEqual(note.notification_type, "report_ready")
        self.assertEqual(note.ref_type, "assessment")


# ── 2 · 3 · 10 검사 목록 ─────────────────────────────────────
class StudyListTests(_Base):
    def setUp(self):
        super().setUp()
        other_order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="us",
            exam_purpose="screening", ordered_by=self.surgeon.staff,
            assigned_to=self.rad2.staff,
        )
        self.other = Study.objects.create(
            patient=self.patient, exam_order=other_order, modality="us",
            read_status="finalized", performed_at=timezone.now() - timedelta(days=1),
        )

    def _ids(self, qs=""):
        r = _client(self.rad).get("/api/v1/studies/" + qs)
        self.assertEqual(r.status_code, 200, r.content)
        return {row["study_id"] for row in _rows(r)}

    def test_row_carries_patient_and_order_fields(self):
        r = _client(self.rad).get("/api/v1/studies/")
        row = next(x for x in _rows(r) if x["study_id"] == self.study.pk)
        for key in ("patient_name", "age", "sex", "patient_number", "order_note",
                    "exam_purpose", "density_category", "density_percent"):
            self.assertIn(key, row)
        self.assertEqual(row["patient_number"], "P-B1-001")
        self.assertEqual(row["order_note"], "좌측 상외측 종괴 촉지")
        self.assertEqual(row["exam_purpose"], "diagnostic")
        self.assertEqual(row["density_category"], "c")
        self.assertEqual(row["patient_name"], "흐름환자")

    def test_read_view_study_carries_fields(self):
        StorageObject.objects.create(study=self.study, object_key="b1/x.dcm")
        r = _client(self.rad).get(f"/api/v1/radiology/studies/{self.study.pk}/read")
        self.assertEqual(r.status_code, 200, r.content)
        s = _data(r)["study"]
        self.assertEqual((s["order_note"], s["exam_purpose"], s["patient_number"]),
                         ("좌측 상외측 종괴 촉지", "diagnostic", "P-B1-001"))

    def test_assigned_me(self):
        self.assertEqual(self._ids("?assigned=me"), {self.study.pk})

    def test_assigned_bad_value(self):
        r = _client(self.rad).get("/api/v1/studies/?assigned=someone")
        self.assertEqual(r.status_code, 400)

    def test_read_status_and_modality(self):
        self.assertEqual(self._ids("?read_status=finalized"), {self.other.pk})
        self.assertEqual(self._ids("?read_status=pending,finalized"),
                         {self.study.pk, self.other.pk})
        self.assertEqual(self._ids("?modality=mammo"), {self.study.pk})
        self.assertEqual(self._ids("?modality=us&read_status=finalized"), {self.other.pk})
        r = _client(self.rad).get("/api/v1/studies/?modality=ct")
        self.assertEqual(r.status_code, 400)

    def test_no_filter_keeps_old_behaviour(self):
        self.assertEqual(self._ids(), {self.study.pk, self.other.pk})


class AssessmentListTests(_Base):
    def setUp(self):
        super().setUp()
        now = timezone.now()
        self.mine_today = Assessment.objects.create(
            study=self.study, read_stage="final", category="4a",
            assessed_by=self.rad.staff, finalized_at=now)
        self.mine_old = Assessment.objects.create(
            study=self.study, read_stage="final", category="3",
            assessed_by=self.rad.staff, finalized_at=now - timedelta(days=3))
        self.mine_draft = Assessment.objects.create(
            study=self.study, read_stage="draft", category="4a",
            assessed_by=self.rad.staff)
        self.theirs = Assessment.objects.create(
            study=self.study, read_stage="final", category="2",
            assessed_by=self.rad2.staff, finalized_at=now)

    def _ids(self, qs):
        r = _client(self.rad).get("/api/v1/assessments" + qs)
        self.assertEqual(r.status_code, 200, r.content)
        return {row["assessment_id"] for row in _rows(r)}

    def test_assessed_by_me_without_study(self):
        self.assertEqual(self._ids("?assessed_by=me"),
                         {self.mine_today.pk, self.mine_old.pk, self.mine_draft.pk})

    def test_finalized_today(self):
        self.assertEqual(self._ids("?assessed_by=me&finalized_on=today"), {self.mine_today.pk})

    def test_finalized_on_date(self):
        day = timezone.localdate(self.mine_old.finalized_at).isoformat()
        self.assertEqual(self._ids(f"?assessed_by=me&finalized_on={day}"), {self.mine_old.pk})

    def test_bad_date_is_400(self):
        r = _client(self.rad).get("/api/v1/assessments?assessed_by=me&finalized_on=09-28")
        self.assertEqual(r.status_code, 400)

    def test_study_filter_unchanged(self):
        self.assertEqual(self._ids(f"?study={self.study.pk}"),
                         {self.mine_today.pk, self.mine_old.pk, self.mine_draft.pk,
                          self.theirs.pk})

    def test_rows_carry_patient_context(self):
        r = _client(self.rad).get("/api/v1/assessments?assessed_by=me&finalized_on=today")
        row = _rows(r)[0]
        self.assertEqual(row["patient_name"], "흐름환자")
        self.assertEqual(row["patient_number"], "P-B1-001")
        self.assertEqual(row["modality"], "mammo")
        self.assertEqual(row["patient_id"], self.patient.pk)


# ── 5 · 6 · 9 병리 ────────────────────────────────────────────
class PathologyGuardTests(_Base):
    def setUp(self):
        super().setUp()
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study,
                                            label="MAMMO-1")
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="accessioned",
            specimen_label="S-B1-001", assigned_to=self.path.staff,
        )

    def _draft(self, body, acc=None):
        return _client(acc or self.path).put(
            f"/api/v1/specimens/{self.specimen.pk}/draft", body, format="json")

    def _finalize(self, body, acc=None):
        return _client(acc or self.path).patch(
            f"/api/v1/specimens/{self.specimen.pk}/finalize", body, format="json")

    def test_finalized_specimen_refuses_draft_and_finalize(self):
        self.assertEqual(self._finalize({"b_category": "b5", "diagnosis": "malignant"})
                         .status_code, 200)
        for r in (self._draft({"b_category": "b2"}),
                  self._finalize({"b_category": "b2", "diagnosis": "benign"})):
            self.assertEqual(r.status_code, 409)
            self.assertEqual(_err(r), "SPECIMEN_ALREADY_FINALIZED")
            self.assertEqual(r.json()["error"]["message"], "확정된 병리 결과는 고칠 수 없습니다.")
        self.specimen.refresh_from_db()
        self.assertEqual(self.specimen.b_category, "b5")

    def test_other_pathologist_forbidden(self):
        r = self._draft({"b_category": "b2"}, acc=self.path2)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(_err(r), "ROLE_FORBIDDEN")
        r = self._finalize({"b_category": "b2", "diagnosis": "benign"}, acc=self.path2)
        self.assertEqual(r.status_code, 403)
        self.specimen.refresh_from_db()
        self.assertIsNone(self.specimen.finalized_at)

    def test_unassigned_specimen_still_open(self):
        self.specimen.assigned_to = None
        self.specimen.save()
        self.assertEqual(self._draft({"b_category": "b2"}, acc=self.path2).status_code, 200)

    def test_missing_specimen_is_404(self):
        r = _client(self.path).put("/api/v1/specimens/999999/draft", {}, format="json")
        self.assertEqual(r.status_code, 404)

    # 6
    def test_draft_accepts_markers(self):
        r = self._draft({"histologic_type": "idc_nst", "nottingham_grade": 2,
                         "er_status": "positive", "pr_status": "low_positive",
                         "her2_status": "equivocal", "ki67_percent": "25.5"})
        self.assertEqual(r.status_code, 200, r.content)
        self.specimen.refresh_from_db()
        s = self.specimen
        self.assertEqual((s.histologic_type, s.nottingham_grade, s.er_status,
                          s.pr_status, s.her2_status, float(s.ki67_percent)),
                         ("idc_nst", 2, "positive", "low_positive", "equivocal", 25.5))
        # 안 보낸 칸은 그대로
        self._draft({"b_category": "b5"})
        s.refresh_from_db()
        self.assertEqual(s.histologic_type, "idc_nst")

    def test_finalize_accepts_markers(self):
        r = self._finalize({"b_category": "b5", "diagnosis": "malignant",
                            "histologic_type": "ilc", "nottingham_grade": 3,
                            "her2_status": "positive", "ki67_percent": 40})
        self.assertEqual(r.status_code, 200, r.content)
        self.specimen.refresh_from_db()
        self.assertEqual((self.specimen.histologic_type, self.specimen.nottingham_grade),
                         ("ilc", 3))

    def test_marker_validation(self):
        for body in ({"nottingham_grade": 4}, {"nottingham_grade": 0},
                     {"ki67_percent": 101}, {"ki67_percent": -1},
                     {"er_status": "maybe"}, {"her2_status": "3+"},
                     {"histologic_type": "unknown_type"}):
            r = self._draft(body)
            self.assertEqual(r.status_code, 400, body)

    # 9
    @patch("core.notify.send")
    def test_finalize_notifies_primary_staff(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            r = self._finalize({"b_category": "b3", "diagnosis": "benign"})
        self.assertEqual(r.status_code, 200)
        calls = [c for c in send.call_args_list if c.kwargs.get("type") == "report_ready"]
        self.assertEqual(len(calls), 1)
        kw = calls[0].kwargs
        self.assertEqual(kw["staff"], self.surgeon.staff)
        self.assertIn("S-B1-001", kw["message"])

    @patch("core.notify.send")
    def test_draft_does_not_notify(self, send):
        with self.captureOnCommitCallbacks(execute=True):
            self._draft({"b_category": "b3"})
        send.assert_not_called()


# ── 7 · 8 검체 목록 · 바인딩 ─────────────────────────────────
class SpecimenListBindTests(_Base):
    def setUp(self):
        super().setUp()
        self.lesion = Lesion.objects.create(
            patient=self.patient, study=self.study, label="MAMMO-1", modality="mammo",
            ai_size_mm="14.20", measured_size_mm="12.30",
            detail={"laterality": "left", "location": "UOQ"})
        self.mine_open = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="accessioned",
            specimen_label="S-B1-A", assigned_to=self.path.staff, bound_by=self.nurse.staff)
        self.mine_done = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="accessioned",
            specimen_label="S-B1-B", assigned_to=self.path.staff,
            finalized_at=timezone.now())
        self.theirs = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="accessioned",
            specimen_label="S-B1-C", assigned_to=self.path2.staff)
        self.unassigned = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, accession_status="bound",
            specimen_label="S-B1-D")

    def _get(self, qs, acc=None):
        r = _client(acc or self.path).get("/api/v1/specimens/" + qs)
        self.assertEqual(r.status_code, 200, r.content)
        return _rows(r)

    def test_row_fields(self):
        row = next(x for x in self._get("") if x["specimen_id"] == self.mine_open.pk)
        self.assertEqual(row["patient_number"], "P-B1-001")
        self.assertEqual(row["bound_by_name"], "간호 B1")
        other = next(x for x in self._get("") if x["specimen_id"] == self.theirs.pk)
        self.assertIsNone(other["bound_by_name"])

    def test_assigned_me_and_finalized(self):
        ids = lambda rows: {r["specimen_id"] for r in rows}
        self.assertEqual(ids(self._get("?assigned=me")), {self.mine_open.pk, self.mine_done.pk})
        self.assertEqual(ids(self._get("?assigned=me&finalized=no")), {self.mine_open.pk})
        self.assertEqual(ids(self._get("?assigned=me&finalized=yes")), {self.mine_done.pk})
        self.assertEqual(ids(self._get("?assigned=none")), {self.unassigned.pk})
        self.assertEqual(len(self._get("")), 4)
        r = _client(self.path).get("/api/v1/specimens/?finalized=maybe")
        self.assertEqual(r.status_code, 400)

    def test_queue_view_assigned_me(self):
        r = _client(self.path).get("/api/v1/specimens/queue?assigned=me&finalized=no")
        self.assertEqual(r.status_code, 200)
        self.assertEqual({x["specimen_id"] for x in _rows(r)}, {self.mine_open.pk})

    def test_ordering_by_last_viewed(self):
        now = timezone.now()
        for sp, at in ((self.mine_open, now - timedelta(hours=2)),
                       (self.theirs, now - timedelta(hours=1))):
            Report.objects.create(patient=self.patient, specimen=sp, report_type="stage",
                                  last_viewed_at=at, last_viewed_by=self.surgeon.staff)
        rows = self._get("?ordering=-report__last_viewed_at")
        self.assertEqual([r["specimen_id"] for r in rows[:2]],
                         [self.theirs.pk, self.mine_open.pk])
        self.assertEqual(len(rows), 4)   # 조인으로 행이 불지 않는다
        rows = self._get("?ordering=report__last_viewed_at")
        self.assertEqual([r["specimen_id"] for r in rows[:2]],
                         [self.mine_open.pk, self.theirs.pk])

    def _bind(self, extra=None, label="S-B1-NEW"):
        body = {"lesion_id": self.lesion.pk, "specimen_label": label,
                "specimen_type": "core_needle", "guidance_route": "ultrasound",
                "collected_at": timezone.now().isoformat()}
        body.update(extra or {})
        return _client(self.nurse).post("/api/v1/specimens/", body, format="json")

    def test_bind_sets_clinical_note_and_snapshot(self):
        Assessment.objects.create(study=self.study, lesion=self.lesion, read_stage="final",
                                  category="4b", finalized_at=timezone.now())
        r = self._bind({"clinical_note": "좌측 상외측 종괴로 조직검사 의뢰"})
        self.assertEqual(r.status_code, 201, r.content)
        sp = Specimen.objects.get(specimen_label="S-B1-NEW")
        self.assertEqual(sp.clinical_note, "좌측 상외측 종괴로 조직검사 의뢰")
        self.assertEqual(sp.target_snapshot,
                         "MAMMO-1 · 좌측 UOQ · 12.3mm · BI-RADS 4B · 맘모그래피")
        self.assertEqual(_data(r)["target_snapshot"], sp.target_snapshot)
        self.assertEqual(_data(r)["bound_by_name"], "간호 B1")

    def test_snapshot_uses_live_final_not_superseded(self):
        new = Assessment.objects.create(study=self.study, lesion=self.lesion,
                                        read_stage="final", category="5",
                                        finalized_at=timezone.now())
        Assessment.objects.create(study=self.study, lesion=self.lesion, read_stage="final",
                                  category="3", finalized_at=timezone.now(),
                                  superseded_by=new)
        self._bind()
        self.assertIn("BI-RADS 5",
                      Specimen.objects.get(specimen_label="S-B1-NEW").target_snapshot)

    def test_bind_without_note_or_assessment(self):
        bare = Lesion.objects.create(patient=self.patient, study=self.study)
        r = self._bind({"lesion_id": bare.pk})
        self.assertEqual(r.status_code, 201, r.content)
        sp = Specimen.objects.get(specimen_label="S-B1-NEW")
        self.assertIsNone(sp.clinical_note)
        self.assertEqual(sp.target_snapshot, "맘모그래피")   # 검사 모달리티만 안다
