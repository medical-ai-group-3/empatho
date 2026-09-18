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
        channel="sse",
        message=message, 
        ref_type=ref_type, 
        ref_id=ref_id
    )
    
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