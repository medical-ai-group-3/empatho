import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { breast as api } from "../../../api";
import { SEX, label } from "../../../codes";
import { useApi } from "../../../lib/useApi";
import { Page } from "../../../lib/Page";
import { Body } from "../../../lib/Body";
import { go } from "../../../nav";
import "../breast.css";   /* 유방외과 전용 — .breast 안에 갇혀 있다. 네 화면이 각자
                             끌고 온다: 주소로 곧장 들어와도 스타일이 빠지면 안 된다 */
import ExamOrderModal from "../components/ExamOrderModal";
import CloseVisitModal from "../components/CloseVisitModal";
import SpecimenBindingModal from "../../../lib/SpecimenBindingModal";

/* 화면 1 · 대기 환자 · 진료 시작 ("/")
 *
 * 큐는 patient.primary_staff_id = 나(로그인한 주치의) 로 이미 갈려 있다.
 * 영상의학과·병리과처럼 assigned_to 로 집는 절차가 없다 — 내 환자가 곧 큐다.
 *
 * "확인 필요한 사항(영상/병리 불일치)" 섹션은 breast.html 레퍼런스에는
 * 없지만 명세서에는 있는 부분이라 여기서 새로 추가했다(정리본 §1 참고).
 *
 * 2·3·4번(뷰어·수술결정·검체바인딩)에서 한 건 끝내고 여기로 돌아오면
 * 다음 환자가 자동 선택된다 — location.state.advance 로 신호를 받는다. */
