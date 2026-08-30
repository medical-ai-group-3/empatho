"""초음파(소켓 4·5) 판독 결과 → 소견 문장.

용어와 표기 규칙은 models/us/README.md 의 「화면 표기 규칙」에서 가져왔다.
생성 모델은 막지 않으면 근거 없는 해석을 덧붙인다 — 시험에서 solidity 를
'밀도'로, '가로로 긴 병변'을 '세로로 긴'으로 옮기는 것을 확인했다.
"""
import json 

VERSION = "us-2026-08-31.a"

SOCKET_IDS = {"4", "5"}

# 레포트 작성규칙
SYSTEM = """유방 초음파 판독 결과를 의사가 읽을 소견문으로 옮긴다.

용어는 아래를 그대로 쓴다. 다르게 바꾸지 않는다.
  max_diameter_px        최대 직경
  height_width_ratio     종횡비
  solidity               볼록성
  boundary_irregularity  경계 요철도
  circularity            원형도

지킬 것
  주어진 수치만 쓴다. 없는 소견을 만들지 않는다.
  등급은 grade.display 를 그대로 쓴다. 구간 표기를 단일 등급으로 바꾸지 않는다.
  크기 뒤에 px 를 붙인다. mm 로 환산하지 않는다.
  orientation_label 은 주어진 문구를 그대로 쓴다.
  수치를 해석하지 않는다. '불규칙한 경계' 같은 서술어를 만들지 않는다.
  악성 여부를 단정하지 않는다. 최종 판정은 의사가 한다."""
  
# 출력을 JSON 으로 강제한다. 이 모델은 그냥 두면 추론 과정을 본문으로 길게
# 뱉는다 — 시험에서 1,746 토큰 중 대부분이 그것이었다. 스키마를 주면 사라진다.
# 등급을 별도 필드로 둔 이유는, 소견 하나만 요구했더니 등급이 빠졌기 때문이다.
SCHEMA = {
    "type": "object",
    "properties": {
        "소견": {"type": "string"},
        "등급": {"type": "string"},
    },
    "required": ["소견", "등급"],
}

def build(result: dict) -> str: 
    """모델에 넘길 부분만 추린다.
    malignancy 는 아예 빼서 보낸다. 절대값을 신뢰할 수 없는 값이라
    화면에 노출하지 않기로 되어 있고, 안 보내면 쓸 수가 없다.
    쓰지 말라고 말로 막는 것보다 확실하다.
    """
    grade = dict(result.get("grade") or {}) 
    grade.pop("malignancy", None)
    grade.pop("boundary_p", None)
    
    trimmed = {
        "lesion_found": result.get("lesion_found"),
        "grade": grade,
        "shape": result.get("shape"),
        "orientation_label": result.get("orientation_label"),
        "mask_reliability": result.get("mask_reliability"),
    }
    return json.dumps(trimmed, ensure_ascii=False, indent=2)