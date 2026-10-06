import { useEffect } from "react";

/* 환자 상세 · 판정 불일치가 같이 쓴다 */
/* 영상 확인 팝업 — 화면 위에 띄운다. Esc · 바깥 누르기 · ×로 닫는다 */
export default function ImagePopup({ name, onClose, children }) {
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [onClose]);

  return (
    <div className="rev-pop-back" onClick={onClose}>
      <div className="rev-pop" role="dialog" aria-label={`영상 확인 · ${name}`}
           onClick={(e) => e.stopPropagation()}>
        <header>
          <b>영상 확인 · {name}</b>
          <button type="button" onClick={onClose} aria-label="닫기">×</button>
        </header>
        <div className="rev-pop-b breast">{children}</div>
      </div>
    </div>
  );
}
