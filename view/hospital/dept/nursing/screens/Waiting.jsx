import { useEffect, useState } from "react";
import { Page, Card, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip, Facts, Queue, Locked, Table } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import { SEX, label } from "../../../codes";
import SideDashboard from "../../../lib/SideDashboard";

/* ═══ 1장 · 내원 대기 · 유방외과 배정 ══════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   지금 와 있는 환자를 접수 순서대로 보고 유방외과 의사에게 배정한다.
 *   [유방외과 큐로 전송]을 누르면 그 환자의 patient.primary_staff_id가
 *   고른 의사로 채워지고, 그때부터 그 의사의 "내 환자" 화면에만 뜬다
 *   (유방외과는 영상·병리처럼 선착순으로 집지 않는다 — 간호과 명세 §1).
 *
 * **세 단이 맡는 일이 다르다**
 *   왼쪽 = 금일 예약·내 업무, 가운데 = 이미 내원해 간호 확인을 기다리는 사람,
 *   오른쪽 = 고른 환자의 상세·문진·전달 처리다.
 *
 * **순번은 표시 전용이다.** 원무가 접수한 순서 그대로다 — 드래그로
 * 못 바꾼다(간호과 명세가 명시적으로 확인해 준 부분).
 *
 * 모든 열은 같은 화면 높이를 쓰고, 넘치는 내용은 카드 안에서만 스크롤한다. */
export default function NursingWaiting({ cfg, embedded = false }) {
  if (!can("nursing.waiting.view")) {
    return (
      <Page bare={embedded} crumb={[cfg.name, "내원 대기 · 유방외과 배정"]} title="내원 대기 · 유방외과 배정">
        <Locked what="내원 대기" />
      </Page>
    );
  }
  return <Inner cfg={cfg} embedded={embedded} />;
}

const POLL_MS = 7000;

function examOrder(it) {
  if (!it) return it;
  return {
    ...it,
    id: it.exam_order_id,
    patient_id: it.patient,
    name: it.patient_name ?? `환자 #${it.patient}`,
    patient_number: it.patient_number ?? `#${it.patient}`,
    status: it.order_status,
    visit_type: it.visit_type ?? it.exam_purpose ?? "-",
    time: it.time ?? it.scheduled_at?.slice(11, 16) ?? "-",
  };
}

/* ⚠ 2026-09-18 다희님 확인(feature/dahee) — sex 를 그대로 꽂으면 null 일 때
 * "null" 글자가 그대로 찍힌다. codes.js 의 SEX 표 + label() 을 거친다 —
 * 값이 없으면 빈칸이다. */
function person(it) {
  const detail = [it.age, label(SEX, it.sex)].filter(Boolean).join("/");
  return detail ? `${it.name} (${detail})` : it.name;
}

function queueItem(it, no) {
  return {
    id: it.exam_order_id,
    no,
    title: `${it.patient_name ?? `환자 #${it.patient}`} (${it.age ?? "-"}/${label(SEX, it.sex) || "-"})`,
    sub: `${it.patient ?? "-"} · ${it.visited_at ?? "-"} 접수 · ${it.visit_type ?? "-"}`,
    chip: it.order_status,
    chipTone: it.order_status === "문진 중" ? "fill" : "line",
  };
}

function Inner({ cfg, embedded }) {
  const today = useApi(() => cfg.api.scheduledToday(), []);
  const [selectedId, setSelectedId] = useState(null);
  const [queueVersion, setQueueVersion] = useState(0);
  const detail = useApi(
    () => (selectedId ? cfg.api.examOrder(selectedId) : Promise.resolve(null)),
    [selectedId],
  );

  return (
    <Page crumb={[cfg.name, "내원 대기 · 유방외과 배정"]}
          title="내원 대기 · 유방외과 배정"
          bare={embedded}
          sub="접수 순번대로 정렬됩니다. 문진을 마치면 유방외과 큐로 보냅니다.">
      <div className={`n-grid${embedded ? " n-grid-embedded" : ""}`}>
        <div className="n-left-stack">
          <Card title="금일 내원 예정" right={<span className="hint">예약 {today.data?.results?.length ?? 0}건</span>} pad={false}>
            <Body loading={today.loading} error={today.error} onRetry={today.reload}>
              <Table
                cols={[
                  { key: "who", label: "환자" },
                  { key: "time", label: "시간" },
                  { key: "kind", label: "구분" },
                ]}
                rows={(today.data?.results ?? []).map(examOrder).map((it) => ({
                  id: it.id,
                  who: person(it),
                  time: it.time,
                  kind: <Chip tone={it.followup_id ? "dot" : "line"}>{it.followup_id ? "추적 관찰" : "예약"}</Chip>,
                }))}
              />
            </Body>
          </Card>
          <SideDashboard />
        </div>

        <WaitingQueue cfg={cfg} selectedId={selectedId} onPick={setSelectedId}
          refreshVersion={queueVersion} />

        <Card className="n-detail-card" title="환자 상세 정보" right={<Chip tone="line">문진 포함</Chip>}>
          {!selectedId
            ? <div className="slot"><b>가운데 목록에서 한 사람을 고르세요</b></div>
            : (
              <Body loading={detail.loading} error={detail.error} onRetry={detail.reload}>
                {detail.data && <PatientDetail cfg={cfg} d={examOrder(detail.data)}
                  onAssigned={() => { setSelectedId(null); setQueueVersion((v) => v + 1); }} />}
              </Body>
            )}
        </Card>
      </div>
    </Page>
  );
}

