import { useState } from "react";
import { breast as api } from "../../../api";
import { BookForm } from "./BookVisit";
import FollowupRounds from "./FollowupRounds";

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
 * 아직 끝나지 않은 것 중 가장 최근 것을 고른다.
 *
 * ⚠ 09-28 — 닫고 나서 **막다른 길이었다.** 진료 흐름의 끝은 추적 · 재진이라
 *   닫은 자리에서 바로 다음 방문을 잡게 한다(둘째 걸음). 안 잡고 넘어가도
 *   된다 — 그때 [다음 환자]. suggest 는 권하는 간격(일).
 *   09-28 추적 회차도 둘째 걸음에서 만든다(FollowupRounds). */
export default function CloseVisitModal({ patient, suggest = 14, onClose, onDone }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [closed, setClosed] = useState(false);

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
      setClosed(true);
    } catch (e) {
      setError(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  /* 닫은 뒤에는 바깥(목록)이 이미 바뀌었다 — 팝업을 닫는 길이 곧 onDone */
  const finish = () => (closed ? onDone?.() : onClose?.());

  return (
    <div className="modal-backdrop" onClick={finish}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>{closed ? "진료를 마쳤습니다" : "진료 완료"} — {patient.name}</h2>
          <button aria-label="닫기" onClick={finish}>×</button>
        </div>
        {!closed ? (
          <>
            <div className="modal-body">
              <p className="bf-lead">
                이번 방문을 마칩니다. 대기 목록과 환자 앱 예약에서 빠집니다.
                촬영을 요청한 검사는 판독이 끝나면 따로 종결됩니다.
              </p>
              {error && <p className="field err">{error}</p>}
            </div>
            <div className="modal-foot">
              <button className="btn ghost" onClick={onClose}>취소</button>
              <button className="btn" onClick={confirm} disabled={saving}>
                {saving ? "처리 중…" : "진료 완료"}
              </button>
            </div>
          </>
        ) : (
          <div className="modal-body">
            <p className="bf-lead">다음 방문을 지금 예약할까요? 원무 예약 화면에 바로 표시됩니다.</p>
            <BookForm patient={patient} suggest={suggest}
                      onSkip={() => onDone?.()} skipLabel="다음 환자 →" />
            {/* 추적(6 · 12 · 24개월)도 같은 자리에서 — 못 쓰는 서버면 안 뜬다 */}
            <FollowupRounds patient={patient} />
          </div>
        )}
      </div>
    </div>
  );
}
