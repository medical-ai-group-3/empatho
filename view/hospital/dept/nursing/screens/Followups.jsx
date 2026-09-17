import { useEffect, useMemo, useState } from "react";
import { Page, Card, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip, Facts, Locked } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";

/* ═══ 2장 · 추적 대상 관리 ═══════════════════════════════════════
 *
 * **추적이 시작되는 경로**
 *   유방외과가 assessment.category = 3으로 확정하면 이 화면 목록에
 *   "추적 대상"으로 뜬다(followup 행이 아직 없다). 시스템이 자동으로
 *   followup을 만들지 않는다 — 간호사가 보고 [추적 회차 생성]을 눌러야
 *   시작된다(간호과 명세 §2).
 *
 * **한 목록에 두 종류가 섞인다** — 추적을 아직 시작하지 않은 환자(추적
 *   대상)와 진행 중인 환자를 한 목록에 두고 상태로 구분한다.
 *
 * **왼쪽·오른쪽 세로 길이를 맞춘다** — 1장과 같은 이유로 `.n-grid`/
 *   `.n-side-stack`(hospital.css)을 그대로 쓴다. */
export default function NursingFollowups({ cfg }) {
  if (!can("nursing.followup.view")) {
    return (
      <Page crumb={[cfg.name, "추적 대상 관리"]} title="추적 대상 관리">
        <Locked what="추적 대상 관리" />
      </Page>
    );
  }
  return <Inner cfg={cfg} />;
}

/* 기한 초과 판정은 명세에도 "배치로 바꿀지 조회 때 계산할지 미정"이라고
   되어 있다 — 조회 때 계산하는 쪽으로 정하고 연다. status가 이미
   overdue면 그대로 쓰고, open인데 due_at이 지났으면 화면에서 올려 보여준다. */
function displayStatus(f) {
  if (f.status === "open" && f.due_at && f.due_at < todayStr()) return "overdue";
  return f.status;
}
function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

const STATUS_LABEL = {
  candidate: "추적 대상",
  open: "추적 중",
  overdue: "기한 초과",
  resolved: "종결",
  declined: "거절 · 상급전원",
  escalated: "거절 · 상급전원",
};
const STATUS_TONE = {
  candidate: "line", open: "dot", overdue: "fill",
  resolved: "line", declined: "line", escalated: "line",
};
const FILTERS = [
  { key: "", label: "전체" },
  { key: "candidate", label: "추적 대상" },
  { key: "open", label: "추적 중" },
  { key: "overdue", label: "기한 초과" },
  { key: "resolved", label: "종결" },
];

