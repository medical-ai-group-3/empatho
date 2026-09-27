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

    def test_입력이_인증과_다르면_거절(self, _):
        r = self.c.post("/api/v1/signup/identity", {**FORM, "sex": "male"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_가입하면_환자와_계정이_이어진다(self, _):
        self.assertEqual(self._link().status_code, 201)
        p = models.Patient.objects.get(pii__phone="01011112222")
        self.assertEqual((p.account.login_id, p.sex, p.birth_year, p.account.phone_verified),
                         ("kim1", "female", 1980, True))

    def test_원무과가_먼저_등록한_환자에_잇는다(self, _):
        p = models.Patient.objects.create(patient_number="P-OLD")
        models.PatientPii.objects.create(patient=p, name="김환자",
                                         birth_date="1980-01-02", phone="01011112222")
        self.assertEqual(self._link().status_code, 201)
        p.refresh_from_db()
        self.assertEqual(p.account.login_id, "kim1")

    def test_이미_가입한_환자는_다시_못한다(self, _):
        self._link()
        r = self.c.post("/api/v1/signup/identity", FORM, format="json")
        self.assertEqual(r.status_code, 400)
