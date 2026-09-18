import { useState } from "react";
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
      </div>
    );
  }

  return (
    <>
      {/* 오늘 몇 회 중 몇 회. **약 종류가 아니라 회차로** 센다 —
          하루 두 번 먹는 약이 있어서 종류로 세면 안 맞는다 */}
      <div className="card">
        <span className="k">오늘 복용</span>
        <span className="v">{done} / {slots.length} 회</span>
        <span className="prog">
          <i style={{ width: `${slots.length ? (done / slots.length) * 100 : 0}%` }} />
        </span>
        {slots.length > 0 && done === slots.length && (
          <span className="s">오늘 드실 약을 다 드셨습니다.</span>
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
    </>
  );
}

/* 처방전 한 장 — 누가 · 언제 · 며칠분, 그리고 그 안의 약들 */
function Rx({ rx, taken, busy, open, setOpen, onToggle, ended }) {
  return (
    <div className={ended ? "card rx ended" : "card rx"}>
      <div className="rx-h">
        <span className="tx">
          <b>{fmtDayKey(rx.issued_on)} 처방</b>
          <span>
            {rx.prescriber} · {rx.dept}
            {rx.days ? ` · ${rx.days}일분` : ""}
          </span>
        </span>
        {ended && <span className="pill read">종료</span>}
      </div>

      {(rx.drugs ?? []).map((g) => {
        const on = open === g.drug_id;
        return (
          <div className="drug" key={g.drug_id}>
            <div className="drug-h">
              <span className="tx">
                <b>{g.name}</b>
                <span>{g.ingredient} · 1회 {g.dose} · 하루 {g.per_day}회</span>
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
                      <em>{got ? "드셨어요" : "아직이에요"}</em>
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
                {g.how && (<><dt>어떻게 드시나요</dt><dd>{g.how}</dd></>)}
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
