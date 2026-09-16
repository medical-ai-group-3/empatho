# -*- coding: utf-8 -*-
"""값 목록 넷 (0013).

컬럼이 있는지가 아니라 **제약이 실제로 막는지**를 본다. choices 는 폼 검증이라
.save() 로 들어오는 값은 아무거나 통과한다 — 콜백과 Celery 는 폼을 안 거치므로
DB 가 마지막 자리다.
"""

from django.db import IntegrityError, transaction
from django.test import TestCase

from core.api.tickets import DERIVED_REQUIRED
from core.models import (REPORT_SOCKET_ID, Account, AiModel, AiResult,
                         ExamOrder, Image, Notification, Patient, Report,
                         Staff, StorageObject, Study)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.patient = Patient.objects.create(patient_number="E_1029304")
        cls.staff = Staff.objects.create(
            account=Account.objects.create(login_id="rad1", role="radiology",
                                           is_active=True),
            full_name="김판독")
        order = ExamOrder.objects.create(
            patient=cls.patient, order_status="ordered", modality="mammo",
            exam_purpose="screening", ordered_by=cls.staff)
        cls.study = Study.objects.create(patient=cls.patient, exam_order=order,
                                         modality="mammo")
        cls.source = StorageObject.objects.create(
            study=cls.study, bucket="empatho-original",
            object_key="study/1/rcc.dcm")

    def blocked(self):
        return self.assertRaises(IntegrityError)


class NotificationChannelTests(Base):
    """Go notify 허브가 I-3 으로 sse 를 보낸다."""

    def make(self, **kw):
        base = {"patient": self.patient, "notification_type": "report_ready",
                "message": "결과가 나왔습니다."}
        base.update(kw)
        return Notification.objects.create(**base)

    def test_sse_가_들어간다(self):
        # cmd/notify/main.go 가 Channel: "sse" 로 보낸다
        self.assertEqual(self.make(channel="sse").channel, "sse")

    def test_기존_셋도_그대로다(self):
        for value in ("app", "sms", "call_queue"):
            self.assertEqual(self.make(channel=value).channel, value)

    def test_모르는_값은_DB_가_막는다(self):
        # 0013 전에는 CHECK 이 없어 아무 문자열이나 들어갔다
        with self.blocked(), transaction.atomic():
            self.make(channel="xxx")

    def test_비어_있어도_된다(self):
        self.assertIsNone(self.make().channel)


class ReportSocketTests(Base):
    """리포트를 낸 소켓. 실재하는 배치만 둔다."""

    def make(self, **kw):
        base = {"patient": self.patient, "study": self.study,
                "report_type": "final", "audience": "clinician"}
        base.update(kw)
        return Report.objects.create(**base)

    def test_초음파가_5_로_들어간다(self):
        # 재배치 4→5. tasks.py 의 SOCKET 이 us: "5" 다
        self.assertEqual(self.make(socket_id="5").socket_id, "5")

    def test_재배치_전_번호_4_는_막힌다(self):
        # 없는 소켓이 리포트 주인으로 들어가면 안 된다
        with self.blocked(), transaction.atomic():
            self.make(socket_id="4")

    def test_실재하는_다섯만_통과한다(self):
        self.assertEqual(REPORT_SOCKET_ID, ["1", "3", "4b", "5", "7"])
        for value in REPORT_SOCKET_ID:
            self.assertEqual(self.make(socket_id=value).socket_id, value)

    def test_요청_번호_쪽에는_4_가_남아_있다(self):
        # requested_socket_id 는 재배치 **전** 값이 들어오는 자리다
        result = AiResult.objects.create(patient=self.patient, study=self.study,
                                         requested_socket_id="4")
        self.assertEqual(result.requested_socket_id, "4")

    def test_모르는_소켓은_막힌다(self):
        with self.blocked(), transaction.atomic():
            self.make(socket_id="99")


class AbstainReasonTests(Base):
    """기권 사유. 100 자로는 모자랐다."""

    def test_101자가_들어간다(self):
        long = "가" * 101
        result = AiResult.objects.create(patient=self.patient, study=self.study,
                                         abstained=True, abstain_reason=long)
        result.refresh_from_db()
        self.assertEqual(len(result.abstain_reason), 101)

    def test_아주_긴_사유도_들어간다(self):
        # text 라 상한이 없다. 기권은 정상 종료라 기록이 남아야 한다
        long = "영상 품질이 낮아 판정할 수 없습니다. " * 100
        result = AiResult.objects.create(patient=self.patient, study=self.study,
                                         abstained=True, abstain_reason=long)
        result.refresh_from_db()
        self.assertEqual(result.abstain_reason, long)


class PreviewKindTests(Base):
    """판독 화면이 띄우는 원본 크기 그림."""

    def make(self, kind, key):
        return Image.objects.create(kind=kind, source_object=self.source,
                                    bucket="empatho-derived", object_key=key)

    def test_preview_가_들어간다(self):
        self.assertEqual(self.make("preview", "study/1/preview/0001.png").kind,
                         "preview")

    def test_thumbnail_과_다른_값이다(self):
        # thumbnail 은 목록용 작은 그림, preview 는 판독 화면용 원본 크기
        a = self.make("preview", "study/1/preview/0001.png")
        b = self.make("thumbnail", "study/1/thumb.png")
        self.assertNotEqual(a.kind, b.kind)

    def test_모르는_kind_는_막힌다(self):
        with self.blocked(), transaction.atomic():
            self.make("bigimage", "study/1/x.png")

    def test_티켓이_preview_를_받는다(self):
        # 원본을 변환한 것이라 ai_result_id 는 안 받는다
        self.assertEqual(DERIVED_REQUIRED["preview"], ("source_object_id",))
        self.assertNotIn("ai_result_id", DERIVED_REQUIRED["preview"])


class DetVersionTests(Base):
    """검출기 판. 분류기와 따로 올라가는 소켓이 있다."""

    def test_분류기와_따로_담긴다(self):
        model = AiModel.objects.create(socket_id="4b", socket_name="mammo",
                                       model_version="cls-2.1",
                                       det_version="det-1.4")
        model.refresh_from_db()
        self.assertEqual(model.model_version, "cls-2.1")
        self.assertEqual(model.det_version, "det-1.4")

    def test_비어_있어도_된다(self):
        model = AiModel.objects.create(socket_id="3", socket_name="mri")
        self.assertIsNone(model.det_version)
