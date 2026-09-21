import { Suspense, lazy, useState } from "react";
import { rad } from "../api";
import { go } from "../nav";
import { Chip, Facts, Fold, Warn, useCan } from "../lib/Parts";
import { Body } from "../lib/Body";
import RadiologyAi from "./RadiologyAi";
import Stage, { polygonsFromAi } from "../lib/Stage";
import { useApi } from "../lib/useApi";
import { useFile } from "../lib/files";
import { BIRADS, MODALITY, READ_STATUS, SEX, label, modality as asModality, text, tone }
  from "../codes";

/* 영상 판독(screens/Read.jsx)과 환자 목록(screens/List.jsx) 둘 다 같은
 * 규칙으로 뷰어에 무엇을 얹을지 정한다 — read.stage 하나였는데
 * list.Detail 에도 같은 뷰어를 붙이면서(2026-09-18, 환자 목록 설계)
 * 한 객체 리터럴 안에서 read.stage 를 list 쪽이 부를 수가 없어(자기
 * 자신을 아직 다 만들기 전이라) 바깥으로 뺐다. */
const MRIReviewGrid = lazy(() => import("../lib/dicom/MRIReviewGrid"));
const DicomStackViewer = lazy(() => import("../lib/dicom/DicomStackViewer"));

function radStage(d, i = 0) {
  if (d.unit?.modality === "mri") {
    return { volumeManifest: d.volume_manifest, volumeBase: d.volume_base };
  }
  if (d.unit?.modality === "mammo") {
    return { stackManifest: d.stack_manifest, stackBase: d.stack_base };
  }

  const s = (d.series ?? [])[i];
  const ai = d.ai;
  let shapes = [];
  const abstained = ai?.abstained ?? ai?.summary?.abstained;
  if (ai && !abstained && ai.lesion_found !== false) {
    if (asModality(ai.modality) === "us") shapes = polygonsFromAi(ai);
  }
  return {
    image: s?.image,
    maskImage: null,
    w: s?.w, h: s?.h, alt: s?.name,
    shapes,
  };
}

/* 영상의학과 설정 — 공통 화면 다섯 장에 끼워 넣는 «다른 점»만 모은 파일
 * ════════════════════════════════════════════════════════════════
 *
 * 병리과와 갈리는 지점
 *   판독 단위   검체가 아니라 **검사(study)**. 대기 큐는 **오더(exam_order)**
 *   등급 체계   B 분류가 아니라 **BI-RADS**
 *   AI 소견     모달리티 셋이 서로 다른 것을 낸다 (초음파 · 맘모 · MRI)
 *   정정 이력   JSONB 가 아니라 **새 assessment 행 + superseded_by**
 *   여기만 있는 것
 *     · 조영제 알레르기 경고 — 촬영 전 반드시 보여야 한다
 *     · 재촬영 요청 — 새 오더를 만든다 (parent_order_id)
 *     · 병변 직접 추가 · 오탐 표시
 *     · 모달리티 구분
 *
 * 한 단계 더 있다
 *   업로드 확정이 오더 확정(PATCH …/complete)과 분석 시작 두 번으로
 *   나뉜다. 병리에는 오더가 없어 이 단계가 없다.
 */

