import { Suspense, lazy, useState } from "react";
import { rad } from "../api";
import { go } from "../nav";
import * as H from "./home";
import { Chip, Facts, Fold, Warn, useCan } from "../lib/Parts";
import { Body } from "../lib/Body";
import RadiologyAi from "./RadiologyAi";
import Stage, { boxesFromLesions, polygonsFromAi } from "../lib/Stage";
import { useApi } from "../lib/useApi";
import { useFile } from "../lib/files";
import { MODALITY, biradsFor, READ_STATUS, SEX, eventDetail, label, modality as asModality, text, tone }
  from "../codes";
/* 판독 · 정정(3·5장) 전용 — 09-28 재배치 */
import { currentAssessment } from "../api";
import { RadiologyAiSummary } from "./RadiologyAi";
import { Phrases } from "../lib/Parts";
import { BIRADS_LABEL, DENSITY_CATEGORY, EXAM_PURPOSE, RECOMMENDATION } from "../codes";
import { getMe } from "../perm";

/* ── 판독(3장) 보조 — 상용구 · 알레르기 · 의뢰 질문 · 밀도 ────────
   ⚠ 상용구는 **서버가 주는 값이 아니다.** 저장 경로가 없어 여기 박았다.
     판독 소견 칸 위에 칩으로 뜬다(screens/Read.jsx → lib/Parts Phrases) */
const PHRASES = [
  ["종괴", ["경계 불규칙, 침상 변연", "타원형 저에코 결절, 경계 명확"]],
  ["석회화", ["분절형 미세석회화", "양성 추정 거대석회화"]],
  ["림프절", ["액와 림프절 종대 없음", "액와 림프절 피질 비후"]],
  ["결론", ["추가 조직검사 권고", "6개월 추적 초음파 권고"]],
];

/* 알레르기 메모 → 이름표. ⚠ 서버는 has_allergy + allergy_note 뿐이라
   무엇에 대한 것인지 모른다 — 「조영제」라고 적혀 있을 때만 조영제 알레르기다.
   전에는 페니실린도 「조영제 알레르기」로 떴다 */
function allergyOf(v) {
  if (v == null || v === false || v === "" || v === "없음") return null;
  const note = v === true ? "있음" : String(v);
  const contrast = /조영|contrast|가돌리늄|gadolin|요오드|iod/i.test(note);
  return { label: contrast ? "조영제 알레르기" : "알레르기", note, contrast };
}
const ageSex = (p) => {
  const bits = [p.age != null && p.age !== "" ? String(p.age) : null, label(SEX, p.sex) || null].filter(Boolean);
  return bits.length ? ` (${bits.join("/")})` : "";
};
/* 의뢰 질문 — 유방외과가 적은 글(order_note)이 먼저, 없으면 검사 목적 */
const askOf = (d) => d.order_note || d.order?.order_note || d.purpose
  || label(EXAM_PURPOSE, d.exam_purpose ?? d.order?.exam_purpose) || null;
const densityText = (d) => [label(Object.fromEntries(DENSITY_CATEGORY.map((o) => [o.value, o.label])), d.density_category),
  d.density_percent != null && d.density_percent !== "" ? `${Number(d.density_percent).toFixed(1)}%` : null]
  .filter(Boolean).join(" · ");
/* 홈 · 큐 · 업로드 · 목록(0·1·2·4장) 전용 — 09-28 재배치 */
import { EXAM_PURPOSE as PURPOSE } from "../codes";
import { getMe as whoAmI } from "../perm";
import { Card as UpCard } from "../lib/Page";

/* 영상 판독(screens/Read.jsx)과 환자 목록(screens/List.jsx) 둘 다 같은
 * 규칙으로 뷰어에 무엇을 얹을지 정한다 — read.stage 하나였는데
 * list.Detail 에도 같은 뷰어를 붙이면서(2026-09-18, 환자 목록 설계)
 * 한 객체 리터럴 안에서 read.stage 를 list 쪽이 부를 수가 없어(자기
 * 자신을 아직 다 만들기 전이라) 바깥으로 뺐다. */
const MRIReviewGrid = lazy(() => import("../lib/dicom/MRIReviewGrid"));
const DicomStackViewer = lazy(() => import("../lib/dicom/DicomStackViewer"));

/* 판독 응답 하나 → 뷰어가 아는 모양. 유방외과 검사 종합 뷰어도 같은
   것을 쓴다(dept/breast/components/ReviewViewer.jsx) — 모달리티마다
   어느 뷰어를 쓰는지가 한 곳에만 적혀 있어야 둘이 안 엇갈린다.

   ⚠ **모달리티 이름이 아니라 «서버가 준 주소»로 고른다.** 전에는 맘모일
     때만 스택 뷰어로 갔다. 그런데 서버가 초음파에도 같은 주소를 주기
     시작하면(09-23) 이름으로 거르는 쪽은 그것을 못 받는다. 주소가 왔다는
     것은 그 뷰어가 열 수 있다는 뜻이다 — 아래 <img> 길은 DICOM 원본을
     못 푼다. */
