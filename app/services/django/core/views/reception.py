"""원무과(reception) view."""

from datetime import datetime, time, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import generics, status, viewsets
from rest_framework import mixins as drf_mixins
from rest_framework.response import Response
from rest_framework.views import APIView

from core.api.errors import ApiError
from core.api.permissions import (
    CanRegisterPatient,
    IsAuthenticatedAccount,
    MatrixPermission,
    OwnedOnlyMixin,
)

from .. import models, serializers
from ..mixins import AuditMixin


def _is_date(value):
    from datetime import date
    try:
        date.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _bad_param(name, message):
    # 쿼리 문자열이 틀리면 ORM 이 ValidationError · ValueError · FieldError 를
    # 던지고 그것이 봉투 밖 500 이 됐다. 400 으로 돌려준다.
    raise ApiError("VALIDATION_ERROR", message, details={name: [message]})


def _param_date(name, value):
    d = parse_date(value) if value else None
    if d is None:
        _bad_param(name, "날짜는 YYYY-MM-DD 로 보내야 합니다.")
    return d


def _param_bound(name, value, end=False):
    """scheduled_from / scheduled_to 경계.

    날짜만 오면(YYYY-MM-DD) from 은 그날 00:00, to 는 **다음 날 00:00 미만**
    으로 본다 — 예전에는 to=2026-09-30 이 「30일 00:00 이하」라 그 달 마지막
    날 예약이 통째로 빠졌다(프론트가 T23:59:59 를 붙여 피하고 있었다).
    시각이 붙어 오면 예전과 같이 그 시각 그대로(이하) 쓴다.
    시간대가 없으면 서버 시간대(Asia/Seoul)로 본다.
    반환: (경계 datetime, 미만으로 걸어야 하는가)
    """
    # ⚠ 요즘 Django 의 parse_datetime 은 날짜만 온 것도 자정으로 받아 준다 —
    #   날짜만인지는 T/공백이 있는지로 먼저 가른다.
    date_only = value and "T" not in value and " " not in value
    try:
        dt = None if date_only else parse_datetime(value)
    except ValueError:
        dt = None
    if dt is None:
        try:
            d = parse_date(value) if value else None
        except ValueError:
            d = None
        if d is None:
            _bad_param(name, "날짜(YYYY-MM-DD) 또는 날짜시각(ISO 8601)이어야 합니다.")
        if end:
            d = d + timedelta(days=1)
        return timezone.make_aware(datetime.combine(d, time.min)), end
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt)
    return dt, False


