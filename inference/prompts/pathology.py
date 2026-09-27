"""병리(소켓 1·2) 판독 결과 → 소견문.

소켓 1 로 부르든 2 로 부르든 같은 dict 가 나온다. 조직 분할 없이 세포만
검출하면 sTIL 의 분모가 없어서, 두 소켓이 한 파이프라인을 공유한다.

AI 계측 TIL 면적비 — 이 이미지 한 장에서 계산한 값이다 (2026-09-10 확정)

  「sTIL」이라 부르지 않는다(09-28). 임상 sTIL 은 병리의사의 육안 점수이고
  치료 기준값도 그 점수로 만들어졌다. 계측값은 핵 면적 기준이라 그보다
  낮게 나와, 같은 이름이면 그 기준에 대어 틀리게 읽힌다.

  stil_percent = immune_nucleus_area_px × nc_ratio(1.5) / stroma_area_px × 100

⚠ stil_interval_low/high 는 싣지 않는다
  세포 분류 헤드에만 드롭아웃을 켜고 50회 돌린 값의 2.5~97.5 백분위수다.
  담기는 것은 분류기의 흔들림뿐이고, 조직 분할·세포 검출·nc_ratio 가정은
  들어 있지 않다. 무엇보다 크롭 위치가 빠져 있다 — 같은 슬라이드도 자른
  자리에 따라 0~36% 로 요동친다(CV≈1.0).
  8.4~13.6 같은 좁은 구간을 보이면 실제보다 정밀해 보인다. PA-N02 로
  대신 안내한다.

  stil_percent 는 드롭아웃을 끄고 따로 한 번 계산한다. 그래서 구간의
  중심(stil_mc_mean)과 값이 다르다.
"""
from prompts import base

# 2026-09-09.a  신규. sTIL 수치 제외 판
# 2026-09-09.b  base.SYSTEM — 번호 붙은 항목은 항목마다 문장을 끊는다
# 2026-09-10.a  sTIL 복원. 구간과 nc_ratio 는 뺀다
# 2026-09-20.a  plain() — 환자용은 「나왔다」까지만 쓴다
# 2026-09-28.a  sTIL → 「AI 계측 TIL 면적비」 · PA-N02 척도 안내
VERSION = "pathology-2026-09-28.a"

SOCKET_IDS = {"1", "2"}

# 간질이 없으면 sTIL 이 null 이 되지만 세포 수는 나온다. 둘 다 있어야 문장이 선다.
REQUIRED = ("stroma_status", "n_cells_total")

# 소견문에 내보내지 않는 값
#   stil_interval_* · stil_mc_mean · stil_mc_std     위 ⚠ 참조
#   nc_ratio · immune_*_area_px                     계산 재료. 소견이 아니다
#   tissue_mask                                     ndarray. 항상 null 이다
#   model_version · predict_seconds                 응답 봉투가 따로 싣는다


def values(r: dict) -> list[tuple[str, str]]:
    if r.get("stroma_status") != "ok":
        return [("간질 검출", "없음"),
                ("평가", "간질이 없어 비율 산출 불가")]

    return [("간질 검출", "있음"),
            ("AI 계측 TIL 면적비", f"{r.get('stil_percent')} %"),
            ("종양 면적 비율", f"{r.get('tsr_tumor_percent')} %"),
            ("간질 면적 비율", f"{r.get('tsr_stroma_percent')} %"),
            ("전체 세포 수", f"{r.get('n_cells_total')}개"),
            ("TIL 세포 수", f"{r.get('n_cells_til')}개"),
            ("간질 내 TIL 세포 수", f"{r.get('n_cells_til_stromal')}개"),
            ("배율", f"{r.get('mpp')} mpp"),
            ("분석 영역", f"{r.get('img_w')} × {r.get('img_h')} px")]


def facts(r: dict) -> list[str]:
    if r.get("stroma_status") != "ok":
        return ["간질이 검출되지 않았습니다.",
                "간질 면적이 분모이므로 비율을 산출하지 못했습니다."]

    return [f"이 크롭의 AI 계측 TIL 면적비는 {r.get('stil_percent')}% 입니다.",
            f"종양 면적 비율 {r.get('tsr_tumor_percent')}%, "
            f"간질 면적 비율 {r.get('tsr_stroma_percent')}% 입니다.",
            f"전체 세포 {r.get('n_cells_total')}개 중 "
            f"TIL 세포는 {r.get('n_cells_til')}개입니다.",
            f"그중 간질 내 TIL 세포는 {r.get('n_cells_til_stromal')}개입니다.",
            f"분석 영역은 {r.get('img_w')} × {r.get('img_h')} px, "
            f"배율은 {r.get('mpp')} mpp 입니다."]

def plain(r: dict) -> list[str]:
    """환자용 값. 「나왔다」까지만 쓴다.

    sTIL · 종양 면적 비율은 환자에게 그대로 옮길 말이 없다. 순화를 모델에
    맡겼더니 종양 면적 0.0% 를 「암세포가 발견되지 않았습니다」로 썼다
    (2026-09-20). 그 한 줄이 이 함수가 있는 이유다.
    """
    if r.get("stroma_status") != "ok" :
        return ["조직 검사에서 판정에 필요한 부분이 충분하지 않았습니다."]
    return ["조직 검사 결과가 나왔습니다.",
            "결과의 의미는 담당 의사의 설명으로 확인해 주십시오."]

NOTES = {
    "PA-N01": "간질이 검출되지 않아 「평가 불가」입니다. 0% 가 아닙니다.",
    "PA-N02": "AI 계측 TIL 면적비는 핵 면적 기준 계측값으로, 병리의사 육안 sTIL보다 낮게 나옵니다. 같은 조직도 잘라낸 자리에 따라 크게 달라집니다.",
    "PA-N03": "종양·간질 비율은 종양÷(종양+간질) 한 가지 정의를 두 관점으로 적은 값입니다. 합이 100% 가 됩니다.",
    "PA-N04": "최종 판정은 의사가 합니다.",
}


def notes(r: dict) -> list[dict]:
    # 간질이 없으면 sTIL 도 비율도 안 나간다. 그 둘을 설명하는 안내도 뺀다.
    if r.get("stroma_status") != "ok":
        return [base.note(NOTES, "PA-N01"), base.note(NOTES, "PA-N04")]
    return [base.note(NOTES, "PA-N02"),
            base.note(NOTES, "PA-N03"),
            base.note(NOTES, "PA-N04")]


def numbers(r: dict) -> list[str]:
    """소견에 그대로 남아 있어야 하는 값."""
    if r.get("stroma_status") != "ok":
        return []
    vals = [r.get("stil_percent"),
            r.get("tsr_tumor_percent"), r.get("tsr_stroma_percent"),
            r.get("n_cells_total"), r.get("n_cells_til"),
            r.get("n_cells_til_stromal"), r.get("mpp")]
    return [str(v) for v in vals if v is not None]