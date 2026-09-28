"""병리과(pathology) view — 2026-09-14 화면명세 기준.

확정 사양서 §8-2: 병리 결과 정정 경로를 두지 않는다 — 확정 후 오류는
새 검체로 처리한다. POST /specimens/{id}/amend 는 만들지 않는다(예전
초안엔 있었으나 무효).
"""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

import logging

from django.db import transaction
from django.utils import timezone

from ..tasks import run_inference
from .. import models, serializers
from ..mixins import AuditMixin
from ..services import discordance
from ..serializers.pathology import MARKER_FIELDS
from core.api.permissions import MatrixPermission, CanFinalizePathologyRead
from core.api.errors import ApiError

logger = logging.getLogger(__name__)


def _get_specimen_for_write(request, pk):
    """draft · finalize 앞의 공통 가드(09-28).

    - 없는 검체는 404(전에는 .get() 이 DoesNotExist → 500 이었다)
    - 확정된 검체는 409 SPECIMEN_ALREADY_FINALIZED — 병리는 정정 경로가
      없다(확정 사양서 §8-2). 전에는 draft 가 확정 값을 조용히 덮었다
    - 누가 집은(assigned_to) 검체는 **집은 사람만** 쓴다 — 403 ROLE_FORBIDDEN.
      아직 아무도 안 집었으면 막지 않는다(종전 동작 유지)
    """
    specimen = (models.Specimen.objects.select_related("patient__primary_staff")
                .filter(pk=pk).first())
    if specimen is None:
        raise ApiError("NOT_FOUND", "검체를 찾을 수 없습니다.")
    if specimen.finalized_at is not None:
        raise ApiError("SPECIMEN_ALREADY_FINALIZED")
    staff = getattr(request.user, "staff", None)
    if specimen.assigned_to_id is not None and (
            staff is None or staff.pk != specimen.assigned_to_id):
        raise ApiError("ROLE_FORBIDDEN", "이 검체를 맡은 선생님만 판독할 수 있습니다.")
    return specimen


def _apply_markers(specimen, data):
    """조직형 · 등급 · 수용체 · Ki-67 — 보낸 칸만 덮는다(null 은 지우기)."""
    for field in MARKER_FIELDS:
        if field in data:
            setattr(specimen, field, data[field])


def _notify_finalized(specimen):
    """확정이 **커밋된 뒤** 주치의에게 한 번. 주치의가 없으면 건너뛴다.

    알림 종류는 새로 파지 않고 report_ready 를 쓴다. 가리키는 대상은
    ref_type="specimen", ref_id=specimen_id — 화면이 눌러서 검체로 간다
    (09-28 REF_TYPE 에 specimen 추가, 0028).
    """
    staff = specimen.patient.primary_staff
    if staff is None:
        return
    pii = getattr(specimen.patient, "pii", None)
    who = getattr(pii, "name", None) or specimen.patient.patient_number
    label = specimen.specimen_label or f"#{specimen.pk}"
    message = f"{who} 환자 검체 {label} 병리 결과가 확정되었습니다."

    def _send():
        from .. import notify
        try:
            notify.send(staff=staff, type="report_ready", message=message,
                        ref_type="specimen", ref_id=specimen.pk)
        except Exception:
            logger.exception("[pathology] 확정 알림 실패 specimen=%s", specimen.pk)

    transaction.on_commit(_send)