export function radStage(d, i = 0, sop = null) {
  if (d.volume_manifest) {
    return { volumeManifest: d.volume_manifest, volumeBase: d.volume_base, ai: d.ai ?? null };
  }

  const files = d.files ?? [];
  const isUs = asModality(d.unit?.modality ?? d.modality ?? d.ai?.modality) === "us";

  if (d.stack_manifest) {
    /* 스택 뷰어는 장마다 도형을 따로 얹는다 — 지금 장이 무엇인지는 뷰어가
       SOP UID 로 알려 준다(onInstance). 맘모 병변은 image.{laterality,view}
       로, 초음파 결과는 source_object 로 그 장을 찾는다 */
    const cur = sop ? files.find((f) => f.sop_instance_uid === sop) ?? null : null;
    const ai = isUs ? (cur ? aiForFiles(d, [cur]) : null) : d.ai ?? null;
    return {
      stackManifest: d.stack_manifest, stackBase: d.stack_base,
      ai,
      aiMissing: isUs && Boolean(cur) && !ai,
      overlay: (at) => {
        const f = files.find((x) => x.sop_instance_uid === at);
        if (!f) return null;
        if (isUs) return { shapes: usShapes(aiForFiles(d, [f])) };
        return { shapes: boxesFromLesions(mammoLesions(d).filter((l) => fileOfLesion(files, l) === f), f.w, f.h) };
      },
      where: isUs ? undefined : (id) => whereLesion(d, files, id),
    };
  }

  const s = (d.series ?? [])[i];
  const sFiles = s?.files?.length ? s.files : s ? [s] : [];
  const ai = isUs ? aiForFiles(d, sFiles) : d.ai ?? null;
  let shapes = [];
  if (isUs) shapes = usShapes(ai);
  else if (asModality(ai?.modality) === "mammo") {
    /* 한 장짜리 원본으로 온 맘모(옛 자료·목업) — 파일에 좌우·방향이 있으면
       그 장의 병변만, 없으면 전부 얹는다 */
    const known = sFiles.some((f) => latOf(f.laterality) && viewOf(f.view_position));
    const ls = mammoLesions(d);
    shapes = boxesFromLesions(
      known ? ls.filter((l) => sFiles.includes(fileOfLesion(files, l))) : ls, s?.w, s?.h);
  }
  return {
    image: s?.image,
    maskImage: null,
    w: s?.w, h: s?.h, alt: s?.name,
    shapes,
    ai,
    aiMissing: isUs && Boolean(s) && !ai,
  };
}

/* 기권 판정은 RadiologyAi 와 같은 규칙이어야 한다 — 봉투와 summary 중
   하나라도 참이면 기권. `??` 로는 봉투의 false 에서 멈춘다. */
const usable = (ai) => Boolean(ai) && !(ai.abstained || ai.summary?.abstained) && ai.lesion_found !== false;
const usShapes = (ai) => (usable(ai) && asModality(ai.modality) === "us" ? polygonsFromAi(ai) : []);

/* 이 영상(파일들)에 돌린 AI 결과.
   초음파는 영상 한 장이 판독 한 번이라 한 검사에 AiResult 가 여럿이다.
   서버가 ai_results(전부, source_object = 저장 파일 번호)를 주면 거기서
   고른다(api.js 가 d.ais 로 정리). 옛 서버는 latest_ai_result 하나뿐이라
   그것을 쓰되, 그 결과가 **다른 장** 것이라고 적혀 있으면 안 얹는다 —
   A 장의 윤곽이 B 장 위에 그려지는 것보다 안 그리는 편이 낫다. */
function aiForFiles(d, files) {
  const ids = new Set(files.map((f) => f?.id).filter((v) => v != null).map(String));
  const mine = (r) => r?.source_object != null && ids.has(String(r.source_object));
  if (Array.isArray(d.ais)) {
    const hit = d.ais.filter(mine);
    return hit.find((r) => r.run_status === "done") ?? hit[0] ?? null;
  }
  const ai = d.ai ?? null;
  return ai && (ai.source_object == null || mine(ai)) ? ai : null;
}

/* 맘모 병변 — 뷰어 도형 id 와 AI 패널이 같은 규칙(l.id ?? b{i})을 쓰도록
   걸러 내기 **전에** id 를 박아 둔다. 거른 뒤에 붙이면 번호가 밀린다 */
function mammoLesions(d) {
  if (!usable(d.ai)) return [];
  return (d.ai.lesions ?? []).map((l, i) => ({ ...l, id: l.id ?? `b${i}` }));
}

const latOf = (v) => ({ l: "L", left: "L", r: "R", right: "R" })[String(v ?? "").toLowerCase()] ?? null;
const viewOf = (v) => String(v ?? "").trim().toUpperCase() || null;

/* 병변이 나온 장 — 병변의 image.{laterality, view}(tasks.py _mammo)와
   파일의 laterality · view_position(DICOM 헤더에서 읽은 값, I-2)을 맞춘다 */
function fileOfLesion(files, l) {
  const lat = latOf(l.image?.laterality);
  const v = viewOf(l.image?.view);
  if (!lat || !v) return null;
  return files.find((f) => latOf(f.laterality) === lat && viewOf(f.view_position) === v) ?? null;
}

/* 「영상에서 보기」가 갈 곳. 못 가면 이유를 준다 — 버튼이 그 이유로 꺼진다 */
function whereLesion(d, files, id) {
  const l = mammoLesions(d).find((x) => x.id === id);
  if (!l) return { why: "이 병변을 결과에서 찾지 못했습니다" };
  if (!Array.isArray(l.box ?? l.bbox)) return { why: "이 병변의 박스 좌표가 결과에 없습니다" };
  if (!l.image?.laterality || !l.image?.view) {
    return { why: "이 병변이 어느 영상(좌우 · CC/MLO)에서 나왔는지 결과에 없습니다" };
  }
  if (!files.some((f) => latOf(f.laterality) && viewOf(f.view_position))) {
    return { why: "업로드된 영상에 좌우 · 촬영 방향(laterality · view_position) 값이 없어 어느 장인지 찾지 못합니다" };
  }
  const f = fileOfLesion(files, l);
  if (!f) return { why: `${latOf(l.image.laterality)}-${viewOf(l.image.view)} 영상이 이 검사에 없습니다` };
  if (!f.sop_instance_uid) return { why: "그 영상의 DICOM 번호(SOP UID)가 없어 뷰어에서 찾지 못합니다" };
  return { sop: f.sop_instance_uid };
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
  /* 2장 품질 — 반려(rejected)여야 서버가 재촬영(retake)을 받는다.
     ⚠ retake 는 study_id 가 아니라 **오더 번호**로 건다 */
  quality:    (id, s) => rad.quality(id, s),
  retake:     (oid)   => rad.retake(oid),
  /* 홈 「오늘 한 일」 — 오늘 내가 확정한 판독 */
  myReads:    ()      => rad.myReads(),
  analyze:    (id)    => rad.analyze(id),
  progress:   (id)    => rad.progress(id),
  /* 원본 응답과 업로드 파일 목록을 화면 계약으로 합치는 일은 api.js가 맡는다. */
  read:       (id)    => rad.read(id),
  draft:      (id, b) => rad.draft(id, b),
  finalize:   (id, b) => rad.finalize(id, b),
  list:       (o, w)  => rad.list(o, w),
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
            study={{ volume_manifest: view.volumeManifest, volume_base: view.volumeBase, anatomy_meshes: d.anatomy_meshes }}
            issue={cfg.api.ticket}
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
          {eventDetail(e) && <p className="exam-history-detail">{eventDetail(e)}</p>}
        </li>
      ))}
    </ul>
  );
}

