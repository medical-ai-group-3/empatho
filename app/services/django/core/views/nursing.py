"""간호과(nursing) view."""

from rest_framework import viewsets, status
from rest_framework.response import Response

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin
from core.api import questionnaire as questionnaire_module
from core.api.errors import ApiError

from .reception import (_OPEN_VISIT_STATUSES, _stamp_first_visit, mark_visited,
                        question_defs)


class VisitTodayViewSet(AuditMixin, viewsets.ViewSet):
    """§6-1 오늘 방문.

    GET  /visits/today/            오늘 scheduled_at 인 exam_order 목록 + 내원상태
    POST /visits/today/            {exam_order_id} → visited_at = now()
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def list(self, request):
        today = timezone.localdate()
        # 줄마다 patient · pii · 주치의를 따로 읽지 않게(N+1)
        qs = (models.ExamOrder.objects
              .filter(scheduled_at__date=today)
              .select_related("patient__pii", "patient__primary_staff")
              .order_by("scheduled_at", "exam_order_id"))
        out = serializers.ExamOrderSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request):
        serializer = serializers.VisitCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        with transaction.atomic():
            # 없는 번호면 DoesNotExist 로 500 이었다 → 404
            order = get_object_or_404(
                models.ExamOrder.objects.select_for_update().select_related("patient"),
                pk=serializer.validated_data["exam_order_id"])
            if order.order_status == "cancelled":
                raise ApiError("RESERVATION_LOCKED", "취소된 예약은 내원 처리할 수 없습니다.")
            # 이미 내원 확인한 오더를 다시 누르면 처음 온 시각이 덮여 대기
            # 순서가 뒤로 밀렸다. 처음 값을 지킨다(mark_visited 가 지킨다).
            # 09-27 — scheduled 는 requested 로 돌려 간호 「내원 대기」에 선다.
            if mark_visited(order, now, self._current_account()):
                # 초진 시각 — 접수(CheckInView)와 같은 규칙
                _stamp_first_visit(order.patient, now, self._current_account())
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_200_OK)


class FollowupViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§6-3 추적 관리."""

    resource = "followup"
    permission_classes = [MatrixPermission]
    # patient_name 이 patient.pii 를 읽는다 — pii 까지 붙여야 줄마다 안 쏜다(N+1)
    queryset = models.Followup.objects.select_related("patient__pii").order_by("due_at", "followup_id")
    serializer_class = serializers.FollowupSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def list(self, request, *args, **kwargs):
        existing = self.get_queryset()
        existing_data = serializers.FollowupSerializer(existing, many=True).data
        result = list(existing_data)

        if request.query_params.get("include_candidates") == "1" and getattr(request.user, "staff", None) is not None:
            tracked_patient_ids = set(existing.values_list("patient_id", flat=True))
            candidates = models.Assessment.objects.filter(
                category="3", read_stage="final"
            ).exclude(lesion__patient_id__in=tracked_patient_ids).select_related("lesion__patient__pii")
            patient = request.query_params.get("patient")
            if patient:
                candidates = candidates.filter(lesion__patient_id=int(patient))

            for a in candidates:
                if a.lesion and a.lesion.patient_id not in tracked_patient_ids:
                    pii = getattr(a.lesion.patient, "pii", None)
                    result.append({
                        "followup_id": None,
                        "patient": a.lesion.patient_id,
                        "patient_name": pii.name if pii else None,
                        "status": "candidate",
                        "round_no": 0,
                    })
                    tracked_patient_ids.add(a.lesion.patient_id)

        return Response(result)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        # 예전에는 request.data 를 그대로 모델에 넣었다 — status 에 모르는 값이
        # 오면 CHECK 위반(IntegrityError)으로, 긴 메모는 DataError 로 500 이었다.
        serializer = serializers.FollowupUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # 09-28 — 회차 결과. 혼자 오면 결과만 적고 통화 기록은 안 건드린다
        # (예전 규칙대로 가면 call_result 가 None 으로 지워진다).
        if "round_result" in data:
            instance.round_result = data["round_result"]
        only_result = "round_result" in data and not (
            {"call_result", "call_note", "status"} & set(data))

        if "closed_reason" in data:
            instance.status = data.get("status", "resolved")
            instance.closed_at = timezone.now()
            instance.closed_reason = data["closed_reason"]
        elif only_result:
            pass
        else:
            instance.call_result = data.get("call_result")
            instance.call_note = data.get("call_note")
            instance.called_by = getattr(request.user, "staff", None)
            instance.called_at = timezone.now()

        instance.updated_by = self._current_account()
        instance.save()

        out = serializers.FollowupSerializer(instance)
        return Response(out.data)

    def get_queryset(self):
        qs = super().get_queryset()
        # 09-28 — ?patient=<id> 로 한 환자의 회차만. 환자 상세 · 예약 팝업이
        # 전체 목록을 받아 화면에서 거르던 것.
        patient = self.request.query_params.get("patient")
        if patient and self.action == "list":
            if not str(patient).isdigit():
                raise ApiError("VALIDATION_ERROR", "patient 는 숫자여야 합니다.")
            qs = qs.filter(patient_id=int(patient))
        return qs

    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id



