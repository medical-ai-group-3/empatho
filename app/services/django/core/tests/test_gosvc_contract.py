# -*- coding: utf-8 -*-
"""Go 서비스와의 계약 — 소견문 티켓 · 알림 티켓 · I-4 부분 갱신.

계약의 주인은 Go 쪽 코드다. 여기 적힌 기대값은 전부 그쪽에서 읽어 온 것이고,
줄 번호가 아니라 **무엇을 검사하는지**를 주석에 남긴다.

    cmd/llm-proxy/main.go   RequireScope("report_narrative", req.ReportID)
    cmd/notify/main.go      cl.Purpose == "notify" && cl.ScopeID != ""
                            hub.Subscribe(cl.ScopeID)   ← 사용자 식별자다
    internal/callback/callback.go   Narrative 의 omitempty 세 칸
"""

import json
import time

import jwt
from django.test import TestCase, override_settings

from core.api.auth import issue_access
from core.api.errors import ApiError
from core.api.internal import sign
from core.api.tickets import (NOTIFY, PURPOSE_ROLES, PURPOSE_SCOPES,
                              SCOPE_MODEL, issue)
from core.models import (Account, ExamOrder, Patient, Report, Staff, Study)

SECRET = "test-callback-secret-0123456789abcdef"
TICKET_KEY = "ticket-key-0123456789abcdef0123456789abcdef"


@override_settings(TICKET_KEY=TICKET_KEY)
class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient_account = Account.objects.create(
            login_id="pat1", role="patient", is_active=True)
        cls.patient = Patient.objects.create(patient_number="E_1029304",
                                             account=cls.patient_account)
        cls.staff_account = Account.objects.create(
            login_id="rad1", role="radiology", is_active=True)
        cls.staff = Staff.objects.create(account=cls.staff_account,
                                         full_name="김판독")
        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=cls.staff)
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mammo")
        cls.report = Report.objects.create(patient=cls.patient, study=cls.study,
                                           report_type="final",
                                           audience="clinician")

    def claims_of(self, token):
        return jwt.decode(token, TICKET_KEY, algorithms=["HS256"])

    def ask(self, account, **body):
        self.client.credentials = None
        return self.client.post(
            "/api/v1/tickets", data=json.dumps(body),
            content_type="application/json",
            headers={"Authorization": "Bearer " + issue_access(account)})


class NarrativeTicketTests(Base):
    """llm-proxy 는 scope_id 가 report_id 인지만 본다."""

    def test_대상이_리포트다(self):
        self.assertEqual(PURPOSE_SCOPES["report_narrative"], ("report",))
        self.assertIs(SCOPE_MODEL["report"], Report)

    def test_클레임이_Go_가_보는_모양이다(self):
        token, claims, _ = issue("report_narrative", "report", self.report.pk)
        decoded = self.claims_of(token)
        self.assertEqual(decoded["purpose"], "report_narrative")
        # RequireScope 가 문자열끼리 비교한다. 숫자로 보내면 조용히 어긋난다.
        self.assertEqual(decoded["scope_id"], str(self.report.pk))
        self.assertIsInstance(decoded["scope_id"], str)
        self.assertTrue(decoded["nonce"])

    def test_사람은_못_낸다(self):
        # derived_upload 와 같다 — Celery 가 issue() 를 직접 쓴다
        self.assertEqual(PURPOSE_ROLES["report_narrative"], frozenset())
        for account in (self.staff_account, self.patient_account):
            r = self.ask(account, purpose="report_narrative",
                         scope_id=self.report.pk)
            self.assertEqual(r.status_code, 403, account.role)
            self.assertEqual(r.json()["error"]["code"], "ROLE_FORBIDDEN")

    def test_유효기간이_리포트_서버_타임아웃보다_길다(self):
        from django.conf import settings

        # llm-proxy 의 REPORT_TIMEOUT 이 2 분이다
        self.assertGreater(settings.TICKET_TTL_SEC["report_narrative"], 120)


class NotifyTicketTests(Base):
    """notify 의 scope_id 는 대상이 아니라 **사람**이다."""

    def test_대상이_계정이다(self):
        self.assertEqual(PURPOSE_SCOPES[NOTIFY], ("account",))
        self.assertIs(SCOPE_MODEL["account"], Account)

    def test_로그인한_누구나_낼_수_있다(self):
        for account in (self.staff_account, self.patient_account):
            r = self.ask(account, purpose=NOTIFY, scope_id=account.pk)
            self.assertEqual(r.status_code, 200, account.role)

    def test_자기_계정이_실린다(self):
        r = self.ask(self.staff_account, purpose=NOTIFY,
                     scope_id=self.staff_account.pk)
        self.assertEqual(r.json()["data"]["scope_id"],
                         str(self.staff_account.pk))

    def test_남의_계정을_달라고_해도_자기_것이_나온다(self):
        # Go 는 이 값을 그대로 믿고 그 사람 스트림에 붙여준다 —
        # 요청 값을 받아 쓰면 남의 알림을 구독할 수 있다.
        r = self.ask(self.staff_account, purpose=NOTIFY,
                     scope_id=self.patient_account.pk)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["scope_id"],
                         str(self.staff_account.pk))

    def test_없는_계정_번호를_보내도_통한다(self):
        # 요청 값을 아예 안 보므로 조회조차 하지 않는다
        r = self.ask(self.staff_account, purpose=NOTIFY, scope_id=999999)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["scope_id"],
                         str(self.staff_account.pk))

    def test_토큰_클레임도_자기_것이다(self):
        r = self.ask(self.patient_account, purpose=NOTIFY,
                     scope_id=self.staff_account.pk)
        decoded = self.claims_of(r.json()["data"]["token"])
        self.assertEqual(decoded["purpose"], NOTIFY)
        self.assertEqual(decoded["scope_id"], str(self.patient_account.pk))

    def test_상한이_없다(self):
        # 파일 전송이 아니다
        _, claims, _ = issue(NOTIFY, "account", self.staff_account.pk)
        self.assertNotIn("max_bytes", claims)


