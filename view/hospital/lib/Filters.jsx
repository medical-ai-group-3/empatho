import { useSearchParams } from "react-router-dom";

/* 거르는 칩 — 홈 주 큐 · 대기 큐 · 목록이 같이 쓴다
 * ════════════════════════════════════════════════════════════════
 *
 *   groups  [{ key, label, items: [{ key, name, test?(row, ctx), query? }] }]
 *
 * 묶음마다 하나만 켠다. 묶음의 첫 칩이 기본(보통 「전체」 — test · query 없음).
 * 묶음끼리는 AND 다.
 *
 * ⚠ **query 와 test 를 둘 다 적는다.** query 는 서버 필터(있으면 서버가
 *   거른다), test 는 화면이 한 번 더 거르는 것이다. 서버가 그 필터를 모르고
 *   전부 돌려줘도 화면은 맞는 것만 보인다 — 서버가 준비되는 순서를
 *   기다리지 않는다.
 */
export function Filters({ groups, value, onChange }) {
  if (!groups?.length) return null;
  return (
    <div className="qfilters">
      {groups.map((g) => {
        const cur = value?.[g.key] ?? g.items[0]?.key;
        return (
          <div className="sorts" role="group" aria-label={g.label} key={g.key}>
            {g.label && <span className="sorts-k">{g.label}</span>}
            {g.items.map((it) => (
              <button type="button" key={it.key} aria-pressed={cur === it.key}
                      className={`pill${cur === it.key ? " on" : ""}`}
                      onClick={() => onChange({ ...value, [g.key]: it.key })}>
                {it.name}
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* 묶음마다 켜진 칩 */
export function picked(groups = [], value = {}) {
  return groups.map((g) => g.items.find((it) => it.key === value?.[g.key]) ?? g.items[0])
    .filter(Boolean);
}

export function applyFilters(rows, groups, value, ctx) {
  const on = picked(groups, value).filter((it) => it.test);
  return on.length ? rows.filter((r) => on.every((it) => it.test(r, ctx))) : rows;
}

/* 서버로 보낼 질의 — 켜진 칩의 query 를 합친다 */
export function filterQuery(groups, value) {
  return Object.assign({}, ...picked(groups, value).map((it) => it.query ?? {}));
}

/* 켠 칩을 주소에 적는다 — 홈의 「초안 n」을 누르면 걸러진 목록으로 온다.
   ⚠ 기본값(첫 칩)은 주소에서 뺀다. 안 빼면 주소가 늘 지저분하다 */
export function useFilterParams(groups = []) {
  const [params, setParams] = useSearchParams();
  const value = Object.fromEntries(groups.map((g) => [g.key, params.get(g.key) ?? g.items[0]?.key]));
  const set = (next) => setParams((prev) => {
    const out = new URLSearchParams(prev);
    groups.forEach((g) => {
      const v = next?.[g.key];
      if (v == null || v === g.items[0]?.key) out.delete(g.key);
      else out.set(g.key, v);
    });
    return out;
  }, { replace: true });
  return [value, set];
}
