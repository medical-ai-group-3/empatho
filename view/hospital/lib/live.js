/* ── 실시간 알림 — notify 허브가 SSE 로 흘려 준다 ────────────────────
 *
 * 쓰는 곳은 상단바의 종(lib/Top.jsx) 하나다. 환자는 SSE 를 쓰지 않는다
 * (empatho-app core/notify.py — 앱은 FCM · 알림 목록 API). 그래서 환자 앱
 * src/api.js 에 있던 것을 여기로 옮겼다. 거기서는 아무도 부르지 않았다.
 *
 * ── 이름 붙은 이벤트를 받는다 ─────────────────────────────────────
 * ⚠ 허브는 `event: notification` · `event: resync` · `event: ready` 로
 *   보낸다(gosvc cmd/notify/main.go 의 sse()). **onmessage 는 이름 없는
 *   이벤트만 받는다** — 옮기기 전 코드는 onmessage 만 달려 있어서, 누가
 *   불렀더라도 알림을 한 건도 못 받았을 것이다.
 *
 * ── 티켓을 주소에 싣는다 ─────────────────────────────────────────
 * ⚠ EventSource 는 헤더를 못 붙인다. 구독만 ?ticket= 으로 받는다
 *   (gosvc 의 streamTicket). nginx 가 이 경로의 접근 로그를 끈다.
 *
 * ── 끊기면 티켓을 새로 받아 다시 연다 ─────────────────────────────
 * ⚠ 자동 재연결은 **같은 주소로** 붙는다. 티켓이 만료되면 옛 티켓으로
 *   영원히 401 을 맞는다 — 알림만 조용히 안 온다. 판독 화면을 하루 종일
 *   켜 두는 자리라 브라우저에 맡기지 않고 우리가 닫고 다시 연다.
 *
 * ── resync ────────────────────────────────────────────────────────
 * 허브 버퍼가 넘치면 resync 가 먼저 온다. 놓친 알림을 이어붙이려 하지
 * 말고 목록을 통째로 다시 받는다.
 */
export function openNotifications({ issue, onEvent, onResync, onError } = {}) {
  let es = null;
  let closed = false;
  let tries = 0;
  let timer = null;

  const parse = (e) => { try { return JSON.parse(e.data); } catch { return null; } };

  async function open() {
    if (closed) return;
    let url = "/svc/v1/notify/stream";
    try {
      /* ⚠ scope_id 를 반드시 싣는다 — 서버가 빈 값을 먼저 막는다. 값은
         서버가 버리고 로그인한 계정으로 바꿔 끼운다(남의 알림 구독 방지) */
      const t = await issue({ purpose: "notify", scope_id: "me" });
      url += `?ticket=${encodeURIComponent(t.token)}`;
    } catch (e) {
      onError?.(e);
      return retry();
    }
    if (closed) return;

    es = new EventSource(url);
    es.addEventListener("ready", () => { tries = 0; });
    es.addEventListener("notification", (e) => { const d = parse(e); if (d) onEvent?.(d); });
    es.addEventListener("resync", (e) => onResync?.(parse(e)));
    es.onerror = (e) => {
      onError?.(e);
      es.close();
      es = null;
      retry();
    };
  }

  /* 1·2·4·8…초, 최대 30초. 서버가 죽었을 때 초당 한 번씩 두드리지 않는다 */
  function retry() {
    if (closed) return;
    const wait = Math.min(30000, 1000 * 2 ** tries++);
    timer = setTimeout(open, wait);
  }

  open();

  return () => {
    closed = true;
    clearTimeout(timer);
    es?.close();
  };
}
