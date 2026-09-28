# -*- coding: utf-8 -*-
"""09-28 진료 흐름 재배치 — 유방외과 워크리스트 · 간호 창구 백엔드.

  GET   /surgery/worklist                 유방외과 워크리스트(next_step)
  GET   /followups/?patient=              추적 회차 한 환자만 · phone 등 얹음
  PATCH /followups/{id}/                  round_result
  POST  /exam-orders/schedule             followup_id 잇기 · 같은 날 규칙
  GET   /questionnaire/form               의료진용 문진 문항
  PATCH /patients/{id}/questionnaire/     오늘 방문 오더에도 담는다
  GET   /patients/?q=                     has_account
  PATCH /patients/{id}/pii                인적 사항 정정
  GET   /discordances?primary_staff=me    내 환자 불일치만

TestCase 라 Postgres 가 있어야 돈다.
"""
from datetime import date, datetime, time, timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core import models, surgery_worklist
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


def _at(days, hh=10, mm=0):
    d = timezone.localdate() + timedelta(days=days)
    return timezone.make_aware(datetime.combine(d, time(hh, mm)))


def _data(r):
    return r.json()["data"]


class _Base(TestCase):
    def setUp(self):
        self.surg_acc, self.surg = _staff("surg-0928", "surgery")
        self.surg2_acc, self.surg2 = _staff("surg2-0928", "surgery")
        self.nur_acc, self.nur = _staff("nur-0928b", "nursing")
        self.rad_acc, self.rad = _staff("rad-0928b", "radiology")
        self.path_acc, self.path = _staff("path-0928b", "pathology")
        self.n = 0

    def _patient(self, staff=None, name="환자", birth=date(1980, 5, 1)):
        self.n += 1
        p = models.Patient.objects.create(patient_number=f"P-0928-{self.n}",
                                          primary_staff=staff, sex="female",
                                          has_allergy=False)
        models.PatientPii.objects.create(patient=p, name=f"{name}{self.n}",
                                         birth_date=birth, phone=f"010-0928-{self.n:04d}")
        return p

    def _order(self, p, **kw):
        kw.setdefault("order_status", "requested")
        return models.ExamOrder.objects.create(patient=p, **kw)

    def _imaging(self, p, **kw):
        return self._order(p, modality="us", exam_purpose="diagnostic",
                           order_status=kw.pop("order_status", "ordered"),
                           ordered_by=self.surg, ordered_at=kw.pop("ordered_at", timezone.now()),
                           **kw)

    def _final_study(self, p, finalized_at=None, stage_report=True):
        order = self._imaging(p, order_status="completed")
        study = models.Study.objects.create(patient=p, exam_order=order, modality="us",
                                            read_status="finalized")
        models.Assessment.objects.create(study=study, read_stage="final", category="4a",
                                         finalized_at=finalized_at or timezone.now())
        if stage_report:
            models.Report.objects.create(patient=p, study=study, report_type="stage",
                                         audience="clinician", socket_id="1")
        return study

    def _final_report(self, p, explained=False):
        out = []
        for aud in ("clinician", "patient"):
            out.append(models.Report.objects.create(
                patient=p, report_type="final", audience=aud, socket_id="7",
                explained_at=timezone.now() if (explained and aud == "clinician") else None))
        return out[0]

    def _view_reports(self, p):
        """유방외과가 리포트 목록을 연다 → 판독 리포트에 열람이 남는다(core/viewed.py)."""
        _client(self.surg_acc).get(f"/api/v1/reports/?patient={p.pk}")


