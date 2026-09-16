"""초음파(소켓 4·5) 판독 결과 → 소견문.

수치와 판단은 코드가 만든다. 모델은 판독값을 읽고 문장으로 서술만 한다.
모델에게 수치를 맡겼더니 볼록성 0.914 를 97% 로, 63.9px 를 81.3mm 로
바꿔 쓰는 것을 확인했다. 오류가 아니라 그럴듯한 문장으로 나오므로 위험하다.

AI 의 판단은 이미 판독 결과 안에 있다 — 등급·확신도·마스크 신뢰도가 그것이다.
MedGemma 가 따로 소견을 내면 이 영상을 보지 않은 두 번째 의견이 된다.
"""
from prompts import base

# 프롬프트 판. 응답에 실려 나가고 healthz 에도 보인다.
# SYSTEM · SCHEMA · values · facts 중 하나라도 고치면 반드시 같이 올린다 —
# 같은 판독에서 왜 다른 소견이 나왔는지 추적할 유일한 단서다.
#
# 2026-09-04.a  SYSTEM 에 근거 표시 규칙 추가 · build 가 근거 목록도 받는다
# 2026-09-09.a  근거 표시 규칙 삭제 · 모델에 완성 문장 대신 판독값을 넘긴다
#               SYSTEM·SCHEMA·build 는 base 로 옮겼다

# 2026-09-09.b  base.SYSTEM — 번호 붙은 항목은 항목마다 문장을 끊는다
VERSION = "us-2026-09-09.b"

# 이 프롬프트가 담당하는 소켓, prompts/__init__.py 의 표가 이걸로 만들어진다 
SOCKET_IDS = {"4","5"}

# result 에 반드시 있어야하는 열쇠 없으면 입력 모양이 틀린것 
REQUIRED = ("lesion_found", "grade")

# 화면 소견문에 내보내지 않는 값 
# grade.malignancy = 참고용 확률
# grade.boundary_p = CORAL 경계 확률 3개
# _mask, polygons = 좌표, 문장이 아니라 그림 

def values(r: dict) -> list[tuple[str, str]]:
    """모델에 넘길 판독값. (이름, 값) 짝으로 낸다.

    facts() 와 나누는 이유
      facts()   완성된 문장. 뼈대를 만든다 — 모델이 실패하면 이것이 그대로 나간다.
      values()  값만. 문장을 짓는 일이 모델 몫이 된다.

    09-08 실측 — 완성 문장을 주면 모델이 그대로 베낀다(온도 0 에서 50/50 동일).
    값만 주니 어미와 연결을 다시 썼고 수치는 150회 전부 보존됐다.
    """
    s = r.get("shape") or {}
    g = r.get("grade") or {}
    mr = r.get("mask_reliability") or {} 
    
    out = [("병변", "검출됨" if r.get("lesion_found") else "검출 안됨")]
    if not r.get("lesion_found") :
        return out 
    
    # shape가 null로 오는 경우가 종종 있음 
    # 없는 값을 넘기면 모델이 최대 직경 None px 로 써버린다 
    if s: 
        out += [("최대 직경", f"{s.get('max_diameter_px')} px"),
                ("면적", f"{s.get('area_px')} px"),
                ("종횡비", str(s.get("height_width_ratio"))),
                ("볼록성", str(s.get("solidity"))),
                ("경계 요철도", str(s.get("boundary_irregularity"))),
                ("원형도", str(s.get("circularity")))]
    if r.get("orientation_label") :
        out.append(("방향", r["orientation_label"]))
    out += [("BI-RADS", str(g.get("display"))),
            ("등급 확신도", str(g.get("confidence"))),
            ("마스크 신뢰도", str(mr.get("level")))]
    return out 

def facts(r: dict) -> list[str]: 
    """뼈대 문장. 모델을 못 쓰거나 수치가 바뀌면 이것이 그대로 나간다.

    읽기에 딱딱할 뿐 내용은 빠지지 않는다. 그래서 모델이 없어도 리포트가 나간다.
    """
    if not r.get("lesion_found") :
        return ["병변이 검출되지 않았습니다."]
    
    s = r.get("shape") or {}
    g = r.get("grade") or {} 
    out = ["병변이 검출되었습니다."]
    
    if s: 
        out.append(f"최대 직경 {s.get('max_diameter_px')}px, "
                   f"면적 {s.get('area_px')}px 입니다")
        out.append(f"종횡비 {s.get('height_width_ratio')}, 볼록성 {s.get('solidity')}, "
                   f"경계 요철도 {s.get('boundary_irregularity')}, "
                   f"원형도 {s.get('circularity')} 입니다.")
        
    if r.get("orientation_label"): 
        out.append(f"{r['orientation_label']}입니다.")
    out.append(f"BI-RADS {g.get('display')} 이며 "
                f"등급 확신도는 {g.get('confidence')}입니다")
    out.append(f"마스크 신뢰도는 {(r.get('mask_reliability') or {}).get('level')}입니다.")
    return out
    
# 안내 문구표. 모델을 거치지 않고 이 문장이 그래도 나간다 
# 문구를 고치면 VERSION 도 올린다 
NOTES = { 
        "US-N01" : "중간 등급에서는 등급 확신도가 '높음'으로 나오지 않습니다. "
                    "CORAL 구조상 그러하며 판정 오류가 아닙니다.", 
        "US-N02" : "등급은 구간으로 표기 됩니다. 단일 등급으로 좁히지 마십시오.",
        "US-N03" : "마스크가 부정확할 수 있어 형태 지표는 참고용으로만 보십시오.", 
        "US-N04" : "마스크가 {n}조각으로 나뉘었습니다.",
        "US-N05" : "크기는 픽셀 단위이며 밀리미터가 아닙니다.", 
        "US-N06" : "최종 판정은 의사가 합니다.",
        }

def notes(r: dict) -> list[dict]:
    """주의 사항 : 학습쪽 문서에서 근거가 있는 것만 넣는다"""
    g = r.get("grade") or {} 
    mr = r.get("mask_reliability") or {}
    poly = r.get("polygons") or {}
    out = []
    
    if g.get("value") in (3,4):
        out.append(base.note(NOTES, "US-N01"))
    if g.get("is_range") :
        out.append(base.note(NOTES, "US-N02"))
    if mr.get("dim_shape_metrics") :
        out.append(base.note(NOTES, "US-N03"))
    if (poly.get("n_components") or 1) > 1 :
        out.append(base.note(NOTES, "US-N04", n=poly["n_components"]))
        
    out.append(base.note(NOTES, "US-N05"))
    out.append(base.note(NOTES, "US-N06"))
    return out 

def numbers(r: dict) -> list[str]:
    """소견에 그대로 남아 있어야 하는 값. 하나라도 없으면 모델 출력을 버린다.

    ⚠ 숫자만 본다. 단위는 보지 않으므로 63.9 px 를 63.9 mm 로 바꿔도 통과한다.
      단위까지 대조하려면 공백을 지우고 비교해야 해서 report.py 도 같이 고쳐야
      한다 — 별건으로 미뤄 둔 항목이다.
    """
    s = r.get("shape") or {}
    g = r.get("grade") or {}
    vals = [g.get("display")]
    if r.get("lesion_found") :
        vals += [s.get("max_diameter_px"), s.get("area_px"),
                 s.get("height_width_ratio"), s.get("solidity"),
                 s.get("boundary_irregularity"), s.get("circularity")]
    return [str(v) for v in vals if v is not None]