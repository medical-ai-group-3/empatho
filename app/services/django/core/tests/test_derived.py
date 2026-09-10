# -*- coding: utf-8 -*-
"""파생물 — 티켓 클레임과 I-1 이 만드는 image 행.

파생물은 storage_object 가 아니라 image 로 간다. v10 이 그 표를 따로 두고
source_object · ai_result · lesion 로 「어디서 왔나」를 남긴다. 바이트 주소는
image 자신의 bucket · object_key 다 — 파생물은 Garage 에만 있다.
"""

import json
import time

from django.test import TestCase, override_settings

from core.api.internal import sign
from core.api.errors import ApiError
from core.api.tickets import DERIVED_REQUIRED, check_derived, issue
from core.models import (Account, AiResult, ExamOrder, Image, Lesion, Patient,
                         Specimen, Staff, StorageObject, Study)

SECRET = "test-callback-secret-0123456789abcdef"
TICKET_KEY = "ticket-key-0123456789abcdef0123456789abcdef"


@override_settings(CALLBACK_SECRET=SECRET, CALLBACK_TIMESTAMP_TOLERANCE_SEC=300,
                   TICKET_KEY=TICKET_KEY)
class DerivedTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        staff = Staff.objects.create(
            account=Account.objects.create(login_id="rad1", role="radiology",
                                           is_active=True),
            full_name="김판독")
        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=staff)
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mammo")
        cls.source = StorageObject.objects.create(
            study=cls.study, bucket="empatho-original",
            object_key="study/1/rcc.dcm")
        cls.ai_result = AiResult.objects.create(patient=cls.patient,
                                                study=cls.study)
        cls.lesion = Lesion.objects.create(study=cls.study, patient=cls.patient,
                                           ai_result=cls.ai_result)

        # 다른 검사 — 티켓 범위 검사에 쓴다
        other_order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="us",
            exam_purpose="diagnostic", ordered_by=staff)
        cls.other_study = Study.objects.create(
            patient=cls.patient, exam_order=other_order, modality="us")
        cls.other_source = StorageObject.objects.create(
            study=cls.other_study, bucket="empatho-original",
            object_key="study/2/us.dcm")

    def derived(self, **kw):
        base = {"kind": "overlay", "source_object_id": self.source.pk,
                "ai_result_id": self.ai_result.pk, "lesion_id": self.lesion.pk}
        base.update(kw)
        return base

    def post(self, payload):
        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        return self.client.post(
            "/internal/v1/storage-objects", data=body,
            content_type="application/json",
            headers={"X-Timestamp": ts,
                     "X-Signature": sign(SECRET.encode(), ts, body),
                     "Idempotency-Key": "derived-test"})

    def payload(self, **kw):
        base = {"bucket": "empatho-derived", "object_key": "derived/ov1.png",
                "checksum_sha256": "a" * 64, "byte_size": 2048,
                "content_type": "image/png", "purpose": "derived_upload",
                "scope_id": str(self.study.pk), "derived": self.derived()}
        base.update(kw)
        return base


class TicketClaimTests(DerivedTestCase):
    """kind · FK 를 티켓에 실어 서명한다."""

    def test_overlay_클레임이_티켓에_실린다(self):
        _, claims, _ = issue("derived_upload", "study", self.study.pk,
                             derived=self.derived())
        self.assertEqual(claims["kind"], "overlay")
        self.assertEqual(claims["source_object_id"], str(self.source.pk))
        self.assertEqual(claims["ai_result_id"], str(self.ai_result.pk))
        self.assertEqual(claims["lesion_id"], str(self.lesion.pk))

    def test_overlay_는_lesion_없이도_된다(self):
        _, claims, _ = issue("derived_upload", "study", self.study.pk,
                             derived=self.derived(lesion_id=None))
        self.assertEqual(claims["lesion_id"], "")

    def test_thumbnail_은_source_만_있으면_된다(self):
        _, claims, _ = issue("derived_upload", "study", self.study.pk,
                             derived={"kind": "thumbnail",
                                      "source_object_id": self.source.pk})
        self.assertEqual(claims["kind"], "thumbnail")
        self.assertEqual(claims["ai_result_id"], "")

    def test_아무도_안_내는_kind_는_거절한다(self):
        # 초음파는 폴리곤 JSON, 병리 응답에 마스크 없음, 맘모는 분할 안 함
        for kind in ("mask", "heatmap"):
            with self.assertRaises(ApiError) as caught:
                check_derived({"kind": kind, "source_object_id": self.source.pk},
                              "study", self.study.pk)
            self.assertEqual(caught.exception.code, "UNSUPPORTED_PURPOSE", kind)

    def test_한덩이_mesh_는_이제_없다(self):
        # 셋으로 나눴다. 옛 이름으로 오면 거절해야 한다.
        with self.assertRaises(ApiError) as caught:
            check_derived({"kind": "mesh", "source_object_id": self.source.pk,
                           "ai_result_id": self.ai_result.pk},
                          "study", self.study.pk)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_PURPOSE")

    def test_받는_kind_는_다섯이다(self):
        self.assertEqual(set(DERIVED_REQUIRED),
                         {"overlay", "thumbnail",
                          "mesh_breast", "mesh_dense", "mesh_lesion"})

    def test_검사_메시는_lesion_없이_된다(self):
        for kind in ("mesh_breast", "mesh_dense"):
            _, claims, _ = issue("derived_upload", "study", self.study.pk,
                                 derived={"kind": kind,
                                          "source_object_id": self.source.pk,
                                          "ai_result_id": self.ai_result.pk})
            self.assertEqual(claims["lesion_id"], "", kind)

    def test_병변_메시는_lesion_이_필수다(self):
        with self.assertRaises(ApiError) as caught:
            check_derived({"kind": "mesh_lesion",
                           "source_object_id": self.source.pk,
                           "ai_result_id": self.ai_result.pk},
                          "study", self.study.pk)
        self.assertIn("lesion_id", caught.exception.details["missing"])

    def test_병변_메시가_lesion_을_싣는다(self):
        _, claims, _ = issue("derived_upload", "study", self.study.pk,
                             derived=self.derived(kind="mesh_lesion"))
        self.assertEqual(claims["kind"], "mesh_lesion")
        self.assertEqual(claims["lesion_id"], str(self.lesion.pk))

    def test_overlay_에_ai_result_가_없으면_막힌다(self):
        with self.assertRaises(ApiError) as caught:
            check_derived(self.derived(ai_result_id=None), "study", self.study.pk)
        self.assertIn("ai_result_id", caught.exception.details["missing"])

    def test_원본이_티켓_범위_밖이면_거절한다(self):
        # study 1 티켓으로 study 2 의 파생물을 올리려는 것
        with self.assertRaises(ApiError) as caught:
            check_derived(self.derived(source_object_id=self.other_source.pk),
                          "study", self.study.pk)
        self.assertEqual(caught.exception.code, "ROLE_FORBIDDEN")

    def test_없는_원본이면_422(self):
        with self.assertRaises(ApiError) as caught:
            check_derived(self.derived(source_object_id=999999),
                          "study", self.study.pk)
        self.assertEqual(caught.exception.code, "TARGET_NOT_FOUND")


