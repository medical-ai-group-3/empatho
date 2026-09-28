"""환자 앱 복약 관리 직렬화 — 처방을 환자가 보는 모양으로.

의사 쪽(POST /patients/{id}/prescriptions)은 serializers/surgery.py 의
PrescriptionCreateSerializer 가 이미 맡고 있다. 여기 있는 것은 두 가지다.

    PrescriptionDrugRowSerializer   content.drugs 한 줄을 행으로 펴기 전 검증
    PatientPrescriptionSerializer   환자 화면(Meds.jsx)이 그리는 모양

의사 쪽과 한 직렬화기로 묶지 않는다. 환자 쪽에는 오늘 회차와 복용 여부가
붙는데, 한 벌로 두면 의사 화면을 그릴 때마다 환자의 복약 기록을 읽게 된다.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from .. import models


# ── content.drugs 를 행으로 펴기 전 ──────────────────────────────────────
class PrescriptionDrugRowSerializer(serializers.Serializer):
    """처방 한 줄. Decision.jsx 의 입력칸과 1:1 이다.

    Prescription.content 는 의사가 보낸 것 **그대로의 원본**으로 남는다.
    이 검증은 그 안의 drugs 를 PrescriptionDrug 행으로도 펼 수 있는지 보는
    것이고, 통과하지 못하면 처방 자체를 거절한다 — 행이 안 생기면 환자 앱에
    회차를 걸 열쇠가 없어 약이 보여도 「먹었다」를 못 누른다.
    """

    name = serializers.CharField(max_length=200)
    ingredient = serializers.CharField(max_length=200, required=False,
                                       allow_blank=True, default="")
    dose = serializers.CharField(max_length=50)
    # 투여 경로 · 제형. 09-28 에 붙었다 — **둘 다 없어도 받는다.** 그 전의
    # 화면이 보내던 처방이 갑자기 400 이 되면 안 된다.
    # ⚠ route 는 목록 밖 값을 거절한다. 자유 문자열로 받으면 "경구" · "PO" ·
    #   "oral" 이 섞여 들어와 화면이 경로로 가를 수 없게 된다.
    route = serializers.ChoiceField(choices=models.as_choices(models.DRUG_ROUTE),
                                    required=False, allow_blank=True,
                                    allow_null=True, default=None)
    form = serializers.CharField(max_length=50, required=False, allow_blank=True,
                                 allow_null=True, default=None)
    # ["09:00", "19:00"]. 화면이 쉼표로 나눠 보낸다.
    times = serializers.ListField(child=serializers.CharField(max_length=5),
                                  allow_empty=False)
    days = serializers.IntegerField(min_value=1)
    purpose = serializers.CharField(max_length=250, required=False,
                                    allow_blank=True, default="")
    how = serializers.CharField(required=False, allow_blank=True, default="")
    watch = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_times(self, value):
        """회차는 **HH:MM 이라야 한다.**

        자유 문자열로 두면 "아침" 과 "09:00" 이 섞여 들어오는데, 복약 기록이
        이 값을 열쇠로 쓴다(medication_log.slot_time). 한번 섞이면 같은
        회차인지 판정할 길이 없다.

        중복도 막는다 — 같은 시각이 두 줄이면 화면에 회차가 두 개 뜨고
        UNIQUE 제약이 둘째를 거절한다.
        """
        seen = []
        for raw in value:
            t = raw.strip()
            parts = t.split(":")
            if len(parts) != 2 or not all(p.isdigit() for p in parts) \
                    or len(parts[0]) != 2 or len(parts[1]) != 2 \
                    or not (0 <= int(parts[0]) <= 23) or not (0 <= int(parts[1]) <= 59):
                raise serializers.ValidationError(
                    "복용 시간은 09:00 처럼 적어 주세요: %r" % raw)
            if t in seen:
                raise serializers.ValidationError("복용 시간이 겹칩니다: %s" % t)
            seen.append(t)
        return seen


def drug_rows(content):
    """content 에서 약 줄을 꺼내 검증한다. 없으면 빈 목록.

    ⚠ drugs 가 없는 content 도 받는다. 팀원분 API 는 content 를 자유
      jsonb 로 열어 두었고(required=False), 처방이 아닌 다른 것이 들어올
      수 있다. 약이 없으면 행을 안 만들 뿐 처방 저장은 그대로 된다 —
      여기서 막으면 기존에 돌던 호출이 갑자기 400 이 된다.
    """
    rows = (content or {}).get("drugs") if isinstance(content, dict) else None
    if not rows:
        return []
    ser = PrescriptionDrugRowSerializer(data=rows, many=True)
    ser.is_valid(raise_exception=True)
    return ser.validated_data


# ── 환자가 보는 것 ───────────────────────────────────────────────────────
class PatientDrugSerializer(serializers.ModelSerializer):
    """환자 화면의 약 한 줄. Meds.jsx 가 읽는 칸 이름 그대로다."""

    # 하루 몇 회인가. 표에 칸을 두지 않고 times 에서 센다 —
    # 두 칸을 두면 어긋날 수 있고, 어긋나면 어느 쪽이 맞는지 모른다.
    per_day = serializers.SerializerMethodField()
    today = serializers.SerializerMethodField()
    # 이 약이 끝나는 날. 약마다 일수가 달라(2026-09-21 팀 결정) 화면이
    # 처방 단위로 계산할 수가 없다. 서버가 세어서 준다 — 기기 시계가
    # 틀어진 만큼 「오늘 끝났다」가 어긋나면 안 되는 값이다.
    ends_on = serializers.SerializerMethodField()

    class Meta:
        model = models.PrescriptionDrug
        fields = ["drug_id", "name", "ingredient", "dose", "route", "form",
                  "times", "per_day",
                  "days", "ends_on", "purpose", "how", "watch", "today"]

    def get_per_day(self, obj):
        return len(obj.times or [])

    def get_ends_on(self, obj):
        return (issued_on(obj.prescription)
                + timedelta(days=obj.days - 1)).isoformat()

    def get_today(self, obj):
        """오늘 먹어야 하는 회차와, 각 회차의 복용 기록.

        ⚠ **끝난 약에는 회차를 내지 않는다.** 빈 목록이면 화면이 회차
          단추를 아예 안 그린다(Meds.jsx 가 `today.length > 0` 로 가른다).
          끝난 약에 단추를 남기면 환자가 안 먹어도 될 약을 계속 누른다.
        """
        today = self.context.get("today") or timezone.localdate()
        start = issued_on(obj.prescription)
        if today < start or today > start + timedelta(days=obj.days - 1):
            return []

        # 오늘 것만 꺼낸다. 뷰가 Prefetch 로 이미 읽어 둔 것을 쓴다 —
        # 여기서 다시 질의하면 약 개수만큼 질의가 난다.
        logs = {log.slot_time: log.log_id
                for log in obj.logs.all() if log.taken_on == today}
        return [{"time": t, "log_id": logs.get(t)} for t in (obj.times or [])]


def issued_on(rx):
    """처방일(날짜).

    ⚠ 팀원분 Prescription 에는 prescribed_at(일시)만 있고 날짜 칸이 없다.
      칸을 더하지 않고 여기서 뽑는다 — 남의 표에 칸을 늘리면 그쪽
      마이그레이션과 엮인다.

      **localtime 을 거쳐 뽑는다.** UTC 로 그냥 .date() 하면 밤 9시 이후에
      처방한 것이 전날로 적히고, 그 하루만큼 복용 기간이 앞당겨진다.
    """
    at = rx.prescribed_at or rx.created_at
    return timezone.localtime(at).date() if at else timezone.localdate()


class PatientPrescriptionSerializer(serializers.ModelSerializer):
    """환자 화면의 처방전 한 장."""

    drugs = PatientDrugSerializer(many=True, read_only=True)
    prescription_id = serializers.IntegerField(read_only=True)
    issued_on = serializers.SerializerMethodField()
    prescriber = serializers.SerializerMethodField()
    dept = serializers.SerializerMethodField()
    hospital = serializers.SerializerMethodField()
    # 처방 단위의 「며칠분」. 약마다 일수가 달라서 **가장 긴 약**으로 적는다.
    # 화면 머리말의 한 줄이고, 실제 기간 판정은 약의 ends_on 이 한다.
    days = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = models.Prescription
        fields = ["prescription_id", "issued_on", "prescriber", "dept",
                  "hospital", "days", "status", "note", "drugs"]

    # 팀원분 표에 없는 칸이다. 화면이 d.note 를 그리므로 자리는 내주되
    # 처방마다 다른 말을 넣을 곳은 아직 없다 — 목록 전체의 한 줄은 뷰가 준다.
    note = serializers.SerializerMethodField()

    def get_note(self, obj):
        return None

    def get_issued_on(self, obj):
        return issued_on(obj).isoformat()

    def get_prescriber(self, obj):
        """처방한 사람의 이름.

        ⚠ 팀원분 표의 prescribed_by 는 Staff 가 아니라 **Account** 다
          (다른 표들과 다르다). 이름은 account.staff.full_name 에 있다.
          비어 있을 수 있어 기본 문구를 둔다 — 「 · 유방외과」처럼 앞이
          비어 시작하면 자료가 깨진 것처럼 보인다.
        """
        staff = getattr(obj.prescribed_by, "staff", None)
        return getattr(staff, "full_name", None) or "담당 의료진"

    def get_dept(self, obj):
        # v10 의 staff 에는 부서 칸이 없다(역할이 곧 부서다). 처방은 유방외과
        # 단독이라 고정해도 틀리지 않는다 — 다른 과가 처방하게 되면 여기부터
        # 고칠 것.
        return "유방외과"

    def get_hospital(self, obj):
        # 단일 병원 운영이라 표가 없다. 화면이 칸을 비워 두지 않게 채워 준다.
        return None

    def get_days(self, obj):
        return max((d.days for d in obj.drugs.all()), default=0)

    def get_status(self, obj):
        """active · ended.

        ⚠ 팀원분 표에 상태 칸이 없다. **칸을 더하지 않고 날짜로 센다** —
          가장 긴 약이 끝났으면 끝난 처방이다. 상태 칸을 더하면 그 칸과
          날짜가 어긋날 수 있고, 어긋나면 어느 쪽이 맞는지 아무도 모른다.
        """
        today = self.context.get("today") or timezone.localdate()
        last = max((d.days for d in obj.drugs.all()), default=0)
        if not last:
            return "ended"
        end = issued_on(obj) + timedelta(days=last - 1)
        return "ended" if today > end else "active"