class QuestionnaireView(AuditMixin, viewsets.ViewSet):
    """§6-2 문진 저장."""

    resource = "questionnaire"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        # 없는 환자면 DoesNotExist 로 500 이었다 → 404
        patient = get_object_or_404(models.Patient, pk=pk)
        validated = questionnaire_module.validate(request.data)
        account = self._current_account()
        # 09-28 — 창구에서 종이 문진을 옮겨 적으면 **오늘 방문 오더에도** 담는다.
        # 진실은 exam_order.questionnaire 이고 patient 쪽은 캐시다(models.py) —
        # 예전에는 캐시에만 써서 접수 화면(오더를 읽는다)에 안 떴다.
        # 앱 문진(PUT /questionnaire)과 같이 한 트랜잭션에 양쪽을 쓴다.
        with transaction.atomic():
            patient.questionnaire = validated
            patient.updated_by = account
            patient.save()
            order = todays_open_order(patient.pk)
            if order is not None:
                order.questionnaire = validated
                order.updated_by = account
                order.save(update_fields=["questionnaire", "updated_by", "updated_at"])
        out = serializers.PatientDetailSerializer(patient)
        # 어느 오더에 담겼는지(없으면 null) — 화면이 접수 줄을 새로 그릴 때 쓴다
        return Response({**out.data,
                         "questionnaire_exam_order_id": order.pk if order else None})


def todays_open_order(patient_id):
    """오늘의 방문 오더 — 문진을 담을 자리. 없으면 None.

    먼저 오늘 내원했고 아직 안 끝난 오더(최근 내원 순), 없으면 오늘로 잡힌
    취소 안 된 예약(아직 안 왔어도 — 접수 전에 문진부터 받는 경우).
    """
    today = timezone.localdate()
    visited = (models.ExamOrder.objects
               .filter(patient_id=patient_id, visited_at__date=today,
                       order_status__in=_OPEN_VISIT_STATUSES)
               .order_by("-visited_at", "-exam_order_id").first())
    if visited is not None:
        return visited
    return (models.ExamOrder.objects
            .filter(patient_id=patient_id, scheduled_at__date=today,
                    visited_at__isnull=True)
            .exclude(order_status="cancelled")
            .order_by("scheduled_at", "exam_order_id").first())


class QuestionnaireFormView(viewsets.ViewSet):
    """GET /questionnaire/form — 의료진용 문진 문항(창구에서 종이 문진을 옮겨 적는 자리).

    환자 앱의 GET /questionnaire 와 **같은 문항 · 같은 모양**(id · question ·
    choices[{id, label}] · critical · hint)이다. 답은 싣지 않는다 — 환자별
    답은 환자 상세(questionnaire)나 오더에서 읽는다.
    권한은 questionnaire 행의 R(의료진 전부, 환자 없음).
    """

    resource = "questionnaire"
    permission_classes = [MatrixPermission]

    def list(self, request):
        questions = question_defs()
        return Response({
            "form_version": questionnaire_module.form()["form_version"],
            "questions": questions,
            "total": len(questions),
        })
    

