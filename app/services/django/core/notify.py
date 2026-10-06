"""알림 한 건을 만들고 Go 허브로 발행한다.

Go 는 알림을 만들지 않는다 — Django 가 만들어 발행하고 Go 는 흘린다.
전달 결과는 Go 가 I-3 콜백으로 되돌려 sent_at 을 찍는다.
"""

import hmac
import json 
import logging 
import time 
import urllib.error
import urllib.request
from hashlib import sha256

from django.conf import settings

from . import models 

logger = logging.getLogger(__name__)

NOTIFY = "http://notify:8092"

def send(patient=None, staff=None, *, type, message, ref_type=None, ref_id=None, severity=None):
    note = models.Notification.objects.create(
        patient=patient, 
        staff=staff, 
        notification_type = type, 
        severity=severity, 
        channel="sse" if staff is not None else "app",
        message=message, 
        ref_type=ref_type, 
        ref_id=ref_id
    )
    # 커밋된 뒤에 큐에 넣는다. 행을 만든 직후에 넣으면, 요청이 나중에
    # 되돌려졌을 때 작업은 그대로 돌고 없는 행을 찾는다 — 2026-09-20 에
    # 실제로 NotUpdated 로 터졌다. account 가 없어도 문자는 갈 수 있으므로
    # 아래 early return 보다 위에 둔다.
    from django.db import transaction
    from .tasks import deliver_external
    transaction.on_commit(lambda: deliver_external.delay(note.pk))
    # 환자는 SSE 를 쓰지 않는다. 앱은 FCM 으로 받고, 앱 안 종 아이콘은 알림
    # 목록 API 로 채운다. 둘 다 흘리면 같은 알림이 두 번 뜨는데, 그걸 막으려면
    # 「누가 접속해 있나」를 서버가 알아야 한다. 경로를 하나로 줄인다.
    if patient is not None:
        return note
    account = (patient or staff).account
    if account is None:
        return note 
    
    body = json.dumps({
        "notification_id": str(note.pk),
        "user_ids": [str(account.pk)],
        "type": type,
        "payload": {
            "message": message,
            "ref_type": ref_type, 
            "ref_id":ref_id
        }
    }).encode() 
    ts = str(int(time.time()))
    mac = hmac.new(settings.CALLBACK_SECRET.encode(), digestmod=sha256)
    mac.update(ts.encode()); mac.update(b"."); mac.update(body)
    
    req= urllib.request.Request(
        f"{NOTIFY}/svc/v1/notify/publish", 
        data=body, 
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Timestamp": ts, 
            "X-Signature": mac.hexdigest()
        }
    )
    
    try :
        with urllib.request.urlopen(req, timeout=10) as r :
            json.loads(r.read())
    except Exception :
        logger.exception("[notify] 발행 실패 %s", note.pk)
    return note