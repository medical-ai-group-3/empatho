#!/usr/bin/env python
"""
서술어와 등급을 판독 소견문 초안으로 옮긴다 — 규칙 기반 + Ollama/MedGemma 다듬기.

무엇을 하고 무엇을 하지 않는가
  한다      확정된 서술어와 등급을 사람이 읽는 문장으로 만든다.
  안 한다   등급을 정하지 않는다. 영상을 보지 않는다. 서술어를 만들지 않는다.

  등급은 규칙표가 정한 값을 그대로 쓴다. 판단을 LLM 에 넘기면 '판독의가 반박할
  수 있는 근거를 남긴다'는 설계 목적이 무너진다 — 규칙표 자동 최적화를 성능이
  올랐는데도 기각한 것과 같은 이유다.

왜 템플릿이 먼저인가
  4B 양자화 모델에 문장 생성을 맡겨봤더니 few-shot 예시를 그대로 베꼈다.
  입력이 '타원형·침상'인데 예시의 '원형·경계 뚜렷'을 쓰면서 등급만 바꿔
  "양성 소견에 부합하여 BI-RADS 4c" 라는 모순된 문장을 냈다.

  그래서 순서를 뒤집었다. 규칙 기반으로 정확한 문장을 먼저 만들고, LLM 에는
  '다듬기'만 맡긴다. 생성보다 재작성이 훨씬 쉬운 과제이고 환각 여지도 작다.
  다듬은 결과가 검사를 통과하지 못하면 템플릿 문장을 쓴다.

      서술어 + 등급 -> 템플릿 문장 (항상 안전)
                            -> LLM 다듬기 -> 검사 통과하면 채택
                                          -> 실패하면 템플릿 사용

  즉 어떤 경우에도 쓸 수 있는 문장이 나온다.

왜 영상을 안 넣는가
  MedGemma 1.5 의 학습 모달리티는 방사선(흉부X선·CT·MRI)·피부과·병리이고
  맘모그래피는 없다. MedSAM3 와 같은 상황이다. 텍스트 역할로만 쓰면 이 문제가
  발생하지 않는다.

사용
  # 서버가 떠 있어야 한다 (--mode template 은 서버 없이도 동작한다)
  OLLAMA_MODELS=~/workspace/.ollama/models OLLAMA_KEEP_ALIVE=60s \
    nohup ollama serve > ~/workspace/.ollama/serve.log 2>&1 &

  python3 report_gen.py --kind mass --desc shape=OVAL,margin=SPICULATED --cat 4c
  python3 report_gen.py --kind calc --desc calctype=PLEOMORPHIC,calcdist=CLUSTERED --cat 4
  python3 report_gen.py --kind mass --desc shape=OVAL,margin=SPICULATED --cat 4c --mode template
"""

import argparse, json, re, sys, time, urllib.error, urllib.request

DEF_MODEL = "hf.co/unsloth/medgemma-1.5-4b-it-GGUF:Q4_K_M"
DEF_HOST = "http://127.0.0.1:11434"

# ── 문장 생성용 한국어 ──────────────────────────────────────────
SHAPE_KO = {"OVAL": "타원형", "ROUND": "원형", "IRREGULAR": "불규칙한 형태의"}

# 변연은 서술형과 관형형이 둘 다 필요하다.
#   "변연은 {서술}."          -> 변연은 침상이다.
#   "{관형} 변연을 근거로"     -> 침상 변연을 근거로
MARGIN_KO = {
    "CIRCUMSCRIBED": ("명확하다", "명확한"),
    "INDISTINCT": ("불명확하다", "불명확한"),
    "SPICULATED": ("침상이다", "침상"),
    "OBSCURED": ("주변 조직에 가려져 있다", "가려진"),
    "MICROLOBULATED": ("미세소엽상이다", "미세소엽상"),
}
FINDING_KO = {
    "ARCHITECTURAL_DISTORTION": "구조 왜곡",
    "LYMPH_NODE": "림프절",
    "FOCAL_ASYMMETRIC_DENSITY": "초점성 비대칭 음영",
    "ASYMMETRIC_BREAST_TISSUE": "비대칭 유방 실질",
}
CALCTYPE_KO = {
    "PLEOMORPHIC": "다형성", "PUNCTATE": "점상", "LUCENT_CENTER": "중심 투과성",
    "AMORPHOUS": "무정형", "ROUND_AND_REGULAR": "규칙적인 원형",
    "FINE_LINEAR_BRANCHING": "미세 선상 분지형", "VASCULAR": "혈관성",
    "COARSE": "조대", "BENIGN_TYPICAL": "전형적 양성",
}
CALCDIST_KO = {
    "CLUSTERED": "군집성", "SEGMENTAL": "분절성",
    "LINEAR": "선상", "REGIONAL_OR_DIFFUSE": "광범위한",
}
ACTION_KO = {
    "1": "정기 검진을 유지한다", "2": "정기 검진을 유지한다",
    "3": "6개월 후 추적 관찰을 권고한다",
    "4": "조직검사를 권고한다", "4a": "조직검사를 권고한다",
    "4b": "조직검사를 권고한다", "4c": "조직검사를 권고한다",
    "5": "조직검사를 권고한다",
}

