# -*- coding: utf-8 -*-
"""MRI 병변 메시 — 병변 행이 생긴 뒤 그 번호를 달고 올라간다 · 이름은 자동."""

from unittest import mock

from django.test import TestCase

from core import mesh, tasks
from core.models import (Account, AiResult, ExamOrder, Image, Lesion, Patient,
                         Staff, StorageObject, Study)
from core.serializers import LesionSerializer


class LesionMeshTestCase(TestCase):
    def setUp(self):
        patient = Patient.objects.create(patient_number="E_1029305")
        staff = Staff.objects.create(
            account=Account.objects.create(login_id="rad9", role="radiology",
                                           is_active=True),
            full_name="김판독")
        order = ExamOrder.objects.create(
            patient=patient, order_status="ordered", modality="mri",
            exam_purpose="diagnostic", ordered_by=staff)
        self.study = Study.objects.create(patient=patient, exam_order=order,
                                          modality="mri")
        self.source = StorageObject.objects.create(
            study=self.study, bucket="empatho-original", object_key="study/x/1.dcm")
        self.ai = AiResult.objects.create(
            patient=patient, study=self.study, source_object=self.source,
            result={"result": {"tumor": {"lesions": [{}, {}]}}})

    def test_병변_메시가_병변_번호를_달고_올라간다(self):
        tasks._store_lesions(self.ai)
        rows = Lesion.objects.filter(ai_result=self.ai).order_by("lesion_index")
        self.assertEqual([l.label for l in rows], ["MRI-1", "MRI-2"])

        part = mesh.MeshPart(mesh.LESION_KIND, 1, "mesh_lesion-1-9.json", b"{}", 3)
        with mock.patch.object(tasks, "_upload_derived") as up:
            tasks._store_lesion_meshes(self.ai, [part])
        self.assertEqual(up.call_args.kwargs["lesion_id"], rows[1].pk)

        # 업로드 콜백이 만든 행을 흉내 — 직렬화에 주소가 실린다
        Image.objects.create(source_object=self.source, ai_result=self.ai,
                             lesion=rows[1], kind="mesh_lesion",
                             bucket="empatho-derived", object_key="study/1/m.json")
        self.assertEqual(LesionSerializer(rows[1]).data["mesh"]["key"], "study/1/m.json")
        self.assertIsNone(LesionSerializer(rows[0]).data["mesh"])

        # 재판독 — 메시가 달린 옛 병변도 지우고 다시 만든다(PROTECT 로 멈추지 않는다)
        tasks._store_lesions(self.ai)
        self.assertEqual(Lesion.objects.filter(ai_result=self.ai).count(), 2)
