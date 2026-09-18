import { useCallback, useEffect, useState } from "react";

/* 내 위치와 거리
 * ════════════════════════════════════════════════════════════════
 *
 * ⚠ **위치는 서버로 보내지 않는다.** 브라우저에서 받아 브라우저에서
 *   재고 끝난다. 좌표는 그 자체가 민감한 정보라, 보내는 순간 「어디에
 *   살고 어느 병원을 다니는지」가 서버 기록에 남는다. 거리만 보여주자고
 *   치를 값이 아니다.
 *
 *   그래서 `distance_km` 를 서버에 달라고 하지 않는다. 병원 좌표만
 *   받아 오면 나머지는 여기서 한다.
 *
 * ⚠ **먼저 묻지 않는다.** 화면을 열자마자 위치 권한 창을 띄우면 대개
 *   거절한다 — 왜 필요한지 모르는 채로 받는 물음이라서다. 사람이
 *   「가까운 순으로 보기」를 누를 때 그때 묻는다.
 *
 * 거부 · 실패해도 화면은 그대로 돈다. 거리 줄이 없을 뿐이다.
 */

/* 두 좌표 사이 거리(km) — 하버사인.
 *
 * 지구를 공으로 치고 재는 식이다. 도시 안 몇 km 를 재는 데는 충분하다
 * (오차 0.5% 안쪽). 정확한 타원체 계산은 이 화면에 과하다. */
export function distanceKm(a, b) {
  if (!a || !b) return null;
  const R = 6371;
  const rad = (d) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLng = rad(b.lng - a.lng);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(s)));
}

/** 사람이 읽는 거리. 1km 아래는 100m 단위로 끊는다 — 「0.43km」보다
 *  「430m」가 걸어갈 만한지 바로 가늠된다 */
export function fmtKm(km) {
  if (km == null) return "";
  if (km < 1) return `${Math.round(km * 100) * 10}m`;
  return `${km.toFixed(1)}km`;
}

/* 위치 상태 — idle · asking · ready · denied · off
 *
 *   idle      아직 안 물었다 (기본)
 *   asking    브라우저가 묻는 중
 *   ready     좌표를 받았다
 *   denied    사람이 거절했거나 실패했다
 *   insecure  주소가 http 라 브라우저가 막았다 (아래 참고)
 *   off       이 브라우저에 위치 기능이 없다
 */
/* 브라우저가 위치를 내줄 수 있는 주소인가.
 *
 * ⚠ **http 로 열면 브라우저가 위치를 막는다.** localhost 는 예외로 봐주지만
 *   `http://lan-host:5180` 처럼 **IP 로 열면 막힌다** — 같은 서버인데
 *   주소만 다르면 안 되는 것이다.
 *
 *   이걸 「거절」과 같이 다루면 안 된다. 사람은 허용한 적도 없는데
 *   「허용하지 않으셨습니다」를 보게 되고, 설정을 뒤져도 바꿀 것이 없다.
 *   막힌 이유가 주소라는 것을 말해 줘야 한다.
 */
function blockedByAddress() {
  if (typeof window === "undefined") return false;
  return window.isSecureContext === false;
}

export function useNear() {
  const [state, setState] = useState(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) return "off";
    return blockedByAddress() ? "insecure" : "idle";
  });
  const [me, setMe] = useState(null);
  const [why, setWhy] = useState(null);

  const ask = useCallback(() => {
    if (!navigator.geolocation) return setState("off");
    if (blockedByAddress()) return setState("insecure");
    setState("asking");
    setWhy(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setMe({ lat: pos.coords.latitude, lng: pos.coords.longitude });
        setState("ready");
      },
      (err) => {
        setState("denied");
        /* 왜 안 됐는지 말한다. 「실패했습니다」만 뜨면 다시 눌러 볼지
           설정을 열어야 할지 모른다 */
        setWhy(err?.code === 1
          ? "위치 사용을 허용하지 않으셨습니다. 브라우저 주소창의 자물쇠에서 바꾸실 수 있어요."
          : "위치를 확인하지 못했습니다. 실내에서는 잘 안 잡힐 수 있어요.");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 5 * 60 * 1000 },
    );
  }, []);

  return { state, me, why, ask };
}

/* 화면을 떠나면 좌표를 들고 있지 않는다 — 메모리에만 있던 것이지만
   명시해 둔다. 저장소(localStorage)에는 애초에 안 넣는다 */
export function useForgetOnLeave(setMe) {
  useEffect(() => () => setMe?.(null), [setMe]);
}

/* ── 지도 ──────────────────────────────────────────────────────
 *
 * 지도를 **앱 안에 박지 않는다.** 카카오·네이버·구글 어느 쪽이든 지도를
 * 화면에 심으려면 키를 받아 넣어야 하고, 그 키는 빌드에 섞여 나간다.
 * 게다가 지도 한 장 때문에 스크립트 수백 KB 를 매번 받는다.
 *
 * 대신 **폰에 이미 있는 지도 앱**으로 넘긴다. 길찾기까지 그쪽이 훨씬
 * 잘한다 — 우리가 흉내 낼 이유가 없다.
 */
/* 자리만 보여주는 링크. 지금은 안 쓴다 — 「길찾기」가 같은 자리를 열고
   거기서 더 나아가서, 같은 데 가는 단추를 둘 두지 않기로 했다.
   지도만 필요한 자리가 생기면 이것을 쓴다 */
export const mapUrl = (h) =>
  h?.lat != null && h?.lng != null
    ? `https://map.kakao.com/link/map/${encodeURIComponent(h.name)},${h.lat},${h.lng}`
    : `https://map.kakao.com/link/search/${encodeURIComponent(h.address ?? h.name)}`;

export const routeUrl = (h) =>
  h?.lat != null && h?.lng != null
    ? `https://map.kakao.com/link/to/${encodeURIComponent(h.name)},${h.lat},${h.lng}`
    : `https://map.kakao.com/link/search/${encodeURIComponent(h.address ?? h.name)}`;
