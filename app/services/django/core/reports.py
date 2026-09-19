"""판독 결과 → 검사 리포트 발급 → AI 소견문 요청.

    판독 완료 ─▶ report 행(stage · locked) ─▶ 소견문 태스크 ─▶ Go ─▶ 리포트 서버
                                                                      │
                            report.narrative_text ◀─ 소견문 저장 콜백 ◀┘

의사는 이 글과 판독값을 같이 보고 판정을 넣는다. 그래서 판독 확정이 아니라
**판독 직후**에 만든다 — 확정 때 만들면 의사가 볼 것이 없다.

환자에게는 안 보인다. report.lock_status 기본값이 locked 이고, 유방외과가
대면 설명을 마치고 잠금을 풀어야 환자 앱에 뜬다(views/surgery.py 의 unlock).

규칙을 views/radiology.py 가 아니라 여기 두는 이유 — 그 파일은 여러 사람이
동시에 고쳐서 충돌이 잦다.
"""
import logging 

from . import models 
from .tasks import SOCKET, request_narrative 

logger = logging.getLogger(__name__)


def issue_stage_report(ai) :
    """판독 한 건에 대한 검사 리포트를 세우고 소견문을 맡긴다.

    파라미터
        ai  판독을 마친 ai_result 행

    돌려주는 값
        report 행
    """
    # 병리는 study 칸이 비어 있다. 검체 → 병변 → 검사로 닿는다 —
    # 병변은 영상이 만들고 검체가 거기 매달리므로 이 길은 늘 있다.
    modality = ai.study.modality if ai.study_id else "pathology"
    study_id = ai.study_id or ai.specimen.lesion.study_id
    socket_id = SOCKET[modality]
    
    # 한 검사에 검사 리포트가 여럿일 수 있다 — 초음파 판독과 그 병변의
    # 조직검사가 같은 검사에 붙는다. 소켓이 그 둘을 가른다.
    # 판독을 다시 돌려도 행은 그대로 두고 소견문만 새로 덮는다.
    report, created = models.Report.objects.get_or_create(
        study_id = study_id, 
        report_type="stage", 
        socket_id=socket_id,
        specimen_id=ai.specimen_id, 
        defaults={"patient_id": ai.patient_id, "audience": "clinician"}
    )
    
    request_narrative.delay(report.pk, ai.pk)
    logger.info("[report] 검사 리포트 %s (%s) study=%s 소켓 %s 소견문 요청", 
                report.pk, "신규" if created else "기존", study_id, socket_id)
    return report 
    
    
def issue_final_report(patient_id, ai_ids, staff=None) :
    """고른 판독들을 묶어 종합 소견서 두 벌(의사용·환자용)을 세운다.

    검사 리포트와 달리 study 가 비어 있다 — 여러 검사를 가로지르기 때문이다.
    무엇을 묶었는지는 content_json 에 남긴다. Report 에서 AiResult 로 가는 FK 가
    없어서 이 목록이 유일한 기록이고, 소견문을 다시 맡길 때도 여기서 읽는다.
    """
    out = []
    for audience in ("clinician", "patient") :
        report = models.Report.objects.create(
            patient_id=patient_id, 
            report_type="final",
            socket_id="7",
            audience=audience, 
            issued_by=staff, 
            content_json={"source_ai_ids": list(ai_ids)},
        )
        request_narrative.delay(report.pk)
        out.append(report)
    
    logger.info("[report] 종합 소견서 %s 환자 %s 판독 %s", [r.pk for r in out], patient_id, list(ai_ids))
    return out 