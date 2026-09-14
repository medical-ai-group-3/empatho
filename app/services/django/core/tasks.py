"""판독 태스크 — 워커가 이미지를 Go 에서 받아 추론 서버로 보낸다.

지금은 흐름 확인용이다. DB 를 쓰지 않고 결과를 로그로만 남긴다.
"""

import json 
import logging 
import time 
import urllib.request
import uuid 

from celery import shared_task 
from .api.tickets import issue 

logger = logging.getLogger(__name__) 

# 파일 게이트웨이 주소
GATEWAY = "http://file-gateway:8091"
# 추론 서버로 전송을 하기 위한 터널 주소 
INFERENCE = "http://tunnel:8001"


# 모달리티별 소켓 지정 
SOCKET = {"us": "5", "mammo": "4b", "mri": "3", "pathology": "1"}

# DICOM 은 Orthanc 에만 있다. 맘모는 한 장, MRI 는 시리즈를 zip 으로 받는다.
#   모달리티 → (티켓 범위 종류, 추론 서버에 넘길 파일 이름)
# MRI 소켓은 이름이 .zip 이어야 압축을 푼다.
DICOM = {"mammo": ("dicom/instances", "image.dcm"), "mri": ("dicom/series", "series.zip")}

# ⑤ celery task로 등록 => core.tasks.run_inference
# 워커는 뜰 때 각 앱의 tasks.py 를 자동으로 찾아 이름을 등록 
@shared_task
# parameter 두 개가 그대로 redis 에 보내는 메세지로 사용 (파일 위치,종류)
def run_inference(ref, modality) :
    """
    ref       어느 파일인가. 모달리티마다 가리키는 것이 다르다
                us · pathology   Garage object_key    예) test/flowcheck/a400a1….png
                mammo            SOP Instance UID     예) 1.3.6.1.4.1.9590….
                mri              Orthanc 시리즈 ID    예) 036fcbc1-37f4517f-…
    modality  us · mammo · mri · pathology

    DICOM(맘모 · MRI)은 Orthanc 에만 있어서 Go 의 dicom 경로로 받는다.
    """
    
    socket = SOCKET[modality]
    logger.info("[run_inference] 수신 ref=%s modality=%s -> 소켓 %s", ref, modality, socket)
    
    # ⑥ [이미지 워커로 전송] == Go 에서 이미지 전달 받음. 워커는 저장소에 접근하지 않는다 ==
    # 티켓 접두사(scope_kind/scope_id)가 Go 가 여는 범위다.
    #   DICOM   dicom/instances/<UID> · dicom/series/<ID> — Go 가 경로와 정확히 같은지 본다
    #   그 외   object_key 앞 두 칸 — Go 가 키가 그 아래인지 본다
    if modality in DICOM: 
        scope_kind, name = DICOM[modality]
        scope_id = ref
        url = f"{GATEWAY}/svc/v1/{scope_kind}/{ref}"
    else : 
        scope_kind, scope_id = ref.split("/")[:2]
        name = ref.rsplit("/", 1)[-1]
        url = f"{GATEWAY}/svc/v1/files/{ref}"
        
    # issue() => (티켓 문자열, 클레임, 만료 시각) 세 개를 돌려주지만 티켓 하나라 나머지는 버림
    # "download" => 읽기만 허용. go 는 서명 · 만료 · 범위만 확인
    token, _, _ = issue("download", scope_kind, scope_id)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as r :
        data = r.read() 
    logger.info("[run_inference] 이미지 %d 바이트", len(data))
    # ⑦ [판독 요청] == 추론 서버로 전송, multipart 한 칸(image 한 장) ==
    boundary = uuid.uuid4().hex
    # 전송할 내용을 담은 body. name은 위에서 정함 
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode() 
    req = urllib.request.Request(f"{INFERENCE}/analyze/{socket}", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    t0 = time.monotonic() 
    with urllib.request.urlopen(req, timeout=800) as r :
        out = json.loads(r.read())
    logger.info("[run_inference] 소켓 %s 응답 %.1f초 abstained=%s reason=%s", out.get("socket_id"), time.monotonic() - t0, out.get("abstained"), out.get("reason"))
        
    return {k: out.get(k) for k in ("socket_id", "abstained", "reason")}