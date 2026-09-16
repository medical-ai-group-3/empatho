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

const SVC = "/svc/v1";

/* ── 무엇을 받을지 — 세 가지다 ────────────────────────────────
 *
 *   { url }     그대로 쓴다 (목업의 data: 주소, 공개 URL)
 *   { key }     Garage 에 있는 파일. 병리 크롭 · 초음파가 여기다
 *   { sop }     맘모 한 장. **Orthanc 에 있다**
 *   { series }  MRI 시리즈 zip. Orthanc
 *
 * ⚠ **티켓 범위 규칙이 둘로 갈린다** (gosvc 의 fromOrthanc).
 *
 *     파일    ObjectKeyPrefix 로 **시작만** 본다
 *             → 티켓 하나로 그 검체의 여러 장을 받는다
 *     DICOM   **정확히 일치**해야 한다
 *             → 영상 한 건에 티켓 하나. 맘모 4장이면 티켓 4개다
 *
 *   「dicom/series/ab 티켓으로 ab12 를 열면 안 된다」는 이유로 그렇게
 *   돼 있다. 그래서 티켓 캐시를 **대상 id 가 아니라 범위 문자열로**
 *   건다 — 전에는 검체 id 하나로만 걸어서, 맘모에 그대로 쓰면 첫 장
 *   티켓을 둘째 장에 재사용하다 403 TICKET_SCOPE_MISMATCH 를 맞는다.
 */
function targetOf(spec, scopeId) {
  if (spec?.sop) {
    return { scope: `dicom/instances/${spec.sop}`,
             path: `${SVC}/dicom/instances/${spec.sop}` };
  }
  if (spec?.series) {
    return { scope: `dicom/series/${spec.series}`,
             path: `${SVC}/dicom/series/${spec.series}` };
  }
  if (spec?.key) {
    /* 파일은 접두사로 보므로 범위가 대상(검체·검사) 단위다 */
    return { scope: scopeId, path: `${SVC}/files/${spec.key}` };
  }
  return null;
}

/* 범위 하나에 티켓 하나를 기억해 둔다. 장마다 새로 받지 않는다 */
const tickets = new Map();

async function getTicket(issue, scope) {
  const hit = tickets.get(scope);
  /* 만료 30초 전부터는 새로 받는다 — 받는 도중에 끊기지 않게 */
  if (hit && hit.expires > Date.now() + 30000) return hit.token;

  /* ⚠ 요청 본문 모양을 **아직 확인받지 못했다** (2026-09-16 기준).
     POST /tickets 가 있다는 것만 들었고 무엇을 넣어야 하는지는 답을
     기다리는 중이다. 지금은 scope_id 에 위 범위 문자열을 그대로 넣는다 —
     DICOM 은 서버가 그 값과 정확히 대조하기 때문이다. 답이 오면 이 한
     줄만 고치면 된다. */
  const t = await issue({ purpose: "download", scope_id: scope });
  const token = t.token;
  const expires = t.expires_at ? Date.parse(t.expires_at) : Date.now() + 240000;
  tickets.set(scope, { token, expires });
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

  /* 범위와 주소를 먼저 정한다. 아래 useEffect 가 이 둘만 보면 되도록
     원시값으로 풀어 둔다 — spec 객체를 그대로 의존성에 넣으면 부모가
     다시 그릴 때마다 새 객체라 무한히 다시 부른다 */
  const t = url ? null : targetOf(spec, scopeId);
  const scope = t?.scope ?? null;
  const path = t?.path ?? null;

  useEffect(() => {
    /* 그대로 쓸 수 있는 주소 — 목업이 여기로 온다 */
    if (url) {
      set({ src: url, loading: false, error: null });
      return;
    }
    if (!path || !scope || !issue) {
      set({ src: null, loading: false, error: null });
      return;
    }

    let live = true;
    let made = null;
    set({ src: null, loading: true, error: null });

    (async () => {
      const token = await getTicket(issue, scope);
      const res = await fetch(path, {
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
  }, [url, path, scope, issue]);

  return state;
}
