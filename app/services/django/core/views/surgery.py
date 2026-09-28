"""유방외과(surgery) view — 2026-09-14 화면명세 기준."""

import re

from rest_framework import viewsets, status, generics
from rest_framework.response import Response

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .. import models, serializers, viewed
from ..mixins import AuditMixin
from core.api.permissions import MatrixPermission, OwnedOnlyMixin, CanDisposeDiscordance
from core.api.errors import ApiError
from core.api.permissions import CanBindSpecimen, CanDecideAssessment, CanUnlockReport, CanIssueFinalReport
from core.api.permissions import IsRole, SURGERY
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

        # ⚠ 줄마다 **무엇의 몇 번인지**를 같이 싣는다. 전에는 {at, type,
        #   detail} 뿐이라 화면이 줄을 눌러도 무엇을 열지 몰랐고, 그래서
        #   누르는 자리로 만들지 못했다(empatho-view/hospital/screens/
        #   Patient.jsx 윗 주석). 번호가 있으면 판독·검체 화면으로 보낸다.
        events = []
        for study in models.Study.objects.filter(patient=patient):
            if study.performed_at:
                events.append({"at": study.performed_at, "type": "촬영",
                               "detail": study.modality, "study_id": study.study_id,
                               "modality": study.modality})

        for ai in models.AiResult.objects.filter(patient=patient):
            if ai.analyzed_at:
                events.append({"at": ai.analyzed_at, "type": "AI 분석 완료", "detail": None,
                               "study_id": ai.study_id, "specimen_id": ai.specimen_id})

        # select_related — 아래에서 study.modality 를 읽는다. 없으면 줄마다
        # 검사를 한 번씩 더 부른다.
        for assessment in (models.Assessment.objects
                           .filter(study__patient=patient)
                           .select_related("study")):
            events.append({
                "at": assessment.created_at, "type": "판독", "detail": assessment.category,
                "assessment_id": assessment.assessment_id,
                "study_id": assessment.study_id,
                "modality": assessment.study.modality,
                # 확정 전(draft)도 이 줄로 나온다. 화면이 「확정」이라고
                # 읽지 않도록 단계를 같이 준다.
                "read_stage": assessment.read_stage,
            })

        for specimen in models.Specimen.objects.filter(patient=patient):
            if specimen.collected_at:
                events.append({"at": specimen.collected_at, "type": "검체 채취",
                               "detail": specimen.specimen_label,
                               "specimen_id": specimen.specimen_id})
            if specimen.finalized_at:
                events.append({"at": specimen.finalized_at, "type": "병리 확진",
                               "detail": specimen.diagnosis,
                               "specimen_id": specimen.specimen_id})

        # ── 치료 결정 · 리포트 · 결과 설명 · 처방 (09-28 유방외과 요청) ──────
        #
        # ⚠ **의료진에게만** 싣는다. 이 문은 환자 본인도 연다(위 role 검사).
        #   리포트는 대면 설명 전까지 잠겨 있고(lock_status), 팀 규칙은 「설명
        #   전에 환자가 결과를 먼저 알면 안 된다」이다. 치료 결정(수술 yes 등)
        #   과 리포트 발급 사실만으로도 결과가 새어 나간다 — 「수술 결정」 한
        #   줄이면 소견문을 안 읽어도 다 안다. 환자용 응답은 전과 한 글자도
        #   다르지 않게 둔다. 환자에게 보이려면 잠금 규칙부터 다시 정할 것.
        #   (처방은 환자 앱에 즉시 보이지만 — models.py PrescriptionDrug 위
        #   주석 — 거기는 약만 싣는 화면이다. 여기서는 report_id 로 리포트와
        #   이어 주므로 같이 막는다.)
        if request.user.role != "patient":
            self._staff_events(patient, events)

        # ⚠ at 이 비면 정렬이 None 비교로 터진다. 새 줄들은 만들 때 거른다.
        events.sort(key=lambda e: e["at"])
        return Response(events)

    @staticmethod
    def _staff_events(patient, events):
        # 치료 결정 — 판독 행에 decision_* 로 붙는다(SurgeryDecisionView).
        # decided_at 이 없으면 아직 결정 전이다.
        # ⚠ 백엔드에는 decision_value 의 한글 이름표가 없다(as_choices 가
        #   코드를 그대로 쓴다). 그래서 detail 에 코드를 그대로 싣고, 화면이
        #   decision_type · decision_value 로 이름을 붙인다.
        for a in (models.Assessment.objects
                  .filter(study__patient=patient, decided_at__isnull=False)
                  .only("assessment_id", "study_id", "decided_at",
                        "decision_type", "decision_value")):
            events.append({
                "at": a.decided_at, "type": "치료 결정",
                "detail": a.decision_value,
                "assessment_id": a.assessment_id,
                "study_id": a.study_id,
                "decision_type": a.decision_type,
                "decision_value": a.decision_value,
            })

        # 리포트 발급과 결과 설명. 한 행에서 두 줄이 나온다.
        for r in (models.Report.objects.filter(patient=patient)
                  .only("report_id", "created_at", "report_type", "audience",
                        "explained_at", "explain_method")):
            if r.created_at:
                events.append({"at": r.created_at, "type": "리포트",
                               "detail": r.report_type,
                               "report_id": r.report_id,
                               "report_type": r.report_type,
                               "audience": r.audience})
            if r.explained_at:
                events.append({"at": r.explained_at, "type": "결과 설명",
                               "detail": r.explain_method,
                               "report_id": r.report_id})

        # 처방. 약 개수는 annotate 로 한 번에 센다 — 처방마다 drugs 를 부르면
        # 처방 수만큼 쿼리가 는다.
        # ⚠ prescribed_at 이 비는 처방이 있어 created_at 으로 받친다.
        for p in (models.Prescription.objects.filter(patient=patient)
                  .annotate(drug_count=Count("drugs"))
                  .only("prescription_id", "report_id", "prescribed_at", "created_at")):
            at = p.prescribed_at or p.created_at
            if at is None:
                continue
            events.append({"at": at, "type": "처방",
                           "detail": f"약 {p.drug_count}종" if p.drug_count else None,
                           "prescription_id": p.prescription_id,
                           "report_id": p.report_id})


