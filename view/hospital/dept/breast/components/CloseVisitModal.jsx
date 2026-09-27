import { useState } from "react";
import { breast as api } from "../../../api";

/* "진료 완료" 확인 팝업 — 촬영 없이 방문을 닫는다.
 *
 * 09-28 — 「이상 없음 · 종결」이라 이름 붙어 있어 진료만 보고 끝난 환자에
 * 아무도 안 눌렀다. 오더가 안 닫혀 환자 앱 「내 예약」·대기에 계속 남았다.
 *
 * 사유 입력칸을 두지 않는다. PATCH /exam-orders/{id}/complete 는 몸통을
 * 안 받아서(api.js 의 breast.completeExamOrder 주석 참고) 여기서 뭘 적어도
 * 서버로 안 간다 — 안 가는 칸을 보여주는 건 거짓 저장이다. 사유를 남기는
 * 기능이 필요해지면 서버에 먼저 자리가 생겨야 한다.
 *
 * 종결할 오더는 patient_id 로 못 찾는다 — 이 환자의 exam-orders 목록에서
 * 아직 끝나지 않은 것 중 가장 최근 것을 고른다. */
export default function CloseVisitModal({ patient, onClose, onDone }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function confirm() {
    setSaving(true);
    setError(null);
    try {
      const orders = await api.ordersOf(patient.patient_id);
      /* 종결은 접수된 방문(requested + visited_at)만 — 미래 예약이나
         촬영을 지시한 오더(ordered 이후)는 넣지 않는다. */
      const open = (orders ?? [])
        .filter((o) => o.order_status === "requested" && o.visited_at)
        .sort((a, b) => new Date(b.visited_at ?? b.scheduled_at ?? b.ordered_at ?? 0)
          - new Date(a.visited_at ?? a.scheduled_at ?? a.ordered_at ?? 0));
      if (!open.length) {
        setError("종결할 오더를 찾지 못했습니다 — 원무 접수 기록을 확인해 주세요");
        return;
      }
      /* 접수된 채 안 닫힌 방문을 모두 닫는다 — 전에 안 닫힌 것까지 남으면
         환자 앱에 계속 뜬다. 백엔드는 exam_order_id 또는 id 를 돌려준다. */
      for (const o of open) await api.completeExamOrder(o.exam_order_id ?? o.id);
      onDone?.();
    } catch (e) {
      setError(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>진료 완료 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13.5 }}>
            이번 방문을 마칩니다. 대기 목록과 환자 앱 예약에서 빠지고
            다음 환자로 넘어갑니다. 촬영을 요청한 건은 판독이 끝나면 따로 닫힙니다.
          </p>
          {error && <p className="field err">{error}</p>}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn" onClick={confirm} disabled={saving}>
            {saving ? "처리 중…" : "진료 완료"}
          </button>
        </div>
      </div>
    </div>
  );
}
