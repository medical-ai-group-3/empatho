import { useMemo, useState } from "react";
import { reception as api } from "../../api";
import { Card } from "../../lib/Page";
import { Body } from "../../lib/Body";
import { Chip, Warn } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { MODALITY, label, modality as asModality } from "../../codes";

/* 예약 캘린더 — 원무 1장 아래에 붙는다
 * ════════════════════════════════════════════════════════════════
 *
 * **조회 전용이다.** 예약을 만들지도 고치지도 않는다. 날짜를 더블클릭하면
 * 예약 화면(3장)으로 넘어가면서 그 날짜가 채워진다.
 *
 * ⚠ **정원이나 「꽉 참」을 표시하지 않는다.** 검사마다 걸리는 시간이 달라서
 *   («9시 유방촬영 15분»과 «10시 MRI 40분»이 한 칸에 똑같이 하나로 센다)
 *   숫자로 자리를 세면 틀린 답이 나온다. 원무가 목록을 보고 판단한다.
 *
 * ── 왜 날짜를 문자열에서 잘라 쓰나 ──────────────────────────────
 * scheduled_at 은 "2026-09-13T09:30:00+09:00" 로 온다. 서버가 KST 로
 * 직렬화하기 때문이다 (settings.py 의 TIME_ZONE="Asia/Seoul" · USE_TZ=True →
 * DRF 가 기본 시간대로 맞춰 내보낸다).
 *
 * 이것을 new Date() 로 돌리면 **보는 사람의 시간대로 다시 옮겨진다.** 병원
 * 밖에서 열거나 노트북 시계가 다른 지역이면 9월 13일 예약이 12일 칸에
 * 들어간다. 병원이 말하는 날짜는 +09:00 기준의 그 날짜 하나뿐이므로
 * 앞 열 글자를 그대로 쓴다.
 */

/* "2026-09-13T09:30:00+09:00" → "2026-09-13" · "09:30" */
const dayOf  = (s) => (s ? s.slice(0, 10) : "");
const timeOf = (s) => (s ? s.slice(11, 16) : "");

const pad = (n) => String(n).padStart(2, "0");
const key = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;

const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

/* 이름이 없으면 번호로 떨어진다. 서버가 patient 를 숫자 id 로만 주기
   때문이다 — patient_name 은 다희님께 요청해 둔 칸이라, 오기 시작하면
   여기가 저절로 이름으로 바뀐다 */
const who = (r) => r.patient_name || `#${r.patient}`;

export default function Calendar({ onOpenDate }) {
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() + 1 });
  /* 고른 날 — **강조만 한다.** 한 번 클릭으로는 아무 데도 안 간다.
     조회 화면이라 클릭이 화면을 바꾸면 훑어보다 튕겨 나간다 */
  const [pickDay, setPickDay] = useState(null);

  const last = new Date(ym.y, ym.m, 0).getDate();
  const from = key(ym.y, ym.m, 1);
  const to   = key(ym.y, ym.m, last);

  const list = useApi(() => api.schedule(from, to), [from, to]);

  /* 날짜별로 묶는다. 서버가 ordering=scheduled_at 으로 정렬해 주지만
     그 값을 못 믿을 이유가 없어도 한 번 더 시각순으로 세운다 —
     날짜가 같고 시각만 다른 줄이 뒤섞이면 달력에서 바로 보인다 */
  const byDay = useMemo(() => {
    const m = new Map();
    for (const r of list.data ?? []) {
      const d = dayOf(r.scheduled_at);
      if (!d) continue;                     // 아직 시각이 없는 신청은 달력에 없다
      if (!m.has(d)) m.set(d, []);
      m.get(d).push(r);
    }
    for (const rows of m.values()) {
      rows.sort((a, b) => timeOf(a.scheduled_at).localeCompare(timeOf(b.scheduled_at)));
    }
    return m;
  }, [list.data]);

  const total = list.data?.filter((r) => r.scheduled_at).length ?? 0;
  const move = (step) => {
    const d = new Date(ym.y, ym.m - 1 + step, 1);
    setYm({ y: d.getFullYear(), m: d.getMonth() + 1 });
    setPickDay(null);
  };
  const toToday = () => {
    const t = new Date();
    setYm({ y: t.getFullYear(), m: t.getMonth() + 1 });
    setPickDay(key(t.getFullYear(), t.getMonth() + 1, t.getDate()));
  };

  return (
    <Card
      title="예약 캘린더"
      right={
        <div className="cal-nav">
          <button className="cal-mv" onClick={() => move(-1)} aria-label="이전 달">‹</button>
          <b>{ym.y}.{pad(ym.m)}</b>
          <button className="cal-mv" onClick={() => move(1)} aria-label="다음 달">›</button>
          <button className="cal-today" onClick={toToday}>오늘</button>
        </div>
      }
    >
      <Body loading={list.loading} error={list.error} onRetry={list.reload}>
        {list.data && (
          <>
            <div className="cal">
              <Grid ym={ym} last={last} byDay={byDay} today={key(now.getFullYear(), now.getMonth() + 1, now.getDate())}
                    pickDay={pickDay} onPickDay={setPickDay} onOpenDate={onOpenDate} />
              <Tree ym={ym} byDay={byDay} total={total}
                    pickDay={pickDay} onPickDay={setPickDay} onOpenDate={onOpenDate} />
            </div>
            <p className="hint">
              날짜를 <b>더블클릭</b>하면 예약 화면으로 넘어갑니다. 여기서는 예약을 만들거나 고치지 않습니다.
            </p>
            {list.data.some((r) => !r.patient_name) && (
              <Warn>서버가 이름을 주지 않는 예약은 환자 번호로 표시합니다.</Warn>
            )}
          </>
        )}
      </Body>
    </Card>
  );
}

