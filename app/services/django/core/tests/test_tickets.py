# -*- coding: utf-8 -*-
"""전송 티켓 발급 — POST /api/v1/tickets (명세 19-1).

Go 를 띄우지 않고, services/gosvc/internal/ticket/ticket.go 의 Verify() 를
파이썬으로 옮겨 우리가 낸 티켓을 그것으로 검증한다. 클레임 이름 하나만 어긋나도
Go 쪽 json.Unmarshal 이 조용히 빈 값을 넣으므로 여기서 잡아야 한다.
"""

import base64
import hashlib
import hmac
import json
import time

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.api.auth import issue_access
from core.api.tickets import PURPOSE_ROLES, issue, object_key_prefix
from core.models import (Account, ExamOrder, Lesion, Patient, Report, Specimen,
                         Staff, Study)

TICKET_KEY = "ticket-key-0123456789abcdef0123456789abcdef"


# ── Go 의 Verify() 를 옮긴 것 ────────────────────────────────────────────
class GoTicketError(Exception):
    pass


def go_verify(key: bytes, token: str, used: set) -> dict:
    """ticket.go 의 Verify() 와 같은 순서로 본다.

    Go 는 JWT 헤더를 보지 않는다 — parts[0].parts[1] 에 HMAC-SHA256 만 건다.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise GoTicketError("TICKET_MALFORMED")
    signing = (parts[0] + "." + parts[1]).encode()
    try:
        sig = base64.urlsafe_b64decode(parts[2] + "=" * (-len(parts[2]) % 4))
    except Exception:
        raise GoTicketError("TICKET_MALFORMED") from None
    if not hmac.compare_digest(sig, hmac.new(key, signing, hashlib.sha256).digest()):
        raise GoTicketError("TICKET_SIGNATURE")

    raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
    claims = json.loads(raw)

    now = int(time.time())
    if not claims.get("exp") or claims["exp"] < now:
        raise GoTicketError("TICKET_EXPIRED")
    if not claims.get("nonce"):
        raise GoTicketError("TICKET_MALFORMED")
    if claims["nonce"] in used:
        raise GoTicketError("TICKET_REPLAYED")
    used.add(claims["nonce"])

    # file-gateway 의 auth() 가 이어서 보는 것
    if not claims.get("object_key_prefix"):
        raise GoTicketError("TICKET_SCOPE_MISMATCH")
    return claims


@override_settings(TICKET_KEY=TICKET_KEY)
class TicketTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        cls.patient_account = Account.objects.create(
            login_id="yoon1971", role="patient", is_active=True)
        cls.patient.account = cls.patient_account
        cls.patient.save()

        cls.accounts, cls.staff = {}, {}
        for role in ("radiology", "pathology", "surgery", "nursing", "reception"):
            acc = Account.objects.create(login_id=role + "1", role=role,
                                         is_active=True)
            cls.accounts[role] = acc
            cls.staff[role] = Staff.objects.create(account=acc, full_name=role)

        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mri",
            exam_purpose="diagnostic", ordered_by=cls.staff["radiology"])
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mri")
        cls.lesion = Lesion.objects.create(study=cls.study, patient=cls.patient)
        cls.specimen = Specimen.objects.create(
            patient=cls.patient, lesion=cls.lesion, accession_status="bound")
        cls.report = Report.objects.create(patient=cls.patient, study=cls.study,
                                           report_type="stage")

        cls.other_patient = Patient.objects.create(patient_number="E_2000001")
        cls.other_report = Report.objects.create(patient=cls.other_patient,
                                                 report_type="final")

    def ask(self, account, **body):
        token = issue_access(account)
        return self.client.post(reverse("ticket-issue"), data=body,
                                content_type="application/json",
                                headers={"authorization": "Bearer " + token})


class GoCompatibilityTests(TicketTestCase):
    def test_우리가_낸_티켓을_Go_가_통과시킨다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        self.assertEqual(r.status_code, 200)
        claims = go_verify(TICKET_KEY.encode(), r.json()["data"]["token"], set())
        self.assertEqual(claims["purpose"], "dicom_upload")
        self.assertEqual(claims["object_key_prefix"],
                         "study/%d" % self.study.pk)

    def test_클레임이_Go_구조체와_같은_이름이다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        claims = go_verify(TICKET_KEY.encode(), r.json()["data"]["token"], set())
        self.assertLessEqual(
            {"purpose", "patient_id", "scope_id", "object_key_prefix",
             "exp", "nonce", "max_bytes"}, set(claims))

    def test_patient_id_와_scope_id_가_문자열이다(self):
        # Go 구조체가 string 이다. 숫자로 보내면 json.Unmarshal 이 실패한다.
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        claims = go_verify(TICKET_KEY.encode(), r.json()["data"]["token"], set())
        self.assertIsInstance(claims["scope_id"], str)
        self.assertIsInstance(claims["patient_id"], str)

    def test_다른_키로_서명하면_Go_가_막는다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        with self.assertRaises(GoTicketError) as caught:
            go_verify(b"wrong-key", r.json()["data"]["token"], set())
        self.assertEqual(str(caught.exception), "TICKET_SIGNATURE")

    def test_nonce_가_매번_다르다(self):
        seen = set()
        for _ in range(5):
            r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                         scope_id=self.study.pk)
            go_verify(TICKET_KEY.encode(), r.json()["data"]["token"], seen)
        self.assertEqual(len(seen), 5)

    def test_같은_티켓을_두_번_쓰면_Go_가_재사용으로_본다(self):
        # 쓰기는 1 회용 그대로다. 읽기는 Go 가 소진을 뺐지만 클레임은 유지된다.
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        token, used = r.json()["data"]["token"], set()
        go_verify(TICKET_KEY.encode(), token, used)
        with self.assertRaises(GoTicketError) as caught:
            go_verify(TICKET_KEY.encode(), token, used)
        self.assertEqual(str(caught.exception), "TICKET_REPLAYED")

    def test_만료된_티켓은_Go_가_막는다(self):
        with override_settings(TICKET_TTL_SEC={**self._ttl(), "dicom_upload": -1}):
            token, _, _ = issue("dicom_upload", "study", self.study.pk)
        with self.assertRaises(GoTicketError) as caught:
            go_verify(TICKET_KEY.encode(), token, set())
        self.assertEqual(str(caught.exception), "TICKET_EXPIRED")

    @staticmethod
    def _ttl():
        from django.conf import settings
        return dict(settings.TICKET_TTL_SEC)


class PrefixTests(TicketTestCase):
    """접두사가 권한 경계다 — 검사 하나로 좁혀야 한다."""

    def test_검사_하나로_좁혀진다(self):
        self.assertEqual(object_key_prefix("study", 51201), "study/51201")

    def test_넓은_접두사가_안_나온다(self):
        for purpose, kind, target in (
                ("dicom_upload", "study", self.study),
                ("wsi_upload", "specimen", self.specimen),
                ("report_pdf", "report", self.report)):
            role = next(iter(PURPOSE_ROLES[purpose]))
            r = self.ask(self.accounts[role], purpose=purpose, scope_id=target.pk)
            prefix = r.json()["data"]["object_key_prefix"]
            self.assertEqual(prefix, "%s/%d" % (kind, target.pk))
            # "study/" 처럼 대상 없이 끝나면 그 아래가 전부 열린다
            self.assertFalse(prefix.endswith("/"))
            self.assertIn("/", prefix)

    def test_접두사에_환자번호가_없다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        self.assertNotIn(self.patient.patient_number,
                         r.json()["data"]["object_key_prefix"])


class TtlTests(TicketTestCase):
    def test_purpose_마다_유효기간이_다르다(self):
        from django.conf import settings

        self.assertEqual(settings.TICKET_TTL_SEC["tile"], 900)
        self.assertEqual(settings.TICKET_TTL_SEC["download"], 120)
        self.assertEqual(settings.TICKET_TTL_SEC["dicom_upload"], 300)

    def test_발급된_티켓의_exp_가_그_값을_따른다(self):
        before = int(time.time())
        _, claims, _ = issue("download", "report", self.report.pk)
        self.assertLessEqual(claims["exp"] - before, 120 + 2)
        _, claims, _ = issue("tile", "study", self.study.pk)
        self.assertGreater(claims["exp"] - before, 800)

    def test_상한이_없으면_Go_가_무제한으로_받는다(self):
        # 업로드는 반드시 max_bytes 가 있어야 한다.
        _, claims, _ = issue("dicom_upload", "study", self.study.pk)
        self.assertGreater(claims["max_bytes"], 0)

    def test_클라이언트는_더_작게만_요청할_수_있다(self):
        _, claims, _ = issue("dicom_upload", "study", self.study.pk,
                             max_bytes=10 ** 12)
        self.assertEqual(claims["max_bytes"],
                         self._cap("dicom_upload"))
        _, claims, _ = issue("dicom_upload", "study", self.study.pk,
                             max_bytes=1024)
        self.assertEqual(claims["max_bytes"], 1024)

    @staticmethod
    def _cap(purpose):
        from django.conf import settings
        return settings.TICKET_MAX_BYTES[purpose]


class IssuePermissionTests(TicketTestCase):
    def test_역할마다_낼_수_있는_purpose_가_다르다(self):
        cases = [("radiology", "dicom_upload", self.study.pk, 200),
                 ("pathology", "dicom_upload", self.study.pk, 403),
                 ("pathology", "wsi_upload", self.specimen.pk, 200),
                 ("radiology", "wsi_upload", self.specimen.pk, 403),
                 ("surgery", "report_pdf", self.report.pk, 200),
                 ("radiology", "report_pdf", self.report.pk, 403)]
        for role, purpose, scope_id, expected in cases:
            r = self.ask(self.accounts[role], purpose=purpose, scope_id=scope_id)
            self.assertEqual(r.status_code, expected, (role, purpose))

    def test_derived_upload_은_사람이_못_낸다(self):
        for role in self.accounts:
            r = self.ask(self.accounts[role], purpose="derived_upload",
                         scope_kind="study", scope_id=self.study.pk)
            self.assertEqual(r.status_code, 403, role)

    def test_derived_upload_은_Celery_가_직접_부른다(self):
        # 사람 토큰 없이 issue() 를 쓴다 — 권한 판정은 부르는 쪽 몫이다.
        token, claims, _ = issue("derived_upload", "study", self.study.pk)
        self.assertEqual(claims["purpose"], "derived_upload")
        go_verify(TICKET_KEY.encode(), token, set())

    def test_prescription_pdf_는_422(self):
        with self.assertLogs("core.api.tickets", level="WARNING"):
            r = self.ask(self.accounts["surgery"], purpose="prescription_pdf",
                         scope_id=self.report.pk)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "UNSUPPORTED_PURPOSE")

    def test_모르는_purpose_는_400(self):
        r = self.ask(self.accounts["radiology"], purpose="아무거나",
                     scope_id=self.study.pk)
        self.assertEqual(r.status_code, 400)

    def test_대상이_없으면_422(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=99999)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "TARGET_NOT_FOUND")

    def test_scope_id_가_없으면_400(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload")
        self.assertEqual(r.status_code, 400)

    def test_인증이_없으면_401(self):
        r = self.client.post(reverse("ticket-issue"),
                             data={"purpose": "dicom_upload", "scope_id": 1},
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)


class ScopeKindTests(TicketTestCase):
    def test_대상이_하나뿐이면_요청이_안_정해도_된다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        self.assertEqual(r.json()["data"]["scope_kind"], "study")

    def test_요청이_엉뚱한_scope_kind_를_보내도_purpose_가_이긴다(self):
        r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_kind="report", scope_id=self.study.pk)
        self.assertEqual(r.json()["data"]["scope_kind"], "study")

    def test_대상이_여럿이면_정해야_한다(self):
        r = self.ask(self.accounts["radiology"], purpose="tile",
                     scope_id=self.study.pk)
        self.assertEqual(r.status_code, 400)

    def test_정하면_그대로_쓴다(self):
        r = self.ask(self.accounts["pathology"], purpose="tile",
                     scope_kind="specimen", scope_id=self.specimen.pk)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["data"]["object_key_prefix"],
                         "specimen/%d" % self.specimen.pk)


class ReadPermissionTests(TicketTestCase):
    """download · tile 은 §15 매트릭스 R + 환자는 본인 것만."""

    def test_판독의는_검사_타일을_받는다(self):
        r = self.ask(self.accounts["radiology"], purpose="tile",
                     scope_kind="study", scope_id=self.study.pk)
        self.assertEqual(r.status_code, 200)

    def test_원무는_타일을_못_받는다(self):
        # §15 에서 원무는 study 에 권한이 없다
        r = self.ask(self.accounts["reception"], purpose="tile",
                     scope_kind="study", scope_id=self.study.pk)
        self.assertEqual(r.status_code, 403)

    def test_환자는_자기_리포트를_받는다(self):
        r = self.ask(self.patient_account, purpose="download",
                     scope_kind="report", scope_id=self.report.pk)
        self.assertEqual(r.status_code, 200)

    def test_환자는_남의_리포트를_못_받는다(self):
        r = self.ask(self.patient_account, purpose="download",
                     scope_kind="report", scope_id=self.other_report.pk)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "ROLE_FORBIDDEN")

    def test_환자는_검사_원본을_못_받는다(self):
        # §15 에서 환자는 study 에 권한이 없다 — 영상은 리포트로만 본다
        r = self.ask(self.patient_account, purpose="download",
                     scope_kind="study", scope_id=self.study.pk)
        self.assertEqual(r.status_code, 403)

    def test_환자는_타일을_아예_못_받는다(self):
        r = self.ask(self.patient_account, purpose="tile",
                     scope_kind="study", scope_id=self.study.pk)
        self.assertEqual(r.status_code, 403)


class IssueLogTests(TicketTestCase):
    def test_발급_이력이_남는다(self):
        with self.assertLogs("core.api.tickets", level="INFO") as caught:
            self.ask(self.accounts["radiology"], purpose="dicom_upload",
                     scope_id=self.study.pk)
        line = caught.output[0]
        for piece in ("trace=", "account=", "purpose=dicom_upload",
                      "scope=study/", "nonce=", "exp="):
            self.assertIn(piece, line)


class KeySeparationTests(SimpleTestCase):
    """TICKET_KEY 와 CALLBACK_SECRET 은 방향이 반대라 같으면 안 된다.

    설정만 보므로 DB 를 쓰지 않는다.
    """

    def _run(self):
        from core.apps import check_signing_keys
        return check_signing_keys(None)

    @override_settings(TICKET_KEY="같은값", CALLBACK_SECRET="같은값")
    def test_같은_값이면_기동_때_걸린다(self):
        ids = [p.id for p in self._run()]
        self.assertIn("core.E001", ids)

    @override_settings(TICKET_KEY="가", CALLBACK_SECRET="나")
    def test_다르면_통과한다(self):
        self.assertEqual([p.id for p in self._run() if p.id == "core.E001"], [])

    @override_settings(TICKET_KEY="", CALLBACK_SECRET="나")
    def test_비어_있으면_경고한다(self):
        self.assertIn("core.W001", [p.id for p in self._run()])


class NoTicketKeyTests(TicketTestCase):
    @override_settings(TICKET_KEY="")
    def test_키가_없으면_발급하지_않는다(self):
        with self.assertLogs("core.api.tickets", level="ERROR"):
            r = self.ask(self.accounts["radiology"], purpose="dicom_upload",
                         scope_id=self.study.pk)
        self.assertEqual(r.status_code, 500)