# ── 환각 검사용 표현 사전 ────────────────────────────────────────
#   생성문에 '입력에 없는 서술어'가 들어왔는지 보려면 각 서술어가 한국어로
#   어떻게 나타나는지 알아야 한다. 한 서술어에 여러 표현이 대응한다.
TERMS = {
    # "타원형"을 먼저 적는 이유 — ROUND 의 "원형"이 "타원형"의 부분 문자열이다.
    "OVAL": ["타원형", "타원"],
    "ROUND": ["원형", "둥근"],
    "IRREGULAR": ["불규칙"],
    "CIRCUMSCRIBED": ["경계가 명확", "경계 명확", "변연은 명확", "변연이 명확",
                      "명확한 변연", "경계가 뚜렷"],
    # "불명확한 변연"을 등록하는 이유 — CIRCUMSCRIBED 의 "명확한 변연"이
    # 여기에 부분 문자열로 들어 있다. 긴 형태가 있어야 오탐이 걸러진다.
    "INDISTINCT": ["불명확한 변연", "변연은 불명확", "불명확", "불분명"],
    "SPICULATED": ["침상", "스피큘"],
    "OBSCURED": ["가려", "차폐"],
    "MICROLOBULATED": ["미세소엽", "소엽상"],
    "ARCHITECTURAL_DISTORTION": ["구조 왜곡", "구조적 왜곡", "구조왜곡"],
    "LYMPH_NODE": ["림프절"],
    "FOCAL_ASYMMETRIC_DENSITY": ["초점성 비대칭", "국소 비대칭"],
    "ASYMMETRIC_BREAST_TISSUE": ["비대칭 유방", "비대칭 조직"],
    "PLEOMORPHIC": ["다형성", "다형태"],
    "PUNCTATE": ["점상"],
    "LUCENT_CENTER": ["중심 투과", "중심투과"],
    "AMORPHOUS": ["무정형"],
    "ROUND_AND_REGULAR": ["규칙적인 원형", "원형이고 규칙"],
    "FINE_LINEAR_BRANCHING": ["미세 선상 분지", "선상 분지", "미세선상"],
    "VASCULAR": ["혈관성", "혈관"],
    "COARSE": ["조대", "거친"],
    "BENIGN_TYPICAL": ["전형적 양성", "양성 전형"],
    "CLUSTERED": ["군집", "집단"],
    "SEGMENTAL": ["분절"],
    "LINEAR": ["선상"],
    "REGIONAL_OR_DIFFUSE": ["광범위", "미만성", "영역성"],
}


