import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Body, Empty } from "../lib/Body";
import { Btn, Page } from "../lib/Page";
import { Chip, Locked, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import { ERR } from "../api";
import * as H from "../dept/home";

/* 1장 · 대기 큐 — `docs/mockup/Radiology.html` · `Pathology.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **두 목업이 유방외과 「내 환자」와 같은 껍데기다.**
 *
 *   ┌ 300px ──┬ 1fr ──────────────────┬ 330px ──┬ 248px ─┐
 *   │ 대기 큐  │ 환자 머리              │ 지난 검사│ 상용구 │
 *   │  1 …     │ 이번 검사 / 이 검체    │ 이 환자의│        │
 *   │  2 …     │ AI 참고 소견           │   이력   │        │
 *   │ [집기]   │ [판독 화면으로]        │         │        │
 *   └──────────┴────────────────────────┴─────────┴────────┘
 *
 * 가운데만 과마다 다르고 나머지는 제목만 바뀐다. 그래서 껍데기 이름이
 * `work-` 다(hospital.css) — 유방외과·영상·병리 셋이 나눠 쓴다.
 *
 * **여기서 하지 않는 일**
 *   · 순서 바꾸기 — 순번은 표시 전용이다. 여럿이 보는 큐라 내가 끌어
 *     옮기면 나만 다른 화면을 보게 된다
 *   · 반려 — 검체나 오더가 이상한지 시스템이 판단할 수 없다
 *
 * ⚠ **경과 시간을 안 쓴다.** 목업 큐 줄 끝의 `41′` 은 서버가 안 준다.
 * ⚠ **탭이 없다.** 목업은 「대기 n / 내 것 n」 둘인데 「내 것」을 부를
 *   경로가 없다 — 큐는 `assigned=none` 으로 박혀 있고, `list()` 에
 *   `assigned=me` 를 얹어도 서버가 그 조건을 보는지 확인할 길이 없다.
 *   **탭이 거짓말하느니 한 목록만 둔다.** 내가 집은 것은 판독 목록
 *   화면이 보여 준다 — 쪽 머리에 그리로 가는 단추를 뒀다(8장).
 */
const POLL_MS = 7000;

export default function QueueScreen({ cfg }) {
  const c = cfg.queue;
  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title}>
        <Locked what={c.title} need={c.need.view} />
      </Page>
    );
  }
  return <Inner cfg={cfg} />;
}

function Inner({ cfg }) {
  const c = cfg.queue;
  const nav = useNavigate();
  const list = useApi(() => cfg.api.queue(), []);
  const again = list.reload;
  const [pick, setPick] = useState(null);

  /* 남이 집어 가면 줄어든다. 가만히 두면 화면이 거짓말을 한다.
     ⚠ **reload(true) 다** — 그냥 reload() 면 7초마다 화면이 「불러오는
       중」으로 돌아가 보고 있던 것이 통째로 사라졌다 온다 */
  useEffect(() => {
    const t = setInterval(() => again(true), POLL_MS);
    return () => clearInterval(t);
  }, [again]);

  const rows = H.rows(list.data);
  const picked = rows.some((r) => cfg.queue.row(r).id === pick)
    ? pick : (rows[0] ? cfg.queue.row(rows[0]).id : null);
  const cur = rows.find((r) => cfg.queue.row(r).id === picked) ?? null;

  function took(goId, orderId) {
    nav(cfg.go.upload(goId), orderId ? { state: { orderId } } : undefined);
  }

  return (
    <Page className="wq-page" crumb={[cfg.name, c.title]} title={c.title}
          right={<Btn to={cfg.go.list()}>판독 목록</Btn>}>
      <div className="work">
        <Side c={c} state={list} rows={rows} pick={picked} onPick={setPick}
              cfg={cfg} onTook={took} />

        <div className="work-mid">
          {!cur
            ? <Empty title={c.emptyText} />
            : <Mid cfg={cfg} row={cur} onTook={took} />}
        </div>

        <Past cfg={cfg} row={cur} />
        <Phrases items={c.phrases} />
      </div>
    </Page>
  );
}

