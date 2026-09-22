"""유방외과(surgery) view — 2026-09-14 화면명세 기준."""

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .. import models, serializers
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin, CanDisposeDiscordance
from core.api.errors import ApiError
from core.api.permissions import CanBindSpecimen, CanDecideAssessment, CanUnlockReport, CanIssueFinalReport
class ExamOrderRequestView(AuditMixin, viewsets.ViewSet):
    """§1 POST /exam-orders — 촬영 요청 팝업(유방외과가 만드는 오더)."""

    resource = "exam_order"
    permission_classes = [MatrixPermission]

    def create(self, request):
        serializer = serializers.ExamOrderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        order = models.ExamOrder.objects.create(
            patient_id=data["patient_id"],
            modality=data["modality"],
            exam_purpose=data["exam_purpose"],
            order_note = data.get("order_note", ""),
            order_status="ordered",
            ordered_at=timezone.now(),
            ordered_by=getattr(request.user, "staff", None),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.ExamOrderSerializer(order)
        return Response(out.data, status=status.HTTP_201_CREATED)


class PatientTimelineView(AuditMixin, viewsets.ViewSet):
    """§2 GET /patients/{id}/timeline — 다섯 표 조립."""

    resource = "patient"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        patient = models.Patient.objects.filter(pk=pk).first()
        if patient is None :
            raise ApiError("NOT_FOUND", "환자를 찾을 수 없습니다")
        if request.user.role == "patient" and patient.account_id != request.user.account_id:
            raise ApiError("ROLE_FORBIDDEN", "본인 기록만 볼 수 있습니다.")

        events = []
        for study in models.Study.objects.filter(patient=patient):
            if study.performed_at:
                events.append({"at": study.performed_at, "type": "촬영", "detail": study.modality})

        for ai in models.AiResult.objects.filter(patient=patient):
            if ai.analyzed_at:
                events.append({"at": ai.analyzed_at, "type": "AI 분석 완료", "detail": None})

        for assessment in models.Assessment.objects.filter(study__patient=patient):
            events.append({
                "at": assessment.created_at, "type": "판독", "detail": assessment.category,
                "assessment_id": assessment.assessment_id,
            })

        for specimen in models.Specimen.objects.filter(patient=patient):
            if specimen.collected_at:
                events.append({"at": specimen.collected_at, "type": "검체 채취", "detail": specimen.specimen_label})
            if specimen.finalized_at:
                events.append({"at": specimen.finalized_at, "type": "병리 확진", "detail": specimen.diagnosis})

        events.sort(key=lambda e: e["at"])
        return Response(events)


class SurgeryReportViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§2·§3 GET/PUT /reports/{id}, GET /reports?patient=&type=final."""

    resource = "report"
    permission_classes = [MatrixPermission]
    queryset = models.Report.objects.all()
    serializer_class = serializers.ReportSerializer
    http_method_names = ["get", "put", "patch", "head", "options"]
    
    def owned_queryset(self, queryset, account):
        # 환자에게는 환자용만. 의사용에는 BI-RADS · px · sTIL 이 그대로 들어 있다 —
        # 환자용 소견문에서 걷어낸 것들이 이 문으로 다 나간다.
        return queryset.filter(patient__account=account, lock_status="unlocked",
                               audience="patient")

    def is_owned_by(self, obj, account):
        return obj.patient.account_id == account.account_id

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get("patient")
        report_type = self.request.query_params.get("type")
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        if report_type:
            qs = qs.filter(report_type=report_type)
        # 정렬을 안 걸면 목록 순서가 DB 마음이다. 의사가 이 목록에서 고른 순서가
        # 그대로 종합 소견서의 검사 순서가 되므로, 뒤섞이면 글도 뒤섞인다.
        return qs.order_by("report_id")

    def update(self, request, *args, **kwargs):
        report = self.get_object()
        incoming = request.data.get("content_json")
        if incoming is not None:
            if not isinstance(incoming, dict):
                raise ApiError("VALIDATION_ERROR", "content_json은 객체여야 합니다.")

            current = report.content_json if isinstance(report.content_json, dict) else {}
            merged = {**current, **incoming}
            current_by_modality = current.get("by_modality")
            incoming_by_modality = incoming.get("by_modality")
            if isinstance(current_by_modality, dict) or isinstance(incoming_by_modality, dict):
                merged["by_modality"] = {
                    **(current_by_modality if isinstance(current_by_modality, dict) else {}),
                    **(incoming_by_modality if isinstance(incoming_by_modality, dict) else {}),
                }
            report.content_json = merged

        # 소견문 수정 — 진료 완료 전까지만 연다. 완료 뒤에는 환자가 이미 읽은
        # 글이라 말없이 바뀌면 안 된다. 고치려면 새로 발급한다.
        text = request.data.get("narrative_text")
        if text is not None:
            if not isinstance(text, str):
                raise ApiError("VALIDATION_ERROR", "narrative_text는 문자열이어야 합니다.")
            if report.lock_status != "locked":
                raise ApiError("VALIDATION_ERROR", "진료가 완료된 소견서는 고칠 수 없습니다.")
            report.narrative_text = text
            # AI 가 쓴 글인지 사람이 고친 글인지 남긴다 — 화면이 표시에 쓰고,
            # 「의사가 매번 고치는 부분」을 찾아 프롬프트를 손볼 단서가 된다.
            cur = report.content_json if isinstance(report.content_json, dict) else {}
            report.content_json = {**cur, "edited_by_clinician": True}

        report.updated_by = self._current_account()
        report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)
    
    def retrieve(self, request, *args, **kwargs):
        report = self.get_object()
        if report.last_viewed_at is None:
            report.last_viewed_at = timezone.now()
            report.last_viewed_by = getattr(request.user, "staff", None)
            report.view_count = (report.view_count or 0) + 1
            report.save()
        else:
            report.view_count = (report.view_count or 0) + 1
            report.last_viewed_at = timezone.now()
            report.save()
        out = serializers.ReportSerializer(report)
        return Response(out.data)


class SurgeryDecisionView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /assessments/{id}/decision — 수술 여부·사유(decision_*)."""

    permission_classes = [CanDecideAssessment]

    def partial_update(self, request, pk=None):
        serializer = serializers.SurgeryDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            assessment = models.Assessment.objects.get(pk=pk)
        except models.Assessment.DoesNotExist:
            raise ApiError("NOT_FOUND")

        assessment.decision_type = data["decision_type"]
        assessment.decision_value = data["decision_value"]
        assessment.decision_reason = data.get("decision_reason", "")
        assessment.decided_by = getattr(request.user, "staff", None)
        assessment.decided_at = timezone.now()
        assessment.updated_by = self._current_account()
        assessment.save()

        out = serializers.AssessmentSerializer(assessment)
        return Response(out.data)


class ReportExplainView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /reports/{id}/explain — 환자 설명 기록."""

    resource = "report"
    permission_classes = [MatrixPermission]

    def partial_update(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)
        serializer = serializers.ReportExplainSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        report.explain_method = data["explain_method"]
        report.patient_confirmed = data["patient_confirmed"]
        report.explained_by = getattr(request.user, "staff", None)
        report.explained_at = timezone.now()
        report.updated_by = self._current_account()
        report.save()

        out = serializers.ReportSerializer(report)
        return Response(out.data)


class ReportUnlockStatusView(viewsets.ViewSet):
    """§3 GET /reports/{id}/unlock-status — 잠금 해제 세 조건 판단."""

    resource = "report"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)
        patient = report.patient

        records_final = not models.Study.objects.filter(
            patient=patient
        ).exclude(read_status="finalized").exists() and not models.Specimen.objects.filter(
            patient=patient, finalized_at__isnull=True
        ).exists()

        discordance_closed = not models.DiscordanceFlag.objects.filter(
            lesion__patient=patient, closed_at__isnull=True
        ).exists()

        explained = report.explained_at is not None

        conditions = [
            {"key": "records_final", "label": "전 레코드 확정", "met": records_final},
            {"key": "discordance_closed", "label": "대조 종결", "met": discordance_closed},
            {"key": "explained", "label": "대면 설명 완료", "met": explained},
        ]
        can_unlock = all(c["met"] for c in conditions)

        return Response({"conditions": conditions, "can_unlock": can_unlock})


class ReportUnlockView(AuditMixin, viewsets.ViewSet):
    """§3 PATCH /reports/{id}/unlock — 잠금 해제."""

    resource = "report"
    permission_classes = [MatrixPermission, CanUnlockReport]

    def partial_update(self, request, pk=None):
        report = models.Report.objects.get(pk=pk)

        status_view = ReportUnlockStatusView()
        status_check = status_view.retrieve(request, pk=pk).data
        if not status_check["can_unlock"]:
            raise ApiError("VALIDATION_ERROR", "잠금 해제 조건이 충족되지 않았습니다.",
                           details=status_check["conditions"])

        report.lock_status = "unlocked"
        report.unlocked_by = getattr(request.user, "staff", None)
        report.unlocked_at = timezone.now()
        report.unlock_reason = request.data.get("unlock_reason", "")
        report.updated_by = self._current_account()
        report.save()
        
        # 환자에게는 환자용 한 벌만 알린다. 종합 소견서는 의사용·환자용 두 벌이
        # 같이 풀려서, 안 가리면 같은 결과로 알림이 두 번 간다.
        if report.audience != "clinician":
            from .. import notify
            notify.send(
                patient=report.patient,
                type="report_ready",
                message="검사 결과가 도착했습니다. 앱에서 확인해 주세요.",
                ref_type="report",
                ref_id=report.pk,
                severity="sev1",
            )

        out = serializers.ReportSerializer(report)
        return Response(out.data)

class FinalReportView(viewsets.ViewSet):
    """POST /reports/final — 고른 검사 판독문들을 종합 소견서 두 벌로 묶는다."""

    resource = "report"
    permission_classes = [MatrixPermission, CanIssueFinalReport]

    def create(self, request):
        patient_id = request.data.get("patient_id")
        report_ids = request.data.get("source_report_ids")
        if not patient_id or not isinstance(report_ids, list) or not report_ids:
            raise ApiError("VALIDATION_ERROR",
                           "patient_id 와 source_report_ids 가 필요합니다.")

        found = {r.pk: r for r in models.Report.objects.filter(
            pk__in=report_ids, patient_id=patient_id, report_type="stage")}
        missing = [i for i in report_ids if i not in found]
        if missing:
            raise ApiError("VALIDATION_ERROR",
                           f"이 환자의 검사 판독문이 아닙니다: {missing}")

        # Report 에서 AiResult 로 가는 FK 가 없다. 리포트를 세울 때 쓴 열쇠를
        # 그대로 되짚는다. 병리는 study 가 비어 있어 검체로만 닿는다.
        ai_ids = []
        for rid in report_ids:
            r = found[rid]
            key = ({"specimen_id": r.specimen_id} if r.specimen_id
                   else {"study_id": r.study_id, "specimen_id": None})
            ai = (models.AiResult.objects
                  .filter(run_status="done", **key)
                  .order_by("-analyzed_at").first())
            if ai is None:
                raise ApiError("VALIDATION_ERROR",
                               f"판독문 {rid} 의 판독 결과를 찾지 못했습니다.")
            ai_ids.append(ai.pk)

        from .. import reports
        out = reports.issue_final_report(
            patient_id, ai_ids, getattr(request.user, "staff", None))
        return Response(serializers.ReportSerializer(out, many=True).data,
                        status=status.HTTP_201_CREATED)

def _specimen_ai(specimen):
    """크롭 한 장 = AiResult 한 행. 병리 판독 화면의 AI 소견 칸이 읽는다.

    ⚠ sTIL 은 내보내지 않는다(null). 소켓이 내는 stil_percent 는 임상 육안
      TIL 의 약 1/12 스케일이고(비보정), 보정은 슬라이드 합산값에만 적용한다
      — empatho-inference/sockets/pathology.py 상단. 그 합산 코드가 아직
      앱 서버에 없다. 비보정값을 보정값 자리에 넣으면 화면이 「면역 반응이
      거의 없다」로 읽힌다.

    ⚠ 평균을 내지 않는다. 같은 슬라이드도 자른 자리에 따라 0~36% 로
      요동친다(CV≈1.0). 크롭마다 한 줄씩 그대로 올린다.
    """
    rows = (models.AiResult.objects
            .filter(source_object__specimen=specimen, run_status="done")
            .select_related("source_object")
            .order_by("source_object_id"))

    out = []
    for r in rows:
        res = (r.result or {}).get("result") or {}
        so = r.source_object
        out.append({
            "id": r.pk,
            "name": so.object_key if so else None,
            "abstained": bool(r.abstained),
            "abstain_reason": r.abstain_reason,
            "stroma_status": res.get("stroma_status"),
            "stil_calibrated": None,
            "stil_level": None,
            "tsr_percent": res.get("tsr_stroma_percent"),
            "cell_counts": {
                "total": res.get("n_cells_total"),
                "til": res.get("n_cells_til"),
                "til_stromal": res.get("n_cells_til_stromal"),
            },
            "mask": res.get("tissue_mask"),
        })
    return out

class SpecimenBindViewSet(AuditMixin, viewsets.ViewSet):
    """§4 POST /specimens — 검체 바인딩.
    §4(병리과) GET /specimens — 전체 목록 + 필터/정렬.
    """

    resource = "specimen_pathology"

    def get_permissions(self):
        if self.action == "create":
            return [CanBindSpecimen()]
        return [MatrixPermission()]
    
    def list(self, request):
        qs = models.Specimen.objects.select_related("patient__pii").all()
        ordering = request.query_params.get("ordering")
        allowed = {
            "patient__name": "patient__pii__name",
            "collected_at": "collected_at",
            "accessioned_at": "accessioned_at",
            "accession_status": "accession_status",
        }
        if ordering and ordering.lstrip("-") in allowed:
            field = allowed[ordering.lstrip("-")]
            qs = qs.order_by(("-" + field) if ordering.startswith("-") else field)
        out = serializers.SpecimenSerializer(qs, many = True)
        return Response(out.data)
    
    def create(self, request):
        serializer = serializers.SpecimenBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        specimen = models.Specimen.objects.create(
            lesion_id=data["lesion_id"],
            patient_id=models.Lesion.objects.get(pk=data["lesion_id"]).patient_id,
            specimen_label=data["specimen_label"],
            specimen_type=data["specimen_type"],
            guidance_route=data["guidance_route"],
            collected_at=data["collected_at"],
            accession_status="bound",
            bound_by=getattr(request.user, "staff", None),
            created_by=self._current_account(),
            updated_by=self._current_account(),
        )
        out = serializers.SpecimenSerializer(specimen)
        return Response(out.data, status=status.HTTP_201_CREATED)
    
    def retrieve(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        out = serializers.SpecimenSerializer(specimen)
        # ai 는 상세에서만 붙인다 — 목록(list)에 붙이면 행마다 크롭 조회가
        # 따라붙어 N+1 이 된다.
        return Response({**out.data, "ai": _specimen_ai(specimen)})

class SpecimenUploadListView(viewsets.ViewSet):
    resource = "specimen_pathology"
    permission_classes = [MatrixPermission]

    def retrieve(self, request, pk=None):
        specimen = models.Specimen.objects.get(pk=pk)
        # 취소된(soft-delete) 파일은 업로드 목록에서 뺀다.
        objects = models.StorageObject.objects.filter(
            specimen=specimen, deleted_at__isnull=True)
        uploads = serializers.StorageObjectSerializer(objects, many=True).data

        # AI가 만든 조직 세그멘테이션은 StorageObject가 아니라 Image
        # (empatho-derived)에 저장된다. 원본 업로드만 반환하면 프론트는
        # mask 주소를 알 수 없으므로, 원본과 연결된 mask 파생물을 같은
        # 목록에 추가한다. 기존 uploads 항목의 모양은 변경하지 않는다.
        masks = models.Image.objects.filter(
            source_object__in=objects,
            kind="mask",
            deleted_at__isnull=True,
        ).values(
            "image_id", "source_object_id", "ai_result_id", "kind",
            "bucket", "object_key", "width_px", "height_px", "content_type",
            "byte_size",
        )
        uploads.extend({
            "id": row["image_id"],
            "storage_object_id": row["image_id"],
            "source_object_id": row["source_object_id"],
            "ai_result_id": row["ai_result_id"],
            "kind": row["kind"],
            "bucket": row["bucket"],
            "object_key": row["object_key"],
            "width_px": row["width_px"],
            "height_px": row["height_px"],
            "content_type": row["content_type"],
            "byte_size": row["byte_size"],
            "name": row["object_key"],
        } for row in masks if row["object_key"])
        return Response({"specimen_id": specimen.specimen_id, "uploads": uploads})

class DiscordanceListView(generics.ListAPIView):
    """§1·§5 GET /discordances?patient={id}&status=open."""

    resource = "discordance_review"
    permission_classes = [MatrixPermission]
    serializer_class = serializers.DiscordanceFlagSerializer

    def get_queryset(self):
        qs = models.DiscordanceFlag.objects.all()
        patient_id = self.request.query_params.get("patient")
        status_param = self.request.query_params.get("status")
        if patient_id:
            qs = qs.filter(lesion__patient_id=patient_id)
        if status_param == "open":
            qs = qs.filter(closed_at__isnull=True)
        return qs


class DiscordanceDisposeView(AuditMixin, viewsets.ViewSet):
    """§5 PATCH /discordances/{id}/dispose — 처분 확정."""

    resource = "discordance_review"
    permission_classes = [CanDisposeDiscordance]

    def partial_update(self, request, pk=None):
        flag = models.DiscordanceFlag.objects.get(pk=pk)
        serializer = serializers.DiscordanceDisposeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        flag.disposition_type = data["disposition_type"]
        flag.disposition_reason = data["disposition_reason"]
        flag.disposed_by = getattr(request.user, "staff", None)
        flag.closed_at = timezone.now()
        flag.updated_by = self._current_account()
        flag.save()

        out = serializers.DiscordanceFlagSerializer(flag)
        return Response(out.data)
    
    def retrieve(self, request, pk=None):
        flag = models.DiscordanceFlag.objects.get(pk=pk)
        out = serializers.DiscordanceFlagSerializer(flag)
        return Response(out.data)


class PrescriptionViewSet(AuditMixin, viewsets.ViewSet):
    """POST/GET /patients/{id}/prescriptions — 유방외과 처방.

    매트릭스의 prescription 행(SURGERY: CR, RECEPTION: R)이 그대로 갈라
    준다 — 생성은 유방외과만, 조회는 유방외과 + 원무(서류 발급 화면)다.
    MatrixPermission 하나로 충분해서 별도 IsRole 을 안 쓴다.
    """

    resource = "prescription"
    permission_classes = [MatrixPermission]

    def _get_patient(self, pk):
        try:
            return models.Patient.objects.get(pk=pk)
        except models.Patient.DoesNotExist:
            raise ApiError("NOT_FOUND")

    def list(self, request, pk=None):
        patient = self._get_patient(pk)
        qs = patient.prescriptions.order_by("-prescribed_at", "-created_at")
        out = serializers.PrescriptionSerializer(qs, many=True)
        return Response(out.data)

    def create(self, request, pk=None):
        patient = self._get_patient(pk)
        serializer = serializers.PrescriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        exam_order = None
        report = None
        if data.get("exam_order_id") is not None:
            try:
                exam_order = models.ExamOrder.objects.get(pk=data["exam_order_id"])
            except models.ExamOrder.DoesNotExist:
                raise ApiError("VALIDATION_ERROR", "존재하지 않는 검사 오더입니다.")
            if exam_order.patient_id != patient.pk:
                raise ApiError("VALIDATION_ERROR", "다른 환자의 검사 오더입니다.")
        else:
            try:
                report = models.Report.objects.get(pk=data["report_id"])
            except models.Report.DoesNotExist:
                raise ApiError("VALIDATION_ERROR", "존재하지 않는 리포트입니다.")
            if report.patient_id != patient.pk:
                raise ApiError("VALIDATION_ERROR", "다른 환자의 리포트입니다.")

        # content 안의 약을 **행으로도 펼 수 있는지** 먼저 본다. 통과하지
        # 못하면 처방 자체를 거절한다 — 행이 안 생기면 환자 앱에 회차를 걸
        # 열쇠가 없어(medication_log 가 약을 가리킨다) 약이 보여도
        # 「먹었다」를 못 누른다. 약이 없는 content 는 그대로 통과한다.
        rows = serializers.drug_rows(data.get("content"))

        account = self._current_account()
        # 처방과 약을 한 덩어리로 넣는다. 중간에 터져서 약 행 없는 처방이
        # 남으면 환자 화면에 빈 카드가 뜬다.
        with transaction.atomic():
            prescription = models.Prescription.objects.create(
                patient=patient,
                exam_order=exam_order,
                report=report,
                content=data.get("content"),
                prescribed_by=account,
                prescribed_at=timezone.now(),
                created_by=account,
                updated_by=account,
            )
            # content 는 의사가 보낸 것 **그대로의 원본**으로 남는다. 아래
            # 행은 그것을 지우는 것이 아니라, 환자 앱이 회차를 걸 수 있게
            # 같은 내용을 열쇠 있는 모양으로 한 벌 더 펴 두는 것이다.
            # 자세한 것은 core/models.py 의 PrescriptionDrug 머리말 참고.
            models.PrescriptionDrug.objects.bulk_create([
                models.PrescriptionDrug(
                    prescription=prescription,
                    name=row["name"],
                    ingredient=row.get("ingredient") or None,
                    dose=row["dose"],
                    times=row["times"],
                    days=row["days"],
                    purpose=row.get("purpose") or None,
                    how=row.get("how") or None,
                    watch=row.get("watch") or None,
                ) for row in rows])

        out = serializers.PrescriptionSerializer(prescription)
        return Response(out.data, status=status.HTTP_201_CREATED)
