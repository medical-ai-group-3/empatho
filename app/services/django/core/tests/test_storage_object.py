# -*- coding: utf-8 -*-
"""storage_object 는 파일 단위다.

Go 가 파일(SOP instance) 하나마다 I-1 콜백을 부른다. 파일마다 object_key 와
checksum 이 달라 한 행에 담기지 않는다. MRI 한 시리즈가 176 장이면 176 행이다.

주인은 study · specimen · report 셋 중 정확히 하나다 — 티켓 purpose 가
dicom_upload · wsi_upload · report_pdf 로 갈린다.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import (Account, ExamOrder, Patient, Report, Staff,
                         StorageObject, Study)


class StorageObjectFileUnitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        account = Account.objects.create(login_id="rad1", role="radiology",
                                         is_active=True)
        staff = Staff.objects.create(account=account, full_name="김판독")
        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mri",
            exam_purpose="diagnostic", ordered_by=staff)
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mri")

    def _file(self, n, series="1.2.3.SERIES", sop=None, **kwargs):
        base = dict(study=self.study, series_uid=series,
                    sop_instance_uid=sop if sop is not None else "1.2.3.SOP.%d" % n,
                    bucket="empatho-original", object_key="mri/%04d.dcm" % n,
                    checksum_sha256="%064d" % n)
        base.update(kwargs)
        return StorageObject.objects.create(**base)

    def test_한_시리즈에_파일이_여럿_들어간다(self):
        # 예전엔 series_uid 가 UNIQUE 라 두 번째 파일에서 막혔다.
        for n in range(176):
            self._file(n)
        rows = StorageObject.objects.filter(series_uid="1.2.3.SERIES")
        self.assertEqual(rows.count(), 176)
        self.assertEqual(rows.values("series_uid").distinct().count(), 1)

    def test_같은_SOP_UID_가_둘이어도_막지_않는다(self):
        # UNIQUE 를 걸지 않는다 — I-1 시점에 이 칸이 NULL 이라 INSERT 를 못 막고,
        # I-2 가 UPDATE 할 때 터지면 그땐 이미 행이 두 개다.
        self._file(1, sop="1.2.3.SOP.SAME")
        self._file(2, sop="1.2.3.SOP.SAME")
        self.assertEqual(
            StorageObject.objects.filter(sop_instance_uid="1.2.3.SOP.SAME").count(), 2)


class ObjectKeyIdempotencyTests(StorageObjectFileUnitTests):
    """I-1 의 멱등키는 (bucket, object_key) 다."""

    def test_같은_버킷의_같은_키는_두_번_안_들어간다(self):
        self._file(1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._file(2, object_key="mri/0001.dcm")

    def test_버킷이_다르면_같은_키를_쓸_수_있다(self):
        self._file(1)
        self._file(2, bucket="empatho-derived", object_key="mri/0001.dcm")
        self.assertEqual(
            StorageObject.objects.filter(object_key="mri/0001.dcm").count(), 2)

    def test_Orthanc_에_둔_파일은_둘_다_비어_서로_안_부딪힌다(self):
        for n in range(3):
            StorageObject.objects.create(
                study=self.study, bucket=None, object_key=None,
                orthanc_series_id="orthanc-%d" % n)
        self.assertEqual(
            StorageObject.objects.filter(object_key__isnull=True).count(), 3)

    def test_I1_재시도가_행을_두_번_만들지_않는다(self):
        for _ in range(3):
            StorageObject.objects.get_or_create(
                bucket="empatho-original", object_key="mri/dup.dcm",
                defaults={"study": self.study, "checksum_sha256": "a" * 64})
        self.assertEqual(
            StorageObject.objects.filter(object_key="mri/dup.dcm").count(), 1)


class OwnerTests(StorageObjectFileUnitTests):
    """주인은 셋 중 정확히 하나 — num_nonnulls(study, specimen, report) = 1."""

    def _report(self):
        return Report.objects.create(patient=self.patient, study=self.study,
                                     report_type="stage", audience="clinician")

    def test_리포트_PDF_가_들어간다(self):
        # 전에는 study ⊕ specimen 둘뿐이라 한 행도 못 들어갔다.
        obj = StorageObject.objects.create(
            report=self._report(), bucket="empatho-derived",
            object_key="report/1001/x.pdf", content_type="application/pdf")
        self.assertIsNone(obj.study_id)
        self.assertIsNotNone(obj.report_id)

    def test_주인이_없으면_막힌다(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StorageObject.objects.create(bucket="b", object_key="k")

    def test_주인이_둘이면_막힌다(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                StorageObject.objects.create(
                    study=self.study, report=self._report(),
                    bucket="b", object_key="k2")