# 방문 중(오늘 내원했고 아직 끝나지 않은) 오더의 상태
_OPEN_VISIT_STATUSES = ("requested", "scheduled", "ordered", "accepted", "in_progress")
    
    
class PatientViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):

    resource = "patient"
    permission_classes = [MatrixPermission]
    queryset = models.Patient.objects.select_related("pii", "primary_staff").all()
    
    def create(self, request, *args, **kwargs) :
        raise ApiError("ROLE_FORBIDDEN", "환자 등록은 /patients/register 로 합니다.")

    def get_queryset(self):
        # 아직 처분 안 한 판정 불일치가 있는가 — 목록 행에 한 칸으로 얹는다.
        #
        # ⚠ 화면(유방외과 「대기 환자」)은 진작 has_open_discordance 를 읽고
        #   있었는데 **어느 응답에도 그런 칸이 없었다**(09-23 확인). 늘
        #   undefined 라 「판정 불일치」 탭이 어떤 환자도 못 세고, 줄의 경고
        #   점도 안 켜졌다 — 엇갈린 것을 안 엇갈렸다고 말하는 쪽이다.
        #
        # 행마다 세지 않고 Exists 로 얹는다 — 있는지만 알면 된다.
        qs = super().get_queryset().annotate(
            has_open_discordance=Exists(
                models.DiscordanceFlag.objects.filter(
                    lesion__patient_id=OuterRef("patient_id"),
                    closed_at__isnull=True,
                )
            ),
        )

        # retrieve · update · partial_update · destroy 는 pk 로 단건을
        # 찾는다 — 목록 유출 방지용 필터(q/status 없으면 빈 쿼리셋)를 걸면
        # 안 된다. 그 필터는 list 에서 「전체 환자를 실수로 긁는 것」을
        # 막으려는 것이라 list 에만 건다.
        if self.action != "list":
            return qs

        p = self.request.query_params
        q = p.get("q", "").strip()
        status_param = p.get("status")
        primary_staff_param = p.get("primary_staff")

        # 09-27 — primary_staff 는 me 말고 직원 번호(staff_id)와 none(미배정)도
        # 받는다. 예전에는 me 면 **여기서 바로 돌아가 status 를 안 봤다** —
        # 유방외과 waiting() 과 patients() 가 같은 줄을 받던 까닭.
        result = qs
        if primary_staff_param:
            if primary_staff_param == "me":
                staff = getattr(self.request.user, "staff", None)
                if staff is None:
                    return qs.none()
                result = result.filter(primary_staff=staff)
            elif primary_staff_param == "none":
                result = result.filter(primary_staff__isnull=True)
            elif primary_staff_param.isdigit():
                result = result.filter(primary_staff_id=int(primary_staff_param))
            else:
                _bad_param("primary_staff", "me · none · 직원 번호 중 하나여야 합니다.")
        elif not q and not status_param:
            # primary_staff 가 없으면 예전처럼 q/status 가 있어야 목록을 준다
            return qs.none()

        # status=waiting — 오늘 내원했고 아직 끝나지 않은 오더가 있는 환자.
        # 다른 값(all 등)은 예전처럼 거르지 않는다 — 간호 환자 목록이
        # status=all 을 「전체 목록 열쇠」로 쓰고 있다.
        if status_param == "waiting":
            result = result.filter(Exists(models.ExamOrder.objects.filter(
                patient_id=OuterRef("patient_id"),
                visited_at__date=timezone.localdate(),
                order_status__in=_OPEN_VISIT_STATUSES,
            )))

        if q:
            cond = (Q(patient_number=q) |
                    Q(pii__name__icontains=q) |
                    Q(pii__phone__icontains=q))
            # ⚠ 예전에는 날짜가 아닌 검색어에도 Q(pii__birth_date=None) 을
            #   붙여서 「생년월일이 비어 있는 환자」가 어떤 검색에도 다 걸렸다.
            if _is_date(q):
                cond |= Q(pii__birth_date=q)
            result = result.filter(cond)
        # 순서가 없으면 페이지를 넘길 때 줄이 겹치거나 빠진다
        return result.order_by("patient_id")
    
    def owned_queryset(self, queryset, account):
        return queryset.filter(account=account)

    def is_owned_by(self, obj, account):
        return obj.account_id == account.account_id

    def get_serializer_class(self):
        if self.action == "create":
            return serializers.PatientCreateSerializer
        if self.action == "retrieve":
            return serializers.PatientDetailSerializer
        if self.action == "list":
            return serializers.PatientListSerializer
        return serializers.PatientSerializer

    # def create(self, request, *args, **kwargs):
    #     serializer = self.get_serializer(data=request.data)
    #     serializer.is_valid(raise_exception=True)
    #     self.perform_create(serializer)
    #     out = serializers.PatientDetailSerializer(serializer.instance)
    #     return Response(out.data, status=status.HTTP_201_CREATED)


class ReservationViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ViewSet):
    """§5-3 예약 생성. exam_order 로 1:N 생성.

    POST /reservations/   {patient_id, scheduled_at, orders: [{exam_purpose, modality}, ...]}
    """

    resource = "reservation"
    permission_classes = [MatrixPermission]

    def owned_queryset(self, queryset, account):
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id

    def create(self, request):
        if getattr(request.user, "patient", None) is not None :
            raise ApiError("ROLE_FORBIDDEN", "예약 신청은 /me/reservation-request로 하세요")
        patient = getattr(request.user, "patient", None)
        payload = request.data
        if patient is not None:
            payload = {**request.data, "patient_id": patient.patient_id}
        serializer = serializers.ReservationCreateSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        rows = serializer.instance
        out_serializer_class = (
            serializers.PatientExamOrderSerializer if patient is not None
            else serializers.ExamOrderSerializer
        )
        if rows :
            from .. import notify
            when = timezone.localtime(rows[0].scheduled_at)
            notify.send(
                patient=rows[0].patient, 
                type="reservation_created",
                message=f"{when:%m월 %d일 %H시} 검사 예약이 확정되었습니다.", 
                ref_type="exam_order",
                ref_id=rows[0].pk,
                severity="normal",
            )
        out = out_serializer_class(rows, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)


