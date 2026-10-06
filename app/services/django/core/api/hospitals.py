"""병원 찾기 — 국립중앙의료원 「전국 병·의원 찾기 서비스」를 앱에 붙인다.

    GET /api/v1/hospitals?q=세브란스&region=서울&page=1&page_size=20
        → {items, regions, count, page, page_size, source, note}

원천은 data.go.kr 의 B552657/HsptlAsembySearchService 다.

── 왜 표를 안 파고 공공데이터를 부르나 ──────────────────────────────

v10 스키마에 병원 표가 없다. 단일 병원 운영이라 「협력 병원 목록」이라는
개념 자체가 없었다. 표를 새로 파면 누가 어떤 기준으로 등록하고 무엇이
바뀌면 고치는지가 따라붙는데, 그것을 정하지 않은 채 표부터 만들면 빈 표가
남는다.

⚠ 그래서 여기 나오는 것은 **협력 병원이 아니라 전국 병·의원**이다(79,013
  건). 화면 문구가 「협력 병원」이면 고쳐야 한다 — 우리가 보증하는 목록이
  아니다. 응답의 note 가 그 말을 싣고 있고, 화면은 그것을 그대로 적는다.

── 위치를 받지 않는다 ───────────────────────────────────────────────

⚠ 이 서비스에는 좌표 주변을 찾는 기능(getEgytLcinfoInqire)이 따로 있지만
  쓰지 않는다. 쓰려면 환자의 좌표를 서버로 보내야 하고, 그 순간 「어디에
  살고 어느 병원을 찾아봤는지」가 우리 로그에 남는다.

  화면(screens/Hospitals.jsx)이 이미 그렇게 만들어져 있다 — 병원 좌표만
  받아서 거리는 브라우저에서 잰다. lat · lng 를 실어 보내는 이유가 그것이다.

── XML 만 준다 ─────────────────────────────────────────────────────

약 정보(식약처)와 달리 이쪽은 JSON 을 안 준다. `_type=json` 을 붙여도 XML 이
온다. 그래서 여기만 ElementTree 로 읽는다.

── 시도 이름이 문서와 다르다 ────────────────────────────────────────

⚠ **자료가 「전남광주통합특별시」라는 합친 이름을 쓴다.** 그래서 Q0 에
  「광주광역시」를 넣으면 9 건, 「전라남도」는 1 건만 나온다 — 옛 이름으로
  남은 찌꺼기다. 두 지역의 실제 자료는 전부 합친 이름 아래 있다.

  강원 · 전북도 「강원특별자치도」 · 「전북특별자치도」라야 하고 옛 이름은
  0 건이다.

  2026-09-21 에 표본 5,000 건의 주소 앞머리를 세어 확인했다. 자료가 또
  바뀔 수 있으니 결과가 갑자기 비면 여기부터 다시 셀 것.
"""

import logging
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .errors import ApiError
from .permissions import IsAuthenticatedAccount

logger = logging.getLogger(__name__)

SOURCE = "국립중앙의료원 전국 병·의원 찾기 서비스"

#: 화면 맨 아래 한 줄. **「협력 병원」이 아니라는 말이 여기 있다.**
#: 서버가 보내는 이유는 문구가 바뀔 때 앱 배포를 기다리지 않으려는 것이다.
NOTE = ("국립중앙의료원이 공개한 전국 병·의원 정보입니다. "
        "우리 병원의 협력 기관 목록이 아니며, 진료 시간과 휴무는 "
        "방문 전에 해당 기관에 확인해 주세요.")

#: 화면에 보이는 이름 → 자료가 쓰는 Q0 값.
#:
#: 화면에는 짧은 이름을 보이고(칩이 한 줄에 들어간다), 서버가 자료의 이름으로
#: 바꿔 보낸다. **둘을 따로 두는 진짜 이유는 「광주·전남」이다** — 자료가 두
#: 지역을 「전남광주통합특별시」 하나로 묶어 두어서, 화면이 자료의 이름을
#: 그대로 쓰면 광주 사람이 「광주」를 찾다가 못 찾는다.
REGION_Q0 = {
    "서울": "서울특별시",
    "경기": "경기도",
    "인천": "인천광역시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "광주·전남": "전남광주통합특별시",
    "강원": "강원특별자치도",
    "충북": "충청북도",
    "충남": "충청남도",
    "전북": "전북특별자치도",
    "경북": "경상북도",
    "경남": "경상남도",
    "제주": "제주특별자치도",
}

