import { useEffect, useState } from "react";

/* 티켓으로 파일 받아오기
 * ════════════════════════════════════════════════════════════════
 *
 * ⚠ **`<img src="…">` 는 Authorization 헤더를 못 보낸다.**
 *
 *   브라우저가 이미지를 가져올 때 헤더를 우리가 못 붙인다. 그런데
 *   Go 관문은 `Authorization: Bearer <티켓 토큰>` 을 요구한다.
 *   그래서 주소를 그냥 img 에 꽂으면 401 이 난다.
 *
 *   해결: **우리가 fetch 로 받아서** blob 으로 만들고, 그 blob 주소를
 *   img 에 준다. 헤더는 fetch 가 붙인다.
 *
 *     티켓 발급 (검사·검체당 한 번)
 *       → fetch(/svc/v1/files/<key>, { Authorization: Bearer <토큰> })
 *       → URL.createObjectURL(blob)
 *       → <img src="blob:…">
 *
 *   읽기 티켓은 1회용이 아니라 한 세션에 하나면 되므로, 한 번 받아
 *   여러 장에 같이 쓴다.
 *
 * ── 주소를 두 가지로 받는다 ──────────────────────────────────
 *   { url: "…" }   그대로 쓴다 (목업의 data: 주소, 공개 URL)
 *   { key: "…" }   티켓을 받아 Go 에서 가져온다
 *
 * 목업에서는 url 로 오고 실제 서버에서는 key 로 온다. 화면은 둘을
 * 구분하지 않는다.
 */

const SVC = "/svc/v1/files";

/* 티켓 하나를 대상(검체·검사)마다 기억해 둔다. 장마다 새로 받지 않는다 */
const tickets = new Map();

async function getTicket(issue, scopeId) {
  const hit = tickets.get(scopeId);
  /* 만료 30초 전부터는 새로 받는다 — 받는 도중에 끊기지 않게 */
  if (hit && hit.expires > Date.now() + 30000) return hit.token;

  const t = await issue({ purpose: "download", scope_id: scopeId });
  const token = t.token;
  const expires = t.expires_at ? Date.parse(t.expires_at) : Date.now() + 240000;
  tickets.set(scopeId, { token, expires });
  return token;
}

/* 화면이 닫히면 티켓도 버린다 */
export function dropTickets() {
  tickets.clear();
}

/* 한 장을 blob 주소로 바꿔 준다.
 *
 * 돌려주는 것 — { src, loading, error }
 * src 는 화면이 사라질 때 revoke 한다. 안 하면 메모리에 계속 쌓인다.
 */
export function useFile(spec, issue, scopeId) {
  const [state, set] = useState({ src: null, loading: false, error: null });
  const url = spec?.url ?? null;
  const key = spec?.key ?? null;

  useEffect(() => {
    /* 그대로 쓸 수 있는 주소 — 목업이 여기로 온다 */
    if (url) {
      set({ src: url, loading: false, error: null });
      return;
    }
    if (!key || !issue || !scopeId) {
      set({ src: null, loading: false, error: null });
      return;
    }

    let live = true;
    let made = null;
    set({ src: null, loading: true, error: null });

    (async () => {
      const token = await getTicket(issue, scopeId);
      const res = await fetch(`${SVC}/${key}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        throw Object.assign(new Error("영상을 불러오지 못했습니다"), {
          status: res.status,
        });
      }
      const blob = await res.blob();
      if (!live) return;
      made = URL.createObjectURL(blob);
      set({ src: made, loading: false, error: null });
    })().catch((e) => {
      if (live) set({ src: null, loading: false, error: e });
    });

    return () => {
      live = false;
      if (made) URL.revokeObjectURL(made);
    };
  }, [url, key, issue, scopeId]);

  return state;
}
