import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { ArrangeBar, Panes, useArrange } from "./Arrange";
import { Link, useNavigate } from "react-router-dom";
import { Body } from "./Body";
import { Chip } from "./Parts";
import { can } from "../perm";
import { byDate, monthGrid, today } from "../dept/home";
import { seen, useRecent } from "./recent";
import * as notes from "./notes";
import { notes as notesApi } from "../api";
import { useApi } from "./useApi";
import Register from "../screens/reception/Register";
import StageBoard from "./StageBoard";
import { Filters, applyFilters } from "./Filters";

/* 과 홈 — 배치는 `docs/mockup/*Home.html` 이 정한다
 * ════════════════════════════════════════════════════════════════
 *
 * 다섯 과의 목업은 **본문 마크업이 완전히 같다.** 다른 것은 자료뿐이다.
 * 그래서 화면은 이 파일 하나고, 칸에 무엇이 들어가는지는 dept/*.jsx 가
 * 준다 — 과가 늘어도 화면을 새로 만들지 않는다.
 *
 *   제목 줄   과 이름 · 날짜 ·········· [업무 화면 →] [주 동작]
 *   칩 줄     그 과 화면으로 가는 바로가기
 *   최근 줄   최근 본 환자 ·········· 내 계정으로 연 환자만 보입니다
 *   ┌ 1.5fr ──────────┬ 1fr ────────┬ 330px ──┐
 *   │ (접수 — 원무만)  │ 오늘 한 일   │ 달력     │
 *   │ 주 큐            │             ├─────────┤
 *   ├─────────────────┤             │ 할 일    │
 *   │ 확인이 필요한 것  │ 인계 사항    │         │
 *   └─────────────────┴─────────────┴─────────┘
 *
 * **인계는 가운데 아래다.** 오른쪽이 아니다 — 「오늘 한 일」 바로 밑에
 * 붙어야 「오늘 무슨 일이 있었나」가 한 칸에서 읽힌다.
 *
 * ⚠ **쪽 머리(빵부스러기 + 「홈」)를 쓰지 않는다.** 목업에 없다. 홈은 더
 *   갈 위가 없고 제목이 「홈」이면 아무 말도 안 하는 줄이 하나 느는 것이다.
 *   그래서 이 화면만 <Page> 를 안 쓰고 자기 머리를 그린다.
 *
 * ⚠ **값이 없는 칸도 없애지 않는다.** 없애면 배치가 또 달라진다.
 *   자리를 두고 무엇이 없어서 비었는지 적는다.
 *
 * ⚠ **「몇 분 기다렸는지」는 쓰지 않는다.** 서버가 그 값을 주지 않는다.
 */
export default function Home({ cfg }) {
  const [bag, setBag] = useState(null);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  /* 과가 홈 설정을 안 준 경우. nav.js 에 use:"home" 을 적어 두고 dept 쪽에
     home 을 안 만들면 여기서 터지는 대신 무엇이 빠졌는지 말한다.
     ⚠ 객체 리터럴을 여기서 만들면 **매 렌더마다 새것**이라 아래 useEffect 의
       의존이 계속 바뀐다. 모듈 바깥에 한 벌만 둔다 */
  const home = cfg.home ?? NO_HOME;

  /* 조용히 다시 불러온다 — 깜빡이면 읽던 중에 화면이 사라진다.
     첫 판만 뼈대를 보이고, 그 뒤로는 값만 갈아 끼운다 */
  useEffect(() => {
    let live = true;
    home.load()
      .then((v) => { if (live) { setBag(v); setError(null); } })
      .catch((e) => { if (live) setError(e); });
    return () => { live = false; };
  }, [home, tick]);

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), REFRESH_MS);
    return () => clearInterval(t);
  }, []);

  const again = () => setTick((n) => n + 1);
  const [barEl, setBarEl] = useState(null);

  return (
    <main className="page home">
      <header className="home-head">
        <h1>{cfg.name}</h1>
        <span className="home-day">{today()}</span>
        <span className="home-fill" />
        {/* 「배치 편집」 자리 — Desk 가 이 자리로 그린다(칸 목록을 Desk 가 알아서).
            편집 중 막대도 여기 서서 **줄을 따로 차지하지 않는다** */}
        <span className="home-arr" ref={setBarEl} />
        <Act act={home.primary} />
      </header>

      <Recent />

      <Body loading={!bag && !error} error={error} onRetry={again}
            skeleton="block">
        <Desk cfg={cfg} home={home} bag={bag} again={again} barEl={barEl} />
      </Body>
    </main>
  );
}

/* 몇 초마다 조용히 다시 불러온다 (5.6) */
const REFRESH_MS = 30000;

const NO_HOME = { load: () => Promise.resolve(null) };

