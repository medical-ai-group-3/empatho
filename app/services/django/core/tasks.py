"""판독 태스크 — 워커가 이미지를 Go 에서 받아 추론 서버로 보내고 행에 남긴다.

ai_result 한 행이 판독 한 번이다. 어느 파일을 어느 소켓으로 돌리는지는
행이 들고 있다 — 태스크는 행 번호만 받는다.

■ 이 파일이 서 있는 자리

    화면 ─ 판독 요청 ─▶ Django ─ ai_result(queued) ─▶ Redis
                                                        │
                                          Celery 워커 ◀─┘  ← 여기부터 이 파일
                                          │
              Go(file-gateway) ◀─ 티켓 ───┤   원본 받기
              추론 서버(:8001) ◀─ 이미지 ─┤   판독
              Go(file-gateway) ◀─ 메시 ───┤   파생물 올리기 (MRI 만)
                                          └─▶ ai_result 갱신 (결과 · 상태 · 시간)

■ 워커가 저장소에 직접 가지 않는 이유

    파일 바이트는 Go 만 다룬다. 워커도 예외가 아니라 Garage · Orthanc 에 직접
    붙지 않고, Django 가 서명한 티켓을 들고 Go 에서 받는다. 저장소 자격이
    워커에 없으므로 워커가 뚫려도 파일 전체가 열리지 않는다.

■ 워커가 DB 는 직접 쓰는 이유

    DB 는 Django 코드만 쓴다는 규칙이 있고, Celery 워커는 Django 코드다
    (web 과 같은 이미지로 뜬다). 그래서 콜백을 거치지 않고 여기서 바로 쓴다.

■ 실패해도 반드시 행을 갱신한다

    예외가 나면 run_status 를 failed 로 남긴다. 로그만 남기면 행이 queued 인
    채로 남아 화면이 영원히 기다린다 — 실패는 화면에 보여야 하는 정보다.
"""

from datetime import timedelta
import json 
import logging 
import time 
import urllib.request
import uuid 
import base64
import http.client
import urllib.error

from celery import shared_task
from . import notify 
from .api.tickets import issue 
from django.utils import timezone

from . import mesh 
from celery.exceptions import SoftTimeLimitExceeded
from .models import AiResult, ExamOrder, Notification, Report, StorageObject, Lesion, Image
from .services import birads as birads_rules

logger = logging.getLogger(__name__) 

# ── 부를 주소 ────────────────────────────────────────────────────────────
# 둘 다 도커망 안의 이름이라 밖으로 나가지 않는다. nginx 를 거치지 않는다.

# 파일 게이트웨이 주소
#   원본 받기 · 파생물 올리기를 여기로 한다. 워커는 저장소 대신 이 주소만 안다.
GATEWAY = "http://file-gateway:8091"
# 추론 서버로 전송을 하기 위한 터널 주소
#   tunnel 컨테이너가 SSH 로 워크스테이션 127.0.0.1:8001 까지 넘긴다.
#   GPU 는 워크스테이션에만 있어서 판독은 반드시 이 경로를 지난다.
INFERENCE = "http://tunnel:8001"

# 소견문 창구
#   Go 가 리포트 서버(워크스테이션 8002)를 대신 부른다. 글은 응답이 아니라
#   소견문 저장 콜백으로 돌아온다.
LLM_PROXY = "http://llm-proxy:8090"

# 모달리티별 소켓 지정
#   추론 서버는 주소의 소켓 번호로 어느 모델을 쓸지 정한다 — 영상을 열어보고
#   짐작하지 않는다. 그래서 보내는 쪽이 번호를 정확히 정해야 한다.
#   여기 없는 모달리티가 오면 KeyError 가 나고, 아래 try 가 failed 로 남긴다.
SOCKET = {"us": "5", "mammo": "4b", "mri": "3", "pathology": "1"}

# DICOM 은 Orthanc 에만 있다. 맘모는 한 장, MRI 는 시리즈를 zip 으로 받는다.
#   모달리티 → (티켓 범위 종류, 추론 서버에 넘길 파일 이름)
# MRI 소켓은 이름이 .zip 이어야 압축을 푼다.
#
# 여기 있는 모달리티와 없는 모달리티는 받는 경로가 갈린다.
#   있음(맘모 · MRI)   Go 의 dicom 경로 — Orthanc 에서 꺼낸다
#   없음(초음파 · 병리) Go 의 files 경로 — Garage 에서 꺼낸다
DICOM = {"mammo": ("dicom/instances", "image.dcm"), "mri": ("dicom/series", "series.zip")}

