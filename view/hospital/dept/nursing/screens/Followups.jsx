import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Page, Card, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, Locked, useCan } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import { DESK, go } from "../../../nav";
import * as H from "../../home";

/* 간호과 · 추적 관리 — `docs/mockup/NursingFollowups.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **이 시스템의 임상적 핵심이다.** 판독이 BI-RADS 3(양성 추정)으로
 * 확정되면 바로 조직검사를 하지 않고 **6 · 12 · 24개월 추적**으로 보낸다.
 * 그 회차를 놓치지 않는 것이 이 화면이 하는 일 전부다.
 *
 *   [지난 기한][오늘][이번 주][전체][추적 대상(회차 없음)]   검색 [    ]
 *   ┌ 목록 ───────────────────────────────┬ 420 고른 회차 ─────────┐
 *   │ 이름 생년월일 환자번호 전화 회차 …   │ 전화(눌러 복사) · 콜 기록  │
 *   │                                    │ 연결 뒤 → 검사 예약 잡기   │
 *   │                                    │        · 다음 회차 · 결과  │
 *   └────────────────────────────────────┴───────────────────────────┘
 *
 * 09-28 팝업만 있던 것을 **목록 + 오른쪽 칸**으로 바꿨다 — 전화를 걸면서 그
 * 사람의 번호 · 지난 콜을 보고, 연결되면 그 자리에서 예약까지 잇는다.
 *
 * ⚠ **경과 시간을 안 쓴다.** 예정일을 적고 「지남 / 오늘 / 이번 주 / 예정」
 *   넷으로만 가른다.
 * ⚠ **색으로 기한을 말하지 않는다.** 지난 것은 soot 채움으로 세운다.
 * ⚠ 09-28 「환자번호」 칸이 내부 번호(patient FK)를 적고 있었다 — 서버가 이제
 *   patient_number · phone · birth_date 를 실어 준다. 없으면 「—」.
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
const BUCKET = { over: "기한 지남", today: "오늘", week: "이번 주" };
const CHIPS = [
  { key: "over", label: "기한 지남" },
  { key: "today", label: "오늘" },
  { key: "week", label: "이번 주" },
  { key: "all", label: "전체" },
  { key: "cand", label: "추적 대상 (회차 없음)" },
];
const ROUND = { stable: "변화 없음", changed: "변화 있음", no_show: "미내원" };

const pidOf = (r) => r.patient ?? r.patient_id;
/* 줄 열쇠 — 후보는 followup_id 가 없다(null). 환자로 가른다 */
const keyOf = (r) => (r.followup_id != null ? String(r.followup_id) : `c-${pidOf(r)}`);

