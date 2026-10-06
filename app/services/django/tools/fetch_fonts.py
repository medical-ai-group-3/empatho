# -*- coding: utf-8 -*-
"""Google Fonts 의 woff2 를 내려받아 정적 파일로 두고 로컬 @font-face 를 쓴다.

화면에서 fonts.googleapis.com 을 직접 부르지 않는 이유 — 학원 내부망이 막히면
글꼴만 조용히 안 뜬다. 그때 화면이 «깨진 것»이 아니라 «다른 글꼴로 멀쩡히»
보여서 시안과 달라진 것을 아무도 눈치채지 못한다.

⚠ 한글은 조각이 많다(IBM Plex Sans KR 네 무게에 376개). 합치지 않는 이유 —
  unicode-range 를 살려 두면 브라우저가 **화면에 실제로 쓰인 글자의 조각만**
  받는다. 한 파일로 묶으면 무게마다 1MB 넘는 것을 첫 화면에서 통째로 받는다.

⚠ 글자를 골라 subset 하지 않는다. 관리자 화면에는 직원 이름처럼 **미리 알 수
  없는 한글**이 뜬다. 고정 집합으로 줄이면 그 이름만 다른 글꼴로 나온다.

    python tools/fetch_fonts.py core/static/empatho/fonts core/static/empatho/fonts.css
"""
import os
import re
import sys
import urllib.request

OUT_DIR, CSS_OUT = sys.argv[1], sys.argv[2]

# woff2 를 받으려면 최신 브라우저인 척해야 한다. 기본 UA 로 부르면 Google 이
# ttf 를 돌려주고, 그러면 용량이 몇 배가 된다.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

FAMILIES = [
    ("IBM+Plex+Sans+KR:wght@400;500;600;700", "ibmplexsanskr"),
    ("JetBrains+Mono:wght@500;700", "jetbrainsmono"),
]

FACE_RE = re.compile(r"@font-face\s*\{[^}]*\}", re.S)
URL_RE = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+)\)")
WEIGHT_RE = re.compile(r"font-weight:\s*(\d+)")


def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as res:
        data = res.read()
    return data if binary else data.decode("utf-8")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    blocks, saved = [], {}

    for spec, slug in FAMILIES:
        css = fetch("https://fonts.googleapis.com/css2?family=%s&display=swap"
                    % spec)
        faces = FACE_RE.findall(css)
        print("%s — @font-face %d개" % (slug, len(faces)))

        # ⚠ 이름을 주소 끝(….0.woff2 의 「0」)에서 뽑으면 **겹친다.** 한글
        #   조각만 번호가 붙고 latin 계열은 안 붙어서, 둘이 같은 이름이 되어
        #   나중 것이 앞의 것을 덮는다. 덮여도 CSS 는 멀쩡해 보이고 글자만
        #   엉뚱하게 나온다. 그래서 무게마다 일련번호를 직접 센다.
        seq = {}
        for face in faces:
            url_m = URL_RE.search(face)
            if not url_m:
                continue
            url = url_m.group(1)
            weight = WEIGHT_RE.search(face).group(1)
            seq[weight] = seq.get(weight, -1) + 1
            name = "%s-%s-%03d.woff2" % (slug, weight, seq[weight])

            if url not in saved:
                data = fetch(url, binary=True)
                with open(os.path.join(OUT_DIR, name), "wb") as fh:
                    fh.write(data)
                saved[url] = (name, len(data))

            blocks.append(URL_RE.sub(
                "url('fonts/%s')" % saved[url][0], face).strip())

    with open(CSS_OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            "/* EMPATHO admin 글꼴 — Google Fonts 에서 받아 여기 둔다.\n"
            " *\n"
            " * 화면이 fonts.googleapis.com 을 직접 부르지 않는다. 내부망이\n"
            " * 막히면 글꼴만 조용히 안 떠서, 화면이 깨진 게 아니라 «다른\n"
            " * 글꼴로 멀쩡히» 보인다 — 시안과 달라진 것을 못 알아챈다.\n"
            " *\n"
            " * unicode-range 는 Google 이 나눈 그대로다. 한글 조각이 많은데,\n"
            " * 합치면 무게마다 1MB 넘는 것을 첫 화면에서 통째로 받게 된다.\n"
            " *\n"
            " * tools/fetch_fonts.py 가 만든다. 손으로 고치지 말 것.\n"
            " */\n\n")
        fh.write("\n\n".join(blocks) + "\n")

    total = sum(size for _, size in saved.values())
    print("받은 파일 %d개 · %.1f MB" % (len(saved), total / 1024 / 1024))


if __name__ == "__main__":
    main()