function Inner({ cfg }) {
  const { loading, data, error, reload } = useApi(() => cfg.api.followups(), []);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState(null);

  const items = useMemo(() => {
    const raw = data?.items ?? [];
    return raw.map((f) => ({ ...f, view_status: displayStatus(f) }));
  }, [data]);

  const shown = filter ? items.filter((f) => f.view_status === filter) : items;
  const selected = items.find((f) => f.id === selectedId) ?? null;

  const counts = useMemo(() => {
    const c = { "": items.length };
    for (const f of items) c[f.view_status] = (c[f.view_status] ?? 0) + 1;
    return c;
  }, [items]);

  return (
    <Page crumb={[cfg.name, "추적 대상 관리"]} title="추적 대상 관리"
          badge={items.some((f) => f.view_status === "overdue") ? `지연 ${counts.overdue}건` : undefined}
          sub="추적 회차를 예정일 순으로 정렬합니다. 안내 콜 결과를 기록하고 회차를 새로 만듭니다.">
      <div className="n-grid">
        <Card title="추적 환자 리스트" pad={false}>
          <Body loading={loading} error={error} onRetry={reload}>
            <div className="tbl-top">
              <div className="sorts" role="group" aria-label="상태 필터">
                <span className="sorts-k">상태</span>
                {FILTERS.map((f) => (
                  <button key={f.key} className={`pill ${filter === f.key ? "on" : ""}`}
                          onClick={() => setFilter(f.key)}>
                    {f.label} <span style={{ opacity: .7 }}>{counts[f.key] ?? 0}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>환자</th><th>회차</th><th>예정일</th><th>상태</th><th>최근 연락</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((f) => (
                    <tr key={f.id} className={selectedId === f.id ? "on" : undefined}
                        onClick={() => setSelectedId(f.id)} tabIndex={0}>
                      <td>{f.name}</td>
                      <td>{f.round_no ? `${f.round_no}회` : "—"}</td>
                      <td>{f.due_at ?? "—"}</td>
                      <td><Chip tone={STATUS_TONE[f.view_status]}>{STATUS_LABEL[f.view_status]}</Chip></td>
                      <td>{f.call_result ?? "미연락"}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <RowActions cfg={cfg} f={f} onPick={() => setSelectedId(f.id)} onDone={reload} />
                      </td>
                    </tr>
                  ))}
                  {shown.length === 0 && (
                    <tr className="none"><td colSpan={6}>해당하는 환자가 없습니다</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </Body>
        </Card>

        <div className="n-side-stack">
          <CreateRoundCard cfg={cfg} selected={selected} onDone={reload} />
          <CallLogCard cfg={cfg} selected={selected} onDone={reload} />
        </div>
      </div>
    </Page>
  );
}

function RowActions({ cfg, f, onPick, onDone }) {
  const [busy, setBusy] = useState(false);

  /* 명세에 종결·재진입 전용 엔드포인트가 없다 — "정해지지 않은 것"에
     안 걸린 진짜 빈틈이다. 상태만 바꾸는 것도 결국 그 회차에 손대는
     일이라 PATCH /followups/{id}/call을 그대로 빌려 쓴다(백엔드가
     전용 경로를 열어 주면 그쪽으로 바꾸면 된다). */
  async function resolve() {
    setBusy(true);
    try { await cfg.api.logCall(f.id, { status: "resolved" }); onDone?.(); }
    finally { setBusy(false); }
  }
  async function reopen() {
    setBusy(true);
    try { await cfg.api.logCall(f.id, { status: "open" }); onDone?.(); }
    finally { setBusy(false); }
  }

  const isCandidate = f.view_status === "candidate";
  const isTerminal = f.view_status === "resolved";
  const isDeclined = f.view_status === "declined" || f.view_status === "escalated";
  /* 종결·거절/상급전원은 명세가 "보기만"이라고 못박은 상태다 — 콜기록도
     종결도 여기서는 막는다. 거절 쪽에서 다시 움직이려면 재진입부터다. */
  const viewOnly = isTerminal || isDeclined;

  return (
    <div className="stack">
      <button className="btn line" onClick={onPick} disabled={isCandidate || viewOnly}>콜 기록</button>
      <button className="btn line" onClick={reopen} disabled={busy || !isDeclined}>재진입</button>
      <button className="btn line" onClick={resolve} disabled={busy || isCandidate || viewOnly}>종결</button>
    </div>
  );
}

/* 추적 회차 생성 — 첫 회차 또는 다음 회차. 추적 대상(회차 없음)이면
   1회차, 이미 진행 중이면 마지막 회차+1을 기본값으로 미리 채운다
   (간호과 명세: "첫 회차 또는 다음 회차를 만든다"). */
function CreateRoundCard({ cfg, selected, onDone }) {
  const nextRound = (selected?.round_no ?? 0) + 1;
  const [round, setRound] = useState(nextRound);
  const [dueAt, setDueAt] = useState("");
  const [purpose, setPurpose] = useState("결과 안내 및 재방문 유도");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  /* 고른 환자가 바뀌면 회차 기본값을 그 환자의 "다음 회차"로 다시 맞춘다 */
  useEffect(() => { setRound(nextRound); }, [selected?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  async function create() {
    if (!selected) return;
    setSaving(true);
    setMsg(null);
    try {
      await cfg.api.createFollowup({
        patient_id: selected.patient_id, round_no: round,
        due_at: dueAt, purpose,
      });
      setMsg(`${round}회차 추적이 생성되었습니다.`);
      onDone?.();
    } catch (e) {
      setMsg(e.detail || "생성에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="추적 회차 생성">
      {!selected ? (
        <div className="slot"><b>왼쪽 목록에서 환자를 고르세요</b></div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Facts items={[["환자", `${selected.name} · ${selected.patient_id}`]]} />
          <div className="fields">
            <label className="field">
              <span>회차</span>
              <input type="number" min={1} value={round}
                onChange={(e) => setRound(Number(e.target.value))} />
            </label>
            <label className="field">
              <span>추적 예정일</span>
              <input type="date" value={dueAt} onChange={(e) => setDueAt(e.target.value)} />
            </label>
            <label className="field" style={{ gridColumn: "1 / -1" }}>
              <span>추적 목적</span>
              <select value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                <option>결과 안내 및 재방문 유도</option>
                <option>수술 후 경과 확인</option>
                <option>영상 추적 (6개월)</option>
              </select>
            </label>
          </div>
          {msg && <div className="notice">{msg}</div>}
          <div className="stack" style={{ justifyContent: "flex-end" }}>
            <Btn kind="fill" onClick={create} disabled={saving || !dueAt}>
              {saving ? "생성 중…" : "생성"}
            </Btn>
          </div>
        </div>
      )}
    </Card>
  );
}

/* 안내 콜 기록 — 아직 회차가 없는 "추적 대상"은 걸 회차가 없어 폼을
   막는다. 통화 결과는 연결 · 부재 · 거부 중 하나만 고른다(단일 선택). */
function CallLogCard({ cfg, selected, onDone }) {
  const [result, setResult] = useState("연결");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  const viewOnlyStatus = ["candidate", "resolved", "declined", "escalated"];
  const disabled = !selected || viewOnlyStatus.includes(selected.view_status);

  async function save() {
    if (!selected) return;
    setSaving(true);
    setMsg(null);
    try {
      await cfg.api.logCall(selected.id, {
        call_at: new Date().toISOString(), call_result: result, call_note: note,
      });
      setMsg("통화 기록을 저장했습니다.");
      onDone?.();
    } catch (e) {
      setMsg(e.detail || "저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card title="안내 콜 기록" right={selected && <span className="hint">{selected.name} · {selected.round_no ? `${selected.round_no}회차` : "—"}</span>}>
      {disabled ? (
        <div className="slot">
          <b>{
            !selected ? "왼쪽 목록에서 환자를 고르세요"
              : selected.view_status === "candidate" ? "먼저 추적 회차를 생성하세요"
              : "종결·거절 상태는 보기만 합니다 — 다시 움직이려면 재진입부터 누르세요"
          }</b>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <p className="muted small" style={{ marginBottom: 8 }}>통화 결과 (필수)</p>
            <div className="stack">
              {["연결", "부재", "거부"].map((r) => (
                <button key={r} className={`pill ${result === r ? "on" : ""}`}
                        onClick={() => setResult(r)}>{r}</button>
              ))}
            </div>
          </div>
          <label className="field">
            <span>통화 메모</span>
            <textarea value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="다음 주 재방문 안내" />
          </label>
          {msg && <div className="notice">{msg}</div>}
          <div className="stack" style={{ justifyContent: "flex-end" }}>
            <Btn kind="fill" onClick={save} disabled={saving}>
              {saving ? "저장 중…" : "통화 기록 저장"}
            </Btn>
          </div>
        </div>
      )}
    </Card>
  );
}