function Inner({ cfg }) {
  const [params] = useSearchParams();
  const list = useApi(() => cfg.api.followups(), [], { live: true });
  /* 홈 「추적 콜」 줄은 ?followup= 을, 환자 목록 「추적」 탭은 ?patient= 를
     달고 온다 — 그 회차를 오른쪽에 편 채로 연다 */
  const [pick, setPick] = useState(() => params.get("followup") || null);
  const askedPatient = params.get("patient");
  const [tab, setTab] = useState(() => (params.get("followup") || askedPatient ? "all" : null));
  const [q, setQ] = useState("");
  /* 보는 중에 다른 회차 · 사람 주소로 오면 한 번 따라간다(화면이 다시 서지 않는다) */
  const askKey = `${params.get("followup") ?? ""}|${askedPatient ?? ""}`;
  const [seenAsk, setSeenAsk] = useState(askKey);
  if (askKey !== seenAsk) {
    setSeenAsk(askKey);
    setPick(params.get("followup") || null);
    setTab("all");
  }

  const rows = H.rows(list.data);
  const again = () => list.reload(true);

  const live = useMemo(() => rows.filter((r) => r.status !== "candidate"), [rows]);
  const cands = useMemo(() => rows.filter((r) => r.status === "candidate"), [rows]);
  /* ⚠ 기한 칸은 **아직 걸 회차만** 센다. 서버가 끝난 회차도 같이 준다.
     「전체」는 끝난 것까지 보여 준다(줄은 흐리게) */
  const open = useMemo(() => live.filter(H.openFollowup), [live]);
  const count = useMemo(() => ({
    over: open.filter((r) => H.dueBucket(r.due_at) === "over").length,
    today: open.filter((r) => H.dueBucket(r.due_at) === "today").length,
    week: open.filter((r) => H.dueBucket(r.due_at) === "week").length,
    all: live.length,
    cand: cands.length,
  }), [live, open, cands]);

  /* 안 고른 상태면 일이 있는 첫 칸으로 — 지난 기한 → 오늘 → 이번 주 */
  const here = tab ?? (count.over > 0 ? "over"
    : count.today > 0 ? "today"
      : count.week > 0 ? "week" : "all");

  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    const base = here === "cand" ? cands : here === "all" ? live
      : open.filter((r) => H.dueBucket(r.due_at) === here);
    return base.filter((r) => !k || `${H.nameOf(r)} ${r.patient_number ?? ""} ${r.phone ?? ""}`
      .toLowerCase().includes(k));
  }, [live, open, cands, here, q]);

  /* ?patient= 로 왔으면 그 사람의 열린 회차(없으면 아무 회차 · 후보)를 고른다 */
  const byPatient = askedPatient
    ? (open.find((r) => String(pidOf(r)) === askedPatient)
      ?? rows.find((r) => String(pidOf(r)) === askedPatient)) : null;
  /* 09-28 아무도 안 골랐으면 **이 칸의 첫 사람**을 편다 — 오른쪽이 「고르세요」
     빈 상자로 서 있으면 창구가 매번 한 번 더 눌러야 했다(접수 화면과 같다) */
  const chosenKey = pick ?? (byPatient ? keyOf(byPatient) : shown[0] ? keyOf(shown[0]) : null);
  const chosen = rows.find((r) => keyOf(r) === String(chosenKey)) ?? null;

  return (
    <Page crumb={[cfg.name, "추적 관리"]} title="추적 관리"
          right={(
            <Btn kind="fill" onClick={() => setTab("cand")} disabled={cands.length === 0}>
              + 추적 회차 만들기
            </Btn>
          )}>
      {/* 09-28(최종) 위 알약 줄과 표 밑 「칸별 수」 상자 여섯이 **같은 수를 두 번**
          보였다. 수 상자를 맨 위 한 줄(폭 전체)로 올려 그것이 곧 거르개가 되게
          하고, 표 밑에는 다가오는 회차만 남긴다 */}
      <div className="fup-top">
        <div className="fup-tiles" role="group" aria-label="추적 구분">
          {CHIPS.map((c) => (
            <button type="button" key={c.key}
                    className={`fup-tile${c.key === here ? " on" : ""}${c.key === "over" && count.over > 0 ? " warn" : ""}`}
                    aria-pressed={c.key === here} onClick={() => setTab(c.key)}>
              <b>{count[c.key]}</b><span>{c.label}</span>
            </button>
          ))}
        </div>
        <label className="fup-find">
          <span>검색</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="이름 · 환자번호 · 전화" />
        </label>
      </div>

      <div className="fup-cols">
        <div className="fup-list">
          <Body loading={list.loading && !list.data} error={list.error}
                onRetry={list.reload}
                empty={shown.length === 0 && (
                  <Empty title={here === "all" ? "추적 중인 환자가 없습니다"
                    : here === "cand" ? "회차를 만들 추적 대상이 없습니다"
                      : `「${CHIPS.find((c) => c.key === here).label}」에 해당하는 환자가 없습니다`} />
                )}>
            <div className="tbl-wrap fup-tbl">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>이름</th><th>생년월일</th><th>환자번호</th><th>전화</th>
                    <th>회차</th><th>예정일</th><th>기한</th><th>최근 콜</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((r) => (
                    <Row key={keyOf(r)} r={r} on={chosen != null && keyOf(r) === keyOf(chosen)}
                         onPick={() => setPick(keyOf(r))} />
                  ))}
                </tbody>
              </table>
            </div>
          </Body>
          {/* 표가 짧으면 밑이 통째로 비었다(09-28) — 다른 칸의 다가오는 회차와
              칸별 수를 둔다. 표가 길면 안 그린다(표가 곧 일이다) */}
          {list.data && shown.length < 8 && open.length > 0 && (
            <Ahead open={open} live={live} here={here}
                   onPick={(r) => { setTab("all"); setPick(keyOf(r)); }} />
          )}
        </div>

        <aside className="fup-side">
          {chosen
            /* key — 회차가 바뀌면 칸이 새로 선다. 앞사람의 고른 결과 · 메모가 안 남는다 */
            ? <Detail key={keyOf(chosen)} cfg={cfg} f={chosen} rows={rows} onDone={again}
                      onPick={(k) => setPick(k)} />
            : (
              /* 고를 사람이 아예 없으면 「선택하세요」가 거짓말이다 */
              rows.length === 0 && list.data ? (
                <div className="slot big">
                  <b>콜을 걸 회차가 없습니다</b>
                  <span>BI-RADS 3으로 확정되면 「추적 대상」에 올라오고, 여기서 첫 회차를 만듭니다.</span>
                </div>
              ) : (
                <div className="slot big">
                  <b>왼쪽 목록에서 환자를 선택하세요</b>
                  <span>전화 후 콜 결과를 기록하고, 연결되면 여기서 바로 검사 예약까지 진행합니다.</span>
                </div>
              )
            )}
        </aside>
      </div>
    </Page>
  );
}