/* 요약 줄 오른쪽 — **주 동작 하나뿐이다.**
 *
 * ⚠ 「내 환자 화면 →」 같은 단추를 여기 두지 않는다. 그건 3층 화면 줄에
 *   이미 있는 곳이고, 같은 링크가 한 화면에 두 번 있으면 **내비게이터가
 *   둘로 보인다**(5.5). 여기 남는 것은 지금 할 일 하나다.
 */
function Act({ act }) {
  if (!act || (act.need && !can(act.need))) return null;
  return <Link className="btn fill" to={act.to}>{act.label}</Link>;
}

/* ── 최근 본 환자 ──────────────────────────────────────────────
 * ⚠ **브라우저에 안 남긴다.** 공용 PC 라 localStorage 에 환자 이름·번호를
 *   적어 두면 다음 사람이 그대로 본다. 화면이 사는 동안만이다(lib/recent.js)
 */
function Recent() {
  const list = useRecent();
  return (
    <div className="recent">
      <b>최근 본 환자</b>
      {list.length === 0
        ? <span className="recent-none">아직 없습니다</span>
        : list.map((r) => (
          <span className="rchip" key={r.id}>
            {r.name}
            {r.no && <i>{r.no}</i>}
            {r.why && <em>{r.why}</em>}
          </span>
        ))}
      <span className="home-fill" />
      <span className="recent-note">내 계정으로 열어 본 환자만 표시됩니다</span>
    </div>
  );
}

/* ══ 3단 격자 ═══════════════════════════════════════════════════
 *
 * 칸마다 이름(id)을 붙이고, 어느 단 몇 번째에 둘지는 배치(layout)가 정한다.
 * 기본 배치는 위 머리말 그림 그대로다. 칸 머리의 손잡이(⠿)를 끌거나,
 * 손잡이에 초점을 두고 방향키로 옮긴다(↑↓ 같은 단 안, ←→ 옆 단).
 *
 * ⚠ 배치는 이 브라우저에 과별로 남긴다(localStorage). 「최근 본 환자」는
 *   공용 PC 라 안 남기지만(아래 Recent) 배치에는 **환자 정보가 없다** —
 *   칸 이름의 순서뿐이다.
 */
function Desk({ cfg, home, bag, again, barEl }) {
  const queue = bag && home.queue ? home.queue(bag) : null;
  const stuck = (bag && home.stuck ? home.stuck(bag) : []).filter((s) => s.count > 0);
  const done = bag && home.done ? home.done(bag) : null;
  const marks = bag && home.marks ? home.marks(bag) : [];
  const side = bag && home.side ? home.side(bag) : null;

  /* ⚠ Todo · Handover 는 key 로 과를 건다. 과를 옮기면 **다시 마운트**되어
     useState 의 첫 읽기가 그 과 것으로 다시 돈다 — 효과 안에서 setList 하면
     렌더가 한 번 더 돌고, 그 사이 남의 과 메모가 한 판 보인다 */
  const cards = {
    /* intake:"top" 이면 격자 칸이 아니라 맨 위 한 줄이다(아래 return) */
    intake:   home.intake === true && <Intake api={cfg.api} onDone={again} />,
    queue:    <Queue queue={queue} />,
    stuck:    <Stuck items={stuck} />,
    flow:     home.flow && <Flow flow={home.flow(bag)} />,
    done:     home.done && <Done done={done} />,
    todo:     <Todo key={cfg.key} dept={cfg.key} />,
    handover: <Handover key={cfg.key} dept={cfg.key} />,
    calendar: <Calendar marks={marks} note={bag && home.calNote ? home.calNote(bag) : null}
                        to={home.calTo} />,
    side:     home.side && <Side side={side} />,
    /* 과가 더 싣는 목록 칸(home.cards — { 이름: (bag) => 칸 | null }).
       null 이면 칸을 안 세운다 — 서버가 그 경로를 안 열어 준 배포본(403 ·
       404)에서 빈 칸이 서지 않게. 영상의학과 「내 판독 불일치 결과」가 쓴다 */
    ...Object.fromEntries(Object.entries(home.cards ?? {}).map(([id, make]) => {
      const spec = bag ? make(bag) : null;
      return [id, spec && <ListCard key={id} spec={spec} />];
    })),
  };

  /* 기본 배치 — 과가 home.layout 으로 바꿀 수 있다. 「오늘 한 일」을 안 쓰는 과(home.done 이 없다)는 그 자리에
     할 일이 올라온다 — 오른쪽 단은 달력과 오늘 예약이 쓴다 */
  const base = (home.layout ?? [
    ["intake", "queue", "stuck"],
    ["flow", home.done ? "done" : "todo", "handover"],
    ["calendar", "side", ...(home.done ? ["todo"] : [])],
  ]).map((pane) => pane.filter((id) => cards[id]));

  const lay = useArrange(`home.${cfg.key}`, base);

  return (
    <>
      {/* 간호과는 위에서 아래로 **환자가 오는 순서**다 — 찾아서 접수 →
          오늘 현황판(도착 예정 → … → 외래 진료) → 그 밖의 일. 둘 다 끌어
          옮기는 칸이 아니다. 흐름은 한 방향으로 읽혀야 한다 */}
      {home.intake === "top" && (
        <div className="home-intake"><Intake api={cfg.api} onDone={again} /></div>
      )}
      {home.board && bag && <StageBoard {...home.board(bag)} />}
      {barEl && createPortal(<ArrangeBar lay={lay} />, barEl)}
      <Panes lay={lay} cards={cards} className="desk" paneClass="pane"
             cols={home.cols ?? ["minmax(0, 1.5fr)", "minmax(0, 1fr)", "var(--desk-r)"]} />
    </>
  );
}