const api = {
  queue:      ()      => rad.queue(),
  detail:     (id)    => rad.order(id),      /* 1장 큐 — 오더를 본다 */
  listDetail: (id)    => rad.study(id),      /* 4장 목록 — 검사를 본다 */
  assign:     (id)    => rad.assign(id),
  /* 집은 뒤 Study 를 만든다. 병리에는 이 단계가 없다 — 검체는 이미
     존재하고, 영상은 「촬영 시작」이 곧 Study 생성이다 */
  start:      (id)    => rad.start(id),
  uploadInfo: (id)    => rad.uploadInfo(id),
  /* ⚠ 판독 화면(3장)이 원본을 받을 때 쓴다. 빠지면 티켓을 못 받아
     **아무 말 없이 빈 뷰어**가 된다 — 목업은 image.url 로 와서
     티켓을 안 타기 때문에 목업에서만 멀쩡해 보인다 (lib/files.js) */
  ticket:     (b)     => rad.ticket(b),

  /* 오더 확정 — 병리에는 없는 단계.
   *
   * ⚠ **여기만 단위가 다르다.** 화면들이 들고 다니는 id 는 study_id 다.
   *   큐에서 오더를 집은 뒤 start-study 가 만들어 준 것이고, 업로드 ·
   *   분석 · 판독이 전부 그것으로 움직인다. 그런데 확정은 오더 표를
   *   건드리는 일이라 **exam_order_id** 가 맞다. start-study 응답에
   *   둘이 같이 오는 이유가 그것이다 ({ study_id, exam_order_id }).
   *
   *   전에는 study_id 를 그대로 /exam-orders/{id}/complete 에 넣고
   *   있었다. 목업은 {id} 자리에 아무 값이나 받아 주어서 안 드러났지만,
   *   진짜 서버에서는 404 이고 — 번호 체계가 겹치는 순간 **남의 오더를
   *   확정한다.**
   *
   *   **서버에 칸을 더해 달라고 기다릴 필요는 없다.** 큐에서 집을 때
   *   이미 그 번호를 손에 쥔다 — 집은 것이 곧 오더이고, start-study 도
   *   `{ study_id, exam_order_id }` 를 같이 준다. 1장이 그것을 2장으로
   *   들려 보내고(screens/Queue.jsx), 2장이 여기 d 에 실어 준다.
   *
   *   새로고침으로 2장에 바로 들어오면 그 번호가 없다. 그때는 조회
   *   응답에 실려 온 것을 쓰고, 그것도 없으면 **확정을 건너뛴다.**
   *   빠뜨린 확정은 나중에 다시 걸 수 있지만, 엉뚱한 오더를 확정한
   *   것은 되돌릴 수 없다 */
  complete:   (id, d) => {
    const orderId = d?.exam_order_id ?? d?.order_id ?? null;
    return orderId ? rad.complete(orderId) : Promise.resolve(null);
  },

  /* 정정 이력을 따로 부르는 길. **api.js 에 진작 있었는데 아무도 안
     불렀다.** 판독 응답에 history 가 실려 오면 그것을 쓰고, 안 오면
     5장이 이걸로 받아 온다 (screens/Amend.jsx) */
  history:    (id)    => rad.history(id),
  analyze:    (id)    => rad.analyze(id),
  progress:   (id)    => rad.progress(id),
  /* 원본 응답과 업로드 파일 목록을 화면 계약으로 합치는 일은 api.js가 맡는다. */
  read:       (id)    => rad.read(id),
  draft:      (id, b) => rad.draft(id, b),
  finalize:   (id, b) => rad.finalize(id, b),
  list:       (o)     => rad.list(o),
  amend:      (id, b) => rad.amend(id, b),
  addLesion:  (b)     => rad.addLesion(b),
  /* 환자 목록(4장) 상세에 검사 이력을 붙이려고 추가했다(2026-09-18) */
  timeline:   (pid)   => rad.timeline(pid),
};

/* 환자 목록(4장) 상세용 뷰어 — 판독 화면(screens/Read.jsx)과 같은 규칙
 * (radStage)으로 무엇을 그릴지 정하지만, 여기는 **조회 전용**이다.
 * 병변 추가 · 오탐 표시 같은 판독 도구는 없다 — mode="review"를 그대로
 * 넘긴다(공통 영상 Viewer 설계, 2026-09-17 문서 — 아직 컴포넌트 쪽
 * mode 게이팅이 다 구현되진 않았지만 값은 미리 넘겨 둔다). */
