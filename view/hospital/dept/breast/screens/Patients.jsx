import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { breast as api } from "../../../api";
import { SEX, label } from "../../../codes";
import { Body } from "../../../lib/Body";
import { Btn, Card, Page } from "../../../lib/Page";
import { go } from "../../../nav";
import { Chip, Search, Sort, Split, Table } from "../../../lib/Parts";
import { Two } from "../../../lib/ListCells";
import { shortAt } from "../../../lib/shortAt";
import { useApi } from "../../../lib/useApi";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";
import Stepper from "../components/Stepper";
import * as H from "../../home";
import { historyDetail, historyTo, toDecision } from "../history";
import { NEXT, PENDING_KEYS, flowOf } from "../flow";
import { briefOf } from "../results";

/* 유방외과 전체 환자 목록 ("/breast/patients")
 *
 * 영상의학과 전체 환자 목록과 같은 «왼쪽 목록 · 오른쪽 상세» 구조다.
 * 단, 유방외과에서는 판독을 쓰거나 정정하지 않으므로 그 두 행동은 두지
 * 않고 검사 종합 확인과 수술 결정으로만 이어진다.
 *
 * 09-28 — 목록 칸을 진료 쪽으로 바꿨다(최근 내원 · 최근 BI-RADS · B ·
 * 다음 할 일 · 불일치). 서버 worklist(scope=all)가 주는 값이다. 그 경로가
 * 없거나 칸이 없으면 「—」로 둔다 — 환자마다 상세를 부르면 목록 길이만큼
 * 요청이 나서 되짚지 않는다(고른 한 명만 오른쪽에서 되짚는다).
 * ⚠ 첫 줄을 저절로 고른다 — 오른쪽이 「고르면 보입니다」로 비어 있었다.
 * ⚠ 오른쪽의 환자 정보 아홉 줄(연락처 · 간호 메모 …)을 뺐다. 고른 사람이
 *   지금 어디까지 왔는지(단계 줄)와 결과 한 줄이 그 자리에 더 쓸모 있다. */
const SORTS = [
  { key: "name", label: "이름" },
  { key: "visited", label: "내원 순서" },
  { key: "status", label: "다음 할 일" },
];

/* 09-28 — 여섯 칸이 목록 폭(440px)에 안 들어 1280 창에서 끝 칸(불일치)이
   목록 밖으로 잘리고 이름이 「김영희 (41/ / 여)」로 꺾였다.
   · BI-RADS · B 를 한 칸(「4b · B3」)으로, 불일치는 다음 할 일 칸의 칩으로
   · 나이 · 성별 · 등록번호는 이름 밑 둘째 줄, 알레르기는 이름 옆 작은 표시
   · 이름 칸만 남는 폭을 받고 나머지는 값 폭만큼(Table cls) */
const COLS = [
  { key: "patient", label: "환자", cls: "c-grow" },
  { key: "visited", label: "최근 내원", cls: "c-fit" },
  { key: "grade", label: "BI-RADS · B", cls: "c-fit" },
  { key: "next", label: "다음 할 일", cls: "c-fit" },
];

