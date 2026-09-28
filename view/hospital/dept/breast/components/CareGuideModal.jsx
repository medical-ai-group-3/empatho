import { Link } from "react-router-dom";
import { go } from "../../../nav";
import Stepper from "./Stepper";

/* 다음 진료 안내 — 이 환자의 진료 흐름 전체와 다음 할 일.
 *
 * 단계 판단은 flow.js 한 곳이다(여기서 다시 세지 않는다).
 *
 * ⚠ 09-28 — 전에는 검사 네 칸(맘모 · 초음파 · MRI · 조직검사)만 보였고,
 *   불일치 · 추적 · 치료 방침일 때는 **「확인」 하나로 막혔다.** 안내만
 *   하고 갈 곳을 안 주는 팝업이었다. 이제 다음 할 일이 곧 주 단추이고
 *   (처분하기 · 치료 방침 · 재진 예약 …), 결과를 기다리는 중일 때만
 *   주 단추가 없다 — 할 일이 남의 차례라서다. */
export default function CareGuideModal({ patient, flow, onClose, onRun }) {
  const next = flow?.next;
  const pid = patient.patient_id;
  const can = next && (next.to || next.act);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>다음 진료 안내 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p className="bf-lead">
            <b>{next?.label ?? "—"}</b>
            {next?.why && <> — {next.why}</>}
          </p>
          <Stepper steps={flow?.steps ?? []} />
        </div>
        <div className="modal-foot">
          {/* 보조 길 — 흐름 순서대로. 다음 할 일과 같은 곳이면 안 겹쳐 둔다 */}
          <Link className="btn ghost" to={go.breast.review(pid)} onClick={onClose}>환자 상세</Link>
          {next?.key !== "decision" && (
            <Link className="btn ghost" to={go.breast.decision(pid)} onClick={onClose}>치료 방침</Link>
          )}
          <button className="btn ghost" onClick={onClose}>닫기</button>
          {can && (
            next.to && !next.act
              ? <Link className="btn" to={next.to} onClick={onClose}>{next.label} →</Link>
              : <button className="btn" onClick={() => onRun(next)}>{next.label}</button>
          )}
        </div>
      </div>
    </div>
  );
}
