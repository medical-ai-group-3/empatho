import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Body, Empty } from "../lib/Body";
import { Btn, Page } from "../lib/Page";
import { Chip, Locked, useCan } from "../lib/Parts";
import { Filters, applyFilters, useFilterParams } from "../lib/Filters";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import { go } from "../nav";
import { ERR } from "../api";
import { eventDetail } from "../codes";
import * as H from "../dept/home";

/* 1장 · 대기 큐 — `docs/mockup/Radiology.html` · `Pathology.html`
 * ════════════════════════════════════════════════════════════════
 *
 *   ┌ 300px ──┬ 1fr ──────────────────┬ 330px ──┐
 *   │ 대기 큐  │ 환자 머리 · [집기]      │ 지난 검사│
 *   │  거르기  │ 이번 검사 / 이 검체    │ 이 환자의│
 *   │  1 …     │  (의뢰 질문이 맨 위)   │   이력   │
 *   │ [다음 건]│                        │  (누르면 │
 *   │          │                        │   새 탭) │
 *   └──────────┴────────────────────────┴─────────┘
 *
 * 가운데만 과마다 다르고 나머지는 제목만 바뀐다. 그래서 껍데기 이름이
 * `work-` 다(hospital.css) — 유방외과·영상·병리 셋이 나눠 쓴다.
 *
 * ⚠ 09-28 — **상용구 칸과 「AI 참고 소견」 칸을 뺐다**(과 설정으로 켠다:
 *   queue.phrasesCol · queue.aiNote). 상용구는 소견을 쓰는 판독 화면의
 *   일이고, AI 칸은 큐에서는 늘 「아직 없습니다」였다 — 촬영 전이라 AI 가
 *   돌 수가 없다. 늘 빈 칸은 읽을 것 없이 자리만 먹는다.
 *
 * **여기서 하지 않는 일**
 *   · 순서 바꾸기 — 순번은 표시 전용이다. 여럿이 보는 큐라 내가 끌어
 *     옮기면 나만 다른 화면을 보게 된다. 거르기(모달리티 · 목적)는 한다 —
 *     순서는 그대로 두고 안 볼 것만 가린다
 *   · 반려 — 검체나 오더가 이상한지 시스템이 판단할 수 없다
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

  /* 고른 줄은 주소에 적는다. 홈의 대기 카드가 ?pick= 을 붙여 보내므로
     「그 줄을 눌렀는데 다른 것이 열려 있다」가 안 된다. 목록 화면
     (screens/List.jsx)과 같은 방식이다 — 뒤로 와도 살아남는다. */
  const [params, setParams] = useSearchParams();
  const raw = params.get("pick");
  const pick = raw == null ? null : (/^\d+$/.test(raw) ? Number(raw) : raw);
  const setPick = (id) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    if (id == null) next.delete("pick");
    else next.set("pick", String(id));
    return next;
  }, { replace: true });
  const [fv, setFv] = useFilterParams(c.filters);

  /* 남이 집어 가면 줄어든다. 가만히 두면 화면이 거짓말을 한다.
     ⚠ **reload(true) 다** — 그냥 reload() 면 7초마다 화면이 「불러오는
       중」으로 돌아가 보고 있던 것이 통째로 사라졌다 온다 */
  useEffect(() => {
    const t = setInterval(() => again(true), POLL_MS);
    return () => clearInterval(t);
  }, [again]);

  const all = H.rows(list.data);
  const rows = applyFilters(all, c.filters, fv);
  const picked = rows.some((r) => cfg.queue.row(r).id === pick)
    ? pick : (rows[0] ? cfg.queue.row(rows[0]).id : null);
  const cur = rows.find((r) => cfg.queue.row(r).id === picked) ?? null;

  function took(goId, orderId) {
    nav(cfg.go.upload(goId), orderId ? { state: { orderId } } : undefined);
  }

  const say = c.phrasesCol === true;
  return (
    <Page className="wq-page" crumb={[cfg.name, c.title]} title={c.title}
          right={<Btn to={cfg.go.list()}>환자 목록</Btn>}>
      <div className={`work${say ? "" : " no-say"}`}>
        <Side c={c} state={list} rows={rows} total={all.length} pick={picked} onPick={setPick}
              cfg={cfg} onTook={took} fv={fv} setFv={setFv} />

        <div className="work-mid">
          {!cur
            ? <Empty title={all.length ? "조건에 맞는 항목이 없습니다" : c.emptyText} />
            : <Mid cfg={cfg} row={cur} onTook={took} />}
        </div>

        <Past cfg={cfg} row={cur} />
        {say && <Phrases items={c.phrases} />}
      </div>
    </Page>
  );
}

/* ── 왼쪽 300px — 대기 큐 ────────────────────────────────────── */
function Side({ c, state, rows, total, pick, onPick, cfg, onTook, fv, setFv }) {
  const next = rows[0] ? c.row(rows[0]) : null;
  return (
    <aside className="work-q">
      <header className="work-q-h">
        <h2>{c.listTitle} <em className="work-q-n">{rows.length === total ? total : `${rows.length} / ${total}`}</em></h2>
        <span className="hcard-k">도착 순 · 순서 고정</span>
        <Filters groups={c.filters} value={fv} onChange={setFv} />
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0 && <Empty title={total ? "조건에 맞는 항목이 없습니다" : c.emptyText} />}>
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
                  {/* 기다린 시간 — 요청 · 채취 시각에서 센다(dept/home.js waited) */}
                  {r.wait && <i title="기다린 시간">{r.wait}</i>}
                </span>
              </button>
            );
          })}
        </div>
      </Body>
      {next && (
        <footer className="work-q-f">
          <Take cfg={cfg} id={next.id} onTook={onTook} verb={c.takeVerb} label={c.nextLabel ?? "다음 건 담당하기"} />
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
function Take({ cfg, id, onTook, label, verb = "담당하기", kind = "line" }) {
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
          : (e.detail || "처리하지 못했습니다. 다시 시도해 주세요"));
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
      <span className="hcard-k">{verb === "접수" ? "접수하면" : "담당하면"} 내 목록으로 옮겨지고 다른 사람 목록에서 사라집니다</span>
      <Btn kind="fill" onClick={go} disabled={busy}>
        {busy ? "처리 중…" : verb}
      </Btn>
      <Btn onClick={() => setAsking(false)} disabled={busy}>취소</Btn>
    </span>
  );
}