# ⑤ celery task로 등록 => core.tasks.run_inference
# 워커는 뜰 때 각 앱의 tasks.py 를 자동으로 찾아 이름을 등록 
@shared_task
# redis로 가는 메세지는 행 번호 하나, 나머지는 DB에서 읽어옴 
def run_inference(ai_result_id) :
    """ai_result 한 행을 판독하고 결과를 그 행에 쓴다.

    행 하나가 판독 한 번이다. 어느 파일을 어느 소켓으로 돌리는지는 행이 들고 있다.
      us · pathology   source_object 의 object_key
      mammo            source_object 의 sop_instance_uid
      mri              source_object 가 비어 있다 — 시리즈 전체를 보므로
                       가리킬 파일 한 장이 없다. 검사의 저장 행에서 시리즈를 찾는다
    병리는 study 가 없고 specimen 에 매달린다. 모달리티를 그렇게 가른다.

    파라미터
        ai_result_id  판독할 ai_result 의 기본키. Redis 메시지에 실려 오는
                      유일한 값이다. 파일 주소 · 모달리티를 메시지에 담지
                      않는 이유는, 담으면 DB 와 메시지 두 곳에 같은 사실이
                      생겨 둘이 어긋날 수 있어서다.

    돌려주는 값
        run_status 문자열("done" · "failed"). Celery 결과 저장소(Redis db1)에
        24시간 남는다. 진짜 기록은 ai_result 행이고 이 반환값은 요약이다.

    안에서 쓰는 이름
        ai        판독할 행. 결과를 여기에 채워 마지막에 한 번 save() 한다
        modality  us · mammo · mri · pathology 넷 중 하나
        socket    추론 서버 주소에 붙일 소켓 번호
        ref       Go 에게 「이것을 달라」고 가리키는 값. 모달리티마다 다르다
        t0        걸린 시간 재기용 시작점. 벽시계가 아니라 단조 시계를 쓴다 —
                  중간에 시스템 시각이 바뀌어도 음수가 나오지 않는다
        out       추론 서버 응답 JSON. 그대로 ai_result.result 에 들어간다

    실패
        어느 단계에서 터지든 행은 failed 로 남고 예외는 밖으로 나가지 않는다.
        Celery 재시도를 쓰지 않는 이유는, 같은 실패가 반복되면 GPU 를 그만큼
        더 점유해서다. 다시 돌릴지는 사람이 정한다.
    """

    # ① 행을 읽어 무엇을 할지 정한다.
    #    study 가 있으면 영상이고 모달리티는 검사에 적혀 있다. 없으면 병리다 —
    #    병리는 검체에 매달리고 검사가 없다(09-16 배포로 그렇게 바뀌었다).
    ai = AiResult.objects.get(pk=ai_result_id)
    modality = ai.study.modality if ai.study_id else "pathology"
    socket = SOCKET[modality]

    # ② 시작했음을 먼저 남긴다. 화면이 queued 와 running 을 구분해 보여준다.
    #    ai 객체 대신 update() 를 쓰는 것은, 아래에서 결과를 채워 save() 할 때
    #    이 두 칸을 다시 쓰지 않기 위해서다 — 같은 값을 두 번 쓰지 않는다.
    AiResult.objects.filter(pk=ai_result_id).update(run_status = "running", requested_socket_id = socket)
    
    logger.info("[run_inference]행 %s modality=%s -> 소켓 %s", ai.pk, modality, socket)
    
    t0 = time.monotonic()
    # 병변 메시는 병변 행이 생긴 뒤에 올린다(_store_lesion_meshes) — 그때까지 든다
    lesion_meshes = []
    
    try :
        # 맘모는 영상 넷이 한 검진이라 장마다 판독하고 합친다.
        # 나머지는 가리키는 것 하나를 그대로 보낸다.
        if modality == "mammo" :
            out = _mammo(ai, socket)
        else :
            out = _analyze(modality, socket, _ref(ai, modality))
            
        # 기권이면 파생물이 없다. 추론 서버는 실패도 200 에 abstained 로
        # 돌려주는 것이 규약이라 그때는 result 칸 자체가 안 온다. 그대로
        # 읽으면 KeyError 로 터지고, 정상 기권이 failed 로 둔갑한다 —
        # 09-19 MRI 가 그랬다(mesh.split 에 out["result"]).
        if out.get("abstained") or "result" not in out :
            logger.info("[run_inference] 행 %s 기권 - %s", ai.pk, out.get("reason"))
            
        # MRI 응답은 대부분이 3D 메시다. 걷어내지 않으면 jsonb 한 칸이 그 크기가 된다.
        elif modality == "mri" :
            out, lesion_meshes = _store_meshes(out, ai)
        
        elif modality in ("pathology", "us") :
            out = _store_mask(out, ai)
            
        # ⑧ 결과를 행에 채운다. 저장은 마지막에 한 번만 한다.
        #    abstained 는 「판독을 못 했다」이고 실패(failed)와 다르다 — 호출은
        #    정상이었고 모델이 판정을 거부한 것이라 done 으로 남긴다.
        ai.result = out
        ai.abstained = bool(out.get("abstained"))
        ai.abstain_reason = out.get("reason") or None
        ai.run_status = "done"
    
    except SoftTimeLimitExceeded :
        # Celery 가 그만 이라고 보낸것 하드 제한이 오기전에 기록 
        logger.error("[run_inference] 행 %s 시간 초과", ai.pk)
        ai.run_status = "failed"
        ai.abstain_reason = "soft_time_limit"
    
    except Exception as e:
        # 실패해도 행에 남긴다. 로그만 남기면 화면이 queue 인채로 멈춘다
        logger.exception("[run_inference] 행 %s 실패", ai.pk)
        ai.run_status = "failed"
        # 칸이 text 다(0013 이전에는 varchar(100) 이었다). 자르면 원인을 못 읽는다.
        ai.abstain_reason = f"{type(e).__name__}: {e}"
        
    # ⑨ 성공 · 실패 어느 쪽이든 시간과 시각을 남기고 한 번 저장한다.
    #    try 안에서 저장하지 않는 이유는, 실패 경로에서도 같은 칸을 채워야
    #    「언제 돌렸고 얼마나 걸렸나」가 남기 때문이다.
    ai.elapsed_sec = round(time.monotonic() - t0, 3)
    ai.analyzed_at = timezone.now()
    # 이 태스크가 채운 칸만 쓴다. 통째로 저장하면 앞에서 update() 로 적어 둔
    # requested_socket_id 가 메모리의 옛 값(None)으로 덮인다.
    # updated_at 은 auto_now 라 목록에 넣어야 갱신된다.
    ai.save(update_fields=[
        "result", "abstained", "abstain_reason", "run_status",
        "elapsed_sec", "analyzed_at", "updated_at"])
    # 판독이 끝났으면 검사 리포트를 세우고 AI 소견문을 맡긴다.
    #
    # 여기서 가져오는 이유 — core.reports 가 맨 위에서 이 모듈의 SOCKET 과
    # request_narrative 를 가져간다. 파일 맨 위에서 서로를 부르면 둘 다
    # 반쯤 올라간 상태에서 만나 ImportError 가 난다.
    #
    # 소견문이 실패해도 판독 결과는 이미 저장됐다. 그래서 여기서 터져도
    # 행을 failed 로 되돌리지 않는다 — 판독은 성공한 것이 맞다
    if ai.run_status == "done" :
        try :
            _store_lesions(ai)
            from . import reports
            from . import notify
            report = reports.issue_stage_report(ai)
            staff = getattr(ai.created_by, "staff", None)
            if staff:
                notify.send(
                    staff=staff, 
                    type="report_ready",
                    message = "AI 판독이 끝났습니다.",
                    ref_type="report",
                    ref_id=report.pk
                )
            # 메시 업로드가 실패해도 소견문 · 알림은 이미 나갔다 — 그래서 맨 뒤
            _store_lesion_meshes(ai, lesion_meshes)
        except Exception as exc :
            logger.exception("[run_inference] 판독 뒤처리 실패 %s", ai.pk)
    logger.info("[run_inference] 행 %s %s %.1f초", ai.pk, ai.run_status, float(ai.elapsed_sec))
    return ai.run_status

