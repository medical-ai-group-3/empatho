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
 * ── 규격 (2026-09-17, empatho-app 저장소에서 직접 확인) ────────
 *
 *   그동안 요청 본문 모양을 못 받아서 짐작으로 보내고 있었는데,
 *   서버 코드를 보고 맞췄다. 짐작이 **틀렸었다.**
 *
 *     POST /api/v1/tickets
 *       { purpose, scope_kind, scope_id }
 *     ← { token, expires_at, object_key_prefix, max_bytes, … }
 *
 *   · scope_id 는 **검체·검사의 정수 PK** 다. 전에는 `dicom/instances/…`
 *     같은 경로 문자열을 넣고 있었는데, 서버는 그 값으로 Specimen·Study
 *     행을 찾는다(`model.objects.get(pk=int(scope_id))`). 경로를 넣으면
 *     TARGET_NOT_FOUND 다.
 *   · scope_kind 는 **빼면 안 된다.** purpose 가 여러 대상을 받으면
 *     서버가 요구한다 — tile 은 study·specimen 둘이라 필수다.
 *
 * ── 왜 download 가 아니라 tile 인가 ──────────────────────────
 *
 *   유효기간이 다르고, 그 차이가 우리 쓰임새를 가른다.
 *
 *     download  120초. 「받는 즉시 끝나는」 한 번짜리
 *     tile      900초. 주석에 **「뷰어 한 세션」** 이라고 적혀 있다
 *
 *   판독 화면은 크롭·시리즈를 넘겨 가며 오래 본다. 티켓 하나로 그
 *   검체의 여러 장을 받는 구조라 tile 이 맞다. Go 의 `getFile` 도 둘 다
 *   받는다(`purposeDownload, purposeTile`).
 *
 * ── 범위가 곧 권한이다 ───────────────────────────────────────
 *
 *   서버가 티켓에 `object_key_prefix = "<scope_kind>/<scope_id>"` 를
 *   서명해 넣고, Go 는 **키가 그 아래인지**만 본다.
 *
 *     티켓 specimen/801  →  specimen/801/crop_01.png  ○
 *                           specimen/802/crop_01.png  ✗ 403
 *
 *   그래서 **검체·검사 하나에 티켓 하나**면 그 아래 전부를 받는다.
 *   장마다 새로 받지 않는다.
 *
 * ── 주소를 두 가지로 받는다 ──────────────────────────────────
 *   { url: "…" }   그대로 쓴다 (목업의 data: 주소, 공개 URL)
 *   { key: "…" }   티켓을 받아 Go 에서 가져온다
 *
 * 목업에서는 url 로 오고 실제 서버에서는 key 로 온다.
 */

const SVC = "/svc/v1";

/* 뷰어가 쓰는 티켓. 위 「왜 tile 인가」 참고 */
const PURPOSE = "tile";

/* ── DICOM 도 같은 티켓으로 받는다 ────────────────────────────
 *
 * 전에는 못 받았다. Go 가 DICOM 에 대해서만 티켓 범위를 «정확히 일치»로
 * 봤는데(`cl.ObjectKeyPrefix != "dicom/instances/<UID>"`), `POST /tickets`
 * 는 접두사를 `{종류}/{id}` 로만 만들어서 그 모양을 낼 수가 없었다.
 * 그걸 낼 수 있는 것은 issue() 를 직접 부르는 Celery 뿐이라, 화면에서는
 * 늘 403 이었다 — **맘모 원본과 MRI 시리즈를 받을 길이 아예 없었다.**
 *
 * 2026-09-18 — Go 가 올릴 때 Orthanc 에 대상을 적어 두고, 내려줄 때 그걸
 * 티켓과 대조하도록 바꿨다(gosvc 의 dicomAllowed). 그래서 **파일과 똑같은
 * 검사 티켓 하나로** 맘모도 MRI 도 받는다.
 *
 * ⚠ 그 기능 **전에 올라간 자료에는 적힌 것이 없다.** 그런 자료는 403 이
 *   난다 — 다시 올리거나 Orthanc 메타데이터를 채워야 한다.
 */
