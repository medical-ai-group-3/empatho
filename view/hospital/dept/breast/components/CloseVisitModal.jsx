import { useState } from "react";
import { breast as api } from "../../../api";

/* "이상 없음 · 종결" 확인 팝업 — 촬영 없이 방문을 닫는다.
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
      /* 종결은 지금 접수된 방문(requested + visited_at)만 할 수 있다.
         미래 예약이나 이전 미종결 오더까지 후보에 넣으면 엉뚱한 검사가
         종결될 수 있다. */
      const open = (orders ?? [])
        .filter((o) => o.order_status === "requested" && o.visited_at)
        .sort((a, b) => new Date(b.visited_at ?? b.scheduled_at ?? b.ordered_at ?? 0)
          - new Date(a.visited_at ?? a.scheduled_at ?? a.ordered_at ?? 0));
      const target = open[0];
      if (!target) {
        setError("종결할 오더를 찾지 못했습니다 — 원무 접수 기록을 확인해 주세요");
        return;
      }
      /* 백엔드는 상황에 따라 exam_order_id 또는 기본 id를 돌려준다. */
      const orderId = target.exam_order_id ?? target.id;
      if (orderId == null) {
        setError("종결할 방문 번호를 확인하지 못했습니다. 새로고침 후 다시 시도해 주세요.");
        return;
      }
      await api.completeExamOrder(orderId);
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
          <h2>이상 없음 · 종결 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ fontSize: 13.5 }}>
            촬영 없이 이 환자의 방문을 종결합니다. 대기 목록에서 빠지고
            다음 환자로 넘어갑니다.
          </p>
          {error && <p className="field err">{error}</p>}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>취소</button>
          <button className="btn" onClick={confirm} disabled={saving}>
            {saving ? "처리 중…" : "종결"}
          </button>
        </div>
      </div>
    </div>
  );
}