def _narrative_result(report, ai_result_id) :
    """리포트 서버에 넘길 판독값을 만든다. 소켓 7 만 모양이 다르다.

      검사 리포트  판독 하나의 result 를 그대로 넘긴다
      종합 소견서  고른 판독들을 stages 로 묶고 청중을 붙인다

    묶을 목록은 발급할 때 content_json 에 적어 두었다 — Report 에서 AiResult 로
    가는 FK 가 없어서 지금 다시 찾아낼 방법이 없다.
    """
    if report.socket_id != "7" :
        ai = AiResult.objects.get(pk=ai_result_id)
        result = (ai.result or {}).get("result")
        if not isinstance(result, dict) :
            logger.warning("[narrative] 리포트 %s 판독 %s 에 결과가 없다", report.pk, ai.pk)
            return None
        return result

    ids = (report.content_json or {}).get("source_ai_ids") or []
    rows = {a.pk: a for a in AiResult.objects.filter(pk__in=ids)}
    stages = []
    for pk in ids :                       # 의사가 고른 순서를 지킨다
        ai = rows.get(pk)
        result = (ai.result or {}).get("result") if ai else None
        if isinstance(result, dict) :
            stages.append({"socket": SOCKET[ai.study.modality if ai.study_id else "pathology"],
                           "result": result})
    if not stages :
        logger.warning("[narrative] 종합 리포트 %s 에 묶을 판독이 없다", report.pk)
        return None
    return {"stages": stages, "audience": report.audience}

