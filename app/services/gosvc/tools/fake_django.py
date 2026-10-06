#!/usr/bin/env python3
"""가짜 Django — 내부 콜백(I-1~I-4)을 받아 화면에 찍는다.

무엇에 쓰나
    진짜 Django 의 /internal/v1/* 이 아직 없어서 Go 를 끝까지 시험할 수 없다.
    이걸 대신 띄우면 Go 가 보내는 것을 **그대로 볼 수 있다.**

무엇을 확인하나
    ① 서명이 맞는가            — Django 팀이 같은 식으로 계산하면 되는지 확인
    ② 멱등키가 붙는가          — 재시도가 중복 행을 만들지 않는지
    ③ I-1 이 I-2 보다 먼저인가 — 명세 21장의 순서 보장
    ④ 본문에 무엇이 들어오는가 — Django 모델을 이 모양에 맞추면 된다

⚠ 시험용이다. 운영에 쓰지 말 것. 인증서도 없고 저장도 안 한다.

사용
    python3 fake_django.py --port 9999 --secret dev-secret
    python3 fake_django.py --fail /internal/v1/dicom-instances   # I-2 만 실패시켜 보기
"""

import argparse
import hashlib
import hmac
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

SEEN = {}          # 멱등키 -> 처음 받은 시각
ORDER = []         # 받은 경로 순서 (I-1 → I-2 확인용)

C = {"g": "\033[32m", "r": "\033[31m", "y": "\033[33m",
     "b": "\033[1m", "d": "\033[2m", "0": "\033[0m"}


def sign(secret: bytes, ts: str, body: bytes) -> str:
    """Go 의 callback.Sign 과 같아야 한다 — HMAC-SHA256(ts + "." + body).

    구분자(.)가 없으면 (ts="1", body="23") 과 (ts="12", body="3") 이
    같은 서명을 낸다. Django 도 반드시 이 식으로 계산할 것.
    """
    m = hmac.new(secret, digestmod=hashlib.sha256)
    m.update(ts.encode())
    m.update(b".")
    m.update(body)
    return m.hexdigest()


class Handler(BaseHTTPRequestHandler):
    secret = b""
    fail_paths: set = set()

    def log_message(self, *a):
        pass                      # 기본 접근 로그를 끈다. 우리가 직접 찍는다

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n)
        path = self.path
        ts = self.headers.get("X-Timestamp", "")
        got = self.headers.get("X-Signature", "")
        idem = self.headers.get("Idempotency-Key", "")

        print(f"\n{C['b']}{'─'*70}{C['0']}")
        print(f"{C['b']}{path}{C['0']}  {time.strftime('%H:%M:%S')}")

        # ① 서명
        if not ts or not got:
            ok = False
            print(f"  서명      {C['r']}✗ 헤더 없음{C['0']} "
                  f"(X-Timestamp / X-Signature)")
        else:
            want = sign(self.secret, ts, body)
            ok = hmac.compare_digest(want, got)
            if ok:
                print(f"  서명      {C['g']}✓ 일치{C['0']}  {C['d']}{got[:16]}…{C['0']}")
            else:
                print(f"  서명      {C['r']}✗ 불일치{C['0']}")
                print(f"            받은 값 {got[:32]}…")
                print(f"            계산값 {want[:32]}…")
                print(f"            {C['y']}→ 비밀키가 다르거나 서명 대상 조합이 다르다{C['0']}")

        # ② 멱등키
        if not idem:
            print(f"  멱등키    {C['r']}✗ 없음{C['0']} — 재시도가 중복 행을 만든다")
        elif idem in SEEN:
            print(f"  멱등키    {C['y']}↺ 재시도{C['0']}  {idem}")
            print(f"            {C['d']}처음 받은 시각 {SEEN[idem]}{C['0']}")
            print(f"            {C['y']}→ Django 는 여기서 새 행을 만들면 안 된다{C['0']}")
        else:
            SEEN[idem] = time.strftime("%H:%M:%S")
            print(f"  멱등키    {C['g']}✓{C['0']} {idem}")

        # ③ 순서 — I-1 이 I-2 보다 먼저여야 한다 (명세 21장)
        ORDER.append(path)
        if path.endswith("/dicom-instances"):
            if "/internal/v1/storage-objects" in ORDER[:-1]:
                print(f"  순서      {C['g']}✓ I-1 이 먼저 왔다{C['0']}")
            else:
                print(f"  순서      {C['r']}✗ I-1 없이 I-2 가 왔다{C['0']} "
                      f"— 명세 21장 위반")

        # ④ 본문
        try:
            obj = json.loads(body)
            print(f"  본문 ({len(body)} bytes)")
            for k, v in obj.items():
                if v is None or v == "" or v == []:
                    print(f"    {C['d']}{k:26} (비어 있음){C['0']}")
                else:
                    s = json.dumps(v, ensure_ascii=False)
                    if len(s) > 90:
                        s = s[:90] + "…"
                    print(f"    {k:26} {s}")
            # 맘모에서 특히 중요한 것 — 화소 간격
            if "pixel_spacing" in obj:
                if obj.get("pixel_spacing"):
                    print(f"  {C['g']}화소 간격 있음{C['0']} "
                          f"{obj['pixel_spacing']} mm/px "
                          f"({obj.get('pixel_spacing_tag')})")
                else:
                    print(f"  {C['y']}⚠ 화소 간격 없음 — 해상도 보정 불가{C['0']}")
        except Exception as e:
            print(f"  본문      {C['r']}JSON 이 아니다{C['0']}: {e}")
            print(f"            {body[:200]!r}")

        if path in self.fail_paths:
            print(f"  {C['r']}→ 500 을 돌려준다 (--fail 지정){C['0']}")
            self.send_response(500)
        elif not ok:
            print(f"  {C['r']}→ 401 을 돌려준다 (서명 불일치){C['0']}")
            self.send_response(401)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(
            {"fake_django": True, "received": len(ORDER),
             "idempotency_keys": len(SEEN)}).encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--host", default="127.0.0.1",
                    help="컨테이너 안에서는 0.0.0.0 이어야 다른 컨테이너가 붙는다. "
                         "기본값이 127.0.0.1 인 것은 실수로 밖에 열지 않기 위해서다")
    ap.add_argument("--secret", default="dev-secret",
                    help="Go 의 CALLBACK_SECRET 과 같아야 한다")
    ap.add_argument("--fail", action="append", default=[],
                    help="이 경로에는 500 을 돌려준다 (여러 번 지정 가능)")
    a = ap.parse_args()

    Handler.secret = a.secret.encode()
    Handler.fail_paths = set(a.fail)

    print(f"{C['b']}가짜 Django{C['0']}  {a.host}:{a.port}")
    print(f"  받는 경로")
    for p, n in [("/internal/v1/storage-objects", "I-1 저장 객체"),
                 ("/internal/v1/dicom-instances", "I-2 DICOM 메타"),
                 ("/internal/v1/notifications/delivery", "I-3 알림 전달"),
                 ("/internal/v1/reports/{id}/narrative", "I-4 리포트 서술")]:
        print(f"    {p:42} {n}")
    if a.fail:
        print(f"  {C['y']}실패시킬 경로: {', '.join(a.fail)}{C['0']}")
    print(f"  {C['d']}Ctrl-C 로 종료{C['0']}\n")

    try:
        HTTPServer((a.host, a.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print(f"\n\n받은 콜백 {len(ORDER)}건 · 서로 다른 멱등키 {len(SEEN)}개")
        sys.exit(0)


if __name__ == "__main__":
    main()