export default function Patients() {
  const [sort, setSort] = useState(SORTS[0].key);
  const [query, setQuery] = useState("");
  const [pickedId, setPickedId] = useState(null);
  const { loading, data: patients, error, reload } = useApi(() => api.patients(), [], { live: true });
  /* 서버 worklist — 없으면 null 이고 진료 칸이 「—」로 빈다 */
  const wl = useApi(() => api.worklist("all").catch(() => null), [], { live: true });
  const items = useMemo(() => new Map(H.rows(wl.data).map((it) => [String(it.patient_id), it])),
    [wl.data]);

  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    const filtered = (patients ?? []).filter((patient) => !keyword ||
      [patient.name, patient.patient_number, patient.phone]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(keyword)),
    );
    return [...filtered].sort((a, b) => sortPatients(a, b, sort, items));
  }, [patients, query, sort, items]);
  const picked = pickedId ?? visible[0]?.patient_id ?? null;

  return (
    <Page className="breast breast-patients-page" crumb={["유방외과", "전체 환자"]}
      title="전체 환자">
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {patients && (
            <Split
              side="third"
              empty="왼쪽 목록에서 환자를 선택하면 요약이 표시됩니다"
              left={
                <Card title={`환자 목록 (${patients.length})`}
                  right={<Search placeholder="환자명 · 등록번호 · 연락처" value={query} onChange={setQuery} />}
                  pad={false}>
                  <div className="tbl-top">
                    <Sort items={SORTS} value={sort} onChange={setSort} />
                  </div>
                  <Table cols={COLS} value={picked} onPick={setPickedId}
                    emptyText={patients.length ? "검색에 맞는 환자가 없습니다" : "아직 등록된 환자가 없습니다"}
                    rows={visible.map((p) => toRow(p, items.get(String(p.patient_id))))} />
                  <div className="tbl-foot">
                    <span>{patients.length}건 중 {visible.length}건 표시</span>
                    <span className="muted">대기 여부와 관계없이 등록된 모든 환자를 표시합니다</span>
                  </div>
                </Card>
              }
              right={picked
                ? <PatientDetail id={picked} item={items.get(String(picked))} />
                /* 고를 사람이 없을 때 — 전에는 오른쪽 위에 점선 띠 하나만 뜨고
                   나머지가 통째로 비었다. 요약 카드 자리를 그대로 두고 까닭을 적는다 */
                : (
                  <Card title="환자 요약" className="patients-detail-card">
                    <div className="bf-pl-empty">
                      <b>{patients.length ? "검색에 맞는 환자가 없습니다" : "아직 등록된 환자가 없습니다"}</b>
                      <span>{patients.length
                        ? "이름 · 등록번호 · 연락처 중 하나로 다시 찾아 주세요."
                        : "간호 접수에서 환자를 등록하면 이 목록에 나타납니다. 환자를 고르면 진료 단계와 검사 이력이 여기에 표시됩니다."}</span>
                    </div>
                  </Card>
                )}
            />
          )}
        </Body>
      </div>
    </Page>
  );
}

function toRow(patient, it) {
  const next = it?.next_step ? NEXT[it.next_step] : null;
  const odd = it ? it.open_discordance : patient.has_open_discordance;
  const bcat = it?.latest_b_category ?? it?.b_category ?? null;
  /* 서버 worklist 가 싣는 최근 판정 — 칸 이름이 정해지기 전이라 둘 다 본다 */
  const birads = it?.latest_birads ?? it?.birads ?? null;
  const grade = [birads, bcat ? `B${String(bcat).toUpperCase().replace(/^B/, "")}` : null]
    .filter(Boolean).join(" · ");
  const allergic = Boolean(H.allergy(patient) || it?.has_allergy);
  const name = patient.name || "이름 미등록";
  return {
    id: patient.patient_id,
    patient: (
      <Two strong title={name}
           main={<>{name}{allergic && <i className="lst-flag">알레르기</i>}</>}
           sub={[H.who(patient), patient.patient_number].filter(Boolean).join(" · ")} />
    ),
    /* 「09-21」 — 날짜만(올해가 아니면 「25-09-21」) */
    visited: shortAt(String(it?.last_visit_at ?? patient.last_visit_at ?? patient.first_visited_at ?? "").slice(0, 10)) ?? "—",
    grade: grade || "—",
    next: (next || odd) ? (
      <span className="lst-chips">
        {next && <Chip tone={PENDING_KEYS.includes(it.next_step) ? "fill" : "line"}>{next.name}</Chip>}
        {odd && <Chip tone="fill">불일치</Chip>}
      </span>
    ) : "—",
  };
}

