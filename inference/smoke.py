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
# 리포트 서버는 별도 프로세스라 따로 확인해야 한다. 8001 만 보면
# report.py · prompts 의 오타가 배포를 그냥 통과한다 — 09-16 에 두 번 그랬다.
REPORT = "http://127.0.0.1:8002"

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
    
def post_report(socket_id: str, result: dict) :
    """리포트 서버에 판독 결과 한 벌을 넘긴다.

    본문 열쇠가 둘이어야 한다 — 하나면 FastAPI 가 본문 전체를 result 에 담는다.
    """
    body = json.dumps({"result": result, "evidence": []}).encode()
    req = urllib.request.Request(
        f"{REPORT}/report/{socket_id}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try :
        with urllib.request.urlopen(req, timeout=120) as r:
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
    #
    # 500 이면 urlopen 이 예외를 던진다. 감싸지 않으면 아래 요약도 못 찍고
    # 죽어서, 무엇이 실패했는지가 로그에 안 남는다.
    try :
        with urllib.request.urlopen(f"{BASE}/healthz", timeout=15) as r:
            ok &= check("healthz 가 200", r.status == 200)
    except HTTPError as e :
        ok &= check("healthz 가 200", False, f"HTTP {e.code}")

    # ── 리포트 서버(8002) ─────────────────────────────────────────
    # 맘모 기권을 쓰는 이유 — 지킬 수치가 없어 모델을 안 태운다(report.py).
    # 그래서 Ollama 가 내려가 있어도 이 검사는 서버 코드만 본다.
    status, d = post_report("4b", {"summary": {"abstained": True, "n_lesions": 0},
                                   "lesions": []})
    ok &= check("POST /report/4b 가 200", status == 200, f"HTTP {status}")
    ok &= check("소견문이 비어 있지 않음", bool(d.get("소견")), str(d.get("소견"))[:40])
    ok &= check("뼈대로 나감", d.get("fallback") == "no_numbers_to_verify",
                str(d.get("fallback")))

    # 별칭도 판독 창구와 같아야 한다. 4 로 부르면 5 가 돌아온다.
    status, d = post_report("4", {"lesion_found": False, "grade": {},
                                  "mask_reliability": {}})
    ok &= check("리포트 별칭 4 -> 5", status == 200 and d.get("socket_id") == "5",
                f"HTTP {status} / {d.get('socket_id')}")

        # 소켓 7 — 종합 소견서. 청중 둘을 다 본다.
    # 초음파 병변 한 건이면 지켜야 할 수치가 7개 나온다(등급 + 형태 6).
    #   의사용   그 7개가 소견문에 남아 있어야 한다
    #   환자용   7개가 하나도 없어야 한다
    # 모델이 살아 있으면 검사를 통과한 문장이 나오고, 죽어 있거나 규칙을 어기면
    # 뼈대로 되돌아간다. 세 경우 모두 결론이 같아서 Ollama 없이도 이 검사는 유효하다.
    US7 = {"lesion_found": True,
           "shape": {"max_diameter_px": 160.3, 
                     "area_px": 9599.0,
                     "height_width_ratio": 0.763, 
                     "solidity": 0.812,
                     "boundary_irregularity": 1.164, 
                     "circularity": 0.518},
           "orientation_label": "가로로 긴 형태",
           "grade": {"display": "4~5", "confidence": "보통"},
           "mask_reliability": {"level": "높음"}}
    NUMS = ["4~5", "160.3", "9599.0", "0.763", "0.812", "1.164", "0.518"]

    for audience, keep in (("clinician", True), ("patient", False)) :
        status, d = post_report("7", {"stages": [{"socket": "5", "result": US7}],
                                      "audience": audience})
        text = d.get("소견") or ""
        left = [n for n in NUMS if n in text]
        ok &= check(f"POST /report/7 {audience} 가 200", status == 200,
                    f"HTTP {status} {str(d.get('_body'))[:80] if status != 200 else ''}")
        ok &= check(f"  {audience} 소견문이 비어 있지 않음", bool(text),
                    f"{d.get('fallback')} / {text[:40]}")
        ok &= check(f"  {audience} 수치 {'보존' if keep else '제거'}",
                    len(left) == len(NUMS) if keep else not left,
                    f"7개 중 {len(left)}개 남음 {left if left != NUMS else ''}")
        
    try :
        with urllib.request.urlopen(f"{REPORT}/health", timeout=15) as r:
            ok &= check("리포트 health 가 200", r.status == 200)
    except HTTPError as e :
        ok &= check("리포트 health 가 200", False, f"HTTP {e.code}")
    print(" ---")
    print(" 전부 통과" if ok else "   실패 있음")
    return 0 if ok else 1

if __name__ == "__main__" :
    sys.exit(main())
