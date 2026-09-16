# -*- coding: utf-8 -*-
"""Go → Django 내부 콜백 (명세 21장).

Go 를 띄우지 않고 서명을 직접 만들어 요청을 흉내낸다. 서명 계산은
services/gosvc/tools/fake_django.py 의 sign() 과 대조한다 — 그쪽이 Go 의
callback.Sign 을 그대로 옮긴 참조 구현이다.
"""

import hashlib
import hmac
import json
import time

from django.test import TestCase, override_settings
from django.utils import timezone

from core.api.internal import sign
from core.models import (Account, ExamOrder, Notification, Patient, Report,
                         Specimen, Staff, StorageObject, Study, Lesion)

SECRET = "test-callback-secret-0123456789abcdef"


def go_sign(secret: bytes, ts: str, body: bytes) -> str:
    """fake_django.py 의 sign() 을 그대로 옮긴 것. 우리 구현과 대조용이다."""
    m = hmac.new(secret, digestmod=hashlib.sha256)
    m.update(ts.encode())
    m.update(b".")
    m.update(body)
    return m.hexdigest()


class SignCompatibilityTests(TestCase):
    def test_Go_참조구현과_같은_서명을_낸다(self):
        for ts, body in [("1757400000", b'{"a":1}'), ("0", b""),
                         ("1757400000", '{"한글":"본문"}'.encode())]:
            self.assertEqual(sign(SECRET.encode(), ts, body),
                             go_sign(SECRET.encode(), ts, body))

    def test_구분자가_있어_경계가_안_섞인다(self):
        # 점이 없으면 (ts="1", body="23") 과 (ts="12", body="3") 이 같아진다.
        self.assertNotEqual(sign(SECRET.encode(), "1", b"23"),
                            sign(SECRET.encode(), "12", b"3"))


@override_settings(CALLBACK_SECRET=SECRET, CALLBACK_TIMESTAMP_TOLERANCE_SEC=300)
class CallbackTestCase(TestCase):
    """서명을 붙여 POST 하는 공통 도구."""

    def post(self, path, payload, secret=SECRET, ts=None, idem="test-idem",
             signature=None):
        body = json.dumps(payload).encode()
        ts = ts if ts is not None else str(int(time.time()))
        headers = {
            "X-Timestamp": ts,
            "X-Signature": signature or sign(secret.encode(), ts, body),
            "Idempotency-Key": idem,
        }
        return self.client.post("/internal/v1/" + path, data=body,
                                content_type="application/json", headers=headers)


class SignatureVerificationTests(CallbackTestCase):
    PATH = "storage-objects"

    def test_서명이_없으면_401(self):
        r = self.client.post("/internal/v1/" + self.PATH, data=b"{}",
                             content_type="application/json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "UNAUTHENTICATED")

    def test_비밀값이_다르면_401(self):
        r = self.post(self.PATH, {"a": 1}, secret="wrong-secret-value")
        self.assertEqual(r.status_code, 401)

    def test_본문을_한_글자_바꾸면_401(self):
        body = json.dumps({"a": 1}).encode()
        ts = str(int(time.time()))
        r = self.client.post(
            "/internal/v1/" + self.PATH, data=b'{"a": 2}',
            content_type="application/json",
            headers={"X-Timestamp": ts,
                     "X-Signature": sign(SECRET.encode(), ts, body)})
        self.assertEqual(r.status_code, 401)

    def test_시간이_5분을_넘으면_401(self):
        old = str(int(time.time()) - 301)
        self.assertEqual(self.post(self.PATH, {"a": 1}, ts=old).status_code, 401)

    def test_미래_시각도_5분을_넘으면_401(self):
        future = str(int(time.time()) + 301)
        self.assertEqual(self.post(self.PATH, {"a": 1}, ts=future).status_code, 401)

    def test_5분_안이면_서명은_통과한다(self):
        # 서명은 통과하고 본문 검증에서 걸린다 — 401 이 아니다.
        r = self.post(self.PATH, {"a": 1}, ts=str(int(time.time()) - 299))
        self.assertEqual(r.status_code, 400)

    def test_시각_형식이_이상하면_401(self):
        self.assertEqual(self.post(self.PATH, {"a": 1}, ts="어제").status_code, 401)

    @override_settings(CALLBACK_SECRET="")
    def test_비밀값이_비어_있으면_아무것도_안_받는다(self):
        with self.assertLogs("core.api.internal", level="ERROR"):
            r = self.post(self.PATH, {"a": 1}, secret="")
        self.assertEqual(r.status_code, 401)

    def test_JSON_이_아니면_400(self):
        ts = str(int(time.time()))
        body = b"not json"
        r = self.client.post(
            "/internal/v1/" + self.PATH, data=body,
            content_type="application/json",
            headers={"X-Timestamp": ts,
                     "X-Signature": sign(SECRET.encode(), ts, body)})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "VALIDATION_ERROR")


