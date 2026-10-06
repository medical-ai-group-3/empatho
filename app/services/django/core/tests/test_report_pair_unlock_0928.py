# -*- coding: utf-8 -*-
"""09-28 — 종합 소견서 두 벌(의사용 · 환자용)의 설명 · 잠금 해제는 짝 전체에 건다.

전에는 치료 방침 화면이 의사용 번호로 설명 · 해제를 불렀고, 서버는 그 한 행만
바꿨다. 환자 앱은 환자용만 읽으므로(SurgeryReportViewSet.owned_queryset) 「잠금
해제」를 눌러도 환자에게는 아무것도 안 열렸다. 환자용 번호로 부르면 설명 기록이
의사용에 있어 조건 ③(대면 설명)이 끝내 안 켜졌다.
"""
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account, Assessment, DiscordanceFlag, ExamOrder, Lesion, Notification,
    Patient, Report, Specimen, Staff, Study,
)


def _client(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class ReportPairUnlockTests(TestCase):
    def setUp(self):
        self.doc = Account.objects.create(login_id="pair-surgery", role="surgery",
                                          account_status="active", is_active=True)
        Staff.objects.create(account=self.doc, staff_number="SUR-PAIR", full_name="외과")
        self.pacct = Account.objects.create(login_id="pair-patient", role="patient",
                                            account_status="active", is_active=True)
        self.patient = Patient.objects.create(patient_number="P-PAIR-1", sex="F",
                                              account=self.pacct)
        order = ExamOrder.objects.create(patient=self.patient, order_status="requested",
                                         modality="mammo", exam_purpose="screening")
        self.study = Study.objects.create(patient=self.patient, exam_order=order,
                                          modality="mammo", read_status="finalized")
        self.lesion = Lesion.objects.create(patient=self.patient, study=self.study)
        self.assessment = Assessment.objects.create(
            study=self.study, lesion=self.lesion, read_stage="final", category="4b",
            finalized_at=timezone.now())
        self.specimen = Specimen.objects.create(
            patient=self.patient, lesion=self.lesion, specimen_label="S-PAIR-1",
            specimen_type="cnb", guidance_route="us", accession_status="accessioned",
            b_category="b2", finalized_at=timezone.now())
        src = {"source_ai_ids": [11, 12]}
        # issue_final_report 와 같은 순서 — 의사용, 곧바로 환자용
        self.clin = Report.objects.create(patient=self.patient, report_type="final",
                                          socket_id="7", audience="clinician", content_json=src)
        self.pat = Report.objects.create(patient=self.patient, report_type="final",
                                         socket_id="7", audience="patient", content_json=dict(src))
        self.c = _client(self.doc)

    def _status(self, report):
        r = self.c.get(f"/api/v1/reports/{report.pk}/unlock-status")
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        return body.get("data", body)

    def _explain(self, report, content="진단과 치료 계획 설명"):
        r = self.c.patch(f"/api/v1/reports/{report.pk}/explain",
                         {"explain_method": "대면", "patient_confirmed": True,
                          "explain_content": content}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_의사용에_설명하면_환자용_조건도_켜진다(self):
        self._explain(self.clin)
        self.pat.refresh_from_db()
        self.assertIsNotNone(self.pat.explained_at)
        self.assertEqual(self.pat.explain_method, "대면")
        self.assertEqual(self.pat.content_json["explain_content"], "진단과 치료 계획 설명")
        # 묶은 판독 목록은 그대로 남는다
        self.assertEqual(self.pat.content_json["source_ai_ids"], [11, 12])
        st = self._status(self.pat)
        conds = {c["key"]: c for c in st["conditions"]}
        self.assertTrue(conds["explained"]["met"])
        self.assertTrue(st["can_unlock"])
        self.assertEqual(sorted(st["report_ids"]), sorted([self.clin.pk, self.pat.pk]))

    def test_환자용을_풀면_의사용도_같이_풀리고_알림은_한_번(self):
        self._explain(self.pat)
        r = self.c.patch(f"/api/v1/reports/{self.pat.pk}/unlock", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.clin.refresh_from_db(); self.pat.refresh_from_db()
        self.assertEqual(self.pat.lock_status, "unlocked")
        self.assertEqual(self.clin.lock_status, "unlocked")
        self.assertIsNotNone(self.pat.unlocked_at)
        self.assertEqual(Notification.objects.filter(
            patient=self.patient, ref_type="report").values_list("ref_id", flat=True).get(),
            self.pat.pk)
        # 환자 앱이 이제 환자용 한 벌을 읽는다
        pc = _client(self.pacct)
        rows = pc.get(f"/api/v1/reports/?patient={self.patient.pk}").json()
        rows = rows.get("data", rows)
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertEqual([x["report_id"] for x in rows], [self.pat.pk])

    def test_의사용_번호로_풀어도_환자용이_열린다(self):
        self._explain(self.clin)
        r = self.c.patch(f"/api/v1/reports/{self.clin.pk}/unlock", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.pat.refresh_from_db()
        self.assertEqual(self.pat.lock_status, "unlocked")
        self.assertEqual(Notification.objects.filter(ref_type="report", ref_id=self.pat.pk).count(), 1)
        self.assertEqual(Notification.objects.filter(ref_type="report", ref_id=self.clin.pk).count(), 0)

    def test_조건마다_막는_것을_싣는다(self):
        pending = Study.objects.create(patient=self.patient, exam_order=self.study.exam_order,
                                       modality="us", read_status="draft")
        flag = DiscordanceFlag.objects.create(lesion=self.lesion, specimen=self.specimen,
                                              assessment=self.assessment, violated_rule="rule1",
                                              flag_status="open", flagged_at=timezone.now())
        st = self._status(self.pat)
        conds = {c["key"]: c for c in st["conditions"]}
        self.assertFalse(st["can_unlock"])
        self.assertFalse(conds["records_final"]["met"])
        self.assertEqual([(i["kind"], i.get("study_id")) for i in conds["records_final"]["items"]],
                         [("study", pending.pk)])
        self.assertEqual([i["discordance_id"] for i in conds["discordance_closed"]["items"]], [flag.pk])
        self.assertFalse(conds["explained"]["met"])
        r = self.c.patch(f"/api/v1/reports/{self.pat.pk}/unlock", {}, format="json")
        self.assertEqual(r.status_code, 400)
        self.pat.refresh_from_db()
        self.assertEqual(self.pat.lock_status, "locked")

    def test_다시_만든_짝과_섞이지_않는다(self):
        src2 = {"source_ai_ids": [11, 12, 13]}
        clin2 = Report.objects.create(patient=self.patient, report_type="final",
                                      socket_id="7", audience="clinician", content_json=src2)
        pat2 = Report.objects.create(patient=self.patient, report_type="final",
                                     socket_id="7", audience="patient", content_json=dict(src2))
        self._explain(clin2)
        pat2.refresh_from_db(); self.pat.refresh_from_db()
        self.assertIsNotNone(pat2.explained_at)
        self.assertIsNone(self.pat.explained_at)

    def test_없는_리포트는_404(self):
        r = self.c.get("/api/v1/reports/999999/unlock-status")
        self.assertEqual(r.status_code, 404)
