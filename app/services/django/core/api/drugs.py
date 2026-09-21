"""약 정보 조회 — 식약처 「의약품개요정보(e약은요)」 공공데이터를 앱에 붙인다.

    GET /api/v1/drugs?q=타이레놀&page=1&page_size=10
        → {items: [...], count, page, page_size, source, disclaimer}
    GET /api/v1/drugs/{item_seq}
        → {item: {...}, source, disclaimer}

원천은 data.go.kr 의 DrbEasyDrugInfoService 다. 「e약은요」는 허가사항을
일반인이 읽을 수 있게 풀어 쓴 자료라 환자 앱에 실을 수 있는 몇 안 되는
공식 문서다.

── 왜 처방전에 붙이지 않고 따로 두나 ────────────────────────────────

⚠ **처방전의 purpose · how · watch 는 여기서 채우지 않는다.** 복약 관리
  (api.prescriptions · screens/Meds.jsx)는 「설명은 처방에 실려 온다」를
  규칙으로 세워 둔 자리다. 같은 성분이라도 이 환자가 왜 먹는지는 처방한
  사람이 정하고, 약전 문장을 이름으로 긁어다 그 칸에 끼워 넣으면 그 순간
  **우리가 하는 의학적 조언**이 된다.

  그래서 이 경로는 **환자가 스스로 찾아보는 사전**이다. 응답에 source 와
  disclaimer 를 늘 실어 화면이 「식약처 자료이고 내 처방 설명이 아니다」를
  말할 수 있게 한다. 두 자리를 섞지 말 것.

── 인증키 ───────────────────────────────────────────────────────────

`DRUG_API_KEY` 로 받는다. 코드에 박지 않는다 — 공공데이터 일반 인증키는
계정에 묶인 값이고, 저장소에 들어가면 회수가 곧 서비스 중단이다.

키가 비어 있으면 **503 으로 끊는다.** 빈 키로 부르면 공공데이터 쪽이
SERVICE_KEY_IS_NOT_REGISTERED_ERROR 를 200 에 실어 주기 때문에, 막지
않으면 「결과 없음」과 구분이 안 된 채 조용히 빈 화면이 된다.

── 캐시 ─────────────────────────────────────────────────────────────

약 정보는 거의 안 바뀌는데(updateDe 가 연 단위다) 앱에서는 같은 약을
여러 사람이 반복해서 찾는다. 공공데이터는 일일 호출 한도가 있으므로
질의별로 캐시한다. 한도를 넘기면 그날 하루 기능이 통째로 죽는다.
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

#: 화면이 답마다 함께 보여 주는 한 줄. 챗봇의 DISCLAIMER 와 같은 이유로
#: 서버가 보낸다 — 문구가 바뀔 때 앱 배포를 기다리지 않는다.
DISCLAIMER = ("식품의약품안전처가 공개한 의약품 정보입니다. "
              "처방받으신 약의 복용법은 처방전과 담당 의료진의 안내를 따라 주세요.")

SOURCE = "식품의약품안전처 의약품개요정보(e약은요)"

#: 공공데이터 칸 이름 → 우리 칸 이름. 화면이 Qesitm 같은 이름을 읽게 두면
#: 원천이 바뀔 때 화면까지 따라 고쳐야 한다.
FIELDS = {
    "itemSeq": "item_seq",
    "itemName": "name",
    "entpName": "maker",
    "itemImage": "image",
    "efcyQesitm": "efficacy",          # 이 약은 어떤 효능이 있나요
    "useMethodQesitm": "how_to_use",   # 어떻게 사용하나요
    "atpnWarnQesitm": "warning",       # 경고 (굵게 다뤄야 하는 것)
    "atpnQesitm": "caution",           # 사용 전 알아야 할 것
    "intrcQesitm": "interaction",      # 함께 먹으면 안 되는 약·음식
    "seQesitm": "side_effect",         # 이상반응
    "depositMethodQesitm": "storage",  # 보관법
    "updateDe": "updated_at",
}

#: 한 번에 가져올 수 있는 수. 공공데이터가 더 받아 주더라도 앱 화면이
#: 한 번에 그릴 수 있는 양을 넘기지 않는다.
MAX_PAGE_SIZE = 50


def clean(value):
    """원천 문장을 화면에 싣기 전에 다듬는다.

    ⚠ 원천 본문에 **비줄바꿈 공백(U+00A0)과 빈 줄**이 섞여 들어온다.
      그대로 두면 화면에서 문단 사이가 들쭉날쭉해지고, 그 공백은 글자 단위
      줄바꿈을 막아 좁은 폭에서 문장이 화면 밖으로 삐져나간다.
    """
    if value is None:
        return ""
    text = str(value).replace(" ", " ").replace("\r\n", "\n")
    # 빈 줄은 걷어내고 문단만 남긴다 — 원천은 문단마다 빈 줄을 두 개씩 넣는다.
    paras = [" ".join(p.split()) for p in text.split("\n")]
    return "\n".join(p for p in paras if p)


def normalize(row):
    """공공데이터 한 행 → 우리 모양."""
    item = {ours: clean(row.get(theirs)) for theirs, ours in FIELDS.items()}
    # 사진은 문장이 아니다. 없으면 빈 문자열이 아니라 None 이라야 화면이
    # `{item.image && <img …>}` 하나로 가른다.
    item["image"] = item["image"] or None
    return item


def fetch(operation, params):
    """공공데이터를 부른다. 응답은 파싱된 body.

    ── 왜 한 번 감싸나 ──────────────────────────────────────────────
    이 API 는 **실패를 200 에 실어 보낸다.** 키가 잘못됐거나 한도를 넘겨도
    HTTP 는 200 이고 본문만 XML 오류문이다. urlopen 의 예외만 보면 그 둘이
    「결과 없음」으로 흘러가 화면이 조용히 빈다. 그래서 본문을 열어 보고
    직접 끊는다.
    """
    key = settings.DRUG_API_KEY
    if not key:
        logger.error("DRUG_API_KEY 가 비어 있다 — 약 정보를 가져올 수 없다")
        raise ApiError("UPSTREAM_DRUG_UNAVAILABLE",
                       "약 정보 조회가 설정되어 있지 않습니다.")

    # ⚠ serviceKey 를 urlencode 에 함께 넣지 않는다. 공공데이터 포털이 주는
    #   키에는 이미 %2B 같은 인코딩이 섞여 있는 경우가 있어 한 번 더 인코딩
    #   하면 서명이 깨진다. 일반 인증키(Decoding)는 그대로 붙이면 된다.
    query = urllib.parse.urlencode({**params, "type": "json"})
    url = "%s/%s?serviceKey=%s&%s" % (
        settings.DRUG_API_BASE.rstrip("/"), operation,
        urllib.parse.quote(key, safe="-_.~"), query)

    try:
        with urllib.request.urlopen(url, timeout=settings.DRUG_API_TIMEOUT_SEC) as res:
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        logger.error("[drugs] 공공데이터 %s: %s", e.code,
                     e.read().decode("utf-8", "replace")[:300])
        raise ApiError("UPSTREAM_DRUG_UNAVAILABLE")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("[drugs] 공공데이터에 못 닿았다 (%s): %s", settings.DRUG_API_BASE, e)
        raise ApiError("UPSTREAM_DRUG_UNAVAILABLE")

    try:
        payload = json.loads(raw)
    except ValueError:
        # 오류일 때만 XML 이 온다 — 위 주석의 그 경우다.
        logger.error("[drugs] JSON 이 아닌 응답: %s", raw[:300])
        raise ApiError("UPSTREAM_DRUG_UNAVAILABLE")

    # 성공은 body 가 있고 resultCode 가 00 이다. 모양이 두 갈래다
    # (header 가 최상위일 때와 response 아래일 때) — 둘 다 받는다.
    root = payload.get("response", payload)
    header = root.get("header") or {}
    code = header.get("resultCode")
    if code not in (None, "00"):
        logger.error("[drugs] 공공데이터 resultCode=%s %s",
                     code, header.get("resultMsg"))
        raise ApiError("UPSTREAM_DRUG_UNAVAILABLE")

    return root.get("body") or {}


def search(name, page, page_size):
    """약 이름으로 찾는다. 같은 질의는 캐시에서 준다."""
    ckey = "drugs:q:%s:%d:%d" % (name, page, page_size)
    hit = cache.get(ckey)
    if hit is not None:
        return hit

    body = fetch("getDrbEasyDrugList",
                 {"itemName": name, "pageNo": page, "numOfRows": page_size})
    out = {
        "items": [normalize(r) for r in (body.get("items") or [])],
        "count": int(body.get("totalCount") or 0),
        "page": page,
        "page_size": page_size,
    }
    cache.set(ckey, out, settings.DRUG_API_CACHE_SEC)
    return out


def by_seq(item_seq):
    """품목기준코드 하나. 목록에서 눌러 들어온 상세 화면이 쓴다."""
    ckey = "drugs:seq:%s" % item_seq
    hit = cache.get(ckey)
    if hit is not None:
        return hit

    body = fetch("getDrbEasyDrugList", {"itemSeq": item_seq, "numOfRows": 1})
    rows = body.get("items") or []
    if not rows:
        # 캐시하지 않는다 — 오타로 한 번 찾은 코드를 하루 종일 없는 것으로
        # 기억할 이유가 없고, 원천에 나중에 실릴 수도 있다.
        raise ApiError("NOT_FOUND", "해당 의약품 정보를 찾을 수 없습니다.")

    item = normalize(rows[0])
    cache.set(ckey, item, settings.DRUG_API_CACHE_SEC)
    return item


def to_int(raw, default, low, high):
    """질의 문자열의 수. 범위를 벗어나면 **거부하지 않고 자른다**.

    페이지 번호가 범위 밖이라고 400 을 주면 화면이 그것까지 분기해야 하는데,
    목록을 넘기다 끝에 닿은 것은 오류가 아니다.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