# ── 템플릿 — 항상 안전한 1차 문장 ───────────────────────────────
def make_template(kind, desc, cat):
    """
    규칙 기반 소견문. 환각이 구조적으로 불가능하다 — 입력에 있는 서술어만
    문장에 들어간다. 등급도 인자로 받은 값을 그대로 쓴다.
    """
    act = ACTION_KO.get(str(cat), "판독의 판단을 따른다")

    if kind == "mass":
        shape = SHAPE_KO.get(desc.get("shape", ""), "")
        marg = MARGIN_KO.get(desc.get("margin", ""))
        find = FINDING_KO.get(desc.get("finding", ""))

        s1 = f"{shape} 종괴가 관찰된다".replace("  ", " ").strip()
        if marg:
            s1 = f"{shape} 종괴가 관찰되며 변연은 {marg[0]}".replace("  ", " ").strip()
        s1 = s1.lstrip() + "."
        if find:
            s1 += f" {find}이 동반된다."

        basis = f"{marg[1]} 변연" if marg else (find or "관찰된 소견")
        s2 = f"{basis}을 근거로 BI-RADS {cat}로 분류하며, {act}."
        return (s1 + " " + s2).replace("  ", " ")

    ctype = CALCTYPE_KO.get(desc.get("calctype", ""), "")
    cdist = CALCDIST_KO.get(desc.get("calcdist", ""), "")
    if ctype and cdist:
        s1 = f"{ctype} 석회화가 {cdist} 분포로 관찰된다."
        basis = "석회화의 형태와 분포"
    elif ctype:
        s1 = f"{ctype} 석회화가 관찰된다."
        basis = "석회화의 형태"
    elif cdist:
        s1 = f"석회화가 {cdist} 분포로 관찰된다."
        basis = "석회화의 분포"
    else:
        s1 = "석회화가 관찰된다."
        basis = "관찰된 소견"
    return f"{s1} {basis}를 근거로 BI-RADS {cat}로 분류하며, {act}."


# ── LLM 다듬기 ─────────────────────────────────────────────────
def build_polish_prompt(draft):
    """
    생성이 아니라 재작성을 시킨다. 4B 에게 훨씬 쉬운 과제이고, 초안에 없는
    내용을 끌어올 여지가 작다.
    """
    return f"""아래 유방촬영 판독 소견문 초안을 자연스러운 한국어 판독 문체로 다듬어라.

초안: {draft}

규칙:
- 내용을 바꾸지 마라. 소견을 추가하거나 빼지 마라.
- BI-RADS 등급은 초안과 똑같이 쓴다.
- 문장 수를 유지한다.
- 다듬은 문장만 출력한다. 설명·목록·제목을 붙이지 마라.

다듬은 문장:"""


STOPS = ["\n\n", "초안:", "규칙:", "다듬은 문장:", "[", "참고:", "설명:"]

MD = re.compile(r"^\s*(?:[-*·•]|\d+[.)])\s+|\*\*|__|^#+\s*", re.M)
LABEL = re.compile(r"^\s*(소견문|판독\s*소견|출력|다듬은\s*문장)\s*[:：]\s*", re.M)


def clean(text):
    t = LABEL.sub("", text)
    t = MD.sub("", t)
    t = re.split(r"\n\s*(?:참고|주의|설명|Note)\s*[:：]", t)[0]
    lines = [ln.strip() for ln in t.strip().splitlines() if ln.strip()]
    return " ".join(lines)


def call_ollama(model, prompt, host=DEF_HOST, temperature=0.1, timeout=180,
                quiet=False):
    # 첫 호출은 모델을 VRAM 에 올리느라 30~60초가 걸린다. 표시가 없으면 멈춘
    # 것으로 오해하게 된다.
    if not quiet:
        print("  다듬는 중 ... (첫 호출은 모델 적재로 30~60초)",
              file=sys.stderr, flush=True)
    t0 = time.time()
    req = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "stream": False,
                         "options": {"temperature": temperature,
                                     "stop": STOPS,
                                     "num_predict": 200}}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)["response"].strip()
        if not quiet:
            print(f"  받음 ({time.time() - t0:.0f}s)", file=sys.stderr, flush=True)
        return out
    except urllib.error.URLError as e:
        return None      # 서버가 없으면 템플릿으로 간다


# ── 검사 ───────────────────────────────────────────────────────
def verify(text, desc, cat):
    """등급이 그대로인지, 입력에 없는 서술어가 들어왔는지 본다."""
    problems = []

    cats = set(re.findall(r"BI-?RADS\s*:?\s*(4[abc]|[0-6])", text, re.I))
    if not cats:
        problems.append("BI-RADS 등급이 문장에 없다")
    elif str(cat).lower() not in {c.lower() for c in cats}:
        problems.append(f"등급이 바뀌었다: 입력 {cat} -> 생성문 {sorted(cats)}")

    given = set(desc.values())
    for key, forms in TERMS.items():
        if key in given:
            continue
        for f in forms:
            if f not in text:
                continue
            if _covered_by_given(f, text, given) or _negated(f, text):
                continue
            problems.append(f'입력에 없는 소견이 등장: {key} ("{f}")')
            break
    return problems