# ── 1. 워크리스트 ─────────────────────────────────────────────────────
class SurgeryWorklistTests(_Base):
    URL = "/api/v1/surgery/worklist"

    def _get(self, qs="", acc=None):
        r = _client(acc or self.surg_acc).get(self.URL + qs)
        self.assertEqual(r.status_code, 200, r.content)
        return _data(r)

    def _item(self, data, p):
        for i in data["items"]:
            if i["patient_id"] == p.pk:
                return i
        return None

    def test_모양과_칸(self):
        p = self._patient(self.surg)
        self._order(p, visited_at=timezone.now())
        data = self._get()
        self.assertEqual(set(data), {"items", "counts"})
        item = self._item(data, p)
        self.assertEqual(set(item), {
            "patient_id", "patient_name", "patient_number", "age", "sex", "has_allergy",
            "last_visit_at", "today_stage", "pending_orders", "unseen_results",
            "open_discordance", "final_report_id", "report_explained", "decision",
            "prescription_count", "next_step"})
        self.assertEqual(item["patient_name"], "환자1")
        self.assertIsInstance(item["age"], int)
        self.assertEqual(item["today_stage"], "간호·문진")
        self.assertEqual(item["next_step"], "exam")
        for step in surgery_worklist.STEPS:
            self.assertIn(step, data["counts"])
        self.assertEqual(data["counts"]["exam"], 1)
        self.assertEqual(data["counts"]["total"], 1)

    def test_유방외과만(self):
        for acc in (self.nur_acc, self.rad_acc):
            r = _client(acc).get(self.URL)
            self.assertEqual(r.status_code, 403)

    def test_내_환자만_기본_scope_all_은_과_전체(self):
        mine = self._patient(self.surg)
        other = self._patient(self.surg2)
        self._order(mine, visited_at=timezone.now())
        self._order(other, visited_at=timezone.now())
        ids = {i["patient_id"] for i in self._get()["items"]}
        self.assertEqual(ids, {mine.pk})
        ids = {i["patient_id"] for i in self._get("?scope=all")["items"]}
        self.assertEqual(ids, {mine.pk, other.pk})
        ids = {i["patient_id"] for i in self._get(f"?primary_staff={self.surg2.pk}")["items"]}
        self.assertEqual(ids, {other.pk})
        self.assertEqual(_client(self.surg_acc).get(self.URL + "?primary_staff=x").status_code, 400)

    def test_오래된_움직임없는_환자는_빠진다(self):
        p = self._patient(self.surg)
        o = self._order(p, visited_at=_at(-60), order_status="completed")
        models.ExamOrder.objects.filter(pk=o.pk).update(created_at=_at(-60), updated_at=_at(-60))
        self.assertIsNone(self._item(self._get(), p))

    def test_오래됐어도_끝나지_않은_일이_있으면_선다(self):
        p = self._patient(self.surg)
        o = self._imaging(p, ordered_at=_at(-90))
        models.ExamOrder.objects.filter(pk=o.pk).update(created_at=_at(-90), updated_at=_at(-90))
        item = self._item(self._get(), p)
        self.assertEqual(item["next_step"], "wait_results")
        self.assertEqual(item["pending_orders"], 1)

    def test_불일치가_맨_앞(self):
        p = self._patient(self.surg)
        study = self._final_study(p)
        lesion = models.Lesion.objects.create(study=study, patient=p)
        models.DiscordanceFlag.objects.create(lesion=lesion, flagged_at=timezone.now(),
                                              violated_rule="rule1", flag_status="sev1")
        data = self._get()
        item = self._item(data, p)
        self.assertTrue(item["open_discordance"])
        self.assertEqual(item["next_step"], "discordance")
        self.assertEqual(data["counts"]["open_discordance"], 1)
        self.assertEqual(data["items"][0]["patient_id"], p.pk)

    def test_새_결과는_review_열람하면_report(self):
        p = self._patient(self.surg)
        self._final_study(p)
        item = self._item(self._get(), p)
        self.assertEqual(item["unseen_results"], 1)
        self.assertEqual(item["next_step"], "review")
        self._view_reports(p)
        item = self._item(self._get(), p)
        self.assertEqual(item["unseen_results"], 0)
        self.assertEqual(item["next_step"], "report")

    def test_판독_리포트가_없는_결과는_미열람으로_안_센다(self):
        p = self._patient(self.surg)
        self._final_study(p, stage_report=False)
        item = self._item(self._get(), p)
        self.assertEqual(item["unseen_results"], 0)
        self.assertEqual(item["next_step"], "report")

    def test_병리_확정도_미열람과_대기를_센다(self):
        p = self._patient(self.surg)
        study = self._final_study(p)
        self._view_reports(p)
        lesion = models.Lesion.objects.create(study=study, patient=p)
        sp = models.Specimen.objects.create(patient=p, lesion=lesion, accession_status="bound")
        item = self._item(self._get(), p)
        self.assertEqual(item["pending_orders"], 1)
        self.assertEqual(item["next_step"], "wait_results")
        sp.finalized_at = timezone.now()
        sp.save()
        models.Report.objects.create(patient=p, study=study, specimen=sp,
                                     report_type="stage", socket_id="4b")
        item = self._item(self._get(), p)
        self.assertEqual(item["pending_orders"], 0)
        self.assertEqual(item["unseen_results"], 1)
        self.assertEqual(item["next_step"], "review")

    def test_소견서_결정_설명_처방_순서(self):
        p = self._patient(self.surg)
        study = self._final_study(p, finalized_at=timezone.now() - timedelta(hours=2))
        self._view_reports(p)
        rep = self._final_report(p)
        item = self._item(self._get(), p)
        self.assertEqual(item["final_report_id"], rep.pk)
        self.assertEqual(item["next_step"], "decision")
        a = study.assessments.first()
        a.decision_type, a.decision_value, a.decided_at = "surgery", "yes", timezone.now()
        a.save()
        item = self._item(self._get(), p)
        self.assertEqual(item["decision"], "yes")
        self.assertEqual(item["next_step"], "explain")
        self.assertFalse(item["report_explained"])
        rep.explained_at = timezone.now()
        rep.save()
        item = self._item(self._get(), p)
        self.assertTrue(item["report_explained"])
        self.assertEqual(item["next_step"], "prescription")
        models.Prescription.objects.create(patient=p, report=rep, prescribed_at=timezone.now())
        item = self._item(self._get(), p)
        self.assertEqual(item["prescription_count"], 1)
        self.assertEqual(item["next_step"], "followup")

    def test_오늘_진료_검사를_냈으면_결과대기_결과_뒤_close(self):
        p = self._patient(self.surg)
        visit = self._order(p, visited_at=timezone.now(), handed_at=timezone.now(),
                            handed_to=self.surg)
        self.assertEqual(self._item(self._get(), p)["today_stage"], "외래 진료")
        self.assertEqual(self._item(self._get(), p)["next_step"], "exam")
        self._imaging(p)
        self.assertEqual(self._item(self._get(), p)["next_step"], "wait_results")
        # 검사를 물리면 다시 exam, 촬영 없이 완료로 닫히면(결과 없음) close
        models.ExamOrder.objects.filter(patient=p, modality="us").update(order_status="cancelled")
        self.assertEqual(self._item(self._get(), p)["next_step"], "exam")
        models.ExamOrder.objects.filter(patient=p, modality="us").update(order_status="completed")
        self.assertEqual(self._item(self._get(), p)["next_step"], "close")
        visit.order_status = "completed"
        visit.save()
        self.assertEqual(self._item(self._get(), p)["next_step"], "followup")

    def test_쿼리_수가_줄_수와_상관없다(self):
        def seed(k):
            for _ in range(k):
                p = self._patient(self.surg)
                self._order(p, visited_at=timezone.now())
                st = self._final_study(p)
                lesion = models.Lesion.objects.create(study=st, patient=p)
                models.Specimen.objects.create(patient=p, lesion=lesion,
                                               accession_status="bound")
                self._final_report(p)
                models.Prescription.objects.create(patient=p, report=models.Report.objects.filter(
                    patient=p, report_type="final").first(), prescribed_at=timezone.now())
        c = _client(self.surg_acc)

        def count():
            with CaptureQueriesContext(connection) as ctx:
                r = c.get(self.URL)
            self.assertEqual(r.status_code, 200)
            return len(ctx.captured_queries), len(_data(r)["items"])

        seed(2)
        q1, n1 = count()
        seed(6)
        q2, n2 = count()
        self.assertEqual((n1, n2), (2, 8))
        self.assertEqual(q1, q2)


