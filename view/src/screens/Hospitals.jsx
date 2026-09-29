import { useEffect, useState } from "react";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Tilly from "../lib/Tilly";
import { Body, Head } from "../lib/Screen";
import { distanceKm, fmtKm, nearestRegion, routeUrl, useNear } from "../lib/near";
import Call from "../lib/Call";
import Icon from "../lib/Icon";

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
  /* 찾은 말 · 고른 지역. 입력칸과 **따로 둔다** — 글자를 칠 때마다
     서버를 부르지 않는다(바깥 공공데이터라 일일 한도가 있다). 지역은
     누르는 즉시, 이름은 넣고 눌렀을 때 바뀐다 */
  const [asked, setAsked] = useState({ q: "", region: "" });
  const { loading, data, error, reload } = useApi(
    () => api.hospitals({ q: asked.q, region: asked.region }),
    [asked.q, asked.region]);
  const near = useNear();
  /* 위치를 받았는데 「전체」면 가장 가까운 시도로 옮긴다 — 전국 첫 장
     20건 안에서는 가까운 순이 의미가 없다. 한 번만 한다: 그 뒤에 사람이
     「전체」를 다시 누르면 그대로 둔다 */
  useEffect(() => {
    if (near.state !== "ready" || asked.region) return;
    const r = nearestRegion(near.me);
    if (r) { setRegion(r); setAsked((a) => ({ ...a, region: r })); }
  }, [near.state]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Head title="병원 찾기" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <Inner d={data} near={near}
                 region={region} q={q} setQ={setQ}
                 onRegion={(r) => { setRegion(r); setAsked((a) => ({ ...a, region: r })); }}
                 onSearch={() => setAsked((a) => ({ ...a, q: q.trim() }))} />
        )}
      </Body>
    </>
  );
}

/* ⚠ 전에는 여기서 걸렀다(match 함수). 목록이 손에 꼽을 만큼이라 서버를
   다시 부를 이유가 없다고 봤는데, 붙고 보니 **전국 요양기관**이 온다
   — 한 화면에 스무 건씩 들어오는 것을 화면에서 걸러 봐야 그 스무 건
   안에서만 걸러진다. 「서울」을 눌렀는데 이 장에 서울이 없으면 빈 화면이
   나오고, 다음 장에는 있다.

   그래서 이름도 지역도 **서버가 거른다.** 화면은 받은 것을 그대로 그린다.
   심평원 API 가 yadmNm(이름) · sidoCd(시도)로 이미 걸러 주는 자리다. */

function Inner({ d, near, region, q, setQ, onRegion, onSearch }) {
  /* 지역 칩은 서버가 준 목록이다. 화면이 시도 이름을 들고 있으면 그 표와
     서버의 코드 표가 어긋날 수 있고, 어긋나면 그 지역만 조용히 빈다 */
  const regions = d.regions ?? [];
  /* 전화 확인 창을 띄운 병원. 한 번에 하나만 뜬다 */
  const [calling, setCalling] = useState(null);

  /* 거리를 재고, 위치를 받았으면 **가까운 순**으로 세운다.
     못 받았으면 서버가 준 순서를 그대로 둔다 — 임의로 섞지 않는다 */
  const items = (d.items ?? [])
    /* 좌표가 없는 기관이 섞여 온다(심평원 자료가 그렇다). 그런 곳은
       거리를 못 재고 길찾기도 못 하지만 **목록에서 빼지는 않는다** —
       전화는 걸 수 있고, 찾던 병원이 그것일 수 있다 */
    .map((h) => ({
      ...h,
      km: near.me && h.lat != null && h.lng != null ? distanceKm(near.me, h) : null,
    }))
    /* 거리를 아는 것끼리만 세운다. 모르는 것은 뒤로 보낸다 —
       0 으로 치면 맨 앞에 서서 「제일 가까운 곳」처럼 보인다 */
    .sort((a, b) => {
      if (a.km == null && b.km == null) return 0;
      if (a.km == null) return 1;
      if (b.km == null) return -1;
      return a.km - b.km;
    });

  return (
    <>
      {/* 누를 때 찾는다. 글자마다 부르면 바깥 공공데이터의 일일 한도를
          「세브란스」 한 번에 다섯 번씩 쓴다 */}
      <form className="search" onSubmit={(e) => { e.preventDefault(); onSearch(); }}>
        <Icon name="search" />
        <input value={q} placeholder="병원 이름"
               aria-label="병원 이름"
               onChange={(e) => setQ(e.target.value)} />
        <button className="btn soft" type="submit">찾기</button>
      </form>

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
                      onClick={() => onRegion(r === "전체" ? "" : r)}>
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
              {/* 진료시간. 자료에 없는 기관이 있어 있을 때만 그린다 —
                  칸을 비워 두면 빈 줄이 남아 목록이 성글어 보인다.

                  ⚠ 요일이 다 같을 때만 「평일 09:00~18:00」로 묶여 온다.
                    하루라도 다르면 서버가 요일을 따로 적어 보낸다 —
                    묶어 놓고 실제로는 수요일만 오후 휴진이면 그 한 줄을
                    믿고 갔다가 헛걸음한다. 화면에서 다시 묶지 말 것 */}
              {h.hours && <p className="hos-l">{h.hours}</p>}
              {/* 「휴게시간 13:00~14:00」 같은 안내. 진료시간만 보고 갔다가
                  점심시간에 닿는 일을 줄인다 */}
              {h.etc && <p className="hos-l">{h.etc}</p>}
              {h.note && <p className="hos-l hos-mine">{h.note}</p>}

              {/* 둘뿐이다.
                  · 번호를 글자로 또 적지 않는다 — 단추가 바로 건다
                  · 「지도」와 「길찾기」는 **같은 곳으로 간다.** 카카오맵이
                    둘 다 그 병원 자리를 열고, 길찾기 쪽이 거기서 더
                    나아간다. 같은 데 가는 단추를 둘 두면 무엇이 다른지
                    누르기 전에는 모른다 */}
              <div className="hos-go">
                {/* 바로 걸지 않고 한 번 묻는다 — 잘못 눌러 병원에 전화가
                    가는 것을 막고, 못 거는 기기에서는 번호를 보여 준다
                    (lib/Call 참고) */}
                {/* 번호도 좌표도 없는 기관이 섞여 온다. 눌러도 아무 일이
                    안 나는 단추를 두면 「왜 안 되지」를 만든다 — 아예 안 낸다 */}
                {h.phone && (
                  <button className="btn soft" onClick={() => setCalling(h)}>
                    전화
                  </button>
                )}
                {h.lat != null && h.lng != null && (
                  <a className="btn soft" href={routeUrl(h)}
                     target="_blank" rel="noreferrer">길찾기</a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <p className="note">{d.note}</p>

      {calling && (
        <Call name={calling.name} phone={calling.phone}
              onClose={() => setCalling(null)} />
      )}
    </>
  );
}