/* 칸 하나의 틀 — 점 + 제목 + 건수, 오른쪽에 작은 글씨나 단추.
   ⚠ 목업은 칸마다 점 색이 다르지만(파랑·주황·초록·보라) 이 판은 **상태
     색을 새로 만들지 않는다**(tokens.css). 점은 **한 모양**이다 — 시안 ·
     검정 · 빈 네모로 갈라 두었더니 뜻 없는 무늬로 읽혔다(09-28).
     dot="none" 은 제목이 곧 값인 칸(달력의 「2026년 9월」)만 쓴다 */
function Card({ dot = "on", title, count, right, grow, className = "", children }) {
  /* 옮기기 손잡이는 배치 편집 중에만 lib/Arrange.jsx 의 틀이 단다 */
  const cls = ["hcard", grow && "grow", className].filter(Boolean).join(" ");
  return (
    <section className={cls}>
      <div className="hcard-h">
        {dot !== "none" && <i className="hdot" aria-hidden="true" />}
        <h2>{title}</h2>
        {count != null && <b className="hcard-n">{count}</b>}
        <span className="home-fill" />
        {right}
      </div>
      {children}
    </section>
  );
}

/* 빈 칸 한 줄 — 칸 몸통 자리를 대신 차지하고 **그 가운데에** 선다(.hnone).
   칸이 단 끝까지 늘어나도 「없습니다」가 머리 밑에 붙은 채 아래가 통째로
   비지 않는다. 목록 그릇(.qrows · .drows …) 안에 두지 않는다 — 그릇은
   격자 · 여백이 있어서 가운데를 못 잡는다 */
function None({ children }) {
  return <p className="hnone">{children}</p>;
}

/* ── 왼쪽 맨 위 — 접수 (원무만) ────────────────────────────────
 * 찾아서 확인한 뒤 누른다. **자동으로 접수하지 않는다** — 동명이인이
 * 있어서 한 명이어도 사람이 골라야 한다.
 */
function Intake({ api, onDone }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState(null);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [reg, setReg] = useState(false);
  const [ok, setOk] = useState(null);
  /* 접수 화면(screens/reception/Intake.jsx)과 같은 열쇠 — 원무든 간호든 */
  const may = can(["reception.checkin", "nursing.waiting.view"]);

  async function find(e) {
    e.preventDefault();
    if (!q.trim()) return;
    setErr(null);
    setOk(null);
    try { setFound(await api.search(q.trim()) ?? []); }
    catch (e2) { setErr(e2); setFound([]); }
  }

  async function take(p) {
    setBusy(p.patient_id);
    setErr(null);
    try {
      await api.checkIn({ patient_id: p.patient_id });
      setFound((list) => list.filter((r) => r.patient_id !== p.patient_id));
      /* 줄이 조용히 사라지기만 하면 됐는지 모른다 */
      setOk(`${p.name ?? "환자"} 님을 접수했습니다 — 「내원 대기」에 표시됩니다`);
      onDone();
    } catch (e2) { setErr(e2); }
    finally { setBusy(null); }
  }

  return (
    <Card title="접수" right={<span className="hcard-k">환자를 검색해 확인한 뒤 접수합니다</span>}>
      {/* 등록 팝업을 여기서 바로 연다 — 만든 사람은 아래 찾은 줄에 올라와
          [접수] 만 누르면 된다. 다른 화면으로 넘기지 않는다 */}
      {reg && (
        <Register onClose={() => setReg(false)}
                  onDone={(p, how) => {
                    setReg(false); setErr(null); setFound([p]);
                    setOk(how === "exists"
                      ? "이미 등록된 환자입니다 — 아래 목록에서 [접수]를 누르세요"
                      : "등록했습니다 — 아래 목록에서 [접수]를 누르세요");
                  }} />
      )}
      <form className="intake-find" onSubmit={find}>
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="이름 · 전화 · 생년월일" aria-label="환자 검색" />
        <button className="btn dark" type="submit">검색</button>
        <button className="btn line" type="button" onClick={() => setReg(true)}>
          + 신규 등록
        </button>
      </form>

      {err && <p className="hcard-err">{err.detail || err.message}</p>}
      {ok && !err && <p className="hcard-k hpad" role="status">{ok}</p>}
      {found?.length === 0 && !err && !ok && (
        <p className="hcard-k hpad">찾는 환자가 없습니다</p>
      )}

      {(found ?? []).map((p) => (
        <div className="ifound" key={p.patient_id}>
          <span className="ifound-tx">
            <span className="ifound-1"><b>{p.name}</b></span>
            <span className="ifound-2">
              {[p.patient_number, p.birth_date, p.phone].filter(Boolean).join(" · ")}
            </span>
          </span>
          <button className="btn fill sm" onClick={() => take(p)}
                  disabled={busy === p.patient_id || !may}
                  title={may ? undefined : "권한이 없습니다. 관리자에게 문의하세요"}>접수</button>
        </div>
      ))}
    </Card>
  );
}

