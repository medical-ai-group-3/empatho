"""처방 DUR 성분 점검 — 식약처 「의약품안전사용서비스(DUR) 성분정보」를 붙인다.

    POST /api/v1/drugs/dur
        {ingredients: ["아스피린", "메토트렉세이트"], age?: 66, sex?: "F"|"M"}
        → {alerts: [...], checked, ran, source, disclaimer[, partial, failed]}

원천은 data.go.kr 의 DURIrdntInfoService03 이다. 처방 화면이 약을 적는
동안 성분끼리 · 환자 나이 · 성별로 걸리는 것을 미리 보여 준다.

── 무엇을 보나 ─────────────────────────────────────────────────────

    combo      병용금기      성분마다 짝 목록을 받아, 짝이 **이번 처방의 다른
                             성분**이면 알린다. 한 쌍은 한 번만.
    age        특정연령대금기 AGE_BASE("18세 이하" 등)를 풀어 나이가 들면
    pregnancy  임부금기      여성 15–50세(나이 모르면 여성 전부) — caution
    elderly    노인주의      65세 이상 — caution

  필요 없는 점검은 **부르지 않는다.** 나이가 없으면 age · elderly 를,
  남성이면 pregnancy 를 건너뛴다. 공공데이터는 일일 한도가 있고, 한 번
  점검이 성분 수 × 점검 수만큼 부른다.

── 왜 patient_id 를 안 받나 ─────────────────────────────────────────

⚠ 나이 · 성별만 받는다. 환자 번호를 받으면 이 경로가 환자 PII 를 읽는
  자리가 되고, 권한 매트릭스에 새 행이 필요해진다. 부르는 화면은 이미
  환자를 열어 두고 있어 나이 · 성별을 안다.

── 임부금기를 caution 으로 두는 이유 ──────────────────────────────

⚠ 우리는 임신 여부를 모른다. 가임기 여성이라는 것만 안다. 그래서 금기
  (taboo)로 띄우지 않고 「임신 가능성을 확인하라」는 주의로 낸다 — 금기로
  띄우면 모든 가임기 여성 처방에 빨간 경고가 떠서 경고가 무시되기 시작한다.

── 원천의 함정 ─────────────────────────────────────────────────────

⚠ 서비스는 …Service03 인데 **오퍼레이션은 …02 로 끝난다.**
⚠ 성분 이름 거르는 칸이 오퍼레이션마다 다르다 (2026-09-28 실측).
    병용금기만 ingrKorName, 나머지는 ingrName. 틀린 칸을 주면 오류 없이
    **거르지 않은 전체**(임부금기 1459 건)를 준다 — 조용히 틀린다.
  거르기는 부분 일치다(「메토트」도 메토트렉세이트를 찾는다). 그래서
  받은 행을 한 번 더 우리 규칙(match)으로 거른다.
⚠ 실패는 HTTP 401/400 에 OpenAPI_ServiceResponse(XML 또는 JSON)로 온다.
  활용신청을 안 했으면 401 이다.

── 실패 ────────────────────────────────────────────────────────────

한 오퍼레이션이 죽어도 500 을 내지 않는다. 된 것만 싣고 partial · failed
로 알린다 — 「아무 경고도 없다」와 「점검을 못 했다」를 화면이 가를 수 있어야
한다. 키가 비었을 때만 통째로 503 이다(drugs.py 와 같은 이유).
"""

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from .drugs import clean
from .errors import ApiError
from .permissions import IsAuthenticatedAccount

logger = logging.getLogger(__name__)

DISCLAIMER = ("식약처 DUR 성분정보로 자동 점검한 결과이며 참고용입니다. "
              "최종 판단은 처방의가 환자 상태를 확인해 내려 주세요.")
SOURCE = "식품의약품안전처 의약품안전사용서비스(DUR) 성분정보"

#: 점검 종류 → (오퍼레이션, 성분 거르는 칸). 위 머리말의 함정 참고.
OPS = {
    "combo": ("getUsjntTabooInfoList02", "ingrKorName"),
    "age": ("getSpcifyAgrdeTabooInfoList02", "ingrName"),
    "pregnancy": ("getPwnmTabooInfoList02", "ingrName"),
    "elderly": ("getOdsnAtentInfoList02", "ingrName"),
}

#: 한 번에 받는 성분 수. 성분 × 4 번 부르므로 한도를 지키려면 막아 둔다.
MAX_INGREDIENTS = 20
#: 한 성분 · 한 오퍼레이션에서 받는 행 수. 부분 일치라 짧은 이름은 여러
#: 성분이 걸린다 — 넘치면 로그만 남기고 첫 쪽만 본다.
ROWS = 100
#: 동시에 부르는 수. 성분 20 × 4 를 차례로 부르면 느린 날 수십 초가 된다.
WORKERS = 8