class ReservationRequestViewSet(AuditMixin, viewsets.ViewSet):
    """§7 환자 예약 신청.

    POST /me/reservation-requests   {scheduled_at}
    """

    resource = "reservation"
    permission_classes = [MatrixPermission]

    def get_serializer_class(self):
        return serializers.ReservationRequestCreateSerializer

    def create(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        from datetime import datetime

        from core.api import questionnaire as qm
        date = (request.data or {}).get("date")
        time = (request.data or {}).get("time")
        if not date or not time:
            raise ApiError("VALIDATION_ERROR", "날짜와 시간이 필요합니다.",
                            details={"required": ["date", "time"]})
        try:
            naive = datetime.fromisoformat("%sT%s" % (date, time))
        except ValueError:
            raise ApiError("VALIDATION_ERROR", "날짜/시간 형식이 올바르지 않습니다.")
        scheduled = timezone.make_aware(naive, timezone.get_current_timezone())
        order = models.ExamOrder.objects.create(
            patient=patient, scheduled_at=scheduled, order_status="requested",
            modality=None, exam_purpose=None, ordered_by=None,
            created_by=request.user, updated_by=request.user,
        )
        q = (request.data or {}).get("questionnaire") or {}
        answers = q.get("answers")
        if isinstance(answers, dict) and answers:
            patient.questionnaire = qm.validate(answers)  # ponytail: 환자 캐시에만 저장(방문별 exam_order.questionnaire 는 추후)
            patient.updated_by = request.user
            patient.save(update_fields=["questionnaire", "updated_at"])
        out = serializers.PatientExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_201_CREATED)

class ReservationRequestQueueView(generics.ListAPIView):
    """§7 원무 큐 — order_status='requested' 만 노출.

    GET /reservation-requests
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer
    # 행마다 patient · pii · 주치의를 따로 읽지 않게 한 번에 붙인다(N+1)
    queryset = (models.ExamOrder.objects.filter(order_status="requested")
                .select_related("patient__pii", "patient__primary_staff")
                .order_by("scheduled_at", "exam_order_id"))


class ExamOrderConfirmView(AuditMixin, viewsets.ViewSet):
    """§7 원무 확정 — 날짜만 정한다.

    검사 종류(modality·exam_purpose·ordered_by)는 원무가 아니라 유방외과가
    나중에 정한다 — 0015 로 order_status='scheduled' 가 생겨(09-17 팀 확정),
    원무는 requested → scheduled 로만 옮긴다. ordered 전환은 별도 경로(유방외과)
    가 맡는다.

    PATCH /exam-orders/{id}/confirm   {scheduled_at}
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        from django.db import transaction

        with transaction.atomic():
            # .get() 은 없는 번호에 DoesNotExist 로 500 이었다 → 404
            order = get_object_or_404(
                models.ExamOrder.objects.select_for_update(), pk=pk)

            if order.order_status != "requested":
                raise ApiError("ALREADY_CONFIRMED")

            serializer = serializers.ExamOrderConfirmSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            order.scheduled_at = serializer.validated_data["scheduled_at"]
            order.order_status = "scheduled"
            order.updated_by = self._current_account()
            order.save()

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_200_OK)

