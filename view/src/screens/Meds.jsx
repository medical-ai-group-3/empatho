import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import Tilly from "../lib/Tilly";
import { Body, Head } from "../lib/Screen";
import { fmtDayKey } from "../lib/when";
import Icon from "../lib/Icon";

/* 13 · 복약 관리
 *
 * **처방전이 원천이다.** 약 목록을 따로 들고 있지 않고, 처방전을 불러와
 * 그 안의 약을 꺼내 쓴다.
 *
 *   처방전 ──┬── 약 ── 오늘 회차 ── 먹었다 기록
 *            └── 약 ── …
 *
 * 왜 처방전을 거치나 — 약이 **왜 거기 있는지**를 화면이 같이 말할 수
 * 있어야 한다. 「타목시펜 20mg」만 띄우면 환자는 그게 누가 언제 처방한
 * 것인지, 언제까지 먹는 것인지 모른다. 약만 보여주는 화면은 약통 사진과
 * 다를 것이 없다.
 *
 * ── 설명은 처방에 실려 온다 ──────────────────────────────────
 *
 * ⚠ **앱이 약 설명을 지어내지 않는다.** purpose · how · watch 는 서버가
 *   준 문장을 그대로 옮긴다. 같은 성분도 환자마다 쓰는 이유가 다르고,
 *   무엇을 주의해야 하는지는 처방한 사람이 안다. 앱이 약전을 긁어다
 *   붙이는 순간 그것은 **의학적 조언**이 된다.
 *
 * ⚠ 식약처 자료를 찾아보는 화면(screens/Drugs.jsx)이 따로 있다. 여기서
 *   거기로 **약 이름을 넘기지 않는다.** 처방받은 약을 눌렀더니 일반
 *   허가사항이 뜨면 환자는 그것을 자기 약 설명으로 읽는다 — 위 경고를
 *   링크 한 줄로 우회하는 셈이다. 잇는 것은 「찾아볼 수 있다」는 안내뿐이다.
 *
 * ── 앱이 하지 않는 것 ────────────────────────────────────────
 *
 * ⚠ **약을 더하거나 고치거나 지울 수 없다.** 손잡이는 「먹었다」를 적는
 *   것 하나뿐이다. 앱에서 약을 만들 수 있게 하면 화면의 목록과 처방이
 *   갈라지고, 그 뒤로는 어느 쪽이 맞는지 아무도 모른다.
 *
 * ⚠ **거른 뒤의 처리를 계산하지 않는다.** 「두 알 드세요」 같은 말은
 *   약마다 다르고 처방한 사람이 정한다. 화면은 문의하라고만 한다.
 *
 * ── 기록은 낙관적으로 ────────────────────────────────────────
 * 체크는 누르는 즉시 채워진다. 왕복을 기다렸다 채우면 「안 눌렸나」 싶어
 * 한 번 더 누른다. 실패하면 되돌리고 이유를 띄운다.
 *
 * ⚠ 복용 시각은 **서버가 찍는다.** 앱은 어느 회차인지만 보낸다.
 */
export default function Meds() {
  const { loading, data, error, reload } = useApi(() => api.prescriptions());

  return (
    <>
      <Head title="복약 관리" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </>
  );
}