class SurgeryReportViewSet(AuditMixin, OwnedOnlyMixin, viewsets.ModelViewSet):
    """§2·§3 GET/PUT /reports/{id}, GET /reports?patient=&type=final."""

    resource = "report"
    permission_classes = [MatrixPermission]
    queryset = models.Report.objects.all()
    serializer_class = serializers.ReportSerializer
    http_method_names = ["get", "put", "patch", "head", "options"]

    def list(self, request, *args, **kwargs):
        res = super().list(request, *args, **kwargs)
        # 유방외과가 한 환자의 리포트를 열면(환자 상세 · 치료 방침 · 내 환자)
        # 그 환자 판독 리포트에 열람을 남긴다 — 영상 · 병리 목록의 「유방외과
        # 열람」이 이 값을 읽는다(core/viewed.py). 응답을 만든 뒤에 남긴다
        pid = request.query_params.get("patient")
        if getattr(request.user, "role", None) == "surgery" and pid and str(pid).isdigit():
            viewed.mark(int(pid), getattr(request.user, "staff", None))
        return res

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
        # 환자가 안내문을 열면 그 안내문의 「결과 도착」 알림도 확인된 것이다.
        # 알림을 거치지 않고 홈 카드로 들어와도 「새 안내」가 꺼져야 한다 —
        # 홈은 확인 안 된 알림으로 「새」를 센다(PatientHomeView).
        if getattr(request.user, "role", None) == "patient":
            models.Notification.objects.filter(
                patient=report.patient, ref_type="report", ref_id=report.pk,
                acknowledged_at__isnull=True,
            ).update(acknowledged_at=timezone.now())
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
        # 목록의 「유방외과 열람」 칸 — core/viewed.py
        from django.db.models import F  # 09-28 B1 — 열람순 정렬(빈 칸 뒤로)

        qs = models.Specimen.objects.select_related("patient__pii", "bound_by").annotate(
            viewed_at=viewed.last_seen("specimen"))
        # ?patient= 로 한 환자 것만. 없으면 종전대로 전부 — 검체 접수 화면이
        # 전체 목록을 쓴다. 유방외과·검사 종합은 한 환자만 보면 되는데
        # 지금까지 전부 받아 화면에서 걸렀다(api.js 의 readings).
        patient = request.query_params.get("patient")
        if patient:
            if not str(patient).isdigit():
                raise ApiError("VALIDATION_ERROR", "patient 는 숫자여야 합니다.")
            qs = qs.filter(patient_id=int(patient))
        # 09-28 — 병리 「내 검체」. ?assigned=me · ?finalized=yes|no
        assigned = request.query_params.get("assigned")
        if assigned == "me":
            staff = getattr(request.user, "staff", None)
            qs = qs.filter(assigned_to=staff) if staff is not None else qs.none()
        elif assigned == "none":
            qs = qs.filter(assigned_to__isnull=True)
        elif assigned:
            raise ApiError("VALIDATION_ERROR", "assigned 는 me 또는 none 이어야 합니다.")
        finalized = request.query_params.get("finalized")
        if finalized == "yes":
            qs = qs.filter(finalized_at__isnull=False)
        elif finalized == "no":
            qs = qs.filter(finalized_at__isnull=True)
        elif finalized:
            raise ApiError("VALIDATION_ERROR", "finalized 는 yes 또는 no 여야 합니다.")
        ordering = request.query_params.get("ordering")
        allowed = {
            "patient__name": "patient__pii__name",
            "collected_at": "collected_at",
            "accessioned_at": "accessioned_at",
            "accession_status": "accession_status",
            "finalized_at": "finalized_at",
            # 유방외과 열람순. 검체에 리포트가 여럿이라 조인으로 정렬하면 행이
            # 불어난다 — 위에서 얹은 viewed_at(가장 최근 열람)으로 정렬한다
            "report__last_viewed_at": "viewed_at",
        }
        if ordering and ordering.lstrip("-") in allowed:
            field = allowed[ordering.lstrip("-")]
            expr = (F(field).desc(nulls_last=True) if ordering.startswith("-")
                    else F(field).asc(nulls_last=True))
            qs = qs.order_by(expr, "-specimen_id")
        out = serializers.SpecimenSerializer(qs, many = True)
        return Response(out.data)
    
    def create(self, request):
        serializer = serializers.SpecimenBindSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from ..services import specimen_snapshot  # 09-28 B1

        lesion = models.Lesion.objects.select_related("study", "patient").get(pk=data["lesion_id"])
        specimen = models.Specimen.objects.create(
            lesion_id=data["lesion_id"],
            patient_id=lesion.patient_id,
            specimen_label=data.get("specimen_label") or specimen_label_for(lesion, data["collected_at"]),
            specimen_type=data["specimen_type"],
            guidance_route=data["guidance_route"],
            collected_at=data["collected_at"],
            # 09-28 — 의뢰 문구(선택)와 바인딩 순간의 병변 모습
            clinical_note=data.get("clinical_note") or None,
            target_snapshot=specimen_snapshot.build(lesion),
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

def specimen_label_for(lesion, collected_at):
    """검체 라벨 자동 생성 — S-{채취일}-{환자번호}-{병변} (09-28).

    병변은 병변 이름(MRI-1 · US-1 · 맘모 모델 id)을 쓰고, 이름이 없는 옛
    병변은 모달리티-순번, 그것도 없으면 L{병변번호}. 같은 날 같은 병변에서
    두 번 채취하면 -2, -3 을 붙인다.
    ponytail: 동시에 같은 라벨을 두 번 만들면 UK 가 IntegrityError 로 막는다(재시도 없음)
    """
    part = lesion.label or (
        f"{lesion.modality.upper()}-{lesion.lesion_index + 1}"
        if lesion.modality and lesion.lesion_index is not None else f"L{lesion.pk}")
    part = re.sub(r"[^A-Za-z0-9-]", "", part)[:16] or f"L{lesion.pk}"
    base = f"S-{timezone.localtime(collected_at):%Y%m%d}-{lesion.patient.patient_number}-{part}"[:46]
    label, n = base, 2
    while models.Specimen.objects.filter(specimen_label=label).exists():
        label, n = f"{base}-{n}", n + 1
    return label


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
        # 09-28 — ?primary_staff=me | <직원 번호> — 내 환자 것만. 환자는 병변으로
        # 찾고(플래그에 환자 칸이 없다), 병변이 빈 플래그는 검체로 받친다.
        primary_staff = self.request.query_params.get("primary_staff")
        if primary_staff:
            if primary_staff == "me":
                staff = getattr(self.request.user, "staff", None)
                if staff is None:
                    return qs.none()
                staff_id = staff.pk
            elif primary_staff.isdigit():
                staff_id = int(primary_staff)
            else:
                raise ApiError("VALIDATION_ERROR", "primary_staff 는 me 또는 직원 번호여야 합니다.")
            qs = qs.filter(Q(lesion__patient__primary_staff_id=staff_id)
                           | Q(lesion__isnull=True,
                               specimen__patient__primary_staff_id=staff_id))
        if status_param == "open":
            qs = qs.filter(closed_at__isnull=True)
        # ⚠ 순서를 못 박는다 — 부르는 쪽이 맨 앞 하나를 골라 「처분하기」를
        #   건다(api.js 의 open_discordance). 안 박으면 어느 건으로 갈지가
        #   요청마다 달라진다. 최근에 걸린 것이 앞이다.
        return qs.order_by("-flagged_at", "-discordance_flag_id")


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
        # 상세는 **펴서** 준다 — 화면이 두 판독을 나란히 놓는 자리다.
        # 얕은 것(FK 번호)만 주면 양쪽이 「아직 없습니다」로 뜬다.
        flag = (models.DiscordanceFlag.objects
                .select_related("lesion__patient__pii",
                                "assessment__assessed_by",
                                "specimen__assigned_to")
                .get(pk=pk))
        out = serializers.DiscordanceDetailSerializer(flag)
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


class SurgeryWorklistView(viewsets.ViewSet):
    """GET /surgery/worklist — 유방외과 워크리스트(한 환자 한 줄 + 다음 할 일).

    ?primary_staff=me(기본) | <직원 번호>   주치의로 거른다
    ?scope=all                              주치의가 유방외과인 환자 전부(과 전체)

    응답 {items: [...], counts: {<next_step>: n, open_discordance: n, total: n}}.
    계산 규칙과 칸의 뜻은 core/surgery_worklist.py 머리말.

    권한 — 매트릭스의 patient 행(유방외과 R)에 유방외과 역할을 하나 더 건다.
    patient R 은 모든 의료진이 가져서 그것만으로는 다른 과에도 열린다.
    """

    resource = "patient"
    permission_classes = [MatrixPermission, IsRole.of(SURGERY)]

    def list(self, request):
        from .. import surgery_worklist
        p = request.query_params
        scope = p.get("scope")
        if scope not in (None, "", "all", "me"):
            raise ApiError("VALIDATION_ERROR", "scope 는 all 이어야 합니다.")
        primary_staff = p.get("primary_staff") or "me"
        if primary_staff != "me" and not primary_staff.isdigit():
            raise ApiError("VALIDATION_ERROR", "primary_staff 는 me 또는 직원 번호여야 합니다.")
        patients = surgery_worklist.patient_scope(
            getattr(request.user, "staff", None), primary_staff=primary_staff,
            scope="all" if scope == "all" else None)
        return Response(surgery_worklist.build(patients))