export default function Waiting() {
  const nav = useNavigate();
  const loc = useLocation();
  const { loading, data: list, error, reload } = useApi(() => api.waiting());
  const [selectedId, setSelectedId] = useState(null);
  const [modal, setModal] = useState(null); // "exam" | "specimen" | "close" | null

  useEffect(() => {
    if (!list || list.length === 0) return;
    /* 화면3(수술결정)·5(불일치처분)에서 돌아올 때는 이 화면이 통째로
     * 다시 마운트되어 selectedId가 null로 리셋된다 — "누구 다음"인지는
     * location.state.from(끝낸 환자 id)으로 받아야 한다. 검체 모달(#4)은
     * 같은 인스턴스 안에서 끝나므로 이 경로를 안 타고 바로 다음으로 넘어간다. */
    setSelectedId((cur) => {
      const from = loc.state?.advance ? loc.state.from : null;
      if (from && list.some((p) => p.patient_id === from)) {
        return nextAfter(list, from);
      }
      if (cur && list.some((p) => p.patient_id === cur)) return cur;
      return list[0].patient_id;
    });
    if (loc.state?.advance) nav(".", { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list]);

  function nextAfter(l, id) {
    const i = l.findIndex((p) => p.patient_id === id);
    return l[(i + 1) % l.length].patient_id;
  }

  const detail = usePatient(selectedId);

  return (
    <Page className="breast" crumb={["유방외과", "대기 환자"]}
            title="대기 환자" sub="내 환자 목록 · 진료 시작">
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {list && (
            <div className="split">
              <div className="card">
                <h3>대기 목록 ({list.length})</h3>
                <table className="list">
                  <thead>
                    <tr>
                      <th>환자번호</th><th>이름</th><th>나이/성별</th><th>진행상황</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((p) => (
                      <tr key={p.patient_id}
                          className={p.patient_id === selectedId ? "on" : ""}
                          onClick={() => setSelectedId(p.patient_id)}>
                        <td>{p.patient_number}</td>
                        <td>{p.name}</td>
                        <td>{p.age}세 · {label(SEX, p.sex)}</td>
                        <td>
                          <span className="pill wait">{p.status}</span>
                          {p.has_open_discordance && (
                            <span className="pill danger" style={{ marginLeft: 6 }}>불일치</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div>
                <Body loading={detail.loading} error={detail.error} onRetry={detail.reload}>
                  {detail.data && (
                    <PatientPanel
                      patient={detail.data}
                      onNext={() => setSelectedId(nextAfter(list, selectedId))}
                      onExamOrder={() => setModal("exam")}
                      onSpecimen={() => setModal("specimen")}
                      onClose={() => setModal("close")}
                      onReview={() => nav(go.breast.review(detail.data.patient_id))}
                      onDiscordance={() =>
                        nav(go.breast.discordance(detail.data.open_discordance.discordance_id))}
                    />
                  )}
                </Body>
              </div>
            </div>
          )}
        </Body>
      </div>

      {modal === "exam" && detail.data && (
        <ExamOrderModal patient={detail.data} onClose={() => setModal(null)}
          onDone={() => { setModal(null); }} />
      )}
      {modal === "specimen" && detail.data && (
        <SpecimenBindingModal patient={detail.data} onClose={() => setModal(null)}
          onDone={() => {
            setModal(null);
            setSelectedId((cur) => nextAfter(list, cur));
          }} />
      )}
      {modal === "close" && detail.data && (
        <CloseVisitModal patient={detail.data} onClose={() => setModal(null)}
          onDone={() => {
            setModal(null);
            setSelectedId((cur) => nextAfter(list, cur));
            reload(true);
          }} />
      )}
    </Page>
  );
}

function usePatient(id) {
  return useApi(() => (id ? api.patient(id) : Promise.resolve(null)), [id]);
}

/* 현재 환자 카드 하나 — 머리(아바타·이름) · 정보 · 알림 박스 · 버튼을
 * 전부 같은 카드 안에 두고, 버튼은 카드 우측 하단에 고정한다. 환자마다
 * 병변 개수·불일치 유무가 달라도 버튼이 카드 자체의 가장자리에 붙어
 * 있으니 다음 환자로 넘어갈 때 손이 버튼을 쫓아다닐 일이 없다.
 * 알림 박스도 "있으면 나타나고 없으면 사라지는" 것이 아니라 늘 같은
 * 자리에 있고 내용만(불일치 있음/없음) 바뀐다. */
function PatientPanel({ patient, onNext, onExamOrder, onSpecimen, onClose, onReview, onDiscordance }) {
  const d = patient.open_discordance;
  const rows = [
    { k: "성별·나이", v: `${label(SEX, patient.sex)} · ${patient.age}세` },
    { k: "내원 목적", v: patient.visit_purpose },
    { k: "알레르기", v: patient.allergy },
    { k: "주 증상", v: patient.chief_complaint },
    { k: "활력 징후", v: patient.vitals },
    { k: "가족력", v: patient.family_history },
    { k: "검사 이력", v: patient.exam_summary },
  ];
  return (
    <>
      <div className="card">
        <div className="pt-card-head">
          <h3>현재 환자 정보</h3>
          <span className="status pill wait">진료 중</span>
        </div>

        <div className="pt-head">
          <span className="avatar" aria-hidden="true">{patient.name[0]}</span>
          <span>
            <span className="name">{patient.name}</span>
            <p className="sub">{patient.patient_number} · {patient.visit_type}</p>
          </span>
        </div>

        <div className="pt-info">
          {rows.map((r) => (
            <div className="row" key={r.k}>
              <span className="k">{r.k}</span><span className="v">{r.v}</span>
            </div>
          ))}
        </div>

        <div className={d ? "notice danger" : "notice muted"}
          style={{ marginTop: 14, cursor: d ? "pointer" : "default" }}
          role={d ? "button" : undefined} onClick={d ? onDiscordance : undefined}>
          <span className="ic" aria-hidden="true">{d ? "⚠" : "ⓘ"}</span>
          <span>
            <b>확인 필요한 사항</b>
            {d ? (
              <>
                {d.violated_rule}
                <span className="hint">{d.lesion_id} · 클릭하면 불일치 처분 화면으로 이동합니다 →</span>
              </>
            ) : "영상/병리 불일치 없음"}
          </span>
        </div>

        <div className="pt-actions">
          <button className="btn ghost" onClick={onNext}>다음 환자</button>
          <div className="right-group">
            <button className="btn ghost" onClick={onExamOrder}>촬영 요청</button>
            <button className="btn ghost" onClick={onSpecimen}>검체 신청</button>
            {/* 명세서 §2-1 버튼은 [다음환자][촬영요청][검체신청][진료보기]
                4개였는데, "이상 없음 · 종결"을 다섯째로 추가했다 — 촬영이
                필요 없다고 판단되는 환자를 오더 없이 바로 닫는 길이
                없었다(CloseVisitModal.jsx 참고, 2026-09-18). */}
            <button className="btn ghost" onClick={onClose}>이상 없음 · 종결</button>
            <button className="btn" onClick={onReview}>진료 보기</button>
          </div>
        </div>
      </div>

      {patient.lesions?.length > 0 && (
        <div className="card">
          <h3>병변</h3>
          <table className="list">
            <thead><tr><th>병변</th><th>위치</th><th>크기</th><th>검체</th></tr></thead>
            <tbody>
              {patient.lesions.map((l) => (
                <tr key={l.lesion_id}>
                  <td>{l.lesion_id}</td><td>{l.site}</td><td>{l.size_mm}mm</td>
                  <td>{l.specimen_id ? <span className="pill ok">등록됨</span> : <span className="pill wait">필요</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