class ExamOrderQueryView(
    drf_mixins.ListModelMixin,
    drf_mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """GET /exam-orders — 여러 화면이 공유하는 유연한 목록 조회.
    GET /exam-orders/{id} — 단건 조회.

    지원 쿼리:
      status, visited(yes/none), scheduled_on(today/YYYY-MM-DD),
      visited_on(today/YYYY-MM-DD), scheduled_from, scheduled_to, patient,
      assigned(none/yes — 환자 주치의 배정 여부), ordering
    """

    resource = "exam_order"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.ExamOrderSerializer

    # 정렬 허용 칸. 아무 문자열이나 order_by 에 넘기면 FieldError 로 500 이었다.
    ORDERING_FIELDS = ("visited_at", "scheduled_at", "ordered_at", "exam_order_id",
                       "created_at", "updated_at")

    def get_queryset(self):
        # 목록 한 줄이 patient · pii · 주치의를 읽는다 — 붙여 두지 않으면
        # 간호 큐(page_size 200)가 줄마다 쿼리를 서너 번씩 더 쐈다(N+1).
        qs = models.ExamOrder.objects.select_related(
            "patient__pii", "patient__primary_staff")
        if self.action == "retrieve":
            # 단건은 pk 로 찾는다 — 목록용 거르기를 걸면 ?status= 같은
            # 꼬리 하나로 멀쩡한 오더가 404 가 된다.
            return qs
        p = self.request.query_params

        if p.get("status"):
            qs = qs.filter(order_status=p["status"])

        visited = p.get("visited")
        if visited == "yes":
            qs = qs.filter(visited_at__isnull=False)
        elif visited == "none":
            qs = qs.filter(visited_at__isnull=True)

        scheduled_on = p.get("scheduled_on")
        if scheduled_on == "today":
            qs = qs.filter(scheduled_at__date=timezone.localdate())
        elif scheduled_on:
            qs = qs.filter(scheduled_at__date=_param_date("scheduled_on", scheduled_on))

        # 09-27 — 오늘 내원한 것만. visited=yes 만으로는 **어제 접수하고 안
        # 끝난 오더**까지 오늘 대기 줄에 섞였다.
        visited_on = p.get("visited_on")
        if visited_on == "today":
            qs = qs.filter(visited_at__date=timezone.localdate())
        elif visited_on:
            qs = qs.filter(visited_at__date=_param_date("visited_on", visited_on))

        if p.get("scheduled_from"):
            bound, _ = _param_bound("scheduled_from", p["scheduled_from"])
            qs = qs.filter(scheduled_at__gte=bound)
        if p.get("scheduled_to"):
            bound, exclusive = _param_bound("scheduled_to", p["scheduled_to"], end=True)
            qs = qs.filter(**{"scheduled_at__lt" if exclusive else "scheduled_at__lte": bound})

        if p.get("patient"):
            if not p["patient"].isdigit():
                _bad_param("patient", "환자 번호(patient_id)는 숫자여야 합니다.")
            qs = qs.filter(patient_id=int(p["patient"]))

        # 09-27 — 유방외과로 보냈는가(환자 주치의가 있는가). 간호 「내원 대기」
        # 가 assigned=none 을 붙이면 보낸 환자가 줄에서 빠진다. 보내기는
        # 환자의 primary_staff 만 바꾸고 오더 상태는 requested 그대로라
        # 서버가 이 칸 말고는 가를 방법이 없었다.
        assigned = p.get("assigned")
        if assigned == "none":
            qs = qs.filter(patient__primary_staff__isnull=True)
        elif assigned == "yes":
            qs = qs.filter(patient__primary_staff__isnull=False)
        elif assigned:
            _bad_param("assigned", "none 또는 yes 여야 합니다.")

        ordering = p.get("ordering", "visited_at")
        if ordering.lstrip("-") not in self.ORDERING_FIELDS:
            _bad_param("ordering", "정렬은 %s 중 하나여야 합니다." % ", ".join(self.ORDERING_FIELDS))
        # 같은 시각끼리 페이지를 넘길 때 줄이 겹치거나 빠지지 않게 pk 로 한 번 더
        return qs.order_by(ordering, "exam_order_id")


class StaffListView(generics.ListAPIView):
    """GET /staff?role= — 배정 팝업용 직원 목록."""

    resource = "patient"  # 별도 리소스 없어 patient 권한으로 간주(간호가 조회)
    permission_classes = [MatrixPermission]
    serializer_class = serializers.StaffSerializer

    def get_queryset(self):
        if getattr(self.request.user, "staff", None) is None:
            raise ApiError("ROLE_FORBIDDEN", "의료진만 조회할 수 있습니다.")
        qs = models.Staff.objects.select_related("account").all()
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(account__role=role)
        return qs


class PatientTodayStatusView(viewsets.ViewSet):
    """GET /patients/today-status — 방문 환자 모니터링(§1)."""

    resource = "patient"
    permission_classes = [MatrixPermission]

    # stage 는 예전 문자열 그대로 둔다(화면 dept/home.js STAGE 가 이 글자로
    # 찾는다). 09-27 — 「접수 대기」 하나로 뭉쳐 있던 것을 가르려고
    # stage_code · stage_detail 을 **더한다.**
    #   nursing                간호·문진 — 접수했고 아직 유방외과로 안 보냄
    #   outpatient             외래 진료 — 주치의(유방외과)가 배정됨, 검사 지시 전
    #   radiology_wait         영상의학과 대기
    #   radiology_in_progress  영상의학과 촬영중
    #   ai_analysis            AI 분석중
    #   cancelled              취소
    #   그 밖                  order_status 그대로
    @staticmethod
    def _stage(o):
        if o.order_status in ("requested", "scheduled"):
            if o.patient.primary_staff_id:
                return "접수 대기", "outpatient", "외래 진료"
            return "접수 대기", "nursing", "간호·문진"
        if o.order_status == "cancelled":
            return "cancelled", "cancelled", "취소"
        if o.order_status == "ordered" and not o.assigned_to_id:
            return "영상의학과 대기", "radiology_wait", "영상의학과 대기"
        if o.assigned_to_id:
            if getattr(o, "has_study", False):
                return "AI 분석중", "ai_analysis", "AI 분석중"
            return "영상의학과 촬영중", "radiology_in_progress", "영상의학과 촬영중"
        return o.order_status, o.order_status, o.order_status

    def list(self, request):
        if getattr(request.user, "staff", None) is None:
            raise ApiError("ROLE_FORBIDDEN", "의료진만 조회할 수 있습니다.")
        today = timezone.localdate()
        # 촬영 여부를 줄마다 exists() 로 묻던 것을 한 번에 얹는다(N+1)
        orders = (models.ExamOrder.objects
                  .filter(visited_at__date=today)
                  .select_related("patient__pii", "patient__primary_staff")
                  .annotate(has_study=Exists(models.Study.objects.filter(
                      exam_order_id=OuterRef("pk"))))
                  .order_by("visited_at", "exam_order_id"))

        result = []
        for o in orders:
            stage, code, detail = self._stage(o)
            pii = getattr(o.patient, "pii", None)
            primary_staff = o.patient.primary_staff
            result.append({
                "exam_order_id": o.exam_order_id,
                "patient_id": o.patient_id,
                "patient_name": pii.name if pii else None,
                "stage": stage,
                "stage_code": code,
                "stage_detail": detail,
                "order_status": o.order_status,
                "visited_at": o.visited_at,
                "primary_staff": o.patient.primary_staff_id,
                "primary_staff_name": primary_staff.full_name if primary_staff else None,
            })
        return Response(result)
    
class PatientRegisterView(AuditMixin, viewsets.ViewSet):
    """§1 [+] 등록 — POST /patients/register. (기존 PatientCreateSerializer 와 별개 — 간소화된 접수용)

    CanRegisterPatient — patient 매트릭스(원무만 CRUD)는 그대로 두고
    간호에게 이 endpoint 하나만 연다. 정식 등록(POST /patients/,
    PatientViewSet)은 여전히 원무 단독이다."""
    resource = "patient"
    permission_classes = [CanRegisterPatient]
    
    def create(self, request):
        serializer = serializers.PatientRegisterSerializer(data = request.data)
        serializer.is_valid(raise_exception=True)
        try:
            # patient 와 pii 를 한 트랜잭션으로 — pii 가 실패하면 번호만 있는
            # 환자가 남았다.
            with transaction.atomic():
                patient = serializer.save(
                    created_by = self._current_account(),
                    updated_by=self._current_account(),
                )
        except IntegrityError:
            # validate 와 저장 사이에 같은 전화가 먼저 들어온 경우(동시 등록).
            # 예전에는 500 이었다.
            msg = "이미 다른 환자에게 등록된 전화번호입니다."
            raise ApiError("VALIDATION_ERROR", msg, details={"phone": [msg]})
        created = serializer.created
        out = serializers.PatientDetailSerializer(patient)
        data = {**out.data, "created": created}
        return Response(data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    
class CheckInView(AuditMixin, viewsets.ViewSet):
    """§1 [접수하기] — POST /exam-orders (requested + visited_at)."""
    
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        serializer = serializers.CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient_id = serializer.validated_data["patient_id"]
        now = timezone.now()

        with transaction.atomic():
            patient = models.Patient.objects.select_for_update().get(pk=patient_id)

            # 같은 환자를 오늘 이미 접수했고 아직 requested 면 그 오더를 200 으로
            # 돌려준다. [접수하기] 를 두 번 누르면 내원 대기 줄에 같은 사람이
            # 두 번 섰다.
            existing = (models.ExamOrder.objects
                        .filter(patient_id=patient_id, order_status="requested",
                                visited_at__date=timezone.localdate(now))
                        .order_by("visited_at").first())
            if existing is not None:
                out = serializers.ExamOrderSerializer(existing)
                return Response(out.data, status=status.HTTP_200_OK)

            order = models.ExamOrder.objects.create(
                patient_id=patient_id,
                order_status="requested",
                visited_at=now,
                created_by=self._current_account(),
                updated_by=self._current_account()
            )

            # 초진 시각은 오더의 visited_at 과 **같은 값**이어야 한다 — now() 를
            # 따로 두 번 부르면 몇 μs 어긋나 visit_type 판정이 흔들린다.
            if not patient.first_visited_at:
                patient.first_visited_at = now
                patient.updated_by = self._current_account()
                patient.save(update_fields=["first_visited_at", "updated_by", "updated_at"])

        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status= status.HTTP_201_CREATED)
    
class ExamOrderScheduleView(AuditMixin, viewsets.ViewSet):
    """§3 [예약 완료] — POST /exam-orders (원무가 날짜만 정함, 검사종류는 안 정함)."""
    resource = "exam_order"
    permission_classes = [MatrixPermission]
    
    def create(self, request):
        serializer = serializers.ExamOrderScheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        
        order = models.ExamOrder.objects.create(
            patient_id=data["patient_id"],
            scheduled_at = data["scheduled_at"],
            order_status= "requested",
            ordered_at = timezone.now(),
            created_by = self._current_account(),
            updated_by = self._current_account(),
        )
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status = status.HTTP_201_CREATED)
    