ELDERLY_AGE = 65
FERTILE_AGES = (15, 50)


class UpstreamFailed(Exception):
    """오퍼레이션 하나가 실패했다. 뷰가 받아 partial 로 바꾼다."""


def norm(name):
    """비교용 이름 — 공백을 빼고 소문자로."""
    return "".join(str(name or "").split()).lower()


def match(a, b):
    """같은 성분으로 보나. **한쪽이 다른 쪽을 품으면 같다.**

    염 · 제형이 붙은 이름(아스피린리신 · 주사용아스피린리신)이 기본 성분
    (아스피린)과 따로 적혀 오기 때문이다. 넓게 잡아 한 번 더 뜨는 편이
    놓치는 것보다 낫다.
    """
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a)


def rows_of(body):
    """body.items 를 행 목록으로 편다.

    ⚠ 모양이 여러 갈래다. [{"item": {...}}, …] 가 보통이고, 공공데이터
      공통 모양인 {"item": [...]} · {"item": {...}} 도 온다. 0 건이면
      items 칸 자체가 없거나 빈 문자열이다.
    """
    items = body.get("items")
    if not items:
        return []
    if isinstance(items, dict):
        items = items.get("item") or []
        items = items if isinstance(items, list) else [items]
    out = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("item"), dict):
            out.append(it["item"])
        elif isinstance(it, dict):
            out.append(it)
    return out


def fetch(operation, params):
    """오퍼레이션 하나를 부른다. 응답은 파싱된 body. 실패면 UpstreamFailed."""
    query = urllib.parse.urlencode({**params, "type": "json"})
    # ⚠ serviceKey 는 따로 붙인다 — drugs.fetch 의 같은 주석 참고.
    url = "%s/%s?serviceKey=%s&%s" % (
        settings.DUR_API_BASE.rstrip("/"), operation,
        urllib.parse.quote(settings.DUR_API_KEY, safe="-_.~"), query)

    try:
        with urllib.request.urlopen(url, timeout=settings.DUR_API_TIMEOUT_SEC) as res:
            raw = res.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        # 401 이면 대개 이 서비스의 활용신청이 안 된 것이다.
        logger.error("[dur] %s %s: %s", operation, e.code,
                     e.read().decode("utf-8", "replace")[:300])
        raise UpstreamFailed(operation)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("[dur] %s 에 못 닿았다: %s", operation, e)
        raise UpstreamFailed(operation)

    try:
        payload = json.loads(raw)
    except ValueError:
        logger.error("[dur] %s JSON 이 아닌 응답: %s", operation, raw[:300])
        raise UpstreamFailed(operation)

    root = payload.get("response", payload)
    header = root.get("header") or {}
    code = header.get("resultCode")
    if code not in (None, "00") or "OpenAPI_ServiceResponse" in root:
        logger.error("[dur] %s resultCode=%s %s", operation, code,
                     header.get("resultMsg") or root.get("OpenAPI_ServiceResponse"))
        raise UpstreamFailed(operation)
    return root.get("body") or {}


def lookup(kind, ingredient):
    """성분 하나의 한 점검 행들. **이 성분에 해당하는 행만** 남긴다.

    캐시는 (오퍼레이션, 정규화한 성분) 단위다. 실패는 캐시하지 않는다 —
    한 번 죽은 것을 하루 종일 「걸리는 것 없음」으로 기억하면 안 된다.
    """
    operation, param = OPS[kind]
    key = norm(ingredient)
    ckey = "dur:%s:%s" % (operation, key)
    hit = cache.get(ckey)
    if hit is not None:
        return hit

    body = fetch(operation, {param: ingredient.strip(), "pageNo": 1, "numOfRows": ROWS})
    total = int(body.get("totalCount") or 0)
    if total > ROWS:
        logger.warning("[dur] %s %r 가 %d 건 — 첫 %d 건만 본다",
                       operation, ingredient, total, ROWS)

    name_field = "INGR_KOR_NAME" if kind == "combo" else "INGR_NAME"
    rows = [r for r in rows_of(body)
            # 삭제된 고시는 버린다. 원천은 지운 것을 DEL_YN 으로만 표시한다.
            if (r.get("DEL_YN") or "정상") != "삭제"
            and match(r.get(name_field), ingredient)]
    cache.set(ckey, rows, settings.DUR_API_CACHE_SEC)
    return rows


# ── 연령 기준 ───────────────────────────────────────────────────────────

_AGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(세|개월|주)\s*(미만|이하|이상|초과)")
_UNIT_YEARS = {"세": 1.0, "개월": 1 / 12, "주": 1 / 52}


def age_rules(text):
    """"18세 이하" → [(18.0, "이하")]. 못 읽으면 빈 목록.

    "3세 이상 12세 미만" 처럼 둘이 오면 둘 다 낸다(둘 다 맞아야 든다).
    """
    return [(float(n) * _UNIT_YEARS[u], op) for n, u, op in _AGE_RE.findall(text or "")]


