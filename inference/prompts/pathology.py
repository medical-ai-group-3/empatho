"""병리(소켓 1·2) 판독 결과 → 소견문.

소켓 1 로 부르든 2 로 부르든 같은 dict 가 나온다. 조직 분할 없이 세포만
검출하면 sTIL 의 분모가 없어서, 두 소켓이 한 파이프라인을 공유한다.

⚠ sTIL 수치를 싣지 않는다 (2026-09-09 현재)
  서빙이 내는 stil_percent 는 핵 기준값에 nc_ratio(1.5)를 곱한 값이다.
  검증 결과 GT 스케일에 맞추려면 핵 기준값에 k*(12.2)를 곱해야 하고,
  서빙이 그 방식으로 교체될 예정이다. 필드 이름은 stil_percent 그대로라
  응답만 보고는 어느 판인지 구분할 수 없다.
  「병리소켓 최종요약」 문서가 「코드 반영 전까지 이 필드를 그대로 화면에
  노출하지 말 것」이라고 못 박고 있으므로, 교체가 확인될 때까지 뺀다.

  교체되면 할 일
    ① model_version.pipeline_version 이 올라갔는지 확인한다
       (현재 stil-serving-1.0.0)
    ② values·facts 에 sTIL 을 넣고 PA-N02 를 뺀다
    ③ 오차 범위를 쓸 때 「신뢰구간」이라 부르지 않는다 — 세포 분류기
       재현성 하한일 뿐이다
"""
from prompts import base

# 2026-09-09.a  신규. sTIL 수치 제외 판
# 2026-09-09.b  base.SYSTEM — 번호 붙은 항목은 항목마다 문장을 끊는다
VERSION = "pathology-2026-09-09.b"

SOCKET_IDS = {"1", "2"}

# 간질이 없으면 sTIL 이 null 이 되지만 세포 수는 나온다. 둘 다 있어야 문장이 선다.
REQUIRED = ("stroma_status", "n_cells_total")

# 소견문에 내보내지 않는 값
#   stil_percent · stil_mc_mean · stil_interval_*   위 ⚠ 참조
#   tissue_mask                                     ndarray. 항상 null 이다
#   model_version · predict_seconds                 응답 봉투가 따로 싣는다


def values(r: dict) -> list[tuple[str, str]]:
    if r.get("stroma_status") != "ok":
        return [("간질 검출", "없음"),
                ("평가", "간질이 없어 비율 산출 불가")]

    return [("간질 검출", "있음"),
            ("종양 면적 비율", f"{r.get('tsr_tumor_percent')} %"),
            ("간질 면적 비율", f"{r.get('tsr_stroma_percent')} %"),
            ("전체 세포 수", f"{r.get('n_cells_total')}개"),
            ("TIL 세포 수", f"{r.get('n_cells_til')}개"),
            ("간질 내 TIL 세포 수", f"{r.get('n_cells_til_stromal')}개"),
            ("핵/세포질 비", str(r.get("nc_ratio"))),
            ("배율", f"{r.get('mpp')} mpp"),
            ("분석 영역", f"{r.get('img_w')} × {r.get('img_h')} px")]


def facts(r: dict) -> list[str]:
    if r.get("stroma_status") != "ok":
        return ["간질이 검출되지 않았습니다.",
                "간질 면적이 분모이므로 비율을 산출하지 못했습니다."]

    return [f"종양 면적 비율 {r.get('tsr_tumor_percent')}%, "
            f"간질 면적 비율 {r.get('tsr_stroma_percent')}% 입니다.",
            f"전체 세포 {r.get('n_cells_total')}개 중 "
            f"TIL 세포는 {r.get('n_cells_til')}개입니다.",
            f"그중 간질 내 TIL 세포는 {r.get('n_cells_til_stromal')}개입니다.",
            f"분석 영역은 {r.get('img_w')} × {r.get('img_h')} px, "
            f"배율은 {r.get('mpp')} mpp 입니다."]


NOTES = {
    "PA-N01": "간질이 검출되지 않아 「평가 불가」입니다. 0% 가 아닙니다.",
    "PA-N02": "sTIL 수치는 캘리브레이션 교체 중이라 이 리포트에 싣지 않았습니다.",
    "PA-N03": "종양·간질 비율은 두 정의를 모두 산출한 값입니다. 정의 확정 전입니다.",
    "PA-N04": "최종 판정은 의사가 합니다.",
}


def notes(r: dict) -> list[dict]:
    out = []
    if r.get("stroma_status") != "ok":
        out.append(base.note(NOTES, "PA-N01"))
    out.append(base.note(NOTES, "PA-N02"))
    out.append(base.note(NOTES, "PA-N03"))
    out.append(base.note(NOTES, "PA-N04"))
    return out


def numbers(r: dict) -> list[str]:
    """소견에 그대로 남아 있어야 하는 값."""
    if r.get("stroma_status") != "ok":
        return []
    vals = [r.get("tsr_tumor_percent"), r.get("tsr_stroma_percent"),
            r.get("n_cells_total"), r.get("n_cells_til"),
            r.get("n_cells_til_stromal"), r.get("mpp")]
    return [str(v) for v in vals if v is not None]