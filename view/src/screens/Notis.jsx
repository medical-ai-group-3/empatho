import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";
import { fmtStamp } from "../lib/when";

/* 11 · 알림
 *
 * 홈 머리말의 종을 누르면 여기다. 탭에는 없다 — 늘 들르는 곳이 아니라
 * **점이 떴을 때** 오는 곳이다.
 *
 * ── 누르면 그 자리로 간다 ─────────────────────────────────────
 * 알림은 그 자체가 목적이 아니라 **가리키는 것**이 목적이다. 안내문이
 * 왔다는 알림을 눌렀는데 알림만 읽히고 끝나면 한 번 더 찾아 들어가야
 * 한다. ref_type 이 있는 것은 링크로 만들고, 없는 것은 링크가 아니다 —
 * 눌리는데 아무 일도 안 나는 것이 제일 나쁘다.
 *
 * ── 읽음 표시 ─────────────────────────────────────────────────
 * 화면을 여는 것만으로 전부 읽음 처리하지 않는다. 목록을 스치듯 본 것과
 * 그 알림을 실제로 연 것은 다르다. **누른 것만** 읽음으로 보낸다.
 *
 * 안 읽은 것에는 「새 소식」이 붙고 읽은 것에는 아무것도 안 붙는다.
 * 색이 아니라 글자가 뜻을 진다.
 */

/* 알림이 가리키는 곳. 모르는 ref_type 은 null 을 돌려주고, 그러면
   링크가 아니라 그냥 한 줄로 남는다. 나중에 종류가 늘어도 여기만
   고치면 된다. */
function target(n) {
  if (n.ref_type === "report" && n.ref_id) return `/reports/${n.ref_id}`;
  if (n.ref_type === "exam_order") return "/book";
  return null;
}

export default function Notis() {
  const { loading, data, error, reload } = useApi(() => api.notifications());

  return (
    <>
      <Head title="알림" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner items={data.items} />}
      </Body>
    </>
  );
}

function Inner({ items }) {
  if (!items?.length) {
    return (
      <div className="empty">
        <i className="ic" aria-hidden="true">◍</i>
        <p>받은 알림이 없습니다.</p>
      </div>
    );
  }

  return (
    <>
      <div className="list">
        {items.map((n) => {
          const to = target(n);
          const unread = !n.acknowledged_at;
          const inner = (
            <>
              <span className="dt">{fmtStamp(n.sent_at)}</span>
              <span className="tx">
                <b>{n.message}</b>
                {n.detail && <span>{n.detail}</span>}
              </span>
              {unread && <span className="pill new">새 소식</span>}
            </>
          );

          /* 읽음 처리는 **보내고 기다리지 않는다.** 이 요청이 느리다고
             화면이 안 넘어가면 안 된다. 실패해도 넘어간다 — 다음에
             목록을 다시 부르면 그때 맞춰진다 */
          const read = () => { api.markRead(n.notification_id).catch(() => {}); };

          return to ? (
            <Link key={n.notification_id} to={to} onClick={read}>
              {inner}
            </Link>
          ) : (
            <div key={n.notification_id}>{inner}</div>
          );
        })}
      </div>

      <p className="note">
        어떤 알림을 받을지는 <Link className="lnk" to="/settings">설정</Link>
        에서 정하실 수 있습니다.
      </p>
    </>
  );
}
