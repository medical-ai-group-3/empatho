#!/usr/bin/env python3
"""티켓 발급 — Django 가 할 일을 시험 동안 대신한다.

Go 는 자체 권한 판정을 하지 않는다(명세 19-1). Django 가 서명한 티켓만
검증한다. 그 Django 가 아직 없으므로 시험용으로 여기서 서명한다.

**Django 쪽 구현은 이것과 같으면 된다.** PyJWT 를 쓴다면

    import jwt
    jwt.encode(claims, key, algorithm="HS256")

가 그대로 맞는다. 여기서는 의존성 없이 표준 라이브러리로만 만든다.

⚠ 시험용이다. 운영 티켓을 이걸로 만들지 말 것.

사용
    # 업로드용
    python3 mint_ticket.py --purpose dicom_upload \\
        --patient P-77 --scope STUDY-1 --prefix patients/P-77/studies/STUDY-1

    # 다운로드용 (접두사가 권한 경계다)
    python3 mint_ticket.py --purpose download \\
        --patient P-77 --scope STUDY-1 --prefix patients/P-77/studies/STUDY-1

    # 리포트 서술용 — scope 가 report_id 와 같아야 한다
    python3 mint_ticket.py --purpose report_narrative --scope R-1 --patient P-77
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import time


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def mint(key: str, claims: dict) -> str:
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"},
                          separators=(",", ":")).encode())
    pay = b64(json.dumps(claims, separators=(",", ":"),
                         ensure_ascii=False).encode())
    signing = f"{head}.{pay}"
    sig = hmac.new(key.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{b64(sig)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.getenv("TICKET_KEY", "dev-key"),
                    help="Go 의 TICKET_KEY 와 같아야 한다")
    ap.add_argument("--purpose", required=True,
                    help="dicom_upload · wsi_upload · download · tile · "
                         "report_pdf · prescription_pdf · report_narrative · "
                         "chat · notify")
    ap.add_argument("--patient", default="P-TEST")
    ap.add_argument("--scope", default="S-TEST",
                    help="study_id · report_id · session_id · user_id")
    ap.add_argument("--prefix", default="",
                    help="object_key_prefix. 업로드·다운로드에 필수. "
                         "Go 는 이 아래에만 쓰고 읽는다")
    ap.add_argument("--max-bytes", type=int, default=200 * 1024 * 1024)
    ap.add_argument("--content-type", default="application/dicom")
    ap.add_argument("--ttl", type=int, default=300, help="초. 명세 기본 5분")
    ap.add_argument("--nonce", default="",
                    help="비우면 난수. 재사용 거부를 시험하려면 같은 값을 두 번 쓴다")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    claims = {
        "purpose": a.purpose,
        "patient_id": a.patient,
        "scope_id": a.scope,
        "exp": int(time.time()) + a.ttl,
        "nonce": a.nonce or os.urandom(12).hex(),
    }
    if a.prefix:
        claims["object_key_prefix"] = a.prefix
    if a.max_bytes:
        claims["max_bytes"] = a.max_bytes
    if a.content_type:
        claims["content_type"] = a.content_type

    tok = mint(a.key, claims)
    if a.verbose:
        import sys
        print(json.dumps(claims, ensure_ascii=False, indent=2), file=sys.stderr)
    print(tok)


if __name__ == "__main__":
    main()