@override_settings(CALLBACK_SECRET=SECRET,
                   CALLBACK_TIMESTAMP_TOLERANCE_SEC=300)
class NarrativeCallbackTests(Base):
    """I-4 — Go 가 뺀 키를 없는 값으로 읽어 덮어쓰면 안 된다."""

    FULL = {
        "narrative_text": "우측 유방 상외측에 종괴가 보입니다.",
        "evidence_links": ["MG-01", "MG-02"],
        "dropped_sentence_log": [{"text": "버린 문장", "why": "근거 없음"}],
        "notes": [{"code": "N1", "text": "이 소견은 참고용입니다."}],
        "prompt_version": "v3",
        "fallback": False,
    }

    def post(self, payload, idem="narr-1"):
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        return self.client.post(
            "/internal/v1/reports/%d/narrative" % self.report.pk, data=body,
            content_type="application/json",
            headers={"X-Timestamp": ts,
                     "X-Signature": sign(SECRET.encode(), ts, body),
                     "Idempotency-Key": idem})

    def fill(self):
        self.assertEqual(self.post(self.FULL).status_code, 200)
        self.report.refresh_from_db()

    def test_한_번에_다_채워진다(self):
        self.fill()
        self.assertEqual(self.report.narrative_text, self.FULL["narrative_text"])
        self.assertEqual(self.report.evidence_links, ["MG-01", "MG-02"])
        self.assertEqual(self.report.prompt_version, "v3")
        self.assertEqual(len(self.report.notes), 1)

    def test_두_번째에_notes_가_없으면_남아_있는다(self):
        # Go 의 Notes 에 omitempty 가 붙어 있다 — 없으면 키가 빠진다
        self.fill()
        payload = dict(self.FULL)
        del payload["notes"]
        self.post(payload, idem="narr-2")
        self.report.refresh_from_db()
        self.assertEqual(len(self.report.notes), 1)

    def test_두_번째에_prompt_version_이_없으면_남아_있는다(self):
        self.fill()
        payload = dict(self.FULL)
        del payload["prompt_version"]
        self.post(payload, idem="narr-3")
        self.report.refresh_from_db()
        self.assertEqual(self.report.prompt_version, "v3")

    def test_빈_본문은_아무것도_안_지운다(self):
        # 재시도가 빈 채로 와도 앞서 채운 것이 살아 있어야 한다
        self.fill()
        self.post({}, idem="narr-4")
        self.report.refresh_from_db()
        self.assertEqual(self.report.narrative_text,
                         self.FULL["narrative_text"])
        self.assertEqual(self.report.evidence_links, ["MG-01", "MG-02"])
        self.assertEqual(self.report.prompt_version, "v3")
        self.assertEqual(len(self.report.notes), 1)

    def test_fallback_은_키가_있을_때만_바뀐다(self):
        self.fill()
        self.assertFalse(self.report.fallback)

        self.post({"fallback": True, "fallback_reason": "모델 출력이 규칙을 어김"},
                  idem="narr-5")
        self.report.refresh_from_db()
        self.assertTrue(self.report.fallback)
        self.assertEqual(self.report.content_json["fallback_reason"],
                         "모델 출력이 규칙을 어김")

        # 키가 빠진 요청이 True 를 False 로 되돌리면 안 된다
        self.post({"narrative_text": "다시 쓴 문장"}, idem="narr-6")
        self.report.refresh_from_db()
        self.assertTrue(self.report.fallback)

    def test_빈_배열은_모름이_아니라_근거_없음이다(self):
        self.fill()
        self.post({"evidence_links": []}, idem="narr-7")
        self.report.refresh_from_db()
        self.assertEqual(self.report.evidence_links, [])
        self.assertIsNotNone(self.report.evidence_links)

    def test_빈_문자열은_None_으로_간다(self):
        # 텍스트 칸은 ""과 None 을 가를 이유가 없다
        self.fill()
        self.post({"narrative_text": "", "prompt_version": ""}, idem="narr-8")
        self.report.refresh_from_db()
        self.assertIsNone(self.report.narrative_text)
        self.assertIsNone(self.report.prompt_version)
