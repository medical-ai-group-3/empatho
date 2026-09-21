"""병원 찾기 — 건강보험심사평가원 「병원정보서비스」 공공데이터를 앱에 붙인다.

    GET /api/v1/hospitals?q=세브란스&region=서울&page=1&page_size=20
        → {items, regions, count, page, page_size, source, note}

원천은 data.go.kr 의 B551182/hospInfoServicev2 다.

── 왜 표를 안 파고 공공데이터를 부르나 ──────────────────────────────

v10 스키마에 병원 표가 없다. 단일 병원 운영이라 「협력 병원 목록」이라는
개념 자체가 없었다. 표를 새로 파면 누가 어떤 기준으로 등록하고 무엇이
바뀌면 고치는지가 따라붙는데, 그것을 정하지 않은 채 표부터 만들면 빈 표가
남는다.

⚠ 그래서 여기 나오는 것은 **협력 병원이 아니라 전국 요양기관**이다. 화면
  문구가 「협력 병원」이면 고쳐야 한다 — 우리가 보증하는 목록이 아니다.
  응답의 note 가 그 말을 싣고 있고, 화면은 그것을 그대로 적는다.

── 위치를 받지 않는다 ───────────────────────────────────────────────

⚠ 이 API 에는 xPos · yPos · radius 로 **좌표 주변을 찾는 기능이 있지만
  쓰지 않는다.** 쓰려면 환자의 좌표를 서버로 보내야 하고, 그 순간 「어디에
  살고 어느 병원을 찾아봤는지」가 우리 로그에 남는다. 따로 동의를 받아야
  하는 정보다.

  화면(screens/Hospitals.jsx)이 이미 그렇게 만들어져 있다 — 병원 좌표만
  받아서 거리는 브라우저에서 잰다. 여기서 좌표를 받기 시작하면 그 설계가
  조용히 무너진다. lat · lng 를 실어 보내는 이유가 그것이다.

── 확인하지 못한 것 ────────────────────────────────────────────────

⚠ 2026-09-21 현재 우리 인증키가 **이 서비스에 등록되어 있지 않다**
  (SERVICE_KEY_IS_NOT_REGISTERED_ERROR). data.go.kr 은 서비스마다 따로
  활용신청을 받는다 — 약 정보(1471000)는 되고 이것(B551182)은 안 된다.

  그래서 아래 칸 이름과 시도 코드는 **문서를 보고 적은 것이고 실제 응답으로
  맞춰 보지 못했다.** 키가 등록되면 가장 먼저 할 일이 그 대조다. 모르는
  모양이 와도 터지지 않게 느슨하게 읽지만, 느슨하다는 것이 맞다는 뜻은
  아니다.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import ApiError
from .permissions import IsAuthenticatedAccount

logger = logging.getLogger(__name__)

SOURCE = "건강보험심사평가원 병원정보서비스"

#: 화면 맨 아래 한 줄. **「협력 병원」이 아니라는 말이 여기 있다.**
#: 서버가 보내는 이유는 문구가 바뀔 때 앱 배포를 기다리지 않으려는 것이다.
NOTE = ("건강보험심사평가원이 공개한 전국 요양기관 정보입니다. "
        "우리 병원의 협력 기관 목록이 아니며, 진료 시간과 휴무는 "
        "방문 전에 해당 기관에 확인해 주세요.")

#: 시도 이름 → 심평원 sidoCd.
#:
#: ⚠ 문서를 보고 적었고 **실제 응답으로 대조하지 못했다**(머리말 참고).
#:   틀린 코드가 있으면 그 지역만 결과가 비는데, 화면에서는 「그 지역에
#:   병원이 없다」와 똑같아 보인다. 키가 등록되면 17 개를 한 번씩 눌러 볼 것.
SIDO = {
    "서울": "110000", "부산": "210000", "대구": "220000", "인천": "230000",
    "광주": "240000", "대전": "250000", "울산": "260000", "세종": "410000",
    "경기": "310000", "강원": "320000", "충북": "330000", "충남": "340000",
    "전북": "350000", "전남": "360000", "경북": "370000", "경남": "380000",
    "제주": "390000",
}

#: 화면의 지역 칩. 「전체」가 맨 앞이다 — Hospitals.jsx 가 그 값을 빈
#: 문자열로 바꿔 서버에 안 보낸다.
REGIONS = ["전체"] + list(SIDO)

#: 한 번에 가져올 수 있는 수. 화면이 한 번에 그릴 수 있는 양을 넘기지 않는다.
MAX_PAGE_SIZE = 50


def one_or_many(value):
    """공공데이터의 items 를 **늘 목록으로** 만든다.

    ⚠ 이 계열 API 는 결과가 하나면 item 을 목록이 아니라 **낱개 dict** 로
      준다. 목록으로만 읽으면 「한 건 찾았을 때만 터지는」 버그가 되는데,
      검색 결과가 하나인 경우는 드물어서 한참 뒤에야 드러난다.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def fetch(params):
    """공공데이터를 부른다. 응답은 파싱된 body.

    ⚠ 이 API 도 **실패를 200 에 실어 보낸다**(약 정보와 같다). 키가 잘못
      됐거나 한도를 넘겨도 본문만 오류문이라, urlopen 의 예외만 보면
      「결과 없음」으로 흘러가 화면이 조용히 빈다. 본문을 열어 보고 끊는다.
    """
    key = settings.HOSPITAL_API_KEY
    if not key:
        logger.error("HOSPITAL_API_KEY 가 비어 있다 — 병원 정보를 가져올 수 없다")
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE",
                       "병원 찾기가 설정되어 있지 않습니다.")

    # ⚠ serviceKey 를 urlencode 에 함께 넣지 않는다 — 포털이 주는 키에 이미
    #   인코딩이 섞여 있으면 한 번 더 인코딩돼 서명이 깨진다. (drugs.py 와 같다)
    query = urllib.parse.urlencode({**params, "_type": "json"})
    url = "%s/getHospBasisList?serviceKey=%s&%s" % (
        settings.HOSPITAL_API_BASE.rstrip("/"),
        urllib.parse.quote(key, safe="-_.~"), query)

    try:
        with urllib.request.urlopen(url, timeout=settings.HOSPITAL_API_TIMEOUT_SEC) as res:
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        logger.error("[hospitals] 공공데이터 %s: %s", e.code, body)
        # 403 + SERVICE_KEY_IS_NOT_REGISTERED_ERROR 가 이리로 온다.
        # 「활용신청이 아직 안 됐다」는 뜻이고 재시도해도 같다.
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("[hospitals] 공공데이터에 못 닿았다 (%s): %s",
                     settings.HOSPITAL_API_BASE, e)
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    try:
        payload = json.loads(raw)
    except ValueError:
        logger.error("[hospitals] JSON 이 아닌 응답: %s", raw[:300])
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    root = payload.get("response", payload)
    header = root.get("header") or {}
    code = header.get("resultCode")
    if code not in (None, "00"):
        logger.error("[hospitals] 공공데이터 resultCode=%s %s",
                     code, header.get("resultMsg"))
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    return root.get("body") or {}


