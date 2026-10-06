#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""mobile_spec.md 를 DB v10 기준으로 고친다.

무엇이 어긋났나
  이 문서는 09-08 에 v9 기준으로 썼다. 09-09 에 v10 이 나왔고 우리는
  거기에 맞췄다. 문서 머리에 «v9 기준»이 붙어 있으면 읽는 사람이
  **지금 것을 옛것으로 오해한다.**

무엇을 안 고치나
  병변 필드 이름(ai_size_* · certainty_axes)은 이 문서에 **한 군데도
  없다.** 앱 화면 명세라 응답 필드를 직접 안 쓴다. 그래서 v10 개명이
  이 문서를 안 건드린다 — 판 번호와 «v9 에서 들어갔다»는 문장뿐이다.

  그 문장들도 지우지 않는다. **그때 그렇게 들어왔다는 기록**이고,
  v10 에서도 그대로 있다는 사실만 덧붙인다.

사용
  python3 training/code/patch_spec_v10.py            # 확인만
  python3 training/code/patch_spec_v10.py --apply
"""

import argparse
import shutil
from pathlib import Path

TARGET = Path.home() / "workspace/breast/mammo/docs/mobile_spec.md"

EDITS = [
    ("머리말",
     "2026-09-08 갱신 · DB 스키마 v9 기준",
     "2026-09-09 갱신 · DB 스키마 v10 기준"),

    ("consent 문장",
     "v9 `consent` 에 `withdrawn_at` 이 있다",
     "`consent` 에 `withdrawn_at` 이 있다"),

    ("DB 절 제목",
     "## DB — 요청했던 것은 v9 에서 다 들어갔다  *(09-08 확인)*",
     "## DB — 요청했던 것은 다 들어갔다  *(v10 · 09-09 확인)*"),

    ("동의 기록 표 줄",
     "| 동의 기록 표 | **v9 신설.** `consent`",
     "| 동의 기록 표 | **v9 신설 · v10 유지.** `consent`"),

    ("알림 종류 줄",
     "| `notification_type` 에 예약 | **v9 추가.**",
     "| `notification_type` 에 예약 | **v9 추가 · v10 유지.**"),

    ("ref_type 줄",
     "| `ref_type` 에 `exam_order` | **v9 추가** |",
     "| `ref_type` 에 `exam_order` | **v9 추가 · v10 유지** |"),

    ("v10 에서 새로 생긴 것 — 절 끝에 덧붙인다",
     """**둘로 쪼갠 것이 요청보다 낫다.** 「예약이 잡혔다」와 「바뀌었다」는 환자가
할 행동이 다르다.""",
     """**둘로 쪼갠 것이 요청보다 낫다.** 「예약이 잡혔다」와 「바뀌었다」는 환자가
할 행동이 다르다.

### v10 에서 더 생긴 것  *(09-09)*

| 무엇 | 화면에 무엇이 달라지나 |
|---|---|
| `lesion.ai_size_*` / `measured_size_*` | 크기가 **AI 원본**과 **판독의 측정값**으로 갈렸다. 화면이 둘을 구분해 보여줄 수 있다 |
| `lesion.is_false_positive` | 판독의가 「이건 병변이 아니다」를 표시한다. **그 단추를 어느 화면에 둘지 정해야 한다** |
| `ai_result.run_status` | `queued · running · done · failed`. 판독이 비동기라 **«분석 중» 화면이 필요하다** |

`is_false_positive` 는 지금 기능으로는 안 쓰이지만, **쌓여야 나중에 서술어를
다시 학습할 수 있다.** 표시할 자리가 없으면 데이터가 한 줄도 안 모인다."""),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    if not TARGET.is_file():
        raise SystemExit(f"[중단] 없는 파일: {TARGET}")
    s = TARGET.read_text(encoding="utf-8")

    print("=" * 76)
    print(f"mobile_spec.md 를 v10 기준으로  {TARGET}")
    print("=" * 76)

    if "DB 스키마 v10 기준" in s:
        print("\n  이미 v10 이다. 아무것도 안 한다.")
        return

    bad = []
    for name, old, _new in EDITS:
        n = s.count(old)
        print(f"  [{('찾음' if n == 1 else f'**{n}군데**'):>8}] {name}")
        if n != 1:
            bad.append((name, n, old))
    if bad:
        print("\n[중단] 앵커가 안 맞는다. 아무것도 안 고쳤다.")
        for name, n, old in bad:
            print(f"    {name} — {n}번 · 찾던 것: "
                  f"{old.strip().splitlines()[0][:60]}")
        raise SystemExit(2)

    new = s
    for _n, old, rep in EDITS:
        new = new.replace(old, rep)

    print(f"\n  {len(s):,} -> {len(new):,} 글자 ({len(new)-len(s):+,})")
    print("""
  바뀌는 것
    머리말 판 번호           v9 → v10
    「v9 추가」 세 줄         「v9 추가 · v10 유지」  — 기록은 지우지 않는다
    v10 신설 절              ai_size_* · is_false_positive · run_status

  안 바뀌는 것
    병변 필드 이름           이 문서에 원래 없다. 앱 화면 명세라
                            응답 필드를 직접 안 쓴다""")

    if not a.apply:
        print("\n  --apply 를 줘야 실제로 고친다. 지금은 확인만 했다.")
        return

    shutil.copy2(TARGET, TARGET.with_suffix(".md.bakv10"))
    TARGET.write_text(new, encoding="utf-8")
    print(f"\n  고쳤다. 원본은 {TARGET.name}.bakv10")
    print("""
  확인

    head -2 docs/mobile_spec.md
    grep -n "v9\\|v10" docs/mobile_spec.md

  그다음 커밋하고, .bak 은 지운다.

    git add -A && git commit -m "docs: mobile_spec 을 DB v10 기준으로"
    rm -f docs/mobile_spec.md.bakv10""")


if __name__ == "__main__":
    main()