#: 화면의 지역 칩. 「전체」가 맨 앞이다 — Hospitals.jsx 가 그 값을 빈
#: 문자열로 바꿔 서버에 안 보낸다.
REGIONS = ["전체"] + list(REGION_Q0)

#: 주소 앞머리 → 화면에 보일 짧은 이름. 목록에 지역을 적을 때 쓴다.
#: 자료에 옛 이름(「광주광역시」 9 건 · 「전라남도」 1 건)과 줄인 이름
#: (「서울」 17 건)이 섞여 있어 그것들도 받아 준다.
ADDR_REGION = {v: k for k, v in REGION_Q0.items()}
ADDR_REGION.update({
    "광주광역시": "광주·전남", "전라남도": "광주·전남",
    "강원도": "강원", "전라북도": "전북",
    "서울": "서울", "경기": "경기", "충남": "충남", "충북": "충북",
})

#: 한 번에 가져올 수 있는 수. 화면이 한 번에 그릴 수 있는 양을 넘기지 않는다.
MAX_PAGE_SIZE = 50

#: dutyTime{n}s · {n}c 의 n. 자료가 1=월 … 7=일 · 8=공휴일로 쓴다.
DAYS = [(1, "월"), (2, "화"), (3, "수"), (4, "목"), (5, "금"),
        (6, "토"), (7, "일"), (8, "공휴일")]


