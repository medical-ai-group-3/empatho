# -*- coding: utf-8 -*-
"""POST/GET /patients/{id}/prescriptions — 유방외과 처방.

생성은 유방외과만, 조회는 유방외과 + 원무(서류 발급 화면)."""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from core.api.auth import issue_access
from core.models import (
    Account,
    ExamOrder,
    Patient,
    PatientPii,
    PrescriptionDrug,
    Report,
    Staff,
)


def _client_for(account):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + issue_access(account))
    return c


class PrescriptionTests(TestCase):
    def setUp(self):
        self.surgery_account = Account.objects.create(
            login_id="rx-surgery-test", role="surgery",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.surgery_account, staff_number="SUR-RX-001", full_name="처방 테스트",
        )
        self.reception_account = Account.objects.create(
            login_id="rx-reception-test", role="reception",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.reception_account, staff_number="REC-RX-001", full_name="처방 조회 테스트",
        )
        self.radiology_account = Account.objects.create(
            login_id="rx-radiology-test", role="radiology",
            account_status="active", is_active=True,
        )
        Staff.objects.create(
            account=self.radiology_account, staff_number="RAD-RX-001", full_name="처방 무관 테스트",
        )

        self.patient = Patient.objects.create(patient_number="P-RX-001")
        PatientPii.objects.create(
            patient=self.patient, name="처방테스트환자", birth_date=date(1995, 5, 5),
            phone="010-9999-0000",
        )
        self.other_patient = Patient.objects.create(patient_number="P-RX-002")
        PatientPii.objects.create(
            patient=self.other_patient, name="다른환자", birth_date=date(1996, 6, 6),
            phone="010-1234-5678",
        )

        self.order = ExamOrder.objects.create(
            patient=self.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.surgery_account.staff,
        )
        self.other_order = ExamOrder.objects.create(
            patient=self.other_patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=self.surgery_account.staff,
        )
        self.report = Report.objects.create(patient=self.patient)

        self.client = _client_for(self.surgery_account)

    def test_surgery_creates_prescription_linked_to_exam_order(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk, "content": {"drug": "타목시펜", "dose": "1일 1회"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["patient"], self.patient.pk)
        self.assertEqual(data["exam_order"], self.order.pk)
        self.assertIsNone(data["report"])
        self.assertEqual(data["content"], {"drug": "타목시펜", "dose": "1일 1회"})
        self.assertIsNotNone(data["prescribed_at"])

    def test_surgery_creates_prescription_linked_to_report(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"report_id": self.report.pk, "content": {"drug": "아나스트로졸"}},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(data["report"], self.report.pk)
        self.assertIsNone(data["exam_order"])

    def test_both_exam_order_and_report_is_rejected(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk, "report_id": self.report.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_neither_exam_order_nor_report_is_rejected(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"content": {"drug": "무엇에도 안 매달림"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_exam_order_of_another_patient_is_rejected(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.other_order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reception_cannot_create(self):
        other_client = _client_for(self.reception_account)
        response = other_client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_radiology_cannot_create_or_read(self):
        other_client = _client_for(self.radiology_account)
        create_response = other_client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk},
            format="json",
        )
        self.assertEqual(create_response.status_code, 403)

        list_response = other_client.get(f"/api/v1/patients/{self.patient.pk}/prescriptions")
        self.assertEqual(list_response.status_code, 403)

    def test_reception_can_list_for_document_issuance(self):
        self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk, "content": {"drug": "타목시펜"}},
            format="json",
        )
        other_client = _client_for(self.reception_account)
        response = other_client.get(f"/api/v1/patients/{self.patient.pk}/prescriptions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 1)

    def test_surgery_can_list(self):
        self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"exam_order_id": self.order.pk}, format="json",
        )
        self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"report_id": self.report.pk}, format="json",
        )
        response = self.client.get(f"/api/v1/patients/{self.patient.pk}/prescriptions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["data"]), 2)

    def test_missing_patient_is_404(self):
        response = self.client.get("/api/v1/patients/999999/prescriptions")
        self.assertEqual(response.status_code, 404)


class PrescriptionDrugRouteFormTests(TestCase):
    """content.drugs 의 투여 경로(route) · 제형(form). 09-28 추가 — 둘 다 선택."""

    def setUp(self):
        surgeon = Account.objects.create(
            login_id="rx-route-surgery", role="surgery",
            account_status="active", is_active=True,
        )
        Staff.objects.create(account=surgeon, staff_number="SUR-RX-101", full_name="경로 테스트")
        self.patient_account = Account.objects.create(
            login_id="rx-route-patient", role="patient",
            account_status="active", is_active=True,
        )
        self.patient = Patient.objects.create(patient_number="P-RX-101",
                                              account=self.patient_account)
        self.report = Report.objects.create(patient=self.patient)
        self.client = _client_for(surgeon)

    def _drug(self, **extra):
        return {"name": "타목시펜정", "ingredient": "타목시펜", "dose": "1정",
                "times": ["09:00"], "days": 30, **extra}

    def _post(self, *drugs):
        return self.client.post(
            f"/api/v1/patients/{self.patient.pk}/prescriptions",
            {"report_id": self.report.pk, "content": {"drugs": list(drugs)}},
            format="json",
        )

    def test_route_and_form_saved_and_read_back(self):
        res = self._post(self._drug(route="oral", form="정제"),
                         self._drug(name="졸라덱스", route="injection", form="주사제"))
        self.assertEqual(res.status_code, 201, res.content)

        rows = {d.name: d for d in PrescriptionDrug.objects.filter(
            prescription__patient=self.patient)}
        self.assertEqual((rows["타목시펜정"].route, rows["타목시펜정"].form), ("oral", "정제"))
        self.assertEqual((rows["졸라덱스"].route, rows["졸라덱스"].form), ("injection", "주사제"))

        # 의사 쪽 목록 — content 는 보낸 그대로다.
        listed = self.client.get(f"/api/v1/patients/{self.patient.pk}/prescriptions")
        drugs = listed.json()["data"][0]["content"]["drugs"]
        self.assertEqual(drugs[0]["route"], "oral")
        self.assertEqual(drugs[0]["form"], "정제")

        # 환자 쪽 목록 — 행에서 읽는다.
        mine = _client_for(self.patient_account).get("/api/v1/me/prescriptions")
        self.assertEqual(mine.status_code, 200, mine.content)
        got = {d["name"]: d for d in mine.json()["data"]["items"][0]["drugs"]}
        self.assertEqual((got["졸라덱스"]["route"], got["졸라덱스"]["form"]),
                         ("injection", "주사제"))

    def test_invalid_route_is_400(self):
        res = self._post(self._drug(route="경구"))
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertFalse(PrescriptionDrug.objects.exists())

    def test_missing_or_blank_route_form_is_fine(self):
        res = self._post(self._drug(), self._drug(name="빈칸", route="", form=""),
                         self._drug(name="널", route=None, form=None))
        self.assertEqual(res.status_code, 201, res.content)
        for d in PrescriptionDrug.objects.all():
            self.assertIsNone(d.route, d.name)
            self.assertIsNone(d.form, d.name)
