import { useState } from "react";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Tilly from "../lib/Tilly";
import { Body, Head } from "../lib/Screen";
import { distanceKm, fmtKm, routeUrl, useNear } from "../lib/near";

/* 14 · 병원 찾기
 *
 * 검진과 진료를 받을 수 있는 협력 병원 목록이다.
 *
 * ── 위치는 브라우저에서만 쓴다 ─────────────────────────────
 *
 * ⚠ **좌표를 서버로 보내지 않는다.** 브라우저에서 받아 브라우저에서
 *   재고 끝난다(lib/near). 좌표는 그 자체가 민감한 정보라, 보내는 순간
 *   「어디에 살고 어느 병원을 다니는지」가 서버 기록에 남는다.
 *   그래서 서버에는 **병원 좌표만** 달라고 하고 거리는 우리가 잰다.
 *
 * ⚠ **화면을 열자마자 묻지 않는다.** 들어오자마자 위치 권한 창이 뜨면
 *   대개 거절한다 — 왜 필요한지 모르는 채로 받는 물음이라서다.
 *   「가까운 순으로」를 누를 때 그때 묻는다.
 *
 *   거절해도 화면은 그대로 돈다. 거리 줄과 정렬이 없을 뿐이다.
 *
 * ── 지도는 폰에 있는 것을 쓴다 ───────────────────────────────
 * 지도를 앱 안에 심으려면 키를 받아 빌드에 섞어야 하고 스크립트도
 * 수백 KB 다. 길찾기까지 지도 앱이 훨씬 잘한다 — 흉내 낼 이유가 없다.
 *
 * 지금 다니는 곳에는 표를 붙인다 — 목록에서 자기 병원을 못 찾아
 * 헤매지 않게.
 */
export default function Hospitals() {
  const [region, setRegion] = useState("");
  const [q, setQ] = useState("");
  const { loading, data, error, reload } = useApi(() => api.hospitals(), []);
  const near = useNear();

  return (
    <>
      <Head title="병원 찾기" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <Inner d={data} near={near}
                 region={region} setRegion={setRegion} q={q} setQ={setQ} />
        )}
      </Body>
    </>
  );
}

/* 거르는 일은 화면에서 한다. 목록이 손에 꼽을 만큼이라 서버를 다시
   부를 이유가 없다 — 지역을 누를 때마다 기다리게 하는 편이 나쁘다 */
function match(h, region, q) {
  if (region && region !== "전체" && h.region !== region) return false;
  const k = q.trim().toLowerCase();
  if (!k) return true;
  return [h.name, h.dept, h.address].some(
    (v) => String(v ?? "").toLowerCase().includes(k));
}

function Inner({ d, near, region, setRegion, q, setQ }) {
  const regions = d.regions ?? [];

  /* 거리를 재고, 위치를 받았으면 **가까운 순**으로 세운다.
     못 받았으면 서버가 준 순서를 그대로 둔다 — 임의로 섞지 않는다 */
  const items = (d.items ?? [])
    .filter((h) => match(h, region, q))
    .map((h) => ({ ...h, km: near.me ? distanceKm(near.me, h) : null }))
    .sort((a, b) => (a.km == null || b.km == null ? 0 : a.km - b.km));

  return (
    <>
      <label className="search">
        <span aria-hidden="true">⌕</span>
        <input value={q} placeholder="병원 이름 · 진료과 · 주소"
               onChange={(e) => setQ(e.target.value)} />
      </label>

      {/* 가까운 순 — 누를 때 위치를 묻는다 */}
      {near.state !== "off" && (
        <div className="nearbar">
          {near.state === "ready" ? (
            <span className="s">내 위치에서 가까운 순입니다</span>
          ) : near.state === "insecure" ? (
            /* 주소 때문에 막힌 것이다. 단추를 두면 눌러도 아무 일이
               안 나므로 아예 안 낸다 — 왜 안 되는지만 적는다 */
            <p className="hint">
              지금 주소(http)에서는 브라우저가 위치를 내주지 않습니다.
              <br />같은 화면을 <b>localhost</b> 로 여시면 됩니다.
            </p>
          ) : (
            <button className="btn soft" disabled={near.state === "asking"}
                    onClick={near.ask}>
              {near.state === "asking" ? "위치 확인 중…" : "가까운 순으로 보기"}
            </button>
          )}
          {near.why && <p className="hint">{near.why}</p>}
          {near.state === "ready" && (
            <p className="note">위치는 이 기기에서만 쓰이고 서버로 보내지 않습니다.</p>
          )}
        </div>
      )}

      {regions.length > 0 && (
        <div className="chips" role="group" aria-label="지역">
          {regions.map((r) => {
            const on = region === r || (!region && r === "전체");
            return (
              <button key={r} type="button" aria-pressed={on}
                      className={on ? "chip on" : "chip"}
                      onClick={() => setRegion(r === "전체" ? "" : r)}>
                {r}
              </button>
            );
          })}
        </div>
      )}

      {items.length === 0 ? (
        <div className="empty">
          <Tilly mood="rest" size="md" alt="" />
          <p>찾으시는 병원이 없습니다.</p>
        </div>
      ) : (
        <div className="list">
          {items.map((h) => (
            <div key={h.hospital_id} className="col hos">
              <div className="row">
                <span className="tx">
                  <b>{h.name}</b>
                  <span>{h.dept}</span>
                </span>
                {/* 거리는 위치를 받았을 때만 뜬다 */}
                {h.km != null && <span className="pill read">{fmtKm(h.km)}</span>}
              </div>

              <p className="hos-l">{h.address}</p>
              <p className="hos-l">{h.hours}</p>
              {h.note && <p className="hos-l hos-mine">{h.note}</p>}

              {/* 둘뿐이다.
                  · 번호를 글자로 또 적지 않는다 — 단추가 바로 건다
                  · 「지도」와 「길찾기」는 **같은 곳으로 간다.** 카카오맵이
                    둘 다 그 병원 자리를 열고, 길찾기 쪽이 거기서 더
                    나아간다. 같은 데 가는 단추를 둘 두면 무엇이 다른지
                    누르기 전에는 모른다 */}
              <div className="hos-go">
                <a className="btn soft" href={`tel:${h.phone.replaceAll("-", "")}`}>
                  전화
                </a>
                <a className="btn soft" href={routeUrl(h)}
                   target="_blank" rel="noreferrer">길찾기</a>
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="note">{d.note}</p>
    </>
  );
}