function isForwarded(it) {
  if (it?.primary_staff_id ?? it?.primary_staff ?? it?.assigned_staff_id ?? it?.surgeon_id) {
    return true;
  }
  const dept = String(it?.destination_department ?? it?.queue_department ?? "").toLowerCase();
  return Boolean(dept && !dept.includes("nursing") && !dept.includes("간호"));
}

/* 대기 목록은 이 카드만 다시 불러온다. 부모 화면에 목록 데이터를 두면
   폴링할 때 상세·예약·내 업무까지 함께 다시 그려져 사용자가 화면 전체가
   갱신된다고 느낄 수 있다. quiet reload는 기존 행을 남겨 둔 채 새 목록만
   교체하므로, 새 접수나 다른 부서 전송이 있어도 선택한 환자 상세는 유지된다. */
function WaitingQueue({ cfg, selectedId, onPick, refreshVersion }) {
  const arrived = useApi(() => cfg.api.waitingArrived(), []);
  /* 간호과가 유방외과로 전송한 환자는 서버의 requested 목록에 잠시
     남아 있을 수 있다. 배정 정보가 응답에 포함되면 이 카드에서 즉시
     제외해 다른 과로 넘어간 환자를 다시 접수하지 않게 한다. */
  const rows = (arrived.data?.results ?? arrived.data?.items ?? arrived.data ?? [])
    .filter((it) => !isForwarded(it));

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") arrived.reload(true);
    };
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [arrived.reload]);

  /* 전송·처리 직후에는 다음 폴링을 기다리지 않고 이 카드만 갱신한다. */
  useEffect(() => {
    if (refreshVersion > 0) arrived.reload(true);
  }, [refreshVersion, arrived.reload]);

  /* 처음에는 가장 먼저 접수한 사람을 선택한다. 이미 선택한 사람이 목록에
     남아 있으면 그대로 둔다. 다른 부서로 전송되어 사라진 경우에만 다음
     사람으로 자연스럽게 옮긴다. */
  useEffect(() => {
    if (rows.length === 0) {
      if (selectedId != null) onPick(null);
      return;
    }
    const exists = rows.some((it) => it.exam_order_id === selectedId);
    if (selectedId == null || !exists) onPick(rows[0].exam_order_id);
  }, [rows, selectedId, onPick]);

  return (
    <Card title="내원한 대기 환자" right={<span className="hint">자동 갱신</span>}
      className="n-queue-card" pad={false}>
      <Body loading={arrived.loading} error={arrived.error} onRetry={arrived.reload}>
        <Queue
          items={rows.map((it, i) => queueItem(it, i + 1))}
          value={selectedId}
          onPick={onPick}
          emptyText="내원한 대기 환자가 없습니다"
        />
      </Body>
    </Card>
  );
}

/* 환자 상세 + 문진(읽기 전용) + 간호 메모(편집 가능) + 검체 바인딩 ·
   유방외과 큐 전송. 문진은 exam_order.questionnaire를 그대로 훑어서
   보여준다 — 환자마다 항목이 다를 수 있어 고정 입력칸으로 안 만든다
   (간호과 명세 §1: "환자가 앱에서 낸 것을 그대로 본다"). */
