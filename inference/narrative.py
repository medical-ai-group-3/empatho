"""근거 없는 문장 버리기 — Go 의 internal/narrative 와 같은 규칙이다.

두 곳에서 다르게 검사하면 한쪽만 통과한 문장이 생긴다. 규칙이 바뀌면
양쪽을 같이 고쳐야 한다. 원본은 services/gosvc/internal/narrative/narrative.go.
"""

import re

TAG = re.compile(r"\[\[e:([A-Za-z0-9_.:-]+)\]\]")
_DIGITS = "0123456789"


def sentences(raw: str) -> list[str]:
    """문장으로 자른다. 종결부호는 문장에 붙여 남긴다.

    [.!?] 로 그냥 자르면 소수점에서 쪼개진다. Go 쪽 시험에서 실제로
    "우상방에 1.2cm 종괴가 있다" 가 "우상방에 1." 과 "2cm 종괴가 있다" 로
    갈라졌고, 앞쪽은 근거 표시가 없어 통째로 버려졌다.

    우리 소견은 63.9px · 0.629 처럼 측정값이 더 많다. 앞뒤가 모두 숫자인
    점은 경계로 보지 않는다.
    """
    out, start, i, n = [], 0, 0, len(raw)
    while i < n:
        c = raw[i]
        if c == "\n":
            s = raw[start:i + 1].strip()
            if s:
                out.append(s)
            start = i = i + 1
            continue
        if c not in ".!?":
            i += 1
            continue
        if (c == "." and 0 < i < n - 1
                and raw[i - 1] in _DIGITS and raw[i + 1] in _DIGITS):
            i += 1
            continue
        j = i
        while j + 1 < n and raw[j + 1] in ".!?":   # "..." 은 한 번만 끊는다
            j += 1
        s = raw[start:j + 1].strip()
        if s:
            out.append(s)
        start = i = j + 1
    s = raw[start:].strip()
    if s:
        out.append(s)
    return out


def filter_(raw: str, allowed) -> dict:
    """근거 표시가 없거나 지어낸 문장을 버린다.

    allowed 가 비면 전부 버린다. 검사할 수 없는 것을 통과시키면 검사가
    없는 것과 같다. 지어낸 인용은 근거 없는 문장보다 나쁘다 —
    확인된 것처럼 보인다.
    """
    ok = set(allowed or ())
    kept, evidence, seen, dropped = [], [], set(), []

    for s in sentences(raw):
        ids = TAG.findall(s)
        if not ids:
            dropped.append({"sentence": s, "reason": "근거 표시 없음"})
            continue
        good = [i for i in ids if i in ok]
        if not good:
            dropped.append({"sentence": s,
                            "reason": "인용한 근거 id 가 제공 목록에 없음"})
            continue
        for g in good:
            if g not in seen:
                seen.add(g)
                evidence.append(g)
        # 표시는 사람이 읽을 문장에서 지운다. 근거는 따로 나간다.
        clean = TAG.sub("", s).strip().replace(" .", ".").strip()
        if clean:
            kept.append(clean)

    return {"text": " ".join(kept).strip(),
            "evidence": evidence,
            "dropped": dropped}