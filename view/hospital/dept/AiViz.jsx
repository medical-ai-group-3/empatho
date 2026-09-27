/* AI 산출값 시각화 조각 — 이미지 오버레이가 아닌 표·그래프 쪽
 * ────────────────────────────────────────────────────────────────
 *
 * 「AI 산출값 시각화 방안」(2026-09-22) 에 적힌 것 중 **저장 값만으로 그릴
 * 수 있는 것**을 여기 모은다. 모델을 더 돌리지 않는다.
 *
 * ⚠ 값이 없으면 그리지 않는다. 0 과 「없음」은 다르다 — 빈 막대는
 *   「0%」로 읽히고, 그건 모델이 낸 말이 아니다. 각 컴포넌트가 null 을
 *   받으면 null 을 돌려주고, 부르는 쪽은 그대로 두면 된다.
 *
 * SVG 를 쓰지 않는다. 막대·게이지 정도는 div 폭으로 충분하고, 그래야
 * 글꼴·색이 화면 토큰을 그대로 따른다.
 */

const isNum = (v) => typeof v === "number" && Number.isFinite(v);

/* 두 값이 합쳐 100 이 되는 비율 띠. TSR(종양:간질)이 이 모양이다. */
export function SplitBar({ label, parts }) {
  const use = (parts ?? []).filter((p) => isNum(p.value));
  const total = use.reduce((s, p) => s + p.value, 0);
  if (use.length === 0 || total <= 0) return null;

  return (
    <div className="viz">
      {label && <div className="viz-h">{label}</div>}
      <div className="viz-split">
        {use.map((p, i) => (
          <span key={i} className={`viz-seg t${i}`}
                style={{ width: `${(p.value / total) * 100}%` }}
                title={`${p.name} ${p.value}`} />
        ))}
      </div>
      <div className="viz-keys">
        {use.map((p, i) => (
          <span key={i} className="viz-key">
            <i className={`viz-dot t${i}`} />{p.name}
            <b>{p.text ?? `${round(p.value)}%`}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

/* 전체 중 일부가 차지하는 비율. 세포 수처럼 「몇 개 중 몇 개」에 쓴다. */
export function PartBar({ label, total, parts, unit = "개" }) {
  if (!isNum(total) || total <= 0) return null;
  const use = (parts ?? []).filter((p) => isNum(p.value));
  if (use.length === 0) return null;

  return (
    <div className="viz">
      {label && <div className="viz-h">{label}<b>{fmt(total)}{unit}</b></div>}
      {use.map((p, i) => (
        <div className="viz-row" key={i}>
          <span className="viz-name">{p.name}</span>
          <span className="viz-track">
            <i className={`viz-fill t${i}`}
               style={{ width: `${Math.min(100, (p.value / total) * 100)}%` }} />
          </span>
          <span className="viz-val">
            {fmt(p.value)}<em>{pctOf(p.value, total)}</em>
          </span>
        </div>
      ))}
    </div>
  );
}

/* 0~100% 한 값. MRI 치밀도가 이 모양이다. */
export function Gauge({ label, percent, note }) {
  if (!isNum(percent)) return null;
  const w = Math.max(0, Math.min(100, percent));
  return (
    <div className="viz">
      {label && <div className="viz-h">{label}<b>{round(percent)}%</b></div>}
      <div className="viz-track lg"><i className="viz-fill t0" style={{ width: `${w}%` }} /></div>
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}

/* 값 여러 개를 한 축에 점으로 찍는다 — 평균을 내지 않기 위한 그림.
   병리 크롭별 AI 계측값이 이것이다(같은 슬라이드도 자른 자리에 따라
   흔들린다). ⚠ "sTIL"이라 부르지 않는다 — 병리의가 입력하는 sTIL 과
   척도가 다르다(09-28, dept/PathologyAi.jsx 머리말 참고). */
export function StripPlot({ label, points, unit = "%", note }) {
  const use = (points ?? []).filter((p) => isNum(p.value));
  if (use.length < 2) return null;          /* 한 점이면 분포가 아니다 */

  const vals = use.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 1;
  const at = (v) => ((v - lo) / span) * 100;

  return (
    <div className="viz">
      {label && <div className="viz-h">{label}<b>{round(lo)}–{round(hi)}{unit}</b></div>}
      <div className="viz-strip">
        {hi > lo && (
          <i className="viz-range" style={{ left: "0%", width: "100%" }} />
        )}
        {use.map((p, i) => (
          <span key={i} className="viz-pt" style={{ left: `${at(p.value)}%` }}
                title={`${p.name}: ${p.value}${unit}`}>
            <em>{p.name}</em>
          </span>
        ))}
      </div>
      <div className="viz-ends"><span>{round(lo)}{unit}</span><span>{round(hi)}{unit}</span></div>
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}

/* 인접 등급 확률. 「2인지 3인지」의 애매함을 막대로 본다. */
export function GradeBars({ label, values, note }) {
  const use = (values ?? []).filter((v) => isNum(v.p));
  if (use.length === 0) return null;
  const max = Math.max(...use.map((v) => v.p)) || 1;
  return (
    <div className="viz">
      {label && <div className="viz-h">{label}</div>}
      {use.map((v, i) => (
        <div className="viz-row" key={i}>
          <span className="viz-name">{v.name}</span>
          <span className="viz-track">
            <i className={`viz-fill ${v.on ? "on" : "t1"}`}
               style={{ width: `${(v.p / max) * 100}%` }} />
          </span>
          <span className="viz-val">{pct(v.p)}</span>
        </div>
      ))}
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}

function round(n, d = 1) {
  if (!isNum(n)) return "—";
  return Number.isInteger(n) ? String(n) : n.toFixed(d);
}
function fmt(n) {
  return isNum(n) ? n.toLocaleString("ko-KR") : "—";
}
function pct(p) {
  return isNum(p) ? `${(p * 100).toFixed(0)}%` : "—";
}
function pctOf(v, total) {
  if (!isNum(v) || !isNum(total) || total <= 0) return "";
  return ` ${((v / total) * 100).toFixed(0)}%`;
}