@shared_task(bind=True, queue="io")
def request_narrative(self, report_id, ai_result_id=None) :
    """리포트 한 건의 AI 소견문을 리포트 서버에 맡긴다.

    ■ 왜 태스크인가
        리포트 서버는 GPU 를 쓴다. 모델이 올라와 있으면 1초 미만이지만 처음
        부를 때는 적재를 기다린다. 판독 태스크가 그것까지 안고 있으면 다음
        판독이 밀린다.

    ■ 글이 돌아오는 길
        여기서 Go 를 부르고 끝이다. 문장은 응답이 아니라 콜백으로 들어온다.

            Django ─티켓─▶ llm-proxy ─▶ 리포트 서버 ─▶ 소견문 저장 콜백 ─▶ report

        Go 응답에도 같은 내용이 실려 있지만 쓰지 않는다. 저장 경로가 둘이면
        어느 쪽이 이겼는지 알 수 없다.

    ■ 실패해도 리포트는 남는다
        명세 규칙이다 — 리포트 서버가 죽어도 리포트는 발급된다. 예외를
        올리지 않는다.
        연결이 안 되거나 5xx 면 두 번까지 다시 건다(20초 간격). 터널이
        잠깐 끊기거나 리포트 서버가 재기동 중인 경우가 대부분이라 그때는
        기다리면 된다. 4xx 는 우리가 잘못 보낸 것이라 다시 보내도 같다.
        그래도 안 되면 notes 에 사유를 남긴다. 빈칸으로 두면 화면이
        「아직 생성 중」과 구분을 못 해 영원히 기다린다.
        GPU 를 붙잡는다는 우려는 큐를 가른 뒤(2026-09-19) 약해졌다 —
        소견문은 io 워커에서 돌고 판독(8001)과 다른 프로세스(8002)다.
    """
    report = Report.objects.get(pk=report_id)    
    # 봉투가 아니라 안쪽을 보낸다. 리포트 서버는 /analyze 의 result 를 그대로
    # 받는다 — 봉투째 주면 lesion_found 를 못 찾아 「병변이 검출되지
    # 않았습니다」가 나간다.
    result = _narrative_result(report, ai_result_id)
    if result is None :
        return "no_result"
    if not isinstance(result, dict) :
        logger.warning("[narrative] 리포트 %s 판독 %s 에 결과가 없다", report_id, ai.pk)
        return "no_result"
    # evidence 는 아직 빈 목록이다. AI 결과에서 병변 행을 만드는 코드가 없어
    # 채울 것이 없다. 리포트 서버는 그때 근거 검사를 건너뛰고 숫자 검사만
    # 한다 — 400 이 아니라 정상 경로다.
    body = json.dumps({
        "report_id": str(report.pk),
        "socket": report.socket_id,
        "result": result,
        "evidence": []
    }).encode() 
    
    token, _, _ = issue("report_narrative", "report", report.pk)
    req = urllib.request.Request(
        f"{LLM_PROXY}/svc/v1/llm/report-narrative",
        data = body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try :
        # Go 는 5분까지 기다린다. 우리가 먼저 끊으면 Go 는 계속 만들고 있고
        # 콜백도 정상으로 들어오는데 이 태스크만 실패로 남아 헷갈린다.
        with urllib.request.urlopen(req, timeout=330) as r :
            out = json.loads(r.read())
    except Exception as exc :
        # 콜백이 먼저 들어왔을 수 있다. 그 사이에 글이 도착했으면 다시 걸 이유가 없다 
        report.refresh_from_db() 
        if report.narrative_text:
            logger.info("[narrative] 리포트 %s 콜백이 먼저 들어왔다.", report_id)
            return "arrived_late"
        
        # 4xx 는 우리가 잘 못 보낸거라 다시보내도 같은 결과 
        # 나모지는 잠시 뒤에 시도하면 될 수 있다 
        code = getattr(exc, "code", None)
        if (code is None or code >=500) and self.request.retries < 2 :
            raise self.retry(exc=exc, countdown=20)
        
        logger.warning("[narrative] 리포트 %s 못 보냄 (%s)", report_id, type(exc).__name__)
        report.notes = {**(report.notes or {}), "narrative_error": f"{type(exc).__name__}: {exc}"[:300]}
        report.save(update_fields=["notes", "updated_at"])
        return f"failed:{type(exc).__name__}"
    
    logger.info("[narrative] 리포트 %s 보냄 / 소켓 %s / fallback=%s", report_id, report.socket_id, out.get("fallback"))
    return "sent"

def _analyze(modality, socket, refs) :
    # ⑥ [이미지 워커로 전송] == Go 에서 이미지 전달 받음. 워커는 저장소에 접근하지 않는다 ==
    # 티켓 접두사(scope_kind/scope_id)가 Go 가 여는 범위다.
    #   DICOM   dicom/instances/<UID> · dicom/series/<ID> — Go 가 경로와 정확히 같은지 본다
    #   그 외   object_key 앞 두 칸 — Go 가 키가 그 아래인지 본다
    #
    # scope_kind · scope_id  티켓이 여는 범위. 이 범위 밖의 파일은 같은
    #                        티켓으로 못 받는다 — 권한 경계가 여기다
    # name                   추론 서버에 넘길 파일 이름. MRI 는 .zip 이어야
    #                        압축을 풀고, 나머지는 확장자로 형식을 본다
    # url                    Go 에서 받을 주소
    parts = []
    for ref in refs : 
        if modality in DICOM :
            scope_kind, name = DICOM[modality]
            scope_id = ref
            url = f"{GATEWAY}/svc/v1/{scope_kind}/{ref}"
        else :
            # Garage 키는 "scope_kind/scope_id/파일명" 모양이다. 앞 두 칸이 곧
            # 범위라 거기서 잘라 쓰고, 이름은 마지막 칸을 그대로 쓴다.
            scope_kind, scope_id = ref.split("/")[:2]
            name = ref.rsplit("/",1)[-1]
            url = f"{GATEWAY}/svc/v1/files/{ref}"
        token, _,_ = issue("download", scope_kind, scope_id)
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}"
        })
        with urllib.request.urlopen(req, timeout=300) as r :
            parts.append((name, r.read()))
    logger.info("[run_inference] 이미지 %s 바이트", [len(d) for _,  d in parts])
        
    
    # ⑦ [판독 요청] == 추론 서버로 전송. 칸은 image · post 둘 =
    #
    # 영상을 디스크에 쓰지 않고 메모리에서 바로 본문으로 만든다. 요청 형식이
    # multipart 인 것은 추론 서버의 창구가 그것 하나여서다 — 환자 정보는
    # 보내지 않는다. MRI 만 둘째 칸(post, 조영 후)이 차고, 그러면 추론 서버가
    # 병변까지 낸다(phases=2). 나머지 모달리티는 image 한 칸이다.
    #
    # boundary  본문에서 칸과 칸을 가르는 표식. 내용과 겹치면 안 되므로
    #           요청마다 새 난수로 만든다
    boundary = uuid.uuid4().hex
    body = b""
    for field, (name, data) in zip(("image", "post"), parts) :
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}";'
                 f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'
                 ).encode() + data + b"\r\n"
    body += f"--{boundary}--\r\n".encode() 
    
    req = urllib.request.Request(f"{INFERENCE}/analyze/{socket}", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    # 추론 서버는 실패도 HTTP 200 에 abstained 로 돌려준다. 그래서 상태
    # 코드를 따로 보지 않고, 기권 여부는 응답 안에서 읽는다.
    #
    # 유휴 회수와 겹치면 연결이 끊긴다 — 판독 서버는 30초 놀면 GPU 를
    # 반납하려고 프로세스를 끝내고, supervisor 가 곧바로 다시 띄운다.
    # 그 순간에 들어간 요청만 끊기므로 한 번 더 걸면 된다.
    # 두 번째도 끊기면 그때는 실패로 남긴다.
    for attempt in (1,2) :
        try : 
            with urllib.request.urlopen(req, timeout=600) as r :
                out = json.loads(r.read())
            break
        except (urllib.error.URLError, ConnectionError, http.client.HTTPException) as exc :
            if attempt == 2 :
                raise 
            logger.warning("[run_inference] 연결 끊김 - 다시 건다 (%s)", type(exc).__name__)
            time.sleep(3)
    return out

def _birads(value) :
    """모델이 낸 BI-RADS 등급을 우리 코드값(BIRADS_CATEGORY)으로 맞춘다.

    모델마다 4 · "4A" · "BI-RADS 4a" 처럼 모양이 제각각이다. 문자열로 바꾸고
    소문자 · 접두사를 걷어 코드표에 있으면 그 값을, 없으면 None 을 돌려준다 —
    모르는 값 때문에 판독 뒤처리가 멈추면 안 된다.
    ⚠ 세분 없는 4 도 이제 코드표 값이다(MRI 판정용 — services/birads.py).
    """
    return birads_rules.normalize(value)

def _birads_rank(value) :
    """등급 비교용 열쇠. 코드표 밖 값은 가장 낮다.

    int 와 str 이 섞여 와도(4 와 "4a") 비교가 TypeError 로 터지지 않는다.
    세분 없는 4 는 4b 와 같은 자리다 — 이유는 services/birads.py 머리말.
    """
    return birads_rules.rank(value)

def _mammo(ai, socket) :
    """맘모는 영상 넷(좌우 × CC/MLO)이 한 검진이다.

    장마다 판독하고 결과를 합친다. 합친 모양은 한 장짜리와 같게 두어
    리포트 서버가 그대로 읽는다 — 병변에 어느 영상인지만 붙인다.
    """
    rows = (StorageObject.objects.filter(study_id=ai.study_id, sop_instance_uid__isnull=False, deleted_at__isnull=True).order_by("storage_object_id"))
    if not rows :
        raise ValueError("이 검사에 맘모 영상이 없다")
    
    envelope, lesions = None, []
    n, top, biopsy, abstained = 0, None, False, True
    for row in rows :
        out = _analyze("mammo", socket, [row.sop_instance_uid])
        envelope = envelope or out 
        s = ((out.get("result") or {}).get("summary")) or {}
        img = {
            "laterality": row.laterality, 
            "view": row.view_position
            }
        for l in ((out.get("result") or {}).get("lesions") or []) :
            side = (row.laterality or "?")[:1].upper()
            lesions.append({
                **l, 
                "image": img,
                "id": f"{side}-{row.view_position or '?'}-{l.get('id')}"
                })
        if not s.get("abstained") :
            abstained = False
        n += s.get("n_lesions") or 0
        biopsy = biopsy or bool(s.get("biopsy"))
        # 장마다 int · str 이 섞여 올 수 있다 — 그대로 > 로 견주면 TypeError 로
        # 판독 전체가 failed 가 된다. 코드표 순서로 견주고 문자열로 남긴다.
        b = s.get("max_birads")
        if b is not None and b != "" and (top is None or _birads_rank(b) > _birads_rank(top)) :
            top = _birads(b) or str(b)
    out = dict(envelope)
    out["result"] = {
        "summary" : {
            "abstained": abstained, 
            "n_lesions": n, 
            "max_birads": top, 
            "biopsy": biopsy
            },
        "lesions": lesions}
    return out

def _store_lesions(ai) :
    """판독 결과에서 병변 행을 만든다.

    병변은 여러 곳의 뿌리다 — 판정이 병변별로 달리고, 소견문 근거 목록도
    이 행에서 나오며, 검체가 여기 매달린다.

    병리는 여기서 만들지 않는다. 병변은 **영상이 만들고 검체가 거기 매달린다** —
    병리는 이미 떼어낸 조직을 보는 것이라 병변을 새로 찾지 않는다.
    Specimen.lesion 이 NOT NULL 인 것이 그 뜻이고, 유방외과의 검체 바인딩이
    lesion_id 를 요구한다(views/surgery.py). 그래서 이 함수가 비면 그 뒤가
    전부 막힌다.
    """
    if not ai.study_id :
        return 0
    
    modality = ai.study.modality 
    res = (ai.result or {}).get("result") or {}
    
    # ponytail: 같은 검사를 다시 판독하면 새 ai_result 가 생긴다. 옛 AI 병변은
    # 검체·판정이 안 붙은 것만 지운다 — 붙은 것은 PROTECT 라 지워지지도 않고,
    # 지우면 안 되는 기록이다.
    old = Lesion.objects.filter(
        study_id=ai.study_id,
        lesion_source="ai",
        specimens__isnull=True,
        assessments__isnull=True
    )
    # 초음파는 영상 한 장이 판독 한 번이다(한 검사에 AiResult 여럿). 검사 전체를
    # 지우면 장마다 도는 판독이 서로의 병변을 지워, 마지막 장의 병변 하나만
    # 남았다. 같은 원본에서 나온 병변만 지운다.
    if modality == "us" :
        old = old.filter(ai_result__source_object_id=ai.source_object_id)
    # 병변 메시(Image.lesion)가 PROTECT 라 먼저 지운다 — 안 그러면 재판독이
    # ProtectedError 로 멈춘다. ponytail: Garage 의 메시 파일은 남는다(고아)
    Image.objects.filter(lesion__in=old).delete()
    old.delete()
    
    rows = [] 
    if modality == "us" :
        if res.get("lesion_found") :
            shape = res.get("shape") or {}
            grade = res.get("grade") or {}
            # 장 번호 — 이 검사의 (안 지운) 원본을 번호순으로 놓았을 때 몇째인가.
            # 판독 화면의 images 와 같은 순서라 「US-2」가 둘째 장이다. 판독이
            # 붙은 원본은 취소가 막혀 있어 번호가 뒤에서 밀리지 않는다.
            nth = StorageObject.objects.filter(
                study_id=ai.study_id, deleted_at__isnull=True,
                storage_object_id__lte=ai.source_object_id).count() or 1
            rows.append(dict(
                lesion_index=nth - 1,
                label=f"US-{nth}",
                birads_model = grade.get("display"),
                grade_confidence=grade.get("confidence"),
                ai_size_px=shape.get("max_diameter_px"),
                ai_size_measurable=False, 
                mask_reliability = (res.get("mask_reliability") or {}).get("level"),
                detail = {"shape": shape, "orientation_label": res.get("orientation_label"),
                          "source_object": ai.source_object_id}
            ))
    elif modality == "mammo" :
        for i, l in enumerate(res.get("lesions") or []) :
            rows.append(dict(
                lesion_index=i, 
                label=l.get("id") or f"MAMMO-{i+1}",
                lesion_kind=l.get("kind"),
                birads_model=l.get("birads"),
                detail = {
                    "descriptors": l.get("descriptors"),
                    "biopsy" : l.get("biopsy"),
                    "confidence": l.get("confidence"),
                    "image": l.get("image"),
                    "box": l.get("box")
                }
            ))
    elif modality == "mri" :
        for i, l in enumerate((res.get("tumor") or {}).get("lesions") or []) :
            rows.append(dict(
                lesion_index=i, 
                label=f"MRI-{i+1}",
                # 모델이 등급을 내면 옮긴다. 코드표 밖 값은 비워 둔다(원값은 detail)
                birads_model=_birads(l.get("birads")),
                ai_size_mm=l.get("max_diameter_mm"),
                ai_size_measurable=True, 
                detail={
                    "volume_cm3": l.get("volume_cm3"),
                    "quadrant": l.get("quadrant"),
                    "nipple_distance_mm": l.get("nipple_distance_mm"),
                    **({"birads_raw": l.get("birads")}
                       if l.get("birads") is not None and _birads(l.get("birads")) is None
                       else {}),
                }
            ))
    for row in rows :
        Lesion.objects.create(
            study_id=ai.study_id, patient_id=ai.patient_id, 
            ai_result=ai, modality=modality, lesion_source="ai", **row)
    logger.info("[lesion] 판독 %s %s 병변 %d건", ai.pk, modality, len(rows))
    return len(rows)

def _series_row(study_id, role="pre") :
    """이 검사의 Orthanc 시리즈를 대표하는 저장 행 하나.

    시리즈 한 벌이 파일 146장이라 저장 행도 146개지만 시리즈 ID 는 같다.
    그래서 그중 아무 행이나 하나면 시리즈를 가리킬 수 있다. 행 자체가
    필요한 이유는 파생물 티켓이 원본 번호를 요구해서다 — MRI 는 ai_result 의
    원본 칸이 비어 있어 여기서 대신 찾는다.

    조영 전 시리즈를 쓴다. 표시가 없으면 먼저 들어온 시리즈를 쓴다 —
    series_role 을 채우는 코드가 아직 없다. 제대로 가리려면 Go 가 DICOM
    헤더에서 읽어 DICOM 정보 콜백에 실어야 한다. 그 전까지는 조영 후
    시리즈를 집을 수 있다.

    deleted_at 이 빈 행만 본다 — 지운 파일을 다시 부르지 않는다.

    파라미터
        study_id  검사 번호

    예외
        ValueError  이 검사에 Orthanc 시리즈가 하나도 없을 때
    """
    rows = (StorageObject.objects
            .filter(study_id=study_id, orthanc_series_id__isnull=False,
                    deleted_at__isnull=True)
            .order_by("storage_object_id"))
    row = rows.filter(series_role=role).first()
    if row is None and role == "pre" :
        row = rows.first()
        if row is not None :
            logger.warning("[run_inference] 검사 %s 조영 표시가 없다 - 먼저 들어온 시리즈를 쓴다",study_id)
    if row is None and role == "pre" :
        raise ValueError("이 검사에 Orthanc 시리즈가 없다")
    return row


def _ref(ai, modality) :
    """어느 파일을 보낼지 고른다. 모달리티마다 가리키는 칸이 다르다

    ai_result 는 원본을 한 행만 가리킨다. 그런데 모달리티마다 「한 행」의 뜻이
    달라서 Go 에게 건넬 값도 달라진다.

    파라미터
        ai        판독할 ai_result 행
        modality  us · mammo · mri · pathology

    돌려주는 값
        Go 에게 건넬 가리킴값
          us · pathology   Garage object_key   예) study/12/a3f1….png
          mammo            SOP Instance UID    예) 1.3.6.1.4.1.9590….
          mri              Orthanc 시리즈 ID   예) 036fcbc1-37f4517f-…

    예외
        ValueError  가리킬 것을 못 찾았을 때. 부르는 쪽의 try 가 받아 행을
                    failed 로 남긴다.
    """
    if modality == "mri" :
        # 조영 전·후 두 시리즈를 보낸다. 후가 없으면 전만 보내고 밀도만 받는다.
        post = _series_row(ai.study_id, "post")
        return [_series_row(ai.study_id).orthanc_series_id] + ([post.orthanc_series_id] if post else [])
    
    # MRI 가 아니면 원본 한 장을 반드시 가리킨다. 비어 있으면 요청을 만든 쪽이
    # 원본을 안 넣은 것이라 여기서 멈추고 failed 로 남긴다.
    src = ai.source_object
    if src is None :
        raise ValueError("원본이 비어있다")
    if modality == "mammo" :
        # 맘모는 DICOM 한 장이다. Orthanc 에서 꺼내려면 인스턴스 번호가 필요하다.
        if not src.sop_instance_uid :
            raise ValueError(
                "맘모 원본에 SOP Instance UID 가 없다 — DICOM 정보 콜백이 "
                f"아직 안 들어왔거나 실패했다 (storage_object {src.pk})")
        return [src.sop_instance_uid]
    # 초음파 · 병리는 Garage 에 그대로 있다.
    #
    # 키가 비는 경우가 있다 — DICOM 을 올리면 Orthanc 로 옮기면서 Garage 키를
    # 비운다(I-2). 초음파·병리 검사에 DICOM 이 올라오면 그 일이 생긴다.
    # 그냥 두면 아래에서 None.split 이 나 「'NoneType' object has no attribute
    # 'split'」로만 남는다 — 무엇이 잘못됐는지 안 보인다(09-23 study 117).
    if not src.object_key :
        raise ValueError(
            f"{modality} 원본에 저장소 키가 없다 (storage_object {src.pk}) — "
            f"Orthanc 로 옮겨진 DICOM 이면 이 모달리티로는 못 읽는다 "
            f"(orthanc_series_id={src.orthanc_series_id})")
    return [src.object_key]
    
def _upload_derived(ai, kind, payload, content_type, filename, source_id, lesion_id=None, object_name=None):
    """파생물 하나를 Go 로 올리고 실제 주소를 받아 온다.

    티켓에 꼬리표(종류 · 원본 · 실행)를 실어 서명한다. Go 가 그것을 파일 등록
    콜백에 그대로 넘기고, Django 가 발급 때와 같은 함수로 다시 검증한다 —
    파생물이 엉뚱한 실행에 붙지 않게 하는 자리다.

    범위는 검사(영상) 아니면 검체(병리)다. ai_result 가 둘 중 하나만 가리킨다.

    파라미터
        kind          파생물 종류. mask · mesh_breast 처럼 티켓이 아는 이름
        payload       올릴 바이트
        content_type  Go 가 저장할 때 붙일 형식
        filename      확장자만 쓰인다. 이름 전체는 Go 가 난수로 정한다
        source_id     이 파생물이 나온 원본 행 번호
        lesion_id     병변 메시만 쓴다

    돌려주는 값
        {"bucket": ..., "object_key": ...} — Go 가 실제로 저장한 주소
    """
    scope_kind = "study" if ai.study_id else "specimen"
    scope_id = ai.study_id or ai.specimen_id
    
    derived = {
        "kind": kind,
        "source_object_id":source_id, 
        "ai_result_id":ai.pk
    }
    if lesion_id:
        derived["lesion_id"] = lesion_id
        
    token, _, _ = issue("derived_upload", scope_kind, scope_id,
                        content_type=content_type, max_bytes=len(payload), 
                        derived=derived, object_name=object_name)
    req = urllib.request.Request(
        f"{GATEWAY}/svc/v1/derived", data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "X-Filename" : filename,
        }
    )
    with urllib.request.urlopen(req, timeout=60) as r :
        saved = json.loads(r.read())
    logger.info("[derived] %s %d 바이트 -> %s", kind, len(payload), saved["object_key"])
    return saved