function targetOf(spec, scope) {
  if (!scope?.kind || scope?.id == null) return null;
  const common = {
    scopeKey: `${scope.kind}/${scope.id}`,
    kind: scope.kind,
    id: scope.id,
  };
  /* 맘모 한 장 — SOP Instance UID 로 찾는다 */
  if (spec?.sop) return { ...common, path: `${SVC}/dicom/instances/${spec.sop}` };
  /* MRI 시리즈 — Orthanc 시리즈 ID. zip 으로 온다 */
  if (spec?.series) return { ...common, path: `${SVC}/dicom/series/${spec.series}` };
  /* AI가 만든 세그멘테이션·메시·오버레이는 원본 버킷이 아니라
     empatho-derived 에 저장된다. 원본 파일 경로로 요청하면 404가 나거나
     빈 화면이 되므로 파생물 전용 다운로드 라우트를 사용한다. */
  if (spec?.derived && spec?.key) return { ...common, path: `${SVC}/derived/${spec.key}` };
  if (spec?.key) return { ...common, path: `${SVC}/files/${spec.key}` };
  return null;
}

/* 범위 하나에 티켓 하나를 기억해 둔다. 장마다 새로 받지 않는다 */
const tickets = new Map();

/* 업로드는 같은 대상의 여러 장을 올릴 수 있다. tile 티켓과 목적이 달라
   섞어 쓰면 안 되므로 별도 캐시를 둔다. */
const uploadTickets = new Map();

async function getTicket(issue, t) {
  const hit = tickets.get(t.scopeKey);
  /* 만료 30초 전부터는 새로 받는다 — 받는 도중에 끊기지 않게 */
  if (hit && hit.expires > Date.now() + 30000) return hit.token;

  const res = await issue({
    purpose: PURPOSE,
    scope_kind: t.kind,
    scope_id: t.id,
  });
  const token = res.token;
  /* 서버가 준 만료를 쓴다. 없으면 tile 기본값(900초)보다 짧게 잡아 둔다 —
     짧게 잡으면 한 번 더 받을 뿐이지만, 길게 잡으면 죽은 티켓을 쓴다 */
  const expires = res.expires_at
    ? Date.parse(res.expires_at)
    : Date.now() + 600000;
  tickets.set(t.scopeKey, { token, expires });
  return token;
}

/* 화면이 닫히면 티켓도 버린다 */
export function dropTickets() {
  tickets.clear();
  uploadTickets.clear();
}

/* 파일 올리기
 *
 * 다운로드 티켓(tile)은 화면을 보는 동안 재사용하지만, 업로드 티켓은
 * 파일의 종류·크기 제한까지 확인해야 하므로 파일 하나를 올릴 때마다
 * 새로 받는다. Django에는 바이트를 보내지 않고, 발급받은 짧은 수명
 * 티켓으로 Go file-gateway에만 원본을 보낸다.
 *
 * issue  cfg.api.ticket
 * scope  { kind: "study" | "specimen", id }
 * purpose "dicom_upload" | "wsi_upload"
 */
async function getUploadTicket(issue, scope, purpose, contentType, refresh = false) {
  const key = `${purpose}:${scope.kind}/${scope.id}`;
  const cached = uploadTickets.get(key);
  if (!refresh && cached && cached.expires > Date.now() + 10000) return cached.token;

  const ticket = await issue({
    purpose,
    scope_kind: scope.kind,
    scope_id: scope.id,
    content_type: contentType,
  });
  if (!ticket?.token) throw new Error("업로드 권한을 받지 못했습니다.");
  const expires = ticket.expires_at ? Date.parse(ticket.expires_at) : Date.now() + 290000;
  uploadTickets.set(key, { token: ticket.token, expires, maxBytes: ticket.max_bytes });
  return ticket.token;
}