def age_in(age, rules):
    """만 나이(정수)가 기준에 드나.

    ⚠ 나이를 **정수 해(年)** 로만 안다. "24개월 미만" 을 만 1 세와 견주면
      12–23 개월 어디든 들므로 든다고 본다 — 아래로 넉넉히 잡는 쪽이다.
      만 0 세는 "4주 미만" 에도 든다. 금기를 놓치는 것보다 한 번 더 뜨는 편이 낫다.
    """
    for limit, op in rules:
        ok = {"미만": age < limit, "이하": age <= limit,
              "이상": age >= limit, "초과": age > limit}[op]
        if not ok:
            return False
    return True


# ── 점검 ────────────────────────────────────────────────────────────────

def detail_of(row, *extra):
    """PROHBT_CONTENT 에 비고 · 제형을 한 줄씩 붙인다.

    ⚠ 비고와 제형을 버리지 않는다. 「methotrexate 주 15mg 이상일 때」,
      「서방정만」 같은 **금기가 성립하는 조건**이 거기 적혀 온다.
    """
    lines = [clean(row.get("PROHBT_CONTENT"))]
    if clean(row.get("REMARK")):
        lines.append("비고: " + clean(row.get("REMARK")))
    for label, field in extra:
        if clean(row.get(field)):
            lines.append("%s: %s" % (label, clean(row.get(field))))
    return "\n".join(l for l in lines if l)


def plan(age, sex):
    """이번 요청에서 돌릴 점검. 필요 없는 것은 부르지도 않는다."""
    kinds = ["combo"]
    if age is not None:
        kinds.append("age")
    if sex == "F" and (age is None or FERTILE_AGES[0] <= age <= FERTILE_AGES[1]):
        kinds.append("pregnancy")
    if age is not None and age >= ELDERLY_AGE:
        kinds.append("elderly")
    return kinds


def alerts_for(kind, ingredient, rows, ingredients, age):
    """한 성분 · 한 점검의 행 → 경고들."""
    out = []
    for r in rows:
        if kind == "combo":
            for other in ingredients:
                if other == ingredient or not match(r.get("MIXTURE_INGR_KOR_NAME"), other):
                    continue
                out.append({
                    "type": "combo", "level": "taboo",
                    "ingredient": ingredient, "with": other,
                    "message": "%s과(와) %s은(는) 함께 쓰면 안 되는 병용금기입니다."
                               % (ingredient, other),
                    "detail": detail_of(r),
                })
        elif kind == "age":
            base = clean(r.get("AGE_BASE"))
            rules = age_rules(base)
            if not rules:
                # 못 읽는 기준은 버리지 않는다 — 금기를 조용히 놓치는 쪽이 더 나쁘다.
                out.append({
                    "type": "age", "level": "caution", "ingredient": ingredient,
                    "message": "%s은(는) 특정연령대금기 성분입니다(기준: %s). 연령을 확인해 주세요."
                               % (ingredient, base or "미상"),
                    "detail": detail_of(r, ("제형", "FORM_NAME")),
                })
            elif age_in(age, rules):
                out.append({
                    "type": "age", "level": "taboo", "ingredient": ingredient,
                    "message": "%s은(는) %s 금기입니다(환자 %d세)." % (ingredient, base, age),
                    "detail": detail_of(r, ("제형", "FORM_NAME")),
                })
        elif kind == "pregnancy":
            grade = clean(r.get("GRADE"))
            out.append({
                "type": "pregnancy", "level": "caution", "ingredient": ingredient,
                "message": "%s은(는) 임부금기%s 성분입니다. 임신 가능성을 확인해 주세요."
                           % (ingredient, " " + grade if grade else ""),
                "detail": detail_of(r, ("제형", "FORM_NAME")),
            })
        elif kind == "elderly":
            out.append({
                "type": "elderly", "level": "caution", "ingredient": ingredient,
                "message": "%s은(는) 노인주의 성분입니다(환자 %d세). 신중히 투여해 주세요."
                           % (ingredient, age),
                "detail": detail_of(r, ("제형", "FORM_NAME")),
            })
    return out


