import { useEffect, useLayoutEffect, useState } from "react";
import { markSeen, seen } from "./seen";

/* 코치마크 — 화면 위에 얹어 «여기를 보라»고 짚는다.
 *
 * 소개 슬라이드를 대신한다. 슬라이드는 아직 앱을 안 써 본 사람에게
 * 말하는 것이라 감이 없고, 그래서 건너뛴다. 이건 **그 자리를 처음 보는
 * 순간에** 그 자리에서 말한다.
 *
 * ── 어떻게 보이게 했나 ────────────────────────────────────────
 * 「설명에 집중되게」가 목표다. 그래서 넷을 지킨다.
 *
 *   · **어둠이 깔린다.** 툭 나타나지 않고 짧게 스며든다. 갑자기 검어지면
 *     놀라서 무엇이 쓰였는지보다 «뭐지»를 먼저 본다
 *   · **조명이 미끄러진다.** 다음 걸음으로 넘어갈 때 구멍이 자리를 옮기는
 *     것이 보인다. 눈이 그 움직임을 따라가면 다음에 볼 곳을 안 찾아도 된다
 *   · **말풍선이 대상을 가리킨다.** 꼬리가 밝은 자리를 향한다 — 글과
 *     대상이 따로 놀지 않는다
 *   · **뒤가 안 움직인다.** 덮개 위에서 쓸어도 뒤 화면이 스크롤되지
 *     않는다. 조명은 그대로인데 내용만 흐르면 엉뚱한 곳을 짚게 된다
 *
 * ── 지키는 규칙 ───────────────────────────────────────────────
 *   · **한 번에 다 띄우지 않는다.** 홈에서 셋이 끝이다
 *   · **언제든 나갈 수 있다.** ✕ · Esc · 바깥 누르기
 *   · **한 번 보면 다시 안 뜬다**(seen.js)
 *   · 짚을 것이 화면에 없으면 그 걸음을 **건너뛴다**
 *
 * 대상은 화면 쪽에서 data-coach 로 표시한다. 클래스 이름으로 찾으면
 * 디자인을 고칠 때 조용히 끊긴다.
 */
const PAD = 8;       // 밝게 뚫는 구멍이 대상보다 얼마나 넉넉한가
const GAP = 14;      // 구멍과 말풍선 사이
const EDGE = 16;     // 말풍선이 화면 가장자리에서 떨어지는 거리
const APP = 520;     // 말풍선 최대 폭 — 앱 폭과 같다
const TIP_H = 150;   // 아래에 놓을 자리가 되는지 재는 어림값

export default function Coach({ steps, seenKey }) {
  const [i, setI] = useState(0);
  const [box, setBox] = useState(null);
  const [done, setDone] = useState(() => seen(seenKey));

  const step = steps[i];

  /* 대상을 잰다. 그리기 직전에 재야 자리가 안 튄다.
     화면이 돌아가면 다시 잰다. */
  useLayoutEffect(() => {
    if (done || !step) return;

    function measure() {
      const el = document.querySelector(step.sel);
      if (!el) { setBox(null); return; }
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, w: r.width, h: r.height });
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [done, step]);

  /* 짚을 것이 없으면 그 걸음은 지나간다. 화면에 없는 것을 가리키느니
     아무 말도 안 하는 편이 낫다. */
  useEffect(() => {
    if (!done && step && box === null) next();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [box, step, done]);

  useEffect(() => {
    if (done) return;
    const onKey = (e) => { if (e.key === "Escape") finish(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  function next() {
    if (i + 1 >= steps.length) finish();
    else setI(i + 1);
  }
  function finish() {
    markSeen(seenKey);
    setDone(true);
  }

  if (done || !step || !box) return null;

  // 아래에 놓을 자리가 있으면 아래, 없으면 위
  const below = box.top + box.h + GAP + TIP_H < window.innerHeight;

  // 말풍선 꼬리는 **밝은 자리의 한가운데**를 향한다. 다만 말풍선 밖으로
  // 나가면 안 되므로 양 끝에서 한 뼘 안쪽으로 묶는다.
  const tipW = Math.min(window.innerWidth - EDGE * 2, APP);
  const tipL = (window.innerWidth - tipW) / 2;
  const arrow = Math.min(Math.max(box.left + box.w / 2 - tipL, 22), tipW - 22);

  return (
    <div className="coach" role="dialog" aria-modal="true"
         aria-label={step.title}>
      {/* 바깥을 눌러도 넘어간다. 짚어 준 것을 눌러 보려던 손가락이
          그대로 다음으로 이어지게 */}
      <button className="coach-veil" onClick={next} aria-label="다음" />

      {/* 구멍 — 테두리가 아니라 «바깥을 덮는 그림자»로 만든다.
          이러면 대상이 실제로 밝게 남는다. 걸음이 바뀌면 이 상자가
          자리를 옮기면서 조명이 미끄러진다 */}
      <div className="coach-hole" style={{
        top: box.top - PAD, left: box.left - PAD,
        width: box.w + PAD * 2, height: box.h + PAD * 2,
      }} />

      <div className={below ? "coach-tip" : "coach-tip up"}
           style={{
             top: below ? box.top + box.h + GAP + PAD : undefined,
             bottom: below ? undefined
               : window.innerHeight - box.top + GAP + PAD,
             left: tipL, width: tipW,
             "--arrow": `${arrow}px`,
           }}>
        <span className="coach-n">{i + 1} / {steps.length}</span>
        <b>{step.title}</b>
        <p>{step.body}</p>

        <div className="coach-foot">
          <button className="lnk" onClick={finish}>건너뛰기</button>
          <button className="btn coach-next" onClick={next}>
            {i + 1 >= steps.length ? "알겠어요" : "다음"}
          </button>
        </div>
      </div>

      <button className="coach-x" onClick={finish} aria-label="안내 닫기">✕</button>
    </div>
  );
}
