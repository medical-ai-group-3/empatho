"""Go → Django 내부 콜백 (명세 21장).

Go 는 Postgres 에 직접 쓰지 않는다. 파일을 저장하거나 알림을 보내거나 소견을
받아 온 결과를 전부 이 통로로 넘긴다.

    POST /internal/v1/storage-objects           I-1  파일 저장 뒤
    POST /internal/v1/dicom-instances           I-2  DICOM 헤더 읽은 뒤
    POST /internal/v1/notifications/delivery    I-3  알림 보낸 뒤
    POST /internal/v1/reports/{id}/narrative    I-4  서술 생성 뒤

계약은 services/gosvc/internal/callback/callback.go 가 갖고 있다. 이미 배포돼
호출 중이라 그쪽이 기준이고 여기가 맞춘다.

    서명   HMAC-SHA256(CALLBACK_SECRET, X-Timestamp + "." + body) 를 hex 로.
           ±5 분을 벗어나면 거절한다 — Go 가 nonce 를 안 보내서 시간 창이
           재전송을 막는 유일한 수단이다.
    멱등   재시도가 행을 두 번 만들지 않아야 한다. 자연키로 잡는다 —
           I-1 은 (bucket, object_key), 나머지 셋은 기존 행 갱신이다.
           멱등 전용 표를 두지 않는다.
    상태   4xx 면 Go 가 재시도를 포기한다. 다시 보내도 같은 것만 4xx 로 준다.
           DB 오류처럼 다음에 될 수도 있는 것은 5xx 로 둬서 재시도를 받는다.

밖에서는 닿지 않는다. compose 에서 web 은 127.0.0.1:8000 이고,
conf/nginx.conf 가 location /internal/ 을 404 로 잘라낸다.
"""

import hmac
import json
import logging
import time
from hashlib import sha256

from django.conf import settings
from django.db import transaction
from django.urls import path
from django.utils.dateparse import parse_datetime
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Notification, Report, Specimen, StorageObject, Study
from .errors import ApiError

logger = logging.getLogger(__name__)

# 티켓 purpose → storage_object 의 어느 주인에 매다는가.
# 여기 없는 purpose 는 담을 칸이 없다는 뜻이라 422 로 거절한다.
PURPOSE_OWNER = {
    "dicom_upload": ("study", Study),
    "wsi_upload": ("specimen", Specimen),
    "report_pdf": ("report", Report),
    # derived_upload · prescription_pdf 는 자리가 없다. 정해지면 여기 추가.
}

# DICOM 값 → v10 choices
LATERALITY = {"L": "left", "R": "right"}
NOTIFICATION_STATUS_FIELD = {"delivered": "sent_at", "read": "acknowledged_at"}


def sign(secret, timestamp, body):
    """Go 의 callback.Sign 과 같아야 한다.

    구분자 없이 이으면 (ts="1", body="23") 과 (ts="12", body="3") 이 같은
    서명을 낸다. Go 가 점을 넣은 이유다.
    """
    mac = hmac.new(secret, digestmod=sha256)
    mac.update(timestamp.encode())
    mac.update(b".")
    mac.update(body)
    return mac.hexdigest()


