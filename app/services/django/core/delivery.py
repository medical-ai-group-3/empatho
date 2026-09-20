"""알림을 바깥으로 내보낸다 — FCM 웹 푸시 · 솔라피 SMS.

Go 알림 허브가 아니라 여기 있는 이유
  Go 는 DB 를 읽지 않는다(규칙 1). 전화번호와 push_token 이 DB 에 있어서,
  Go 에서 보내려면 Django 가 전화번호를 Go 로 넘겨야 한다. PII 를 한 겹 더
  퍼뜨리는 일이라 여기서 보낸다. Go 는 SSE 만 맡는다.

자격증명이 없으면 조용히 건너뛴다. 실패도 여기서 삼킨다 —
알림 하나 못 보낸 것으로 판독 흐름을 세우지 않는다.
"""

import base64 
import hashlib
import hmac 
import json 
import logging 
import re 
import secrets 
import time 
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone 

import jwt 
from django.conf import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
FCM_SEND = "https://fcm.googleapis.com/v1/projects/{}/messages:send"
SOLAPI_SEND = "https://api.solapi.com/messages/v4/send"

# 알림 종류 -> 푸시 제목 
# 본문은 Notification.message 를 그대로 쓴다 
TITLE = {
    "report_ready": "검사 결과",
    "reservation_created": "예약 확정",
    "reservation_changed": "예약 변경",
    "reservation_requested": "예약 요청",
    "followup": "추적 관찰",
    "discordance": "확인 필요",
}

_oauth = {"token": None, "exp": 0.0}

def _service_account() :
    if not settings.FCM_CREDENTIALS_B64:
        return None 
    try : 
        return json.loads(base64.b64decode(settings.FCM_CREDENTIALS_B64))
    except Exception :
        logger.exception("[delivery] FCM 자격증명을 읽지 못 했다.")
        return None
    
