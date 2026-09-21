import { MODALITY, label } from "../../../codes";

const STEPS = [
  { id: "mammo", label: "맘모그래피" },
  { id: "us", label: "초음파" },
  { id: "mri", label: "MRI" },
  { id: "specimen", label: "조직검사" },
];

/* 유방외과에서 진료 화면을 열기 전에 보여 주는 다음 단계 안내.
   "기록 없음"을 단순 오류로 끝내지 않고, 지금 할 수 있는 요청/등록 버튼을
   바로 준다. 단계 판단은 Waiting.jsx의 nextCareStep 한 곳에만 둔다. */
export default function CareGuideModal({ patient, step, progress, onClose, onAction }) {
  const current = step.modality ?? (step.kind === "specimen" || step.kind === "pathology-wait" ? "specimen" : null);
  const isActionable = step.kind === "request" || step.kind === "specimen";

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>다음 진료 안내 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p style={{ marginTop: 0, lineHeight: 1.6 }}>{step.message}</p>
          <div className="care-steps" aria-label="검사 진행 순서">
            {STEPS.map((item) => {
              const status = progress[item.id] ?? "todo";
              return (
                <div className={`care-step ${status}`} key={item.id}>
                  <span aria-hidden="true">{status === "done" ? "✓" : status === "waiting" ? "…" : "○"}</span>
                  <b>{item.label}</b>
                  <small>{status === "done" ? "완료" : status === "waiting" ? "진행 중" : "대기"}</small>
                </div>
              );
            })}
          </div>
          {step.kind === "pathology-wait" && (
            <p className="hint">검체는 병리과에서 접수·판독 후 결과가 반영됩니다.</p>
          )}
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>{isActionable ? "나중에" : "확인"}</button>
          {isActionable && (
            <button className="btn fill" onClick={onAction}>
              {step.kind === "request" ? `${label(MODALITY, current)} 촬영 요청` : "검체 등록"}
            </button>
          )}
        </div>
      </div>
      <style>{`
        .care-steps { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:6px; margin-top:18px; }
        .care-step { display:flex; min-width:0; flex-direction:column; gap:3px; padding:10px 7px; border:1px solid var(--line); border-radius:8px; color:var(--muted); font-size:12px; text-align:center; }
        .care-step > span { font-size:16px; font-weight:700; }
        .care-step b { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:inherit; }
        .care-step small { font-size:11px; }
        .care-step.done { border-color:var(--accent); color:var(--accent); background:color-mix(in srgb, var(--accent) 8%, transparent); }
        .care-step.waiting { border-color:var(--primary); color:var(--primary); }
      `}</style>
    </div>
  );
}
