# -*- coding: utf-8 -*-
"""admin.css 의 «무너지면 조용한» 약속들.

화면이 깨져도 뷰는 200 을 내고 테스트는 다 통과한다. 그래서 두 번 같은
자리가 무너졌다.

  2026-09-25 ① Django base.css 를 이기려고 특이도를 올렸는데, 그 규칙에
              display 까지 같이 적어서 칸별 배치를 전부 덮었다. 아바타와
              이름이 세로로 쌓이고 부서 색점이 사라지고 처리 단추가 왼쪽에
              붙었다.
  2026-09-25 ② 그 전에는 특이도가 모자라 Django 쪽이 이겼다(밑줄 · 머리줄
              배경).

여기서 보는 것은 «모양이 예쁜가»가 아니라 **규칙이 서로를 안 잡아먹는가**다.
브라우저 없이 확인할 수 있는 것이 그것뿐이고, 무너진 원인이 매번 그것이었다.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

CSS = Path(__file__).resolve().parent.parent / "static" / "empatho" / "admin.css"

#: 배치를 정하는 속성들. 특이도를 올린 규칙이 이걸 들고 있으면 칸별 규칙이
#: 진다 — 위 ①이 바로 그 일이었다.
LAYOUT = {"display", "flex", "flex-direction", "justify-content",
          "align-items", "gap", "grid-template-columns", "float", "position"}

#: 부서 여섯 + 환자. 색이 겹치면 두 과가 같은 점이 된다
DEPTS = ("admin", "surgery", "pathology", "radiology", "nursing", "reception")


def _rules():
    """(선택자, {속성: 값}) 목록. 주석은 걷어낸다."""
    text = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    out = []
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        props = {}
        for line in body.split(";"):
            if ":" in line:
                name, _, value = line.partition(":")
                props[name.strip()] = value.strip()
        out.append((" ".join(selector.split()), props))
    return out


def _find(needle):
    return [(s, p) for s, p in _rules() if needle in s]


def _box(value):
    """padding 줄임말을 (위, 오른쪽, 아래, 왼쪽) 로 편다."""
    parts = [int(p.removesuffix("px")) for p in value.split()]
    if len(parts) == 1:
        parts *= 4
    elif len(parts) == 2:
        parts = [parts[0], parts[1], parts[0], parts[1]]
    elif len(parts) == 3:
        parts = [parts[0], parts[1], parts[2], parts[1]]
    return parts


def _merged(needle):
    """그 선택자를 쓰는 규칙들을 **적힌 차례대로** 포갠 값.

    한 선택자가 여러 번 나온다(배치 한 벌, 색 한 벌…). 첫 규칙만 보면
    「text-align 만 정하는 줄」을 집고 배치가 없다고 잘못 말한다. 뒤에 온
    것이 이기는 CSS 규칙을 그대로 흉내 낸다 — 특이도가 같을 때의 얘기다.
    """
    out = {}
    for _, props in _find(needle):
        out.update(props)
    return out


class AdminCssTests(SimpleTestCase):
    def test_css_가_있다(self):
        """경로가 바뀌면 아래 시험이 전부 조용히 0건이 된다."""
        self.assertTrue(CSS.exists(), CSS)
        self.assertTrue(len(_rules()) > 100)

    # ── ① 특이도를 올린 규칙은 border 만 ─────────────────────────
    def test_테두리_끄는_규칙은_테두리만_건드린다(self):
        """#changelist 를 붙여 (1,1,1) 이 된 자리다. 여기 display 를 같이
        적으면 .e-approve td.e-who 같은 칸별 규칙 (0,2,1) 이 전부 진다."""
        rules = [(s, p) for s, p in _rules()
                 if "#changelist" in s and ".e-approve" in s and " td" in s]

        self.assertTrue(rules, "테두리 끄는 규칙을 못 찾았다 — 이름이 바뀌었나")
        for selector, props in rules:
            with self.subTest(selector):
                self.assertFalse(
                    set(props) - {"border", "border-bottom", "border-top",
                                  "background"},
                    "%s 가 테두리 · 배경 말고 다른 것도 정한다: %s"
                    % (selector, sorted(props)))

    def test_칸_배치를_정하는_규칙에는_ID_가_없다(self):
        """ID 가 붙으면 그 뒤에 오는 칸별 규칙이 못 이긴다."""
        for selector, props in _rules():
            if ".e-approve" not in selector or "#" not in selector:
                continue
            with self.subTest(selector):
                self.assertFalse(
                    LAYOUT & set(props),
                    "%s 가 배치를 정한다: %s"
                    % (selector, sorted(LAYOUT & set(props))))

    # ── 세 칸이 실제로 제 모양을 갖는가 ──────────────────────────
    def test_이름_칸은_가로로_눕는다(self):
        """아바타와 이름이 세로로 쌓였던 자리다."""
        props = _merged("td.e-who")

        self.assertEqual(props.get("display"), "flex")
        self.assertEqual(props.get("align-items"), "center")
        self.assertEqual(props.get("gap"), "12px")

    def test_처리_칸은_오른쪽에_붙는다(self):
        props = _merged("td.e-approve-act")

        self.assertEqual(props.get("display"), "flex")
        self.assertEqual(props.get("justify-content"), "flex-end")
        self.assertEqual(props.get("gap"), "8px")

    def test_부서_색점이_크기를_갖는다(self):
        """inline 이면 width · height 가 통째로 무시돼 점이 사라진다."""
        props = _merged("td.e-dept i")

        self.assertIn(props.get("display"), ("inline-block", "block", "flex"))
        self.assertEqual(props.get("width"), "8px")
        self.assertEqual(props.get("height"), "8px")

    def test_부서_여섯_색이_서로_다르다(self):
        colors = {}
        for dept in DEPTS:
            found = _find(".d-%s" % dept)
            self.assertTrue(found, "부서색이 없다: %s" % dept)
            colors[dept] = _merged(".d-%s" % dept).get("color")

        self.assertNotIn(None, colors.values())
        self.assertEqual(len(set(colors.values())), len(DEPTS),
                         "두 과가 같은 점이 된다: %s" % colors)

    # ── 줄 높이 ─────────────────────────────────────────────────
    def test_줄_높이가_시안대로_58px_이다(self):
        """값을 여기 또 적지 않는다 — CSS 에서 읽어 더한다. 두 벌로 두면
        한쪽만 고쳐 놓고 시험은 계속 통과한다."""
        row = _merged(".e-approve tbody tr")
        avatar = _merged(".e-avatar-sm")

        pad = int(row["padding"].split()[0].removesuffix("px"))
        tall = int(avatar["height"].removesuffix("px"))

        self.assertEqual(pad * 2 + tall, 58)

    def test_역할_고르개에_글자_들어갈_자리가_있다(self):
        """높이를 안 적으면 padding 이 곧 높이가 된다. 8+8 에 테두리 2 라
        글자에 남는 자리가 14px 뿐이었고 한글 받침이 잘렸다.

        값을 여기 또 적지 않고 CSS 에서 읽어 뺀다 — 두 벌로 두면 한쪽만
        고쳐 놓고 시험은 계속 통과한다."""
        props = _merged(".e-field select")

        tall = int(props["height"].removesuffix("px"))
        top, _, bottom, _ = _box(props["padding"])
        font = int(props["font-size"].removesuffix("px"))
        inner = tall - top - bottom - 2          # 위아래 테두리 1px 씩

        self.assertGreaterEqual(
            inner, font + 6,
            "글자 %dpx 에 남는 높이가 %dpx 다 — 받침이 잘린다" % (font, inner))

    # ── ② 특이도가 모자라 Django 에 지던 자리 ───────────────────
    def test_밑줄_끄는_규칙이_base_css_를_이긴다(self):
        """base.css 의 a:not(…, #header a, …) 는 :not() 안의 ID 때문에
        (1,0,2) 다. #content a (1,0,1) 로는 진다."""
        rules = [s for s, p in _rules()
                 if "#content a" in s and p.get("text-decoration") == "none"]

        self.assertTrue(rules)
        self.assertTrue(all("#container" in s for s in rules),
                        "특이도가 모자라 밑줄이 다시 그어진다: %s" % rules)
