import { useEffect, useId, useRef, useState } from "react";
import { breast as api } from "../../../api";
import { DUR_TYPE, ROUTE, label } from "../../../codes";
import { FREQ, durSex, emptyDrug, freqOf, HHMM, ingredientHints, ingredientOf, norm, routeOf, sorted, timesProblem } from "../rx";
import RxHandout from "./RxHandout";

/* ⑥ 처방 — 치료 방침 화면에서 떼어 냈다(09-28).
 *
 * 서버 계약(core/serializers/prescription.py PrescriptionDrugRowSerializer):
 *   { name, ingredient?, dose, times: ["HH:MM", …], days ≥ 1, route?, form?,
 *     purpose?, how?, watch? }
 *   route ∈ codes.js ROUTE · form 은 제형 글(「정제」). 둘 다 빈 칸이면 보내지 않는다.
 *   times 는 HH:MM · 겹침 없음 · 하나 이상. 복약 기록(medication_log.slot_time)이
 *   이 값을 회차 열쇠로 쓴다 — 「아침」 같은 말이 섞이면 같은 회차인지 모른다.
 *
 * ⚠ 09-28 — 복용 시간을 **글로 적던 칸**을 없앴다. 「09:00, 19:00」을 손으로
 *   치다가 「9시」 「09:00,19:00 」처럼 어긋나 서버가 거절했다. 이제 복용 횟수
 *   (QD · BID · TID · QID · HS)를 고르면 기본 시각이 서고, 시각은 시계 칸으로만
 *   고친다. 회차를 더하고 뺄 수 있다.
 * ⚠ 필요시(PRN)는 두지 않았다 — 서버가 시각 하나 이상을 요구해서(allow_empty
 *   =False) 「시각 없는 약」을 받을 길이 없다. 필요시 약은 알림 받을 시각을 하나
 *   두고 복용 안내에 적는다.
 * ⚠ purpose · how · watch 는 e약은요에서 **채우지 않는다**(core/api/drugs.py
 *   머리말 — 약전 문장을 설명칸에 넣는 순간 우리가 하는 의학적 조언이 된다).
 *   약 이름 · 성분명만 제안한다. */

/* 다음 회차 시각 — 마지막 시각 + 4시간, 겹치면 한 시간씩 민다 */
function nextSlot(times) {
  const last = sorted(times.filter((t) => HHMM.test(t))).at(-1);
  let h = last ? (Number(last.slice(0, 2)) + 4) % 24 : 9;
  for (let i = 0; i < 24; i += 1) {
    const t = `${String(h).padStart(2, "0")}:00`;
    if (!times.includes(t)) return t;
    h = (h + 1) % 24;
  }
  return "12:00";
}

/* 복용 횟수 + 시각. 시각은 시계 칸(<input type="time">)으로만 고친다 */
export function TimesField({ times, onChange, idPrefix }) {
  const freq = freqOf(times);
  const problem = times.length ? timesProblem(times) : null;
  const set = (i, v) => onChange(times.map((t, j) => (j === i ? v : t)));
  return (
    <div className="rx-times-field">
      <div className="rx-freq" role="radiogroup" aria-label="복용 횟수">
        {FREQ.map((f) => (
          <button type="button" key={f.k} role="radio" aria-checked={freq === f.k}
                  className={`bf-chip${freq === f.k ? " on" : ""}`}
                  onClick={() => onChange([...f.times])}>
            {f.label} <small>{f.k}</small>
          </button>
        ))}
        {times.length > 0 && !freq && <span className="rx-freq-own">직접 지정 · 1일 {times.length}회</span>}
      </div>
      {times.length > 0 && (
        <ol className="rx-times" aria-label="복용 시각">
          {times.map((t, i) => (
            <li key={i} className="rx-time">
              <label htmlFor={`${idPrefix}-t${i}`}>{i + 1}회</label>
              <input id={`${idPrefix}-t${i}`} type="time" step={300} required value={t}
                     aria-invalid={!HHMM.test(t) || times.indexOf(t) !== i}
                     onChange={(e) => set(i, e.target.value)} />
              <button type="button" className="rx-time-x" aria-label={`${i + 1}회 시각 삭제`}
                      onClick={() => onChange(times.filter((_, j) => j !== i))}>×</button>
            </li>
          ))}
          <li>
            <button type="button" className="edit-btn" onClick={() => onChange([...times, nextSlot(times)])}>
              + 시각 추가
            </button>
          </li>
        </ol>
      )}
      {problem && <span className="err" role="alert">{problem}</span>}
    </div>
  );
}