/* ── 가운데 — 고른 건 ──────────────────────────────────────── */
function Mid({ cfg, row, onTook }) {
  const c = cfg.queue;
  const r = c.row(row);
  const one = useApi(() => cfg.api.detail(r.id), [r.id]);
  const d = one.data;
  /* 알레르기는 **머리에 한 번만** 띄운다 — 전에는 머리 · 경고줄 · 정보칸
     세 곳에 같은 말이 있었다 */
  const al = d ? H.allergyTag(d.contrast_allergy) : null;

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
            {al && (
              <span className="pb-warn" title={al.note ?? undefined}>
                <i aria-hidden="true">⚠</i><b>{al.label}</b>{al.note && ` · ${al.note}`}
              </span>
            )}
            <span className="home-fill" />
            {/* ⚠ 주소를 직접 적지 않는다 — 주소가 바뀌면 nav.js 만 고치면
                되게 해 둔 자리다 */}
            {d.patient_id && <Btn to={go.patient(d.patient_id)}>환자 기록</Btn>}
            {/* 집기는 머리에 둔다 — 아래에 두면 긴 검체 정보에 밀려 화면
                밖으로 나갔다(병리 1600×950 에서 스크롤해야 보였다) */}
            <Take key={r.id} cfg={cfg} id={r.id} onTook={onTook} kind="fill" verb={c.takeVerb}
                  label={c.takeLabel ?? "담당하기"} />
          </header>

          <section className="work-box">
            <header className="work-box-h">
              <h3>{c.detailTitle}</h3>
              <span className="home-fill" />
              {r.chip && <Chip tone={r.chipTone}>{r.chip}</Chip>}
            </header>
            {/* key — 사람을 바꾸면 접힘 상태도 새로 시작한다 */}
            <c.Detail key={r.id} d={d} cfg={cfg} />
          </section>

          {/* AI 칸은 과가 켤 때만(queue.aiNote) — 큐에서는 촬영 전이라
              늘 비어 있었다 */}
          {c.aiNote && (
            <section className="work-box">
              <header className="work-box-h">
                <h3>AI 참고 소견</h3>
                <span className="home-fill" />
                <span className="hcard-k">판정은 판독의가 합니다</span>
              </header>
              <p className="hcard-k">{c.aiNote}</p>
            </section>
          )}
        </>
      )}
    </Body>
  );
}

/* ── 330px — 지난 검사 / 이 환자의 이력 ───────────────────────
   같은 환자가 전에 무엇을 했는지. 판독은 늘 이전과 견주는 일이다(4.4).
   · 줄 아래 글은 codes.js eventDetail 로 — 「us」「4b」 같은 코드가 날것으로
     안 뜬다
   · 과가 거를 수 있다(queue.pastKeep) — 병리는 영상 · 병리 · 불일치만
   · 과가 갈 곳을 주면(queue.pastLink) 누른다 — **새 탭**으로 연다. 큐에서
     보던 줄과 고른 건을 잃지 않게
   ⚠ 환자 번호를 모르면 못 부른다 — 그때는 칸을 비워 둔다 */
function Past({ cfg, row }) {
  const c = cfg.queue;
  const pid = row ? c.row(row).patientId : null;
  const has = typeof cfg.api.timeline === "function";
  const line = useApi(
    () => (has && pid ? H.soft(cfg.api.timeline(pid)) : Promise.resolve([])),
    [has, pid]);
  const rows = [...H.rows(line.data)].filter(c.pastKeep ?? (() => true)).reverse();

  /* ⚠ opener 를 끊지 않는다(noopener 금지) — 로그인 토큰이 sessionStorage
     에 있어서, 여는 쪽과 이어진 탭이어야 복사되어 새 탭이 로그인 화면으로
     안 떨어진다 */
  const open = (to) => window.open(to, "_blank");

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
              {has ? "아직 없습니다" : "이 과에서는 이력을 볼 수 없습니다"}
            </p>
          )
          : rows.map((e, i) => {
            const to = c.pastLink?.(e) ?? null;
            const tx = eventDetail(e);
            return (
              <article className="work-ev" key={`${e.at}-${i}`}
                       {...(to ? {
                         role: "button", tabIndex: 0, title: "새 탭에서 판독 열기",
                         onClick: () => open(to),
                         onKeyDown: (ev) => { if (ev.key === "Enter") open(to); },
                       } : {})}>
                <div className="work-ev-h">
                  <time>{H.day(e.at)}</time>
                  <Chip>{e.type}</Chip>
                  {to && <><span className="home-fill" /><i className="work-ev-go" aria-hidden="true">↗</i></>}
                </div>
                {tx && <p>{tx}</p>}
              </article>
            );
          })}
      </div>
    </section>
  );
}

/* ── 248px — 상용구 (queue.phrasesCol 을 켠 과만) ─────────────
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
