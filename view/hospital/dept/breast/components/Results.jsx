import { Chip } from "../../../lib/Parts";
import { MODALITY, label, modality as asModality } from "../../../codes";
import * as H from "../../home";
import { pathExtras, pendingOf, receptors, upper } from "../results";

/* 결과 줄들 — 대기 환자 · 환자 상세 · 치료 방침 ① 이 같이 쓴다.
 *
 * 판정은 readings(api.js 의 breast.readings)에서 온다. 확정된 것만, 최신이
 * 앞이다. 글자 만들기는 ../results.js. */

export function PendingLine({ orders, empty = null }) {
  const list = pendingOf(orders);
  if (!list.length) return empty;
  return (
    <p className="bf-pend">
      {list.map((o) => <Chip key={o.id} tone="dot">{o.text}</Chip>)}
    </p>
  );
}

/* 영상 판독 — 검사마다 한 줄. 판정 · 날짜 · 밀도. lead 면 맨 위 소견을 편다 */
export function RadRows({ rows = [], lead = true }) {
  if (!rows.length) return <p className="hcard-k">확정된 영상 판독이 없습니다</p>;
  return (
    <ul className="bf-res">
      {rows.map((r, i) => (
        <li key={r.study_id ?? i} className={i === 0 ? "on" : undefined}>
          <span className="bf-res-h">
            <b>{label(MODALITY, asModality(r.modality)) || "영상"}</b>
            <time>{H.day(r.at) ?? "—"}</time>
            <span className="home-fill" />
            {r.density && <Chip>밀도 {r.density}</Chip>}
            {r.grade && <Chip tone={i === 0 ? "fill" : "line"}>BI-RADS {r.grade}</Chip>}
          </span>
          {i === 0 && lead && r.note && <span className="bf-res-b">{r.note}</span>}
        </li>
      ))}
    </ul>
  );
}

/* 병리 — 검체마다 한 줄. B 분류 · 진단 · 조직형 · 등급 · 수용체 */
export function PathRows({ rows = [] }) {
  if (!rows.length) return <p className="hcard-k">확진된 병리 결과가 없습니다</p>;
  return (
    <ul className="bf-res">
      {rows.map((r, i) => {
        const extra = [...pathExtras(r), ...receptors(r)];
        return (
          <li key={r.specimen_id ?? i} className={i === 0 ? "on" : undefined}>
            <span className="bf-res-h">
              <b>{r.label ?? `검체 ${r.specimen_id}`}</b>
              <time>{H.day(r.at) ?? "—"}</time>
              <span className="home-fill" />
              {r.grade && <Chip tone={i === 0 ? "fill" : "line"}>{upper(r.grade)}</Chip>}
            </span>
            {r.note && <span className="bf-res-b">{r.note}</span>}
            {extra.length > 0 && (
              <span className="bf-rcp">{extra.map((x) => <Chip key={x}>{x}</Chip>)}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