def _store_mask(out, ai) :
    """마스크 PNG 를 파생물로 보내고 결과에는 주소만 남긴다.

    병리는 조직 분할(tissue_mask_png), 초음파는 병변 마스크(mask_png)다.
    판독 서버가 numpy 를 PNG 로 만들어 base64 로 싣고, 여기서 파일로 옮긴다.
    그대로 두면 판독할 때마다 같은 그림이 DB 안에 쌓인다.

    초음파는 윤곽 좌표(polygons)를 함께 낸다. 둘 다 남긴다 — 화면이 마스크로
    칠하고 좌표로 테두리를 그린다.
    """
    res = (out.get("result") or {}) 
    key = "tissue_mask_png" if "tissue_mask_png" in res else "mask_png"
    encoded = res.get(key)
    if not encoded :
        return out 
    
    out = dict(out)
    res = dict(res)
    out["result"] = res
    
    name = f"{key.replace('_png', '')}-{ai.pk}.png"
    saved = _upload_derived(ai, "mask", base64.b64decode(encoded),
                            "image/png", name, ai.source_object_id, object_name=name)
    res.pop(key, None)
    res[key.replace("_png", "")] = {
        "bucket": saved["bucket"],
        "object_key": saved["object_key"], 
        "content_type": "image/png"
    }
    return out 
    
