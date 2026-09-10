# -*- coding: utf-8 -*-
"""patient.primary_staff — 주치의.

간호과가 환자를 배정할 때 지정한다. 알림은 걸지 않는다 — 화면에 이름만 뜬다.
"""

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from core.api import permissions as perm
from core.models import Account, Patient, Staff


class PrimaryStaffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doctor = Staff.objects.create(
            account=Account.objects.create(login_id="sur1", role="surgery",
                                           is_active=True),
            full_name="김서연")
        cls.other = Staff.objects.create(
            account=Account.objects.create(login_id="sur2", role="surgery",
                                           is_active=True),
            full_name="박지훈")

    def test_주치의를_지정한다(self):
        p = Patient.objects.create(patient_number="E_1029304",
                                   primary_staff=self.doctor)
        p.refresh_from_db()
        self.assertEqual(p.primary_staff.full_name, "김서연")

    def test_없어도_된다(self):
        # 원무가 등록할 때는 아직 배정 전이다
        p = Patient.objects.create(patient_number="E_2000001")
        self.assertIsNone(p.primary_staff_id)

    def test_나중에_배정한다(self):
        p = Patient.objects.create(patient_number="E_3000001")
        p.primary_staff = self.doctor
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.primary_staff_id, self.doctor.pk)

    def test_담당의가_바뀔_수_있다(self):
        p = Patient.objects.create(patient_number="E_4000001",
                                   primary_staff=self.doctor)
        p.primary_staff = self.other
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.primary_staff.full_name, "박지훈")

    def test_배정된_의료진은_못_지운다(self):
        # PROTECT — 환자가 매달려 있으면 staff 행이 안 지워진다
        Patient.objects.create(patient_number="E_5000001",
                               primary_staff=self.doctor)
        with self.assertRaises(Exception):
            with transaction.atomic():
                self.doctor.delete()

    def test_내_환자_목록이_바로_나온다(self):
        # 유방외과 로그인 시 「내 환자 목록」 필터
        for n in range(3):
            Patient.objects.create(patient_number="E_60000%d" % n,
                                   primary_staff=self.doctor)
        Patient.objects.create(patient_number="E_700000", primary_staff=self.other)
        self.assertEqual(self.doctor.primary_patients.count(), 3)
        self.assertEqual(self.other.primary_patients.count(), 1)


class PrimaryStaffPermissionTests(SimpleTestCase):
    """§15 첫 행이 이미 주는 권한으로 충분한지."""

    def test_간호가_환자를_고칠_수_있다(self):
        # 주치의 배정이 patient 의 U 다. §15 에 이미 있어 새로 정할 것이 없다.
        self.assertTrue(perm.rule_for("patient", perm.NURSING).allows("U"))

    def test_원무도_고칠_수_있다(self):
        self.assertTrue(perm.rule_for("patient", perm.RECEPTION).allows("U"))

    def test_영상의학은_읽기만(self):
        rule = perm.rule_for("patient", perm.RADIOLOGY)
        self.assertTrue(rule.allows("R"))
        self.assertFalse(rule.allows("U"))

    def test_유방외과도_읽기만(self):
        # 「내 환자 목록」은 읽기다. 배정은 간호가 한다.
        rule = perm.rule_for("patient", perm.SURGERY)
        self.assertTrue(rule.allows("R"))
        self.assertFalse(rule.allows("U"))