class NextStepFunctionTests(TestCase):
    def test_우선순위(self):
        now = timezone.now()
        ns = surgery_worklist.next_step
        self.assertEqual(ns({"open_discordance": True, "unseen_results": 3}), "discordance")
        self.assertEqual(ns({"unseen_results": 1, "pending_orders": 2}), "review")
        self.assertEqual(ns({"pending_orders": 2, "last_result_at": now}), "wait_results")
        self.assertEqual(ns({"last_result_at": now}), "report")
        self.assertEqual(ns({"last_result_at": now, "final_report_id": 1,
                             "final_report_at": now - timedelta(days=1)}), "report")
        base = {"last_result_at": now - timedelta(days=2), "final_report_id": 1,
                "final_report_at": now - timedelta(days=1)}
        self.assertEqual(ns(base), "decision")
        self.assertEqual(ns({**base, "decided_at": now - timedelta(days=3)}), "decision")
        base["decided_at"] = now
        self.assertEqual(ns(base), "explain")
        base["explained_at"] = now
        self.assertEqual(ns(base), "prescription")
        base["last_prescribed_at"] = now
        self.assertEqual(ns(base), "followup")
        self.assertEqual(ns({**base, "open_visit_today": True}), "close")
        self.assertEqual(ns({"open_visit_today": True}), "exam")
        self.assertEqual(ns({"open_visit_today": True, "exam_ordered_today": True}), "close")
        self.assertEqual(ns({}), "followup")

    def test_오래전_설명은_처방을_조르지_않는다(self):
        now = timezone.now()
        f = {"last_result_at": now - timedelta(days=90), "final_report_id": 1,
             "final_report_at": now - timedelta(days=80), "decided_at": now - timedelta(days=80),
             "explained_at": now - timedelta(days=60)}
        self.assertEqual(surgery_worklist.next_step(f), "followup")