def _covered_by_given(f, text, given):
    """짧은 표현이 긴 표현에 먹히는 경우. LINEAR "선상" ⊂ "미세 선상 분지"."""
    for g in given:
        for gf in TERMS.get(g, []):
            if f != gf and f in gf and gf in text:
                return True
    return False


NEG = re.compile(r"(하지|치|지)\s*않|없|아니")


def _negated(f, text, window=8):
    """"경계가 명확하지 않다"에서 CIRCUMSCRIBED 를 신고하면 안 된다."""
    for m in re.finditer(re.escape(f), text):
        if not NEG.search(text[m.end():m.end() + window]):
            return False
    return True


def parse_desc(s):
    out = {}
    for item in s.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            sys.exit(f"형식 오류: {item}   (축=서술어 이어야 한다)")
        ax, val = item.split("=", 1)
        out[ax.strip()] = val.strip().upper()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["mass", "calc"], required=True)
    ap.add_argument("--desc", required=True,
                    help="축=서술어 쉼표 구분. 예: shape=OVAL,margin=SPICULATED")
    ap.add_argument("--cat", required=True, help="규칙표가 정한 BI-RADS. 예: 4c")
    ap.add_argument("--mode", choices=["hybrid", "template", "llm"],
                    default="hybrid",
                    help="hybrid=템플릿 후 LLM 다듬기(기본) · template=LLM 없이")
    ap.add_argument("--model", default=DEF_MODEL)
    ap.add_argument("--host", default=DEF_HOST)
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--retry", type=int, default=2)
    ap.add_argument("--raw", action="store_true", help="채택된 문장만 출력")
    a = ap.parse_args()

    desc = parse_desc(a.desc)
    draft = make_template(a.kind, desc, a.cat)

    # 템플릿 자체를 먼저 검사한다. 여기서 걸리면 사전에 문제가 있는 것이다.
    t_problems = verify(draft, desc, a.cat)

    final, source, polished, p_problems = draft, "템플릿", None, []
    if a.mode != "template":
        for attempt in range(a.retry + 1):
            out = call_ollama(a.model, build_polish_prompt(draft), a.host,
                              a.temperature, quiet=a.raw)
            if out is None:
                if not a.raw:
                    print("  Ollama 연결 실패 — 템플릿 문장을 쓴다", file=sys.stderr)
                break
            polished = clean(out)
            p_problems = verify(polished, desc, a.cat)
            if not p_problems:
                final, source = polished, "LLM 다듬기"
                break
            if attempt < a.retry and not a.raw:
                print(f"  ! {attempt+1}차 다듬기가 검사에 걸림. 다시 시도",
                      file=sys.stderr)

    if a.mode == "llm" and source != "LLM 다듬기":
        print("LLM 다듬기가 검사를 통과하지 못했다", file=sys.stderr)
        for p in p_problems:
            print(f"  · {p}", file=sys.stderr)
        sys.exit(1)

    if a.raw:
        print(final)
        return

    print("=" * 72)
    print(f"판독 소견문 초안   ({a.kind} · BI-RADS {a.cat})")
    print("=" * 72)
    print(f"  입력 서술어  {desc}")
    print(f"  등급 근거    규칙표 계산값 (LLM 이 정한 것이 아니다)")
    print()
    print(f"■ 템플릿 (규칙 기반)")
    print(f"  {draft}")
    if t_problems:
        print("  ! 템플릿이 검사에 걸렸다 — 사전 확인 필요")
        for p in t_problems:
            print(f"    · {p}")
    if polished is not None:
        print(f"\n■ LLM 다듬기")
        print(f"  {polished}")
        if p_problems:
            print("  ! 검사 실패 — 채택하지 않는다")
            for p in p_problems:
                print(f"    · {p}")
    print()
    print("-" * 72)
    print(f"  채택: {source}")
    print(f"  {final}")
    print()
    print("  ※ 초안이다. 판독의 확인 없이 사용하지 마라.")


if __name__ == "__main__":
    main()