class SpecimenQueueView(generics.ListAPIView):
    """§1 GET /specimens?status=bound&assigned=none — 접수 대기 목록."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.SpecimenSerializer

    def get_queryset(self):
        qs = (models.Specimen.objects.select_related("patient__pii", "bound_by")
              .order_by("collected_at"))

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(accession_status=status_param)

        assigned_param = self.request.query_params.get("assigned")
        if assigned_param == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif assigned_param == "me":
            # 09-28 — GET /specimens 와 같은 규칙
            staff = getattr(self.request.user, "staff", None)
            qs = qs.filter(assigned_to=staff) if staff is not None else qs.none()

        finalized = self.request.query_params.get("finalized")
        if finalized == "yes":
            qs = qs.filter(finalized_at__isnull=False)
        elif finalized == "no":
            qs = qs.filter(finalized_at__isnull=True)

        return qs


class SpecimenAssignView(AuditMixin, viewsets.ViewSet):
    """§1 PATCH /specimens/{id}/assign — 집기. 동시 집기는 409.

    ⚠ 09-26 확인 — accession_status 를 여기서 "accessioned" 로 안 올리면
    bound(접수 대기) 였던 검체가 확진까지 끝나도 영원히 접수 대기로
    보인다. draft·finalize·ai-results 어디도 이 칸을 안 건드리기 때문에
    (grep 으로 확인 — bind 때 "bound" 로 찍는 게 유일한 대입이었다),
    집는 순간(=병리과가 검체를 정식으로 받는 시점)이 유일하게 맞는
    자리다.
    """

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        staff = getattr(request.user, "staff", None)
        if staff is None:
            raise ApiError("VALIDATION_ERROR", "의료진 계정이 아닙니다.")

        updated = models.Specimen.objects.filter(
            pk=pk, assigned_to__isnull=True
        ).update(assigned_to=staff, accession_status="accessioned",
                 accessioned_at=timezone.now(), updated_by=self._current_account())

        if updated == 0:
            raise ApiError("ALREADY_ASSIGNED", "다른 선생님이 이미 맡았습니다.")

        specimen = models.Specimen.objects.get(pk=pk)
        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)

class SpecimenAiResultView(AuditMixin, viewsets.ViewSet):
    """§2 POST /specimens/{id}/ai-results — 분석 시작. 올린 크롭마다 1행."""

    resource = "ai_result"
    permission_classes = [MatrixPermission]

    def start(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        results = []
        # deleted_at 이 빈 것만 본다 — 취소된 크롭은 분석 대상이 아니다
        # (views/radiology.py 의 AiResultQueueView.start() 와 같은 자리).
        objects = models.StorageObject.objects.filter(
            specimen=specimen, deleted_at__isnull=True)
        for storage_object in objects:
            # 크롭 한 장이 판독 한 번이다.
            #
            # specimen 을 반드시 채운다 — ai_result_owner_ck 가 study·specimen
            # 중 **정확히 하나**를 요구한다. 둘 다 비우면 행을 만드는 순간
            # 제약 위반으로 500 이 난다. 병리는 검사가 없고 검체에 매달리며,
            # 워커도 study_id 가 비어 있으면 병리로 본다(tasks.py run_inference).
            result = models.AiResult.objects.create(
                patient=specimen.patient,
                specimen=specimen,
                source_object=storage_object,
                run_status="queued",
                created_by=self._current_account(),
                updated_by=self._current_account(),
            )
            results.append(result)
            run_inference.delay(result.pk)
        out = serializers.AiResultSerializer(results, many=True)
        return Response(out.data, status=status.HTTP_202_ACCEPTED)


class SpecimenDraftView(AuditMixin, viewsets.ViewSet):
    """§3 PUT /specimens/{id}/draft — 임시저장(덮어쓰기)."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission, CanFinalizePathologyRead]

    def update(self, request, pk=None):
        specimen = _get_specimen_for_write(request, pk)
        serializer = serializers.SpecimenDraftSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _apply_markers(specimen, data)

        specimen.b_category = data.get("b_category", specimen.b_category)
        specimen.diagnosis = data.get("diagnosis", specimen.diagnosis)
        specimen.finding_note = data.get("finding_note", specimen.finding_note)
        # ⚠ 09-28 — sTIL 은 병리의가 직접 입력한다. 값이 들어왔을 때만
        # 찍고, stil_source 를 "manual" 로 남긴다. stil_level 은 계산하지
        # 않는다 — 여기서 안 건드리면 null 그대로 남는다.
        if data.get("stil_calibrated") is not None:
            specimen.stil_calibrated = data["stil_calibrated"]
            specimen.stil_source = "manual"
        specimen.reported_by = getattr(request.user, "staff", None)
        specimen.updated_by = self._current_account()
        specimen.save()

        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)


class SpecimenFinalizeView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /specimens/{id}/finalize — 확진 확정. finalized_at 을 찍는다."""

    resource = "specimen_pathology"
    permission_classes = [MatrixPermission, CanFinalizePathologyRead]

    def partial_update(self, request, pk=None):
        specimen = _get_specimen_for_write(request, pk)
        serializer = serializers.SpecimenFinalizeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _apply_markers(specimen, data)

        specimen.b_category = data["b_category"]
        specimen.diagnosis = data["diagnosis"]
        specimen.finding_note = data.get("finding_note", "")
        # ⚠ 09-28 — draft 와 같은 규칙. SpecimenDraftView.update() 참고.
        if data.get("stil_calibrated") is not None:
            specimen.stil_calibrated = data["stil_calibrated"]
            specimen.stil_source = "manual"
        specimen.reported_by = getattr(request.user, "staff", None)
        specimen.finalized_at = timezone.now()
        specimen.updated_by = self._current_account()
        specimen.save()

        # 영상 최종 판정과 자동 대조. 규칙은 services/discordance.py 한 곳에
        # 모여 있다 — 여기에 조건문을 두지 않는다.
        # ⚠ **커밋된 뒤** 돈다. 같은 트랜잭션에서 돌리면 확정이 뒤에 실패해
        #   되돌려질 때 플래그만 남는다.
        discordance.evaluate_on_commit(specimen.patient, specimen)
        # 09-28 — 유방외과 주치의에게 「병리 확정」 알림(커밋 뒤)
        _notify_finalized(specimen)

        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data)