/* ── 표 밑 — 한눈에 · 다가오는 회차 ─────────────────────────────
 * 칸별 수(누르면 그 칸으로)와 **지금 칸에 없는** 열린 회차를 예정일 순으로
 * 여섯. 전부 위 목록(GET /followups/)을 다시 센 것이다 — 새 값이 없다.
 * ⚠ 「그 뒤」는 이번 주를 넘긴 열린 회차, 「종결」은 끝난 회차(연결 · 거부) */
function Ahead({ open, live, here, onPick }) {
  const later = open.filter((r) => !H.dueBucket(r.due_at)).length;
  const closed = live.length - open.length;
  const next = open
    .filter((r) => here === "all" || here === "cand" || H.dueBucket(r.due_at) !== here)
    .sort((a, b) => String(a.due_at ?? "9").localeCompare(String(b.due_at ?? "9")))
    .slice(0, 6);
  return (
    <section className="fup-more" aria-label="다가오는 회차">
      <h3>
        {here === "all" || here === "cand" ? "다가오는 회차" : "다른 구분의 다가오는 회차"}
        <span className="home-fill" />
        <span className="hcard-k">이번 주 이후 {later}건 · 종결 {closed}건</span>
      </h3>
      {next.length === 0
        ? <p className="hcard-k">다가오는 회차가 없습니다</p>
        : (
          <ul className="fup-next">
            {next.map((r) => {
              const b = H.dueBucket(r.due_at);
              return (
                <li key={keyOf(r)}>
                  <button type="button" onClick={() => onPick(r)}>
                    <time>{r.due_at ? String(r.due_at).slice(0, 10) : "예정일 없음"}</time>
                    <b>{H.nameOf(r)}</b>
                    <span>{r.round_no != null ? `${r.round_no}회차` : ""}</span>
                    <span className="home-fill" />
                    <span className="hcard-k">{b ? BUCKET[b] : "예정"} · {r.call_result ?? "미연락"}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
    </section>
  );
}

/* 한 줄.
   ⚠ **나이·성별을 못 적는다.** 추적 응답에 성별이 없다 — 생년월일을 그대로 둔다.
   ⚠ **몇 개월 추적인지 못 적는다.** 응답에 간격이 없다(round_no 뿐이다) */
function Row({ r, on, onPick }) {
  const cand = r.status === "candidate";
  const bucket = cand ? null : H.dueBucket(r.due_at);
  const done = !cand && !H.openFollowup(r);
  return (
    <tr className={[done && "off", on && "on"].filter(Boolean).join(" ") || undefined}
        onClick={onPick} tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter") onPick(); }}>
      <td><b>{H.nameOf(r)}</b></td>
      <td className="num">{r.birth_date ?? "—"}</td>
      <td className="num">{r.patient_number ?? "—"}</td>
      <td className="num">{r.phone ?? "—"}</td>
      <td>{cand ? <Chip>BI-RADS 3</Chip> : r.round_no != null ? `${r.round_no}회차` : "—"}</td>
      <td className="num">{r.due_at ? String(r.due_at).slice(0, 10) : "—"}</td>
      <td>
        {cand ? <span className="hcard-k">회차 없음</span>
          : done ? <span className="hcard-k">종결</span>
            : bucket
              ? <span className={`fup-due${bucket === "over" ? " k1" : ""}`}>{BUCKET[bucket]}</span>
              : <span className="hcard-k">예정</span>}
      </td>
      <td>
        {r.call_result
          ? <Chip>{r.call_result}</Chip>
          : <span className="hcard-k">{cand ? "—" : "미연락"}</span>}
        {/* 서버 칸 이름은 called_at 이다(call_at 은 옛 이름) */}
        {(r.called_at ?? r.call_at) && <span className="hcard-k"> {H.day(r.called_at ?? r.call_at)}</span>}
      </td>
    </tr>
  );
}

/* ── 오른쪽 420 — 고른 회차 ────────────────────────────────────── */
function Detail({ cfg, f, rows, onDone, onPick }) {
  const cand = f.status === "candidate";
  const openRound = !cand && H.openFollowup(f);
  const pid = pidOf(f);
  const [copied, setCopied] = useState(false);
  const [just, setJust] = useState(null);   /* 방금 남긴 콜 결과 */

  /* 전화번호는 눌러서 복사 — 창구 전화기에 옮겨 치는 자리다 */
  async function copy() {
    try { await navigator.clipboard.writeText(f.phone); setCopied(true); }
    catch { setCopied(false); }
  }

  /* 같은 사람의 다른 회차 — 몇 번째인지 · 지난 결과 */
  const mine = rows.filter((r) => String(pidOf(r)) === String(pid) && r.status !== "candidate")
    .sort((a, b) => (a.round_no ?? 0) - (b.round_no ?? 0));
  const lastRound = mine.reduce((m, r) => Math.max(m, r.round_no ?? 0), 0);

  return (
    <Card className="fup-card"
          title={(
            <span className="plist-who">
              <b>{H.nameOf(f)}</b>
              <span>{[f.patient_number, f.birth_date].filter(Boolean).join(" · ")}</span>
            </span>
          )}
          right={pid != null && <Btn to={go.patient(pid)}>환자 기록</Btn>}>
      <div className="fup-phone">
        {f.phone ? (
          <button type="button" className="fup-tel" onClick={copy} title="눌러서 복사">
            <b className="num">{f.phone}</b>
            <span>{copied ? "복사했습니다" : "눌러서 복사"}</span>
          </button>
        ) : cand
          /* ⚠ 후보 줄은 서버가 이름만 준다(FollowupViewSet.list) — 없는 게 아니다 */
          ? <span className="hcard-k">추적 대상 목록에는 전화번호가 없습니다 — 환자 기록에서 확인하세요</span>
          : <span className="hcard-k">등록된 전화번호가 없습니다 — 환자 목록에서 수정해 주세요</span>}
      </div>

      <dl className="kv">
        <div><dt>회차</dt><dd>{cand ? "회차 없음 · BI-RADS 3 확정" : `${f.round_no ?? "—"}회차`}</dd></div>
        {!cand && <div><dt>예정일</dt><dd className="num">{f.due_at ? String(f.due_at).slice(0, 10) : "—"}</dd></div>}
        {!cand && (
          <div><dt>최근 콜</dt><dd>
            {f.call_result ?? "미연락"}
            {(f.called_at ?? f.call_at) && ` · ${H.day(f.called_at ?? f.call_at)}`}
            {f.call_note && ` · ${f.call_note}`}
          </dd></div>
        )}
        {!cand && <div><dt>상태</dt><dd>{openRound ? "진행 중" : `종결${f.closed_reason ? ` · ${f.closed_reason}` : ""}`}</dd></div>}
        {f.round_result && <div><dt>회차 결과</dt><dd>{ROUND[f.round_result] ?? f.round_result}</dd></div>}
      </dl>

      {mine.length > 1 && (
        <div className="fup-rounds">
          {mine.map((r) => (
            <button type="button" key={keyOf(r)} className={`pill${keyOf(r) === keyOf(f) ? " on" : ""}`}
                    onClick={() => onPick(keyOf(r))}>
              {r.round_no}회차{r.round_result ? ` · ${ROUND[r.round_result] ?? r.round_result}` : ""}
            </button>
          ))}
        </div>
      )}

      {cand && <Make cfg={cfg} pid={pid} round={1} onDone={onDone} title="첫 회차 만들기" />}

      {openRound && (
        <Call cfg={cfg} f={f} onDone={(result) => { setJust(result); onDone(); }} />
      )}

      {/* 연결로 끝난 회차(또는 이미 끝난 회차) — 다음 걸음 셋 */}
      {!cand && !openRound && (
        <Next cfg={cfg} f={f} pid={pid} just={just} last={lastRound} onDone={onDone} />
      )}
    </Card>
  );
}

/* ── 콜 기록 — `docs/mockup/NursingCallModal.html` 을 칸 안으로 ──
 * ⚠ **「연결」은 이 회차를 끝낸다.** 되돌릴 수 없어서 고르는 것과
 *   남기는 것을 두 걸음으로 나눈다(9장).
 */
const RESULTS = ["연결", "부재", "거부"];

function Call({ cfg, f, onDone }) {
  const [pick, setPick] = useState(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const may = useCan("nursing.followup.call");

  async function save() {
    if (!pick || busy) return;
    setBusy(true);
    setErr(null);
    try {
      /* ⚠ 메모 칸 이름은 call_note 다. /call 은 status 를 안 받는다 —
         「연결」로 회차를 끝내려면 closeFollowup 을 따로 부른다(api.js) */
      const id = f.followup_id;
      await cfg.api.logCall(id, { call_result: pick, call_note: note });
      if (pick === "연결") {
        await cfg.api.closeFollowup(id, { status: "resolved", closed_reason: "안내 콜 연결" });
      }
      onDone?.(pick);
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="fup-sec">
      <h3>콜 기록</h3>
      <div className="work-seg narrow" role="radiogroup" aria-label="콜 결과">
        {RESULTS.map((v) => (
          <button type="button" key={v} role="radio" aria-checked={v === pick}
                  className={`work-opt${v === pick ? " on" : ""}`}
                  disabled={!may.ok} onClick={() => setPick(v)}>{v}</button>
        ))}
      </div>
      <textarea className="fup-note" value={note} onChange={(e) => setNote(e.target.value)}
                rows={2} placeholder="메모" disabled={!may.ok} />
      {err && <p className="note err">{err}</p>}
      <div className="rowb">
        {/* ⚠ 9장이 남기라고 한 말 — 되돌릴 수 없는 갈림길이다 */}
        <span className="hcard-k">「연결」로 기록하면 이 회차가 종결됩니다. 부재 · 거부는 목록에 다시 표시됩니다.</span>
        <Btn kind="fill" onClick={save} {...may.attrs} disabled={!pick || busy || !may.ok}>
          {busy ? "기록하는 중…" : "기록"}
        </Btn>
      </div>
    </section>
  );
}

/* ── 끝난 회차 다음 — 검사 예약 · 다음 회차 · 회차 결과 ────────────
 * 연결은 「안내를 했다」일 뿐 검사가 잡힌 것이 아니다. 예약은 예약 관리에서
 * 잡는다(같은 날 중복 막이가 거기 있다) — followup 을 달아 보내면 그 예약이
 * 이 회차에 이어진다(POST /exam-orders/schedule 의 followup_id).
 */
function Next({ cfg, f, pid, just, last, onDone }) {
  const may = useCan(["nursing.followup.call", "nursing.waiting.view"]);
  const [result, setResult] = useState(f.round_result ?? null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const connected = (just ?? f.call_result) === "연결";

  async function saveResult(v) {
    setBusy(true); setMsg(null);
    try {
      await cfg.api.roundResult(f.followup_id, v);
      setResult(v); setMsg("회차 결과를 남겼습니다");
      onDone?.();
    } catch (e) { setMsg(e.detail || e.message); }
    finally { setBusy(false); }
  }

  const due = f.due_at ? String(f.due_at).slice(0, 10) : "";
  const to = `${go.nursing.reservations()}?patient=${pid}&followup=${f.followup_id}${due ? `&date=${due}` : ""}`;

  return (
    <>
      <section className="fup-sec">
        <h3>{connected ? "연결됐습니다 — 다음 단계" : "종결된 회차"}</h3>
        <div className="rowb fup-go">
          <Btn kind="fill" to={to}>검사 예약 잡기 →</Btn>
        </div>
      </section>

      <section className="fup-sec">
        <h3>회차 결과</h3>
        <div className="work-seg narrow" role="radiogroup" aria-label="회차 결과">
          {Object.entries(ROUND).map(([k, name]) => (
            <button type="button" key={k} role="radio" aria-checked={k === result}
                    className={`work-opt${k === result ? " on" : ""}`}
                    disabled={busy || !may.ok} onClick={() => saveResult(k)}>{name}</button>
          ))}
        </div>
        {msg && <span className="hcard-k" role="status">{msg}</span>}
      </section>

      {/* 다음 회차는 **이 사람의 마지막 회차 뒤에만** 만든다 — 앞 회차를 열어
          [다음 회차]를 누르면 같은 번호가 둘 생긴다 */}
      {(f.round_no ?? 0) >= last && (
        <Make cfg={cfg} pid={pid} round={(f.round_no ?? 0) + 1} onDone={onDone}
              title={`다음 회차(${(f.round_no ?? 0) + 1}회차) 만들기`} />
      )}
    </>
  );
}

/* ── 회차 만들기 ───────────────────────────────────────────────
 * **6 · 12 · 24개월이 여기서 정해진다.** 서버에 「간격」 칸이 없고 due_at
 * 하나만 받는다 — 단추가 날짜를 계산해 넣는다. 날짜칸은 손으로 고칠 수 있다.
 */
const MONTHS = [6, 12, 24];

function plus(months) {
  const d = new Date();
  d.setMonth(d.getMonth() + months);
  return H.iso(d);
}

function Make({ cfg, pid, round, onDone, title }) {
  const [due, setDue] = useState(plus(6));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [ok, setOk] = useState(null);
  const may = useCan("nursing.followup.create");

  async function make() {
    if (pid == null || busy) return;
    setBusy(true); setErr(null);
    try {
      /* due_at 은 DateTimeField 다 — 병원 시간(KST) 오전 9시로 붙여 보낸다 */
      await cfg.api.createFollowup({ patient_id: Number(pid), round_no: round,
                                     due_at: `${due}T09:00:00` });
      setOk(`${round}회차 · ${due}로 만들었습니다`);
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="fup-sec">
      <h3>{title}</h3>
      <div className="fup-make">
        <div className="work-seg narrow" role="group" aria-label="추적 간격">
          {MONTHS.map((m) => (
            <button type="button" key={m} className={`work-opt${due === plus(m) ? " on" : ""}`}
                    disabled={!may.ok} onClick={() => setDue(plus(m))}>+{m}개월</button>
          ))}
        </div>
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
               disabled={!may.ok} aria-label="추적 예정일" />
      </div>
      {err && <p className="note err">{err}</p>}
      <div className="rowb">
        {ok && <span className="hcard-k" role="status">{ok}</span>}
        <Btn kind="fill" onClick={make} {...may.attrs} disabled={!due || busy || !may.ok}>
          {busy ? "만드는 중…" : "만들기"}
        </Btn>
      </div>
    </section>
  );
}

Followups.need = DESK;