class Fixtures(CallbackTestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        account = Account.objects.create(login_id="rad1", role="radiology",
                                         is_active=True)
        cls.staff = Staff.objects.create(account=account, full_name="김판독")
        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mri",
            exam_purpose="diagnostic", ordered_by=cls.staff)
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mri")
        cls.lesion = Lesion.objects.create(study=cls.study, patient=cls.patient)
        cls.specimen = Specimen.objects.create(
            patient=cls.patient, lesion=cls.lesion, accession_status="bound")
        cls.report = Report.objects.create(patient=cls.patient, study=cls.study,
                                           report_type="stage")

    def obj_payload(self, **kw):
        base = {"bucket": "empatho-original", "object_key": "mri/0001.dcm",
                "checksum_sha256": "a" * 64, "byte_size": 1024,
                "content_type": "application/dicom", "storage_class": "STANDARD",
                "purpose": "dicom_upload", "scope_id": str(self.study.pk),
                "patient_id": str(self.patient.pk)}
        base.update(kw)
        return base


class StorageObjectCallbackTests(Fixtures):
    """I-1 — 파일 저장 뒤."""

    def test_DICOM_은_study_에_매달린다(self):
        r = self.post("storage-objects", self.obj_payload())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["data"]["created"])
        obj = StorageObject.objects.get(object_key="mri/0001.dcm")
        self.assertEqual(obj.study_id, self.study.pk)
        self.assertIsNone(obj.specimen_id)
        self.assertIsNone(obj.report_id)
        self.assertEqual(obj.byte_size, 1024)

    def test_WSI_는_specimen_에_매달린다(self):
        r = self.post("storage-objects", self.obj_payload(
            purpose="wsi_upload", scope_id=str(self.specimen.pk),
            object_key="path/slide.svs"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(StorageObject.objects.get(
            object_key="path/slide.svs").specimen_id, self.specimen.pk)

    def test_리포트_PDF_는_report_에_매달린다(self):
        r = self.post("storage-objects", self.obj_payload(
            purpose="report_pdf", scope_id=str(self.report.pk),
            object_key="report/1.pdf"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(StorageObject.objects.get(
            object_key="report/1.pdf").report_id, self.report.pk)

    def test_자리가_없는_purpose_는_422_로_거절하고_남긴다(self):
        # 처방 표가 MVP 밖이라 파일이 갈 곳이 없다.
        # derived_upload 는 image 로 가므로 여기 없다 — test_derived.py 참고.
        purpose = "prescription_pdf"
        with self.assertLogs("core.api.internal", level="WARNING") as caught:
            r = self.post("storage-objects", self.obj_payload(purpose=purpose))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "UNSUPPORTED_PURPOSE")
        self.assertIn(purpose, caught.output[0])
        self.assertEqual(StorageObject.objects.count(), 0)

    def test_대상이_없으면_422(self):
        r = self.post("storage-objects", self.obj_payload(scope_id="99999"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "TARGET_NOT_FOUND")

    def test_필수값이_없으면_400(self):
        payload = self.obj_payload()
        del payload["object_key"]
        r = self.post("storage-objects", payload)
        self.assertEqual(r.status_code, 400)
        self.assertIn("object_key", r.json()["error"]["details"]["missing"])

    def test_재시도해도_행이_하나다(self):
        for _ in range(3):
            r = self.post("storage-objects", self.obj_payload())
            self.assertEqual(r.status_code, 200)
        self.assertEqual(StorageObject.objects.count(), 1)
        self.assertFalse(r.json()["data"]["created"])   # 두 번째부터는 False

    def test_한_시리즈의_파일_176개가_다_들어간다(self):
        for n in range(176):
            r = self.post("storage-objects",
                          self.obj_payload(object_key="mri/%04d.dcm" % n))
            self.assertEqual(r.status_code, 200, n)
        self.assertEqual(StorageObject.objects.count(), 176)


class DicomInstanceCallbackTests(Fixtures):
    """I-2 — DICOM 헤더 읽은 뒤."""

    def setUp(self):
        self.post("storage-objects", self.obj_payload())
        self.obj = StorageObject.objects.get(object_key="mri/0001.dcm")

    def dicom_payload(self, **kw):
        base = {"bucket": "empatho-original", "object_key": "mri/0001.dcm",
                "study_instance_uid": "1.2.3.STUDY",
                "series_instance_uid": "1.2.3.SERIES",
                "sop_instance_uid": "1.2.3.SOP.1",
                "modality": "MR", "laterality": "R", "view_position": "CC",
                "rows": 512, "columns": 384, "pixel_spacing": [0.83, 0.83],
                "manufacturer_model_name": "SIGNA Premier",
                "orthanc_study_id": "orthanc-study-1"}
        base.update(kw)
        return base

    def test_헤더_값이_채워진다(self):
        r = self.post("dicom-instances", self.dicom_payload())
        self.assertEqual(r.status_code, 200)
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.series_uid, "1.2.3.SERIES")
        self.assertEqual(self.obj.sop_instance_uid, "1.2.3.SOP.1")
        self.assertEqual(self.obj.laterality, "right")      # L/R 을 옮긴다
        self.assertEqual(self.obj.view_position, "CC")
        self.assertEqual(self.obj.width_px, 384)            # columns
        self.assertEqual(self.obj.height_px, 512)           # rows
        self.assertEqual(float(self.obj.pixel_spacing_mm), 0.83)

    def test_Orthanc_에_저장되면_주소가_Orthanc_로_옮겨진다(self) :
        self.post("dicom-instances", self.dicom_payload(orthanc_series_id="orthanc-series-1"))
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.orthanc_series_id, "orthanc-series-1")
        self.assertIsNone(self.obj.object_key)
        self.assertIsNone(self.obj.bucket)
    
    def test_Orthanc_ID_가_없으면_Garage_키를_남긴다(self):
        # 전송 실패 
        self.post("dicom-instances", self.dicom_payload(orthanc_series_id=None))
        self.obj.refresh_from_db()
        self.assertEqual(self.obj.object_key, "mri/0001.dcm")

    def test_study_에_UID_와_Orthanc_ID_가_채워진다(self):
        self.post("dicom-instances", self.dicom_payload())
        self.study.refresh_from_db()
        self.assertEqual(self.study.study_uid, "1.2.3.STUDY")
        self.assertEqual(self.study.orthanc_study_id, "orthanc-study-1")
        self.assertEqual(self.study.device_name, "SIGNA Premier")

    def test_MRI_기하가_다_있으면_has_geometry_가_참(self):
        self.post("dicom-instances", self.dicom_payload(
            image_position_patient=[0.0, 0.0, 1.0],
            image_orientation_patient=[1.0, 0, 0, 0, 1.0, 0],
            slice_thickness=1.2))
        self.obj.refresh_from_db()
        self.assertTrue(self.obj.has_geometry)

    def test_기하가_모자라면_거짓(self):
        # 맘모는 낱장 2D 라 위치·방향이 없다. 오류가 아니다.
        self.post("dicom-instances", self.dicom_payload())
        self.obj.refresh_from_db()
        self.assertFalse(self.obj.has_geometry)

    def test_두께만_있고_방향이_없으면_거짓(self):
        self.post("dicom-instances", self.dicom_payload(slice_thickness=1.2))
        self.obj.refresh_from_db()
        self.assertFalse(self.obj.has_geometry)

    def test_화소_간격이_없으면_비운다(self):
        with self.assertLogs("core.api.internal", level="INFO"):
            self.post("dicom-instances", self.dicom_payload(pixel_spacing=None))
        self.obj.refresh_from_db()
        self.assertIsNone(self.obj.pixel_spacing_mm)

    def test_I1_이_먼저_안_오면_422(self):
        with self.assertLogs("core.api.internal", level="WARNING"):
            r = self.post("dicom-instances",
                          self.dicom_payload(object_key="mri/없는파일.dcm"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "TARGET_NOT_FOUND")

    def test_재시도해도_행이_안_늘고_값이_같다(self):
        for _ in range(3):
            self.assertEqual(
                self.post("dicom-instances", self.dicom_payload()).status_code, 200)
        self.assertEqual(StorageObject.objects.count(), 1)


class NotificationDeliveryCallbackTests(Fixtures):
    """I-3 — 알림 보낸 뒤."""

    def setUp(self):
        self.note = Notification.objects.create(
            patient=self.patient, notification_type="report_ready",
            message="검사 리포트를 열람하실 수 있습니다.")

    def payload(self, status="delivered", **kw):
        base = {"notification_id": str(self.note.pk), "user_id": "12",
                "channel": "sse", "status": status,
                "at": timezone.now().isoformat()}
        base.update(kw)
        return base

    def test_delivered_는_sent_at_에_찍힌다(self):
        r = self.post("notifications/delivery", self.payload())
        self.assertEqual(r.status_code, 200)
        self.note.refresh_from_db()
        self.assertIsNotNone(self.note.sent_at)
        self.assertIsNone(self.note.acknowledged_at)
        self.assertEqual(self.note.channel, "sse")

    def test_read_는_acknowledged_at_에_찍힌다(self):
        self.post("notifications/delivery", self.payload())
        self.post("notifications/delivery", self.payload(status="read"))
        self.note.refresh_from_db()
        # 서로 다른 사건이라 앞의 것을 덮지 않는다
        self.assertIsNotNone(self.note.sent_at)
        self.assertIsNotNone(self.note.acknowledged_at)

    def test_구독자가_없었던_것은_200_이지만_안_찍는다(self):
        with self.assertLogs("core.api.internal", level="INFO"):
            r = self.post("notifications/delivery",
                          self.payload(status="no_subscriber"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["data"]["recorded"])
        self.note.refresh_from_db()
        self.assertIsNone(self.note.sent_at)

    def test_없는_알림이면_422(self):
        r = self.post("notifications/delivery",
                      self.payload(notification_id="99999"))
        self.assertEqual(r.status_code, 422)

    def test_시각이_RFC3339_가_아니면_400(self):
        r = self.post("notifications/delivery", self.payload(at="어제"))
        self.assertEqual(r.status_code, 400)


class ReportNarrativeCallbackTests(Fixtures):
    """I-4 — 서술 생성 뒤."""

    def payload(self, **kw):
        base = {"narrative_text": "우측 유방 CC 상외측에 군집성 석회가 관찰됩니다.",
                "evidence_links": ["MG-01", "MG-02"],
                "dropped_sentence_log": [{"sentence": "버린 문장", "reason": "근거 없음"}],
                "notes": [{"id": "MG-N02", "text": "표식 크기는 병변 크기가 아닙니다."}],
                "prompt_version": "mammo-2026-09-05.a",
                "fallback": False}
        base.update(kw)
        return base

    def path(self):
        return "reports/%d/narrative" % self.report.pk

    def test_서술이_채워진다(self):
        r = self.post(self.path(), self.payload())
        self.assertEqual(r.status_code, 200)
        self.report.refresh_from_db()
        self.assertIn("군집성 석회", self.report.narrative_text)
        self.assertEqual(self.report.evidence_links, ["MG-01", "MG-02"])
        self.assertEqual(self.report.prompt_version, "mammo-2026-09-05.a")
        self.assertFalse(self.report.fallback)

    def test_버린_문장이_dropped_sentences_로_들어간다(self):
        # Go 는 dropped_sentence_log 로 보내고 v10 칸 이름은 dropped_sentences 다
        self.post(self.path(), self.payload())
        self.report.refresh_from_db()
        self.assertEqual(self.report.dropped_sentences[0]["reason"], "근거 없음")

    def test_안내_문구가_notes_로_들어간다(self):
        self.post(self.path(), self.payload())
        self.report.refresh_from_db()
        self.assertEqual(self.report.notes[0]["id"], "MG-N02")

    def test_fallback_사유는_content_json_으로_간다(self):
        # v10 의 fallback 은 boolean 이라 사유를 담을 칸이 없다
        self.post(self.path(), self.payload(
            fallback=True, fallback_reason="숫자 검사에 걸림"))
        self.report.refresh_from_db()
        self.assertTrue(self.report.fallback)
        self.assertEqual(self.report.content_json["fallback_reason"], "숫자 검사에 걸림")

    def test_기존_content_json_을_지우지_않는다(self):
        Report.objects.filter(pk=self.report.pk).update(
            content_json={"birads": "4c"})
        self.post(self.path(), self.payload(
            fallback=True, fallback_reason="근거 없음"))
        self.report.refresh_from_db()
        self.assertEqual(self.report.content_json["birads"], "4c")
        self.assertEqual(self.report.content_json["fallback_reason"], "근거 없음")

    def test_fallback_이_안_오면_거짓으로_둔다(self):
        payload = self.payload()
        del payload["fallback"]
        self.post(self.path(), payload)
        self.report.refresh_from_db()
        self.assertFalse(self.report.fallback)

    def test_없는_리포트면_422(self):
        r = self.post("reports/99999/narrative", self.payload())
        self.assertEqual(r.status_code, 422)

    def test_재시도해도_결과가_같다(self):
        for _ in range(3):
            self.assertEqual(self.post(self.path(), self.payload()).status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(len(self.report.notes), 1)


class ExposureTests(CallbackTestCase):
    def test_Swagger_에_안_실린다(self):
        from django.test import Client

        schema = Client().get("/api/schema/").content.decode()
        self.assertNotIn("/internal/", schema)

    def test_JWT_없이도_서명만_맞으면_통과한다(self):
        # 상대가 사람이 아니라 Go 다. 인증·권한 클래스를 끈 것이 의도대로인지.
        r = self.post("storage-objects", {"bucket": "b"})
        self.assertNotEqual(r.status_code, 401)
