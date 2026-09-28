"""영상 최종 판정과 병리 확진의 자동 대조.

병리가 확진을 확정하는 순간(§3 PATCH /specimens/{id}/finalize) 같은 환자의
**영상 최종 판정**과 견주어, 두 판정이 엇갈리면 `DiscordanceFlag` 를 세운다.
유방외과 「검사 종합」 화면의 배너가 그 플래그를 읽는다.

── 규칙은 둘뿐이다 ──────────────────────────────────────────────
  영상이 의심인데 병리가 정상·양성   → 위양성 검토 (rule1)
  영상이 저위험인데 병리가 악성      → 위음성 검토 (rule2)

**B3(불확정) · B4(의심) 는 규칙 밖이다.** 어느 쪽과 만나도 세우지 않는다 —
둘 다 재검·추가 조직검사 대상이라 「불일치」로 단정할 근거가 없다.
BI-RADS 0(추가검사 필요) · 6(조직학적 확진됨) 도 같은 이유로 뺀다.

⚠ **규칙을 세 개로 늘리지 마라.** 4a/4b/4c 세분, 밀도, MRI 부피 같은 것을
  넣기 시작하면 이 표가 임상 지침이 되어 버린다. 그건 규칙표 버전을 올리고
  따로 논의할 일이다.

⚠ **여기서 예외를 던지지 않는다.** 병리 확정은 이미 끝난 일이고, 대조가
  안 된다고 해서 그 확정을 되돌릴 수는 없다. 못 하면 로그만 남긴다.
"""

import logging

from django.db import transaction
from django.utils import timezone

from .. import models
from . import birads as birads_rules

logger = logging.getLogger(__name__)

# 규칙표 버전. 규칙을 고치면 이 값을 올린다 — 플래그마다 어느 판으로
# 세워졌는지 남아야 나중에 「그때는 왜 안 걸렸나」를 답할 수 있다.
RULE_TABLE_VERSION = "disc-v1"

# ── 값 집합 ────────────────────────────────────────────────────
# ⚠ 저장된 실제 표현 그대로다. models.py:56 · :77 참고 — 둘 다 **소문자
#   문자열**이고, B 카테고리에 b5a · b5b 세분은 **없다**.
BENIGN = frozenset({"b1", "b2"})            # 정상 · 양성
MALIGNANT = frozenset({"b5"})               # 악성
# 영상 의심. MRI 는 4 를 세분하지 않아 세분 없는 "4" 도 여기 든다 —
# 맘모 · 초음파의 4a~4c 와 같이 본다(services/birads.py). 규칙을 늘린 게
# 아니라 같은 「의심」을 MRI 표기로 받는 것이라 규칙표 버전은 그대로 둔다.
SUSPICIOUS_IMAGING = birads_rules.SUSPICIOUS              # 4 · 4a · 4b · 4c · 5
LOW_RISK_IMAGING = frozenset({"1", "2", "3"})             # 영상 저위험

# ── 규칙표 ─────────────────────────────────────────────────────
# (영상 집합, 병리 집합) → (violated_rule 코드, 사람이 읽는 사유 틀)
#
# ⚠ violated_rule 은 CharField(max_length=20, choices=VIOLATED_RULE) 다
#   (models.py:821). 문장이 안 들어간다 — 코드만 넣고, 사람이 읽는 문장은
#   review_note(250자) 에 적는다.
RULES = (
    (SUSPICIOUS_IMAGING, BENIGN, "rule1",
     "영상 의심(BI-RADS {birads}) · 병리 {b} — 위양성 검토"),
    (LOW_RISK_IMAGING, MALIGNANT, "rule2",
     "영상 저위험(BI-RADS {birads}) · 병리 {b} — 위음성 검토"),
)


def describe(flag):
    """플래그 한 건을 사람이 읽는 한 줄로. 화면이 이 문장을 띄운다.

    ⚠ 직렬라이저가 쓴다 — `violated_rule` 을 그대로 내보내면 화면에
      「rule1」이 뜬다.
    """
    return flag.review_note or dict(
        rule1="영상과 병리가 엇갈립니다 — 위양성 검토",
        rule2="영상과 병리가 엇갈립니다 — 위음성 검토",
    ).get(flag.violated_rule, "영상과 병리가 엇갈립니다")


def _latest_final_assessment(patient):
    """이 환자의 **가장 최근 최종 영상 판정** 하나.

    ⚠ 모달리티(맘모·초음파·MRI) 우선순위를 정한 문서가 없다. 그래서
      **가장 최근 final 하나**로 간다 — 규칙이 생기면 여기만 고치면 된다.
    ⚠ 등급이 비어 있는 행은 거른다. 기권·평가 불가가 그렇게 남는다.
    """
    return (models.Assessment.objects
            .filter(study__patient=patient, read_stage="final")
            .exclude(category__isnull=True)
            .exclude(category="")
            .order_by("-finalized_at", "-created_at")
            .first())