class DrugSearchView(APIView):
    """GET /api/v1/drugs"""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="drug-search",
        summary="약 정보 찾기",
        description="식약처 의약품개요정보(e약은요)에서 약 이름으로 찾는다. "
                    "처방전에 실린 복약 설명을 대신하지 않는다.",
        responses={200: {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "object"}},
                "count": {"type": "integer"},
                "page": {"type": "integer"},
                "page_size": {"type": "integer"},
                "source": {"type": "string"},
                "disclaimer": {"type": "string"},
            },
        }},
    )
    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            raise ApiError("VALIDATION_ERROR", "찾으실 약 이름을 입력해 주세요.",
                           details={"missing": ["q"]})

        page = to_int(request.query_params.get("page"), 1, 1, 1000)
        page_size = to_int(request.query_params.get("page_size"), 10, 1, MAX_PAGE_SIZE)

        out = search(q, page, page_size)
        return Response({**out, "source": SOURCE, "disclaimer": DISCLAIMER})


class DrugDetailView(APIView):
    """GET /api/v1/drugs/{item_seq}"""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="drug-detail",
        summary="약 정보 상세",
        description="품목기준코드(item_seq) 로 의약품 정보 한 건을 가져온다.",
        responses={200: {
            "type": "object",
            "properties": {
                "item": {"type": "object"},
                "source": {"type": "string"},
                "disclaimer": {"type": "string"},
            },
        }},
    )
    def get(self, request, item_seq):
        return Response({"item": by_seq(item_seq),
                         "source": SOURCE, "disclaimer": DISCLAIMER})
