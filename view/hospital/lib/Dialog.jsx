import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/* 팝업 — 화면 가운데에 띄우고 뒤를 어둡게 한다
 * ────────────────────────────────────────────────────────────────
 *
 * **body 에 포털로 붙인다.** 화면 안에 그냥 두면 조상 중 하나에
 * transform · filter · contain 이 있을 때 position:fixed 가 그 조상
 * 기준으로 잡혀서, 가운데가 아니라 엉뚱한 자리에 뜬다. 그런 속성이
 * 나중에 어디에 생길지 모르니 아예 밖으로 꺼낸다.
 *
 * 닫는 길을 셋 둔다 — [×] · Esc · 바깥 클릭.
 * 하나만 두면 그것을 못 찾은 사람이 갇힌다.
 *
 *   <Dialog title="…" sub="…" onClose={…} foot={<Btn …/>}>
 *     …내용…
 *   </Dialog>
 *
 * ⚠ 팝업의 sub 는 남아 있다. 쪽 머리(Page)에서는 설명 줄을 걷어냈지만
 *   팝업은 다르다 — 어쩌다 한 번 뜨는 자리라 「무엇을 하는 창인가」를
 *   한 줄로 말해야 한다. 되돌릴 수 없는 일이면 특히 그렇다.
 *
 * ⚠ 「고르면 닫힌다」는 여기서 안 한다. 고르는 함수 안에서 닫아라 —
 *   이 부품은 닫는 **방법**만 준다.
 */
export default function Dialog({ title, sub, foot, wide, onClose, children }) {
  const box = useRef(null);
  const back = useRef(null);

  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose?.(); };
    document.addEventListener("keydown", esc);

    /* 뒤 화면이 같이 굴러가면 팝업이 떠 있는 줄 모르고 뒤를 스크롤한다 */
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    box.current?.focus();
    return () => {
      document.removeEventListener("keydown", esc);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  /* 바깥 클릭 — **누르기 시작한 곳도 바깥이어야** 닫는다.
     안에서 글자를 끌어 선택하다 바깥에서 손을 떼면 닫히는 일이 잦다.
     onClick 하나로 두면 그게 막히지 않는다 */
  const downOnBack = useRef(false);

  return createPortal(
    <div
      className="dlg-back"
      ref={back}
      onMouseDown={(e) => { downOnBack.current = e.target === back.current; }}
      onMouseUp={(e) => {
        if (downOnBack.current && e.target === back.current) onClose?.();
        downOnBack.current = false;
      }}
    >
      <div className={`dlg${wide ? " wide" : ""}`} role="dialog" aria-modal="true"
           aria-label={title} tabIndex={-1} ref={box}>
        <div className="dlg-head">
          <div className="dlg-head-t">
            <b>{title}</b>
            {sub && <span>{sub}</span>}
          </div>
          <button className="dlg-x" onClick={onClose} aria-label="닫기"
                  type="button">×</button>
        </div>

        <div className="dlg-body">{children}</div>

        {foot && <div className="dlg-foot">{foot}</div>}
      </div>
    </div>,
    document.body,
  );
}