/* ── 왼쪽 — 주 큐 ──────────────────────────────────────────────
 * 한 줄짜리다. 번호 · 이름 · 나이 성별 · 칩 · 한 줄 요약 · 시각 · ›
 */
function Queue({ queue }) {
  /* 탭이 없으면 칸 하나가 곧 탭 하나다 — 부르는 쪽이 둘 다 쓸 수 있게 */
  const tabs = queue?.tabs?.length
    ? queue.tabs
    : [{ key: "all", name: queue?.title, rows: queue?.rows, empty: queue?.empty }];
  /* 탭 순서(흐름 순)와 처음 여는 탭(지금 할 일)이 다를 수 있다 — queue.pick */
  const [pick, setPick] = useState(queue?.pick ?? tabs[0].key);
  const tab = tabs.find((t) => t.key === pick) ?? tabs[0];
  /* 거르는 칩(queue.filters, lib/Filters) — 탭 안에서 한 번 더 거른다 */
  const [fv, setFv] = useState({});
  const rows = applyFilters(tab.rows ?? [], queue?.filters, fv);
  /* 열 이름은 과가 바꿀 수 있다. 그리고 **이 탭의 어느 줄에도 값이 없는
     열은 이름을 안 단다** — 빈 열 위에 「상태」만 떠 있으면 무엇을 적는
     칸인지 묻게 된다(유방외과 09-28). 셀 자리는 그대로 둔다(subgrid) */
  const cols = { ...COLS, ...queue?.cols };
  const has = (k) => rows.some((r) => r[k]);
  /* 과가 더 싣는 열(유방외과: 내원 · 담당의). 「진행」 뒤, 환자번호 앞에 선다.
     격자 열 수가 달라지므로 틀을 여기서 다시 짠다(.qrows 의 기본 7열) */
  /* 탭마다 다를 수 있다 — 같은 「언제」 칸도 촬영 대기 탭은 요청 시각,
     나머지는 촬영 시각이다(영상 홈). 칸 이름이 그 차이를 말한다 */
  const extra = tab.extra ?? queue?.extra ?? [];
  /* ⚠ 09-28 — 남는 폭을 **맨 끝 빈 칸 하나에 몰지 않는다.** 그렇게 하면
     왼쪽 칸들이 붙고 가운데가 통째로 빈다(영상 홈 「판독 현황」). 칸마다
     제 글자만큼은 받고(max-content) 나머지를 비율로 나눠 표처럼 퍼지게
     한다. 한 줄 요약(sub)이 가장 많이 받는다 */
  const spread = "minmax(max-content, 1fr)";
  /* ⚠ 이 탭의 **어느 줄에도 값이 없는 열은 폭을 안 받는다**(0). 이름만 떼고
     1fr 을 그대로 주면 빈 열이 표 한가운데 폭을 먹고, 정작 값이 있는
     「할 일」 · 「기한」이 두 줄로 눌렸다(간호 홈 「전화 · 예약 확인」 1280) */
  /* ⚠ 09-28 — 빈 열을 폭 0 으로만 두면 **열 사이 간격은 그대로 먹는다**
     (빈 나이·성별 열 · 예전 빈 칸 자리마다 간격 하나씩). 그래서 빈 열은
     격자에서 아예 뺀다 — 머리 줄과 QRow 가 같은 `on` 으로 셀을 안 그려서
     subgrid 의 셀 수가 열 수와 늘 맞는다 */
  const on = { meta: has("meta"), chip: has("chip"), sub: has("sub") };
  const shown = extra.filter((c) => has(c.key));
  const grid = {
    gridTemplateColumns: [
      "max-content",                                   // 번호
      "minmax(max-content, 1.2fr)",                    // 이름
      on.meta && spread,                               // 나이·성별
      on.chip && spread,                               // 칩
      on.sub && "minmax(6em, 2fr)",                    // 한 줄 요약(두 줄까지 접힌다)
      ...shown.map(() => spread),                      // 과가 더 싣는 칸
      "minmax(min-content, max-content)",              // 환자번호 · 시각(좁으면 두 줄)
    ].filter(Boolean).join(" "),
  };

  return (
    <Card title={queue?.title ?? "목록"} count={rows.length} grow
          right={queue?.hint && <span className="hcard-k">{queue.hint}</span>}>
      {/* 탭은 둘 이상일 때만. 하나뿐이면 칸 머리가 이미 그 말을 했다 */}
      {tabs.length > 1 && (
        <nav className="qtabs">
          {tabs.map((t) => (
            <button key={t.key} type="button"
                    className={`qtab${t.key === tab.key ? " on" : ""}`}
                    aria-pressed={t.key === tab.key}
                    onClick={() => setPick(t.key)}>
              {t.name}<i>{(t.rows ?? []).length}</i>
            </button>
          ))}
        </nav>
      )}
      <Filters groups={queue?.filters} value={fv} onChange={setFv} />
      {rows.length === 0
        ? <None>{tab.empty ?? "목록이 비어 있습니다"}</None>
        : <div className="qrows" style={grid}>
              <div className="qrow-head" aria-hidden="true">
                <i className="qrow-n" />
                <b>이름</b>
                {on.meta && <span className="qrow-meta">{cols.meta}</span>}
                {on.chip && <span className="qrow-chip">{cols.chip}</span>}
                {on.sub && <span className="qrow-sub">{cols.sub}</span>}
                {shown.map((c) => <span className="qrow-x" key={c.key}>{c.name}</span>)}
                {/* 오른쪽 끝에 시각도 서는 탭이면 머리에 적는다 — 「환자번호」
                    밑에 11:56 이 붙어 번호의 일부로 읽혔다(09-28) */}
                <span className="qrow-r">{has("at") ? `${cols.r} · 시각` : cols.r}</span>
              </div>
              {rows.map((r, i) => <QRow key={r.id} row={r} n={i + 1} on={on} extra={shown} />)}
          </div>}
    </Card>
  );
}

