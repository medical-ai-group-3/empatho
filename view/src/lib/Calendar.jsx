/* 달력 — 한 달치를 그린다.
 *
 * 두 곳에서 쓴다.
 *   홈    onPick 없이 → **보기만 한다**
 *   예약  onPick 주고  → 표시된 날을 고를 수 있다
 *
 * 고르는 곳을 한 군데로 몰아 둔 이유가 있다. 홈에서도 고를 수 있으면
 * 어느 쪽이 «진짜» 신청인지 헷갈린다. 그래서 부품은 하나지만 홈에서는
 * 손잡이를 안 준다.
 *
 * 서버가 주는 모양(GET /api/v1/home 의 calendar):
 *   { month:"2026-09",
 *     marks:[ { date:"2026-09-15", kind:"confirmed", label:"유방초음파 14:00" } ] }
 *
 * kind 다섯만 안다. 모르는 kind 가 오면 점을 찍지 않고 넘긴다 — 화면이
 * 깨지는 것보다 낫다. 새 kind 가 생기면 여기 KIND 에 한 줄 더한다.
 */

const WD = ["일", "월", "화", "수", "목", "금", "토"];

// 순서가 곧 범례 순서다
const KIND = {
  open:      "예약 가능",
  done:      "검사 완료",
  confirmed: "예약 확정",
  requested: "방문 신청 · 확인 중",
  followup:  "추적 예정",
};

/* 오늘을 「YYYY-MM-DD」로. new Date().toISOString() 은 UTC 라
 * 한국에서 밤 9시가 넘으면 하루 앞선 날짜가 나온다. 지역 시각으로 만든다. */
function todayKey() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export default function Calendar({
  month, marks = [], footer, onPick, selected, onPrev, onNext,
}) {
  if (!month) return null;

  const [y, m] = month.split("-").map(Number);
  const lead = new Date(y, m - 1, 1).getDay();  // 1일이 무슨 요일인가
  const days = new Date(y, m, 0).getDate();     // 그 달의 마지막 날

  // 날짜 → 표시. 같은 날에 둘이 오면 뒤엣것이 이긴다(서버가 하나만 준다)
  const byDay = new Map();
  for (const k of marks) {
    if (typeof k?.date !== "string" || !k.date.startsWith(month)) continue;
    byDay.set(Number(k.date.slice(8, 10)), k);
  }

  const cells = [];
  for (let i = 0; i < lead; i++) cells.push(null);
  for (let d = 1; d <= days; d++) cells.push(d);
  while (cells.length % 7) cells.push(null);

  const today = todayKey();
  const p = (n) => String(n).padStart(2, "0");

  // 범례는 이 달에 실제로 있는 것만 낸다
  const shown = Object.keys(KIND).filter((k) =>
    [...byDay.values()].some((v) => v.kind === k));

  return (
    <div className="cal">
      {/* 달 넘기기는 예약에서만 준다(onPrev · onNext). 넘길 달이 없으면
          null 이 와서 단추가 눌리지 않는다 */}
      <div className="mhead">
        <span>{y}년 {m}월</span>
        {(onPrev !== undefined || onNext !== undefined) && (
          <span className="mnav">
            <button type="button" aria-label="이전 달"
                    disabled={!onPrev} onClick={onPrev || undefined}>‹</button>
            <button type="button" aria-label="다음 달"
                    disabled={!onNext} onClick={onNext || undefined}>›</button>
          </span>
        )}
      </div>

      <div className="wd" aria-hidden="true">
        {WD.map((w) => <span key={w}>{w}</span>)}
      </div>

      <div className="grid">
        {cells.map((d, i) => {
          if (d === null) return <div key={`p${i}`} className="d pad" />;

          const key = `${y}-${p(m)}-${p(d)}`;
          const mk = byDay.get(d);
          const known = mk && KIND[mk.kind];
          // 고를 수 있는 것은 **표시가 있는 날**뿐이다. 빈 날은 병원이
          // 자리를 안 열어 둔 날이라 눌러도 될 일이 없다.
          const pick = onPick && known;

          const cls = [
            "d",
            i % 7 === 0 ? "sun" : "",
            key === today ? "today" : "",
            known ? "marked" : "",
            selected === key ? "sel" : "",
          ].filter(Boolean).join(" ");

          // 점만으로는 뜻이 안 전해진다. 읽어 주는 기계를 위해 글로도 남긴다
          const say = known
            ? `${m}월 ${d}일, ${mk.label || KIND[mk.kind]}`
            : `${m}월 ${d}일`;

          const inner = (
            <>
              <span>{d}</span>
              <i className={`dot ${known ? mk.kind : "none"}`} />
            </>
          );

          return pick ? (
            <button
              key={key}
              type="button"
              className={cls}
              aria-label={say}
              aria-pressed={selected === key}
              onClick={() => onPick(key)}
            >
              {inner}
            </button>
          ) : (
            <div key={key} className={cls} aria-label={say}>{inner}</div>
          );
        })}
      </div>

      {shown.length > 0 && (
        <div className="legend">
          {shown.map((k) => (
            <span key={k}><i className={`dot ${k}`} />{KIND[k]}</span>
          ))}
        </div>
      )}

      {footer && <div className="foot">{footer}</div>}
    </div>
  );
}