def _store_meshes(out, ai) :
    """MRI 메시를 파생물 버킷으로 보내고 결과에는 실제 주소만 남긴다.

    주소는 올리기 전에 정해진다. mesh.split 이 티켓 접두사(study/<검사번호>) 뒤에
    붙일 이름을 만들고 Go 가 그 이름을 그대로 쓰므로, 올린 뒤 스텁을 고칠 필요가 없다.

    왜 필요한가
        MRI 응답은 48MB 안팎이고 그 대부분이 3D 메시(정점 · 삼각형 좌표)다.
        그대로 ai_result.result 에 넣으면 jsonb 한 칸이 그 크기가 되어 조회가
        느려지고 백업이 커진다. 메시는 파일로 두고 결과에는 주소만 남긴다.

    파라미터
        out  추론 서버 응답 봉투 전체. 판독값은 out["result"] 안에 있고
             메시도 거기 있다(result.density.breast_mesh 등). 원본은
             건드리지 않는다
        ai   판독한 ai_result 행. 티켓 범위와 파생물 꼬리표에 쓴다

    돌려주는 값
        메시를 뺀 봉투. 메시가 있던 자리에는 스텁(주소 · 정점 수)이 남는다.
        키를 지우지 않는 이유는, 그 자리를 따라 걷는 쪽이 「값이 없다」와
        「여기 있었고 저기 있다」를 구분할 수 있게 하기 위해서다.

    안에서 쓰는 이름
        inner      메시를 뺀 판독값(봉투 안쪽)
        parts      떼어낸 메시 목록. 각각 바이트 · 종류 · 확정된 주소를 든다
        source_id  파생물 티켓에 실을 원본 번호
    """
    # 메시 분리 코드는 판독값 기준이라 봉투가 아니라 그 안쪽을 넘긴다.
    # 봉투에는 모델 이름 · 판 같은 작은 값만 있어 걷어낼 것이 없다.
    inner, parts = mesh.split(out["result"], ai.study_id, ai.pk)
    out = dict(out)
    out["result"] = inner

    # MRI 는 원본 칸이 비어 있다(시리즈 전체를 보므로 가리킬 한 장이 없다).
    # 파생물 티켓은 원본 번호를 요구하므로 시리즈를 대표하는 행 번호를
    # 티켓에만 싣는다 — ai_result 행에 저장하지는 않는다.
    source_id = ai.source_object_id or _series_row(ai.study_id).pk

    held = []
    for part in parts :
        # 병변 메시는 **지금 못 올린다** — 파생물 티켓이 병변 번호를 요구하는데
        # 병변 행은 판독이 끝난 뒤(_store_lesions) 생긴다. 스텁에는 「아직 안
        # 올림」만 남기고 들고 있다가 _store_lesion_meshes 가 올린다(09-27).
        # 전에는 여기서 버려서 병변 3D 가 한 번도 안 떴다.
        if part.kind == mesh.LESION_KIND :
            _walk_ref(inner, f"study/{ai.study_id}/{part.object_name}", None)
            held.append(part)
            continue

        # 파생물 티켓은 쓰기 티켓이다. 범위(검사)와 함께 꼬리표를 서명에 싣는다 —
        # Go 가 그대로 파일 등록 콜백에 실어 보내고, Django 가 발급 때와 같은
        # 함수로 다시 검증한다. 그래야 파생물이 엉뚱한 실행에 붙지 않는다.
        #   content_type  Go 가 저장할 때 붙일 형식
        #   max_bytes     이 파일 크기만큼만 허용. 넘으면 Go 가 받다가 끊는다
        _upload_derived(ai, part.kind, part.payload, part.content_type,
                        part.object_name, source_id,
                        object_name=part.object_name)
    return out, held