class MeView(viewsets.ViewSet):
    """GET /me"""

    permission_classes = [IsAuthenticatedAccount]  # core.api.permissions 에서 import

    def list(self, request):
        # 환자와 의료진이 같은 문으로 들어오고 role 로만 갈린다.
        # 내보낼 것이 서로 겹치지 않아서 여기서 가른다.
        if request.user.role == "patient":
            out = serializers.MePatientSerializer(request.user)
        else:
            out = serializers.MeSerializer(request.user)
        return Response(out.data)
    
class PushTokenView(viewsets.ViewSet):
    """PATCH /me/push-token — 앱이 받은 FCM 토큰을 자기 계정에 붙인다.

    빈 문자열을 보내면 지운다. 로그아웃할 때 앱이 그렇게 부른다 —
    안 지우면 그 기기를 쓰는 다음 사람에게 남의 알림이 간다.

    대상이 요청 본문이 아니라 토큰에서 나온다. 남의 계정에 붙일 길이 없다.
    """

    permission_classes = [IsAuthenticatedAccount]

    def partial_update(self, request, pk=None):
        serializer = serializers.PushTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = request.user
        account.push_token = serializer.validated_data["push_token"] or None
        account.save(update_fields=["push_token"])
        return Response({"push_token": account.push_token})
    
class NotificationViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """GET /notifications/ · PATCH /notifications/{id}/ — 내 알림.

    격자가 전 역할에 RU(own_only) 를 준다. 만드는 것은 시스템이라 사람에게
    C 가 없고 DELETE 도 없다 — 매트릭스가 알아서 403 을 낸다.
    """

    resource = "notification"
    permission_classes = [MatrixPermission]
    queryset = models.Notification.objects.all()
    serializer_class = serializers.NotificationSerializer

    def owned_queryset(self, queryset, account):
        # 수신자는 환자 아니면 의료진 하나다. 계정에 딸린 쪽으로 건다.
        staff = getattr(account, "staff", None)
        if staff is not None:
            return queryset.filter(staff=staff)
        return queryset.filter(patient__account=account)

    def is_owned_by(self, obj, account):
        staff = getattr(account, "staff", None)
        if staff is not None:
            return obj.staff_id == staff.pk
        return obj.patient is not None and obj.patient.account_id == account.account_id

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.query_params.get("unread") == "true":
            qs = qs.filter(acknowledged_at__isnull=True)
        ntype = self.request.query_params.get("type")
        if ntype:
            qs = qs.filter(notification_type=ntype)
        return qs.order_by("-created_at")

    def update(self, request, *args, **kwargs):
        # 확인 처리만 연다. 본문·수신자·종류는 시스템이 쓴 그대로 둔다 —
        # 기본 동작에 맡기면 매트릭스 U 하나로 message 까지 고쳐진다.
        note = self.get_object()
        if request.data.get("acknowledged") is True and note.acknowledged_at is None:
            note.acknowledged_at = timezone.now()
            note.updated_by = self._current_account()
            note.save(update_fields=["acknowledged_at", "updated_by", "updated_at"])
        return Response(serializers.NotificationSerializer(note).data)
    
