import { useMemo, useState } from "react";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, Locked, useCan } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import { DESK } from "../../../nav";
import * as H from "../../home";

/* 간호과 · 추적 관리 — `docs/mockup/NursingFollowups.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **이 시스템의 임상적 핵심이다.** 판독이 BI-RADS 3(양성 추정)으로
 * 확정되면 바로 조직검사를 하지 않고 **6 · 12 · 24개월 추적**으로 보낸다.
 * 그 회차를 놓치지 않는 것이 이 화면이 하는 일 전부다.
 *
 *   추적 관리                              [+ 추적 회차 만들기]
 *   [오늘 2] [지난 기한 1] [이번 주 3] [전체 8]     검색 [      ]
 *   ─────────────────────────────────────────────────────────────
 *   이름  생년월일  환자번호  회차  예정일  기한  최근 콜  [콜 기록]
 *
 * ⚠ **경과 시간을 안 쓴다.** 목업 기한 칸의 「하루 지남」은 경과다.
 *   예정일을 적고 「지남 / 오늘 / 이번 주 / 예정」 넷으로만 가른다.
 * ⚠ **색으로 기한을 말하지 않는다.** 지난 것은 soot 채움으로 세운다.
 */
export default function Followups({ cfg }) {
  if (!can(DESK)) {
    return (
      <Page crumb={[cfg.name, "추적 관리"]} title="추적 관리">
        <Locked what="추적 관리" need="nursing.followup.view" />
      </Page>
    );
  }
  return <Inner cfg={cfg} />;
}

/* 기한 칸 — 「며칠 지났나」가 아니라 「어느 칸에 드나」다 */
const BUCKET = { over: "지남", today: "오늘", week: "이번 주" };
const CHIPS = [
  { key: "today", label: "오늘" },
  { key: "over", label: "지난 기한" },
  { key: "week", label: "이번 주" },
  { key: "all", label: "전체" },
];

function Inner({ cfg }) {
  const list = useApi(() => cfg.api.followups(), []);
  /* 기본 칸은 **일이 있는 곳**이다. 「오늘」로 고정해 두면 오늘 콜이
     없는 날 화면이 빈 채로 열려 고장처럼 보인다 — 지난 기한이 있으면
     거기가 먼저다(놓친 회차가 제일 급하다) */
  const [tab, setTab] = useState(null);
  const [q, setQ] = useState("");
  const [call, setCall] = useState(null);
  const [making, setMaking] = useState(false);

  const rows = H.rows(list.data);
  const again = () => list.reload(true);

  /* 후보는 아직 회차가 없는 사람이다 — 표에 섞으면 「예정일 없음」이
     줄줄이 뜬다. 회차 만들기 쪽에서만 쓴다 */
  const live = useMemo(() => rows.filter((r) => r.status !== "candidate"), [rows]);
  const cands = useMemo(() => rows.filter((r) => r.status === "candidate"), [rows]);

  const count = useMemo(() => ({
    today: live.filter((r) => H.dueBucket(r.due_at) === "today").length,
    over: live.filter((r) => H.dueBucket(r.due_at) === "over").length,
    week: live.filter((r) => H.dueBucket(r.due_at) === "week").length,
    all: live.length,
  }), [live]);

  /* 안 고른 상태면 일이 있는 첫 칸으로 — 지난 기한 → 오늘 → 이번 주 */
  const here = tab ?? (count.over > 0 ? "over"
    : count.today > 0 ? "today"
      : count.week > 0 ? "week" : "all");

  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return live
      .filter((r) => here === "all" || H.dueBucket(r.due_at) === here)
      .filter((r) => !k
        || `${H.nameOf(r)} ${r.patient_id ?? ""}`.toLowerCase().includes(k));
  }, [live, here, q]);

  return (
    <Page crumb={[cfg.name, "추적 관리"]} title="추적 관리"
          right={(
            <Btn kind="fill" onClick={() => setMaking(true)} disabled={cands.length === 0}>
              + 추적 회차 만들기
            </Btn>
          )}>
      <div className="fup-top">
        {CHIPS.map((c) => (
          <button type="button" key={c.key}
                  className={`fup-chip${c.key === here ? " on" : ""}`}
                  aria-pressed={c.key === here} onClick={() => setTab(c.key)}>
            {c.label} <i>{count[c.key]}</i>
          </button>
        ))}
        <span className="home-fill" />
        <label className="fup-find">
          <span>검색</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="이름 · 환자번호" />
        </label>
      </div>

      <Body loading={list.loading && !list.data} error={list.error}
            onRetry={list.reload}
            empty={shown.length === 0 && (
              <Empty title={here === "all"
                ? "추적 중인 환자가 없습니다"
                : `${CHIPS.find((c) => c.key === here).label} 칸에 든 환자가 없습니다`} />
            )}>
        <div className="tbl-wrap fup-tbl">
          <table className="tbl">
            <thead>
              <tr>
                <th>이름</th><th>생년월일</th><th>환자번호</th><th>회차</th>
                <th>예정일</th><th>기한</th><th>최근 콜</th><th />
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => <Row key={r.id} r={r} onCall={() => setCall(r)} />)}
            </tbody>
          </table>
        </div>
      </Body>

      {call && (
        <CallModal cfg={cfg} f={call} onClose={() => setCall(null)}
                   onDone={() => { setCall(null); again(); }} />
      )}
      {making && (
        <MakeModal cfg={cfg} cands={cands} onClose={() => setMaking(false)}
                   onDone={() => { setMaking(false); again(); }} />
      )}
    </Page>
  );
}

