import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { breast as api } from "../../../api";
import { SEX, label } from "../../../codes";
import { Body } from "../../../lib/Body";
import { Btn, Card, Page } from "../../../lib/Page";
import { go } from "../../../nav";
import { Facts, Search, Sort, Split, Table } from "../../../lib/Parts";
import { useApi } from "../../../lib/useApi";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";
import { historyTo } from "../history";

/* 유방외과 전체 환자 목록 ("/breast/patients")
 *
 * 영상의학과 전체 환자 목록과 같은 «왼쪽 목록 · 오른쪽 상세» 구조다.
 * 단, 유방외과에서는 판독을 쓰거나 정정하지 않으므로 그 두 행동은 두지
 * 않고 검사 종합 확인과 수술 결정으로만 이어진다. */
const SORTS = [
  { key: "name", label: "이름" },
  { key: "visited", label: "내원 순서" },
  { key: "status", label: "진료 구분" },
];

const COLS = [
  { key: "patient", label: "환자", w: "28%" },
  { key: "visit", label: "방문 구분", w: "18%" },
  { key: "visited", label: "첫 방문일", w: "20%" },
  { key: "status", label: "진료 구분", w: "18%" },
];

export default function Patients() {
  const [sort, setSort] = useState(SORTS[0].key);
  const [query, setQuery] = useState("");
  const [pickedId, setPickedId] = useState(null);
  const { loading, data: patients, error, reload } = useApi(() => api.patients());

  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const filtered = (patients ?? []).filter((patient) => !keyword ||
      [patient.name, patient.patient_number, patient.phone]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
    return [...filtered].sort((a, b) => sortPatients(a, b, sort));
  }, [patients, query, sort]);

  return (
    <Page className="breast breast-patients-page" crumb={["유방외과", "전체 환자 목록"]}
      title="전체 환자 목록">
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patients && (
            <Split
              side="third"
              empty="왼쪽 목록에서 환자를 고르면 상세 정보가 보입니다"
              left={
                <Card title={`환자 목록 (${patients.length})`}
                  right={<Search placeholder="환자명 · 등록번호 · 연락처" value={query} onChange={setQuery} />}
                  pad={false}>
                  <div className="tbl-top">
                    <Sort items={SORTS} value={sort} onChange={setSort} />
                  </div>
                  <Table cols={COLS} value={pickedId} onPick={setPickedId}
                    rows={visible.map(toRow)} />
                  <div className="tbl-foot">
                    <span>{patients.length}건 중 {visible.length}건 표시</span>
                    <span className="muted">대기 여부와 관계없이 등록된 환자입니다</span>
                  </div>
                </Card>
              }
              right={pickedId && <PatientDetail id={pickedId} />}
            />
          )}
        </Body>
      </div>
    </Page>
  );
}

function toRow(patient) {
  return {
    id: patient.patient_id,
    patient: `${patient.name || "이름 미등록"} (${patient.age ?? "—"}/${patient.sex ? label(SEX, patient.sex) : "—"})`,
    visit: patient.first_visited_at ? "방문 이력 있음" : "첫 방문 예정",
    visited: formatDate(patient.first_visited_at),
    status: <span className="pill wait">{patient.status || "—"}</span>,
  };
}

function sortPatients(a, b, sort) {
  if (sort === "name") return String(a.name ?? "").localeCompare(String(b.name ?? ""), "ko");
  if (sort === "status") return String(a.status ?? "").localeCompare(String(b.status ?? ""), "ko");
  if (sort === "visited") return String(b.first_visited_at ?? "").localeCompare(String(a.first_visited_at ?? ""));
  return String(a.patient_number ?? "").localeCompare(String(b.patient_number ?? ""));
}

function PatientDetail({ id }) {
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);

  return (
    <Card title="환자 요약" className="patients-detail-card"
          right={<Btn kind="fill" to={go.breast.review(id)}>환자 상세</Btn>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {patient && (
          <>
            <PatientDetailBody patient={patient} />
          </>
        )}
      </Body>
    </Card>
  );
}

