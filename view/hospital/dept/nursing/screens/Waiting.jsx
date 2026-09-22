import { useEffect, useState } from "react";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, Locked } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import { DESK, go } from "../../../nav";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import * as H from "../../home";

/* 내원 대기 · 유방외과 배정 — `docs/mockup/Nursing-내원대기.html`
 * ════════════════════════════════════════════════════════════════
 *
 * **접수 화면의 아래 절반이다.** 화면 줄에서 뺐고(6.1) 접수 화면이 이걸
 * 통째로 끼워 쓴다 — 이 과에서 제일 많이 보이는 자리다.
 *
 *   ┌ 330px ───────┬ 1fr ─────────────────────┬ 380px ────────┐
 *   │ 내원한 대기   │ 고른 환자                 │ 금일 내원 예정 │
 *   │ 환자          │  방문 정보 │ 문진          ├───────────────┤
 *   │  1 …          │  ─────────────────────   │ 오늘 추적 콜   │
 *   │  2 …          │  유방외과 의사 배정        ├───────────────┤
 *   │               │  [검체 바인딩]  [보내기]   │ 검체 바인딩    │
 *   └───────────────┴──────────────────────────┴───────────────┘
 *
 * **왼쪽 줄을 누르면 가운데가 그 환자로 바뀐다.** 화면을 옮기지 않는다 —
 * 배정이 이 과의 주 업무라 고르고 보내는 것이 한 자리에서 끝나야 한다.
 *
 * ⚠ **순번은 표시 전용이다.** 원무가 접수한 순서 그대로고 끌어서 못 바꾼다.
 * ⚠ **경과 시간을 안 쓴다.** 목업 줄 끝의 `(61′)` 은 서버가 주지 않는다 —
 *   접수 시각만 적는다.
 * ⚠ **칸을 카드로 띄우지 않는다.** 상자 하나를 1px 선으로 가른다(4.5).
 * ⚠ **쪽 머리가 없다.** 접수 화면 안에 들어가므로 제목을 또 달지 않는다.
 */
export default function NursingWaiting({ cfg, embedded = false }) {
  /* 간호과는 원무 일까지 하는 한 과다 — **보는 것**은 과 열쇠 하나면 된다.
     쓰는 동작은 아래에서 제 열쇠로 그대로 잠근다 */
  if (!can(DESK)) {
    /* 끼워 넣은 자리에서는 쪽 머리를 또 달지 않는다 — 접수 화면이 이미
       제 머리를 그렸다. 잠긴 사정만 그 자리에 적는다 */
    const locked = <Locked what="내원 대기" need="nursing.waiting.view" />;
    return embedded ? locked : (
      <Page crumb={[cfg.name, "내원 대기"]} title="내원 대기">{locked}</Page>
    );
  }
  return <Inner cfg={cfg} embedded={embedded} />;
}

/* 몇 초마다 조용히 다시 불러온다. 깜빡이면 고른 환자가 사라진다 */
const POLL_MS = 7000;

function Inner({ cfg, embedded }) {
  const api = cfg.api;
  const [pick, setPick] = useState(null);
  const [tick, setTick] = useState(0);

  const arrived = useApi(() => api.waitingArrived(), [tick]);
  const booked = useApi(() => H.soft(api.scheduledToday()), []);
  const calls = useApi(() => H.soft(api.followups()), [tick]);
  const detail = useApi(
    () => (pick ? api.examOrder(pick) : Promise.resolve(null)), [pick, tick]);

  useEffect(() => {
    const t = setInterval(() => setTick((n) => n + 1), POLL_MS);
    return () => clearInterval(t);
  }, []);

  const rows = H.rows(arrived.data);
  const body = (
    <div className="nwait">
      <Queue state={arrived} rows={rows} pick={pick} onPick={setPick} />

      <div className="nwait-mid">
        {!pick
          ? <Empty title="왼쪽에서 한 사람을 고르세요" />
          : (
            <Body loading={detail.loading && !detail.data} error={detail.error}
                  onRetry={detail.reload}>
              {detail.data && (
                <Detail cfg={cfg} d={detail.data}
                        onDone={() => { setPick(null); setTick((n) => n + 1); }} />
              )}
            </Body>
          )}
      </div>

      <Side booked={booked} calls={calls} />
    </div>
  );

  return embedded ? body : (
    <Page crumb={[cfg.name, "내원 대기"]} title="내원 대기">{body}</Page>
  );
}