def to_float(value):
    """좌표. 못 읽으면 None — 그 병원만 거리 · 길찾기가 빠진다.

    ⚠ 0 으로 채우지 않는다. 0,0 은 아프리카 앞바다라 「가까운 순」의 맨
      끝이나 맨 앞에 엉뚱하게 붙고, 길찾기를 누르면 지도가 거기로 간다.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize(row):
    """심평원 한 행 → 화면이 읽는 모양 (screens/Hospitals.jsx).

    ⚠ 진료시간(hours)은 **여기 없다.** 심평원은 그것을 세부정보 API
      (getDtlInfo)로 따로 주는데, 병원마다 한 번씩 더 불러야 해서 목록
      한 장에 스무 번을 더 부르게 된다. 공공데이터에는 일일 한도가 있다.
      화면은 hours 가 없으면 그 줄을 그리지 않는다.
    """
    return {
        # 암호화요양기호. 기관마다 고정이라 화면의 열쇠로 쓴다.
        "hospital_id": row.get("ykiho") or row.get("yadmNm"),
        "name": (row.get("yadmNm") or "").strip(),
        # 종별(종합병원 · 병원 · 의원…). 진료과가 아니다 — 진료과는 이
        # 목록에 안 실려 온다.
        "dept": (row.get("clCdNm") or "").strip() or None,
        "address": (row.get("addr") or "").strip() or None,
        "phone": (row.get("telno") or "").strip() or None,
        "region": (row.get("sidoCdNm") or "").strip() or None,
        "district": (row.get("sgguCdNm") or "").strip() or None,
        # ⚠ XPos 가 경도(lng), YPos 가 위도(lat)다. 바꿔 넣으면 길찾기가
        #   엉뚱한 데로 가는데, 한국 안에서는 둘 다 그럴듯한 숫자라
        #   (위도 33~38 · 경도 124~132) 눈으로는 안 보인다.
        "lat": to_float(row.get("YPos")),
        "lng": to_float(row.get("XPos")),
        "url": (row.get("hospUrl") or "").strip() or None,
    }


def search(q, region, page, page_size):
    """이름 · 지역으로 찾는다. 같은 질의는 캐시에서 준다."""
    ckey = "hospitals:%s:%s:%d:%d" % (q, region, page, page_size)
    hit = cache.get(ckey)
    if hit is not None:
        return hit

    params = {"pageNo": page, "numOfRows": page_size}
    if q:
        params["yadmNm"] = q
    # 모르는 지역 이름은 **거르지 않고 무시한다.** 400 을 주면 화면이 그것까지
    # 분기해야 하는데, 지역 칩은 우리가 보낸 목록에서 고른 것이라 어긋날 일이
    # 없고, 어긋났다면 그것은 화면 잘못이 아니라 우리 표가 낡은 것이다.
    if region and region in SIDO:
        params["sidoCd"] = SIDO[region]

    body = fetch(params)
    rows = one_or_many((body.get("items") or {}).get("item")
                       if isinstance(body.get("items"), dict)
                       else body.get("items"))

    out = {
        "items": [normalize(r) for r in rows],
        "count": int(body.get("totalCount") or 0),
        "page": page,
        "page_size": page_size,
    }
    cache.set(ckey, out, settings.HOSPITAL_API_CACHE_SEC)
    return out


def to_int(raw, default, low, high):
    """질의 문자열의 수. 범위를 벗어나면 거부하지 않고 자른다."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


class HospitalSearchView(APIView):
    """GET /api/v1/hospitals"""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="hospital-search",
        summary="병원 찾기",
        description="심평원 병원정보서비스에서 이름 · 지역으로 찾는다. "
                    "우리 병원의 협력 기관 목록이 아니다.",
        responses={200: {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "object"}},
                "regions": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "source": {"type": "string"},
                "note": {"type": "string"},
            },
        }},
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        region = (request.query_params.get("region") or "").strip()
        page = to_int(request.query_params.get("page"), 1, 1, 1000)
        page_size = to_int(request.query_params.get("page_size"), 20, 1, MAX_PAGE_SIZE)

        # ⚠ 이름도 지역도 없으면 **전국을 첫 장부터** 준다. 막지 않는 이유는
        #   화면이 들어오자마자 아무 조건 없이 한 번 부르기 때문이다
        #   (Hospitals.jsx 의 useApi 가 그렇다). 막으면 첫 화면이 오류로 뜬다.
        out = search(q, region, page, page_size)
        return Response({**out, "regions": REGIONS,
                         "source": SOURCE, "note": NOTE})