/* 자동완성 목록 한 벌 — 약 이름 · 성분명이 같이 쓴다 */
function SuggestList({ id, items, active, onPick, onHover, render, tail = null }) {
  return (
    <ul className="drug-suggest-list" id={id} role="listbox">
      {items.map((item, i) => (
        <li key={i} id={`${id}-${i}`} role="option" aria-selected={i === active}
            className={i === active ? "on" : undefined}
            /* blur 보다 먼저 잡아야 목록이 닫히기 전에 고른다 */
            onMouseDown={(e) => { e.preventDefault(); onPick(item); }}
            onMouseEnter={() => onHover(i)}>
          {render(item)}
        </li>
      ))}
      {tail}
    </ul>
  );
}

function useListKeys(items, open, setOpen, choose) {
  const [active, setActive] = useState(-1);
  function onKeyDown(e) {
    if (!open || !items.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault(); setActive((i) => (i + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault(); setActive((i) => (i <= 0 ? items.length : i) - 1);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault(); choose(items[active]); setActive(-1);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }
  return { active, setActive, onKeyDown };
}

/* 약 이름 칸 + 자동완성(GET /drugs — 식약처 e약은요).
 *
 * ⚠ 목록에 없는 약도 그대로 적을 수 있어야 한다 — 원내 조제약·신약은
 *   e약은요에 없다. 그래서 고르지 않아도 입력값이 곧 약 이름이다.
 * ⚠ 키가 없는 배포본은 503 이다 — 한 줄로 알리고 손으로 적게 둔다.
 * ⚠ 늦게 온 응답이 새 응답을 덮지 않게 요청마다 번호를 매긴다.
 * onResults — 받은 품목들. 성분명 칸이 괄호 속 성분을 제안하는 데 쓴다. */
export function DrugNameInput({ value, onChange, onPick, onResults, id }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState(null);
  const [result, setResult] = useState({ q: "", items: [], error: null });
  const seq = useRef(0);
  const report = useRef(onResults);
  useEffect(() => { report.current = onResults; });

  const q = value.trim();
  const searching = q.length >= 2 && q !== picked;

  useEffect(() => {
    if (!searching) { seq.current += 1; return undefined; }
    const n = ++seq.current;
    const timer = setTimeout(async () => {
      try {
        const res = await api.drugs(q);
        if (n !== seq.current) return;
        const items = res?.items ?? [];
        setResult({ q, items, error: null });
        report.current?.(items);
      } catch (e) {
        if (n !== seq.current) return;
        setResult({ q, items: [], error: e.status === 503
          ? "지금은 약 검색을 사용할 수 없습니다. 약 이름을 직접 입력해 주세요."
          : "약 검색에 실패했습니다. 약 이름을 직접 입력해 주세요." });
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [q, searching]);

  const items = searching ? result.items : [];
  const loading = searching && result.q !== q;
  const error = searching && result.q === q ? result.error : null;

  function choose(item) {
    setPicked(item.name);
    onPick(item);
    setOpen(false);
  }
  const keys = useListKeys(items, open, setOpen, choose);
  const showList = open && searching && (items.length > 0 || loading);

  return (
    <div className="drug-suggest">
      <input id={id} role="combobox" aria-expanded={showList} aria-controls={listId}
        aria-autocomplete="list" autoComplete="off"
        aria-activedescendant={keys.active >= 0 ? `${listId}-${keys.active}` : undefined}
        value={value}
        onChange={(e) => { setPicked(null); setOpen(true); keys.setActive(-1); onChange(e.target.value); }}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={keys.onKeyDown}
        placeholder="두 글자 이상 입력하면 약을 찾습니다" />
      {showList && (
        <SuggestList id={listId} items={items} active={keys.active} onPick={choose}
          onHover={keys.setActive}
          render={(item) => (
            <>
              <span className="drug-suggest-name">{item.name}</span>
              {item.maker && <span className="drug-suggest-maker">{item.maker}</span>}
            </>
          )}
          tail={loading && !items.length ? <li className="drug-suggest-empty">찾는 중…</li> : null} />
      )}
      {error && <span className="err">{error}</span>}
    </div>
  );
}

/* 성분명 칸 + 제안. 적은 글자가 곧 값이다(목록 밖 성분도 적는다) */
export function IngredientInput({ value, onChange, hints, id }) {
  const listId = useId();
  const [open, setOpen] = useState(false);
  const items = ingredientHints(value, hints);
  const exact = items.length === 1 && norm(items[0].ko) === norm(value);
  function choose(item) { onChange(item.ko); setOpen(false); }
  const keys = useListKeys(items, open, setOpen, choose);
  const showList = open && items.length > 0 && !exact;
  return (
    <div className="drug-suggest">
      <input id={id} role="combobox" aria-expanded={showList} aria-controls={listId}
        aria-autocomplete="list" autoComplete="off"
        aria-activedescendant={keys.active >= 0 ? `${listId}-${keys.active}` : undefined}
        value={value}
        onChange={(e) => { setOpen(true); keys.setActive(-1); onChange(e.target.value); }}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={keys.onKeyDown}
        placeholder="예: 레트로졸 — 누르면 추천 약 목록이 표시됩니다" />
      {showList && (
        <SuggestList id={listId} items={items} active={keys.active} onPick={choose}
          onHover={keys.setActive}
          render={(item) => (
            <>
              <span className="drug-suggest-name">{item.ko}</span>
              {(item.en || item.from) && (
                <span className="drug-suggest-maker">{[item.en, item.from].filter(Boolean).join(" · ")}</span>
              )}
            </>
          )} />
      )}
    </div>
  );
}

/* 약 이름으로 투여 경로 · 제형을 짐작해 **빈 칸에만** 넣는다 */
function fillRoute(drug, name) {
  const g = routeOf(name);
  if (!g || (drug.route && drug.form.trim())) return drug;
  return { ...drug, route: drug.route || g.route, form: drug.form.trim() ? drug.form : g.form };
}

/* 성분명 칸 → DUR 에 보낼 성분들. 복합제(「트라마돌염산염 · 아세트아미노펜」)는
   쪼갠다 — 한 덩어리로 보내면 서버가 어느 성분인지 못 찾는다 */
function durIngredients(drugs) {
  const out = drugs.flatMap((d) => d.ingredient.split(/\s*[·,/+]\s*/))
    .map((s) => s.trim()).filter(Boolean);
  return [...new Set(out)].sort();
}

/* DUR 점검(POST /drugs/dur). 성분 묶음이 바뀌면 600ms 뒤에 다시 묻는다.
 * ⚠ 늦게 온 응답이 새 묶음의 결과를 덮지 않게 요청마다 번호를 매긴다.
 * ⚠ 묶음이 바뀐 뒤 답이 오기 전에는 「점검 중」이다 — 옛 결과를 새 묶음의
 *   결과처럼 보이면 금기가 걸린 약을 더하고도 「걸린 항목 없음」을 본다. */
function useDur(ingredients, patient) {
  const key = ingredients.join("\u0001");
  const age = patient?.age ?? null;
  const sex = durSex(patient?.sex);
  const [res, setRes] = useState({ key: null });
  const [again, setAgain] = useState(0);
  const seq = useRef(0);

  useEffect(() => {
    if (!key) { seq.current += 1; return undefined; }
    const n = ++seq.current;
    const timer = setTimeout(async () => {
      try {
        const data = await api.dur({ ingredients: key.split("\u0001"), age, sex });
        if (n === seq.current) setRes({ key, status: "ok", data: data ?? {} });
      } catch (e) {
        if (n !== seq.current) return;
        setRes({ key, status: e.status === 503 || e.code === "DUR_UNAVAILABLE" ? "off" : "fail" });
      }
    }, 600);
    return () => clearTimeout(timer);
  }, [key, age, sex, again]);

  if (!key) return { status: "idle" };
  if (res.key !== key) return { status: "loading" };
  return { ...res, retry: () => { setRes({ key: null }); setAgain((x) => x + 1); } };
}

const durPair = (a) => (a.with ? `${a.ingredient} + ${a.with}` : a.ingredient);
const durSig = (alerts) => alerts.map((a) => `${a.type}|${a.ingredient}|${a.with ?? ""}`).join(";");

/* DUR 결과 — 저장 단추 바로 위. 금기는 채움 한 덩어리, 주의는 조용한 목록.
 * ⚠ 금기여도 **막지 않는다.** 처방은 의사가 정한다 — 대신 확인 표시를
 *   받아야 저장된다(말없이 지나가지 않게). 경고 목록이 바뀌면 표시를 푼다. */
function DurPanel({ dur, missing, acked, onAck }) {
  if (dur.status === "idle") {
    return missing.length > 0
      ? <p className="rx-dur-line">DUR 점검은 성분명으로 합니다 — 성분명을 적으면 점검합니다</p>
      : null;
  }
  const data = dur.data ?? {};
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const taboos = alerts.filter((a) => a.level === "taboo");
  const cautions = alerts.filter((a) => a.level !== "taboo");
  const checked = Array.isArray(data.checked) ? data.checked : [];
  const failed = Array.isArray(data.failed) ? data.failed : [];
  return (
    <section className="rx-dur" aria-label="DUR 점검" aria-live="polite">
      {dur.status === "loading" && <p className="rx-dur-line">DUR 점검 중…</p>}
      {dur.status === "off" && <p className="rx-dur-line">DUR 점검을 쓸 수 없습니다 — 서버에 키가 없습니다</p>}
      {dur.status === "fail" && (
        <p className="rx-dur-line">
          DUR 점검에 실패했습니다
          <button type="button" className="rx-dur-retry" onClick={dur.retry}>다시 시도</button>
        </p>
      )}
      {dur.status === "ok" && (
        <>
          {taboos.length > 0 && (
            <div className="rx-dur-taboo" role="alert">
              <b className="rx-dur-h"><span aria-hidden="true">⚠</span> 금기 {taboos.length}건</b>
              <ul>
                {taboos.map((a, i) => (
                  <li key={i}>
                    <b>{durPair(a)} — {label(DUR_TYPE, a.type)}</b>
                    {(a.detail || a.message) && <span>{a.detail || a.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {cautions.length > 0 && (
            <div className="rx-dur-caution">
              <b className="rx-dur-h">주의 {cautions.length}건</b>
              <ul>
                {cautions.map((a, i) => (
                  <li key={i}>
                    <b>{durPair(a)} — {label(DUR_TYPE, a.type)}</b>
                    {(a.detail || a.message) && <span>{a.detail || a.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {!alerts.length && (
            <p className="rx-dur-line">DUR 점검: 걸린 항목이 없습니다 (성분 {checked.length}개 확인)</p>
          )}
          {(data.partial || failed.length > 0) && (
            <p className="rx-dur-line">
              일부 점검을 하지 못했습니다{failed.length ? ` — ${failed.map((f) => label(DUR_TYPE, f)).join(" · ")}` : ""}
            </p>
          )}
          {taboos.length > 0 && (
            <label className="check-row rx-dur-ack">
              <input type="checkbox" checked={acked} onChange={(e) => onAck(e.target.checked)} />
              금기를 확인했고 그래도 처방합니다
            </label>
          )}
        </>
      )}
      {missing.length > 0 && (
        <p className="rx-dur-line">성분명이 없어 점검하지 못한 약: {missing.join(" · ")}</p>
      )}
      {dur.status === "ok" && (data.source || data.disclaimer) && (
        <p className="rx-dur-src">{[data.source, data.disclaimer].filter(Boolean).join(" · ")}</p>
      )}
    </section>
  );
}

/* ⑥ 처방. 저장된 처방을 **약까지** 먼저 보여 준다 */
export default function PrescriptionDraft({ patient, report, saved, blocked }) {
  const [drugs, setDrugs] = useState([emptyDrug()]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [writing, setWriting] = useState(false);
  const [handout, setHandout] = useState(null);
  const [ack, setAck] = useState({ sig: null, on: false });
  const baseId = useId();
  const reportId = report?.report_id ?? null;
  const list = saved.data ?? [];

  function change(index, key, value) {
    setDrugs((rows) => rows.map((drug, i) => (i === index ? { ...drug, [key]: value } : drug)));
  }

  /* 자동완성에서 고른 약. 이름과, 비어 있으면 성분명까지만 채운다 —
     설명칸(purpose·how·watch)은 처방한 사람이 쓰는 자리라 건드리지 않는다 */
  function pick(index, item) {
    setDrugs((rows) => rows.map((drug, i) => (i !== index ? drug : fillRoute({
      ...drug,
      name: item.name,
      ingredient: drug.ingredient.trim() ? drug.ingredient : ingredientOf(item.name),
    }, item.name))));
  }

  /* 고르지 않고 손으로 적은 이름도 칸을 떠날 때 한 번 짐작한다.
     ⚠ 치는 도중에 짐작하면 「…주」까지 친 순간 주사로 굳는다 */
  function inferRoute(index) {
    setDrugs((rows) => rows.map((drug, i) => (i !== index ? drug : fillRoute(drug, drug.name))));
  }

  function heard(index, items) {
    const found = [...new Set(items.map((it) => ingredientOf(it.name)).filter(Boolean))];
    change(index, "hints", found);
  }

  function remove(index) {
    setDrugs((rows) => (rows.length === 1 ? rows : rows.filter((_, i) => i !== index)));
  }

  /* 조사까지 붙여 둔다 — 「약 이름을(를)」처럼 괄호로 둘 다 적지 않게 */
  const rowProblem = (drug) => !drug.name.trim() ? "약 이름을"
    : !drug.dose.trim() ? "1회 복용량을"
    : timesProblem(drug.times) ? "복용 시각을"
    : !(Number(drug.days) > 0) ? "처방 일수를" : null;
  const firstProblem = drugs.map(rowProblem).find(Boolean) ?? null;

  const dur = useDur(writing ? durIngredients(drugs) : [], patient);
  const durMissing = drugs.filter((d) => d.name.trim() && !d.ingredient.trim()).map((d) => d.name.trim());
  const taboos = dur.status === "ok" ? (dur.data?.alerts ?? []).filter((a) => a.level === "taboo") : [];
  const sig = durSig(taboos);
  const acked = ack.on && ack.sig === sig;   /* 목록이 바뀌면 표시가 저절로 풀린다 */
  const hold = dur.status === "loading" ? "DUR 점검이 끝나면 저장할 수 있습니다"
    : taboos.length && !acked ? "금기 확인에 표시해 주세요" : null;
  const valid = Boolean(reportId) && !firstProblem && !hold;

  async function save() {
    if (!valid || saving || blocked) return;
    const cleaned = drugs.map((drug) => ({
      name: drug.name.trim(), ingredient: drug.ingredient.trim(),
      dose: drug.dose.trim(),
      times: sorted(drug.times),
      days: Number(drug.days),
      ...(drug.route ? { route: drug.route } : null),
      ...(drug.form.trim() ? { form: drug.form.trim() } : null),
      purpose: drug.purpose.trim(),
      how: drug.how.trim(), watch: drug.watch.trim(),
    }));
    setSaving(true); setMsg(null);
    try {
      await api.prescribe(patient.patient_id, { report_id: reportId, content: { drugs: cleaned } });
      setDrugs([emptyDrug()]);
      setAck({ sig: null, on: false });
      setWriting(false);
      setMsg("처방을 저장했습니다. 환자 앱의 복약 관리에서 확인할 수 있습니다.");
      saved.reload(true);
    } catch (e) {
      setMsg(e.detail || e.message || "처방을 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="prescription-draft">
      <p className="meta">저장 즉시 환자 앱의 복약 관리에 표시됩니다. 처방 일수는 약마다 따로 셉니다.</p>

      {saved.error && <p className="warnline">저장된 처방을 불러오지 못했습니다.</p>}
      {list.length > 0 && (
        <ul className="bf-rx">
          {list.map((rx, i) => (
            <li key={rx.prescription_id ?? i}>
              <span className="bf-rx-h">
                <b>{String(rx.prescribed_at ?? rx.created_at ?? "").slice(0, 10) || "날짜 없음"}</b>
                {rx.prescriber && <span className="note">{rx.prescriber}</span>}
                <button type="button" className="btn ghost sm rx-handout-open"
                        onClick={() => setHandout(rx)}>복약 안내문</button>
              </span>
              {(rx.content?.drugs ?? []).map((d, j) => {
                const times = Array.isArray(d.times) ? d.times : [];
                const f = freqOf(times);
                return (
                  <span className="bf-rx-d" key={j}>
                    <b>{d.name}</b>
                    {[d.ingredient, [label(ROUTE, d.route), d.form].filter(Boolean).join(" ") || null, d.dose,
                      times.length ? `${f ? `${FREQ.find((x) => x.k === f).label}(${f})` : `1일 ${times.length}회`} ${times.join(" · ")}` : d.times,
                      d.days ? `${d.days}일` : null, d.purpose].filter(Boolean).join(" · ")}
                  </span>
                );
              })}
            </li>
          ))}
        </ul>
      )}
      {blocked && <p className="note">판정 불일치(②)를 처분한 뒤 처방할 수 있습니다.</p>}
      {!blocked && !reportId && <p className="note">종합 리포트(③)가 생성된 뒤 처방을 저장할 수 있습니다.</p>}

      {!writing ? (
        <div className="card-foot split">
          <span className="note">{msg ?? (list.length ? `저장된 처방 ${list.length}건` : "아직 처방이 없습니다 — 약이 필요 없으면 건너뛰어도 됩니다")}</span>
          <button className="btn ghost" onClick={() => setWriting(true)} disabled={blocked || !reportId}>
            + 새 처방
          </button>
        </div>
      ) : (
        <>
          {drugs.map((drug, index) => {
            const fid = `${baseId}-${index}`;
            return (
              <div className="prescription-drug" key={index} data-rx-row={index}>
                <div className="prescription-drug-head">
                  <b>약 {index + 1}</b>
                  {drugs.length > 1 && <button className="edit-btn" onClick={() => remove(index)}>삭제</button>}
                </div>
                <div className="prescription-grid rx-grid4">
                  <div className="field rx-wide" onBlur={() => inferRoute(index)}>
                    <label htmlFor={`${fid}-name`}>약 이름 <span className="req">*</span></label>
                    <DrugNameInput id={`${fid}-name`} value={drug.name}
                      onChange={(value) => change(index, "name", value)}
                      onPick={(item) => pick(index, item)}
                      onResults={(items) => heard(index, items)} />
                  </div>
                  <div className="field rx-wide">
                    <label htmlFor={`${fid}-ing`}>성분명</label>
                    <IngredientInput id={`${fid}-ing`} value={drug.ingredient} hints={drug.hints}
                      onChange={(value) => change(index, "ingredient", value)} />
                  </div>
                  <div className="field">
                    <label htmlFor={`${fid}-dose`}>1회 복용량 <span className="req">*</span></label>
                    <input id={`${fid}-dose`} value={drug.dose} onChange={(e) => change(index, "dose", e.target.value)} placeholder="예: 1정" />
                  </div>
                  <div className="field">
                    <label htmlFor={`${fid}-days`}>처방 일수 <span className="req">*</span></label>
                    <input id={`${fid}-days`} type="number" min="1" value={drug.days} onChange={(e) => change(index, "days", e.target.value)} placeholder="일수" />
                  </div>
                  <div className="field">
                    <label htmlFor={`${fid}-route`}>투여 경로</label>
                    <select id={`${fid}-route`} value={drug.route} onChange={(e) => change(index, "route", e.target.value)}>
                      <option value="">선택 안 함</option>
                      {Object.entries(ROUTE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor={`${fid}-form`}>제형</label>
                    <input id={`${fid}-form`} value={drug.form} onChange={(e) => change(index, "form", e.target.value)} placeholder="예: 정제" />
                  </div>
                </div>
                <div className="field">
                  <label>복용 횟수 · 시각 <span className="req">*</span></label>
                  <TimesField idPrefix={fid} times={drug.times} onChange={(times) => change(index, "times", times)} />
                </div>
                <div className="field">
                  <label htmlFor={`${fid}-purpose`}>처방 목적</label>
                  <input id={`${fid}-purpose`} value={drug.purpose} onChange={(e) => change(index, "purpose", e.target.value)} placeholder="환자 앱에 표시할 처방 목적" />
                </div>
                <div className="field">
                  <label htmlFor={`${fid}-how`}>복용 안내</label>
                  <textarea id={`${fid}-how`} value={drug.how} onChange={(e) => change(index, "how", e.target.value)} placeholder="환자 앱에 표시할 복용 방법과 안내" />
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor={`${fid}-watch`}>주의사항</label>
                  <textarea id={`${fid}-watch`} value={drug.watch} onChange={(e) => change(index, "watch", e.target.value)} placeholder="예: 이런 증상이 있으면 병원에 연락하세요 — 환자 앱에 강조해 표시됩니다" />
                </div>
              </div>
            );
          })}

          <DurPanel dur={dur} missing={durMissing} acked={acked}
                    onAck={(on) => setAck({ sig, on })} />

          <div className="card-foot split prescription-actions">
            <button className="btn ghost sm" onClick={() => setDrugs((rows) => [...rows, emptyDrug()])}>+ 약 추가</button>
            <span className="note">{msg ?? (firstProblem ? `${firstProblem} 입력해 주세요` : hold)}</span>
            <button className="btn ghost" onClick={() => { setWriting(false); setDrugs([emptyDrug()]); }}>취소</button>
            <button className="btn" onClick={save} disabled={!valid || saving || blocked}>
              {saving ? "저장 중…" : "처방 저장"}
            </button>
          </div>
        </>
      )}
      {handout && <RxHandout patient={patient} rx={handout} onClose={() => setHandout(null)} />}
    </div>
  );
}