/* ── 왼쪽 330px — 내원한 대기 환자 ─────────────────────────────
 * 환자 줄은 세 줄이다(5.2).
 *
 *   박서연  47 · 여  [예약 · 결과 상담]
 *   P-2026-00418 · 09:05 접수
 *   문진 중                                    ← 어디까지 왔나
 *
 * ⚠ **셋째 줄에 검사 진행 점(`MG ● US ○ …`)을 못 찍는다.** 5.2 가 거기
 *   네 모달리티를 찍으라고 하지만 이 목록 응답에 그 값이 없다 — 열쇠가
 *   status · visit_type · visited_at · followup_id 넷뿐이다. 게다가 이
 *   큐는 **촬영 전 환자만** 모으므로 넷이 다 ○ 로 똑같아져서 줄끼리
 *   구분도 안 된다. 그래서 그 자리에 **서버가 준 status 를 그대로** 둔다.
 * ⚠ **status 를 옮겨 부르지 않는다.** 「문진 중」을 「문진 대기」로 바꿔
 *   적으면 서버가 단계를 하나 늘렸을 때 그 줄이 거짓말을 한다.
 */
function Queue({ state, rows, pick, onPick }) {
  return (
    <section className="nwait-q">
      <header className="bcol-h">
        <i className="hdot" aria-hidden="true" />
        <b>내원한 대기 환자</b>
        <em>{rows.total ?? rows.length}</em>
        <span className="home-fill" />
        <span className="hcard-k">접수 순 · 순서 고정</span>
      </header>
      <Body loading={state.loading && !state.data} error={state.error}
            onRetry={state.reload}
            empty={rows.length === 0 && <Empty title="내원한 대기 환자가 없습니다" />}>
        <div className="nwait-q-b">
          {rows.map((r, i) => {
            const id = r.exam_order_id ?? r.id;
            return (
              <article key={id} className={`nrow${id === pick ? " on" : ""}`}
                       role="button" tabIndex={0}
                       onClick={() => onPick(id)}
                       onKeyDown={(e) => { if (e.key === "Enter") onPick(id); }}>
                <i className="nrow-n">{i + 1}</i>
                <span className="nrow-tx">
                  <span className="nrow-1">
                    <b>{H.nameOf(r)}</b>
                    {H.who(r) && <span>{H.who(r)}</span>}
                    {r.visit_type && <Chip>{r.visit_type}</Chip>}
                  </span>
                  <span className="nrow-2">
                    {H.noOf(r) && <i>{H.noOf(r)}</i>}
                    {/* ⚠ 경과 시간이 아니라 접수 시각이다 */}
                    {H.at(r.visited_at) && <time>{H.at(r.visited_at)} 접수</time>}
                  </span>
                  <span className="nrow-3">
                    <span>{r.status ?? "단계를 못 받았습니다"}</span>
                    {r.followup_id && <span>추적 관찰 건</span>}
                  </span>
                </span>
              </article>
            );
          })}
        </div>
      </Body>
    </section>
  );
}

/* ── 가운데 — 고른 환자 ────────────────────────────────────────
 * 머리(누구인가) · 방문 정보 · 문진 · 유방외과 의사 배정 · 바닥 줄.
 *
 * ⚠ **문진은 읽기 전용이다.** 환자가 앱에서 낸 것을 그대로 본다 —
 *   항목이 환자마다 달라서 고정 입력칸으로 안 만든다.
 */
