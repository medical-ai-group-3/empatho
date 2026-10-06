"""환자 앱 복약 관리 view.

    GET    /me/prescriptions
    POST   /me/medications/{drug_id}/log        {time}
    DELETE /me/medications/{drug_id}/log/{log_id}

의사 쪽(POST·GET /patients/{id}/prescriptions)은 views/surgery.py 의
PrescriptionViewSet 이 이미 맡고 있다. 여기는 그것이 남긴 것을 환자가 보고
「먹었다」를 적는 자리다.

── 잠금을 따르지 않는다 ─────────────────────────────────────────────

⚠ 리포트의 lock_status 를 보지 않는다 (2026-09-21 팀 결정). 약은 오늘부터
  먹어야 하는 것이라 대면 설명 날짜까지 묶어 두면 복약이 그만큼 늦어진다.
  잠금이 막으려던 것은 「설명 전에 결과를 먼저 읽는 것」인데 처방에는
  소견이 실리지 않는다 — 그래서 처방에 소견 문장을 싣지 말 것.

── 복용 시각은 서버가 찍는다 ────────────────────────────────────────

앱은 **어느 회차인지**(time)만 보낸다. 기기 시계가 틀어진 만큼 기록이
어긋나면 안 되는 자료다 — 나중에 「언제 드셨나요」를 되짚을 때 taken_at 이
유일한 근거다.
"""

from django.db import IntegrityError
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.response import Response

from .. import models, serializers
from core.api.errors import ApiError
from core.api.permissions import MatrixPermission


def patient_of(request):
    """요청한 사람의 환자 행. 환자 계정이 아니면 막는다."""
    patient = getattr(request.user, "patient", None)
    if patient is None:
        raise ApiError("ROLE_FORBIDDEN",
                       details={"reason": "환자 계정이 아닙니다."})
    return patient


class MyPrescriptionView(viewsets.ViewSet):
    """GET /me/prescriptions"""

    resource = "prescription"
    permission_classes = [MatrixPermission]

    #: 화면 맨 아래 한 줄. 서버가 보내는 이유는 문구가 바뀔 때 앱 배포를
    #: 기다리지 않으려는 것이다 — 챗봇의 DISCLAIMER 와 같은 자리다.
    NOTE = ("처방 내용은 병원 기록을 그대로 옮긴 것입니다. "
            "복용 중 궁금한 점은 담당 주치의나 접수처에 문의해 주세요.")

    def list(self, request):
        patient = patient_of(request)
        today = timezone.localdate()

        qs = (models.Prescription.objects
              .filter(patient=patient)
              # prescribed_by 는 Account 이고 이름은 그 아래 staff 에 있다.
              .select_related("prescribed_by__staff")
              # 약과 **오늘 기록만** 미리 읽는다. 기록 전부를 끌어오면
              # 몇 달 치가 따라온다 — 화면이 쓰는 것은 오늘 것뿐이다.
              .prefetch_related(
                  "drugs",
                  Prefetch(
                      "drugs__logs",
                      queryset=models.MedicationLog.objects.filter(taken_on=today)))
              .order_by("-prescribed_at", "-created_at"))

        out = serializers.PatientPrescriptionSerializer(
            qs, many=True, context={"today": today})
        return Response({"items": out.data, "note": self.NOTE})


class MedicationLogView(viewsets.ViewSet):
    """POST /me/medications/{drug_id}/log · DELETE …/log/{log_id}"""

    resource = "medication_log"
    permission_classes = [MatrixPermission]

    def _my_drug(self, request, drug_id):
        """내 처방의 약인가. 아니면 404 다.

        ⚠ 「남의 약이다」와 「없는 약이다」를 **구분해서 알리지 않는다.**
          403 으로 갈라 주면 drug_id 를 훑어 남이 무슨 약을 먹는지 셀 수 있다.
        """
        patient = patient_of(request)
        drug = (models.PrescriptionDrug.objects
                .select_related("prescription")
                .filter(pk=drug_id, prescription__patient=patient)
                .first())
        if drug is None:
            raise ApiError("NOT_FOUND", "처방에 없는 약입니다.")
        return patient, drug

    def create(self, request, drug_id=None):
        patient, drug = self._my_drug(request, drug_id)

        slot = (request.data.get("time") or "").strip()
        # 처방에 없는 회차는 받지 않는다. 받아 두면 화면에 그릴 자리가 없어
        # 「기록했다는데 안 보인다」가 된다.
        if slot not in (drug.times or []):
            raise ApiError("VALIDATION_ERROR",
                           "처방에 없는 복용 시간입니다.",
                           details={"time": slot, "expected": drug.times})

        try:
            log = models.MedicationLog.objects.create(
                drug=drug, patient=patient, slot_time=slot,
                taken_on=timezone.localdate())
        except IntegrityError:
            # UNIQUE 제약에 걸렸다 — 두 번 눌린 것이다. 화면은 이미 채워져
            # 있으므로 되돌릴 것이 없고, 코드만 알려 준다.
            raise ApiError("MEDICATION_ALREADY_LOGGED")

        return Response({"log_id": log.log_id, "taken_at": log.taken_at},
                        status=status.HTTP_201_CREATED)

    def destroy(self, request, drug_id=None, log_id=None):
        _, drug = self._my_drug(request, drug_id)
        deleted, _ = models.MedicationLog.objects.filter(
            pk=log_id, drug=drug).delete()
        if not deleted:
            raise ApiError("NOT_FOUND", "취소할 복용 기록이 없습니다.")
        return Response(status=status.HTTP_204_NO_CONTENT)
