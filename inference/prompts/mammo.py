"""맘모그래피(소켓 4b) 판독 결과 → 소견문.

초음파와 달리 병변이 여러 건 나온다. 실측 최대 7건이었다.
서술어 모델에 '소견 없음' 클래스가 없어서, 임계값을 넘는 검출이 없으면
'정상'이 아니라 기권이다 — summary.abstained 가 그것이다.
"""
from prompts import base 

# 2026-09-09.a 신규. base 의 SYSTEM SCHEMA build를 쓴다 
# 2026-09-09.b  base.SYSTEM — 번호 붙은 항목은 항목마다 문장을 끊는다
VERSION = "mammo-2026-09-18"

SOCKET_IDS = {"4b"}

# lesions 는 빈 목록일 수 있다. summary는 항상 있다 
REQUIRED = ("lesions", "summary")

# 소견문에 내보내지 않는 값 
# box, crop : 좌표. 그림으로 보여줄 것 
# score     : 검출 점수, 등급과 혼동됨 
# certainty : 축 확신도 합. 내부 계산용 

def _one(l: dict) -> str :
    """병변 한 건을 한줄로. 서술어는 값만 이어 붙인다.
    
    맘모는 영상 넷(좌우 × CC/MLO)이 한 검진이다. 앱 서버가 넷을 합치면서
    병변마다 image 를 붙여 준다 — 그게 없으면 좌우를 구분할 수 없어
    소견문으로 못 쓴다. 한 장만 보낸 경우에는 image 가 없고, 그때는
    예전처럼 종류부터 시작한다.
    """
    parts = []
    img = l.get("image") or {}
    if img.get("laterality") or img.get("view") :
        side = {
            "left": "좌측",
            "right": "우측"
        }.get(img.get("laterality"), "")
        parts.append(f"{side} {img.get('view') or ''}".strip())
    parts.append(str(l.get("kind")))
        
    if l.get("birads") :
        parts.append(f"BI-RADS {l['birads']}")
    dd = l.get("descriptors") or {}
    if dd:
        parts.append(" · ".join(str(v.get("value")) for v in dd.values()))
    if l.get("biopsy") :
        parts.append("생검 권고")
    if l.get("confidence") == "low":
        parts.append("확신도 낮음")
    return " / ".join(parts)

def values(r:dict) -> list[tuple[str, str]]:
    """모델에 넘길 판독값, 병변마다 한 줄씩 붙인다"""
    s = r.get("summary") or {} 
    lesions = r.get("lesions") or [] 
    
    if s.get("abstained") :
        return [("병변", "검출 안 됨"),
                ("사유", str(s.get("abstain_reason")))]
        
    out = [("병변 수", f"{s.get('n_lesions')}건"),
           ("최고 등급", f"BI-RADS {s.get('max_birads')}"),
           ("생검 권고", "있음" if s.get("biopsy") else "없음")]
    for l in lesions:
        out.append((f"병변 {l.get('id')}", _one(l)))
    return out

def facts(r:dict) -> list[str]: 
    """뼈대 문장, 모델이 실패하면 이거 그대로 나감"""
    s = r.get("summary") or {}
    lesions = r.get("lesions") or []
    
    if s.get("abstained") :
        return ["임계값을 넘는 검출이 없어 판정하지 않았습니다.",
                "정상이라는 뜻은 아닙니다"]
        
    out = [f"병변 {s.get('n_lesions')}건이 검출되었습니다.", 
           f"최고 등급은 BI-RADS {s.get('max_birads')} 입니다."]
    for l in lesions:
        out.append(f"병변 {l.get('id')}: {_one(l)}.")
    if s.get("biopsy") :
        out.append("생검 권고 대상 병변이 있습니다")
    return out 

NOTES = {
    "MG-N01": "검출이 없으면 기권입니다. 정상이라는 판정이 아닙니다. "
              "서술어 모델에 '소견 없음' 항목이 없습니다.",
    "MG-N02": "확신도가 낮은 병변이 {n}건 있습니다. 해당 서술어는 직접 확인하십시오.",
    "MG-N03": "픽셀 간격 정보가 없어 실제 크기로 환산하지 못했습니다.",
    "MG-N04": "등급은 서술어를 규칙표에 넣어 얻은 값입니다. 직접 예측한 등급이 아닙니다.",
    "MG-N05": "최종 판정은 의사가 합니다.",
}

def notes(r:dict) -> list[dict]: 
    s = r.get("summary") or {}
    lesions = r.get("lesions") or [] 
    out = [] 
    
    if s.get("abstained"): 
        out.append(base.note(NOTES, "MG-N01"))
    low=sum(1 for l in lesions if l.get("confidence") == "low")
    if low:
        out.append(base.note(NOTES, "MG-N02", n=low))
    if not (r.get("image") or {}).get("pixel_spacing_mm"):
        out.append(base.note(NOTES, "MG-N03"))
    if lesions:
        out.append(base.note(NOTES, "MG-N04"))
    
    out.append(base.note(NOTES, "MG-N05"))
    return out 

def numbers(r:dict) -> list[str]:
    """소견에 그대로 남아 있어야 하는 값.

    ⚠ BI-RADS 값은 "4c" · "5" 처럼 짧다. 우연히 다른 자리에 같은 글자가 있으면
      검사를 통과해 버린다 — 잘못 걸러 낼 위험(거짓 실패)은 없고 놓칠 위험만
      있다. 뼈대 되돌리기가 최후 방어선이므로 이대로 둔다.
    """
    s = r.get("summary") or {} 
    if s.get("abstained") :
        return [] 
    vals = [s.get("n_lesions"), s.get("max_birads")]
    for l in r.get("lesions") or []:
        vals.append(l.get("birads"))
        # 서술어도 지킨다. 모델이 병변을 묶으면 여기서 걸린다 —
        # 09-09 에 4B 가 6건을 두 묶음으로 요약하며 2건의 서술어를 지웠다.
        vals += [v.get("value") for v in (l.get("descriptors") or {}).values()]
    return [str(v) for v in vals if v is not None]