const COLS = { meta: "나이·성별", chip: "구분", sub: "상태", r: "환자번호" };

/* ⚠ **환자번호는 오른쪽 끝이다.** 왼쪽에 몰아 두면 한 줄 요약이 짧은 과
 *   (유방외과처럼 요약이 아예 없는 과)에서 가운데가 통째로 빈다.
 *   양 끝을 잡아야 표로 읽힌다 — 「1 김민지 47·여 ⋯⋯ P-0012 ›」
 */
function QRow({ row, n, on, extra = [] }) {
  const open = useOpen(row);
  return (
    <article className="qrow" {...open}>
      <i className="qrow-n">{n}</i>
      <b>{row.name}</b>
      {/* 열이 있으면(on — 이 탭의 어느 줄에든 값이 있으면) 이 줄에 값이
          없어도 셀은 그린다 — 안 그리면 subgrid 에서 자식 수가 줄어 뒤
          항목이 앞 컬럼으로 밀린다(나이·성별이 빈 줄). 열이 통째로 없으면
          머리 줄과 같이 셀도 안 그린다 */}
      {on.meta && <span className="qrow-meta">{row.meta}</span>}
      {on.chip && (
        <span className="qrow-chip">
          {row.chip ? <Chip tone={row.chipTone ?? "line"}>{row.chip}</Chip> : null}
        </span>
      )}
      {on.sub && <span className="qrow-sub">{row.sub}</span>}
      {extra.map((c) => <span className="qrow-x" key={c.key}>{row[c.key]}</span>)}
      <span className="qrow-r">
        {row.no && <i className="qrow-no">{row.no}</i>}
        {row.at && <time>{row.at}</time>}
        {row.to && <i className="qrow-go" aria-hidden="true">›</i>}
      </span>
    </article>
  );
}

/* 줄을 누르면 그 환자를 열고, **열었다는 사실만** 기억한다(메모리).
   누를 데가 없으면 커서도 안 바꾼다 — 눌러 보고 나서야 알면 늦다 */
function useOpen(row) {
  const nav = useNavigate();
  if (!row.to) return {};
  const go = () => {
    /* ⚠ **환자 번호로 담는다.** row.id 는 과마다 다르다 — 영상은 검사,
       병리는 검체, 간호는 오더 번호다. 그대로 담으면 「최근 본 환자」가
       같은 환자를 여러 칩으로 늘리고 번호가 겹치면 남을 덮어쓴다
       (lib/recent.js 의 경고). 과들이 줄에 pid 를 같이 실어 준다 */
    seen({ id: row.pid ?? row.id, name: row.name, no: row.no, why: row.why });
    nav(row.to);
  };
  return {
    role: "button",
    tabIndex: 0,
    onClick: go,
    onKeyDown: (e) => { if (e.key === "Enter") go(); },
  };
}

/* ── 왼쪽 아래 — 확인이 필요한 것 ──────────────────────────────
 * 종류 태그 + 문장 + 건수. **0건은 줄을 안 세운다** — 없는 걱정이 줄로
 * 서면 진짜 걱정이 묻힌다.
 */