def check(ingredients, age=None, sex=None):
    """점검 본체. 뷰와 떼어 둔다 — 셸에서 바로 불러 볼 수 있게.

    ingredients 는 이미 다듬은(빈 것 뺀 · 중복 뺀) 목록이다.
    """
    if not settings.DUR_API_KEY:
        logger.error("DUR_API_KEY 가 비어 있다 — DUR 점검을 할 수 없다")
        raise ApiError("UPSTREAM_DUR_UNAVAILABLE", "DUR 점검이 설정되어 있지 않습니다.")

    kinds = plan(age, sex)
    jobs = [(k, ing) for k in kinds for ing in ingredients]

    def run(job):
        kind, ing = job
        try:
            return kind, ing, lookup(kind, ing)
        except UpstreamFailed:
            return kind, ing, None

    with ThreadPoolExecutor(max_workers=min(WORKERS, len(jobs))) as pool:
        results = list(pool.map(run, jobs))

    alerts, failed, seen = [], [], set()
    for kind, ing, rows in results:
        if rows is None:
            if kind not in failed:
                failed.append(kind)
            continue
        for a in alerts_for(kind, ing, rows, ingredients, age):
            # A↔B 는 한 쌍이다 — 양쪽 성분에서 다 걸려 온다. 같은 성분의
            # 같은 문장(제형만 다른 행)도 한 번만.
            who = frozenset((a["ingredient"], a.get("with"))) if kind == "combo" \
                else a["ingredient"]
            key = (kind, who, a["detail"])
            if key in seen:
                continue
            seen.add(key)
            alerts.append(a)

    # 금기가 먼저, 주의가 뒤. 같은 급 안에서는 점검 순서대로.
    alerts.sort(key=lambda a: (a["level"] != "taboo", list(OPS).index(a["type"])))
    out = {"alerts": alerts, "checked": list(ingredients), "ran": kinds}
    if failed:
        out.update(partial=True, failed=failed)
    return out


# ── 요청 ────────────────────────────────────────────────────────────────

def parse(data):
    """요청 본문 → (성분들, 나이, 성별). 틀리면 400."""
    raw = data.get("ingredients")
    if not isinstance(raw, list):
        raise ApiError("VALIDATION_ERROR", "성분 목록(ingredients)을 보내 주세요.",
                       details={"ingredients": "list"})
    ingredients, keys = [], set()
    for v in raw:
        name = " ".join(str(v).split()) if isinstance(v, (str, int)) else ""
        # 빈 칸은 버린다 — 화면이 아직 안 채운 줄을 그대로 보낸다.
        if not name or norm(name) in keys:
            continue
        keys.add(norm(name))
        ingredients.append(name)
    if not ingredients:
        raise ApiError("VALIDATION_ERROR", "점검할 성분이 없습니다.",
                       details={"missing": ["ingredients"]})
    if len(ingredients) > MAX_INGREDIENTS:
        raise ApiError("VALIDATION_ERROR",
                       "성분은 한 번에 %d개까지 점검할 수 있습니다." % MAX_INGREDIENTS,
                       details={"ingredients": len(ingredients), "max": MAX_INGREDIENTS})

    age = data.get("age")
    if age is not None:
        # bool 은 int 의 하위형이라 따로 막는다 — true 가 1 세가 된다.
        if isinstance(age, bool) or not isinstance(age, int) or not (0 <= age <= 130):
            raise ApiError("VALIDATION_ERROR", "나이(age)는 0–130 사이의 정수여야 합니다.",
                           details={"age": age})

    sex = data.get("sex")
    if sex is not None and sex not in ("F", "M"):
        raise ApiError("VALIDATION_ERROR", "성별(sex)은 F 또는 M 이어야 합니다.",
                       details={"sex": sex})

    if "patient_id" in data:
        # ⚠ 받지 않는다(머리말 참고). 조용히 무시하면 부르는 쪽이 환자를
        #   조회해 나이를 채워 준다고 믿는다.
        raise ApiError("VALIDATION_ERROR",
                       "patient_id 는 받지 않습니다. age · sex 를 보내 주세요.",
                       details={"unexpected": ["patient_id"]})
    return ingredients, age, sex


class DurCheckView(APIView):
    """POST /api/v1/drugs/dur"""

    permission_classes = [IsAuthenticatedAccount]

    @extend_schema(
        operation_id="drug-dur-check",
        summary="처방 DUR 성분 점검",
        description="식약처 DUR 성분정보로 병용금기 · 연령 · 임부 · 노인 주의를 점검한다. "
                    "참고용이고 처방 저장을 막지 않는다.",
        request={"application/json": {
            "type": "object",
            "properties": {
                "ingredients": {"type": "array", "items": {"type": "string"}},
                "age": {"type": "integer"},
                "sex": {"type": "string", "enum": ["F", "M"]},
            },
            "required": ["ingredients"],
        }},
        responses={200: {
            "type": "object",
            "properties": {
                "alerts": {"type": "array", "items": {"type": "object"}},
                "checked": {"type": "array", "items": {"type": "string"}},
                "ran": {"type": "array", "items": {"type": "string"}},
                "partial": {"type": "boolean"},
                "failed": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"},
                "disclaimer": {"type": "string"},
            },
        }},
    )
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        ingredients, age, sex = parse(data)
        out = check(ingredients, age=age, sex=sex)
        return Response({**out, "source": SOURCE, "disclaimer": DISCLAIMER})
