"""storage_object 공용 view — 영상의학과 · 병리과가 함께 쓴다.

부서 전용 파일에 안 둔 이유는 serializers/storage.py 상단 주석과 같다 —
study 소유(영상)든 specimen 소유(병리)든 규칙이 하나라 갈라 둘 이유가 없다.
"""

from rest_framework import viewsets
from rest_framework.response import Response

from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import IsAuthenticatedAccount, RADIOLOGY, PATHOLOGY
from core.api.errors import ApiError


class StorageObjectCancelView(AuditMixin, viewsets.ViewSet):
    """PATCH /storage-objects/{id}/cancel — 업로드 취소(조건부 soft-delete).

    §7.7 언저리, 명세 §1-4 25개 밖 — 업로드 화면에서 잘못 올린 파일을 지우는
    자리다. 단순 soft-delete 가 아니다:

        분석 시작 전   해당 study/specimen 에 AiResult 가 하나도 없다.
                       deleted_at · deleted_by · delete_reason 을 찍고 끝.
        분석 시작 후   AiResult 가 이미 있다 — 그 파일을 워커가 이미 봤을 수
                       있어 409(CANCEL_NOT_ALLOWED_AFTER_ANALYSIS). 정정이
                       필요하면 관리자 몫이다.

    Garage/Orthanc 의 실제 파일은 안 건드린다. 보존기간 정책이 나오면 그때
    deleted_at 이 오래된 행을 배치로 지운다 — 이번 범위 밖이다.

    권한은 매트릭스(storage_object: RADIOLOGY/PATHOLOGY 둘 다 CR)를 안 쓴다.
    거긴 U 가 없어서(§ permissions.py "올리는 부서만 C. D 는 아무도") 이
    PATCH 를 못 태운다 — **올린 그 부서만** 이라는 조건도 매트릭스 칸 하나로
    못 표현한다 (study 소유면 영상의학과, specimen 소유면 병리과 — 서로
    바꿔 취소 못 한다). CanFinalizeRadiologyRead 류처럼 여기서 직접 본다.
    """

    resource = "storage_object"
    permission_classes = [IsAuthenticatedAccount]

    def _get_object(self, pk):
        try:
            return models.StorageObject.objects.select_related(
                "study", "specimen"
            ).get(pk=pk)
        except models.StorageObject.DoesNotExist:
            raise ApiError("NOT_FOUND")

    def _required_role(self, obj):
        # report 소유 파일(발급 PDF)은 사람이 올린 게 아니라 이 경로로
        # 못 건드린다 — 어느 부서를 요구해야 할지도 없다.
        if obj.study_id is not None:
            return RADIOLOGY
        if obj.specimen_id is not None:
            return PATHOLOGY
        return None

    def _has_analysis(self, obj):
        if obj.study_id is not None:
            return models.AiResult.objects.filter(study_id=obj.study_id).exists()
        return models.AiResult.objects.filter(specimen_id=obj.specimen_id).exists()

    def cancel(self, request, pk=None):
        obj = self._get_object(pk)

        required_role = self._required_role(obj)
        if required_role is None or request.user.role != required_role:
            raise ApiError("ROLE_FORBIDDEN",
                           details={"reason": "올린 부서만 취소할 수 있습니다."})

        if obj.deleted_at is not None:
            # 이미 취소된 행이다 — 다시 취소할 것이 없다.
            raise ApiError("NOT_FOUND")

        if self._has_analysis(obj):
            raise ApiError("CANCEL_NOT_ALLOWED_AFTER_ANALYSIS")

        serializer = serializers.StorageObjectCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        account = self._current_account()
        obj.deleted_at = timezone.now()
        obj.deleted_by = account
        obj.delete_reason = serializer.validated_data.get("reason", "")
        obj.updated_by = account
        obj.save()

        out = serializers.StorageObjectSerializer(obj)
        return Response(out.data)