/* ── 거르는 칩 (lib/Filters) — 홈 · 큐 · 목록 ─────────────────
   홈 줄 · 큐 줄 둘 다 modality · exam_purpose 칸을 들고 있어 한 벌로 쓴다.
   ⚠ 목적을 모르는 줄(옛 서버의 검사 행)은 「검진」「진단」 어디에도 안 든다 —
     모르는 것을 한쪽으로 넣으면 거른 목록이 거짓말을 한다 */
const MOD_GROUP = {
  key: "mod", label: "모달리티",
  items: [
    { key: "all", name: "전체" },
    ...Object.entries(MODALITY).map(([k, name]) => ({
      key: k, name, query: { modality: k },
      test: (r) => asModality(r.modality) === k,
    })),
  ],
};
const HOME_FILTERS = [
  MOD_GROUP,
  { key: "why", label: "목적",
    items: [
      { key: "all", name: "전체" },
      ...Object.entries(PURPOSE).map(([k, name]) => ({
        key: k, name, test: (r) => r.exam_purpose === k,
      })),
    ] },
];

/* 「내 것」 — 서버가 assigned=me 를 알면 서버가 거른다. 화면은 이름이
   적혀 오는 경우(목업 · assigned_to_name)만 /me 이름과 맞춰 본다. 번호로만
   오면 못 맞추므로 «누군가 맡은 것»까지만 거른다 */
function mine(r) {
  /* 09-28 — /me 가 staff_id 를 준다. 번호끼리 견주는 것이 먼저다 */
  const myId = whoAmI()?.staff_id;
  if (myId != null && typeof r.assigned_to === "number") return r.assigned_to === myId;
  const who = r.assigned_to_name ?? (typeof r.assigned_to === "string" ? r.assigned_to : null);
  const me = whoAmI()?.name;
  if (who && me) return who.includes(me);
  return r.assigned_to != null;
}

const LIST_FILTERS = [
  { key: "st", label: "상태",
    items: [
      { key: "all", name: "전체" },
      { key: "pending", name: "대기", query: { read_status: "pending" },
        test: (r) => r.read_status == null || r.read_status === "pending" },
      { key: "draft", name: "초안", query: { read_status: "draft" },
        test: (r) => r.read_status == null || r.read_status === "draft" },
      { key: "finalized", name: "확정", query: { read_status: "finalized" },
        test: (r) => r.read_status == null ? Boolean(r.finalized) : r.read_status === "finalized" },
    ] },
  MOD_GROUP,
  { key: "own", label: "담당",
    items: [
      { key: "all", name: "전체" },
      { key: "me", name: "내 것", query: { assigned: "me" }, test: mine },
    ] },
];