function ListViewer({ d, cfg, slide, onSlide, bright, contrast, mask }) {
  const view = radStage(d, slide);
  const isVolume = Boolean(view.volumeManifest);
  const isStack = Boolean(view.stackManifest);
  const isCornerstone = isVolume || isStack;
  const scope = { kind: cfg.scopeKind, id: d.id };
  const img = useFile(view.image, cfg.api.ticket, scope);
  const msk = useFile(view.maskImage, cfg.api.ticket, scope);

  return (
    <div className="list-viewer">
      {isVolume ? (
        <Suspense fallback={<div className="mri-loading">MRI 뷰어 불러오는 중…</div>}>
          <MRIReviewGrid lesions={d.lesions}
            study={{ volume_manifest: view.volumeManifest, volume_base: view.volumeBase }}
            mode="review" />
        </Suspense>
      ) : isStack ? (
        <Suspense fallback={<div className="mri-loading">맘모 뷰어 불러오는 중…</div>}>
          <DicomStackViewer manifestUrl={view.stackManifest} baseUrl={view.stackBase} mode="review" />
        </Suspense>
      ) : (
        <Stage
          src={img.src} w={view.w} h={view.h} alt={view.alt}
          loading={img.loading} loadError={img.error}
          bright={bright} contrast={contrast}
          mask={msk.src} shapes={view.shapes ?? []}
          opacity={mask}
        />
      )}
      {!isCornerstone && (d.series ?? []).length > 1 && (
        <div className="list-viewer-slides">
          {d.series.map((s, i) => (
            <button type="button" key={s.id ?? i}
              className={i === slide ? "on" : ""}
              onClick={() => onSlide(i)}>{s.name}</button>
          ))}
        </div>
      )}
    </div>
  );
}

/* 검사 이력 — 유방외과 Review.jsx 의 Timeline과 같은 모양(hospital.css
 * 의 공용 .timeline 클래스). 서버 PatientTimelineView는 {at, type,
 * detail, assessment_id} 를 준다 — label 없이 type 자체가 이미 한글
 * ("촬영"·"AI 분석 완료"·"판독" 등)이라 그대로 제목으로 쓴다. */
/* ⚠ 2026-09-18 — 타임라인(점+세로선) 모양 말고 리스트로 달라는 요청.
 * 유방외과 Review.jsx 것과 갈라져서, 여기는 새 클래스(exam-history)를
 * 쓴다 — 줄마다 한 항목, 왼쪽 종류·오른쪽 시각, 그 아래 detail. */
function ListTimeline({ events }) {
  if (!events?.length) {
    return <p className="muted small">아직 검사 이력이 없습니다.</p>;
  }
  return (
    <ul className="exam-history">
      {events.map((e, i) => (
        <li key={i}>
          <div className="exam-history-head">
            <span className="exam-history-type">{e.type}</span>
            <span className="exam-history-at">{e.at?.replace("T", " ").slice(0, 16)}</span>
          </div>
          {e.detail && <p className="exam-history-detail">{e.detail}</p>}
        </li>
      ))}
    </ul>
  );
}