# ── 2 · 3 · 7. 추적 · 예약 ──────────────────────────────────────────────
class FollowupAndScheduleTests(_Base):
    def setUp(self):
        super().setUp()
        self.c = _client(self.nur_acc)
        self.p = self._patient()
        self.other = self._patient()
        self.fu = models.Followup.objects.create(patient=self.p, round_no=1, status="open",
                                                 due_at=_at(30))
        self.fu2 = models.Followup.objects.create(patient=self.other, round_no=1,
                                                  status="open", due_at=_at(30))

    def test_목록에_전화_생년월일_환자번호_와_patient_필터(self):
        rows = _data(self.c.get(f"/api/v1/followups/?patient={self.p.pk}"))
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        self.assertEqual([r["followup_id"] for r in rows], [self.fu.pk])
        self.assertEqual(rows[0]["phone"], self.p.pii.phone)
        self.assertEqual(rows[0]["birth_date"], "1980-05-01")
        self.assertEqual(rows[0]["patient_number"], self.p.patient_number)
        rows = _data(self.c.get("/api/v1/followups/"))
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.c.get("/api/v1/followups/?patient=x").status_code, 400)

    def test_round_result_만_보내면_통화기록은_그대로(self):
        self.fu.call_result = "연결"
        self.fu.save()
        r = self.c.patch(f"/api/v1/followups/{self.fu.pk}/", {"round_result": "stable"},
                         format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.fu.refresh_from_db()
        self.assertEqual(self.fu.round_result, "stable")
        self.assertEqual(self.fu.call_result, "연결")
        r = self.c.patch(f"/api/v1/followups/{self.fu.pk}/", {"round_result": "nope"},
                         format="json")
        self.assertEqual(r.status_code, 400)

    def test_round_result_와_종료를_같이(self):
        r = self.c.patch(f"/api/v1/followups/{self.fu.pk}/",
                         {"round_result": "changed", "closed_reason": "재검"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.fu.refresh_from_db()
        self.assertEqual((self.fu.round_result, self.fu.status), ("changed", "resolved"))

    def _book(self, c, **kw):
        body = {"patient_id": self.p.pk, "scheduled_at": timezone.localtime(_at(20)).isoformat()}
        body.update(kw)
        return c.post("/api/v1/exam-orders/schedule", body, format="json")

    def test_예약에_추적_회차를_잇는다(self):
        r = self._book(self.c, followup_id=self.fu.pk)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(_data(r)["followup"], self.fu.pk)
        self.assertEqual(models.ExamOrder.objects.get(pk=_data(r)["exam_order_id"]).followup_id,
                         self.fu.pk)

    def test_다른_환자_회차는_400(self):
        self.assertEqual(self._book(self.c, followup_id=self.fu2.pk).status_code, 400)
        self.assertEqual(self._book(self.c, followup_id=999999).status_code, 400)
        self.assertFalse(models.ExamOrder.objects.filter(patient=self.p).exists())

    def test_회차_없이도_예전처럼(self):
        r = self._book(self.c)
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(_data(r)["followup"])

    def test_유방외과도_다음_방문을_잡고_같은_날_규칙이_걸린다(self):
        sc = _client(self.surg_acc)
        r = self._book(sc)
        self.assertEqual(r.status_code, 201, r.content)
        r2 = self._book(sc, scheduled_at=timezone.localtime(_at(20, 15, 0)).isoformat())
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.json()["error"]["code"], "DUPLICATE_RESERVATION")
        # 회차를 이어도 같은 날 규칙은 그대로
        r3 = self._book(sc, followup_id=self.fu.pk)
        self.assertEqual(r3.status_code, 409)


# ── 4. 문진 ───────────────────────────────────────────────────────────
class QuestionnaireStaffTests(_Base):
    def test_의료진은_문항을_읽고_환자는_못_읽는다(self):
        for acc in (self.nur_acc, self.surg_acc, self.rad_acc):
            r = _client(acc).get("/api/v1/questionnaire/form")
            self.assertEqual(r.status_code, 200, r.content)
            d = _data(r)
            self.assertEqual(d["form_version"], "v1")
            self.assertEqual(d["total"], len(d["questions"]))
            q = d["questions"][0]
            self.assertEqual(set(q), {"id", "question", "choices", "critical", "hint"})
            self.assertEqual(set(q["choices"][0]), {"id", "label"})
        pacc = models.Account.objects.create(login_id="pt-0928", role="patient",
                                             account_status="active", is_active=True)
        self.assertEqual(_client(pacc).get("/api/v1/questionnaire/form").status_code, 403)

    def _answers(self):
        from core.api import questionnaire as qm
        q = qm.active_questions()[0]
        return {q["code"]: q["options"][0]["id"]}

    def test_창구_문진은_오늘_방문_오더에도_담긴다(self):
        p = self._patient()
        old = self._order(p, visited_at=_at(-3), order_status="completed")
        today = self._order(p, visited_at=timezone.now())
        r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/questionnaire/",
                                        self._answers(), format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(_data(r)["questionnaire_exam_order_id"], today.pk)
        today.refresh_from_db()
        old.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual(today.questionnaire, p.questionnaire)
        self.assertEqual(today.questionnaire["answers"], self._answers())
        self.assertIsNone(old.questionnaire)

    def test_오늘_예약만_있어도_그_오더에(self):
        p = self._patient()
        booked = self._order(p, order_status="scheduled", scheduled_at=_at(0, 23, 0))
        r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/questionnaire/",
                                        self._answers(), format="json")
        self.assertEqual(_data(r)["questionnaire_exam_order_id"], booked.pk)

    def test_오늘_오더가_없으면_환자에만(self):
        p = self._patient()
        r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/questionnaire/",
                                        self._answers(), format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(_data(r)["questionnaire_exam_order_id"])
        p.refresh_from_db()
        self.assertIsNotNone(p.questionnaire)


# ── 5 · 6. 환자 목록 · 인적 사항 정정 ─────────────────────────────────
class PatientPiiTests(_Base):
    def test_목록에_has_account(self):
        p = self._patient(name="가입")
        q = self._patient(name="미가입")
        p.account = models.Account.objects.create(login_id="pt-acc", role="patient",
                                                  account_status="active", is_active=True)
        p.save()
        rows = _data(_client(self.nur_acc).get("/api/v1/patients/?status=all"))
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        by = {r["patient_id"]: r for r in rows}
        self.assertTrue(by[p.pk]["has_account"])
        self.assertFalse(by[q.pk]["has_account"])

    def test_간호가_이름_전화_생일을_고친다(self):
        p = self._patient()
        r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/pii",
                                        {"name": "고친이름", "phone": "010-1111-2222",
                                         "birth_date": "1970-01-02"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(_data(r)["pii"]["name"], "고친이름")
        p.pii.refresh_from_db()
        self.assertEqual((p.pii.phone, str(p.pii.birth_date)), ("010-1111-2222", "1970-01-02"))
        self.assertEqual(p.pii.updated_by_id, self.nur_acc.pk)

    def test_보낸_칸만_고친다(self):
        p = self._patient()
        before = p.pii.phone
        r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/pii", {"name": "새"},
                                        format="json")
        self.assertEqual(r.status_code, 200)
        p.pii.refresh_from_db()
        self.assertEqual((p.pii.name, p.pii.phone), ("새", before))
        self.assertEqual(_client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/pii", {},
                                                     format="json").status_code, 400)

    def test_남의_전화면_400_자기_전화는_된다(self):
        p = self._patient()
        q = self._patient()
        c = _client(self.nur_acc)
        r = c.patch(f"/api/v1/patients/{p.pk}/pii", {"phone": q.pii.phone}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("phone", r.json()["error"]["details"])
        r = c.patch(f"/api/v1/patients/{p.pk}/pii", {"phone": p.pii.phone}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_동시_충돌도_400(self):
        from unittest import mock
        from django.db import IntegrityError
        p = self._patient()
        with mock.patch.object(models.PatientPii, "save", side_effect=IntegrityError("dup")):
            r = _client(self.nur_acc).patch(f"/api/v1/patients/{p.pk}/pii",
                                            {"phone": "010-9999-0000"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_patient_pii_U_가_없는_과는_403_없는_환자는_404(self):
        p = self._patient()
        for acc in (self.surg_acc, self.rad_acc):
            r = _client(acc).patch(f"/api/v1/patients/{p.pk}/pii", {"name": "x"}, format="json")
            self.assertEqual(r.status_code, 403)
        r = _client(self.nur_acc).patch("/api/v1/patients/999999/pii", {"name": "x"},
                                        format="json")
        self.assertEqual(r.status_code, 404)


# ── 8. 불일치 목록 primary_staff ─────────────────────────────────────────
class DiscordancePrimaryStaffTests(_Base):
    def _flag(self, staff, closed=False):
        p = self._patient(staff)
        study = self._final_study(p)
        lesion = models.Lesion.objects.create(study=study, patient=p)
        return models.DiscordanceFlag.objects.create(
            lesion=lesion, flagged_at=timezone.now(), violated_rule="rule1",
            closed_at=timezone.now() if closed else None)

    def _ids(self, qs):
        rows = _data(_client(self.surg_acc).get("/api/v1/discordances" + qs))
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows
        return {r["discordance_id"] for r in rows}

    def test_내_환자_열린_것만(self):
        mine = self._flag(self.surg)
        self._flag(self.surg, closed=True)
        theirs = self._flag(self.surg2)
        self.assertEqual(self._ids("?status=open&primary_staff=me"), {mine.pk})
        self.assertEqual(self._ids(f"?status=open&primary_staff={self.surg2.pk}"), {theirs.pk})
        self.assertEqual(self._ids("?status=open"), {mine.pk, theirs.pk})
        r = _client(self.surg_acc).get("/api/v1/discordances?primary_staff=bad")
        self.assertEqual(r.status_code, 400)
