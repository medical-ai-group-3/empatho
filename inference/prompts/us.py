"""초음파(소켓 4·5) 판독 결과 → 소견문.

수치와 판단은 코드가 문장으로 만든다. 모델은 그것을 읽기 좋게 엮기만 한다.
모델에게 수치를 맡겼더니 볼록성 0.914 를 97% 로, 63.9px 를 81.3mm 로
바꿔 쓰는 것을 확인했다. 오류가 아니라 그럴듯한 문장으로 나오므로 위험하다.

AI 의 판단은 이미 판독 결과 안에 있다 — 등급·확신도·마스크 신뢰도가 그것이다.
MedGemma 가 따로 소견을 내면 이 영상을 보지 않은 두 번째 의견이 된다.
"""

# 프롬프트 판. 응답에 실려 나가고 healthz 에도 보인다.
# SYSTEM · SCHEMA · facts 중 하나라도 고치면 반드시 같이 올린다 —
# 같은 판독에서 왜 다른 소견이 나왔는지 추적할 유일한 단서다.
VERSION = "us-2026-08-31.b"

# 이 프롬프트가 담당하는 소켓. report.py 의 PROMPTS 표가 이걸로 만들어진다.
SOCKET_IDS = {"4", "5"}


def facts(r: dict) -> list[str]:
    """수치와 판단을 사실 문장으로. 여기서 나온 숫자는 틀릴 수 없다."""
    if not r.get("lesion_found"):
        return ["병변이 검출되지 않았습니다."]

    s = r.get("shape") or {}
    g = r.get("grade") or {}
    out = ["병변이 검출되었습니다."]
    
    # 마스크가 불안정하면 판독이 shape 를 null 로 준다. 없는 값을 문장에 박으면 
    # 최대 직경 nonepx 이 그래로 의사에게 전달된다.
    if s :
        out.append(f"최대 직경 {s.get('max_diameter_px')}px, "
                   f"면적 {s.get('area_px')}px 입니다.")
        out.append(f"종횡비 {s.get('height_width_ratio')}, 볼록성 {s.get('solidity')}, "
                   f"경계 요철도 {s.get('boundary_irregularity')}, "
                   f"원형도 {s.get('circularity')} 입니다.")
        
    if r.get("orientation_label") :
        out.append(f"{r['orientation_label']}입니다.")
        
    out.append(f"BI-RADS {g.get('display')} 이며 "
               f"등급 확신도는 {g.get('confidence')}입니다.")
    out.append(f"마스크 신뢰도는 {(r.get('mask_reliability') or {}).get('level')}입니다.")
    
    return out


def notes(r: dict) -> list[str]:
    """주의사항. 학습 쪽 문서에 근거가 있는 것만 넣는다."""
    g = r.get("grade") or {}
    mr = r.get("mask_reliability") or {}
    poly = r.get("polygons") or {}
    out = []

    if g.get("value") in (3, 4):
        out.append("중간 등급에서는 등급 확신도가 '높음'으로 나오지 않습니다. "
                   "CORAL 구조상 그러하며 판정 오류가 아닙니다.")
    if g.get("is_range"):
        out.append("등급은 구간으로 표기됩니다. 단일 등급으로 좁히지 마십시오.")
    if mr.get("dim_shape_metrics"):
        out.append("마스크가 부정확할 수 있어 형태 지표는 참고용으로만 보십시오.")
    if (poly.get("n_components") or 1) > 1:
        out.append(f"마스크가 {poly['n_components']}조각으로 나뉘었습니다.")

    out.append("크기는 픽셀 단위이며 밀리미터가 아닙니다.")
    out.append("최종 판정은 의사가 합니다.")
    return out


def numbers(r: dict) -> list[str]:
    """소견에 그대로 남아 있어야 하는 값. 하나라도 없으면 모델 출력을 버린다."""
    s = r.get("shape") or {}
    g = r.get("grade") or {}
    vals = [g.get("display")]
    if r.get("lesion_found"):
        vals += [s.get("max_diameter_px"), s.get("area_px"),
                 s.get("height_width_ratio"), s.get("solidity"),
                 s.get("boundary_irregularity"), s.get("circularity")]
    return [str(v) for v in vals if v is not None]


# 모델이 지킬 규칙. 매 요청 같은 값이 들어간다.
SYSTEM = """아래 문장들을 하나의 자연스러운 소견문으로 엮는다.

지킬 것
  문장에 있는 숫자를 그대로 옮긴다. 바꾸거나 단위를 환산하지 않는다.
  주어진 문장에 없는 내용을 보태지 않는다.
  수치가 무엇을 뜻하는지 해석하지 않는다.
  악성 여부를 말하지 않는다.
  존댓말로 쓴다."""

# 응답 형식 강제. 이게 없으면 모델이 생각 과정과 머리말을 같이 뱉는다.
# 필드가 「소견」 하나뿐인 이유 — 안내는 코드가 쓰고 모델을 거치지 않는다.
SCHEMA = {
    "type": "object",
    "properties": {"소견": {"type": "string"}},
    "required": ["소견"],
}

def build(fact_lines: list[str]) -> str:
    # 주의사항은 모델에 넘기지 않는다. 우리가 쓴 문장이 그대로 나가야 한다.
    return "[사실]\n" + "\n".join(fact_lines)