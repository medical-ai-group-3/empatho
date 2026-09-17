import { useState } from "react";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Tilly from "../lib/Tilly";
import { Body, Head } from "../lib/Screen";

/* 14 · 병원 찾기
 *
 * 검진과 진료를 받을 수 있는 협력 병원 목록이다.
 *
 * ── 위치를 안 쓴다 ───────────────────────────────────────────
 *
 * ⚠ **기기 위치를 받지 않는다.** 「가까운 순」은 편하지만 그러려면
 *   위치를 서버로 보내야 하고, 그건 따로 동의를 받아야 하는 정보다.
 *   환자 앱에서 동의 하나를 더 받는 값은 싸지 않다 — 지역으로 고르는
 *   것으로 충분하다.
 *
 *   서버가 distance_km 를 주면 적고, 안 주면 거리 줄이 아예 없다.
 *   나중에 위치를 쓰기로 하면 화면은 안 고쳐도 된다.
 *
 * ── 전화가 가장 중요한 손잡이다 ──────────────────────────────
 * 이 화면에 오는 사람은 대개 **예약을 하려고** 온다. 그래서 전화번호가
 * 글자가 아니라 **누르면 걸리는 것**이어야 한다(tel:). 폰에서 번호를
 * 외워 자판으로 옮겨 적게 하면 안 된다.
 *
 * 지금 다니는 곳에는 표를 붙인다 — 목록에서 자기 병원을 못 찾아
 * 헤매지 않게.
 */
export default function Hospitals() {
  const [region, setRegion] = useState("");
  const [q, setQ] = useState("");
  const { loading, data, error, reload } = useApi(() => api.hospitals(), []);

  return (
    <>
      <Head title="병원 찾기" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <Inner d={data} region={region} setRegion={setRegion} q={q} setQ={setQ} />
        )}
      </Body>
    </>
  );
}

/* 거르는 일은 화면에서 한다. 목록이 손에 꼽을 만큼이라 서버를 다시
   부를 이유가 없다 — 지역을 누를 때마다 기다리게 하는 편이 나쁘다.
   목록이 길어지면 그때 api.hospitals({ region, q }) 로 넘긴다 */
function match(h, region, q) {
  if (region && region !== "전체" && h.region !== region) return false;
  const k = q.trim().toLowerCase();
  if (!k) return true;
  return [h.name, h.dept, h.address].some(
    (v) => String(v ?? "").toLowerCase().includes(k));
}

function Inner({ d, region, setRegion, q, setQ }) {
  const items = (d.items ?? []).filter((h) => match(h, region, q));
  const regions = d.regions ?? [];

  return (
    <>
      <label className="search">
        <span aria-hidden="true">⌕</span>
        <input value={q} placeholder="병원 이름 · 진료과 · 주소"
               onChange={(e) => setQ(e.target.value)} />
      </label>

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
                {h.note && <span className="pill new">{h.note}</span>}
              </div>

              <p className="hos-l">{h.address}</p>
              <p className="hos-l">{h.hours}</p>
              {/* 거리는 서버가 줄 때만 적는다 — 위 주석 참고 */}
              {h.distance_km != null && (
                <p className="hos-l">약 {h.distance_km}km</p>
              )}

              {/* 누르면 걸린다. 번호를 옮겨 적게 하지 않는다 */}
              <a className="btn soft" href={`tel:${h.phone.replaceAll("-", "")}`}>
                {h.phone} 전화하기
              </a>
            </div>
          ))}
        </div>
      )}

      <p className="note">{d.note}</p>
    </>
  );
}
