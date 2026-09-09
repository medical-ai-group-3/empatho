"""유방 MRI(소켓 3) 판독 결과 → 소견문.

조영 후 볼륨이 없으면 phases=1 이고 밀도만 낸다. tumor 는 null 이다.
둘 다 있으면 phases=2 이고 병변이 채워진다.

⚠ 메시(breast_mesh · dense_tissue_mesh)는 소견문에 넣지 않는다. 좌표
  수백만 개라 프롬프트가 터지고, 문장으로 옮길 값도 아니다.
⚠ patient_id 는 설계상 "unknown" 이다. 추론 서버에 환자 식별자를 보내지
  않는다 — 소견문에도 넣지 않는다.
"""
from prompts import base

VERSION = "mri-2026-09-09.a"

SOCKET_IDS = {"3"}

REQUIRED = ("phases", "density")

def values(r:dict) -> list[tuple[str, str]]: 
    d = r.get("density") or {} 
    tumor = r.get("tumor")
    
    out = [("조영 단계", "조영 전·후 2단계" if r.get("phases") == 2 else "조영 전 1단계"), 
           ("슬라이스 수", f"{r.get('n_slices')}장"),
           ("유방 부피", f"{d.get('breast_voxels')} 복셀"),
           ("치밀 조직 부피", f"{d.get('dense_voxels')} 복셀"),
           ("치밀도", f"{d.get('dense_density_pct')} %")]
    
    if not tumor: 
        out.append(("병변", "판독 안 함 (조영 후 볼륨 없음)"))
        return out 
    
    out.append(("병변 수", f"{tumor.get('lesion_count')}건"))
    if tumor.get("location_note"):
        out.append(("위치", str(tumor["location_note"])))
    return out 

def facts(r:dict) -> list[str]:
    d = r.get("density") or {}
    tumor = r.get("tumor")
    
    out = [f"슬라이스 {r.get('n_slices')}장을 판독했습니다",
           f"유방 부피 {d.get('breast_voxels')} 복셀, "
           f"치밀 조직 {d.get('dense_voxels')} 복셀입니다.",
           f"치밀도는 {d.get('dense_density_pct')}% 입니다."]
    
    if not tumor:
        out.append("조영 후 볼륨이 없어 병변은 판독하지 않았습니다.")
        return out 
    
    out.append(f"병변 {tumor.get('lesion_count')}건이 검출되었습니다.")
    if tumor.get("location_note"):
        out.append(f"{tumor['location_note']}.")
    return out

NOTES = {
    "MR-N01": "조영 후 볼륨이 없어 밀도만 산출했습니다. 병변 유무는 알 수 없습니다.",
    "MR-N02": "부피는 복셀 수이며 mm³ 로 환산하지 않았습니다.",
    "MR-N03": "치밀도는 유방 부피 대비 치밀 조직 부피의 비율입니다. "
              "BI-RADS 밀도 범주와 다릅니다.",
    "MR-N04": "최종 판정은 의사가 합니다.",
}

def notes(r:dict) -> list[dict]:
    out = []
    if not r.get("tumor") :
        out.append(base.note(NOTES, "MR-N01"))
    out.append(base.note(NOTES, "MR-N02"))
    out.append(base.note(NOTES, "MR-N03"))
    out.append(base.note(NOTES, "MR-N04"))
    return out 

def numbers(r:dict) -> list[str]:
    d = r.get("density") or {} 
    tumor = r.get("tumor") or {} 
    vals = [d.get("breast_voxels"), d.get("dense_voxels"),
            d.get("dense_density_pct"), r.get("n_slices")]
    if tumor:
        vals.append(tumor.get("lesion_count"))
    return [str(v) for v in vals if v is not None]