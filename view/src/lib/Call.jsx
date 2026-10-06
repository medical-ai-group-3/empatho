import { useEffect, useRef } from "react";

/* 전화 걸기 확인 — 아이폰의 통화 확인 창 모양
 * ════════════════════════════════════════════════════════════════
 *
 * ── 왜 한 번 더 묻나 ─────────────────────────────────────────
 *
 * `tel:` 링크는 **폰에서는 바로 걸린다.** 잘못 눌러도 통화가 시작된다.
 * 병원에 실수로 전화가 가는 것은 사소한 일이 아니다 — 받는 쪽도 일이고
 * 거는 쪽도 당황한다.
 *
 * 그리고 **데스크톱에서는 아무 일도 안 일어난다.** 걸 수 있는 앱이
 * 없어서 브라우저가 조용히 무시한다. 눌렀는데 아무 반응이 없으면
 * 고장으로 읽힌다 — 시연 화면이 대개 데스크톱이다.
 *
 * 창을 한 번 띄우면 둘 다 풀린다. 번호가 눈에 보이니 **못 거는 기기에서도
 * 옮겨 적을 수 있고**, 거는 기기에서는 확인이 된다.
 *
 * ── 아이폰 모양을 따르는 이유 ────────────────────────────────
 * 이 창을 처음 보는 사람이 없어야 한다. 가운데 선 흰 상자, 굵은 번호,
 * 아래 두 칸으로 나뉜 단추 — 폰을 쓰는 사람은 이 모양을 이미 안다.
 * 새 모양을 배우게 할 자리가 아니다.
 *
 * ⚠ 되돌릴 수 없는 쪽(전화 걸기)을 **오른쪽**에 둔다. 아이폰의 규칙이고,
 *   왼손 엄지가 먼저 닿는 자리를 취소에 준다.
 */
export default function Call({ name, phone, onClose }) {
  const ref = useRef(null);
  const back = useRef(null);

  /* 창이 뜨면 초점을 안으로 들인다. 안 그러면 읽어 주는 기계가 뒤
     화면을 계속 읽고, 키보드로는 창에 닿지도 못한다.
     닫을 때 원래 자리로 돌려준다 — 목록의 어디였는지 잃지 않게 */
  useEffect(() => {
    back.current = document.activeElement;
    ref.current?.focus();
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      back.current?.focus?.();
    };
  }, [onClose]);

  const tel = `tel:${String(phone ?? "").replaceAll("-", "")}`;

  return (
    <div className="callveil" onClick={onClose}>
      {/* 상자 안을 눌러도 안 닫히게 — 바깥만 닫는다 */}
      <div className="callbox" role="dialog" aria-modal="true"
           aria-labelledby="call-t" tabIndex={-1} ref={ref}
           onClick={(e) => e.stopPropagation()}>
        <div className="callbox-b">
          <b id="call-t">{name}</b>
          {/* 번호가 주인공이다. 못 거는 기기에서는 이것을 보고 옮겨 적는다 */}
          <p className="callno">{phone}</p>
        </div>
        <div className="callbox-a">
          <button className="callbtn" onClick={onClose}>취소</button>
          {/* 되돌릴 수 없는 쪽이 오른쪽 */}
          <a className="callbtn go" href={tel} onClick={onClose}>전화 걸기</a>
        </div>
      </div>
    </div>
  );
}