def _store_lesion_meshes(ai, held) :
    """_store_meshes 가 들고 있던 병변 메시를 병변 행에 붙여 올린다.

    part.lesion_index 는 결과의 tumor.lesions 순번이고, _store_lesions 도 같은
    순번으로 lesion_index 를 매긴다 — 그 번호로 행을 찾는다.
    """
    if not held :
        return
    ids = dict(Lesion.objects.filter(ai_result=ai).values_list("lesion_index", "pk"))
    source_id = ai.source_object_id or _series_row(ai.study_id).pk
    for part in held :
        lid = ids.get(part.lesion_index)
        if lid is None :
            continue
        _upload_derived(ai, part.kind, part.payload, part.content_type,
                        part.object_name, source_id, lesion_id=lid,
                        object_name=part.object_name)

def _walk_ref(node, planned_key, saved) :
    """예정 주소로 넣어 둔 스텁을 찾아 실제 주소로 바꾼다.

    saved 가 None 이면 올리지 않은 것이다 — 없는 주소를 가리키지 않게 지우고
    표시만 남긴다.

    왜 훑어서 찾나
        메시가 응답의 어느 깊이에 있는지는 종류마다 다르다(검사 메시는 density
        아래, 병변 메시는 배열 원소 아래). 경로를 다시 계산하는 대신 예정
        주소로 스텁을 찾는다 — 예정 주소는 종류마다 다르게 만들어져서 그 자체가
        구분값이 된다.

    파라미터
        node         훑을 자리. 재귀로 dict · list 를 따라 내려간다
        planned_key  mesh.split 이 스텁에 심어 둔 예정 주소
        saved        Go 가 돌려준 실제 주소. None 이면 올리지 않았다는 뜻

    돌려주는 값
        고쳤으면 True. any() 가 첫 성공에서 멈추므로 한 번 찾으면 더 안 훑는다.
    """
    if isinstance(node, dict) :
        ref = node.get(mesh.REF_KEY)
        if isinstance(ref, dict) and ref.get("object_key") == planned_key :
            if saved is None :
                # 주소를 지우고 표시만 남긴다. 주소가 남아 있으면 없는 파일을
                # 받으러 가서 실패한다.
                ref.pop("bucket", None)
                ref.pop("object_key", None)
                ref["stored"] = False 
            else :
                ref["bucket"] = saved["bucket"]
                ref["object_key"] = saved["object_key"]
            return True
        return any(_walk_ref(v, planned_key, saved) for v in node.values())
    if isinstance(node, list) :
        return any(_walk_ref(v, planned_key, saved) for v in node)
    return False 