export const radiology = {
  key: "radiology",
  name: "영상의학과",
  api,
  go: go.radiology,

  /* ── 홈 (docs/mockup/RadiologyHome.html) ────────────
   *
   * ⚠ **목업이 줄마다 적는 AI 상태를 못 쓴다.** 목록 응답에
   *   AI 결과가 안 실린다 — 줄마다 /ai-results?study= 를 부르면
   *   줄 수만큼 요청이 나간다(8장 1번).
   */
  home: {
    /* 판독(assessment)을 한 번 더 받는다 — 줄마다 부르는 것이 아니라
       필터 없이 한 번이다(GET /assessments). 「오늘 한 일」이 확정 시각을
       알려면 이게 있어야 한다. 검사 목록에는 확정 시각이 없다 —
       StudySerializer 가 updated_at 을 빼고(exclude = AUDIT_FIELDS)
       Study 에는 확정 시각 칸 자체가 없다. */
    /* ⚠ 목록은 한 쪽 20건이다 — 홈이 단계별로 나눠 세려면 넉넉히 받는다.
       ⚠ 확정된 검사는 오더를 안 부른다(want.need) — 홈이 확정 건의 목적을
         안 쓴다. 옛 서버에서 30초마다 나가던 요청이 확정 건만큼 준다(api.js).
       ⚠ 「오늘 한 일」은 myReads(assessed_by=me · finalized_on=today) —
         전에는 필터 없는 /assessments 라 남의 확정까지 셌다 */
    load: () => Promise.all([
      H.soft(api.queue()),
      api.list({ page_size: 200 }, { need: (r) => r.read_status !== "finalized" }),
      H.soft(api.myReads()),
    ]).then(([queue, list, reads]) => ({
      queue: H.rows(queue), studies: H.rows(list), reads: H.rows(reads),
    })),

    /* 달력은 뺀다 — 찍을 점이 없어 늘 빈 달이었다(marks 가 늘 []).
       「확인이 필요한 것」도 뺀다 — 탭 머리 숫자가 같은 말을 한다 */
    layout: [["queue"], ["done", "handover"], ["todo"]],

    primary: { label: "다음 환자 받기", to: go.radiology.queue(),
               need: "radiology.queue.view" },

    /* ── 홈 주 큐 — 판독 현황 ─────────────────────────────────
     * 한 줄에 몰아 두면 「AI 가 아직 도는 것」과 「AI 는 끝났고 내 소견만
     * 남은 것」이 섞여서 무엇부터 집을지 안 보였다. 단계대로 탭을 가른다.
     *
     *   촬영 대기   유방외과가 낸 오더 중 아직 아무도 안 집은 것
     *   업로드 대기 촬영은 시작했는데 영상이 아직 없는 검사
     *   AI 분석 중  영상은 올라왔고 AI 가 도는 중(queued · running)
     *   소견 대기   AI 가 끝났거나(done · failed) 안 돌린 것 — 의사 소견 차례
     *   초안        저장만 하고 확정 안 한 판독
     *
     * ⚠ AI 상태는 서버 목록 행의 ai_status(가장 최근 실행)다. 옛 서버는 이
     *   칸이 없어 undefined 다 — 그때는 「소견 대기」로 떨어진다(판독은 AI
     *   없이도 쓸 수 있으니 막히지 않는 쪽이다). */
    queue: ({ queue, studies }) => {
      const pending = studies.filter((r) => r.read_status === "pending");
      const hasImg = (r) => r.image_count > 0;
      const running = (r) => r.ai_status === "queued" || r.ai_status === "running";
      const AI_NOTE = { done: "AI 완료", failed: "AI 실패", queued: "AI 대기", running: "AI 분석 중" };

      const study = (why) => (r) => ({
        id: r.id,
        name: H.nameOf(r),
        no: H.noOf(r),
        meta: H.who(r),
        chip: r.modality ? label(MODALITY, asModality(r.modality)) : null,
        chipTone: "fill",
        sub: [AI_NOTE[r.ai_status] ?? (hasImg(r) ? "AI 없음" : null),
              /* 모달리티는 칩이 말한다 — 목적만 */
              label(PURPOSE, r.exam_purpose) || r.exam_name].filter(Boolean).join(" · "),
        at: H.at(r.performed_at),
        /* 기다린 시간 — 촬영한 뒤로. 오더 시각은 새 서버만 행에 싣는다 */
        wait: H.waited(r.performed_at ?? r.ordered_at),
        modality: asModality(r.modality),
        exam_purpose: r.exam_purpose ?? null,
        /* 영상이 없으면 업로드, 있으면 판독 — 영상 없는 검사를 판독으로
           보내면 409 STUDY_NOT_READ_READY 다(서버 image_count 참고) */
        to: hasImg(r) ? go.radiology.read(r.id) : go.radiology.upload(r.id),
        /* ⚠ id 는 검사 번호다 — 「최근 본 환자」는 환자 번호로(lib/recent.js) */
        pid: r.patient ?? r.patient_id ?? null,
        why,
      });

      /* 탭은 **일이 흐르는 순서**다 — 촬영 → 업로드 → AI → 소견 → 초안.
         처음 여는 탭은 판독의가 지금 할 일인 「소견 대기」(pick) */
      return {
        title: "판독 현황",
        hint: "일이 흐르는 순서",
        cols: { chip: "모달리티", sub: "내용" },
        pick: "doctor",
        /* 기다린 시간은 별도 열 — 시각(at)과 나란히 */
        extra: [{ key: "wait", name: "대기" }],
        filters: HOME_FILTERS,
        tabs: [
          /* 유방외과가 낸 오더 — 집는 것은 촬영 대기 화면이 한다.
             줄을 누르면 그 오더가 골라진 채로 열린다(?pick=) */
          { key: "order", name: "촬영 대기", empty: "촬영 대기 중인 오더가 없습니다",
            rows: queue.map((o) => ({
              id: `o-${o.id}`,
              name: o.patient_name ?? H.nameOf(o),
              no: o.patient_no ?? H.noOf(o),
              meta: H.who(o),
              chip: o.modality ? label(MODALITY, asModality(o.modality)) : null,
              sub: [label(PURPOSE, o.exam_purpose) || null, o.purpose || null,
                    `${o.ordered_by_name ?? "유방외과"} 요청`].filter(Boolean).join(" · "),
              at: H.at(o.ordered_at),
              wait: H.waited(o.ordered_at),
              modality: asModality(o.modality),
              exam_purpose: o.exam_purpose ?? null,
              to: `${go.radiology.queue()}?pick=${o.id}`,
              pid: o.patient_id ?? o.patient ?? null,
              why: "촬영 대기",
            })) },
          { key: "upload", name: "업로드 대기", empty: "영상을 기다리는 검사가 없습니다",
            rows: pending.filter((r) => !hasImg(r)).map(study("업로드")) },
          { key: "ai", name: "AI 분석 중", empty: "AI 가 분석 중인 검사가 없습니다",
            rows: pending.filter((r) => hasImg(r) && running(r)).map(study("판독")) },
          { key: "doctor", name: "소견 대기", empty: "소견을 쓸 검사가 없습니다",
            rows: pending.filter((r) => hasImg(r) && !running(r)).map(study("판독")) },
          { key: "draft", name: "초안", empty: "확정 안 한 판독이 없습니다",
            rows: studies.filter((r) => r.read_status === "draft").map(study("판독")) },
        ],
      };
    },

    /* 확정 시각은 검사가 아니라 판독이 안다(Assessment.finalized_at).
       전에는 검사 목록의 updated_at 으로 걸렀는데 그 값이 응답에 아예
       없어서(StudySerializer 가 뺀다) 늘 0 건이었다 — 확정이 다섯인
       날에도 「아직 집계하지 않습니다」가 떴다. */
    /* ⚠ 09-28 — 판독 행의 검사 칸 이름은 `study` 다(AssessmentSerializer).
       전에는 a.study_id 를 읽어 검사를 못 찾고 「환자 #… · 검사」로 떴고,
       누르면 /read/undefined 로 갔다. 둘 다 받는다.
       ⚠ 옛 서버는 assessed_by=me · finalized_on=today 를 몰라 남의 판독까지
       준다 — 오늘 · 확정 · 안 덮인 것은 여기서 다시 거른다. 「내 것」은
       assessed_by 가 번호라 /me(이름뿐)와 못 맞춘다 — 새 서버가 거른다 */
    done: ({ studies, reads }) => {
      const study = new Map(studies.map((r) => [String(r.id), r]));
      const it = (reads ?? []).filter((a) =>
        a.read_stage === "final" && !a.superseded_by && H.isToday(a.finalized_at));
      return {
        summary: `확정 ${it.length}`,
        empty: "오늘 확정한 판독이 아직 없습니다",
        items: it.map((a) => {
          const sid = a.study ?? a.study_id;
          /* 새 서버는 판독 행에 환자 이름 · 모달리티를 싣는다. 옛 서버는
             검사 목록에서 찾는다(홈이 받은 200건 밖이면 번호로) */
          const s = study.get(String(sid)) ?? {};
          const mod = a.modality ?? s.modality;
          const kind = mod ? label(MODALITY, asModality(mod)) : "검사";
          const who = a.patient_name || s.patient_name || `검사 #${sid}`;
          return {
            id: a.assessment_id,
            at: H.at(a.finalized_at),
            text: `${who} · ${kind} 판독 확정${a.category ? ` · BI-RADS ${a.category}` : ""}`,
            to: sid != null ? go.radiology.read(sid) : null,
          };
        }),
      };
    },
  },

  /* 티켓이 여는 범위의 단위 — 영상은 검사(study)다.
     ⚠ 이 화면들이 들고 다니는 id 가 study_id 라 그대로 맞는다.
     맘모 원본·MRI 시리즈(DICOM)는 이 범위로 못 받는다 — 서버가
     DICOM 범위의 티켓을 사람에게 안 내준다 (lib/files.js 참고) */
  scopeKind: "study",

  /* ── 1장 · 촬영 대기 큐 ───────────────────────────────── */
  queue: {
    title: "촬영 대기",
    listTitle: "촬영 대기 오더",
    /* 네 단 껍데기가 읽는 제목들(screens/Queue.jsx) */
    detailTitle: "이번 검사",
    pastTitle: "지난 검사",
    /* ⚠ **서버가 주는 값이 아니다.** 상용구를 저장하는 경로가 없어 여기
       박아 뒀다. 사람마다 다르게 쓰려면 서버에 자리가 있어야 한다(8장) */
    phrases: [
      ["종괴", ["경계 불규칙, 침상 변연", "타원형 저에코 결절, 경계 명확"]],
      ["석회화", ["분절형 미세석회화", "양성 추정 거대석회화"]],
      ["림프절", ["액와 림프절 종대 없음", "액와 림프절 피질 비후"]],
      ["결론", ["추가 조직검사 권고", "6개월 추적 초음파 권고"]],
    ],
    /* ⚠ 09-28 — 상용구 칸은 큐에서 안 그린다(phrasesCol 을 안 켠다).
       소견을 쓰는 판독 화면의 일이다. 글은 남겨 둔다 */
    searchHint: "환자 · 환자번호",
    emptyText: "촬영 대기 중인 오더가 없습니다",
    /* 누르면 하는 일 그대로 — 전에는 「환자 선택」이라 고르기만 하는 줄
       알았다. 실제로는 되돌릴 수 없는 집기다 */
    takeLabel: "이 검사 집기",
    filters: HOME_FILTERS,
    need: { view: "radiology.queue.view", assign: "radiology.queue.assign" },
    /* 지난 검사 줄 → 그 검사의 판독(새 탭). 병리 줄은 권한 밖이라 안 건다 */
    pastLink: (e) => (e.study_id != null ? go.radiology.read(e.study_id) : null),

    row: (it) => {
      const al = H.allergyTag(it.contrast_allergy);
      return {
        id: it.id,
        /* 지난 검사 칸이 이 번호로 환자 이력을 부른다 */
        patientId: it.patient_id ?? it.patient ?? null,
        title: `${H.nameOf(it)}${H.who(it) ? ` (${it.age ?? "?"}/${label(SEX, it.sex)})` : ""}`,
        /* 누가 낸 오더인지 같이 적는다 — 이 큐는 유방외과가 낸 촬영 요청이다 */
        sub: [label(MODALITY, asModality(it.modality)), label(PURPOSE, it.exam_purpose) || null,
              `${it.ordered_by_name ?? "유방외과"} 요청`].filter(Boolean).join(" · "),
        wait: H.waited(it.ordered_at),
        chip: al ? al.label : it.device || null,
        chipTone: al ? "fill" : "line",
      };
    },

    /* 맨 위는 **유방외과가 묻는 것**이다 — 왜 찍는지가 무엇을 찍는지보다
       먼저 읽혀야 한다. 환자 · 알레르기는 머리(Queue.jsx)에 한 번만 있다 */
    Detail: ({ d }) => {
      const why = label(PURPOSE, d.exam_purpose);
      return (
        <>
          {(why || d.purpose) && (
            <div className="work-ask-q">
              <span className="section-label">{why ? `의뢰 · ${why}` : "의뢰"}</span>
              {d.purpose
                ? <p className="quote">{d.purpose}</p>
                : <p className="muted small">의뢰 문구가 없습니다</p>}
            </div>
          )}
          <Facts items={[
            ["모달리티", label(MODALITY, asModality(d.modality))],
            ["검사명", d.exam_name],
            d.device && ["촬영 장비", d.device],
            ["요청", [d.ordered_by_name ?? d.ordered_by, H.at(d.ordered_at) ? `${String(d.ordered_at).slice(0, 16).replace("T", " ")}` : null,
                      H.waited(d.ordered_at) ? `${H.waited(d.ordered_at)} 대기` : null].filter(Boolean).join(" · ") || "—"],
          ]} />
        </>
      );
    },
  },

  /* ── 2장 · 촬영 업로드 ────────────────────────────────── */
  upload: {
    title: "업로드",
    infoTitle: "환자 · 검사 정보",
    dropText: "촬영본을 드래그하세요",
    acceptFor: (d) => {
      const modality = String(d?.modality ?? d?.unit?.modality ?? "").toLowerCase();
      /* MG와 MRI는 Orthanc/DICOM 경로를 타야 하므로 이미지 파일을
         허용하면 저장은 되지만 판독용 시리즈가 만들어지지 않는다. */
      if (modality === "mammo" || modality === "mg" || modality === "mammography" || modality === "mri") {
        return ".dcm,.zip,application/dicom,application/zip";
      }
      return ".dcm,.zip,image/*,video/*";
    },
    /* 끌어 놓는 칸 아래 한 줄 — 무엇을 어떤 꼴로 올리는가 */
    hint: "맘모 양측 CC·MLO 4뷰(DICOM) · 초음파 프레임·클립 · MRI 시리즈는 zip 으로",
    estimate: "초음파 약 0.4초 · 맘모 약 34초 · MRI 약 3분. 기다리지 않고 나가도 됩니다 — 다시 들어오면 진행이 그대로 보입니다.",
    need: {
      view: "radiology.upload.view",
      send: "radiology.upload.send",
      run: "radiology.ai.run",
    },

    /* 누구의 무엇 — **한 줄**(screens/Upload.jsx 의 .up-strip).
       알레르기는 여기 한 번 */
    Info: ({ d }) => {
      const al = H.allergyTag(d.contrast_allergy);
      return (
        <>
          <b>{H.nameOf(d)}</b>
          {H.who(d) && <span>{H.who(d)}</span>}
          {H.noOf(d) && <span>{H.noOf(d)}</span>}
          <Chip tone="fill">{label(MODALITY, asModality(d.modality)) || "검사"}</Chip>
          {(label(PURPOSE, d.exam_purpose) || d.exam_name) && <span>{label(PURPOSE, d.exam_purpose) || d.exam_name}</span>}
          {d.purpose && <span className="up-strip-q" title={d.purpose}>{d.purpose}</span>}
          {d.performed_at && <span>촬영 {String(d.performed_at).slice(0, 16).replace("T", " ")}</span>}
          {al && (
            <span className="pb-warn" title={al.note ?? undefined}>
              <i aria-hidden="true">⚠</i><b>{al.label}</b>{al.note && ` · ${al.note}`}
            </span>
          )}
        </>
      );
    },

    /* 올린 것이 무엇으로 묶였나 — 보기 전용. ⚠ 전에는 체크박스가 있었는데
       아무 데도 안 이어져 있었다(풀어도 전부 분석에 들어갔다) */
    Series: ({ d }) => ((d.series ?? []).length > 0 && (
      <UpCard title={`시리즈 ${d.series.length}`}>
        <ul className="slides">
          {d.series.map((s) => (
            <li key={s.id}><span>{s.name}</span> <small className="muted">{s.count}장</small></li>
          ))}
        </ul>
      </UpCard>
    )),

    /* ① 품질 — [승인] · [반려 → 재촬영].
       서버는 **반려(quality_status=rejected)된 오더에서만** 재촬영을 만든다.
       새 오더는 곧바로 촬영 대기 큐로 들어간다(원무 재접수 없음) */
    Quality: (p) => <Quality {...p} />,
  },

  /* ── 3장 · 판독 ───────────────────────────────────────── */
  read: {
    title: "판독",
    /* 환자는 맨 위 띠에 있다 — 왼쪽 칸은 검사 이야기만 */
    infoName: "검사 정보",
    unitName: "판독",
    saveHint: "확정하면 유방외과로 전달됩니다. 이후 고치려면 판독 정정으로 새 판독을 만듭니다.",
    finalNote: "고치려면 판독 정정으로 새 판독을 만듭니다. 옛 판독은 지워지지 않습니다.",
    /* 왼쪽 칸에 이 환자의 다른 검사(새 탭) — screens/Read.jsx Priors */
    priors: true,
    phrases: PHRASES,

    /* 확정된 검사는 읽기 전용 — 다시 확정하면 초안이 없어 409 거나 판정이
       조용히 바뀐다. 현재 판독은 GET /assessments?study= 에서 찾는다
       (current_assessment 는 초안만 든다) */
    isFinal: (d) => Boolean(d.finalized) || d.read_status === "finalized",
    loadFinal: (id) => api.history(id).then((rows) => currentAssessment(H.rows(rows))),

    /* 임시저장 바디. 권고 · 권고 사유는 Assessment 칸이다(서버 값 — codes.js
       RECOMMENDATION). null 은 지운다는 뜻이다.
       ⚠ 밀도는 Study 칸이고 판독 저장이 안 받는다 — 폼에는 읽기로만 둔다 */
    draftPayload: (f) => ({
      lesion_id: f.lesion_id ?? null,
      finding_note: f.finding_note ?? "",
      category: f.category || null,
      recommendation: f.recommendation || null,
      recommendation_reason: f.recommendation ? f.recommendation_reason?.trim() || null : null,
    }),

    /* 확정 → 다음 건. 내 판독 대기(영상 있음 · AI 안 도는 중) 중 가장 오래된 것.
       ⚠ ?assigned=me · read_status 는 서버가 아직 안 거를 수 있다 — 여기서
         한 번 더 거른다. 담당자 칸이 오고 내 번호를 알면 남의 것은 뺀다 */
    after: async (id) => {
      const rows = await rad.rows({ assigned: "me", read_status: "pending,draft",
                                    ordering: "performed_at", page_size: 50 });
      const me = getMe()?.staff_id ?? null;
      const next = rows.find((r) => String(r.study_id ?? r.id) !== String(id)
        && (r.read_status === "pending" || r.read_status === "draft")
        && (r.image_count == null || r.image_count > 0)
        && r.ai_status !== "queued" && r.ai_status !== "running"
        && (me == null || r.assigned_to == null || String(r.assigned_to) === String(me)));
      return next ? (next.study_id ?? next.id) : null;
    },

    /* 맨 위 띠 — 누구 · 번호 · 알레르기 · 모달리티 · 의뢰 질문 · 이전 등급 */
    strip: (d, { priors }) => {
      const p = d.patient ?? {};
      const al = allergyOf(p.contrast_allergy);
      const prev = priors.find((x) => x.birads);
      return [
        [null, `${p.name ?? ""}${ageSex(p)}`],
        ["번호", p.no],
        al ? [al.label, al.note, true] : ["알레르기", "없음"],
        ["모달리티", label(MODALITY, asModality(d.unit?.modality))],
        ["의뢰 질문", askOf(d)],
        ["이전 BI-RADS", prev
          ? `${String(prev.birads).replace(/^BI-RADS\s*/i, "")} · ${H.day(prev.at)}` : "없음"],
      ];
    },
    AiSummary: RadiologyAiSummary,

    /* ⚠ 확정된 검사 — Read.jsx 가 폼 대신 이것을 그린다. fin 은 현재 판독 행 */
    Final: ({ d, fin, failed }) => {
      if (!fin) {
        return <p className="muted">{failed ? "확정 판독을 불러오지 못했습니다." : "현재 확정 판독 행을 찾지 못했습니다."}</p>;
      }
      return (
        <>
          <Facts items={[
            ["판정 등급", fin.category ? `BI-RADS ${label(BIRADS_LABEL, fin.category)}` : "—"],
            d.density_category && ["밀도", densityText(d)],
            fin.recommendation && ["권고", label(RECOMMENDATION, fin.recommendation)],
            fin.recommendation_reason && ["권고 사유", fin.recommendation_reason],
            ["판독의", fin.assessed_by_name ?? (fin.assessed_by != null ? `직원 #${fin.assessed_by}` : "—")],
            ["확정", fin.finalized_at],
          ]} />
          <p className="vfin-k">판독 소견</p>
          <p className="quote">{fin.finding_note || "—"}</p>
        </>
      );
    },
    need: {
      view: "radiology.read.view",
      ai: "radiology.ai.view",
      draft: "radiology.read.draft",
      finalize: "radiology.read.finalize",
    },
    /* 서버 확정(PATCH …/finalize)은 바디를 안 읽고 임시저장 행만 final 로
       올린다 — 화면의 지금 값을 먼저 임시저장하고 확정한다(screens/Read.jsx) */
    draftBeforeFinalize: true,
    /* 판정 등급(BI-RADS)은 모달리티와 상관없이 판독의 핵심이다 — MRI
       도 적는다(ACR BI-RADS MRI · 4 는 세분 없음). MRI 는 AI 소견에
       등급이 없는 경우가 많아 소견문이 곧 근거라 소견도 같이 요구한다. */
    ready: (f, d) => d?.unit?.modality === "mri"
      ? Boolean(f.category) && Boolean(f.finding_note?.trim())
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
      const mod = asModality(d.unit?.modality);
      /* 맘모 · MRI 는 뷰어가 전체를 한 번에 받는다(휠 · MPR) — 골라 끼우는
         목록이 아니다. ⚠ 전에는 눌러도 안 바뀌는 「촬영 뷰」 칸 넷이 단추처럼
         서 있었다(09-28 제거). MRI Phase 이름만 한 줄로 적는다 */
      const isCornerstone = mod === "mri" || mod === "mammo" || Boolean(d.stack_manifest || d.volume_manifest);
      const al = allergyOf(d.patient?.contrast_allergy);
      return (
        <>
          {/* 조영제일 때만 경고 띠 — 그 밖의 알레르기는 맨 위 띠에 있다 */}
          {al?.contrast && <Warn>조영제 알레르기 — {al.note}</Warn>}
          <Facts items={[
            ["검사명", d.unit.exam_name],
            ["모달리티", label(MODALITY, mod)],
            (d.unit.device ?? d.device_name) && ["촬영 장비", d.unit.device ?? d.device_name],
            ["촬영일", d.unit.performed_at],
            ["검사 상태", text(d.unit, "read_status", READ_STATUS, "status_label")],
            askOf(d) && ["의뢰 질문", askOf(d)],
            d.density_category && ["밀도", densityText(d)],
            mod === "mri" && (d.series ?? []).length > 0
              && ["촬영 Phase", d.series.map((s) => s.name).join(" · ")],
          ]} />

          {isCornerstone ? null : (
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

    Doctor: ({ d, f, set, pendingMark, onLesionCreated, phrases, insert }) => {
      const add = useCan("radiology.lesion.add");
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
          {/* ⚠ AI 가 낸 등급(lesion.birads_model)과 다른 컬럼이다.
              한 화면에 있지만 섞이지 않게 자리를 갈라 둔다.
              선택지는 모달리티마다 다르다 — MRI 는 4 에 세분이 없다 */}
          <label className="field">
            <span>판정 등급 (BI-RADS)</span>
            <select value={f.category ?? ""} onChange={(e) => set("category", e.target.value)}>
              <option value="">선택하세요</option>
              {biradsFor(d.unit?.modality).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>

          {/* 밀도 — 검사(Study) 값이라 여기서는 읽기만. 판독 저장이 안 받는다 */}
          {d.density_category && (
            <p className="muted small">유방 밀도 {densityText(d)}</p>
          )}
          {/* 권고 — 안 골라도 확정된다. 고르면 사유 칸이 열린다 */}
          <label className="field">
            <span>권고</span>
            <select value={f.recommendation ?? ""} onChange={(e) => set("recommendation", e.target.value)}>
              <option value="">— 없음</option>
              {Object.entries(RECOMMENDATION).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          {f.recommendation && (
            <label className="field">
              <span>권고 사유</span>
              <input maxLength={250} value={f.recommendation_reason ?? ""}
                     onChange={(e) => set("recommendation_reason", e.target.value)} />
            </label>
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
            <textarea className="lg" rows={8} value={f.finding_note ?? ""}
                      onChange={(e) => set("finding_note", e.target.value)} />
          </label>
          {/* 상용구 — ⚠ label 밖에 둔다. label 안의 단추는 그 label 의 대상이 되어
              소견 칸을 눌러도 첫 상용구가 눌린다 */}
          <Phrases groups={phrases} onPick={insert} />
        </>
      );
    },
  },

  /* ── 4장 · 전체 환자 목록 ─────────────────────────────── */
  list: {
    title: "환자 목록",
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
    /* 상태 · 모달리티 · 내 것 — 서버가 거르고(read_status · modality ·
       assigned=me) 화면이 한 번 더 거른다(lib/Filters) */
    filters: LIST_FILTERS,
    /* 상세 칸 머리 — 누구의 무슨 검사인지 */
    detailTitle: (d) => [H.nameOf(d), label(MODALITY, asModality(d.modality))].filter(Boolean).join(" · "),

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
      patient: `${H.nameOf(r)}${H.who(r) ? ` (${r.age ?? "?"}/${label(SEX, r.sex)})` : ""}`,
      modality: label(MODALITY, asModality(r.modality)),
      /* 「09-28 08:05」 — 목록 칸이 좁아 해를 뺀다(상세에 전체가 있다) */
      performed: r.performed_at ? String(r.performed_at).slice(5, 16).replace("T", " ") : "—",
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
      /* 알레르기는 정보 칸에 한 번 — 전에는 위 경고줄과 정보 칸 둘이었다 */
      const al = H.allergyTag(d.contrast_allergy);
      return (
        <>
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
                ["환자", `${H.nameOf(d)}${H.who(d) ? ` (${d.age ?? "?"}/${label(SEX, d.sex)})` : ""}`],
                ["환자번호", d.patient_no],
                al && [al.label, al.note ?? "있음"],
                ["의뢰", [label(PURPOSE, d.exam_purpose), d.purpose].filter(Boolean).join(" · ") || "—"],
                ["촬영", [d.performed_at && String(d.performed_at).slice(0, 16).replace("T", " "), d.device]
                  .filter(Boolean).join(" · ") || "—"],
                ["담당 판독의", d.assigned_to_name ?? d.assigned_to ?? "—"],
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
    title: "판독 정정",
    categoryLabel: "판정 등급 (BI-RADS)",
    /* 검사의 모달리티마다 다르다 — MRI 는 4, 맘모 · 초음파는 4a~4c */
    categories: (d) => biradsFor(d?.unit?.modality),
    /* 코드 → 「4b — 중등도 악성 의심」 (기존 판독 · 이력 칸) */
    categoryText: (v) => (v ? `BI-RADS ${label(BIRADS_LABEL, v)}` : "—"),
    saveHint: "저장하면 새 판독이 만들어지고 유방외과로 전달됩니다. 옛 판독은 지워지지 않습니다.",
    need: { view: "radiology.amend.view", save: "radiology.amend.save" },

    /* 옛 서버 · 목업은 판독 응답에 history 를 싣는다. 실서버는 안 싣는다 —
       그때 Amend.jsx 가 GET /assessments?study= 로 판 목록을 받는다 */
    history: (d) => d.history ?? [],

    /* 환자는 위 띠(PatientBar)에 있다 — 검사만 */
    Info: ({ d }) => (
      <Facts items={[
        ["검사명", d.unit.exam_name],
        ["모달리티", label(MODALITY, asModality(d.unit?.modality))],
        ["촬영 일시", d.unit.performed_at],
        askOf(d) && ["의뢰 질문", askOf(d)],
      ]} />
    ),
  },
};

/* 2장 ① 품질 — [승인] · [반려 → 재촬영].
 *
 *   승인   PATCH /radiology/studies/{id}/upload {quality_status:"accepted"}
 *          — 그래야 ② AI 분석이 켜진다(Upload.jsx 의 gate)
 *   반려   같은 자리에 "rejected" → POST /exam-orders/{오더}/retake
 *          ⚠ 순서가 이렇다. 서버는 반려된 오더에서만 재촬영을 만든다
 *          ⚠ 되돌릴 수 없다(새 오더가 촬영 대기에 선다) — 한 번 더 묻는다
 *
 * 반려는 됐는데 재촬영이 실패하면(오더 번호를 모름 · 네트워크) 반려 상태에서
 * [재촬영 요청]만 다시 누를 수 있게 남긴다 — 반려를 또 걸지 않는다 */
function Quality({ cfg, id, orderId, quality, setQuality, locked }) {
  const send = useCan(cfg.upload.need.send);
  const retake = useCan("radiology.retake");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [next, setNext] = useState(null);     /* 새 재촬영 오더 번호 */

  async function accept() {
    setBusy(true); setMsg(null);
    try {
      await cfg.api.quality(id, "accepted");
      setQuality("accepted");
    } catch (e) {
      setMsg(e.detail || "승인하지 못했습니다.");
    } finally { setBusy(false); }
  }

  async function askRetake() {
    if (!orderId) {
      setMsg("오더 번호를 몰라 재촬영을 걸 수 없습니다 — 촬영 대기에서 다시 들어와 주세요.");
      return;
    }
    const out = await cfg.api.retake(orderId);
    const n = out?.exam_order_id ?? out?.new_exam_order_id ?? true;
    setNext(n);
  }

  async function reject() {
    setBusy(true); setMsg(null);
    try {
      if (quality !== "rejected") {
        await cfg.api.quality(id, "rejected");
        setQuality("rejected");
      }
      await askRetake();
      setAsking(false);
    } catch (e) {
      setMsg(e.detail || "재촬영을 요청하지 못했습니다.");
    } finally { setBusy(false); }
  }

  if (next) {
    return (
      <p className="hint" role="status">
        반려했습니다 — 재촬영 오더{next === true ? "" : ` ${next}번`}을 촬영 대기에 올렸습니다.
      </p>
    );
  }
  return (
    <>
      <p className="muted small">
        {quality === "accepted" ? "승인했습니다 — AI 분석을 걸 수 있습니다."
          : quality === "rejected" ? "반려했습니다. 재촬영 오더가 아직 없습니다."
            : "올린 촬영본을 보고 판정합니다. 승인해야 분석이 걸립니다."}
      </p>
      {asking ? (
        <div className="stack">
          <span className="hcard-k">반려하면 새 촬영 오더가 촬영 대기에 섭니다</span>
          <button type="button" className="btn fill" onClick={reject} disabled={busy}>
            {busy ? "요청 중…" : "반려하고 재촬영"}
          </button>
          <button type="button" className="btn line" onClick={() => setAsking(false)} disabled={busy}>그만</button>
        </div>
      ) : (
        <div className="stack">
          {quality !== "rejected" && (
            <button type="button" className={`btn ${quality === "accepted" ? "line" : "fill"}`}
                    onClick={accept} disabled={busy || locked || quality === "accepted" || !send.ok}
                    title={send.attrs.title}>
              {quality === "accepted" ? "승인됨" : "승인"}
            </button>
          )}
          <button type="button" className="btn line" onClick={() => setAsking(true)}
                  disabled={busy || locked || !retake.ok}
                  title={retake.ok ? (locked ? "분석을 건 뒤에는 반려하지 않습니다" : undefined) : retake.attrs.title}>
            {quality === "rejected" ? "재촬영 요청" : "반려 → 재촬영"}
          </button>
        </div>
      )}
      {msg && <p className="hint">{msg}</p>}
    </>
  );
}