/* 한 줄.
   ⚠ **나이·성별을 못 적는다.** 추적 응답에 생년월일과 전화번호는 있는데
     성별이 없다. 목업의 「44 · 여」 자리에 **생년월일을 그대로** 둔다 —
     나이만 계산해 넣으면 성별 칸이 빈 채로 남아 더 이상해 보인다(8장).
   ⚠ **몇 개월 추적인지 못 적는다.** 목업은 「6개월 · 1회차」인데 응답에
     간격이 없다(`round_no` 뿐이다). 간격은 `due_at` 으로만 표현된다 —
     회차 만들 때 +6 · +12 · +24 단추가 그 날짜를 잡는다. */
function Row({ r, onCall }) {
  const bucket = H.dueBucket(r.due_at);
  const done = r.status === "resolved";
  return (
    <tr className={done ? "off" : ""}>
      <td><b>{H.nameOf(r)}</b></td>
      <td className="num">{r.birth_date ?? "—"}</td>
      <td className="num">{r.patient_id ?? "—"}</td>
      <td>{r.round_no != null ? `${r.round_no}회차` : "—"}</td>
      <td className="num">{r.due_at ?? "—"}</td>
      <td>
        {bucket
          ? <span className={`fup-due${bucket === "over" ? " k1" : ""}`}>{BUCKET[bucket]}</span>
          : <span className="hcard-k">예정</span>}
      </td>
      <td>
        {r.call_result
          ? <Chip>{r.call_result}</Chip>
          : <span className="hcard-k">미연락</span>}
        {r.call_at && <span className="hcard-k"> {r.call_at}</span>}
      </td>
      <td className="rowb">
        {done
          ? <span className="hcard-k">종결</span>
          : <Btn onClick={onCall}>콜 기록</Btn>}
      </td>
    </tr>
  );
}

/* ── 콜 기록 — `docs/mockup/NursingCallModal.html` ──────────────
 * ⚠ **「연결」은 이 회차를 끝낸다.** 되돌릴 수 없어서 고르는 것과
 *   남기는 것을 두 걸음으로 나눈다(9장).
 */
const RESULTS = ["연결", "부재", "거부"];