/* ── 왼쪽 300px — 대기 큐 ────────────────────────────────────── */
function Side({ c, state, rows, pick, onPick, cfg, onTook }) {
  const next = rows[0] ? c.row(rows[0]) : null;
  return (
    <aside className="work-q">
      <header className="work-q-h">
        <h2>{c.listTitle}</h2>
        <span className="hcard-k">도착한 순서 · 순서 고정</span>
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0 && <Empty title={c.emptyText} />}>
        <div className="work-q-b">
          {rows.map((raw, i) => {
            const r = c.row(raw);
            return (
              <button type="button" key={r.id}
                      className={`work-row${r.id === pick ? " on" : ""}`}
                      onClick={() => onPick(r.id)}>
                <span className="work-row-1">
                  <i className="work-n">{i + 1}</i>
                  <b>{r.title}</b>
                </span>
                <span className="work-row-2">
                  <span>{r.sub}</span>
                </span>
              </button>
            );
          })}
        </div>
      </Body>
      {next && (
        <footer className="work-q-f">
          <Take cfg={cfg} id={next.id} onTook={onTook} label="다음 건 집기" />
          <span className="hcard-k">맨 앞은 {next.title}</span>
        </footer>
      )}
    </aside>
  );
}

/* 집기 — **되돌릴 수 없다.** 집으면 남의 화면에서 사라지고 내 것이 된다.
   그래서 한 번 더 묻는다(9장).

   ⚠ **과에 따라 집은 것과 다음 화면의 단위가 다르다.**
     병리  검체를 집으면 그 검체로 바로 간다
     영상  오더를 집은 뒤 **Study 를 만들어야 한다**. start-study 가 Study
           행을 만드는 유일한 경로이고, 업로드·판독은 오더 id 가 아니라
           study_id 로 움직인다. `cfg.api.start` 가 있는 과만 이 단계를 탄다.
   ⚠ **집기 다음에 부른다.** 순서를 바꾸면 둘이 동시에 눌렀을 때 둘 다
     Study 를 만들어 놓고 한쪽만 409 로 떨어져 고아 행이 남는다.
   ⚠ **오더 번호를 같이 들고 간다.** 다음 화면부터는 study_id 로만
     움직이는데 「오더 확정」 한 곳만 오더 번호를 받는다. */
function Take({ cfg, id, onTook, label, kind = "line" }) {
  const may = useCan(cfg.queue.need.assign);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function go() {
    setBusy(true);
    setErr(null);
    try {
      await cfg.api.assign(id);
      let goId = id;
      let orderId = null;
      if (cfg.api.start) {
        const st = await cfg.api.start(id);
        goId = st?.study_id ?? st?.id ?? id;
        orderId = st?.exam_order_id ?? id;
      }
      onTook?.(goId, orderId);
    } catch (e) {
      setErr(e.code === ERR.ALREADY_ASSIGNED
        ? "다른 선생님이 이미 맡았습니다"
        : e.code === ERR.NETWORK
          ? "서버에 연결하지 못했습니다"
          : (e.detail || "집기에 실패했습니다"));
      setAsking(false);
    } finally { setBusy(false); }
  }

  if (err) return <span className="hcard-k">{err}</span>;
  if (!asking) {
    return (
      <Btn kind={kind} onClick={() => setAsking(true)} {...may.attrs}
           disabled={!may.ok}>{label}</Btn>
    );
  }
  return (
    <span className="work-ask">
      <span className="hcard-k">집으면 내 것이 됩니다</span>
      <Btn kind="fill" onClick={go} disabled={busy}>
        {busy ? "집는 중…" : "집기"}
      </Btn>
      <Btn onClick={() => setAsking(false)} disabled={busy}>그만</Btn>
    </span>
  );
}

