# -*- coding: utf-8 -*-
"""storage_object 는 파일 단위다.

Go 가 파일(SOP instance) 하나마다 I-1 콜백을 부른다. 파일마다 object_key 와
checksum 이 달라 한 행에 담기지 않는다. MRI 한 시리즈가 176 장이면 176 행이다.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Account, ExamOrder, Patient, StorageObject, Study


class StorageObjectFileUnitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        patient = Patient.objects.create(patient_number="E_1029304")
        account = Account.objects.create(login_id="rad1", role="radiology",
                                         is_active=True)
        from core.models import Staff
        staff = Staff.objects.create(account=account, full_name="김판독")
        order = ExamOrder.objects.create(
            patient=patient, order_status="ordered", modality="mri",
            exam_purpose="diagnostic", ordered_by=staff)
        cls.study = Study.objects.create(patient=patient, exam_order=order,
                                         modality="mri")

    def _file(self, n, series="1.2.3.SERIES", sop=None):
        return StorageObject.objects.create(
            study=self.study, series_uid=series,
            sop_instance_uid=sop if sop is not None else "1.2.3.SOP.%d" % n,
            object_key="mri/%04d.dcm" % n, orthanc_series_id=None,
            checksum_sha256="%064d" % n)

    def test_한_시리즈에_파일이_여럿_들어간다(self):
        # 예전엔 series_uid 가 UNIQUE 라 두 번째 파일에서 막혔다.
        for n in range(176):
            self._file(n)
        rows = StorageObject.objects.filter(series_uid="1.2.3.SERIES")
        self.assertEqual(rows.count(), 176)
        self.assertEqual(rows.values("series_uid").distinct().count(), 1)

    def test_같은_DICOM_파일은_두_번_안_들어간다(self):
        self._file(1, sop="1.2.3.SOP.SAME")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._file(2, sop="1.2.3.SOP.SAME")

    def test_DICOM_이_아닌_파일은_sop_가_비어_있어도_여럿이다(self):
        # 병리 PNG 등. 부분 UNIQUE 라 NULL 은 서로 안 부딪힌다.
        for n in range(5):
            StorageObject.objects.create(
                study=self.study, sop_instance_uid=None,
                object_key="path/%d.png" % n, content_type="image/png")
        self.assertEqual(
            StorageObject.objects.filter(sop_instance_uid__isnull=True).count(), 5)

    def test_object_key_는_여전히_유일하다(self):
        # I-1 의 멱등키다. 같은 객체를 두 번 커밋해도 행이 하나여야 한다.
        self._file(1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StorageObject.objects.create(
                    study=self.study, object_key="mri/0001.dcm",
                    sop_instance_uid="1.2.3.SOP.OTHER")

    def test_I1_재시도가_행을_두_번_만들지_않는다(self):
        # I-1 은 object_key 로 멱등을 잡는다 — payload 에 그것뿐이고
        # sop_instance_uid 는 I-2 에서야 온다.
        for _ in range(3):
            StorageObject.objects.get_or_create(
                object_key="mri/dup.dcm",
                defaults={"study": self.study, "checksum_sha256": "a" * 64})
        self.assertEqual(
            StorageObject.objects.filter(object_key="mri/dup.dcm").count(), 1)