function sortPatients(a, b, sort, items) {
  if (sort === "name") return String(a.name ?? "").localeCompare(String(b.name ?? ""), "ko");
  if (sort === "status") {
    /* 다음 할 일 — 흐름 순서. 모르는 사람은 뒤로 */
    const at = (p) => {
      const i = Object.keys(NEXT).indexOf(items?.get(String(p.patient_id))?.next_step);
      return i < 0 ? 99 : i;
    };
    return at(a) - at(b);
  }
  if (sort === "visited") {
    const v = (p) => items?.get(String(p.patient_id))?.last_visit_at ?? p.last_visit_at ?? p.first_visited_at ?? "";
    return String(v(b)).localeCompare(String(v(a)));
  }
  return String(a.patient_number ?? "").localeCompare(String(b.patient_number ?? ""));
}

function PatientDetail({ id, item }) {
  const { loading, data: patient, error, reload } = useApi(() => api.patient(id), [id]);

  return (
    <Card title="환자 요약" className="patients-detail-card"
          right={(
            <>
              <Btn to={go.breast.decision(id)}>치료 방침</Btn>
              <Btn to={go.breast.review(id)}>환자 상세</Btn>
            </>
          )}>
      <Body loading={loading && !patient} error={error} onRetry={reload}>
        {patient && String(patient.patient_id) === String(id) && (
          <PatientDetailBody key={id} patient={patient} item={item} />
        )}
      </Body>
    </Card>
  );
}

function PatientDetailBody({ patient, item }) {
  const nav = useNavigate();
  const timeline = useApi(() => api.timeline(patient.patient_id), [patient.patient_id]);
  const flow = useMemo(() => flowOf({ p: patient, item, timeline: H.rows(timeline.data) }),
    [patient, item, timeline.data]);
  const brief = briefOf(patient);
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
        <div className="bf-pl-h">
          <b>{patient.name || "—"}</b>
          <span className="muted">
            {[patient.age != null ? `${patient.age}세` : null, patient.sex ? label(SEX, patient.sex) : null,
              patient.patient_number, patient.primary_staff_name ? `주치의 ${patient.primary_staff_name}` : null]
              .filter(Boolean).join(" · ")}
          </span>
          {H.some(patient.allergy) && <Chip tone="fill">알레르기 · {H.some(patient.allergy)}</Chip>}
        </div>
        <p className="bf-pl-brief">{brief ?? "확정된 판독 · 병리 결과가 아직 없습니다"}</p>
        <Stepper steps={flow.steps} col />
        {flow.next && (
          <div className="bf-pl-next">
            <span className="muted small">다음 할 일</span>
            <b>{flow.next.label}</b>
            <span className="home-fill" />
            {/* 팝업으로 하는 일(촬영 요청 · 진료 완료 · 재진)은 대기 환자에서 한다 */}
            <Btn kind="fill" onClick={() => nav(flow.next.to ?? go.breast.waiting())}>
              {flow.next.to ? "바로 가기 →" : "대기 환자에서 열기 →"}
            </Btn>
          </div>
        )}
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
 * 검사 줄도 판독 소견은 뷰어에 안 나온다 — 「판독 보기」로 따로 간다.
 * 치료 결정 · 리포트 · 결과 설명 · 처방은 치료 방침으로 간다.
 * ⚠ 치료 결정도 study_id 를 싣지만 뷰어로 열 검사가 아니다 — 번호로
 *   가르면 「판독 보기」가 붙는다. 종류로 먼저 가른다(toDecision). */
function PatientTimeline({ pid, events, pick, onPick }) {
  if (events.length === 0) return <p className="muted small">아직 검사 이력이 없습니다.</p>;
  return (
    <ul className="exam-history">
      {events.map((event, index) => {
        const id = toDecision(event) ? null : event.study_id ?? null;
        const say = historyDetail(event);
        const on = id != null && String(id) === String(pick);
        const body = (
          <>
            <div className="exam-history-head">
              <span className="exam-history-type">{event.type}</span>
              <span className="exam-history-at">{event.at?.replace("T", " ").slice(0, 16)}</span>
            </div>
            {say && <p className="exam-history-detail">{say}</p>}
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