function PatientDetail({ cfg, d, onAssigned }) {
  const [note, setNote] = useState(d.order_note ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [modal, setModal] = useState(null); // "specimen" | "assign"
  const patientInfo = useApi(
    () => (d.patient_id ? cfg.api.patient(d.patient_id) : Promise.resolve(null)),
    [cfg.api, d.patient_id],
  );
  const fullPatient = patientInfo.data;

  async function saveNote() {
    setSaving(true);
    setMsg(null);
    try {
      await cfg.api.saveNote(d.id, note);
      setMsg("간호 메모를 임시저장했습니다.");
    } catch (e) {
      setMsg(e.detail || "임시저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  const patient = {
    patient_id: d.patient_id, name: d.name, age: d.age, sex: d.sex,
    patient_number: d.patient_number,
  };
  const q = Object.entries(d.questionnaire ?? {});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Facts items={[
        ["환자", person(d)],
        ["환자번호", d.patient_number],
        ["생년월일", fullPatient?.pii?.birth_date],
        ["연락처", fullPatient?.pii?.phone],
        ["내원 구분", d.visit_type],
        ["알레르기", fullPatient?.has_allergy ? (fullPatient.allergy_note || "있음") : "없음"],
        ["접수 메모", d.order_note || "-"],
      ]} />

      <div>
        <p className="muted small" style={{ marginBottom: 8 }}>문진 (환자가 앱에서 제출 · 읽기전용)</p>
        {q.length === 0
          ? <p className="muted small">제출된 문진이 없습니다.</p>
          : <Facts items={q} />}
      </div>

      <label className="field">
        <span>간호 메모</span>
        <textarea value={note} onChange={(e) => setNote(e.target.value)}
          placeholder="인계할 내용을 적어 주세요" />
      </label>
      {msg && <div className="notice">{msg}</div>}

      <div className="stack" style={{ justifyContent: "flex-end" }}>
        <Btn kind="line" onClick={() => setModal("specimen")}>검체 바인딩</Btn>
        <Btn kind="line" onClick={saveNote} disabled={saving}>
          {saving ? "저장 중…" : "임시 저장"}
        </Btn>
        <Btn kind="fill" onClick={() => setModal("assign")}>유방외과 큐로 전송</Btn>
      </div>

      {modal === "specimen" && (
        <SpecimenBindingModal patient={patient} onClose={() => setModal(null)}
          onDone={() => setModal(null)} />
      )}
      {modal === "assign" && (
        <AssignModal cfg={cfg} patient={patient} onClose={() => setModal(null)}
          onDone={() => { setModal(null); onAssigned?.(); }} />
      )}
    </div>
  );
}

/* 의사 선택 팝업 — 고른 사람이 patient.primary_staff_id가 된다.
   유방외과는 선착순이 아니라 주치의로 이미 갈려 있어 "내 환자"가 곧
   큐다(간호과 명세 §1) — 그래서 배정은 되돌릴 수 없는 동작으로 다룬다. */
function AssignModal({ cfg, patient, onClose, onDone }) {
  const { loading, data, error, reload } = useApi(() => cfg.api.surgeons(), []);
  const [staffId, setStaffId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  /* 마우스뿐 아니라 키보드로도 즉시 닫는다. 실수로 연 배정 창에서
     작성 중이던 화면으로 빠르게 돌아갈 수 있어야 한다. */
  useEffect(() => {
    const escape = (e) => { if (e.key === "Escape" && !saving) onClose?.(); };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [onClose, saving]);

  useEffect(() => {
    if (!staffId && data?.results?.length) setStaffId(data.results[0].staff_id);
  }, [data, staffId]);

  async function confirm() {
    if (!staffId) return;
    setSaving(true);
    setErr(null);
    try {
      await cfg.api.assignSurgeon(patient.patient_id, staffId);
      onDone?.();
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>유방외과 큐로 전송 — {patient.name}</h2>
          <button aria-label="닫기" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p className="muted small">고른 의사가 이 환자의 주치의가 됩니다. 이후 그 의사의 화면에만 뜹니다.</p>
          <Body loading={loading} error={error} onRetry={reload}>
            <Table
              cols={[{ key: "name", label: "의사" }, { key: "role", label: "직책" }]}
              rows={(data?.results ?? []).map((s) => ({
                id: s.staff_id,
                name: s.full_name,
                role: s.staff_number,
              }))}
              value={staffId}
              onPick={setStaffId}
            />
          </Body>
          {err && <p className="warnline">⚠ {err}</p>}
        </div>
        <div className="modal-foot">
          <button className="btn line" onClick={onClose}>취소</button>
          <button className="btn fill" onClick={confirm} disabled={saving || !staffId}>
            {saving ? "전송 중…" : "전송"}
          </button>
        </div>
      </div>
    </div>
  );
}
