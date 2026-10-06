# -*- coding: utf-8 -*-
"""09-28 유방외과: 환자 이력(timeline)에 치료 결정 · 리포트 · 결과 설명 ·
처방이 안 나온다. 의료진에게만 싣고, 환자 본인 호출에는 싣지 않는다 —
설명 전에 결과가 새면 안 된다(views/surgery.py PatientTimelineView)."""
from datetime import date, datetime, timezone as dt_tz

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account, Assessment, ExamOrder, Patient, PatientPii, Prescription,
    PrescriptionDrug, Report, Staff, Study,
)

NEW_TYPES = {"치료 결정", "리포트", "결과 설명", "처방"}


def _t(day, hour=9):
    return datetime(2026, 9, day, hour, 0, tzinfo=dt_tz.utc)


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class PatientTimelineStaffEventsTests(TestCase):
    def setUp(self):
        self.surgery = Account.objects.create(
            login_id="tl-staff-surgery", role="surgery",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=self.surgery, staff_number="SUR-TL-001",
                             full_name="타임라인 유방외과")
        self.patient_account = Account.objects.create(
            login_id="tl-staff-patient", role="patient",
            account_status="active", is_active=True,
        )
        self.patient = Patient.objects.create(patient_number="P-TL-STAFF-001",
                                              account=self.patient_account)
        PatientPii.objects.create(patient=self.patient, name="이력환자",
                                  birth_date=date(1988, 3, 3), phone="010-5555-1111")

        order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.surgery.staff,
        )
        self.study = Study.objects.create(patient=self.patient, exam_order=order,
                                          modality="mammo", performed_at=_t(1))

        # 판독 — created_at 은 auto_now_add 라 update 로 고정한다.
        self.decided = Assessment.objects.create(
            study=self.study, read_stage="final", category="4a",
            decision_type="biopsy", decision_value="yes", decided_at=_t(5),
        )
        # 결정 칸은 찼지만 decided_at 이 비었다 → 치료 결정 줄이 없어야 한다.
        self.undecided = Assessment.objects.create(
            study=self.study, read_stage="draft", category="3",
            decision_type="imaging", decision_value="defer",
        )
        Assessment.objects.filter(pk__in=[self.decided.pk, self.undecided.pk]) \
            .update(created_at=_t(2))

        self.report = Report.objects.create(
            patient=self.patient, study=self.study, report_type="stage",
            audience="clinician", explained_at=_t(7), explain_method="대면",
        )
        # 설명 전 리포트 → 결과 설명 줄이 없어야 한다.
        self.report_unexplained = Report.objects.create(
            patient=self.patient, report_type="final", audience="patient",
        )
        Report.objects.filter(pk=self.report.pk).update(created_at=_t(4))
        Report.objects.filter(pk=self.report_unexplained.pk).update(created_at=_t(8))

        self.rx = Prescription.objects.create(
            patient=self.patient, report=self.report, prescribed_at=_t(6),
        )
        for name in ("타목시펜", "진통제"):
            PrescriptionDrug.objects.create(prescription=self.rx, name=name,
                                            dose="1정", times=["09:00"], days=30)
        # prescribed_at 이 비면 created_at 으로 받친다. 약이 없으면 detail 은 None.
        self.rx_no_date = Prescription.objects.create(patient=self.patient,
                                                      exam_order=order)
        Prescription.objects.filter(pk=self.rx_no_date.pk).update(created_at=_t(9))

    def _events(self, account):
        res = _client_for(account).get(f"/api/v1/patients/{self.patient.pk}/timeline")
        self.assertEqual(res.status_code, 200)
        return res.json()["data"]

    def test_staff_sees_new_events_with_ids(self):
        events = self._events(self.surgery)

        decisions = [e for e in events if e["type"] == "치료 결정"]
        self.assertEqual(len(decisions), 1)
        d = decisions[0]
        self.assertEqual(d["assessment_id"], self.decided.pk)
        self.assertEqual(d["study_id"], self.study.pk)
        self.assertEqual(d["decision_type"], "biopsy")
        self.assertEqual(d["decision_value"], "yes")
        self.assertEqual(d["detail"], "yes")

        reports = sorted((e for e in events if e["type"] == "리포트"),
                         key=lambda e: e["report_id"])
        self.assertEqual([r["report_id"] for r in reports],
                         [self.report.pk, self.report_unexplained.pk])
        self.assertEqual(reports[0]["report_type"], "stage")
        self.assertEqual(reports[0]["audience"], "clinician")
        self.assertEqual(reports[0]["detail"], "stage")

        explained = [e for e in events if e["type"] == "결과 설명"]
        self.assertEqual(len(explained), 1)
        self.assertEqual(explained[0]["report_id"], self.report.pk)
        self.assertEqual(explained[0]["detail"], "대면")

        rxs = {e["prescription_id"]: e for e in events if e["type"] == "처방"}
        self.assertEqual(set(rxs), {self.rx.pk, self.rx_no_date.pk})
        self.assertEqual(rxs[self.rx.pk]["detail"], "약 2종")
        self.assertEqual(rxs[self.rx.pk]["report_id"], self.report.pk)
        self.assertIsNone(rxs[self.rx_no_date.pk]["detail"])
        self.assertIsNone(rxs[self.rx_no_date.pk]["report_id"])

        # 기존 줄은 그대로.
        self.assertEqual(len([e for e in events if e["type"] == "판독"]), 2)
        self.assertEqual(len([e for e in events if e["type"] == "촬영"]), 1)

    def test_null_timestamps_are_skipped(self):
        events = self._events(self.surgery)
        self.assertTrue(all(e["at"] for e in events))
        self.assertNotIn(self.undecided.pk,
                         [e.get("assessment_id") for e in events if e["type"] == "치료 결정"])
        self.assertNotIn(self.report_unexplained.pk,
                         [e.get("report_id") for e in events if e["type"] == "결과 설명"])

    def test_events_sorted_by_at(self):
        events = self._events(self.surgery)
        ats = [e["at"] for e in events]
        self.assertEqual(ats, sorted(ats))
        order = [e["type"] for e in events]
        # 1 촬영 · 2 판독×2 · 4 리포트 · 5 치료 결정 · 6 처방 · 7 결과 설명 · 8 리포트 · 9 처방
        self.assertEqual(order, ["촬영", "판독", "판독", "리포트", "치료 결정",
                                 "처방", "결과 설명", "리포트", "처방"])

    def test_patient_caller_does_not_see_new_events(self):
        events = self._events(self.patient_account)
        self.assertFalse(NEW_TYPES & {e["type"] for e in events})
        self.assertEqual([e["type"] for e in events], ["촬영", "판독", "판독"])
        for e in events:
            self.assertNotIn("report_id", e)
            self.assertNotIn("prescription_id", e)
            self.assertNotIn("decision_value", e)

    def test_staff_query_count_does_not_grow_per_row(self):
        client = _client_for(self.surgery)
        url = f"/api/v1/patients/{self.patient.pk}/timeline"
        client.get(url)  # 캐시 등 첫 호출 부수효과를 걷어낸다
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as before:
            client.get(url)
        for i in range(3):
            rx = Prescription.objects.create(patient=self.patient, report=self.report,
                                             prescribed_at=_t(10 + i))
            PrescriptionDrug.objects.create(prescription=rx, name="약", dose="1정",
                                            times=[], days=1)
            Report.objects.create(patient=self.patient, report_type="stage",
                                  explained_at=_t(10 + i), explain_method="유선")
        with CaptureQueriesContext(connection) as after:
            client.get(url)
        self.assertEqual(len(before), len(after))
