/* DICOM 시리즈 목록(manifest) 을 받아 온다 — 두 뷰어가 같이 쓴다
 * ════════════════════════════════════════════════════════════════
 *
 * manifest 는 **파일 이름의 배열**이다.
 *
 *   ["0001.dcm", "0002.dcm", …]
 *
 * 뷰어는 baseUrl 을 앞에 붙여 `wadouri:` 로 cornerstone 에 넘긴다.
 *
 * ── 왜 따로 뺐나 ─────────────────────────────────────────────
 *
 * ⚠ **의료 샘플 자료는 저장소에 없다.** 용량이 커서 .gitignore 로 빼 두었다
 *   (public/dicom · mesh · models · samples). 각자 로컬에 채워 넣는다.
 *
 *   그래서 자료를 안 채운 사람이 판독 화면을 열면 manifest 요청이 404 인데,
 *   **Vite 개발 서버는 404 에 index.html 을 돌려준다** (SPA 라 그렇게 둔다).
 *   그걸 JSON 으로 읽으면 이런 오류가 난다.
 *
 *       SyntaxError: Unexpected token '<', "<!doctype "... is not valid JSON
 *
 *   화면에는 이 문장이 그대로 뜬다. 「DICOM 이 깨졌나」로 보이고 cornerstone
 *   쪽을 아무리 뒤져도 원인이 안 나온다. **실은 자료가 없는 것뿐이다.**
 *
 *   그래서 파싱하기 전에 막고 사람이 읽을 문장을 준다.
 */

/* Vite 가 404 대신 돌려준 SPA 껍데기인지 본다.
   content-type 만 보면 안 된다 — 개발 서버는 text/html 을 주지만 배포
   nginx 설정에 따라 다를 수 있다. 앞머리도 같이 본다. */
function looksLikeHtml(ct, text) {
  if (ct && ct.includes("text/html")) return true;
  return /^\s*<(!doctype|html)/i.test(text);
}

export class ManifestMissing extends Error {
  constructor(url) {
    super(
      "샘플 DICOM 자료가 없습니다. 용량 때문에 저장소에 올리지 않는 파일이라, " +
      "로컬 public/dicom/ 에 직접 넣어야 합니다 (.gitignore 참고).",
    );
    this.name = "ManifestMissing";
    this.url = url;
  }
}

/* 돌려주는 것 — 파일 이름 배열. 비어 있으면 빈 배열이다(오류가 아니다).
 *
 * 던지는 것
 *   ManifestMissing  자료가 없다 — 위 사정
 *   Error            그 밖의 실패(권한 · 서버 오류 · 모양이 다름)
 */
export async function loadManifest(url, { signal } = {}) {
  let res;
  try {
    res = await fetch(url, { signal });
  } catch (e) {
    if (e?.name === "AbortError") throw e;
    throw new Error(`목록을 받지 못했습니다 (${e?.message ?? "연결 실패"})`);
  }

  /* 배포에서는 404 가 그대로 온다 — 그때도 같은 문장으로 묶는다 */
  if (res.status === 404) throw new ManifestMissing(url);
  if (!res.ok) throw new Error(`목록 요청이 실패했습니다 (${res.status})`);

  const text = await res.text();
  if (looksLikeHtml(res.headers.get("content-type"), text)) {
    throw new ManifestMissing(url);
  }

  let files;
  try {
    files = JSON.parse(text);
  } catch {
    throw new Error("목록이 JSON 이 아닙니다.");
  }
  if (!Array.isArray(files)) {
    throw new Error("목록은 파일 이름의 배열이어야 합니다.");
  }
  /* 문자열만 남긴다. 섞여 들어오면 wadouri 주소가 "undefined" 가 된다 */
  return files.filter((f) => typeof f === "string" && f);
}