function Detail({ cfg, d, onDone }) {
  const api = cfg.api;
  const id = d.exam_order_id ?? d.id;
  const patientId = d.patient ?? d.patient_id;

  const full = useApi(
    () => (patientId ? H.soft(api.patient(patientId)) : Promise.resolve(null)),
    [patientId]);
  const p = full.data && !Array.isArray(full.data) ? full.data : null;

  const [note, setNote] = useState(d.order_note ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [modal, setModal] = useState(null);

  const mayNote = can("nursing.waiting.assign");
  const mayAssign = can("nursing.waiting.assign");
  const allergy = H.allergy(p ?? d);
  const answers = d.questionnaire?.answers ?? d.questionnaire ?? null;
  const qs = answers && typeof answers === "object" ? Object.entries(answers) : [];

  async function save() {
    setSaving(true);
    setMsg(null);
    try {
      await api.saveNote(id, note);
      setMsg("적어 두었습니다");
    } catch (e) { setMsg(e.detail || e.message); }
    finally { setSaving(false); }
  }

  const patient = {
    patient_id: patientId, name: H.nameOf(d), age: d.age, sex: d.sex,
    patient_number: H.noOf(d),
  };

  return (
    <>
      <header className="ndet-h">
        <span className="ndet-ava" aria-hidden="true">{H.nameOf(d)[0]}</span>
        <span className="ndet-who">
          <span className="ndet-1">
            <b>{H.nameOf(d)}</b>
            {H.who(d) && <span>{H.who(d)}</span>}
          </span>
          <span className="ndet-2">
            {[H.noOf(d), p?.pii?.birth_date,
              H.at(d.visited_at) && `${H.at(d.visited_at)} 접수`]
              .filter(Boolean).join(" · ")}
          </span>
        </span>
        <span className="home-fill" />
        {/* 경고는 환자 띠와 같은 모양을 쓴다 — 같은 뜻에 이름을 또 만들지 않는다 */}
        {allergy && <span className="pb-warn"><i aria-hidden="true">⚠</i>{allergy}</span>}
        {d.visit_type && <Chip>{d.visit_type}</Chip>}
      </header>

      <div className="ndet-b">
        <section className="ndet-box">
          <h3>방문 정보</h3>
          <dl className="kv">
            <div><dt>방문 구분</dt><dd>{d.visit_type ?? "—"}</dd></div>
            <div><dt>연락처</dt><dd>{p?.pii?.phone ?? "—"}</dd></div>
            <div><dt>알레르기</dt><dd>{allergy ?? "표시 없음"}</dd></div>
            {/* ⚠ 「지난 검사」는 이 응답에 없다. 환자 상세가 그 자리다 */}
            <div><dt>접수 메모</dt><dd>{d.order_note || "—"}</dd></div>
          </dl>
          <Btn to={go.patient(patientId)}>환자 상세</Btn>
        </section>

        <section className="ndet-box">
          <h3>문진{qs.length > 0 && <Chip>작성 완료</Chip>}</h3>
          {qs.length === 0
            ? <Empty title="받은 문진이 없습니다" />
            : (
              <dl className="kv">
                {qs.map(([k, v]) => (
                  <div key={k}><dt>{k}</dt><dd>{String(v)}</dd></div>
                ))}
              </dl>
            )}
        </section>

        <section className="ndet-box wide">
          <h3>간호 메모</h3>
          <textarea value={note} onChange={(e) => setNote(e.target.value)}
                    placeholder="인계할 내용" rows={2} disabled={!mayNote} />
          <div className="rowb">
            {msg && <span className="hcard-k">{msg}</span>}
            <Btn onClick={save} disabled={saving || !mayNote}>
              {saving ? "적는 중…" : "적어 두기"}
            </Btn>
          </div>
        </section>

        <Assign cfg={cfg} patient={patient} picked={d.assigned_to}
                may={mayAssign} onDone={onDone} />
      </div>

      <footer className="ndet-f">
        <Btn onClick={() => setModal("specimen")}>검체 바인딩</Btn>
        <span className="home-fill" />
        {/* ⚠ 되돌릴 수 없다 — 9장이 남기라고 한 두 문구 중 하나다 */}
        <span className="hcard-k">보내면 그 의사의 「내 환자」에만 뜹니다</span>
      </footer>

      {modal === "specimen" && (
        <SpecimenBindingModal patient={patient} onClose={() => setModal(null)}
                              onDone={() => setModal(null)} />
      )}
    </>
  );
}

/* ── 유방외과 의사 배정 ────────────────────────────────────────
 * 목업은 라디오 카드다 — 고르면 그 자리에서 보낸다. 팝업을 띄우지 않는다.
 *
 * ⚠ **되돌릴 수 없다.** 고른 사람이 주치의가 되고 그 뒤로는 그 의사의
 *   화면에만 뜬다. 그래서 고르는 것과 보내는 것을 두 걸음으로 나눈다.
 * ⚠ **「지금 대기 n명」은 못 적는다.** 목록 응답에 primary_staff 가 없어
 *   누가 누구 환자인지 모른다(8장 10번).
 */
function Assign({ cfg, patient, picked, may, onDone }) {
  const staff = useApi(() => H.soft(cfg.api.surgeons()), []);
  const people = H.rows(staff.data);
  const [who, setWho] = useState(picked ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function send() {
    if (!who) return;
    setBusy(true);
    setErr(null);
    try {
      await cfg.api.assignSurgeon(patient.patient_id, who);
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  return (
    <section className="ndet-box wide">
      <h3>유방외과 의사 배정</h3>
      {people.length === 0
        ? <Empty title="의사 명단을 못 불렀습니다" />
        : (
          <div className="ndocs">
            {people.map((s) => {
              const id = s.staff_id ?? s.id;
              return (
                <button type="button" key={id} disabled={!may}
                        className={`ndoc${id === who ? " on" : ""}`}
                        aria-pressed={id === who}
                        onClick={() => setWho(id)}>
                  <i aria-hidden="true" />
                  <b>{s.full_name ?? s.name ?? `직원 ${id}`}</b>
                </button>
              );
            })}
          </div>
        )}
      {err && <p className="note err">{err}</p>}
      <div className="rowb">
        <Btn kind="fill" onClick={send} disabled={!who || busy || !may}>
          {busy ? "보내는 중…" : "유방외과 큐로 보내기"}
        </Btn>
      </div>
    </section>
  );
}

/* ── 오른쪽 380px — 곁에 두고 보는 것 셋 ───────────────────────
 * 금일 내원 예정 · 오늘 추적 콜 · 검체 바인딩 필요.
 */
function Side({ booked, calls }) {
  const waiting = H.rows(booked.data);
  const due = H.rows(calls.data).filter((r) => H.dueBucket(r.due_at) === "today");

  return (
    <div className="nwait-side">
      <section className="nside">
        <header className="bcol-h">
          <i className="hdot ring" aria-hidden="true" />
          <b>금일 내원 예정</b>
          <em>{waiting.total ?? waiting.length}</em>
          <span className="home-fill" />
          <span className="hcard-k">아직 안 온 사람</span>
        </header>
        <div className="nside-b">
          {waiting.length === 0
            ? <p className="hcard-k hpad">남은 예약이 없습니다</p>
            : waiting.map((r) => (
              <p className="nside-row" key={r.exam_order_id ?? r.id}>
                <time>{H.at(r.scheduled_at)}</time>
                <b>{H.nameOf(r)}</b>
                {H.who(r) && <span>{H.who(r)}</span>}
                <span className="home-fill" />
                {r.visit_type && <Chip>{r.visit_type}</Chip>}
              </p>
            ))}
        </div>
      </section>

      <section className="nside">
        <header className="bcol-h">
          <i className="hdot ring" aria-hidden="true" />
          <b>오늘 추적 콜</b>
          <em>{due.length}</em>
          <span className="home-fill" />
          <Btn to={go.nursing.followups()}>추적 관리</Btn>
        </header>
        <div className="nside-b">
          {due.length === 0
            ? <p className="hcard-k hpad">오늘 걸 콜이 없습니다</p>
            : due.map((r) => (
              <p className="nside-row" key={r.followup_id ?? `c-${r.patient}`}>
                <b>{H.nameOf(r)}</b>
                <span>{r.round_no}회차</span>
                <span className="home-fill" />
                {r.call_result && <Chip>{r.call_result}</Chip>}
              </p>
            ))}
        </div>
      </section>

      <section className="nside">
        <header className="bcol-h">
          <i className="hdot ring" aria-hidden="true" />
          <b>검체 바인딩 필요</b>
        </header>
        {/* ⚠ **셀 수가 없다.** 「채취는 끝났는데 병변에 연결 안 된 검체」를
            거르는 경로가 서버에 없다 — 병리 큐는 이미 바인딩된 것만 준다
            (status=bound). 칸은 두고 무엇이 없어서 비었는지 적는다 */}
        <p className="hcard-k hpad">
          아직 못 셉니다 — 연결 안 된 검체를 거르는 경로가 없습니다.
          바인딩은 환자를 고른 뒤 아래 [검체 바인딩] 으로 합니다.
        </p>
      </section>
    </div>
  );
}
