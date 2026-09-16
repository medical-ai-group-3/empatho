import { rad } from "../api";
import { go } from "../nav";
import { Chip, Facts, Fold, Warn, useCan } from "../lib/Parts";
import RadiologyAi from "./RadiologyAi";
import { boxesFromLesions, polygonsFromAi } from "../lib/Stage";

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
  uploadInfo: (id)    => rad.uploadInfo(id),
  complete:   (id)    => rad.complete(id),      /* 병리에는 없는 단계 */
  analyze:    (id)    => rad.analyze(id),
  progress:   (id)    => rad.progress(id),
  /* ⚠ 저장 파일 목록이 판독 조회에 없다 (2026-09-16 확인).
     업로드 조회에만 있어서 한 번 더 부른다. 판독 화면에서 「업로드
     조회」를 부르는 게 이름은 안 맞지만 화면은 돈다.
     read 응답에 files 가 들어가면 아래 Promise.all 을 지우면 된다 */
  read: async (id) => {
    const [r, up] = await Promise.all([rad.read(id), rad.uploadInfo(id)]);
    return { ...r, series: withFiles(r.series, up) };
  },
  draft:      (id, b) => rad.draft(id, b),
  finalize:   (id, b) => rad.finalize(id, b),
  list:       (o)     => rad.list(o),
  amend:      (id, b) => rad.amend(id, b),
};

const BIRADS = [
  { value: "0", label: "0 — 추가 검사 필요" },
  { value: "1", label: "1 — 음성" },
  { value: "2", label: "2 — 양성" },
  { value: "3", label: "3 — 양성 가능성 높음" },
  { value: "4a", label: "4a — 낮은 악성 의심" },
  { value: "4b", label: "4b — 중등도 악성 의심" },
  { value: "4c", label: "4c — 높은 악성 의심" },
  { value: "5", label: "5 — 악성 강력 시사" },
  { value: "6", label: "6 — 조직학적으로 확인된 악성" },
];

const MODALITY = { mammo: "맘모", ultrasound: "초음파", mri: "MRI" };

/* 판독 조회의 시리즈에 업로드 조회의 파일(주소·크기)을 얹는다.
   이름이 같은 것끼리 맞추고, 못 맞추면 순서대로 짝짓는다 */
function withFiles(series = [], up = {}) {
  const files = up.files ?? up.series ?? [];
  const byName = new Map(files.map((f) => [f.name, f]));
  return series.map((s, i) => {
    const f = byName.get(s.name) ?? files[i] ?? {};
    return {
      ...s,
      w: s.w ?? f.w, h: s.h ?? f.h,
      image: s.image ?? f.image ?? (f.key ? { key: f.key } : null),
    };
  });
}