def _access_token(sa) :
    """서비스 계정으로 OAuth2 토큰을 받는다. 한시간짜리, 캐시 필요"""
    now = time.time() 
    if _oauth["token"] and now < _oauth["exp"] - 60:
        return _oauth["token"]
    
    claim = {
        "iss": sa["client_email"], 
        "scope": "https://www.googleapis.com/auth/firebase.messaging", 
        "aud": GOOGLE_TOKEN, 
        "iat": int(now),
        "exp": int(now) + 3600
             }
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt.encode(claim, sa["private_key"], algorithm="RS256"),
    }).encode() 
    
    req = urllib.request.Request(
        GOOGLE_TOKEN, 
        data=body, 
        headers={
            "Content-Type": "application/x-www-form-urlencoded"
        }
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        out = json.loads(r.read())
    _oauth.update(token=out["access_token"], 
                  exp=now + int(out.get("expires_in", 3600)))
    return _oauth["token"]

def send_push(account, note) :
    """FCM 웹 푸시. 보냈으면 True.

    토큰이 죽어 있으면(앱 삭제 · 권한 철회) DB 에서 지운다. 안 지우면
    알림이 날 때마다 404 를 받으면서 계속 시도한다.
    """
    sa = _service_account() 
    if not sa or not settings.FCM_PROJECT_ID:
        return False 
    if account is None or not account.push_token:
        return False 
    
    payload = {
        "message" :{
            "token": account.push_token,
            "notification": {
                "title": TITLE.get(note.notification_type, "EMPATHO"),
                "body": note.message,
            }, 
            "webpush": {"fcm_options": {"link": settings.PATIENT_APP_URL}},
            "data": {
                "notification_id": str(note.pk),
                "ref_type": note.ref_type or "",
                "ref_id": str(note.ref_id or "")
            },
        }
    }
    try: 
        req = urllib.request.Request(
            FCM_SEND.format(settings.FCM_PROJECT_ID), 
            data = json.dumps(payload).encode(), 
            headers={
                "Authorization": "Bearer " + _access_token(sa),
                "Content-Type": "application/json"
            })
        with urllib.request.urlopen(req, timeout=20):
            return True
    except urllib.error.HTTPError as e :
        detail = e.read()[:300].decode("utf-8", "replace")
        if e.code == 404 or "UNREGISTERED" in detail:
            account.push_token = None
            account.save(update_fields=["push_token"])
            logger.info("[delivery] 죽은 푸시 토큰 삭제 account=%s", account.pk)
        else :
            logger.warning("[delivery] FCM %s %s", e.code, detail)
    except Exception:
        logger.exception("[delivery] FCM 실패 알림 %s", note.pk)
    return False 

def send_sms(phone, text) :
    """솔라피 단건 발송. 보냈으면 True.

    ⚠ SOLAPI_FROM 은 솔라피에 **사전등록된 발신번호**여야 한다. 등록 안 된
      번호로 보내면 거절되고, 반복하면 계정이 막힌다.
    ⚠ 본문이 EUC-KR 90바이트를 넘으면 솔라피가 LMS 로 올려 보낸다. 요금이 다르다.
    """
    if not (settings.SOLAPI_KEY and settings.SOLAPI_SECRET and settings.SOLAPI_FROM):
        return False 
    to = re.sub(r"\D", "", phone or "")
    if not to:
        return False 
    
    data = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S,000Z")
    salt = secrets.token_hex(16)
    sig = hmac.new(settings.SOLAPI_SECRET.encode(), 
                   (data + salt).encode(), hashlib.sha256).hexdigest()
    
    try :
        req = urllib.request.Request(
            SOLAPI_SEND,
            data=json.dumps({
                "message" :{
                    "to": to, 
                    "from": re.sub(r"\D", "", settings.SOLAPI_FROM),
                    "text": text 
                }
            }).encode(), 
            headers={
                "Authorization": (f"HMAC-SHA256 apiKey={settings.SOLAPI_KEY}, "
                                  f"data={data}, salt={salt}, signature={sig}"),
                "Content-Type": "application/json"
            })
        with urllib.request.urlopen(req, timeout=20) as r :
            out = json.loads(r.read())
        if str(out.get("statusCode", "")).startswith("2"):
            return True
        logger.warning("[delivery] 솔라피 거절 %s %s", out.get("statusCode"), out.get("statusMessage"))
    except urllib.error.HTTPError as e :
        logger.warning("[delivery] 솔라피 %s %s", e.code, e.read()[:200].decode("utf-8", "replace"))
    except Exception:
        logger.exception("[delivery] SMS 실패")
    return False 

def _sms_text(note):
    """문자 본문. 푸시와 달리 제목 칸이 없어서 보내는 곳을 본문에 적는다.

    낯선 번호로 「검사 결과가 도착했습니다」만 오면 스미싱으로 읽힌다.
    링크도 붙인다 — 푸시는 눌러서 열리지만 문자는 갈 길이 없다.

    ⚠ 진단명 · 수치 · 검사 내용은 넣지 않는다. 문자는 잠금 화면에 그대로
      뜨고 가족이 볼 수 있다. 「도착했다」까지만 알리고 내용은 앱에서 본다.
    """
    parts = [p for p in (settings.SMS_PREFIX, note.message,
                         settings.PATIENT_APP_URL) if p]
    return " ".join(parts)

def deliver(note) :
    """환자 알림 한 건을 바깥으로 내보낸다. 성공한 채널 이름을 낸다.

    ⚠ 바깥 발송(FCM · SMS)은 **환자에게만** 한다. 의료진은 병원 웹 안에서
      SSE 로만 받는다 — 진료 정보가 개인 휴대폰 문자로 나가서는 안 된다.
      「환자가 아니면」이 아니라 「의료진이면 절대」로 적는다. 앞엣것은 수신자
      칸이 하나 늘면 뚫린다.

    보통은 푸시가 되면 문자를 보내지 않는다 — 건당 요금이다.
    다만 sev1 은 둘 다 보낸다. 토큰이 살아 있는데 환자가 알림만 꺼두면 FCM 은
    200 을 주지만 환자는 못 본다. 검사 결과처럼 놓치면 안 되는 것은 두 길로 간다.
    """
    if note.staff_id is not None or note.patient_id is None:
        return None

    pushed = send_push(note.patient.account, note)
    if pushed and note.severity != "sev1" :
        return "app"

    phone = getattr(getattr(note.patient, "pii", None), "phone", None)
    if phone and send_sms(phone, _sms_text(note)) :
        return "sms"
    return "app" if pushed else None 