/* ── 달 격자 ──────────────────────────────────────────────────
   칸 안에 **몇 시에 누구인지**를 적는다. 점이나 숫자만 찍으면 결국
   칸마다 눌러 봐야 해서, 훑어보는 화면이 아니게 된다.

   다 들어가지 않으면 「+2」로 접는다. 나머지는 오른쪽 목록에 전부 있다 */
const SHOW = 3;

function Grid({ ym, last, byDay, today, pickDay, onPickDay, onOpenDate }) {
  const lead = new Date(ym.y, ym.m - 1, 1).getDay();   // 1일이 무슨 요일인가
  const cells = [];

  for (let i = 0; i < lead; i++) cells.push(<div key={`_${i}`} className="cal-c out" />);

  for (let d = 1; d <= last; d++) {
    const k = key(ym.y, ym.m, d);
    const rows = byDay.get(k) ?? [];
    const cls = ["cal-c"];
    if (k === today) cls.push("today");
    if (k === pickDay) cls.push("on");
    if (rows.length) cls.push("has");

    cells.push(
      <div key={k} className={cls.join(" ")} tabIndex={0} role="button"
           aria-label={`${ym.m}월 ${d}일 예약 ${rows.length}건`}
           onClick={() => onPickDay(k)}
           onDoubleClick={() => onOpenDate(k)}
           /* 키보드는 Enter 로 연다. 더블클릭에 대응하는 «확정» 동작이
              키보드에는 없어서, 여기서는 Enter 가 그 자리다 */
           onKeyDown={(e) => {
             if (e.key === "Enter") onOpenDate(k);
             else if (e.key === " ") { e.preventDefault(); onPickDay(k); }
           }}>
        <i className="cal-d">{d}</i>
        <ul className="cal-in">
          {rows.slice(0, SHOW).map((r) => (
            <li key={r.exam_order_id}>
              <b>{timeOf(r.scheduled_at)}</b> <span>{who(r)}</span>
            </li>
          ))}
        </ul>
        {rows.length > SHOW && <span className="cal-more">+{rows.length - SHOW}</span>}
      </div>,
    );
  }

  return (
    <div className="cal-grid">
      <div className="cal-wk">
        {WEEK.map((w) => <span key={w}>{w}</span>)}
      </div>
      <div className="cal-body">{cells}</div>
    </div>
  );
}

/* ── 오른쪽 목록 ──────────────────────────────────────────────
     2026.09
      └ 13일
         └ 09:30 김서연
         └ 14:00 윤서현

   격자는 한 달을 한눈에 보는 자리고, 이쪽은 **빠짐없이 읽는 자리**다.
   칸에서 「+2」로 접힌 것도 여기에는 전부 있다.

   예약이 없는 날은 줄을 안 만든다 — 빈 날까지 늘어놓으면 서른 줄 중
   스물다섯이 빈 줄이 된다 */
function Tree({ ym, byDay, total, pickDay, onPickDay, onOpenDate }) {
  const days = [...byDay.keys()].sort();

  return (
    <div className="cal-tree">
      <div className="cal-tree-h">
        <b>{ym.y}.{pad(ym.m)}</b>
        <Chip>{total}건</Chip>
      </div>

      {days.length === 0 ? (
        <div className="slot"><b>이 달에는 예약이 없습니다</b></div>
      ) : (
        <ul className="tree">
          {days.map((k) => {
            const rows = byDay.get(k);
            const d = Number(k.slice(8, 10));
            return (
              <li key={k} className={k === pickDay ? "on" : undefined}>
                <button className="tree-d" onClick={() => onPickDay(k)}
                        onDoubleClick={() => onOpenDate(k)}>
                  {d}일 <i>{rows.length}</i>
                </button>
                <ul>
                  {rows.map((r) => (
                    <li key={r.exam_order_id} className="tree-r">
                      <b>{timeOf(r.scheduled_at)}</b>
                      <span>{who(r)}</span>
                      <em>{label(MODALITY, asModality(r.modality)) || "미정"}</em>
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/* 예약 단계에서는 비어 있을 수 있다 — 검사 종류는 유방외과가 정한다.
   원무가 예약만 잡아 둔 건은 modality 가 null 이라 「미정」이 맞다 */
