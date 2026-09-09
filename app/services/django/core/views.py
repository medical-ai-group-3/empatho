"""API ViewSet.

라우터 인계 문서(EMPATHO_라우터_인계_최종문서) 기준. 역할별로 단계적으로
채운다. 지금은 1단계 골격 — reception·nursing 만 시그니처를 두고, 본체는
직접 구현.

경로 맵은 core/urls.py 주석 참고.
"""

from rest_framework import viewsets
from rest_framework.decorators import action

from rest_framework import status
from rest_framework.response import Response

from django.db.models import Q

from . import models, serializers
from .mixins import RoleScopedViewSet




# ── reception · 원무 ──────────────────────────────────────────
class PatientViewSet(RoleScopedViewSet, viewsets.ModelViewSet):

    required_roles = {"reception", "nursing"}
    queryset = models.Patient.objects.select_related("pii").all()

    def get_queryset(self):
            qs = super().get_queryset()
            q = self.request.query_params.get("q", "").strip()
            if not q:
                return qs.none()
            return qs.filter(
                Q(patient_number=q) |
                Q(pii__name__icontains=q) |
                Q(pii__phone__icontains=q)
            )
            
    def get_serializer_class(self):
        if self.action == "create":
            return serializers.PatientCreateSerializer
        if self.action == "retrieve":
            return serializers.PatientDetailSerializer
        if self.action == "list":
            return serializers.PatientListSerializer
        return serializers.PatientSerializer
    

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data= request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        out = serializers.PatientDetailSerializer(serializer.instance)
        return Response(out.data, status=status.HTTP_201_CREATED)
class ReservationViewSet(RoleScopedViewSet, viewsets.ViewSet):
    """§5-3 예약 생성. exam_order 로 1:N 생성.

    POST /reservations/   {patient_id, scheduled_at, orders: [{exam_purpose, modality}, ...]}
    """

    required_roles = {"reception"}
    
    def create(self, request):
        serializer = serializers.ReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        rows = serializer.instance
        out = serializers.ExamOrderSerializer(rows, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)

    


# ── nursing · 간호 ───────────────────────────────────────────
class VisitTodayViewSet(RoleScopedViewSet, viewsets.ViewSet):
    """§6-1 오늘 방문.

    GET  /visits/today/            오늘 scheduled_at 인 exam_order + 방문상태
    POST /visits/today/            {exam_order_id} → visited_at = now()
    """

    required_roles = {"nursing"}

   


class FollowupViewSet(RoleScopedViewSet, viewsets.ModelViewSet):
    """§6-3 추적 관리.

    GET   /followups/             due_at 정렬 목록
    POST  /followups/             status='open' 으로 생성
    PATCH /followups/{id}/        통화결과(call_result/call_note) 또는 종료(closed_reason)
    """

    required_roles = {"nursing"}
    queryset = models.Followup.objects.select_related("patient").order_by("due_at")
    serializer_class = serializers.FollowupSerializer




class QuestionnaireView(RoleScopedViewSet, viewsets.ViewSet):
    """§6-2 문진 저장. patient.questionnaire (JSONB) 병합.

    PATCH /patients/{patient_id}/questionnaire/
    """

    required_roles = {"nursing"}
    
    def partial_update(self, request, pk=None):
        return Response(status=status.HTTP_501_NOT_IMPLEMENTED)

