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

# ⑤ celery task로 등록 => core.tasks.run_inference
# 워커는 뜰 때 각 앱의 tasks.py 를 자동으로 찾아 이름을 등록 
@shared_task
# object_key 예시 :: test/flowcheck/a400a1….png
# parameter 두 개가 그대로 redis 에 보내는 메세지로 사용 (파일 위치,종류)
def run_inference(object_key, modality) :
    """
    object_key : Go가 정하는 저장소 안 파일의 경로
    modality : 소켓(사용 모델 타입) 
    
    파일의 종류에 따라 Go가 자동으로 garage랑 orthanc를 나눈다
    """
    
    socket = SOCKET[modality]
    scope_kind, scope_id = object_key.split("/")[:2]
    logger.info("[run_inference] 수신 key=%s modality=%s -> 소켓 %s", object_key, modality, socket)
    
    # ⑥ [이미지 워커로 전송] ==  Go 에서 이미지 전달 받음. 워커는 저장소에 접근하지 않는다 == 
    
    # issue() => (티켓 문자열, 클레임, 만료 시각) 세 개를 돌려주지만 티켓 하나라 나머지는 버림 
    # "download" => 읽기만 허용 
    # 서명은 Django 랑 go 가 가진 TICKET_KEY로 함 / go 는 서명과 만료만 확인
    token, _, _ = issue("download", scope_kind, scope_id)
    req = urllib.request.Request(f"{GATEWAY}/svc/v1/files/{object_key}", headers={"Authorization": f"Bearer {token}"})
    # GATEWAY 주소로 접근해서 object_key 에 맞는 파일을 request 하고 header 에 token을 붙여옴 
    # 가져온 파일의 주소를 열어서 내용물을 data에 저장 
    with urllib.request.urlopen(req, timeout=60) as r :
        data = r.read() 
    # 가져온 데이터의 크기를 log 에 기록 
    logger.info("[run_inference] 이미지 %d 바이트", len(data))
    
    # ⑦ [판독 요청] == 추론 서버로 전송, multipart 한 칸(image 한 장) == 
    boundary = uuid.uuid4().hex
    name = object_key.rsplit("/", 1)[-1] # 아마도 profile.jpg
    # 전송할 내용을 담은 body 
    # 구분을 위한 uuid, 데이터 타입, 이름, 이미지 이름, 
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{name}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n').encode() + data + f"\r\n--{boundary}--\r\n".encode()
    # body를 담은 요청서 
    req = urllib.request.Request(f"{INFERENCE}/analyze/{socket}", data = body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    
    t0 = time.monotonic() 
    # request 처리돼서 오면 열어보기 
    with urllib.request.urlopen(req, timeout=800) as r :
        out = json.loads(r.read())
    # 데이터를 log 에 저장 
    logger.info("[run_inference] 소켓 %s 응답 %.1f초 abstained=%s reason=%s", out.get("socket_id"), time.monotonic() - t0, out.get("abstained"), out.get("reason"))
    return {k: out.get(k) for k in ("socket_id", "abstained", "reason")}