export const radiology = {
  key: "radiology",
  name: "영상의학과",
  api,
  go: go.radiology,

  /* 티켓이 여는 범위의 단위 — 영상은 검사(study)다.
     ⚠ 이 화면들이 들고 다니는 id 가 study_id 라 그대로 맞는다.
     맘모 원본·MRI 시리즈(DICOM)는 이 범위로 못 받는다 — 서버가
     DICOM 범위의 티켓을 사람에게 안 내준다 (lib/files.js 참고) */
  scopeKind: "study",

  /* ── 1장 · 촬영 대기 큐 ───────────────────────────────── */
  queue: {
    title: "촬영 대기 큐",
    sub: "유방외과가 낸 오더 중 아직 아무도 집지 않은 것이 요청 순서대로 뜹니다. 집으면 다른 선생님 화면에서 사라집니다.",
    listTitle: "촬영 대기 오더",
    searchHint: "환자 · 환자번호",
    emptyText: "촬영 대기 중인 오더가 없습니다",
    need: { view: "radiology.queue.view", assign: "radiology.queue.assign" },

    row: (it) => ({
      id: it.id,
      title: `${it.patient_name} (${it.age}/${label(SEX, it.sex)})`,
      sub: `${it.patient_no} · ${label(MODALITY, asModality(it.modality))}`,
      chip: it.contrast_allergy ? "조영제 알레르기" : it.device,
      chipTone: it.contrast_allergy ? "fill" : "line",
    }),

    Detail: ({ d }) => (
      <>
        {/* 촬영 전에 반드시 보여야 하는 값이라 맨 위에 세운다 */}
        {d.contrast_allergy && <Warn>조영제 알레르기 — {d.contrast_allergy}</Warn>}

        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
          ["환자번호", d.patient_no],
          ["생년월일", d.birth_date],
          ["연락처", d.phone],
          ["알레르기", d.contrast_allergy || "없음"],
          ["모달리티", label(MODALITY, asModality(d.modality))],
          ["촬영 장비", d.device],
          ["검사명", d.exam_name],
          ["요청 일시", d.ordered_at],
          ["요청한 의사", d.ordered_by],
        ]} />

        {d.purpose && (
          <Fold title="검사 목적">
            <p className="quote">{d.purpose}</p>
          </Fold>
        )}
      </>
    ),
  },

  /* ── 2장 · 촬영 업로드 ────────────────────────────────── */
  upload: {
    title: "촬영 업로드",
    sub: "촬영본을 올리고 AI 분석을 겁니다. 분석이 끝나야 판독으로 넘어갑니다.",
    infoTitle: "환자 · 검사 정보",
    dropText: "촬영본을 드래그하세요",
    accept: ".dcm,.zip,image/*,video/*",
    estimate: "초음파 약 0.4초 · 맘모 약 33.5초(4뷰) · MRI 약 175초. MRI 는 화면 앞에서 기다리지 않아도 됩니다 — 큐로 나갔다 들어와도 진행 상태가 그대로 보입니다.",
    need: {
      view: "radiology.upload.view",
      send: "radiology.upload.send",
      run: "radiology.ai.run",
    },
    notes: [
      "맘모는 양측 CC/MLO 4뷰를 올립니다.",
      "초음파는 프레임 또는 클립 단위로 올립니다.",
      "MRI 는 DICOM 시리즈를 zip 으로 묶어 올립니다 — 추론이 그렇게 받습니다.",
      "파일은 Django 를 거치지 않고 Go 관문으로 곧장 올라갑니다.",
      "분할 업로드는 시작·조각·완료마다 티켓을 새로 받습니다.",
    ],

    Info: ({ d }) => (
      <>
        {d.contrast_allergy && <Warn>조영제 알레르기 — {d.contrast_allergy}</Warn>}
        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
          ["환자번호", d.patient_no],
          ["생년월일", d.birth_date],
          ["연락처", d.phone],
          ["알레르기", d.contrast_allergy || "없음"],
          ["검사명", d.exam_name],
          ["검사 목적", d.purpose],
          ["검사일", d.performed_at],
          ["모달리티", label(MODALITY, asModality(d.modality))],
        ]} />

        <Fold title={`시리즈 ${(d.series ?? []).length}`}>
          <ul className="slides">
            {(d.series ?? []).map((s) => (
              <li key={s.id}>
                <label className="ck">
                  <input type="checkbox" defaultChecked />
                  <span>{s.name}</span>
                  <small>{s.count}장</small>
                </label>
              </li>
            ))}
            {(d.series ?? []).length === 0 && <li className="none">시리즈가 없습니다</li>}
          </ul>
        </Fold>
      </>
    ),

    /* 품질 반려된 원본 오더에서만 서버가 재촬영을 만든다. 새 오더는
       곧바로 영상의학과 대기 큐로 들어가므로 원무 재접수는 필요 없다. */
    Extra: ({ d, cfg }) => <RetakeButton examOrderId={d.exam_order_id} api={cfg.api} />,
  },

  /* ── 3장 · 판독 ───────────────────────────────────────── */
  read: {
    title: "영상 판독",
    sub: "원본 영상에 AI 오버레이를 얹어 보고 소견을 씁니다.",
    infoName: "환자 정보",
    saveHint: "저장하면 판정이 확정되고 유방외과로 전달됩니다. 되돌릴 수 없습니다.",
    need: {
      view: "radiology.read.view",
      ai: "radiology.ai.view",
      draft: "radiology.read.draft",
      finalize: "radiology.read.finalize",
    },
    /* MRI는 등급(BI-RADS)을 안 낸다 — 모델 구조상 없는 값이고, AI
       소견(RadiologyAi.jsx의 Mri())도 등급을 안 보여준다. 그래서 저장
       가능 여부도 판독 소견 유무로 본다. 나머지 모달리티는 등급 선택이
       곧 판독의 핵심이라 그대로 category로 가른다. */
    ready: (f, d) => d?.unit?.modality === "mri"
      ? Boolean(f.finding_note?.trim())
      : Boolean(f.category),

    /* 뷰어에 무엇을 얹나 — 모달리티마다 다르다.
         맘모    공통 영상 Viewer 설계(2026-09-17) 3단계 — DICOM이라
                 Cornerstone 기반 DicomStackViewer로 그린다. stack은
                 Volume이 아니라 R-CC·R-MLO·L-CC·L-MLO 같은 개별 뷰
                 여러 장이라 stackManifest로 따로 분기한다(MRI의
                 volumeManifest와 나란한 계약, 뷰어만 다르다).
         초음파  폴리곤 좌표(SVG). 마스크 파일이 없다. 아직 Stage.jsx다
         MRI     원본이 한 장이 아니라 DICOM Series 전체(Volume)다 —
                 2D 이미지 자리에 못 얹는다. volumeManifest를 주면
                 화면(screens/Read.jsx)이 이미지 대신 Cornerstone3D
                 기반 DicomMprPanel(Axial/Coronal/Sagittal)을 그린다.
       좌표를 도형으로 바꾸는 자리는 lib/Stage.jsx 아래쪽에 모아 두었다.
       실제 함수는 파일 위쪽의 radStage() — list.Detail 도 같이 쓴다. */
    stage: radStage,

    Info: ({ d, slide, onSlide }) => {
      const isMri = d.unit?.modality === "mri";
      /* 맘모도 이제 DicomStackViewer(휠로 뷰 전환)를 쓴다 — MRI와 같은
         이유로 "골라서 화면에 끼우는" 목록이 아니라 "뭐가 있는지"만
         보여주는 목록이어야 한다. onSlide는 더 이상 맘모에 안 먹힌다. */
      const isCornerstone = isMri || d.unit?.modality === "mammo";
      return (
        <>
          {d.patient.contrast_allergy && <Warn>조영제 알레르기 — {d.patient.contrast_allergy}</Warn>}
          <Facts items={[
            ["환자", `${d.patient.name} (${d.patient.age}/${label(SEX, d.patient.sex)})`],
            ["환자번호", d.patient.no],
            ["생년월일", d.patient.birth_date],
            ["연락처", d.patient.phone],
            ["알레르기", d.patient.contrast_allergy || "없음"],
            ["검사명", d.unit.exam_name],
            ["모달리티", label(MODALITY, asModality(d.unit.modality))],
            ["검사 상태", text(d.unit, "read_status", READ_STATUS, "status_label")],
          ]} />

          {isCornerstone ? (
            /* MRI·맘모는 초음파처럼 시리즈 하나를 골라 화면에 바꿔
               끼우는 게 아니다 — DicomMprPanel/DicomStackViewer가 전체를
               한 번에 받아 그린다(맘모는 휠로 뷰 전환). 그래서 골라 «보는»
               버튼이 아니라, 뭐가 찍혔는지 알려주는 목록으로만 둔다.
               클릭 가능한 것처럼 보이면 「눌렀는데 왜 안 바뀌지」가 된다. */
            <Fold title={`${isMri ? "촬영 Phase" : "촬영 뷰"} ${(d.series ?? []).length}`}>
              <ul className="slides mri-phases">
                {(d.series ?? []).map((s) => <li key={s.id}>{s.name}</li>)}
              </ul>
              <p className="muted small">
                {isMri
                  ? "Volume 하나로 합쳐져 있어 오른쪽 뷰어에 한 번에 나옵니다. 골라도 화면은 안 바뀝니다."
                  : "오른쪽 뷰어에서 휠로 뷰를 넘겨 봅니다. 골라도 화면은 안 바뀝니다."}
              </p>
            </Fold>
          ) : (
            <Fold title={`시리즈 ${(d.series ?? []).length}`}>
              <ul className="slides">
                {(d.series ?? []).map((s, i) => (
                  <li key={s.id} className={slide === i ? "on" : undefined}>
                    <button onClick={() => onSlide?.(i)}>{s.name}</button>
                  </li>
                ))}
              </ul>
            </Fold>
          )}
        </>
      );
    },

    Ai: RadiologyAi,

    Doctor: ({ d, f, set, pendingMark, onLesionCreated }) => {
      const add = useCan("radiology.lesion.add");
      const isMri = d.unit?.modality === "mri";
      const [lesionBusy, setLesionBusy] = useState(false);
      const [lesionMsg, setLesionMsg] = useState(null);

      async function addLesion() {
        if (!pendingMark) return;
        setLesionBusy(true); setLesionMsg(null);
        try {
          const out = await api.addLesion({
            study_id: Number(d.id),
            detail: { ...pendingMark },
          });
          setLesionMsg(`병변 #${out.lesion_id ?? out.id}을 등록했습니다.`);
          onLesionCreated?.();
        } catch (e) {
          setLesionMsg(e.detail || "병변 등록에 실패했습니다.");
        } finally { setLesionBusy(false); }
      }

      return (
        <>
          {/* MRI 모델은 BI-RADS를 안 낸다 — 등급 선택도, 「영상에 박스를
              그려 병변을 만든다」는 것도 2D 검출 모델(맘모·초음파) 얘기라
              여기선 뺀다. 판독 소견만 쓴다. */}
          {!isMri && (
            <>
              {/* ⚠ AI 가 낸 등급(lesion.birads_model)과 다른 컬럼이다.
                  한 화면에 있지만 섞이지 않게 자리를 갈라 둔다 */}
              <label className="field">
                <span>판정 등급 (BI-RADS)</span>
                <select value={f.category ?? ""} onChange={(e) => set("category", e.target.value)}>
                  <option value="">선택하세요</option>
                  {BIRADS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>

            </>
          )}

          <div className="stack">
            <button className="btn line" onClick={addLesion}
                    disabled={!add.ok || !pendingMark || lesionBusy}
                    title={!add.ok ? add.attrs.title : pendingMark ? "방금 그린 표시를 병변으로 등록합니다" : "뷰어에서 박스를 먼저 그려 주세요"}>
              {lesionBusy ? "등록 중…" : "병변 등록"}
            </button>
            <span className="muted small">
              {pendingMark ? "뷰어에 그린 표시를 병변으로 등록할 수 있습니다." : "뷰어에서 박스 그리기 후 병변 등록을 누르세요."}
            </span>
            {lesionMsg && <span className="hint">{lesionMsg}</span>}
          </div>

          <label className="field">
            <span>판독 소견</span>
            <textarea className="lg" rows={10} value={f.finding_note ?? ""}
                      onChange={(e) => set("finding_note", e.target.value)} />
          </label>
        </>
      );
    },
  },

  /* ── 4장 · 전체 환자 목록 ─────────────────────────────── */
  list: {
    title: "전체 환자 목록",
    sub: "지난 검사까지 전부 찾아보는 자리입니다. 판독 정정도 여기서 들어갑니다.",
    /* 상세에 뷰어가 들어가서(ListViewer) 고정폭(.wide, 440px)으로는
       좁게 눌린다 — 목록:상세를 화면 비율로 1:2 잡는다(.split.third,
       hospital.css). "내 업무"는 여기 상세가 이미 넓은 자리를 차지해서
       뺀다(2026-09-18). */
    splitSide: "third",
    hideDashboard: true,
    listTitle: "검사 목록",
    searchHint: "환자 · 환자번호",
    /* 검색이 훑는 칸 — 검색창에 적어 둔 것과 같다 */
    search: ["patient_name", "patient_no"],
    need: { view: "radiology.list.view" },

    sorts: [
      { key: "patient__name", label: "이름" },
      { key: "performed_at", label: "촬영 순서" },
      { key: "read_status", label: "진행상황" },
      { key: "modality", label: "모달리티" },
      { key: "report__viewed_at", label: "유방외과 열람" },
    ],

    cols: [
      { key: "patient", label: "환자", w: "24%" },
      { key: "modality", label: "모달리티", w: "14%" },
      { key: "performed", label: "촬영일", w: "16%" },
      { key: "status", label: "진행상황", w: "18%" },
      { key: "viewed", label: "유방외과", w: "14%" },
    ],

    /* 진행상황은 read_status 를 한글로. 「작성 중」으로 거르면 쓰다 만
       판독을 찾을 수 있다 — 병리와 달리 여기서는 표시한다 */
    row: (r) => ({
      id: r.id,
      patient: `${r.patient_name} (${r.age}/${label(SEX, r.sex)})`,
      modality: label(MODALITY, asModality(r.modality)),
      performed: r.performed_at,
      status: <Chip tone={tone("read", r.read_status)}>
        {text(r, "read_status", READ_STATUS, "status_label")}
      </Chip>,
      viewed: r.viewed_at
        ? <Chip tone="line">열람</Chip>
        : <Chip tone="dot">미열람</Chip>,
    }),

    /* 2026-09-18 — 환자 목록 설계에 맞춰 뷰어·검사 이력을 추가했다.
     * 상세(cfg.api.listDetail = rad.study)는 원래 category·finding_note
     * 정도만 주는 가벼운 응답이라 뷰어를 못 그린다 — 판독 화면과 같은
     * 무거운 응답(cfg.api.read = rad.read, series·volume manifest 포함)을
     * 여기서 한 번 더 부른다. 조회 전용이라 저장은 안 한다 — 저장하려면
     * [판독 화면으로] 버튼으로 Read.jsx에 가야 한다(그 화면이 그 일을 한다). */
    Detail: ({ d, cfg }) => {
      const read = useApi(() => cfg.api.read(d.id), [d.id]);
      const timeline = useApi(
        () => cfg.api.timeline(d.patient ?? d.patient_id),
        [d.patient, d.patient_id],
      );
      const [slide, setSlide] = useState(0);
      const [bright] = useState(100);
      const [contrast] = useState(100);
      const [mask] = useState(45);

      /* ⚠ 2026-09-18 — "목록·뷰어·상세" 3단으로 다시 짰다(설계 그림).
       * 바깥 Split(목록 1 : 나머지)은 그대로 두고, "나머지" 안쪽을
       * list-detail-cols로 한 번 더 갈라 뷰어(가운데)·상세정보(오른쪽,
       * 검사 이력을 리스트로) 두 칸으로 만든다. 기능은 없어도 된다는
       * 요구라 뷰어는 조회 전용(mode="review")만 유지한다. */
      return (
        <>
          {d.contrast_allergy && <Warn>조영제 알레르기 — {d.contrast_allergy}</Warn>}

          <div className="list-detail-cols">
            <div className="list-detail-viewer">
              <Body loading={read.loading} error={read.error} onRetry={read.reload}>
                {read.data && (
                  <ListViewer d={read.data} cfg={cfg} slide={slide} onSlide={setSlide}
                    bright={bright} contrast={contrast} mask={mask} />
                )}
              </Body>
            </div>

            <div className="list-detail-info">
              <Facts items={[
                ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
                ["환자번호", d.patient_no],
                ["생년월일", d.birth_date],
                ["연락처", d.phone],
                ["알레르기", d.contrast_allergy || "없음"],
                ["모달리티", label(MODALITY, asModality(d.modality))],
                ["촬영 장비", d.device],
                ["검사일", d.performed_at],
                ["담당 판독의", d.assigned_to],
                ["진행상황", text(d, "read_status", READ_STATUS, "status_label")],
                ["유방외과 열람", d.viewed_at ?? "미열람"],
              ]} />

              <p className="section-label">검사 이력</p>
              <Body loading={timeline.loading} error={timeline.error} onRetry={timeline.reload}>
                {timeline.data && <ListTimeline events={timeline.data} />}
              </Body>

              <Fold title="판독 결과" open={Boolean(d.finalized)}>
                {d.finalized ? (
                  <>
                    <Facts items={[["판정 등급", `BI-RADS ${d.category}`]]} />
                    <p className="quote">{d.finding_note}</p>
                  </>
                ) : <p className="muted">아직 확정된 판독이 없습니다.</p>}
              </Fold>
            </div>
          </div>
        </>
      );
    },
  },

  /* ── 5장 · 판독 정정 ──────────────────────────────────── */
  amend: {
    title: "영상 판독 정정",
    sub: "이미 확정한 판독을 고칩니다. 새 판독이 만들어지고 옛 판독이 그것을 가리킵니다.",
    imageTitle: "주요 이미지",
    categoryLabel: "판정 등급 (BI-RADS)",
    categories: BIRADS,
    saveHint: "저장하면 새 판독이 만들어지고 유방외과로 전달됩니다. 옛 판독은 지워지지 않습니다.",
    need: { view: "radiology.amend.view", save: "radiology.amend.save" },

    /* 영상은 이력이 별도 행이라 판독 응답에 실려 온다.
       ⚠ 응답에 없으면 GET /assessments?study={id} 로 따로 불러야 한다 */
    history: (d) => d.history ?? [],

    Info: ({ d }) => (
      <Facts items={[
        ["환자", `${d.patient.name} (${d.patient.age}/${label(SEX, d.patient.sex)})`],
        ["환자번호", d.patient.no],
        ["생년월일", d.patient.birth_date],
        ["연락처", d.patient.phone],
        ["알레르기", d.patient.contrast_allergy || "없음"],
        ["검사명", d.unit.exam_name],
        ["검사일시", d.unit.performed_at],
        ["담당 판독의", d.unit.assigned_to],
      ]} />
    ),
  },
};

function RetakeButton({ examOrderId, api }) {
  const retake = useCan("radiology.retake");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  async function requestRetake() {
    if (!examOrderId || busy) return;
    setBusy(true); setMsg(null);
    try {
      const out = await api.retake(examOrderId);
      const nextId = out.exam_order_id ?? out.new_exam_order_id;
      setMsg(nextId ? `재촬영 오더 ${nextId}번을 대기 큐에 등록했습니다.` : "재촬영 오더를 대기 큐에 등록했습니다.");
    } catch (e) {
      setMsg(e.detail || e.message || "재촬영 요청을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="rowacts">
      <button className="btn ghost" onClick={requestRetake}
              disabled={!retake.ok || !examOrderId || busy}
              title={!retake.ok ? retake.attrs.title : "품질 반려된 검사만 재촬영을 요청할 수 있습니다"}>
        {busy ? "요청 중…" : "재촬영 요청"}
      </button>
      {msg && <small className="hint">{msg}</small>}
    </span>
  );
}