function Inner({ d }) {
  const all = d.items ?? [];
  const live = all.filter((rx) => rx.status !== "ended");
  const past = all.filter((rx) => rx.status === "ended");

  /* 오늘 회차의 상태. 열쇠는 「약id-시각」이다 — 하루 두 번 먹는 약이
     있어서 약id 만으로는 회차를 못 가린다 */
  const [taken, setTaken] = useState(() => {
    const m = {};
    for (const rx of all) {
      for (const g of rx.drugs ?? []) {
        for (const t of g.today ?? []) m[`${g.drug_id}-${t.time}`] = t.log_id ?? null;
      }
    }
    return m;
  });
  const [busy, setBusy] = useState(null);
  const [msg, setMsg] = useState(null);
  const [open, setOpen] = useState(null);     // 설명을 펼친 약

  const slots = live.flatMap((rx) =>
    (rx.drugs ?? []).flatMap((g) => (g.today ?? []).map((t) => ({ g, t }))));
  const done = slots.filter(({ g, t }) => taken[`${g.drug_id}-${t.time}`]).length;
  const percent = slots.length ? Math.round((done / slots.length) * 100) : 0;
  const remaining = slots.length - done;
  /* 오늘 회차에 먹는 약이 아닌 것(바르는 약 · 주사…)이 섞였으면 「복용」 ·
     「드셨습니다」라고 하지 않는다. 경로가 없는 약은 전처럼 먹는 약으로 본다 */
  const allOral = slots.every(({ g }) => words(g).oral);

  async function toggle(g, time) {
    const key = `${g.drug_id}-${time}`;
    const was = taken[key];
    if (busy) return;
    setBusy(key); setMsg(null);
    setTaken((m) => ({ ...m, [key]: was ? null : "…" }));   // 먼저 채운다
    try {
      if (was) {
        await api.undoMed(g.drug_id, was);
        setTaken((m) => ({ ...m, [key]: null }));
      } else {
        const r = await api.takeMed(g.drug_id, time);
        setTaken((m) => ({ ...m, [key]: r?.log_id ?? "ok" }));
      }
    } catch (e) {
      setTaken((m) => ({ ...m, [key]: was }));              // 실패하면 되돌린다
      setMsg(e.detail || e.message || "기록하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  if (all.length === 0) {
    return (
      <div className="empty">
        <Tilly mood="rest" size="md" alt="" />
        <p>받으신 처방이 없습니다.</p>
        {/* 처방이 없는 분이야말로 약을 찾아볼 일이 있다 — 아래 목록 끝에만
            두면 이 분들에게는 링크가 아예 없다(여기서 일찍 돌아간다) */}
        <Link className="btn ghost" to="/drugs">약 정보 찾아보기</Link>
      </div>
    );
  }

  return (
    <>
      {/* 오늘 몇 회 중 몇 회. **약 종류가 아니라 회차로** 센다 —
          하루 두 번 먹는 약이 있어서 종류로 세면 안 맞는다 */}
      <div className="card med-summary">
        <div className="med-summary-head">
          <span className="k">{allOral ? "오늘 복용" : "오늘 약"}</span>
          <span className="med-summary-percent">{percent}%</span>
        </div>
        <span className="v">{done} / {slots.length} 회 완료</span>
        <span className="prog">
          <i style={{ width: `${percent}%` }} />
        </span>
        {slots.length > 0 && (
          <span className="s">
            {allOral
              ? (remaining ? `오늘 ${remaining}회 복용이 남았습니다.` : "오늘 드실 약을 다 드셨습니다.")
              : (remaining ? `오늘 ${remaining}회가 남았습니다.` : "오늘 챙기실 약을 다 챙기셨습니다.")}
          </span>
        )}
      </div>

      {msg && <div className="card flag"><span className="s">{msg}</span></div>}

      {live.map((rx) => (
        <Rx key={rx.prescription_id} rx={rx} taken={taken} busy={busy}
            open={open} setOpen={setOpen} onToggle={toggle} />
      ))}

      {past.length > 0 && (
        <>
          <h3 className="sec">지난 처방</h3>
          {past.map((rx) => (
            <Rx key={rx.prescription_id} rx={rx} taken={taken} busy={busy}
                open={open} setOpen={setOpen} onToggle={toggle} ended />
          ))}
        </>
      )}

      <p className="note">
        {d.note}
        <br />
        약을 거르셨거나 몸이 불편하시면 <b>임의로 조절하지 마시고</b> 담당
        주치의나 접수처에 문의해 주세요.
      </p>

      {/* 약의 일반 정보를 찾아보는 자리. 약 이름을 넘기지 않는 이유는
          위 머리말에 적어 두었다 */}
      <Link className="btn ghost" to="/drugs">약 정보 찾아보기</Link>
    </>
  );
}

/* 처방전 한 장 — 누가 · 언제 · 며칠분, 그리고 그 안의 약들 */
function Rx({ rx, taken, busy, open, setOpen, onToggle, ended }) {
  const period = prescriptionPeriod(rx);
  return (
    <div className={ended ? "card rx ended" : "card rx"}>
      <div className="rx-h">
        <span className="tx">
          <b>{fmtDayKey(rx.issued_on)} 처방</b>
          <span>
            {rx.prescriber} · {rx.dept}
            {/* 서버가 이 장에서 **가장 긴 약**의 일수를 준다. 약마다
                기간이 달라서 한 숫자로는 이것밖에 말할 수 없다 —
                실제 기간은 약 줄에 각각 적는다 */}
            {rx.days ? ` · 최대 ${rx.days}일분` : ""}
          </span>
        </span>
        {ended && <span className="pill read">종료</span>}
      </div>

      {!ended && period?.needsCheck && (
        <div className="rx-period">
          <b>{period.overdue ? "처방 기간 확인이 필요해요" : "처방 기간이 곧 끝나요"}</b>
          <span>
            이 처방전의 마지막 약이 {period.endLabel}에 끝납니다. {period.overdue
              ? "아직 복용 중이라면 임의로 조절하지 말고 병원에 연락해 확인해 주세요."
              : "다음 처방이나 복용 계획은 병원에 확인해 주세요."}
          </span>
        </div>
      )}

      {(rx.drugs ?? []).map((g) => {
        const on = open === g.drug_id;
        const w = words(g);
        const kind = [w.kind, g.form].filter(Boolean).join(" · ");
        return (
          <div className="drug" key={g.drug_id}>
            <div className="drug-h">
              <span className="tx">
                <b>{g.name}</b>
                {kind && <span className="drug-kind">{kind}</span>}
                <span>
                  {g.ingredient ? `${g.ingredient} · ` : ""}
                  1회 {g.dose} · 하루 {g.per_day}회
                  {/* 일수는 **약마다 다르다**(2026-09-21 팀 결정). 3일치
                      진통제와 30일치 호르몬제가 한 장에 같이 나온다 —
                      처방전 머리말의 「며칠분」만 보면 짧은 약을 계속
                      먹게 된다 */}
                  {g.days ? ` · ${g.days}일분` : ""}
                </span>
              </span>
            </div>

            {/* 오늘 회차. 지난 처방에는 회차가 없다 */}
            {(g.today ?? []).length > 0 && (
              <div className="med-slots">
                {g.today.map((t) => {
                  const key = `${g.drug_id}-${t.time}`;
                  const got = Boolean(taken[key]);
                  return (
                    <button key={t.time} className={got ? "slot on" : "slot"}
                            aria-pressed={got} disabled={busy === key}
                            onClick={() => onToggle(g, t.time)}>
                      <i aria-hidden="true" />
                      <span>{t.time}</span>
                      <em>{got ? w.done : "아직이에요"}</em>
                    </button>
                  );
                })}
              </div>
            )}

            {/* 설명은 접어 둔다. 매일 보는 화면이라 늘 펴 두면 회차를
                찾으러 스크롤을 해야 한다 — 처음 받은 약일 때 펴 본다 */}
            <button className="drug-more" aria-expanded={on}
                    onClick={() => setOpen(on ? null : g.drug_id)}>
              <Icon name={on ? "chevronDown" : "chevronRight"} />
              어떤 약인가요?
            </button>

            {on && (
              <dl className="drug-info">
                {g.purpose && (<><dt>무엇에 쓰나요</dt><dd>{g.purpose}</dd></>)}
                {g.how && (<><dt>{w.how}</dt><dd>{g.how}</dd></>)}
                {g.watch && (
                  <><dt>이럴 땐 알려 주세요</dt><dd className="watch">{g.watch}</dd></>
                )}
              </dl>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* 투여 경로 → 환자에게 하는 말. 서버 값(route)은 codes 와 같은 여섯 개다.
 *
 * ⚠ 경로가 없거나 모르는 값이면 **전처럼 먹는 약의 말**을 쓰되, 「먹는 약」
 *   이라고 적지는 않는다 — 모르는 것을 안다고 하지 않는다.
 * ⚠ 바르는 약 중 패치는 붙인다. 제형 글로만 가를 수 있어 form 을 본다. */
const ROUTE_WORDS = {
  oral:       { kind: "먹는 약",      done: "드셨어요",     how: "어떻게 드시나요" },
  injection:  { kind: "주사",         done: "맞으셨어요",   how: "어떻게 맞으시나요" },
  topical:    { kind: "바르는 약",    done: "바르셨어요",   how: "어떻게 바르시나요" },
  inhalation: { kind: "흡입하는 약",  done: "흡입하셨어요", how: "어떻게 흡입하시나요" },
  eye:        { kind: "눈에 넣는 약", done: "넣으셨어요",   how: "어떻게 넣으시나요" },
  other:      { kind: "기타",         done: "쓰셨어요",     how: "어떻게 쓰시나요" },
};
const PATCH = { kind: "붙이는 약", done: "붙이셨어요", how: "어떻게 붙이시나요" };

function words(g) {
  const w = ROUTE_WORDS[g.route];
  if (!w) return { ...ROUTE_WORDS.oral, kind: null, oral: true };
  if (g.route === "topical" && /패치|첩부|플라스타/.test(g.form ?? "")) return { ...PATCH, oral: false };
  return { ...w, oral: g.route === "oral" };
}

/* 날짜만 있는 처방일은 기기 시간대 영향을 받지 않게 직접 만든다. 수량을
   모르는 앱이 「약이 떨어진다」고 말하는 대신, 처방 기간만 확인한다.

   ⚠ rx.days 는 이 장에서 **가장 긴 약**의 일수다(서버가 그렇게 준다).
     그래서 여기서 나오는 날은 「마지막 약이 끝나는 날」이고, 짧은 약은
     그 전에 이미 끝나 있다. 약별 종료는 서버가 약마다 ends_on 으로 주고,
     끝난 약에는 오늘 회차(today)를 아예 안 실어 보낸다 — 화면이 회차
     단추를 안 그리는 것이 그 때문이다. 여기서 약별로 다시 계산하지 말 것. */
function prescriptionPeriod(rx) {
  if (!rx.issued_on || !rx.days) return null;
  const [year, month, day] = rx.issued_on.split("-").map(Number);
  const end = new Date(year, month - 1, day);
  end.setDate(end.getDate() + rx.days - 1);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const daysLeft = Math.round((end - today) / 86400000);
  const endLabel = `${end.getFullYear()}.${String(end.getMonth() + 1).padStart(2, "0")}.${String(end.getDate()).padStart(2, "0")}`;
  return {
    endLabel,
    overdue: daysLeft < 0,
    needsCheck: daysLeft < 0 || daysLeft <= 7,
  };
}