function Stuck({ items }) {
  const total = items.reduce((n, c) => n + c.count, 0);
  return (
    <Card title="확인 필요" count={total} className="hug">
      {/* 줄들을 한 격자(.srows)에 넣는다 — 태그 폭이 달라도 문장이 같은
          x 에서 시작한다(09-28, 「추적 기한」과 「검체」 뒤 문장이 들쭉날쭉) */}
      {items.length === 0
        ? <None>지금 확인할 것이 없습니다</None>
        : <div className="srows">
            {items.map((c) => (
              <Line key={c.tag} to={c.to} className="srow">
                <span className="stag">{c.tag}</span>
                <span className="srow-tx">{c.text}</span>
                <span className="srow-n">{c.count}건</span>
              </Line>
            ))}
          </div>}
      {/* 단 맨 아래 칸이면 남는 높이를 받는다 — 줄 밑이 그냥 비면 덜 그린
          것처럼 보였다. 바닥 한 줄로 칸의 끝을 잡는다(인계 사항과 같은 꼴) */}
      {items.length > 0 && (
        <p className="hcard-foot">0건인 항목은 줄을 세우지 않습니다.</p>
      )}
    </Card>
  );
}

function Line({ to, className, children }) {
  return to
    ? <Link className={className} to={to}>{children}</Link>
    : <div className={className}>{children}</div>;
}

/* ── 가운데 위 — 오늘 흐름 ────────────────────────────────────
 *
 * 지금 병원 어디에 사람이 몰려 있는지. `/patients/today-status` 의 stage 를
 * 세기만 하면 나오는 값이라 **지어낸 것이 하나도 없다.**
 *
 * 막대는 제일 많은 칸을 기준으로 한 비율이다 — 눈으로 견주라고 두는 것이지
 * 수를 대신하지 않는다. 수는 오른쪽에 그대로 적는다.
 */
function Flow({ flow }) {
  const items = flow?.items ?? [];
  const top = Math.max(1, ...items.map((i) => i.count));
  return (
    <Card title={flow?.title ?? "오늘 흐름"}
          right={flow?.summary && <span className="hcard-k">{flow.summary}</span>}>
      {items.length === 0 ? <None>오늘 내원한 환자가 없습니다</None> : (
      <div className="flows">
        {items.map((it) => (
            <Line key={it.name} to={it.to} className="frow">
              <span className="frow-k">{it.name}</span>
              <span className="frow-bar">
                <i style={{ width: `${Math.round((it.count / top) * 100)}%` }} />
              </span>
              <b>{it.count}</b>
            </Line>
          ))}
      </div>
      )}
    </Card>
  );
}

/* ── 가운데 — 오늘 한 일 ──────────────────────────────────────
 * ⚠ 과에 따라 셀 수 있는 곳과 없는 곳이 갈린다. 판독하는 과(영상·병리)는
 *   오늘 확정한 목록이 곧 「한 일」이다. 나머지는 **서버에 없다**(8장 1번).
 *   칸은 그대로 두고 무엇이 없어서 비었는지 적는다.
 */
function Done({ done }) {
  const items = done?.items ?? [];
  return (
    <Card title="오늘 한 일" grow
          right={done?.summary && <span className="hcard-k">{done.summary}</span>}>
      {items.length === 0 ? <None>{done?.empty ?? "집계된 내용이 없습니다"}</None> : (
      <div className="drows">
        {items.map((it) => (
            <Line key={it.id} to={it.to} className="drow">
              <time>{it.at}</time>
              <i className="drow-dot" aria-hidden="true" />
              <span>{it.text}</span>
            </Line>
          ))}
      </div>
      )}
    </Card>
  );
}

/* ── 가운데 아래 — 인계 사항 ───────────────────────────────────
 * 그 과 전체가 본다. **교대 메모이지 환자 기록이 아니다.**
 * ⚠ 09-27 서버로 옮겼다(GET/POST/DELETE /me/notes?type=handover). 전에는
 *   이 브라우저에만 남아 **같은 과 다른 사람에게 안 보였다** — 인계가
 *   안 되는 인계 칸이었다. 서버가 같은 역할끼리 보여 준다.
 *   과 구분은 서버가 로그인한 역할로 하므로 dept 는 다시 부르는 열쇠로만 쓴다.
 */