export const radiology = {
  key: "radiology",
  name: "영상의학과",
  api,
  go: go.radiology,

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
      title: `${it.patient_name} (${it.age}/${it.sex})`,
      sub: `${it.patient_no} · ${MODALITY[it.modality] ?? it.modality}`,
      chip: it.contrast_allergy ? "조영제 알레르기" : it.device,
      chipTone: it.contrast_allergy ? "fill" : "line",
    }),

    Detail: ({ d }) => (
      <>
        {/* 촬영 전에 반드시 보여야 하는 값이라 맨 위에 세운다 */}
        {d.contrast_allergy && <Warn>조영제 알레르기 — {d.contrast_allergy}</Warn>}

        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${d.sex})`],
          ["환자번호", d.patient_no],
          ["모달리티", MODALITY[d.modality] ?? d.modality],
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
          ["환자", `${d.patient_name} (${d.age}/${d.sex})`],
          ["환자번호", d.patient_no],
          ["검사명", d.exam_name],
          ["검사 목적", d.purpose],
          ["검사일", d.performed_at],
          ["모달리티", MODALITY[d.modality] ?? d.modality],
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

    /* 병리에는 없는 버튼 */
    Extra: ({ cfg, id }) => {
      const retake = useCan("radiology.retake");
      return (
        <button className="btn ghost" disabled={!retake.ok} title={retake.attrs.title}
                onClick={() => cfg.api.retakeDialog?.(id)}>
          재촬영 요청
        </button>
      );
    },
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
    ready: (f) => Boolean(f.category),

    /* 뷰어에 무엇을 얹나 — 모달리티마다 다르다. **둘 다 SVG 로 간다.**
         맘모    검출 모델이라 마스크가 없다. 병변마다 박스 네 숫자
         초음파  폴리곤 좌표. 마스크 파일이 없다
         MRI     3D 메시라 2D 뷰어에 안 얹는다 (Garage 에서 따로 본다)
       좌표를 도형으로 바꾸는 자리는 lib/Stage.jsx 아래쪽에 모아 두었다 */
    stage: (d, i = 0) => {
      const s = (d.series ?? [])[i];
      const ai = d.ai;
      let shapes = [];
      const abstained = ai?.abstained ?? ai?.summary?.abstained;
      if (ai && !abstained && ai.lesion_found !== false) {
        if (ai.modality === "mammo") shapes = boxesFromLesions(ai.lesions, s?.w, s?.h);
        else if (ai.modality === "ultrasound") shapes = polygonsFromAi(ai);
      }
      return {
        image: s?.image,
        maskImage: null,        /* 영상은 마스크 파일이 없다. 전부 좌표다 */
        w: s?.w, h: s?.h, alt: s?.name,
        shapes,
      };
    },

    Info: ({ d, slide, onSlide }) => (
      <>
        {d.patient.contrast_allergy && <Warn>조영제 알레르기 — {d.patient.contrast_allergy}</Warn>}
        <Facts items={[
          ["환자", `${d.patient.name} (${d.patient.age}/${d.patient.sex})`],
          ["환자번호", d.patient.no],
          ["검사명", d.unit.exam_name],
          ["모달리티", MODALITY[d.unit.modality] ?? d.unit.modality],
          ["검사 상태", d.unit.status_label],
        ]} />
        <Fold title={`시리즈 ${(d.series ?? []).length}`}>
          <ul className="slides">
            {(d.series ?? []).map((s, i) => (
              <li key={s.id} className={slide === i ? "on" : undefined}>
                <button onClick={() => onSlide?.(i)}>{s.name}</button>
              </li>
            ))}
          </ul>
        </Fold>
      </>
    ),

    Ai: RadiologyAi,

    Doctor: ({ f, set }) => {
      const add = useCan("radiology.lesion.add");
      return (
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

          <div className="stack">
            <button className="btn line" disabled={!add.ok} title={add.attrs.title}>
              병변 추가
            </button>
            <span className="muted small">영상에 박스를 그려 병변을 직접 만듭니다</span>
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
    listTitle: "검사 목록",
    searchHint: "환자 · 환자번호",
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
      patient: `${r.patient_name} (${r.age}/${r.sex})`,
      modality: MODALITY[r.modality] ?? r.modality,
      performed: r.performed_at,
      status: <Chip tone={STATUS_TONE[r.status_label]}>{r.status_label}</Chip>,
      viewed: r.viewed_at
        ? <Chip tone="line">열람</Chip>
        : <Chip tone="dot">미열람</Chip>,
    }),

    Detail: ({ d }) => (
      <>
        {d.contrast_allergy && <Warn>조영제 알레르기 — {d.contrast_allergy}</Warn>}
        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${d.sex})`],
          ["환자번호", d.patient_no],
          ["모달리티", MODALITY[d.modality] ?? d.modality],
          ["촬영 장비", d.device],
          ["검사일", d.performed_at],
          ["담당 판독의", d.assigned_to],
          ["진행상황", d.status_label],
          ["유방외과 열람", d.viewed_at ?? "미열람"],
        ]} />
        <Fold title="판독 결과" open={Boolean(d.finalized)}>
          {d.finalized ? (
            <>
              <Facts items={[["판정 등급", `BI-RADS ${d.category}`]]} />
              <p className="quote">{d.finding_note}</p>
            </>
          ) : <p className="muted">아직 확정된 판독이 없습니다.</p>}
        </Fold>
      </>
    ),
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
        ["환자", `${d.patient.name} (${d.patient.age}/${d.patient.sex})`],
        ["환자번호", d.patient.no],
        ["검사명", d.unit.exam_name],
        ["검사일시", d.unit.performed_at],
        ["담당 판독의", d.unit.assigned_to],
      ]} />
    ),
  },
};

const STATUS_TONE = { "판독 대기": "line", "작성 중": "fill", "판독 완료": "dot" };
