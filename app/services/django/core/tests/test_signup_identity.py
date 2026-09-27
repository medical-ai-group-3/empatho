"""앱 가입 본인인증 — 포트원 조회(_fetch)는 가짜로 바꿔 끼운다."""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from core import models

OK = {"status": "VERIFIED", "verifiedCustomer": {
    "name": "김환자", "birthDate": "1980-01-02", "gender": "FEMALE",
    "phoneNumber": "01011112222"}}
FORM = {"identity_verification_id": "iv-1", "name": "김환자",
        "birth_date": "1980-01-02", "sex": "female", "phone": "010-1111-2222"}


@mock.patch("core.api.signup._fetch", return_value=OK)
class SignupIdentityTests(TestCase):
    def setUp(self):
        self.c = APIClient()

    def _link(self):
        token = self.c.post("/api/v1/signup/identity", FORM,
                            format="json").json()["data"]["verify_token"]
        return self.c.post("/api/v1/signup/link",
                           {"verify_token": token, "username": "kim1", "password": "pw123456"},
                           format="json")

    @mock.patch("core.api.signup.MATCH_CHECK", True)
    def test_대조를_켜면_입력이_인증과_다를때_거절(self, _):
        r = self.c.post("/api/v1/signup/identity", {**FORM, "sex": "male"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_가입하면_환자와_계정이_이어진다(self, _):
        self.assertEqual(self._link().status_code, 201)
        p = models.Patient.objects.get(pii__phone="01011112222")
        self.assertEqual((p.account.login_id, p.sex, p.birth_year, p.account.phone_verified),
                         ("kim1", "female", 1980, True))

    def _old_patient(self):
        p = models.Patient.objects.create(patient_number="P-OLD")
        models.PatientPii.objects.create(patient=p, name="김환자",
                                         birth_date="1980-01-02", phone="01011112222")
        return p

    @mock.patch("core.api.signup.MATCH_CHECK", True)
    def test_대조를_켜면_원무과가_먼저_등록한_환자에_잇는다(self, _):
        p = self._old_patient()
        self.assertEqual(self._link().status_code, 201)
        p.refresh_from_db()
        self.assertEqual(p.account.login_id, "kim1")

    def test_대조를_끄면_기존_환자에_잇지_않는다(self, _):
        # 본인인증만 하고 남의 정보로 그 사람 기록에 들어가는 길을 막는다
        p = self._old_patient()
        self.assertEqual(self._link().status_code, 400)
        p.refresh_from_db()
        self.assertIsNone(p.account_id)

    def test_임시로_대조없이_입력값으로_가입된다(self, _):
        # MATCH_CHECK 를 True 로 되돌리면 이 테스트를 지운다
        form = {**FORM, "name": "테스트이", "birth_date": "1970-05-06",
                "sex": "male", "phone": "01099998888"}
        r = self.c.post("/api/v1/signup/identity", form, format="json")
        self.assertEqual(r.status_code, 200)
        r = self.c.post("/api/v1/signup/link",
                        {"verify_token": r.json()["data"]["verify_token"],
                         "username": "kim2", "password": "pw123456"}, format="json")
        self.assertEqual(r.status_code, 201)
        a = models.Account.objects.get(login_id="kim2")
        p = a.patient
        self.assertEqual((p.pii.name, str(p.pii.birth_date), p.sex, p.pii.phone, a.phone_verified),
                         ("테스트이", "1970-05-06", "male", "01099998888", False))

    def test_이미_가입한_환자는_다시_못한다(self, _):
        self._link()
        r = self.c.post("/api/v1/signup/identity", FORM, format="json")
        self.assertEqual(r.status_code, 400)