def evaluate(patient, specimen):
    """병리 확진 한 건을 영상 최종 판정과 견준다.

    엇갈리면 `DiscordanceFlag` 를 만들어 돌려주고, 아니면 `None`.

    ⚠ **세우지 않는 경우가 넷이다.** 넷 다 정상이고 로그만 남긴다 —
      ① 영상 최종 판정이 없다  ② 규칙표에 안 걸린다(B3·B4·BI-RADS 0·6)
      ③ 이미 열린 플래그가 있다  ④ 병리 등급이 비어 있다
    """
    b_category = (specimen.b_category or "").lower()
    if not b_category:
        logger.info("[discordance] 검체 %s 병리 등급이 비어 있다", specimen.pk)
        return None

    assessment = _latest_final_assessment(patient)
    if assessment is None:
        logger.info("[discordance] 환자 %s 영상 최종 판정이 없다 — 대조 건너뜀",
                    patient.pk)
        return None

    birads = (assessment.category or "").lower()

    for imaging_set, pathology_set, rule_code, template in RULES:
        if birads in imaging_set and b_category in pathology_set:
            break
    else:
        logger.info("[discordance] 환자 %s 영상 %s · 병리 %s — 규칙 밖",
                    patient.pk, birads, b_category)
        return None

    # ── 중복 방지 ──────────────────────────────────────────────
    # 같은 검체로 이미 열린(닫히지 않은) 플래그가 있으면 새로 만들지 않는다.
    # 병리를 다시 확정해도 플래그가 둘이 되면 안 된다.
    # ⚠ 「열림」은 상태값이 아니라 closed_at IS NULL 이다 — 목록 API 와
    #   잠금 해제 조건이 그렇게 센다(views/surgery.py:226 · :468).
    if models.DiscordanceFlag.objects.filter(
            specimen=specimen, closed_at__isnull=True).exists():
        logger.info("[discordance] 검체 %s 이미 열린 플래그가 있다", specimen.pk)
        return None

    # BI-RADS 세분류는 소문자(4b) — 화면 용어와 같게. B 분류는 대문자(B2)가 표기다
    note = template.format(birads=birads.lower(), b=b_category.upper())

    flag = models.DiscordanceFlag.objects.create(
        # ⚠ **lesion 을 반드시 채운다.** 목록 API 가 lesion__patient 로
        #   거르고(surgery.py:466) 잠금 해제 조건도 그렇게 센다(:226).
        #   specimen 만 채우면 환자로 못 찾는다.
        lesion=specimen.lesion,
        specimen=specimen,
        assessment=assessment,
        violated_rule=rule_code,
        # FLAG_STATUS 에 「open」이 없다(models.py:87). 검토 필요는 review 고,
        # 열려 있다는 것은 closed_at 이 비어 있다는 뜻이다.
        flag_status="review",
        rule_table_version=RULE_TABLE_VERSION,
        flagged_at=timezone.now(),
        review_note=note,
    )
    logger.info("[discordance] 환자 %s 플래그 %s 생성 — %s",
                patient.pk, flag.pk, note)
    _notify(patient, flag, note)
    return flag


def _notify(patient, flag, note):
    """유방외과 주치의에게 한 번. **환자 앱에는 보내지 않는다.**

    ⚠ 주치의가 아직 없으면 보낼 곳이 없다 — 조용히 건너뛴다. 알림이 없다고
      플래그를 안 세우는 것은 아니다.
    """
    staff = patient.primary_staff
    if staff is None:
        logger.info("[discordance] 환자 %s 주치의가 없어 알림을 건너뜀", patient.pk)
        return

    from .. import notify
    notify.send(
        staff=staff,
        type="discordance",
        message=note,
        ref_type="discordance_flag",
        ref_id=flag.pk,
        severity="sev1",
    )


def evaluate_on_commit(patient, specimen):
    """병리 확정이 **커밋된 뒤** 대조한다.

    ⚠ 같은 트랜잭션 안에서 돌리면, 확정이 뒤에 실패해 되돌려질 때 플래그만
      남는다. Celery 로 빼지 않는 이유는 반대다 — 시연에서 확정하자마자
      유방외과 화면에 떠야 한다.
    """
    def run():
        try:
            evaluate(patient, specimen)
        except Exception:
            # 대조가 깨져도 병리 확정은 이미 끝난 일이다. 삼키고 남긴다.
            logger.exception("[discordance] 검체 %s 대조 실패", specimen.pk)

    transaction.on_commit(run)