def _sections(patient):
    from core.api import questionnaire as qm
    wrapper = patient.questionnaire if isinstance(patient.questionnaire, dict) else {}
    answers = wrapper.get("answers") if isinstance(wrapper.get("answers"), dict) else {}
    answers = answers or {}
    return [{
        "id": q["code"], "question": q["text"],
        "choices": [{"id": o["id"], "label": o["text"]} for o in q["options"]],
        "answer": answers.get(q["code"]),
        "critical": False, "hint": "",   # ponytail: v1.yaml 에 critical 없음 — 전부 False
    } for q in qm.active_questions()]


class PatientHomeView(APIView):
    """GET /home — 환자 홈 집계."""
    permission_classes = [IsAuthenticatedAccount]

    def get(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        from core.api import questionnaire as qm
        now = timezone.now()
        pii = getattr(patient, "pii", None)
        orders = models.ExamOrder.objects.filter(patient=patient)
        visited = orders.filter(visited_at__isnull=False).order_by("-visited_at")
        last = visited.first()

        wrapper = patient.questionnaire if isinstance(patient.questionnaire, dict) else {}
        answers = wrapper.get("answers") if isinstance(wrapper.get("answers"), dict) else {}
        answers = answers or {}
        total = len(qm.active_questions())
        answered = len([k for k in answers if not k.startswith("_")])
        q_status = "not_started" if not answers else ("done" if total and answered >= total else "in_progress")

        upcoming = (orders.filter(scheduled_at__gte=now)
                    .exclude(order_status="cancelled").order_by("scheduled_at").first())
        next_res = None
        if upcoming:
            next_res = {"scheduled_at": upcoming.scheduled_at, "place": None,
                        "modality": upcoming.modality, "modality_label": None}

        reports = models.Report.objects.filter(
            patient=patient, report_type="final", audience="patient").order_by("-report_id")
        new_reports = [{
            "report_id": r.report_id, "lock_status": r.lock_status,
            "title": "검사 결과 안내",
            "issued_at": r.explained_at or r.created_at,
            "issued_by_name": getattr(r.issued_by, "full_name", None),
        } for r in reports]

        return Response({
            "display_name": pii.name if pii else None,
            "visit_count": visited.count(),
            "questionnaire": {"status": q_status, "answered": answered,
                              "total": total, "required": False, "hint": ""},
            "next_reservation": next_res,
            "new_reports": new_reports,
            "today_visit": {"active": False},  # ponytail: 당일 동선 소스 없음
            "calendar": None,                   # ponytail: 달력 마커 소스 없음
            "last_visit_at": last.visited_at if last else None,
            "last_visit_dept": ("영상의학과" if (last and last.modality) else None),
        })


class PatientQuestionnaireView(APIView):
    """GET/PUT /questionnaire — 환자 문진."""
    permission_classes = [IsAuthenticatedAccount]

    def get(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        secs = _sections(patient)
        return Response({"sections": secs, "total": len(secs)})

    def put(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        from core.api import questionnaire as qm
        answers = (request.data or {}).get("answers")
        if not isinstance(answers, dict):
            raise ApiError("VALIDATION_ERROR", "answers 객체가 필요합니다.")
        patient.questionnaire = qm.validate(answers)  # 미상 code/option 이면 400
        patient.updated_by = request.user
        patient.save(update_fields=["questionnaire", "updated_at"])
        return Response({"detail": "저장했습니다."})


#: 하루에 여는 시간대. 점심(12~14시)은 비운다.
OPEN_TIMES = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
              "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]


def _open_slots(weekdays=10):
    """예약 가능 자리 — 내일부터 평일 기준 2주치.

    ponytail: 병원 일정표(슬롯) 모델이 없다. 화면이 달력·시간칸을 그리려면
    [{date, times[]}] 가 있어야 해서 여기서 만들어 준다 — 일정표가 생기면
    이 함수만 쿼리로 바꾸면 화면은 그대로 돈다.
    """
    from datetime import timedelta
    out, day = [], timezone.localdate()
    while len(out) < weekdays:
        day += timedelta(days=1)
        if day.weekday() >= 5:          # 토·일은 안 연다
            continue
        out.append({"date": day.isoformat(), "times": list(OPEN_TIMES)})
    return out


class PatientReservationsView(APIView):
    """GET /me/reservations — 내 예약 + 신청용 문항."""
    permission_classes = [IsAuthenticatedAccount]
    CANCELLABLE = {"requested", "scheduled", "ordered"}

    def get(self, request):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        orders = (models.ExamOrder.objects
                  .filter(patient=patient)
                  .exclude(order_status__in=["cancelled", "completed"])
                  .order_by("-scheduled_at"))
        items = [{
            "exam_order_id": o.exam_order_id, "scheduled_at": o.scheduled_at,
            "modality": o.modality, "modality_label": None,
            "hint": (None if o.modality else "병원에서 검사 종류를 정합니다"),
            "place": None, "order_status": o.order_status, "status_label": None,
            "can_cancel": o.order_status in self.CANCELLABLE,
        } for o in orders]
        ps = patient.primary_staff
        return Response({
            "items": items,
            "open_slots": _open_slots(),
            "required_questions": _sections(patient),
            "required_note": "검사 전 확인이 필요한 문항입니다.",
            "primary_staff_name": getattr(ps, "full_name", None),
            "primary_staff_dept": getattr(getattr(ps, "account", None), "role", None),
            "hospital_phone": None,
            "note": "예약은 병원 확인 후 확정됩니다.",
        })


class PatientReservationCancelView(APIView):
    """POST /me/reservations/{id}/cancel — 본인 예약 취소."""
    permission_classes = [IsAuthenticatedAccount]

    def post(self, request, pk=None):
        patient = getattr(request.user, "patient", None)
        if patient is None:
            raise ApiError("VALIDATION_ERROR", "환자 계정이 아닙니다.")
        order = models.ExamOrder.objects.filter(pk=pk, patient=patient).first()
        if order is None:
            raise ApiError("NOT_FOUND", "예약을 찾을 수 없습니다.")
        order.order_status = "cancelled"
        order.cancelled_by = None
        order.updated_by = request.user
        order.save(update_fields=["order_status", "cancelled_by", "updated_at"])
        return Response({"detail": "예약을 취소했습니다."})
    
# ── 09-21 여기 있던 임시 두 뷰를 뺐다 ─────────────────────────────────
#
# PatientPrescriptionsView · HospitalListView(+HOSPITALS_TEMP). 둘 다 「표가
# 아직 없어서」 둔 임시본이었고, 그 표가 생겨 진짜 구현으로 넘어갔다.
#
#   처방  → core/views/prescription.py 의 MyPrescriptionView
#           임시본은 복약 기록 표가 없어 log_id 가 늘 null 이었다 —
#           환자가 「먹었다」를 눌러도 새로고침하면 사라졌다. 이제
#           medication_log 에 실제로 남는다.
#           약도 content(jsonb) 안의 **차례**로 가리키고 있었다(enumerate
#           의 i). 의사가 약을 하나 지우면 그 뒤로 지난 기록이 전부 다른
#           약을 가리킨다 — PrescriptionDrug 행을 판 이유가 그것이다.
#
#   병원  → core/api/hospitals.py 의 HospitalSearchView
#           임시본은 하드코딩 네 건이었다(「미래 대학병원」…). 이제
#           국립중앙의료원 공공데이터에서 전국 79,013 건을 부른다.
#
# 두 임시본의 주석이 「모델이 생기면 바꾼다」고 적어 둔 그대로 한 것이다.
