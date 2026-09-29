import { useId } from "react";
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

/* ── 09-28 추가: 그래프 셋 ─────────────────────────────────────────
 * 막대로 안 되는 모양만 SVG 로 그린다. 색은 화면 토큰(var(--cyan) 등)을 쓴다. */

/* 값 막대 — 이름 · 막대 · 값 글자. max 기준으로 길이를 잡는다.
   맘모 병변별 점수 · 서술어 확신도, MRI 병변 부피가 이 모양이다. */
export function Bars({ label, items, max, note, fmtVal = (v) => round(v, 2) }) {
  const use = (items ?? []).filter((v) => isNum(v.value));
  if (use.length === 0) return null;
  const top = max ?? (Math.max(...use.map((v) => v.value)) || 1);
  return (
    <div className="viz viz-lg">
      {label && <div className="viz-h">{label}</div>}
      {use.map((v, i) => (
        <div className="viz-row" key={i}>
          <span className="viz-name" title={v.name}>{v.name}</span>
          <span className="viz-track">
            <i className={`viz-fill ${v.on ? "on" : "t0"}`}
               style={{ width: `${Math.max(2, Math.min(100, (v.value / top) * 100))}%` }} />
          </span>
          <span className="viz-val">{v.text ?? fmtVal(v.value)}</span>
        </div>
      ))}
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}

/* 방사형 — 축마다 [lo, hi] 범위를 받아 0~1 로 편다. 초음파 형태 지표.
   축 값이 없으면 그 축은 중심(0)에 둔다 — 없는 값을 지어내지 않고, 글자로 「—」 */
export function Radar({ label, axes, note }) {
  const use = (axes ?? []);
  const id = useId().replace(/:/g, "");
  if (use.filter((a) => isNum(a.value)).length < 3) return null;
  /* ⚠ 09-29 글자가 var(--ink)(짙은 색) 고정이라 판독 화면의 어두운 칸(.vside)에서
     묻혔고, 아래 축 글자는 viewBox 밖으로 잘렸다. 색은 --viz-* 로 받아 칸마다
     바꾸고(hospital.css), 둘레 글자 자리를 넉넉히 둔다 */
  const N = use.length, R = 84, C = 150;
  const pt = (i, f) => {
    const t = -Math.PI / 2 + (2 * Math.PI * i) / N;
    return [C + Math.cos(t) * R * f, C + Math.sin(t) * R * f];
  };
  const norm = (a) => isNum(a.value) ? Math.max(0, Math.min(1, (a.value - a.lo) / (a.hi - a.lo))) : 0;
  const ring = (f) => use.map((_, i) => pt(i, f).join(",")).join(" ");
  const poly = use.map((a, i) => pt(i, norm(a)).join(",")).join(" ");
  return (
    <div className="viz viz-lg viz-radar">
      {label && <div className="viz-h">{label}</div>}
      <svg className="viz-svg" viewBox="0 0 300 300" role="img" aria-label={label}>
        <defs>
          <radialGradient id={`rg${id}`} cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="var(--cyan)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--cyan)" stopOpacity="0.12" />
          </radialGradient>
        </defs>
        {/* 바깥 판 — 가장 바깥 고리만 옅게 채워 영역을 잡는다 */}
        <polygon points={ring(1)} className="rd-plate" />
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <polygon key={f} points={ring(f)} className={f === 1 ? "rd-ring out" : "rd-ring"} />
        ))}
        {use.map((_, i) => (
          <line key={i} x1={C} y1={C} x2={pt(i, 1)[0]} y2={pt(i, 1)[1]} className="rd-axis" />
        ))}
        <polygon points={poly} fill={`url(#rg${id})`} className="rd-shape" />
        {use.map((a, i) => {
          const [x, y] = pt(i, norm(a));
          return <circle key={a.name} cx={x} cy={y} r="3.2" className="rd-dot" />;
        })}
        {use.map((a, i) => {
          const [x, y] = pt(i, 1.3);
          const anchor = Math.abs(x - C) < 4 ? "middle" : x > C ? "start" : "end";
          const top = y < C - 4;
          return (
            <text key={a.name} x={x} y={top ? y - 8 : y} textAnchor={anchor} className="rd-k">
              {a.name}
              <tspan x={x} dy="15" className="rd-v">{isNum(a.value) ? round(a.value, 2) : "—"}</tspan>
            </text>
          );
        })}
      </svg>
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}