function Handover({ dept }) {
  const remote = useApi(() => notesApi.list("handover"), [dept]);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const list = (remote.data ?? []).map((n) => ({
    id: n.personal_note_id,
    at: n.created_at,
    who: n.owner_name,
    body: n.content?.text ?? "",
  }));

  async function submit(e) {
    e.preventDefault();
    const v = text.trim();
    if (!v || busy) return;          /* 한글 입력 중 Enter 두 번에 두 건 안 남게 */
    setBusy(true);
    try {
      await notesApi.create("handover", { text: v });
      setText("");
      setOpen(false);
      remote.reload();
    } finally { setBusy(false); }
  }

  async function remove(id) {
    await notesApi.remove(id).catch(() => {});
    remote.reload();
  }

  return (
    <Card title="인계 사항"
          right={(
            <button type="button" className="btn line sm"
                    onClick={() => setOpen((v) => !v)}>인계 남기기</button>
          )}>
      {open && (
        <form className="hand-add" onSubmit={submit}>
          <textarea value={text} onChange={(e) => setText(e.target.value)}
                    placeholder="교대 시 전달할 내용" rows={2} />
          <div className="rowb">
            <button type="button" className="btn line sm"
                    onClick={() => setOpen(false)}>취소</button>
            <button type="submit" className="btn fill sm"
                    disabled={!text.trim() || busy}>남기기</button>
          </div>
        </form>
      )}

      {remote.error && <None>인계 사항을 불러오지 못했습니다</None>}
      {list.length === 0 && !open && !remote.error
        ? <None>{remote.loading ? "불러오는 중…" : "남긴 인계 사항이 없습니다"}</None>
        : list.map((it) => (
          <article className="hrow" key={it.id}>
            <div className="hrow-1">
              <time>{String(it.at ?? "").slice(5, 16).replace("T", " ")}</time>
              <b>{it.who ?? "—"}</b>
              <span className="home-fill" />
              <button className="note-x" aria-label="지우기"
                      onClick={() => remove(it.id)}>
                ×
              </button>
            </div>
            <p>{it.body}</p>
          </article>
        ))}

      <p className="hcard-foot">교대할 때 넘기는 메모입니다. 환자 기록에는 남지 않습니다.</p>
    </Card>
  );
}

/* ── 오른쪽 — 달력 밑 한 칸 (과가 home.side 를 줄 때만) ─────────
 * 간호과는 「오늘 예약」이다 — 오늘 올 사람을 시각 순으로. 줄을 누르면
 * 그 환자로, 머리의 단추는 예약 판으로 간다.
 */
function Side({ side }) {
  const rows = side?.rows ?? [];
  return (
    <Card title={side?.title ?? ""} count={rows.length} grow
          right={side?.to && <Link className="btn line sm" to={side.to}>예약 관리</Link>}>
      {rows.length === 0 ? <None>{side?.empty ?? "목록이 비어 있습니다"}</None> : (
      <div className="drows">
        {rows.map((r) => (
            <Line key={r.id} to={r.to} className="drow">
              <time>{r.at ?? "—"}</time>
              <i className="drow-dot" aria-hidden="true" />
              <span>
                <b>{r.name}</b>{r.meta && <> · {r.meta}</>}{r.sub && <> · {r.sub}</>}
              </span>
            </Line>
          ))}
      </div>
      )}
    </Card>
  );
}

/* ── 과가 더 싣는 목록 칸 (home.cards) ──────────────────────────
 * 두 줄짜리 줄 — 칩 · 이름 · 곁말 ··· 날짜 › / 아래에 까닭 한 줄 · 덧말.
 *   spec = { title, hint, count, empty, error, rows:[{ id, chip, chipTone,
 *            name, meta, sub, note, at, to, off }] }
 * off 인 줄은 흐리게 — 끝난 것(종결)이 열린 것보다 앞에 읽히지 않게 */
function ListCard({ spec }) {
  const rows = spec.rows ?? [];
  return (
    <Card title={spec.title} count={spec.count ?? rows.length} grow
          right={spec.hint && <span className="hcard-k">{spec.hint}</span>}>
      {spec.error ? <None>{spec.error}</None>
        : rows.length === 0 ? <None>{spec.empty ?? "목록이 비어 있습니다"}</None> : (
      <div className="lrows">
        {rows.map((r) => (
              <Line key={r.id} to={r.to} className={`lrow${r.off ? " off" : ""}`}>
                <span className="lrow-1">
                  {r.chip && <Chip tone={r.chipTone ?? "line"}>{r.chip}</Chip>}
                  <b>{r.name}</b>
                  {r.meta && <span className="lrow-meta">{r.meta}</span>}
                  <span className="home-fill" />
                  {r.at && <time>{r.at}</time>}
                  {r.to && <i className="qrow-go" aria-hidden="true">›</i>}
                </span>
                {(r.sub || r.note) && (
                  <span className="lrow-2">
                    {r.sub && <span className="lrow-sub">{r.sub}</span>}
                    {r.note && <em>{r.note}</em>}
                  </span>
                )}
              </Line>
            ))}
      </div>
      )}
    </Card>
  );
}

/* ── 오른쪽 위 — 달력 ──────────────────────────────────────────
 * ⚠ **점은 과가 아는 날짜만** 찍는다. 목업은 「판독 당번 · 학회」를
 *   찍지만 우리 서버에 근무표가 없다. 없는 점은 안 찍는다.
 */
const DOW = ["일", "월", "화", "수", "목", "금", "토"];