class InternalCallbackView(APIView):
    """서명을 검증하고 통과한 것만 처리한다.

    JWT 인증과 권한은 끈다 — 상대가 사람이 아니라 Go 다. Swagger 에서도 뺀다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    schema = None                       # drf-spectacular 가 건너뛴다

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.payload = self._verified_payload(request)

    def _verified_payload(self, request):
        secret = (settings.CALLBACK_SECRET or "").encode()
        if not secret:
            # 빈 비밀값을 허용하면 아무 서명이나 통과하는 게 아니라 아예
            # 검증이 무의미해진다. 설정이 빠진 것을 통과로 취급하지 않는다.
            logger.error("CALLBACK_SECRET 이 비어 있다 — 콜백을 받지 않는다")
            raise ApiError("UNAUTHENTICATED", "콜백 설정이 되어 있지 않습니다.")

        timestamp = request.headers.get("X-Timestamp", "")
        given = request.headers.get("X-Signature", "")
        if not timestamp or not given:
            raise ApiError("UNAUTHENTICATED", "서명 헤더가 없습니다.")

        try:
            skew = abs(time.time() - int(timestamp))
        except ValueError:
            raise ApiError("UNAUTHENTICATED", "X-Timestamp 형식이 올바르지 않습니다.") from None
        if skew > settings.CALLBACK_TIMESTAMP_TOLERANCE_SEC:
            raise ApiError("UNAUTHENTICATED", "X-Timestamp 가 허용 시간차를 벗어났습니다.")

        # 서명한 바이트 그대로 읽고 그대로 파싱한다 — 검증한 것과 처리하는 것이
        # 같은 바이트여야 한다.
        body = request.body
        if not hmac.compare_digest(sign(secret, timestamp, body), given):
            raise ApiError("UNAUTHENTICATED", "서명이 맞지 않습니다.")

        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "본문이 JSON 이 아닙니다.") from None
        if not isinstance(payload, dict):
            raise ApiError("VALIDATION_ERROR", "본문이 객체가 아닙니다.")
        return payload

    @property
    def idempotency_key(self):
        return self.request.headers.get("Idempotency-Key", "")

    def require(self, *names):
        missing = [n for n in names if not self.payload.get(n)]
        if missing:
            raise ApiError("VALIDATION_ERROR", "필수 값이 없습니다.",
                           details={"missing": missing})
        return [self.payload[n] for n in names]

    def target(self, model, pk, what):
        try:
            return model.objects.get(pk=int(pk))
        except (model.DoesNotExist, TypeError, ValueError):
            raise ApiError("CALLBACK_TARGET_NOT_FOUND",
                           details={"target": what, "id": pk}) from None


# ── I-1  파일 저장 ───────────────────────────────────────────────────────
class StorageObjectCallback(InternalCallbackView):
    """Garage 에 커밋된 파일 하나를 등록한다.

    멱등키는 (bucket, object_key) 다 — 모든 행에 있고 이 시점에 확정된다.
    Go 의 멱등키 obj:<object_key> 와 같은 자리다.
    """

    @extend_schema(exclude=True)
    def post(self, request):
        bucket, object_key, purpose = self.require("bucket", "object_key", "purpose")

        owner = PURPOSE_OWNER.get(purpose)
        if owner is None:
            # 담을 칸이 없다. 재시도해도 같으므로 4xx 로 돌려보내고 남긴다 —
            # 조용히 200 을 주면 파일이 어디에도 안 붙은 채 잊힌다.
            logger.warning("[I-1] 받을 수 없는 purpose=%s key=%s — 파일이 매달릴 곳이 없다",
                           purpose, object_key)
            raise ApiError("CALLBACK_UNSUPPORTED_PURPOSE", details={"purpose": purpose})

        field, model = owner
        target = self.target(model, self.payload.get("scope_id"), field)

        obj, created = StorageObject.objects.get_or_create(
            bucket=bucket, object_key=object_key,
            defaults={
                field: target,
                "checksum_sha256": self.payload.get("checksum_sha256") or None,
                "byte_size": self.payload.get("byte_size") or None,
                "content_type": self.payload.get("content_type") or None,
            },
        )
        # storage_class 는 v10 에 칸이 없다. 버린다.
        logger.info("[I-1] %s key=%s %s=%s idem=%s",
                    "등록" if created else "이미 있음", object_key, field,
                    target.pk, self.idempotency_key)
        return Response({"storage_object_id": obj.pk, "created": created})


# ── I-2  DICOM 메타 ──────────────────────────────────────────────────────
class DicomInstanceCallback(InternalCallbackView):
    """I-1 로 등록한 그 파일에 DICOM 헤더에서 읽은 값을 채운다.

    명세 21 장 「I-1 이 성공해야 I-2 가 유효하다」. 대상 행이 없으면 순서가
    깨진 것이라 422 로 돌려보낸다.
    """

    @extend_schema(exclude=True)
    def post(self, request):
        bucket, object_key = self.require("bucket", "object_key")
        try:
            obj = StorageObject.objects.get(bucket=bucket, object_key=object_key)
        except StorageObject.DoesNotExist:
            logger.warning("[I-2] I-1 이 먼저 오지 않았다 key=%s", object_key)
            raise ApiError("CALLBACK_TARGET_NOT_FOUND",
                           details={"target": "storage_object",
                                    "object_key": object_key}) from None

        p = self.payload
        obj.series_uid = p.get("series_instance_uid") or None
        obj.sop_instance_uid = p.get("sop_instance_uid") or None
        obj.laterality = LATERALITY.get(p.get("laterality"), p.get("laterality")) or None
        obj.view_position = p.get("view_position") or None
        obj.width_px = p.get("columns") or None
        obj.height_px = p.get("rows") or None
        obj.pixel_spacing_mm = self._spacing(p.get("pixel_spacing"), object_key)
        obj.has_geometry = self._has_geometry(p)

        # ⚠ orthanc_series_id 는 채우지 못한다. storage_object_address_ck 가
        #   「Orthanc 아니면 Garage, 정확히 하나」인데 DICOM 은 Garage 와
        #   Orthanc 양쪽에 있다. 제약을 고칠지 팀 확인 대상이다.
        if p.get("orthanc_series_id"):
            logger.warning("[I-2] orthanc_series_id 를 버린다 key=%s — "
                           "address CHECK 이 Garage 와 동시 보유를 막는다", object_key)

        with transaction.atomic():
            obj.save()
            self._fill_study(obj, p)

        logger.info("[I-2] 갱신 key=%s sop=%s idem=%s",
                    object_key, obj.sop_instance_uid, self.idempotency_key)
        return Response({"storage_object_id": obj.pk})

    @staticmethod
    def _spacing(pixel_spacing, object_key):
        """DICOM 은 [행 간격, 열 간격] 두 값인데 v10 은 한 칸이다."""
        if not pixel_spacing:
            # 미세석회 판독이 여기 걸린다 — mm/px 를 모르면 크기를 못 낸다.
            logger.info("[I-2] 화소 간격 없음 key=%s — 크기 미산출", object_key)
            return None
        first = pixel_spacing[0]
        if len(pixel_spacing) > 1 and pixel_spacing[0] != pixel_spacing[1]:
            logger.info("[I-2] 화소 간격이 축마다 다르다 key=%s %s — 첫 값만 쓴다",
                        object_key, pixel_spacing)
        return first

    @staticmethod
    def _has_geometry(p):
        """3D 재구성이 되는가. 위치 · 방향 · 두께가 다 있어야 한다."""
        return bool(p.get("image_position_patient")
                    and p.get("image_orientation_patient")
                    and (p.get("slice_thickness") or p.get("spacing_between_slices")))

    @staticmethod
    def _fill_study(obj, p):
        """study 쪽에 DICOM UID 와 Orthanc 식별자를 채운다.

        시리즈 단위 Orthanc ID 는 못 넣지만 study 단위는 제약이 없어서
        뷰어가 검사를 열 길은 남는다.
        """
        study = obj.study
        if study is None:
            return
        changed = []
        if not study.study_uid and p.get("study_instance_uid"):
            study.study_uid = p["study_instance_uid"]
            changed.append("study_uid")
        if not study.orthanc_study_id and p.get("orthanc_study_id"):
            study.orthanc_study_id = p["orthanc_study_id"]
            changed.append("orthanc_study_id")
        if not study.device_name and p.get("manufacturer_model_name"):
            study.device_name = p["manufacturer_model_name"]
            changed.append("device_name")
        if changed:
            study.save(update_fields=changed + ["updated_at"])


# ── I-3  알림 발송 결과 ──────────────────────────────────────────────────
class NotificationDeliveryCallback(InternalCallbackView):
    """보냈는지 · 읽었는지를 알림 행에 찍는다.

    delivered 와 read 는 다른 사건이라 서로 다른 칸에 들어간다. 그래서 같은
    행에 두 번 와도 덮어쓰지 않는다.
    """

    @extend_schema(exclude=True)
    def post(self, request):
        notification_id, status = self.require("notification_id", "status")
        note = self.target(Notification, notification_id, "notification")

        field = NOTIFICATION_STATUS_FIELD.get(status)
        if field is None:
            # no_subscriber — 접속한 화면이 없었다. 실패가 아니라 사실이라
            # 200 으로 받고 남기기만 한다. 화면이 나중에 목록을 받아 간다.
            logger.info("[I-3] status=%s notification=%s — 기록할 칸이 없다",
                        status, notification_id)
            return Response({"notification_id": note.pk, "recorded": False})

        at = parse_datetime(self.payload.get("at") or "")
        if at is None:
            raise ApiError("VALIDATION_ERROR", "at 이 RFC3339 가 아닙니다.",
                           details={"at": self.payload.get("at")})

        changed = [field]
        setattr(note, field, at)
        if self.payload.get("channel"):
            note.channel = self.payload["channel"]      # Go 는 sse 를 보낸다
            changed.append("channel")
        note.save(update_fields=changed + ["updated_at"])

        logger.info("[I-3] %s=%s notification=%s idem=%s",
                    field, at, note.pk, self.idempotency_key)
        return Response({"notification_id": note.pk, "recorded": True})


# ── I-4  리포트 서술 ─────────────────────────────────────────────────────
class ReportNarrativeCallback(InternalCallbackView):
    """리포트 서버가 만든 소견문을 받아 리포트에 채운다.

    LLM 이 죽어도 리포트는 content_json 만으로 발급된다 — 이 콜백은 거기에
    문장을 얹는 것이다.
    """

    @extend_schema(exclude=True)
    def post(self, request, report_id):
        report = self.target(Report, report_id, "report")
        p = self.payload

        report.narrative_text = p.get("narrative_text") or None
        report.evidence_links = p.get("evidence_links")      # Go 는 문자열 배열
        report.dropped_sentences = p.get("dropped_sentence_log")
        report.notes = p.get("notes")
        report.prompt_version = p.get("prompt_version") or None
        report.fallback = bool(p.get("fallback"))

        # v10 에 사유 칸이 없다. 스키마를 늘리지 않고 본문에 넣는다.
        reason = p.get("fallback_reason")
        if reason:
            content = dict(report.content_json or {})
            content["fallback_reason"] = reason
            report.content_json = content

        report.save()
        logger.info("[I-4] 서술 채움 report=%s fallback=%s idem=%s",
                    report.pk, report.fallback, self.idempotency_key)
        return Response({"report_id": report.pk})


urlpatterns = [
    path("storage-objects", StorageObjectCallback.as_view()),
    path("dicom-instances", DicomInstanceCallback.as_view()),
    path("notifications/delivery", NotificationDeliveryCallback.as_view()),
    path("reports/<int:report_id>/narrative", ReportNarrativeCallback.as_view()),
]