def hhmm(raw):
    """"0830" → "08:30". 못 읽으면 None."""
    text = (raw or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    hour, minute = int(text[:2]), int(text[2:])
    # 자료에 2400(자정 마감)이 들어온다. 24:00 은 시각이 아니라 마감 표시라
    # 그대로 적어 준다 — 00:00 으로 바꾸면 「밤 12시부터」로 읽힌다.
    if hour > 24 or minute > 59:
        return None
    return "%02d:%02d" % (hour, minute)


def opening_hours(get):
    """요일별 진료시간을 사람이 읽는 한 줄로.

        평일 08:30~18:00 · 토 08:30~13:30

    ⚠ 월~금이 **모두 같을 때만** 「평일」로 묶는다. 하루라도 다르면 요일을
      따로 적는다 — 묶어 놓고 실제로는 수요일만 오후 휴진이면, 그 한 줄을
      믿고 갔다가 헛걸음한다.

    ⚠ 값이 없는 요일은 **빼고 적지, 「휴무」라고 적지 않는다.** 자료에 안
      실린 것과 그날 쉬는 것은 다른데 여기서는 구분이 안 된다.
    """
    span = {}
    for n, label in DAYS:
        start, close = hhmm(get("dutyTime%ds" % n)), hhmm(get("dutyTime%dc" % n))
        if start and close:
            span[label] = "%s~%s" % (start, close)

    parts = []
    weekdays = ["월", "화", "수", "목", "금"]
    weekday_spans = {span[d] for d in weekdays if d in span}
    if len(weekday_spans) == 1 and all(d in span for d in weekdays):
        parts.append("평일 %s" % weekday_spans.pop())
    else:
        parts += ["%s %s" % (d, span[d]) for d in weekdays if d in span]
    parts += ["%s %s" % (d, span[d]) for d in ("토", "일", "공휴일") if d in span]
    return " · ".join(parts) or None


def to_float(value):
    """좌표. 못 읽으면 None — 그 병원만 거리 · 길찾기가 빠진다.

    ⚠ 0 으로 채우지 않는다. 0,0 은 아프리카 앞바다라 「가까운 순」의 맨
      앞이나 맨 끝에 엉뚱하게 붙고, 길찾기를 누르면 지도가 거기로 간다.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def region_of(addr):
    """주소 앞머리에서 화면에 보일 지역 이름."""
    head = (addr or "").split()
    return ADDR_REGION.get(head[0]) if head else None


def normalize(item):
    """자료 한 행 → 화면이 읽는 모양 (screens/Hospitals.jsx)."""
    def get(tag):
        return (item.findtext(tag) or "").strip()

    addr = get("dutyAddr")
    return {
        # 기관 ID. 기관마다 고정이라 화면의 열쇠로 쓴다.
        "hospital_id": get("hpid") or get("dutyName"),
        "name": get("dutyName"),
        # 종별(종합병원 · 병원 · 의원…). 진료과가 아니다.
        "dept": get("dutyDivNam") or None,
        "address": addr or None,
        "phone": get("dutyTel1") or None,
        "region": region_of(addr),
        "hours": opening_hours(get),
        # 「휴게시간 13:00~14:00」 같은 한 줄. 진료시간만 보고 갔다가
        # 점심시간에 닿는 일을 줄인다.
        #
        # ⚠ 자료에 **줄바꿈이 들어 있다**. 실제로 이런 값이 온다 —
        #   "2017년9월 부터 토요일1,3주 휴진합니다.⏎(병원사정에 따라 변경
        #   될수도 있습니다.)" 화면은 이것을 <p> 한 줄로 그리는데, HTML 이
        #   줄바꿈을 공백으로 접으면서 앞뒤 여백이 남아 띄어쓰기가 어긋난
        #   것처럼 보인다. 그래서 여기서 미리 한 칸으로 만든다.
        "etc": " ".join(get("dutyEtc").split()) or None,
        # ⚠ 위도가 wgs84Lat, 경도가 wgs84Lon 이다. 바꿔 넣으면 길찾기가
        #   엉뚱한 데로 가는데, 한국 안에서는 둘 다 그럴듯한 숫자라
        #   (위도 33~39 · 경도 124~132) 눈으로는 안 보인다.
        "lat": to_float(get("wgs84Lat")),
        "lng": to_float(get("wgs84Lon")),
    }


def fetch(params):
    """공공데이터를 부른다. 응답은 파싱된 XML 루트.

    ⚠ 이 계열 API 는 **실패를 200 에 실어 보내기도 한다.** 본문만 오류문이라
      예외만 보면 「결과 없음」으로 흘러가 화면이 조용히 빈다. 그래서 루트
      태그와 resultCode 를 직접 본다.
    """
    key = settings.HOSPITAL_API_KEY
    if not key:
        logger.error("HOSPITAL_API_KEY 가 비어 있다 — 병원 정보를 가져올 수 없다")
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE",
                       "병원 찾기가 설정되어 있지 않습니다.")

    # ⚠ serviceKey 를 urlencode 에 함께 넣지 않는다 — 포털이 주는 키에 이미
    #   인코딩이 섞여 있으면 한 번 더 인코딩돼 서명이 깨진다. (drugs.py 와 같다)
    query = urllib.parse.urlencode(params)
    url = "%s/getHsptlMdcncListInfoInqire?serviceKey=%s&%s" % (
        settings.HOSPITAL_API_BASE.rstrip("/"),
        urllib.parse.quote(key, safe="-_.~"), query)

    try:
        with urllib.request.urlopen(url, timeout=settings.HOSPITAL_API_TIMEOUT_SEC) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        logger.error("[hospitals] 공공데이터 %s: %s", e.code, body)
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("[hospitals] 공공데이터에 못 닿았다 (%s): %s",
                     settings.HOSPITAL_API_BASE, e)
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as e:
        logger.error("[hospitals] XML 이 아닌 응답 (%s): %s", e, raw[:300])
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    # 성공은 <response>, 오류는 <OpenAPI_ServiceResponse> 로 온다.
    result_code = root.findtext(".//resultCode")
    if root.tag != "response" or result_code not in (None, "00"):
        logger.error("[hospitals] 공공데이터 오류 root=%s code=%s msg=%s",
                     root.tag, result_code,
                     root.findtext(".//resultMsg") or root.findtext(".//errMsg"))
        raise ApiError("UPSTREAM_HOSPITAL_UNAVAILABLE")

    return root


def search(q, region, page, page_size):
    """이름 · 지역으로 찾는다. 같은 질의는 캐시에서 준다."""
    ckey = "hospitals:%s:%s:%d:%d" % (q, region, page, page_size)
    hit = cache.get(ckey)
    if hit is not None:
        return hit

    params = {"pageNo": page, "numOfRows": page_size}
    if q:
        params["QN"] = q
    # 모르는 지역 이름은 **거르지 않고 무시한다.** 400 을 주면 화면이 그것까지
    # 분기해야 하는데, 지역 칩은 우리가 보낸 목록에서 고른 것이라 어긋날 일이
    # 없고, 어긋났다면 그것은 화면 잘못이 아니라 우리 표가 낡은 것이다.
    if region and region in REGION_Q0:
        params["Q0"] = REGION_Q0[region]

    root = fetch(params)
    out = {
        "items": [normalize(it) for it in root.findall(".//item")],
        "count": int(root.findtext(".//totalCount") or 0),
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
        description="국립중앙의료원 전국 병·의원 찾기 서비스에서 이름 · 지역으로 찾는다. "
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