function CallModal({ cfg, f, onClose, onDone }) {
  const [pick, setPick] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const may = useCan("nursing.followup.call");

  async function save() {
    if (!pick) return;
    setBusy(true);
    setErr(null);
    try {
      await cfg.api.logCall(f.id, {
        call_result: pick, note,
        status: pick === "연결" ? "resolved" : "open",
      });
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <b>안내 콜 기록</b>
          <span className="home-fill" />
          <button type="button" aria-label="닫기" onClick={onClose}>×</button>
        </header>

        <div className="modal-body">
          <div className="fup-who">
            <b>{H.nameOf(f)}</b>
            <span className="hcard-k">
              {[f.patient_id, f.round_no != null && `${f.round_no}회차`,
                f.due_at && `예정일 ${f.due_at}`].filter(Boolean).join(" · ")}
            </span>
            <span className="home-fill" />
            {f.phone && <Chip>{f.phone}</Chip>}
          </div>

          <div className="rev-f">
            <span>콜 결과</span>
            <div className="work-seg narrow" role="radiogroup" aria-label="콜 결과">
              {RESULTS.map((v) => (
                <button type="button" key={v} role="radio" aria-checked={v === pick}
                        className={`work-opt${v === pick ? " on" : ""}`}
                        disabled={!may.ok} onClick={() => setPick(v)}>{v}</button>
              ))}
            </div>
          </div>

          <label className="rev-f">
            <span>메모</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)}
                      rows={3} disabled={!may.ok} />
          </label>

          {err && <p className="note err">{err}</p>}
        </div>

        <footer className="modal-foot">
          {/* ⚠ 9장이 남기라고 한 말 — 되돌릴 수 없는 갈림길이다 */}
          <span className="hcard-k">
            「연결」로 남기면 이 회차가 끝납니다. 부재 · 거부는 다시 뜹니다.
          </span>
          <span className="home-fill" />
          <Btn onClick={onClose} disabled={busy}>그만</Btn>
          <Btn kind="fill" onClick={save} {...may.attrs}
               disabled={!pick || busy || !may.ok}>
            {busy ? "남기는 중…" : "남기기"}
          </Btn>
        </footer>
      </div>
    </div>
  );
}

/* ── 추적 회차 만들기 ──────────────────────────────────────────
 * **6 · 12 · 24개월이 여기서 정해진다.** 서버에 「간격」 칸이 없고
 * `due_at` 하나만 받는다 — 그래서 단추가 날짜를 계산해 넣는다.
 * 손으로 고칠 수 있게 날짜칸은 그대로 둔다.
 */
const MONTHS = [6, 12, 24];

function plus(months) {
  const d = new Date();
  d.setMonth(d.getMonth() + months);
  return H.iso(d);
}

function MakeModal({ cfg, cands, onClose, onDone }) {
  const [who, setWho] = useState(cands[0]?.patient_id ?? null);
  const [round, setRound] = useState(1);
  const [due, setDue] = useState(plus(6));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const may = useCan("nursing.followup.create");

  async function make() {
    if (!who) return;
    setBusy(true);
    setErr(null);
    try {
      await cfg.api.createFollowup({ patient_id: who, round_no: round, due_at: due });
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <b>추적 회차 만들기</b>
          <span className="home-fill" />
          <button type="button" aria-label="닫기" onClick={onClose}>×</button>
        </header>

        <div className="modal-body">
          <label className="rev-f">
            <span>환자</span>
            <select value={who ?? ""} onChange={(e) => setWho(e.target.value)}
                    disabled={!may.ok}>
              {cands.map((c) => (
                <option key={c.patient_id} value={c.patient_id}>
                  {H.nameOf(c)} · {c.patient_id}
                </option>
              ))}
            </select>
          </label>

          <div className="rev-dec-b">
            <label className="rev-f narrow">
              <span>회차</span>
              <input type="number" min={1} value={round}
                     onChange={(e) => setRound(Number(e.target.value))}
                     disabled={!may.ok} />
            </label>
            <label className="rev-f">
              <span>추적 예정일</span>
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
                     disabled={!may.ok} />
            </label>
          </div>

          {/* 6 · 12 · 24개월 — 서버에 간격 칸이 없어서 날짜로 넣는다 */}
          <div className="work-seg narrow" role="group" aria-label="추적 간격">
            {MONTHS.map((m) => (
              <button type="button" key={m} className="work-opt"
                      disabled={!may.ok} onClick={() => setDue(plus(m))}>
                +{m}개월
              </button>
            ))}
          </div>

          {err && <p className="note err">{err}</p>}
        </div>

        <footer className="modal-foot">
          <span className="home-fill" />
          <Btn onClick={onClose} disabled={busy}>그만</Btn>
          <Btn kind="fill" onClick={make} {...may.attrs}
               disabled={!who || !due || busy || !may.ok}>
            {busy ? "만드는 중…" : "만들기"}
          </Btn>
        </footer>
      </div>
    </div>
  );
}

Followups.need = DESK;