class DerivedCallbackTests(DerivedTestCase):
    """I-1 이 derived_upload 를 받으면 image 행을 만든다."""

    def test_image_행이_생긴다(self):
        r = self.post(self.payload())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["data"]["created"])

        image = Image.objects.get(object_key="derived/ov1.png")
        self.assertEqual(image.kind, "overlay")
        self.assertEqual(image.source_object_id, self.source.pk)
        self.assertEqual(image.ai_result_id, self.ai_result.pk)
        self.assertEqual(image.lesion_id, self.lesion.pk)

    def test_storage_object_는_안_만든다(self):
        before = StorageObject.objects.count()
        self.post(self.payload())
        self.assertEqual(StorageObject.objects.count(), before)

    def test_바이트_주소가_image_에_직접_들어간다(self):
        self.post(self.payload())
        image = Image.objects.get(object_key="derived/ov1.png")
        self.assertEqual(image.bucket, "empatho-derived")
        self.assertEqual(image.byte_size, 2048)
        self.assertEqual(image.checksum_sha256, "a" * 64)

    def test_thumbnail_은_실행_없이_들어간다(self):
        r = self.post(self.payload(
            object_key="derived/thumb.jpg",
            derived={"kind": "thumbnail", "source_object_id": self.source.pk}))
        self.assertEqual(r.status_code, 200)
        image = Image.objects.get(object_key="derived/thumb.jpg")
        self.assertIsNone(image.ai_result_id)
        self.assertIsNone(image.lesion_id)

    def test_derived_블록이_없으면_400(self):
        payload = self.payload()
        del payload["derived"]
        r = self.post(payload)
        self.assertEqual(r.status_code, 400)
        self.assertIn("derived", r.json()["error"]["details"]["missing"])

    def test_안_정해진_kind_는_422(self):
        with self.assertLogs("core.api.tickets", level="WARNING"):
            r = self.post(self.payload(derived=self.derived(kind="mask")))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "UNSUPPORTED_PURPOSE")

    def test_병변_메시가_image_행이_된다(self):
        r = self.post(self.payload(
            object_key="study/1/mesh/lesion-0.json",
            content_type="application/json",
            derived=self.derived(kind="mesh_lesion")))
        self.assertEqual(r.status_code, 200)
        image = Image.objects.get(object_key="study/1/mesh/lesion-0.json")
        self.assertEqual(image.kind, "mesh_lesion")
        self.assertEqual(image.lesion_id, self.lesion.pk)
        self.assertEqual(image.content_type, "application/json")

    def test_검사_메시는_lesion_이_빈_채로_들어간다(self):
        r = self.post(self.payload(
            object_key="study/1/mesh/breast_mesh.json",
            derived={"kind": "mesh_breast",
                     "source_object_id": self.source.pk,
                     "ai_result_id": self.ai_result.pk}))
        self.assertEqual(r.status_code, 200)
        image = Image.objects.get(object_key="study/1/mesh/breast_mesh.json")
        self.assertIsNone(image.lesion_id)
        self.assertEqual(image.ai_result_id, self.ai_result.pk)

    def test_필수_FK_가_비면_400(self):
        r = self.post(self.payload(derived=self.derived(ai_result_id=None)))
        self.assertEqual(r.status_code, 400)

    def test_남의_검사_원본이면_403(self):
        r = self.post(self.payload(
            derived=self.derived(source_object_id=self.other_source.pk),
            scope_id=str(self.study.pk)))
        self.assertEqual(r.status_code, 403)

    def test_재시도해도_행이_하나다(self):
        for _ in range(3):
            self.assertEqual(self.post(self.payload()).status_code, 200)
        self.assertEqual(Image.objects.filter(
            object_key="derived/ov1.png").count(), 1)

    def test_버킷이_다르면_같은_키를_쓸_수_있다(self):
        # image.object_key 만 UNIQUE 이던 것을 (bucket, object_key) 로 바꿨다
        self.post(self.payload())
        Image.objects.create(kind="thumbnail", source_object=self.source,
                             bucket="empatho-original",
                             object_key="derived/ov1.png")
        self.assertEqual(Image.objects.filter(
            object_key="derived/ov1.png").count(), 2)