function Calendar({ marks, note, to }) {
  const nav = useNavigate();
  const [at, setAt] = useState(() => {
    const n = new Date();
    return { y: n.getFullYear(), m: n.getMonth() };
  });
  const grid = useMemo(() => monthGrid(at.y, at.m), [at]);
  const dots = useMemo(() => byDate(marks), [marks]);
  const kinds = useMemo(() => [...new Set(marks.map((m) => m.kind))], [marks]);

  const now = new Date();
  const nowIso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`
    + `-${String(now.getDate()).padStart(2, "0")}`;

  const move = (d) => setAt(({ y, m }) => {
    const next = new Date(y, m + d, 1);
    return { y: next.getFullYear(), m: next.getMonth() };
  });

  return (
    <Card dot="none" title={grid.label} className="hcal"
          right={(
            <>
              <button type="button" className="hcal-nav" aria-label="이전 달"
                      onClick={() => move(-1)}>‹</button>
              <button type="button" className="hcal-nav" aria-label="다음 달"
                      onClick={() => move(1)}>›</button>
            </>
          )}>
      <div className="hcal-grid">
        {DOW.map((d, i) => (
          <i className={`hcal-dow w${i}`} key={d}>{d}</i>
        ))}
        {grid.cells.map((c, i) => c === null
          ? <i className="hcal-d off" key={`x${i}`} />
          : (
            /* 과가 갈 곳(to)을 주면 날을 누를 수 있다 — 그날 예약 판으로 간다 */
            <i key={c.iso}
               className={`hcal-d w${c.dow}${c.iso === nowIso ? " now" : ""}`
                 + `${c.iso < nowIso ? " past" : ""}${to ? " go" : ""}`}
               {...(to ? {
                 role: "button", tabIndex: 0,
                 "aria-label": `${c.iso} 예약 보기`,
                 onClick: () => nav(to(c.iso)),
                 onKeyDown: (e) => { if (e.key === "Enter") nav(to(c.iso)); },
               } : {})}>
              {c.d}
              <s className={dotClass(dots.get(c.iso), kinds)} />
            </i>
          ))}
      </div>
      {/* ⚠ 숫자는 **머리가 아니라 아래**다. 328px 머리에 달 이름과 단추 둘이
          이미 있어서 거기 더 넣으면 칸 밖으로 37px 나간다 */}
      {(kinds.length > 0 || note) && (
        <p className="hcal-legend">
          {kinds.map((k, i) => (
            <span key={k}><s className={`hcal-dot k${i % 2}`} />{k}</span>
          ))}
          {note && <span className="home-fill" />}
          {note && <span className="hcal-note">{note}</span>}
        </p>
      )}
    </Card>
  );
}

/* 한 날에 점이 여럿이어도 자리는 하나다 — 첫 종류를 찍는다.
   빈 점도 자리를 지킨다. 안 그러면 점 있는 날만 글자가 위로 밀린다 */
function dotClass(kindsHere, kinds) {
  if (!kindsHere?.length) return "hcal-dot";
  return `hcal-dot k${kinds.indexOf(kindsHere[0]) % 2}`;
}

/* ── 오른쪽 아래 — 할 일 ───────────────────────────────────────
 * 내 것만 본다. ⚠ 지금은 이 브라우저에만 남는다(8장 2번)
 */
function Todo({ dept }) {
  const [list, setList] = useState(() => notes.read("todo", dept));
  const [text, setText] = useState("");
  const [composing, setComposing] = useState(false);

  /* ⚠ 한글 조합 중 Enter 는 제출하지 않는다 — 조합을 끝내는 Enter 와 진짜
     Enter 가 따로 와서 같은 할 일이 두 개(끝 글자 잘린 것까지) 생겼다 */
  function submit(e) {
    e.preventDefault();
    if (composing || e.nativeEvent?.isComposing) return;
    setList(notes.add("todo", dept, text));
    setText("");
  }

  const left = list.filter((it) => !it.done).length;

  return (
    <Card title="할 일" grow
          count={list.length > 0 ? `${left}개 남음` : null}
          right={<span className="hcard-k">나만 볼 수 있음</span>}>
      {list.length === 0 ? <None>아래 칸에 적으면 여기에 쌓입니다</None> : (
      <div className="todos">
        {list.map((it) => (
          <label className={`trow${it.done ? " done" : ""}`} key={it.id}>
            <input type="checkbox" checked={it.done}
                   onChange={() => setList(notes.toggle("todo", dept, it.id))} />
            <span>{it.body}</span>
            <button className="note-x" aria-label="지우기"
                    onClick={() => setList(notes.remove("todo", dept, it.id))}>×</button>
          </label>
        ))}
      </div>
      )}
      <form className="todo-add" onSubmit={submit}>
        <input value={text} onChange={(e) => setText(e.target.value)}
               onCompositionStart={() => setComposing(true)}
               onCompositionEnd={() => setComposing(false)}
               placeholder="할 일 추가" aria-label="할 일 추가" />
        <button className="btn dark" type="submit" disabled={!text.trim()}>추가</button>
      </form>
    </Card>
  );
}