/* ── 가운데 — 고른 건 ──────────────────────────────────────── */
function Mid({ cfg, row, onTook }) {
  const c = cfg.queue;
  const r = c.row(row);
  const one = useApi(() => cfg.api.detail(r.id), [r.id]);
  const d = one.data;

  return (
    <Body loading={one.loading && !one.data} error={one.error} onRetry={one.reload}>
      {d && (
        <>
          <header className="work-head">
            <span className="work-ava" aria-hidden="true">{H.nameOf(d)[0]}</span>
            <span className="work-who">
              <span className="work-1">
                <b>{H.nameOf(d)}</b>
                {H.who(d) && <span>{H.who(d)}</span>}
              </span>
              <span className="work-2">
                {[H.noOf(d), d.birth_date].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="home-fill" />
            {H.some(d.contrast_allergy) && (
              <span className="pb-warn">
                <i aria-hidden="true">⚠</i>{H.some(d.contrast_allergy)}
              </span>
            )}
            {d.patient_id && <Btn to={`/hospital/patients/${d.patient_id}`}>환자 상세</Btn>}
          </header>

          <section className="work-box">
            <header className="work-box-h">
              <h3>{c.detailTitle}</h3>
              <span className="home-fill" />
              {r.chip && <Chip>{r.chip}</Chip>}
            </header>
            {/* key — 사람을 바꾸면 접힘 상태도 새로 시작한다 */}
            <c.Detail key={r.id} d={d} cfg={cfg} />
          </section>

          {/* AI 참고 소견 — ⚠ **이 자리에서는 못 채운다.** AI 는 영상이
              올라간 뒤에 돈다(`POST /studies/{id}/ai-results`). 큐에 있는
              것은 아직 촬영 전이라 결과가 없다. **칸은 둔다** — 없애면
              「이 건은 AI 를 안 돌린다」로 읽힌다 */}
          <section className="work-box">
            <header className="work-box-h">
              <h3>AI 참고 소견</h3>
              <span className="home-fill" />
              <span className="hcard-k">판정은 판독의가 합니다</span>
            </header>
            <p className="hcard-k">아직 없습니다 — 올린 뒤에 돕니다</p>
          </section>

          <div className="work-foot">
            <Take cfg={cfg} id={r.id} onTook={onTook} kind="fill"
                  label="집고 올리기" />
          </div>
        </>
      )}
    </Body>
  );
}

/* ── 330px — 지난 검사 / 이 환자의 이력 ───────────────────────
   같은 환자가 전에 무엇을 했는지. 판독은 늘 이전과 견주는 일이다(4.4).
   ⚠ 환자 번호를 모르면 못 부른다 — 그때는 칸을 비워 둔다 */
function Past({ cfg, row }) {
  const c = cfg.queue;
  const pid = row ? c.row(row).patientId : null;
  /* ⚠ **병리에는 timeline 이 없다.** api.js 의 path 에 그 줄이 안 열려
     있다(영상·유방외과만 있다). 새 경로는 안 파므로 그 과에서는 칸을
     비우고 무엇이 없어서 비었는지 적는다(8장) */
  const has = typeof cfg.api.timeline === "function";
  const line = useApi(
    () => (has && pid ? H.soft(cfg.api.timeline(pid)) : Promise.resolve([])),
    [has, pid]);
  const rows = [...H.rows(line.data)].reverse();

  return (
    <section className="work-hist">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>{c.pastTitle}</b>
        <em>{rows.length}</em>
      </header>
      <div className="work-hist-b">
        {rows.length === 0
          ? (
            <p className="hcard-k hpad">
              {has ? "아직 없습니다" : "이 과에는 이력을 부르는 경로가 없습니다"}
            </p>
          )
          : rows.map((r, i) => (
            <article className="work-ev" key={`${r.at}-${i}`}>
              <div className="work-ev-h">
                <time>{H.day(r.at)}</time>
                <Chip>{r.type}</Chip>
              </div>
              {r.detail && <p>{r.detail}</p>}
            </article>
          ))}
      </div>
    </section>
  );
}

/* ── 248px — 상용구 ──────────────────────────────────────────
   ⚠ **서버가 주는 값이 아니다.** 상용구를 저장하는 경로가 없다 — 과마다
     다른 글이라 dept 설정에 박아 뒀다(8장에 적는다) */
function Phrases({ items = [] }) {
  return (
    <section className="work-say">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>상용구</b>
      </header>
      <div className="work-say-b">
        {items.length === 0
          ? <p className="hcard-k hpad">아직 없습니다</p>
          : items.map(([group, list]) => (
            <div className="work-grp" key={group}>
              <span className="work-grp-k">{group}</span>
              {list.map((it) => <p className="work-p" key={it}>{it}</p>)}
            </div>
          ))}
      </div>
    </section>
  );
}