@shared_task(queue="io")
def deliver_external(notification_id) :
    """알림 한 건을 바깥 채널로 내보낸다(FCM · SMS).

    태스크로 떼어 둔 이유 — 외부 호출은 느리고 자주 실패한다. notify.send()
    안에서 부르면 잠금 해제나 판독 뒤처리가 그만큼 붙잡힌다.

    재시도하지 않는다. 푸시가 안 가면 SMS 로 한 번 더 시도하고 거기서 끝낸다 —
    같은 알림을 여러 번 보내는 쪽이 못 보내는 쪽보다 나쁘다.
    """
    from . import delivery 
    note = Notification.objects.filter(pk=notification_id).first()
    if note is None :
        # 행이 사라졌다. 되돌려진 요청이거나 지워진 알림이다 — 보낼 것이 없다.
        logger.info("[delivery] 알림 %s 가 없다. 건너뛴다", notification_id)
        return "gone"
    channel = delivery.deliver(note)
    if channel :
        note.channel = channel 
        if note.sent_at is None: 
            note.sent_at = timezone.now() 
        note.save(update_fields=["channel", "sent_at", "updated_at"])
    return channel or "none"

@shared_task(queue="io")
def reservation_reminders() :
    """내일 예약을 환자에게 알린다. beat 가 한 시간마다 부른다.

    「24시간 안」을 훑는 이유 — 서버가 꺼져 있던 시간이 있어도 다음 주기에
    늦게라도 나간다. 정확한 시점 하나만 보면 그 창을 놓치는 순간 끝이다.

    같은 예약에 두 번 보내지 않는 것은 Notification 을 조회해서 막는다.
    표시용 칸을 따로 두지 않는 이유 — 보낸 기록이 이미 그 표에 있다.
    """
    now = timezone.now()
    orders = (ExamOrder.objects
              .filter(scheduled_at__gt=now,
                      scheduled_at__lte=now + timedelta(hours=24))
              .exclude(order_status__in=["cancelled", "completed"])
              .select_related("patient"))

    sent = 0
    for order in orders :
        if Notification.objects.filter(notification_type="reservation_reminder",
                                       ref_type="exam_order",
                                       ref_id=order.pk).exists() :
            continue
        when = timezone.localtime(order.scheduled_at)
        notify.send(patient=order.patient,
                    type="reservation_reminder",
                    message=f"내일 {when:%H시 %M분} 검사 예약이 있습니다.",
                    ref_type="exam_order", ref_id=order.pk,
                    severity="normal")
        sent += 1

    logger.info("[reminder] 예약 하루 전 알림 %s건", sent)
    return sent