import { useState } from "react";
import { Link } from "react-router-dom";
import { breast as api } from "../../../api";
import { MODALITY, READ_STATUS, label, modality as asModality } from "../../../codes";
import { go } from "../../../nav";
import { RUNNING, ruleText, unlockConds } from "../unlock";

/* 환자 리포트 잠금 해제 — 서버 GET /reports/{id}/unlock-status 가 판단한다.
 *
 *   { conditions: [{ key: "records_final" | "discordance_closed" | "explained",
 *                    label, met, items? }],
 *     can_unlock, report_ids?, unlocked? }
 *
 * ⚠ 09-28 — 화면이 conditions 를 **객체로** 읽고 있었다(c.all_finalized …).
 *   서버는 배열을 준다 — 그래서 세 줄이 늘 「대기」인데 머리글은 「조건을 모두
 *   채웠습니다」라고 했다. 이제 key 로 찾는다. 옛 객체 모양도 받는다.
 * ⚠ 종합 소견서는 의사용 · 환자용 두 벌이다. 서버가 설명 · 해제를 짝 전체에
 *   건다(core/views/surgery.py _report_pair). 화면은 **환자용 번호**로 부른다 —
 *   환자가 읽는 것이 그 벌이다. items 는 새 서버만 준다 — 없으면 이미 불러 둔
 *   환자 상세(오더 · 불일치)로 짚는다. */

/** 안 채운 조건 하나의 「왜」 줄들. 서버 items 가 없으면 환자 상세로 짚는다 */
function whyOf(cond, patient) {
  const pid = patient?.patient_id;
  if (cond.key === "records_final") {
    const items = cond.items ?? [
      ...(patient?.orders ?? []).filter((o) => o.modality && RUNNING.has(o.order_status))
        .map((o) => ({ kind: "order", modality: o.modality, read_status: o.order_status })),
    ];
    return items.map((it) => ({
      text: it.kind === "specimen"
        ? `검체 ${it.specimen_label ?? `#${it.specimen_id}`} — 병리 확진 전`
        : `${label(MODALITY, asModality(it.modality)) || "검사"}${it.study_id != null ? ` #${it.study_id}` : ""} — ${label(READ_STATUS, it.read_status) || it.read_status || "판독 전"}`,
      to: pid != null ? go.breast.review(pid, it.study_id != null ? { study: it.study_id }
        : it.specimen_id != null ? { specimen: it.specimen_id } : null) : null,
      act: "환자 상세 ›",
    }));
  }
  if (cond.key === "discordance_closed") {
    const items = cond.items ?? (patient?.open_discordances ?? [])
      .map((d) => ({ discordance_id: d.discordance_id, violated_rule: d.violated_rule, review_note: d.review_note }));
    const extra = Object.fromEntries((patient?.open_discordances ?? []).map((d) => [String(d.discordance_id), d]));
    return items.map((it) => ({
      text: `불일치 #${it.discordance_id} — ${ruleText({ ...it, ...(extra[String(it.discordance_id)] ?? {}) })}`,
      to: it.discordance_id != null ? go.breast.discordance(it.discordance_id) : null,
      act: "처분하기 →",
    }));
  }
  return [];
}

function LockIcon({ open }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="none"
         stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="10" rx="2" />
      <path d={open ? "M8 11V7a4 4 0 0 1 7.5-2" : "M8 11V7a4 4 0 0 1 8 0v4"} />
    </svg>
  );
}

/* 조건 줄들 — 안 채운 것은 까닭과 할 일을 붙인다.
   compact — 오른쪽 레일(까닭 한 줄 · 할 일 단추 하나) */
export function CondList({ conds, patient, onExplain, compact = false }) {
  return (
    <ul className={`cond-list${compact ? " compact" : ""}`}>
      {conds.map((c, i) => {
        const why = c.met === false ? whyOf(c, patient) : [];
        const shown = compact ? why.slice(0, 1) : why;
        return (
          <li key={c.key} className={`cond-row ${c.met ? "met" : c.met === false ? "unmet" : "unknown"}`}
              data-cond={c.key}>
            <div className="cond-h">
              <span>{"①②③"[i]} {c.label}</span>
              <span className={`pill ${c.met ? "ok" : "wait"}`}>{c.met ? "충족" : c.met === false ? "대기" : "확인 불가"}</span>
            </div>
            {c.met === false && c.key === "explained" && (
              <div className="cond-why">
                <span>환자에게 결과를 설명하고 기록해야 합니다.</span>
                {onExplain && <button type="button" className="edit-btn" onClick={onExplain}>설명 기록으로 ↓</button>}
              </div>
            )}
            {shown.map((w, j) => (
              <div className="cond-why" key={j}>
                <span>{w.text}</span>
                {w.to && <Link className="edit-btn" to={w.to}>{w.act}</Link>}
              </div>
            ))}
            {compact && why.length > shown.length && <div className="cond-why"><span>외 {why.length - shown.length}건</span></div>}
            {c.met === false && c.key === "records_final" && !why.length && (
              <div className="cond-why"><span>확정되지 않은 검사 · 검체가 있습니다(영상의학과 · 병리과 확정 대기).</span></div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/* 잠금 해제 칸 — ⑤ 환자 설명 카드 아래 */
export function LockPanel({ reportId, status, patient, unlocked, unlockedAt, onUnlocked, onExplain }) {
  const conds = unlockConds(status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const done = unlocked || status?.unlocked === true;
  const ready = Boolean(status?.can_unlock) && conds.every((c) => c.met);
  const left = conds.filter((c) => !c.met).length;

  async function unlock() {
    setBusy(true);
    setError(null);
    try {
      await api.unlock(reportId);
      onUnlocked?.();
    } catch (e) {
      setError(e.detail || e.message || "잠금 해제에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`lock-panel${done ? " unlocked" : ready ? " ready" : ""}`}>
      <div className="lock-h">
        <span className="lock-icon"><LockIcon open={done} /></span>
        <p className="status">
          {done ? `환자에게 공개됨${unlockedAt ? ` · ${String(unlockedAt).replace("T", " ").slice(0, 16)}` : ""}`
            : ready ? "조건을 모두 충족했습니다 — 잠금을 해제할 수 있습니다"
            : `환자 리포트가 잠겨 있습니다 — 조건 ${left}개 남음`}
        </p>
      </div>
      <CondList conds={conds} patient={patient} onExplain={onExplain} />
      {!done && (
        <button className="btn" disabled={!ready || busy} onClick={unlock}>
          {busy ? "해제 중…" : "환자 리포트 잠금 해제"}
        </button>
      )}
      {!done && <p className="hint">잠금을 해제하면 환자 앱에 리포트가 공개되고 「결과 도착」 알림이 전송됩니다. 의료진용 리포트도 함께 해제됩니다.</p>}
      {error && <p className="note err">{error}</p>}
    </div>
  );
}