class FollowupCreateView(AuditMixin, viewsets.ViewSet):
    """§2 POST /followups — 회차 생성."""

    resource = "followup"
    permission_classes = [MatrixPermission]

    def create(self, request):
        serializer = serializers.FollowupCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        followup = models.Followup.objects.create(
            patient_id=data["patient_id"],
            round_no=data["round_no"],
            status="open",
            started_at=timezone.now(),
            due_at=data["due_at"],
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.FollowupSerializer(followup)
        return Response(out.data, status=status.HTTP_201_CREATED)


class FollowupCallView(AuditMixin, viewsets.ViewSet):
    """§2 PATCH /followups/{id}/call — 안내 콜 기록."""

    resource = "followup"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        # 없는 번호면 DoesNotExist 로 500 이었다 → 404
        followup = get_object_or_404(models.Followup, pk=pk)
        serializer = serializers.FollowupCallSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        followup.call_result = data["call_result"]
        followup.call_note = data.get("call_note", "")
        followup.called_by = getattr(request.user, "staff", None)
        followup.called_at = timezone.now()
        followup.updated_by = self._current_account()
        followup.save()

        out = serializers.FollowupSerializer(followup)
        return Response(out.data)


class ExamOrderNoteView(AuditMixin, viewsets.ViewSet):
    """PATCH /exam-orders/{id}/note — 내원 메모 저장."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderNoteSerializer

    def partial_update(self, request, pk=None):
        # 없는 번호면 DoesNotExist 로 500 이었다 → 404
        order = get_object_or_404(
            models.ExamOrder.objects.select_related("patient__pii", "patient__primary_staff"),
            pk=pk)
        serializer = serializers.ExamOrderNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order.order_note = serializer.validated_data["note"]
        order.updated_by = self._current_account()
        order.save(update_fields=["order_note", "updated_by", "updated_at"])

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data)


class PatientPiiView(AuditMixin, viewsets.ViewSet):
    """PATCH /patients/{id}/pii — 창구 인적 사항 정정 {name?, phone?, birth_date?}.

    권한은 매트릭스의 patient_pii 행 U(원무 · 원무를 합친 간호). 보낸 칸만
    고친다. 전화가 다른 환자와 겹치면 400 VALIDATION_ERROR(details.phone) —
    등록(PatientRegisterView)과 같은 규칙이고, 검사와 저장 사이에 끼어든
    동시 요청도 IntegrityError 를 같은 오류로 돌린다.
    """

    resource = "patient_pii"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        patient = get_object_or_404(models.Patient, pk=pk)
        serializer = serializers.PatientPiiCorrectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        msg = "이미 다른 환자에게 등록된 전화번호입니다."
        phone = data.get("phone")
        if phone and models.PatientPii.objects.filter(phone=phone).exclude(
                patient_id=patient.pk).exists():
            raise ApiError("VALIDATION_ERROR", msg, details={"phone": [msg]})
        account = self._current_account()
        try:
            with transaction.atomic():
                pii, _ = models.PatientPii.objects.get_or_create(
                    patient=patient, defaults={"created_by": account})
                for field, value in data.items():
                    setattr(pii, field, value)
                pii.updated_by = account
                pii.save()
                patient.updated_by = account
                patient.save(update_fields=["updated_by", "updated_at"])
        except IntegrityError:
            raise ApiError("VALIDATION_ERROR", msg, details={"phone": [msg]})
        patient = models.Patient.objects.select_related("pii", "primary_staff").get(pk=patient.pk)
        return Response(serializers.PatientDetailSerializer(patient).data)
