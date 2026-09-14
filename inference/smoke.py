#!/usr/bin/env python3
"""배포 후 자가 점검 — /healthz 만으로는 /analyze 안의 오타를 못 잡는다.

healthz 는 소켓 표만 읽는다. analyze 안의 잘못된 속성 이름이나 키 이름은
서버가 켜지고 healthz 가 200 을 돌려주는 동안에도 그대로 남아 있다가,
실제 요청이 처음 들어올 때 500 으로 터진다. 한 번 불러 봐야 드러난다.
"""

import io
import json  
import sys
import urllib.request
from urllib.error import HTTPError
from PIL import Image 

BASE = "http://127.0.0.1:8001"

def tiny_png() -> bytes: 
    """8x8 회색 PNG. 레포에 이진 파일을 두지 않으려고 그때그때 만든다."""
    buf = io.BytesIO() 
    Image.new("RGB", (8,8), (128,128,128)).save(buf, format = 'PNG')
    return buf.getvalue() 

def post_image(socket_id: str, data: bytes) :
    """multipart/form-data 로 이미지 한 장을 올린다"""
    b = "----smoke"
    body = (
        f"--{b}\r\n"
        f'Content-Disposition: form-data; name="image"; filename="smoke.png"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + data + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/analyze/{socket_id}",
        data=body, 
        headers={"Content-Type": f"multipart/form-data; boundary={b}"},
    )
    try :
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e :
        return e.code, {"_body": e.read()[:400].decode(errors="replace")}
    
def check(name: str, cond: bool, detail: str = "") -> bool :
    print(f" {'OK  ' if cond else 'FAIL'}  {name}{'   ' + detail if detail else ''}")
    return cond

def main() -> int :
    png = tiny_png()
    ok = True
    
    status, d = post_image("4", png)
    ok &= check("POST /analyze/4 가 200", status == 200, f"HTTP {status}")
    ok &= check("4 -> 5 로 넘김", d.get("socket_id")== "5")
    
    got = d.get("image", {}).get("bytes")
    ok &= check("이미지가 온전히 도착", got == len(png), f"{got} / {len(png)}")
    
    if d.get("abstained") : 
        # 모델이 아직 안 올라간 상태, 왜 기권인지 말해 줘야함 
        ok &= check("기권 이유가 있음", bool(d.get("reason")), str(d.get("reason")))
    else : 
        # 모델이 올라간 상태, 결과와 재현 정보가 다 있어야 한다 
        ok &= check("결과에 등급 포함", "grade" in (d.get("result") or {}))
        ok &= check("lora_version 있음", bool(d.get("lora_version")), str(d.get("lora_version")))
        ok &= check("threshold_version 있음", bool(d.get("threshold_version")), str(d.get("threshold_version")))
        

    # 모르는 소켓은 오류가 아니라 기권이다. 4xx 로 바뀌면 경로가 끊긴다 
    status, d = post_image("zzz", png)
    ok &= check("모르는 소켓도 200 + 기권", 
                status == 200 and d.get("reason") == "unknown_socket", 
                f"HTTP {status} / {d.get('reason')}")
    
        # /healthz 도 확인한다. 오늘 healthz 가 500 인 채로 배포가 두 번 통과했다 —
    # /analyze 만 보면 healthz 안의 오류가 안 잡힌다.
    with urllib.request.urlopen(f"{BASE}/healthz", timeout=15) as r:
        ok &= check("healthz 가 200", r.status == 200)
    print(" ---")
    print(" 전부 통과" if ok else "   실패 있음")
    return 0 if ok else 1

if __name__ == "__main__" :
    sys.exit(main())