function PatientDetailBody({ patient }) {
  const timeline = useApi(() => api.timeline(patient.patient_id), [patient.patient_id]);
  /* 검사 이력에서 고른 줄. 뷰어가 이 검사를 연다 — 고르기 전에는 null
     이고, 그때는 뷰어가 가장 최근 검사를 스스로 고른다. */
  const [pick, setPick] = useState(null);
  useEffect(() => { setPick(null); }, [patient.patient_id]);

  return (
    <div className="list-detail-cols">
      {/* 영상의학과 목록의 조회 전용 Viewer와 같은 자리다. 유방외과는
          판독 입력·판독 정정 도구를 이 화면에 노출하지 않는다. */}
      <div className="list-detail-viewer breast-list-viewer">
        <ReviewViewer patientId={patient.patient_id} lesions={patient.lesions ?? []}
                      studyId={pick} />
      </div>
      <div className="list-detail-info">
        <Facts items={[
          ["환자", `${patient.name || "—"} (${patient.age ?? "—"}/${patient.sex ? label(SEX, patient.sex) : "—"})`],
          ["등록번호", patient.patient_number || "—"],
          ["생년월일", patient.birth_date || "—"],
          ["연락처", patient.phone || "—"],
          ["알레르기", patient.allergy || "없음"],
          ["주치의", patient.primary_staff_name ? `${patient.primary_staff_name} 선생님` : "—"],
          ["내원 구분", patient.visit_type || "—"],
          ["검사 목적", patient.visit_purpose || "—"],
          ["간호 메모", patient.intake_note || "—"],
        ]} />
        <p className="section-label">검사 이력</p>
        <Body loading={timeline.loading} error={timeline.error} onRetry={timeline.reload}>
          {timeline.data && (
            <PatientTimeline pid={patient.patient_id} events={timeline.data}
                             pick={pick} onPick={setPick} />
          )}
        </Body>
      </div>
    </div>
  );
}

/* 검사 이력.
 *
 * 검사 번호(study_id)가 실려 온 줄은 누르면 위 뷰어가 그 검사를 연다.
 * 그 밖의 줄(검체 채취 · 병리 확진 · 번호 없는 줄)은 환자 상세로 가서
 * 그 건의 결과를 펴 본다(history.js). 전에는 이 줄들을 글자로만 두어
 * 병리 결과를 이력에서 열 길이 없었다.
 * 검사 줄도 판독 소견은 뷰어에 안 나온다 — 「판독 보기」로 따로 간다. */
function PatientTimeline({ pid, events, pick, onPick }) {
  if (events.length === 0) return <p className="muted small">아직 검사 이력이 없습니다.</p>;
  return (
    <ul className="exam-history">
      {events.map((event, index) => {
        const id = event.study_id ?? null;
        const on = id != null && String(id) === String(pick);
        const body = (
          <>
            <div className="exam-history-head">
              <span className="exam-history-type">{event.type}</span>
              <span className="exam-history-at">{event.at?.replace("T", " ").slice(0, 16)}</span>
            </div>
            {event.detail && <p className="exam-history-detail">{event.detail}</p>}
          </>
        );
        const to = historyTo(pid, event);
        return (
          <li key={index} className={on ? "on" : undefined}>
            {id == null
              ? <Link className="exam-history-pick" to={to}>{body}</Link>
              : (
                <>
                  <button type="button" className="exam-history-pick"
                          aria-pressed={on} onClick={() => onPick?.(on ? null : id)}>
                    {body}
                  </button>
                  <Link className="exam-history-go" to={to}>판독 보기 ›</Link>
                </>
              )}
          </li>
        );
      })}
    </ul>
  );
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value).slice(0, 10)
    : date.toLocaleDateString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" });
}