async function postFile(token, file, contentType) {
  let res;
  try {
    res = await fetch(`${SVC}/files`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": contentType,
        "X-Filename": file.name,
      },
      body: file,
    });
  } catch (e) {
    throw Object.assign(new Error(e?.message || "파일 서버에 연결하지 못했습니다."), {
      status: 0,
    });
  }

  if (res.ok) return res.status === 204 ? null : res.json().catch(() => null);

  let detail = "파일을 올리지 못했습니다.";
  let code = null;
  try {
    const body = await res.json();
    detail = body?.error?.message ?? body?.detail ?? detail;
    code = body?.error?.code ?? body?.code ?? null;
  } catch { /* 본문이 없는 gateway 오류도 위 문구로 안내한다. */ }
  if (res.status === 403) detail = "이 파일을 올릴 권한이 없습니다.";
  if (res.status === 413 || code === "UPLOAD_TOO_LARGE") detail = "파일 크기가 허용 용량을 초과했습니다.";
  if (res.status === 422 || code === "TARGET_NOT_FOUND") detail = "검사 또는 검체 정보를 찾지 못했습니다. 화면을 새로고침해 주세요.";
  if (res.status === 502 || code === "CALLBACK_FAILED") {
    detail = "파일은 저장되었지만 등록 확인에 실패했습니다. 다시 올리지 말고 담당자에게 알려 주세요.";
  }
  throw Object.assign(new Error(detail), { status: res.status, code });
}

export async function uploadFile(issue, scope, file, purpose) {
  if (!issue || !scope?.kind || scope.id == null || !file) {
    throw new Error("업로드 정보를 준비하지 못했습니다.");
  }

  const contentType = file.type || "application/octet-stream";
  const token = await getUploadTicket(issue, scope, purpose, contentType);
  const cacheKey = `${purpose}:${scope.kind}/${scope.id}`;
  const maxBytes = uploadTickets.get(cacheKey)?.maxBytes;
  if (maxBytes != null && file.size > Number(maxBytes)) {
    throw new Error("파일 크기가 허용 용량을 초과했습니다.");
  }

  try {
    return await postFile(token, file, contentType);
  } catch (e) {
    /* 업로드 티켓은 300초짜리다. 401일 때만 새 티켓으로 한 번 재시도한다.
       502 CALLBACK_FAILED는 파일이 이미 저장됐을 수 있어 절대 재시도하지 않는다. */
    if (e?.status !== 401) throw e;
    const fresh = await getUploadTicket(issue, scope, purpose, contentType, true);
    return postFile(fresh, file, contentType);
  }
}

/* 한 장을 blob 주소로 바꿔 준다.
 *
 * spec   { url } 이거나 { key } — 위 참고
 * issue  티켓 발급 함수 (cfg.api.ticket)
 * scope  { kind: "specimen" | "study", id }  — 티켓이 열 범위
 *
 * 돌려주는 것 — { src, loading, error }
 * src 는 화면이 사라질 때 revoke 한다. 안 하면 메모리에 계속 쌓인다.
 */
export function useFile(spec, issue, scope) {
  const [state, set] = useState({ src: null, loading: false, error: null });
  const url = spec?.url ?? null;

  /* 범위와 주소를 먼저 정한다. 아래 useEffect 가 원시값만 보면 되도록
     풀어 둔다 — spec 객체를 그대로 의존성에 넣으면 부모가 다시 그릴
     때마다 새 객체라 무한히 다시 부른다 */
  const t = url ? null : targetOf(spec, scope);
  const scopeKey = t?.scopeKey ?? null;
  const path = t?.path ?? null;
  const kind = t?.kind ?? null;
  const id = t?.id ?? null;

  useEffect(() => {
    /* 그대로 쓸 수 있는 주소 — 목업이 여기로 온다 */
    if (url) {
      set({ src: url, loading: false, error: null });
      return;
    }
    if (!path || !scopeKey || !issue) {
      set({ src: null, loading: false, error: null });
      return;
    }

    let live = true;
    let made = null;
    set({ src: null, loading: true, error: null });

    (async () => {
      const token = await getTicket(issue, { scopeKey, kind, id });
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
  }, [url, path, scopeKey, kind, id, issue]);

  return state;
}