/* 유방 위치 도식 — 사분면 글자와 유두 거리로 병변을 점으로 찍는다.
   quadrant 는 「상부(superior)-외측(lateral)」처럼 온다. 좌우(laterality)가
   없어 한쪽 유방만 그리고, 내측·외측을 글자로 적는다.
   ⚠ 거리는 병변끼리의 상대 위치다(가장 먼 병변을 가장자리로). 실측 도면이 아니다. */
export function BreastMap({ label, lesions, note, pick, onPick }) {
  const use = (lesions ?? []).map((l, i) => ({ ...l, i })).filter((l) => l.quadrant);
  if (use.length === 0) return null;
  const maxD = Math.max(...use.map((l) => (isNum(l.dist) ? l.dist : 0)), 1);
  const C = 130, R = 100;
  const pos = (l, k) => {
    const q = String(l.quadrant);
    const up = /상부|superior|upper|^U[OI]Q/i.test(q), down = /하부|inferior|lower|^L[OI]Q/i.test(q);
    const med = /내측|medial|inner|^[UL]IQ/i.test(q), lat = /외측|lateral|outer|^[UL]OQ/i.test(q);
    const dx = med ? -1 : lat ? 1 : 0, dy = up ? -1 : down ? 1 : 0;
    const len = Math.hypot(dx, dy) || 1;
    const f = isNum(l.dist) ? 0.25 + 0.7 * (l.dist / maxD) : 0.55;
    const jitter = (k % 3) * 6;                    /* 같은 칸 병변이 겹치지 않게 */
    return [C + (dx / len) * R * f + jitter, C + (dy / len) * R * f + jitter];
  };
  return (
    <div className="viz viz-lg">
      {label && <div className="viz-h">{label}</div>}
      <svg className="viz-svg" viewBox="0 0 260 260" role="img" aria-label={label}>
        <circle cx={C} cy={C} r={R} fill="var(--line-2)" fillOpacity="0.35" stroke="var(--faint)" />
        <line x1={C - R} y1={C} x2={C + R} y2={C} stroke="var(--faint)" strokeDasharray="4 4" />
        <line x1={C} y1={C - R} x2={C} y2={C + R} stroke="var(--faint)" strokeDasharray="4 4" />
        <circle cx={C} cy={C} r="6" fill="var(--warm)" />
        <text x={C} y={C + 20} textAnchor="middle" fontSize="11" fill="var(--warm)">유두</text>
        <text x={C} y={18} textAnchor="middle" fontSize="12" fill="var(--warm)">상부</text>
        <text x={C} y={252} textAnchor="middle" fontSize="12" fill="var(--warm)">하부</text>
        <text x={12} y={C + 4} fontSize="12" fill="var(--warm)">내측</text>
        <text x={248} y={C + 4} textAnchor="end" fontSize="12" fill="var(--warm)">외측</text>
        {use.map((l, k) => {
          const [x, y] = pos(l, k);
          const on = pick != null && pick === l.i;
          return (
            <g key={l.i} style={{ cursor: onPick ? "pointer" : "default" }}
               onClick={() => onPick?.(on ? null : l.i)}>
              <circle cx={x} cy={y} r={on ? 13 : 10} fill={on ? "var(--ink)" : "var(--cyan)"} />
              <text x={x} y={y + 4} textAnchor="middle" fontSize="11" fill="#fff">{l.i + 1}</text>
            </g>
          );
        })}
      </svg>
      {note && <div className="viz-note">{note}</div>}
    </div>
  );
}
