import { useEffect, useState } from "react";
import { Page, Card, Btn } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { Chip, Facts, Queue, Locked, Table } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import { can } from "../../../perm";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";
import { SEX, label } from "../../../codes";

/* ═══ 1장 · 내원 대기 · 유방외과 배정 ══════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   지금 와 있는 환자를 접수 순서대로 보고 유방외과 의사에게 배정한다.
 *   [유방외과 큐로 전송]을 누르면 그 환자의 patient.primary_staff_id가
 *   고른 의사로 채워지고, 그때부터 그 의사의 "내 환자" 화면에만 뜬다
 *   (유방외과는 영상·병리처럼 선착순으로 집지 않는다 — 간호과 명세 §1).
 *
 * **왼쪽·오른쪽 아래가 다르다**
 *   왼쪽(내원한 대기 환자)  = 이미 와서 접수한 사람. requested·visited_at 있음
 *   오른쪽 아래(금일 내원 예정) = 오늘 올 예정인데 아직 안 온 사람. 보기만
 *
 * **순번은 표시 전용이다.** 원무가 접수한 순서 그대로다 — 드래그로
 * 못 바꾼다(간호과 명세가 명시적으로 확인해 준 부분).
 *
 * **왼쪽과 오른쪽 세로 길이를 맞춘다** — 오른쪽 두 카드(환자 상세정보 ·
 * 금일 내원 예정)를 합친 높이가 왼쪽 목록 높이와 같아야 한다는 지시가
 * 있었다. `.n-grid`/`.n-side-stack`(hospital.css)로 뷰포트 기준 높이를
 * 고정하고 넘치는 내용은 카드 안에서만 스크롤한다. */
export default function NursingWaiting({ cfg }) {
  if (!can("nursing.waiting.view")) {
    return (
      <Page crumb={[cfg.name, "내원 대기 · 유방외과 배정"]} title="내원 대기 · 유방외과 배정">
        <Locked what="내원 대기" />
      </Page>
    );
  }
  return <Inner cfg={cfg} />;
}

const POLL_MS = 7000;

function Inner({ cfg }) {
  const arrived = useApi(() => cfg.api.waitingArrived(), []);
  const today = useApi(() => cfg.api.scheduledToday(), []);
  const [selectedId, setSelectedId] = useState(null);
  const detail = useApi(
    () => (selectedId ? cfg.api.examOrder(selectedId) : Promise.resolve(null)),
    [selectedId],
  );

  /* 여럿이 보는 목록이라 주기적으로 다시 부른다 — 간호과 명세: 5~10초 폴링 */
  useEffect(() => {
    const t = setInterval(arrived.reload, POLL_MS);
    return () => clearInterval(t);
  }, [arrived.reload]);

  /* 처음 들어왔을 때 맨 위(가장 먼저 접수한 사람)를 자동으로 골라 둔다 */
  useEffect(() => {
    if (selectedId == null && arrived.data?.items?.length) {
      setSelectedId(arrived.data.items[0].id);
    }
  }, [arrived.data, selectedId]);

  const items = arrived.data?.items ?? [];

  return (
    <Page crumb={[cfg.name, "내원 대기 · 유방외과 배정"]}
          title="내원 대기 · 유방외과 배정"
          badge={`${items.length}명`}
          sub="접수 순번대로 정렬됩니다. 문진을 마치면 유방외과 큐로 보냅니다.">
      <div className="n-grid">
        <Card title="내원한 대기 환자" pad={false}>
          <Body loading={arrived.loading} error={arrived.error} onRetry={arrived.reload}>
            <Queue
              items={items.map((it, i) => ({
                id: it.id,
                no: i + 1,
                title: `${it.name} (${it.age}/${label(SEX, it.sex)})`,
                sub: `${it.patient_number} · ${it.visited_at} 접수 · ${it.visit_type}`,
                chip: it.status,
                chipTone: it.status === "문진 중" ? "fill" : "line",
              }))}
              value={selectedId}
              onPick={setSelectedId}
              emptyText="내원한 대기 환자가 없습니다"
            />
          </Body>
        </Card>

        <div className="n-side-stack">
          <Card title="환자 상세 정보" right={<Chip tone="line">문진 포함</Chip>}>
            {!selectedId
              ? <div className="slot"><b>왼쪽 목록에서 한 사람을 고르세요</b></div>
              : (
                <Body loading={detail.loading} error={detail.error} onRetry={detail.reload}>
                  {detail.data && <PatientDetail cfg={cfg} d={detail.data}
                    onAssigned={() => { setSelectedId(null); arrived.reload(); }} />}
                </Body>
              )}
          </Card>

          <Card title="금일 내원 예정" right={<span className="hint">예약 {today.data?.items?.length ?? 0}건</span>} pad={false}>
            <Body loading={today.loading} error={today.error} onRetry={today.reload}>
              <Table
                cols={[
                  { key: "who", label: "환자" },
                  { key: "time", label: "시간" },
                  { key: "kind", label: "구분" },
                ]}
                rows={(today.data?.items ?? []).map((it) => ({
                  id: it.id,
                  who: `${it.name} (${it.age}/${label(SEX, it.sex)})`,
                  time: it.time,
                  kind: <Chip tone={it.followup_id ? "dot" : "line"}>{it.followup_id ? "추적 관찰" : "예약"}</Chip>,
                }))}
              />
            </Body>
          </Card>
        </div>
      </div>
    </Page>
  );
}

/* 환자 상세 + 문진(읽기 전용) + 간호 메모(편집 가능) + 검체 바인딩 ·
   유방외과 큐 전송. 문진은 exam_order.questionnaire를 그대로 훑어서
   보여준다 — 환자마다 항목이 다를 수 있어 고정 입력칸으로 안 만든다
   (간호과 명세 §1: "환자가 앱에서 낸 것을 그대로 본다"). */
function PatientDetail({ cfg, d, onAssigned }) {
  const [note, setNote] = useState(d.note ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);
  const [modal, setModal] = useState(null); // "specimen" | "assign"

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
        ["환자", `${d.name} (${d.age}/${label(SEX, d.sex)})`],
        ["환자번호", d.patient_number],
        ["내원 구분", d.visit_type],
        ["알레르기", d.allergy || "없음"],
        ["주 증상", d.chief_complaint],
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

  useEffect(() => {
    if (!staffId && data?.items?.length) setStaffId(data.items[0].id);
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
              rows={(data?.items ?? []).map((s) => ({ id: s.id, name: s.name, role: s.role }))}
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
