import { path } from "../api";
import { go } from "../nav";
import * as H from "./home";
import { Chip, Facts, Fold } from "../lib/Parts";
import { Body } from "../lib/Body";
import { Seen, Two } from "../lib/ListCells";
import { shortAt } from "../lib/shortAt";
import { useApi } from "../lib/useApi";
import { useFile } from "../lib/files";
import Stage, { MaskKeys, PATHOLOGY_MASK_COLORS } from "../lib/Stage";
import PathologyAi from "./PathologyAi";
/* 판독(3장) 전용 — 09-28 재배치 */
import { PathologyAiSummary } from "./PathologyAi";
import { Phrases } from "../lib/Parts";
import { currentAssessment } from "../api";
import { getMe } from "../perm";
import { BIRADS_LABEL, GUIDANCE_ROUTE, HER2, HISTOLOGIC_TYPE, MODALITY, NOTTINGHAM, RECEPTOR,
         SPECIMEN_TYPE, modality as asModality } from "../codes";
import { ACCESSION_STATUS, B_CATEGORY, B_CATEGORY_LABEL, DIAGNOSIS,
         label, text } from "../codes";
/* 홈 · 큐 · 업로드 · 목록(0·1·2·4장) 전용 — 09-28 재배치 */
import { BIRADS_LABEL as BR_LABEL, GUIDANCE_ROUTE as GUIDE, MODALITY as MOD,
         SPECIMEN_TYPE as SP_TYPE, modality as modCode } from "../codes";
import { getMe as whoAmI } from "../perm";

/* 병리과 설정 — 공통 화면 다섯 장에 끼워 넣는 «다른 점»만 모은 파일
 * ════════════════════════════════════════════════════════════════
 *
 * 화면의 뼈대는 screens/ 에 있고 두 과가 같이 쓴다. 이 파일에는
 * 병리과에서만 다른 것이 들어간다.
 *
 * 영상의학과와 갈리는 지점
 *   판독 단위   검사(study) 가 아니라 **검체(specimen)**
 *   등급 체계   BI-RADS 가 아니라 **b_category (b1~b5)**
 *   AI 소견     등급·크기·확신도가 아니라 **AI 계측값 · TSR · 세포 수 · 간질**
 *   없는 것     조영제 알레르기 · 재촬영 · 병변 추가 · 모달리티 구분 ·
 *               **판독 정정(5장)** — 확정 사양서 §8-2, 병리는 정정
 *               경로를 두지 않는다. 확정 후 오류는 새 검체로 처리한다
 *
 * ⚠ 09-28 결정 — **sTIL 은 병리의가 검체 단위로 직접 입력한다.**
 *   AI 가 낸 원시값(stil_percent)은 "sTIL"이 아니라 "AI 계측값"으로만
 *   부른다 — 척도가 달라 같은 이름을 쓰면 두 값을 직접 비교하는 것처럼
 *   읽힌다. 보정계수는 안 쓴다.
 *   stil_calibrated 라는 필드 이름은 그대로 쓰지만(모델 필드명이라
 *   마이그레이션 없인 못 바꾼다) 뜻은 "AI가 보정한 값"이 아니라
 *   "병리의가 입력한 sTIL"이다.
 */

/* ── 판독(3장) 보조 ───────────────────────────────────────────
   상용구 — ⚠ 서버가 주는 값이 아니다. 저장 경로가 없어 여기 박았다.
   판독 소견 칸 위 칩으로 뜬다(lib/Parts Phrases) */
const PHRASES = [
  ["조직", ["침윤성 유관암 (IDC)", "관상피내암 (DCIS), 저등급"]],
  ["양성", ["섬유선종", "섬유낭종성 변화"]],
  ["검체", ["표적 병변 미포함 가능성", "검체량 부족 — 재채취 권고"]],
  ["결론", ["악성 소견 없음", "추가 면역조직화학 검사 시행"]],
];

/* 「2026-09-28 09:10」 · 「3시간 전」 — 채취 뒤 얼마나 지났나(고정 시간) */
const readableAt = (v) => String(v).replace("T", " ").slice(0, 16);
function ago(v) {
  const t = Date.parse(v);
  if (!Number.isFinite(t)) return "";
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 60) return `${m}분 전`;
  if (m < 60 * 48) return `${Math.round(m / 60)}시간 전`;
  return `${Math.round(m / 1440)}일 전`;
}

/* 「김환자 (51/여)」. ⚠ 이름 · 나이 · 성별이 비어 오는 줄이 있다 — 그대로
   이으면 「null (null/)」이 찍힌다. 이름은 H.nameOf 로(없으면 「환자 #id」),
   괄호는 아는 것만 */
function patientText(r) {
  if (!r) return "";
  /* 「김하늘 (44 · 여)」 — 빈 것은 안 쓴다(H.who). 「(51/)」가 나오던 것 */
  const bits = H.who(r);
  return bits ? `${H.nameOf(r)} (${bits})` : H.nameOf(r);
}

/* ── 서버 부르는 자리를 공통 이름으로 맞춘다 ──────────────────
   공통 화면은 cfg.api.detail(id) 처럼 부른다. 실제 경로가 과마다
   달라도 화면은 몰라도 된다 */
const api = {
  queue:      ()      => path.queue(),
  detail:     (id)    => path.specimen(id),  /* 1장 큐 */
  listDetail: (id)    => path.specimen(id),  /* 4장 목록 — 병리는 둘 다 검체다 */
  assign:     (id)    => path.assign(id),
  uploadInfo: (id)    => path.uploadInfo(id),
  /* ⚠ 판독 화면(3장)이 원본·마스크를 받을 때 쓴다. 이게 빠져 있으면
     lib/files.js 의 useFile 이 티켓을 못 받아 **아무 말 없이 빈
     뷰어**가 된다 — 오류도 안 나고 「원본 영상이 아직 연결되지
     않았습니다」만 뜬다. 목업은 image.url 로 와서 티켓을 안 타기
     때문에 목업에서는 멀쩡해 보인다 */
  ticket:     (b)     => path.ticket(b),
  analyze:    (id)    => path.analyze(id),
  progress:   (id)    => path.progress(id),
  /* ⚠ 병리는 판독 조회 경로가 아직 없다 (2026-09-16 확인).
     있는 둘을 합쳐 화면이 쓰는 모양으로 만든다.
       GET /specimens/{id}          검체 · 판정 · 정정 이력
       GET /specimens/{id}/upload   올린 파일 목록 (여기에만 있다)
     /specimens/{id}/read 가 생기면 이 함수가 한 줄로 줄어든다 */
  read: async (id) => {
    const [s, up, progress] = await Promise.all([
      path.specimen(id),
      path.uploadInfo(id),
      path.progress(id).catch(() => null),
    ]);
    const ai = progress?.results ?? progress?.items ?? progress?.data?.results
      ?? (Array.isArray(progress?.data) ? progress.data : null)
      ?? (Array.isArray(s.ai) ? s.ai : []);
    const rows = (Array.isArray(ai) ? ai : []).map(pathAiRow);
    const result = toRead(s, up, rows);
    return { ...result, ai: rows };
  },
  draft:      (id, b) => path.draft(id, b),
  finalize:   (id, b) => path.finalize(id, b),
  list:       (o)     => path.list(o),
  /* 1장 영상 대조 — 겨눈 병변 + 그 검사의 최신 확정 BI-RADS */
  correlation: (s)    => path.correlation(s),
  /* 홈 · 목록 「불일치」 */
  openDiscordances: () => path.openDiscordances(),
  /* 09-26 추가 — 큐(1장)의 「이 환자의 이력」 칸이 병리는 timeline이
     없다고 믿고 「이 과에는 이력을 부르는 경로가 없습니다」를 띄우고
     있었다(Queue.jsx의 Past()가 typeof cfg.api.timeline === "function"
     으로 판정). 서버는 이미 지원한다 — api.js의 path.timeline 참고. */
  timeline:   (pid)   => path.timeline(pid),
  /* amend 없음 — 확정 사양서 §8-2: 병리는 판독 정정 경로를 두지 않는다.
     확정 후 오류는 새 검체로 처리한다 (services/django/core/views/
     pathology.py 상단 docstring) */
  /* complete 없음 — 병리에는 «오더 확정» 단계가 없다 */
};

/* GET /specimens/{id}/upload 이 주는 StorageObject 원본 필드를 화면이
 * 기대하는 {id, name, w, h, image} 모양으로 바꾼다 — api.js 의 radFile()과
 * 같은 자리다. 병리는 storage_objects 가 아니라 uploads 로 온다
 * ({specimen_id, uploads} — views/pathology.py 의 SpecimenUploadListView). */
function pathFile(raw = {}) {
  const bytes = raw.byte_size;
  const size = typeof bytes === "number" ? `${(bytes / 1048576).toFixed(1)} MB` : "";
  const kind = raw.kind ?? raw.file_kind ?? raw.type ?? "image";
  const image = fileRef(raw.image ?? raw.file ?? raw.object ?? raw.object_key, kind === "mask");
  const mask = fileRef(raw.mask ?? raw.mask_image ?? raw.segmentation
    ?? raw.labelmap ?? raw.mask_object ?? raw.mask_file, true);
  return {
    ...raw,
    id: raw.storage_object_id ?? raw.id,
    name: raw.name ?? raw.object_key ?? `파일 ${raw.storage_object_id ?? ""}`,
    size,
    w: raw.w ?? raw.width_px,
    h: raw.h ?? raw.height_px,
    image,
    mask,
    kind,
  };
}

/* 서버가 파일 참조를 {key}, {url}, 문자열 중 어느 모양으로 내려도
 * Stage/useFile 이 이해하는 형태로 맞춘다. 세그멘테이션은 원본 업로드와
 * 별도 storage object 로 내려올 수 있으므로 이 변환을 공용으로 쓴다. */
function fileRef(value, derived = false) {
  if (!value) return null;
  if (typeof value === "string") {
    return /^(https?:|data:|blob:)/i.test(value)
      ? { url: value }
      : { key: value, ...(derived ? { derived: true } : {}) };
  }
  if (typeof value !== "object") return null;
  if (value.url || value.src || value.download_url) {
    return { url: value.url ?? value.src ?? value.download_url };
  }
  if (value.key || value.object_key) {
    return { key: value.key ?? value.object_key, ...(derived ? { derived: true } : {}) };
  }
  return null;
}

/* 서버가 주는 legend 값(tissue_mask_legend, 영문 "other"/"tumor"/"stroma")을
 * 화면 표시용 한글로 바꾼다. 번호→뜻 대응은 여전히 서버 값을 그대로 따른다 —
 * 여기서 바꾸는 건 그 뜻을 화면에 적을 글자뿐이고, 서버가 안 보낸 키는
 * 원래 영문 그대로 둔다(모르는 값을 지우지 않는다). */
const PATHOLOGY_LEGEND_KO = {
  other: "기타(배경·지방 등)",
  tumor: "종양",
  stroma: "간질",
};

export function translateLegend(legend) {
  if (!legend) return legend;
  return Object.fromEntries(
    Object.entries(legend).map(([v, name]) => [v, PATHOLOGY_LEGEND_KO[name] ?? name])
  );
}

function isMaskFile(file = {}) {
  const kind = String(file.kind ?? "").toLowerCase();
  return ["mask", "segmentation", "labelmap", "overlay"].includes(kind)
    || /(^|[-_.])(mask|segmentation|labelmap)([-_.]|$)/i.test(file.name ?? "");
}

function attachMasks(crops, files, aiRows) {
  const masks = files.filter(isMaskFile);
  return crops.map((crop, index) => {
    if (crop.mask) return crop;

    const ai = aiRows[index] ?? {};
    const aiMask = fileRef(ai.mask ?? ai.mask_image ?? ai.segmentation
      ?? ai.labelmap ?? ai.overlay, true);
    if (aiMask) return { ...crop, mask: aiMask };

    /* 우선 원본 파일 id/이름으로 짝을 찾고, 식별자가 없는 응답은
     * 원본과 마스크가 같은 순서로 내려오는 경우만 순서로 연결한다. */
    const match = masks.find((mask) => {
      const source = mask.source_id ?? mask.source_object_id ?? mask.source_storage_object_id
        ?? mask.parent_id ?? mask.original_id;
      return source != null && String(source) === String(crop.id);
    }) ?? masks.find((mask) => {
      const base = String(crop.name ?? "").replace(/\.[^.]+$/, "");
      return base && String(mask.name ?? "").includes(base);
    }) ?? masks[index];
    return match?.image ? { ...crop, mask: match.image } : crop;
  });
}

/* 서버 두 응답 → 판독 화면이 쓰는 한 덩어리.
 *
 * **서버 모양이 바뀌면 여기만 고친다.** 화면 다섯 장은 이 모양만 안다. */
/* /ai-results 는 **봉투**를 준다 — { ai_result_id, run_status, abstained,
   result: { image, socket_id, result: { …모델이 낸 값… } } }.
   화면은 안쪽 값을 이름으로 찾는데 봉투를 그대로 넘기고 있었다. 그래서
   sTIL·TSR·세포 수가 전부 「—」로, 간질 상태는 undefined !== "absent" 라
   늘 「있음」으로 나왔다(09-23 검체 40 에서 확인). 한 겹 벗겨 준다.

   ⚠ 09-28 결정으로 stil_percent 를 이제 화면에 낸다 — 단, 이름은
     "sTIL"이 아니라 "AI 계측값"이다. 임상 육안 TIL(병리의가 입력하는
     stil_calibrated, Specimen 쪽에서 읽는다 — toRead() 참고)과 척도가
     달라 같은 이름을 쓰면 안 된다. 저/중/고 라벨도 안 쓴다 — 그건
     "sTIL 수치"라는 임상 판정의 언어라 AI 계측값에 붙이면 안 된다. */
function pathAiRow(row = {}) {
  const env = row.result ?? {};
  const r = env.result ?? {};
  return {
    ...row,
    id: row.ai_result_id ?? row.id,
    name: env.image?.filename ?? row.name,
    abstained: Boolean(row.abstained ?? env.abstained),
    abstain_reason: row.abstain_reason ?? env.reason ?? null,

    stroma_status: r.stroma_status ?? null,
    /* AI 원시값. "sTIL"이라 안 부른다 — PathologyAi.jsx 에서 "AI 계측값"
       으로 표시한다. */
    stil_percent: r.stil_percent ?? null,

    /* TSR 은 종양 비율로 읽는다. 간질 비율은 짝으로 함께 넘긴다. */
    tsr_percent: r.tsr_tumor_percent ?? null,
    tsr_tumor_percent: r.tsr_tumor_percent ?? null,
    tsr_stroma_percent: r.tsr_stroma_percent ?? null,

    cell_counts: {
      total: r.n_cells_total ?? null,
      til: r.n_cells_til ?? null,
      til_stromal: r.n_cells_til_stromal ?? null,
    },
    n_cells_total: r.n_cells_total ?? null,
    n_cells_til: r.n_cells_til ?? null,
    n_cells_til_stromal: r.n_cells_til_stromal ?? null,

    tumor_area_px: r.tumor_area_px ?? null,
    stroma_area_px: r.stroma_area_px ?? null,
    immune_cell_area_px: r.immune_cell_area_px ?? null,
    /* serving 1.1.0(09-28) — 분자가 「간질 안 면역세포 주변 5µm 영역」이 됐다.
       1.0.0 식(핵 면적 × 1.5)은 stil_nucleus_percent 로 따로 온다 */
    immune_region_area_px: r.immune_region_area_px ?? null,
    stil_nucleus_percent: r.stil_nucleus_percent ?? null,
    til_region_radius_um: r.til_region_radius_um ?? null,
    mpp: r.mpp ?? null,

    /* 마스크 픽셀값의 뜻 — {"0":"other","1":"tumor","2":"stroma"} 꼴.
       뷰어가 색 범례를 이걸로 적는다(lib/Stage.jsx 의 MaskKeys) */
    mask_legend: r.tissue_mask_legend ?? null,
  };
}

function toRead(s, up, aiRows = []) {
  const files = (up.uploads ?? []).map(pathFile);
  const cropFiles = files.filter((file) => !isMaskFile(file));
  return {
    /* ⚠ id 가 빠져 있어 판독 화면의 「지난 기록」이 늘 0 이었다(09-28) —
       이력은 환자 번호로 부른다. s.patient 가 FK 번호다 */
    patient: {
      id: s.patient ?? s.patient_id ?? null,
      name: s.patient_name, age: s.age, sex: s.sex,
      no: s.patient_number || s.patient_no, birth: s.birth, phone: s.phone, allergy: s.allergy,
    },
    unit: {
      id: s.id, no: s.specimen_no, kind: s.kind, method: s.method,
      collected_at: s.collected_at, site: s.site,
      /* 판독 화면 왼쪽 「검체」 칸 · 영상 대조 칸이 쓴다 (09-28) */
      specimen_type: s.specimen_type ?? null,
      guidance_route: s.guidance_route ?? null,
      bound_by_name: s.bound_by_name ?? null,
      clinical_note: s.clinical_note ?? null,
      target_snapshot: s.target_snapshot ?? null,
      lesion: s.lesion ?? null,
      finalized_at: s.finalized_at ?? null,
      finalized: Boolean(s.finalized_at) || s.finalized === true,
      /* ⚠ 서버는 코드(accession_status)만 준다 — 4장 목록(list.row)과
         같은 방식으로 여기서도 라벨을 입힌다. s.status_label 을 그대로
         읽던 전 코드는 그런 필드가 서버에 없어 항상 빈칸이었다. */
      reported_by: s.reported_by,
      status_label: text(s, "accession_status", ACCESSION_STATUS, "status_label"),
      amend_history: s.amend_history ?? [],
      /* 09-28 추가 — 병리의가 검체 단위로 직접 입력하는 sTIL. AI 결과
         (ai_result 행)가 아니라 **검체(Specimen) 응답**에서 읽는다 —
         AI 소견 패널(PathologyAi.jsx)이 보여 주는 "AI 계측값"과는
         다른 값이다. 백엔드가 아직 이 필드를 안 주는 배포에도 화면이
         깨지지 않도록 없으면 null 로 둔다. */
      stil_calibrated: s.stil_calibrated ?? null,
      stil_source: s.stil_source ?? null,
    },
    radiology_summary: s.radiology_summary ?? null,
    /* 크롭 한 장 = 원본 + (있으면) 세그멘테이션 마스크.
       마스크가 업로드 목록의 별도 파일로 오거나 AI 결과 안에 포함될 수
       있어 attachMasks()가 두 응답을 병합한다. 두 응답 모두에 없으면
       그때만 「마스크 없음」으로 표시한다. */
    crops: attachMasks(cropFiles.map((f) => ({
      id: f.id, name: f.name,
      w: f.w ?? 512, h: f.h ?? 512,      /* 크롭은 512×512 */
      image: f.image,
      mask: f.mask ?? null,
    })), files, aiRows),
    images: cropFiles.map((f) => ({ id: f.id, name: f.name })),
    ai: aiRows,
    /* ⚠ 09-28 확인 — Specimen 응답엔 "doctor"라는 필드가 없다.
       s.doctor 는 늘 undefined 였고, 그래서 Read.jsx 의 편집 폼(f)이
       검체를 다시 열 때마다 b_category·diagnosis·finding_note 를
       매번 빈 값으로 시작하고 있었다(기존 결함 — 임시저장을 다시 열면
       써 둔 값이 안 보였다). sTIL 입력칸을 붙이며 같이 고친다 —
       검체 필드에서 직접 시드로 채운다.
       stil_calibrated 는 DB 가 소수 2자리로 주는데(레거시 컬럼) 입력
       칸 계약은 1자리다 — 안 건드린 값을 그대로 다시 보내면 2자리라
       거부(400)당하니 여기서 1자리로 반올림해 둔다. */
    doctor: {
      b_category: s.b_category ?? null,
      diagnosis: s.diagnosis ?? null,
      finding_note: s.finding_note ?? "",
      stil_calibrated: s.stil_calibrated != null
        ? Number(s.stil_calibrated).toFixed(1)
        : null,
      /* 09-28 — 조직형 · 등급 · 수용체 · Ki-67 (서버 값은 codes.js) */
      histologic_type: s.histologic_type ?? "",
      nottingham_grade: s.nottingham_grade ?? "",
      er_status: s.er_status ?? "",
      pr_status: s.pr_status ?? "",
      her2_status: s.her2_status ?? "",
      ki67_percent: s.ki67_percent != null ? String(Number(s.ki67_percent)) : "",
    },
  };
}

/* ── 홈 · 큐 · 업로드 · 목록이 같이 쓰는 것 (09-28) ─────────────── */

/* 검체 종류 · 유도 — 서버 코드면 한글로, 모르는 글이면 그대로(codes.label) */
const kindText = (v) => label(SP_TYPE, v);
const guideText = (v) => label(GUIDE, v);

/* 「09-28 08:20 · 3시간 전」 — 채취 시각과 지난 시간 */
function collectedText(at) {
  if (!at) return null;
  const w = H.waited(at);
  return `${String(at).slice(5, 16).replace("T", " ")}${w ? ` · ${w} 전` : ""}`;
}

/* 내가 맡은 검체인가. 서버가 assigned=me 를 알면 이미 걸러 온다 — 화면은
   이름이 적혀 오는 경우(목업 · assigned_to_name)만 /me 이름과 맞춘다.
   번호로만 오면 못 맞춰 «누군가 맡은 것»까지만 거른다 */
function mine(r) {
  /* 09-28 — /me 가 staff_id 를 준다. 번호끼리 견주는 것이 먼저다 */
  const myId = whoAmI()?.staff_id;
  if (myId != null && typeof r.assigned_to === "number") return r.assigned_to === myId;
  const who = r.assigned_to_name ?? (typeof r.assigned_to === "string" ? r.assigned_to : null)
    ?? r.reported_by ?? null;
  const me = whoAmI()?.name;
  if (who && me) return who.includes(me);
  return r.assigned_to != null;
}

/* 열린 불일치 → 걸린 검체 · 환자. 불일치 행이 검체를 가리키면 검체로,
   못 가리키면(목록 행은 환자만 싣는다) 그 환자의 검체 전부로 본다 */
function discSets(rows = []) {
  const spec = new Set();
  const pat = new Set();
  rows.forEach((d) => {
    const sid = d.specimen_id ?? d.specimen ?? d.lesion?.specimen_id;
    if (sid != null) spec.add(String(sid));
    else {
      const pid = d.patient_id ?? d.patient?.patient_id ?? d.patient;
      if (pid != null && typeof pid !== "object") pat.add(String(pid));
    }
  });
  return { spec, pat };
}
const isDisc = (r, ctx) => Boolean(ctx?.disc) && (ctx.disc.spec.has(String(r.id))
  || ctx.disc.pat.has(String(r.patient ?? r.patient_id)));

/* 판독 단계 — api.js 의 read_state(assigned_to · finalized_at 로 센 것) */
const STATE = { waiting: "미접수", reading: "판독 중", final: "확정" };
const STATE_TONE = { waiting: "line", reading: "fill", final: "dot" };

/* 목록 칩 한 묶음 — 주소 ?f= 로 온다(홈 흐름 줄 · 「초안」 줄이 여기로) */
const LIST_FILTERS = [
  { key: "f", label: "보기",
    items: [
      { key: "all", name: "전체" },
      { key: "mine", name: "내 판독 중", query: { assigned: "me", finalized: "no" },
        test: (r) => !r.finalized && mine(r) },
      { key: "open", name: "미확정", query: { finalized: "no" }, test: (r) => !r.finalized },
      { key: "final", name: "확정", query: { finalized: "yes" }, test: (r) => r.finalized },
      /* 서버에 불일치 필터가 없다 — 열린 불일치 목록(list.context)과 맞춘다 */
      { key: "disc", name: "불일치", test: isDisc },
    ] },
];

/* 병변 크기 — 서버가 「12.30」처럼 소수 둘째 자리 글자로 준다 */
function sizeMm(l) {
  const v = l?.size_mm ?? l?.measured_size_mm ?? l?.ai_size_mm;
  return v == null || v === "" ? null : `${Number(v)}mm`;
}

/* 영상 대조 — 1장 가운데.
   ① 겨눈 병변(Specimen.lesion) → 그 검사의 최신 확정 BI-RADS (서버 두 번)
   ② 없으면 바인딩 때 찍어 둔 표적 한 줄(target_snapshot)
   ③ 그도 없으면 옛 목업의 radiology_summary
   ⚠ 영상 판정이다 — 병리 등급(B 분류)과 다른 체계라 그 말을 붙인다 */
function Correlate({ d, cfg }) {
  const hasLesion = d.lesion != null && typeof d.lesion !== "object";
  const cor = useApi(() => (hasLesion ? cfg.api.correlation(d) : Promise.resolve(null)), [d.id, hasLesion]);
  const c = cor.data;
  const snap = typeof d.target_snapshot === "string" ? d.target_snapshot
    : d.target_snapshot ? Object.values(d.target_snapshot).filter((v) => v != null && typeof v !== "object").join(" · ")
      : null;
  const rs = d.radiology_summary;
  const lesion = c?.lesion;
  const lines = [
    c?.category && ["최신 확정", `BI-RADS ${label(BR_LABEL, c.category)}${c.finalized_at ? ` · ${String(c.finalized_at).slice(5, 10)}` : ""}`],
    lesion && ["병변", [lesion.label ?? (lesion.lesion_id != null ? `#${lesion.lesion_id}` : null),
      c.modality && label(MOD, modCode(c.modality)), lesion.site,
      sizeMm(lesion)]
      .filter(Boolean).join(" · ")],
    snap && ["표적", snap],
    !c?.category && rs?.birads && ["BI-RADS", rs.birads],
    !c && rs?.note && ["영상 소견", rs.note],
  ].filter(Boolean);
  return (
    <div className="work-ask-q">
      <span className="section-label">영상 대조</span>
      {cor.loading && hasLesion ? <p className="muted small">불러오는 중…</p>
        : lines.length ? <Facts items={lines} />
          : <p className="muted small">이 검체에 연결된 표적 병변 · 영상 판정이 없습니다</p>}
      {lines.length > 0 && <p className="muted small">영상 판정입니다 — 병리 등급(B 분류)과 다른 체계입니다.</p>}
    </div>
  );
}

export const pathology = {
  key: "pathology",
  name: "병리과",
  api,
  go: go.pathology,

  /* ── 홈 (docs/mockup/PathologyHome.html) ────────────
   *
   * 영상과 같은 틀이다. 다른 것은 판독 단위가 검체라는 것뿐이다.
   */
  home: {
    /* 내 검체만 받는다(assigned=me) — 「내 판독중 · 오늘 확정」은 내 일이다.
       ⚠ 옛 서버는 assigned 를 몰라 전부 준다 — 아래 mine() 이 다시 거른다.
       ⚠ 줄마다 환자를 부르지 않는다(api.js pathRows) */
    load: () => Promise.all([
      api.queue(),
      H.soft(api.list({ assigned: "me", page_size: 200 })),
      H.soft(api.openDiscordances()),
    ]).then(([queue, list, disc]) => {
      const specimens = H.rows(list).filter(mine);
      return { queue: H.rows(queue), specimens, disc: discSets(H.rows(disc)) };
    }),

    primary: { label: "다음 검체 접수", to: go.pathology.queue(),
               need: "pathology.queue.view" },

    /* 달력은 뺀다 — 찍을 점이 없어 늘 빈 달이었다. 맨 위는 흐름 한 줄 */
    layout: [["flow", "queue", "stuck"], ["done", "handover"], ["todo"]],

    /* 흐름 — 접수 대기 → 내 판독중 → 오늘 확정 → 불일치. 줄을 누르면
       걸러진 목록(?f=)으로 간다 */
    flow: (bag) => {
      if (!bag) return null;
      const { queue, specimens, disc } = bag;
      const today = specimens.filter((r) => r.finalized && H.isToday(r.finalized_at));
      /* 평균 TAT — 채취 → 확정. 두 시각이 다 있는 것만 */
      const spans = today.map((r) => new Date(String(r.finalized_at).replace(" ", "T"))
        - new Date(String(r.collected_at ?? "").replace(" ", "T"))).filter((ms) => ms > 0);
      const avg = spans.length ? spans.reduce((a, b) => a + b, 0) / spans.length : null;
      const tat = avg == null ? null
        : avg >= 86400000 ? `${(avg / 86400000).toFixed(1)}일` : `${Math.round(avg / 3600000 * 10) / 10}시간`;
      const L = go.pathology.list();
      return {
        title: "오늘 흐름",
        summary: tat ? `평균 TAT ${tat} (채취→확정)` : "평균 TAT —",
        items: [
          { name: "접수 대기", count: queue.length, to: go.pathology.queue() },
          { name: "내 판독 중", count: specimens.filter((r) => !r.finalized).length, to: `${L}?f=mine` },
          { name: "오늘 확정", count: today.length, to: `${L}?f=final` },
          { name: "불일치", count: specimens.filter((r) => isDisc(r, { disc })).length, to: `${L}?f=disc` },
        ],
      };
    },

    queue: ({ queue }) => ({
      title: "검체 대기",
      hint: "등록 순서대로",
      empty: "접수 대기 검체가 없습니다",
      /* 「구분」「상태」가 아니라 무엇을 적었는지 */
      cols: { chip: "채취 방식", sub: "검체번호" },
      extra: [{ key: "wait", name: "경과" }],
      rows: queue.map((r) => ({
        id: r.id,
        name: H.nameOf(r),
        no: H.noOf(r),
        meta: H.who(r),
        chip: kindText(r.kind),
        chipTone: "fill",
        sub: r.specimen_no ?? "",
        at: H.at(r.collected_at),
        wait: H.waited(r.collected_at),
        /* 접수 대기 줄이다 — 누르면 그 검체가 열린 접수 화면으로 간다.
           환자 화면으로 보내면 거기서 접수·업로드로 가는 길이 없어
           막다른 길이 된다(09-23 확인, 영상의학과와 같은 자리). */
        to: `${go.pathology.queue()}?pick=${r.id}`,
        /* ⚠ 위 id 는 **검체 번호**다 — 「최근 본 환자」는 환자 번호로 담는다
           (lib/recent.js). 줄에 환자 번호를 같이 싣는다 */
        pid: r.patient ?? r.patient_id ?? null,
        why: "검체 접수",
      })),
    }),

    /* 초안 — 써 두고(판정 · 소견 중 하나라도) 확정 안 한 내 검체.
       ⚠ 전에는 걸러지지 않은 목록으로 가서 어느 것이 초안인지 다시 찾아야
       했다 — 「내 판독중」으로 걸러 보낸다 */
    stuck: ({ specimens }) => [
      { tag: "임시저장", text: "임시저장만 하고 확정하지 않은 내 검체",
        count: specimens.filter((r) => !r.finalized
          && (r.b_category || r.diagnosis || r.finding_note)).length,
        to: `${go.pathology.list()}?f=mine` },
      /* ⚠ 목업의 「마스크 확인」은 못 센다. AI 마스크를 봤는지 남기는 칸이
         서버에 없다 */
    ],

    done: ({ specimens }) => {
      const it = specimens.filter((r) => r.finalized && H.isToday(r.finalized_at));
      return {
        summary: `확정 ${it.length}`,
        empty: "오늘 확정한 검체가 아직 없습니다",
        items: it.map((r) => ({
          id: r.id,
          at: H.at(r.finalized_at),
          text: `${H.nameOf(r)} · ${r.specimen_no ?? "검체"} · ${text(r, "diagnosis", DIAGNOSIS, "diagnosis_label") || "진단"} 확정`,
          to: go.pathology.read(r.id),
        })),
      };
    },
  },

  /* 티켓이 여는 범위의 단위. 서버가 `scope_kind` 로 받는 넷
     (study · specimen · report · account) 중 하나여야 한다 —
     병리는 검체다. lib/files.js 참고 */
  scopeKind: "specimen",

  /* ── 1장 · 검체 접수 대기 ─────────────────────────────── */
  queue: {
    title: "검체 접수",
    listTitle: "접수 대기 검체",
    /* 네 단 껍데기가 읽는 제목들(screens/Queue.jsx) */
    detailTitle: "이 검체",
    pastTitle: "이 환자의 이력",
    /* ⚠ **서버가 주는 값이 아니다.** 상용구를 저장하는 경로가 없어 여기
       박아 뒀다. 사람마다 다르게 쓰려면 서버에 자리가 있어야 한다(8장) */
    phrases: [
      ["조직", ["침윤성 유관암 (IDC)", "관상피내암 (DCIS), 저등급"]],
      ["양성", ["섬유선종", "섬유낭종성 변화"]],
      ["검체", ["표적 병변 미포함 가능성", "검체량 부족 — 재채취 권고"]],
      ["결론", ["악성 소견 없음", "추가 면역조직화학 검사 시행"]],
    ],
    /* ⚠ 09-28 — 상용구 칸은 큐에서 안 그린다(phrasesCol 을 안 켠다) */
    searchHint: "환자 · 검체번호",
    emptyText: "접수 대기 중인 검체가 없습니다",
    takeLabel: "이 검체 접수",
    takeVerb: "접수",
    nextLabel: "다음 검체 접수",
    need: { view: "pathology.queue.view", assign: "pathology.queue.assign" },
    /* 이력은 영상 · 병리 · 불일치만 — 처방 · 결과 설명 · 리포트 · 치료 결정은
       검체를 받는 데 안 쓴다 */
    pastKeep: (e) => /촬영|판독|AI|검체|병리|불일치/.test(e.type ?? ""),
    /* 지난 검체 → 그 판독(새 탭). 영상 줄은 병리 권한 밖이라 안 건다 */
    pastLink: (e) => (e.specimen_id != null ? go.pathology.read(e.specimen_id) : null),

    row: (it) => ({
      id: it.id,
      /* 이 환자의 이력 칸이 이 번호로 부른다 */
      patientId: it.patient_id ?? it.patient ?? null,
      title: patientText(it),
      sub: [it.specimen_no, kindText(it.kind)].filter(Boolean).join(" · "),
      wait: H.waited(it.collected_at),
      chip: guideText(it.method) || null,
      chipTone: "line",
    }),

    /* 맨 위는 **유방외과가 묻는 것**(의뢰 문구) — 그다음 검체, 그다음 영상.
       ⚠ 생년월일 · 연락처 · 알레르기는 뺐다 — 검체를 받는 데 안 쓴다.
         환자 확인은 머리의 이름 · 환자번호로 한다 */
    Detail: ({ d, cfg }) => (
      <>
        <div className="work-ask-q">
          <span className="section-label">의뢰</span>
          {d.clinical_note
            ? <p className="quote">{d.clinical_note}</p>
            : <p className="muted small">의뢰 내용이 없습니다</p>}
        </div>

        <Facts items={[
          ["검체번호", d.specimen_no],
          ["종류 · 유도", [kindText(d.kind), guideText(d.method)].filter(Boolean).join(" · ") || "—"],
          ["채취", collectedText(d.collected_at) ?? "—"],
          d.site && ["부위", d.site],
          ["등록자", d.bound_by_name ?? "—"],
        ]} />

        <Correlate d={d} cfg={cfg} />

        {(d.other_specimens ?? []).length > 0 && (
          <p className="muted small">이 환자의 다른 검체 {d.other_specimens.length}건</p>
        )}
      </>
    ),
  },

  /* ── 2장 · 조직 이미지 업로드 ─────────────────────────── */
  upload: {
    title: "업로드",
    infoTitle: "검체 정보",
    dropText: "조직 이미지를 드래그하세요 (여러 장 가능)",
    accept: "image/png,image/jpeg,image/tiff",
    /* 끌어 놓는 칸 아래 한 줄. ⚠ 여러 장을 권한다 — 같은 슬라이드라도
       자른 자리에 따라 AI 계측값이 크게 달라진다 */
    hint: "WSI 전체가 아닌 잘라낸 조직 이미지(크롭)를 올립니다 — 이미지마다 AI 분석이 한 건씩 실행됩니다",
    estimate: "AI 분석은 크롭 한 장에 약 2.2초 걸립니다.",
    need: {
      view: "pathology.upload.view",
      send: "pathology.upload.send",
      run: "pathology.ai.run",
    },
    /* 품질 칸(Quality) 없음 — 병리에는 반려 · 재채취 경로가 없다 */

    /* 누구의 무엇 — **한 줄**(screens/Upload.jsx 의 .up-strip) */
    Info: ({ d }) => (
      <>
        <b>{H.nameOf(d)}</b>
        {H.who(d) && <span>{H.who(d)}</span>}
        {H.noOf(d) && <span>{H.noOf(d)}</span>}
        <Chip tone="fill">{d.specimen_no ?? "검체"}</Chip>
        {[kindText(d.kind), guideText(d.method)].filter(Boolean).length > 0
          && <span>{[kindText(d.kind), guideText(d.method)].filter(Boolean).join(" · ")}</span>}
        {d.site && <span>{d.site}</span>}
        {d.collected_at && <span>채취 {collectedText(d.collected_at)}</span>}
        {d.target_snapshot && typeof d.target_snapshot === "string"
          && <span className="up-strip-q" title={d.target_snapshot}>{d.target_snapshot}</span>}
      </>
    ),
  },

  /* ── 3장 · 판독 ───────────────────────────────────────── */
  read: {
    title: "판독",
    infoName: "검체 정보",
    unitName: "검체",
    /* ⚠ **병리는 정정 경로가 없다**(확정 사양서 §8-2). 영상은 정정
       화면이 있지만 여기는 없다 — 그 사실을 저장 줄에 적는다. 「되돌릴
       수 없다」만으로는 «나중에 고칠 수 있나»가 안 읽힌다 */
    saveHint: "확정은 한 번만 할 수 있습니다. 병리 판독은 정정할 수 없어, 확정 후 "
      + "오류가 있으면 새 검체로 다시 접수해야 합니다.",
    finalNote: "병리 판독은 정정할 수 없습니다. 오류가 있으면 새 검체로 다시 접수합니다.",
    phrases: PHRASES,

    /* 확정된 검체는 읽기 전용 — 서버도 409 SPECIMEN_ALREADY_FINALIZED 로 막는다 */
    isFinal: (d) => Boolean(d.unit?.finalized),

    /* 확정 → 다음 건. 내가 집은 · 아직 확정 안 한 검체 중 가장 먼저 채취한 것.
       ⚠ ?assigned=me&finalized=no 를 서버가 거른다(09-28 B1). 옛 서버를 위해
         여기서도 한 번 더 — 담당자가 비었거나 확정된 것은 뺀다 */
    after: async (id) => {
      const rows = await path.rows({ assigned: "me", finalized: "no",
                                     ordering: "collected_at", page_size: 50 });
      const me = getMe()?.staff_id ?? null;
      const next = rows.find((r) => String(r.specimen_id ?? r.id) !== String(id)
        && !r.finalized_at && r.assigned_to != null
        && (me == null || String(r.assigned_to) === String(me)));
      return next ? (next.specimen_id ?? next.id) : null;
    },

    /* 맨 위 띠 — 병리의에게 필요한 것만. 연락처 · 생년월일 · 알레르기는 뺐다 */
    strip: (d) => [
      [null, patientText(d.patient)],
      ["번호", d.patient.no],
      ["검체", d.unit.no],
      ["종류", label(SPECIMEN_TYPE, d.unit.specimen_type) || d.unit.kind],
      ["상태", d.unit.status_label],
    ],
    AiSummary: PathologyAiSummary,

    /* 확정된 검체 — 폼 대신 값만 */
    Final: ({ d }) => {
      const s = d.doctor ?? {};
      return (
        <>
          <Facts items={[
            ["진단", label(DIAGNOSIS, s.diagnosis) || "—"],
            ["B 분류", label(B_CATEGORY_LABEL, s.b_category) || "—"],
            s.histologic_type && ["조직형", label(HISTOLOGIC_TYPE, s.histologic_type)],
            s.nottingham_grade !== "" && s.nottingham_grade != null && ["Nottingham", label(NOTTINGHAM, s.nottingham_grade)],
            (s.er_status || s.pr_status || s.her2_status) && ["ER · PR · HER2",
              [label(RECEPTOR, s.er_status) || "—", label(RECEPTOR, s.pr_status) || "—", label(HER2, s.her2_status) || "—"].join(" · ")],
            s.ki67_percent !== "" && s.ki67_percent != null && ["Ki-67", `${s.ki67_percent}%`],
            s.stil_calibrated != null && ["sTIL (병리의)", `${s.stil_calibrated}%`],
            ["판독의", d.unit.reported_by ?? "—"],
            ["확정", d.unit.finalized_at],
          ]} />
          <p className="vfin-k">판독 소견</p>
          <p className="quote">{s.finding_note || "—"}</p>
        </>
      );
    },
    need: {
      view: "pathology.read.view",
      ai: "pathology.ai.view",
      draft: "pathology.read.draft",
      finalize: "pathology.read.finalize",
    },
    ready: (f) => Boolean(f.b_category && f.diagnosis),

    /* 09-28 추가 — Read.jsx 의 draft() 는 원래 영상의학과 모양
       (lesion_id·category)을 그대로 썼다. 병리는 그 두 칸이 없어서
       (b_category·diagnosis·stil_calibrated·finding_note 가 있는데도)
       임시저장을 눌러도 저장되지 않았다 — finding_note 만 어쩌다 실려
       나갔다. 이 훅이 있으면 Read.jsx 가 이걸로 바디를 만든다(없는
       과는 기존 모양 그대로 쓴다) */
    draftPayload: (f) => ({
      b_category: f.b_category ?? null,
      diagnosis: f.diagnosis ?? null,
      finding_note: f.finding_note ?? "",
      stil_calibrated: f.stil_calibrated === "" ? null : f.stil_calibrated ?? null,
      /* 09-28 — 빈 칸은 null(지운다). 숫자 칸은 글자로 두면 서버 검증에 걸린다 */
      histologic_type: f.histologic_type || null,
      nottingham_grade: f.nottingham_grade === "" || f.nottingham_grade == null ? null : Number(f.nottingham_grade),
      er_status: f.er_status || null,
      pr_status: f.pr_status || null,
      her2_status: f.her2_status || null,
      ki67_percent: f.ki67_percent === "" || f.ki67_percent == null ? null : Number(f.ki67_percent),
    }),

    /* 뷰어에 무엇을 얹나 — 병리는 **PNG 마스크** 한 장이다.
       조직 분할 결과를 픽셀마다 칠한 것이라 도형으로 못 그린다.
       크롭 한 장에 마스크 한 장이 짝이다 */
    stage: (d, i = 0) => {
      const c = (d.crops ?? [])[i];
      return {
        /* { url } 이면 그대로, { key } 면 티켓 받아 Go 에서 가져온다 */
        image: c?.image,
        maskImage: c?.mask,
        /* 마스크 픽셀값이 무슨 뜻인지는 서버가 같이 보낸다. 화면이
           번호를 제멋대로 해석하지 않게 그대로 넘긴다 — 한글로 바꾸는
           것은 표시용 글자뿐, 번호→뜻 대응 자체는 그대로다. */
        maskLegend: translateLegend((d.ai ?? [])[i]?.mask_legend) ?? null,
        /* 병리 조직분할 전용 색(기타=회색 반투명, 종양=빨강, 간질=파랑).
           다른 과(초음파 등)는 이 prop 을 안 넘겨 기존 색을 그대로 쓴다. */
        maskColors: PATHOLOGY_MASK_COLORS,
        w: c?.w ?? 512, h: c?.h ?? 512,     /* 크롭은 512×512 */
        alt: `크롭 ${i + 1}`,
        shapes: [],            /* 병리는 도형이 없다 — 마스크가 그림이다 */
      };
    },

    /* 왼쪽 — 영상 대조(맨 위, 펼침) · 검체 · 의뢰 문구 · 크롭.
       ⚠ 연락처 · 생년월일 · 알레르기는 뺐다(09-28) — 병리의가 쓸 일이 없다 */
    Info: ({ d, slide, onSlide }) => (
      <>
        <ImagingCorrelation d={d} />
        <Facts items={[
          ["검체번호", d.unit.no],
          ["종류", label(SPECIMEN_TYPE, d.unit.specimen_type) || d.unit.kind],
          ["유도 방식", label(GUIDANCE_ROUTE, d.unit.guidance_route) || d.unit.method],
          ["채취", d.unit.collected_at ? `${readableAt(d.unit.collected_at)} (${ago(d.unit.collected_at)})` : null],
          ["등록자", d.unit.bound_by_name],
          d.unit.site && ["병변 위치", d.unit.site],
        ]} />
        {d.unit.clinical_note && (
          <Fold title="의뢰 내용">
            <p className="quote">{d.unit.clinical_note}</p>
          </Fold>
        )}
        <Fold title={`업로드한 크롭 ${(d.crops ?? []).length}장`}>
          <ul className="slides">
            {(d.crops ?? []).map((c, i) => (
              <li key={c.id} className={slide === i ? "on" : undefined}>
                <button onClick={() => onSlide?.(i)}>
                  크롭 {i + 1} · {c.name}
                  {!c.mask && <small> · 마스크 없음</small>}
                </button>
              </li>
            ))}
          </ul>
        </Fold>
      </>
    ),

    Ai: PathologyAi,

    Doctor: ({ f, set, phrases, insert }) => (
      <>
        <label className="field">
          <span>악성 / 양성 여부</span>
          <select value={f.diagnosis ?? ""} onChange={(e) => set("diagnosis", e.target.value)}>
            <option value="">선택하세요</option>
            {Object.entries(DIAGNOSIS).map(([v, t]) => (
              <option key={v} value={v}>{t}</option>
            ))}
          </select>
        </label>

        {/* ⚠ BI-RADS 가 아니다. BI-RADS 는 영상 체계이고 병리는 B 분류다 */}
        <label className="field">
          <span>등급 (B 분류)</span>
          <select value={f.b_category ?? ""} onChange={(e) => set("b_category", e.target.value)}>
            <option value="">선택하세요</option>
            {B_CATEGORY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>

        {/* 09-28 — 조직형 · 등급 · 수용체 · Ki-67. 전부 선택이다(양성이면 비워 둔다).
            값은 서버가 정한 코드(codes.js) — 빈 칸은 null 로 나가 지운다 */}
        <label className="field">
          <span>조직형</span>
          <select value={f.histologic_type ?? ""} onChange={(e) => set("histologic_type", e.target.value)}>
            <option value="">—</option>
            {Object.entries(HISTOLOGIC_TYPE).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select>
        </label>
        <div className="field-row">
          <label className="field">
            <span>Nottingham</span>
            <select value={f.nottingham_grade ?? ""} onChange={(e) => set("nottingham_grade", e.target.value)}>
              <option value="">—</option>
              {Object.entries(NOTTINGHAM).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Ki-67 (%)</span>
            <input type="number" min="0" max="100" step="0.1" value={f.ki67_percent ?? ""}
                   onChange={(e) => set("ki67_percent", e.target.value)} />
          </label>
        </div>
        <div className="field-row three">
          {[["er_status", "ER", RECEPTOR], ["pr_status", "PR", RECEPTOR], ["her2_status", "HER2", HER2]].map(([k, name, table]) => (
            <label className="field" key={k}>
              <span>{name}</span>
              <select value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)}>
                <option value="">—</option>
                {Object.entries(table).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </label>
          ))}
        </div>

        {/* 09-28 결정 — sTIL(임상 수치)은 병리의가 검체 단위로 직접
           입력한다. AI 계측값(PathologyAi.jsx)과는 다른 값이고 자동
           계산도 안 한다 — 저/중/고 같은 등급도 여기서 안 매긴다. */}
        <label className="field">
          <span>sTIL (%) — 병리의 입력</span>
          <input type="number" min="0" max="100" step="0.1"
                 value={f.stil_calibrated ?? ""}
                 placeholder="0~100"
                 onChange={(e) => set("stil_calibrated", e.target.value)} />
          <span className="muted small">
            {f.stil_calibrated === "" || f.stil_calibrated == null
              ? "병리의 입력 대기"
              : `sTIL ${f.stil_calibrated}% · 병리의 입력`}
          </span>
        </label>

        <label className="field">
          <span>판독 소견</span>
          <textarea className="lg" rows={7} value={f.finding_note ?? ""}
                    placeholder="소견"
                    onChange={(e) => set("finding_note", e.target.value)} />
        </label>
        {/* 상용구 — ⚠ label 밖(label 안 단추는 그 label 의 대상이 된다) */}
        <Phrases groups={phrases} onPick={insert} />
      </>
    ),
  },

  /* ── 4장 · 전체 환자 목록 ─────────────────────────────── */
  list: {
    title: "환자 목록",
    /* 영상의학과 목록과 같은 목록 1 : 상세 2 구조다. 병리는 한 검체의
       조직 사진만 보므로 모달리티 탭 없이 첫 조직 사진을 고정으로 둔다. */
    splitSide: "third",
    hideDashboard: true,
    listTitle: "검체 목록",
    searchHint: "환자 · 검체번호",
    /* 검색이 훑는 칸. **검색창에 적어 둔 것과 같아야 한다** —
       「환자 · 검체번호」라고 써 놓고 다른 데까지 걸리면 왜 걸렸는지
       모른다 */
    search: ["patient_name", "specimen_no"],
    need: { view: "pathology.list.view" },
    /* 전체 · 내 판독중 · 미확정 · 확정 · 불일치 — 주소 ?f= (홈이 여기로 보낸다) */
    filters: LIST_FILTERS,
    /* 불일치 칩이 맞춰 볼 열린 불일치 — 한 번 받는다. 권한이 없으면 빈 것 */
    context: () => api.openDiscordances().catch(() => [])
      .then((rows) => ({ disc: discSets(H.rows(rows)) })),
    detailTitle: (d) => [H.nameOf(d), d.specimen_no].filter(Boolean).join(" · "),

    /* ⚠ report__last_viewed_at · finalized_at 정렬은 09-28 서버부터 받는다
       (빈 값은 뒤로) */
    sorts: [
      { key: "patient__name", label: "이름" },
      { key: "collected_at", label: "채취 순" },
      { key: "accessioned_at", label: "접수 순" },
      { key: "finalized_at", label: "확정 순" },
      { key: "report__last_viewed_at", label: "유방외과 열람" },
    ],

    /* 09-28 — 다섯 칸이 440px 에 안 들어 이름이 꺾이고 끝 칸이 잘렸다.
       검체번호 · 채취일을 한 칸(검체)으로 묶고, 나이 · 성별 · 환자번호는
       이름 밑 둘째 줄로 내린다(lib/ListCells) */
    cols: [
      { key: "patient", label: "환자", cls: "c-grow" },
      { key: "specimen", label: "검체", cls: "c-fit" },
      { key: "status", label: "진행 상황", cls: "c-fit" },
      { key: "viewed", label: "유방외과", cls: "c-fit" },
    ],

    /* 진행상황 — ⚠ accession_status 로는 「판독 완료」를 못 말한다(서버 enum
       이 bound · accessioned 까지뿐). 누가 집었는지 · 확정했는지로 센다:
       미접수 → 판독중 → 확정 (api.js 의 read_state) */
    row: (r) => ({
      id: r.id,
      patient: <Two strong main={H.nameOf(r)} title={H.nameOf(r)}
                    sub={[H.who(r), H.noOf(r)].filter(Boolean).join(" · ")} />,
      /* 「09-28 08:20」 채취 — 목록 칸이 좁아 해를 뺀다 */
      specimen: <Two main={r.specimen_no || "—"} sub={shortAt(r.collected_at) ?? "—"} />,
      status: <Chip tone={STATE_TONE[r.read_state] ?? "line"}>
        {STATE[r.read_state] ?? text(r, "accession_status", ACCESSION_STATUS, "status_label")}
      </Chip>,
      /* 「확인」이 아니라 「열람」이다 — 자동 기록이라 의도적 확인이 아니다 */
      viewed: <Seen at={r.viewed_at} />,
    }),

    Detail: ({ d, cfg }) => <PathologyListDetail d={d} cfg={cfg} />,
  },

  /* 5장(판독 정정) 없음 — 확정 사양서 §8-2: 병리는 정정 경로를 두지
     않는다. 확정 후 오류는 새 검체로 처리한다. List.jsx 가 cfg.amend
     존재 여부로 버튼을 감추고, nav.js 에도 이 과의 amend 라우트가 없다. */
};

/* 병리과 목록의 오른쪽 상세. 영상의학과 목록과 같은 «조회 전용 뷰어 ·
 * 상세 정보» 두 칸이지만, 병리는 검체의 첫 조직 사진만 고정으로 보인다.
 * 사진을 넘기거나 판독 도구를 여는 기능은 목록에 두지 않는다. */
function PathologyListDetail({ d, cfg }) {
  const read = useApi(() => cfg.api.read(d.id), [d.id]);

  return (
    <div className="list-detail-cols">
      <div className="list-detail-viewer">
        <Body loading={read.loading} error={read.error} onRetry={read.reload}>
          {read.data && <FixedTissueViewer read={read.data} cfg={cfg} />}
        </Body>
      </div>
      <div className="list-detail-info">
        <Facts items={[
          ["환자", patientText(d)],
          ["환자번호", H.noOf(d) || "—"],
          ["검체번호", d.specimen_no],
          ["종류 · 유도", [kindText(d.kind), guideText(d.method)].filter(Boolean).join(" · ") || "—"],
          ["채취", collectedText(d.collected_at) ?? "—"],
          ["담당 병리의", d.reported_by ?? d.assigned_to_name ?? "—"],
          ["진행 상황", STATE[d.read_state] ?? text(d, "accession_status", ACCESSION_STATUS, "status_label")],
          ["유방외과 열람", d.viewed_at ?? "미열람"],
        ]} />
        <Fold title="판독 결과" open={Boolean(d.finalized)}>
          {d.finalized ? (
            <>
              <Facts items={[
                ["진단", text(d, "diagnosis", DIAGNOSIS, "diagnosis_label")],
                ["등급", label(B_CATEGORY_LABEL, d.b_category)],
              ]} />
              <p className="quote">{d.finding_note}</p>
            </>
          ) : <p className="muted">아직 확정된 판독이 없습니다.</p>}
        </Fold>
      </div>
    </div>
  );
}

function FixedTissueViewer({ read, cfg }) {
  const crop = read.crops?.[0] ?? null;
  const original = useFile(crop?.image, cfg.api.ticket, { kind: cfg.scopeKind, id: read.unit.id });
  const mask = useFile(crop?.mask, cfg.api.ticket, { kind: cfg.scopeKind, id: read.unit.id });
  const legend = translateLegend((read.ai ?? [])[0]?.mask_legend);

  return (
    <div className="list-viewer pathology-fixed-viewer">
      <Stage src={original.src} w={crop?.w} h={crop?.h}
        alt={crop?.name ?? "조직 사진"} loading={original.loading} loadError={original.error}
        mask={mask.src} maskColors={PATHOLOGY_MASK_COLORS} mode="review" />
      {mask.src && <MaskKeys legend={legend} colors={PATHOLOGY_MASK_COLORS} />}
    </div>
  );
}


/* ── 판독 화면 왼쪽 맨 위 · 영상 대조 (09-28) ─────────────────────
 * 이 검체가 겨냥한 병변(Specimen.lesion → GET /lesions/{id}/)과 그 검사의
 * 지금 유효한 영상 판정(GET /assessments?study=). 병리 결과를 영상과
 * 맞춰 보는 것이 판독의 첫 일이라 **펼친 채** 맨 위에 둔다.
 * ⚠ 병리 권한으로 못 읽으면(403 · 404) 바인딩 때 찍어 둔 target_snapshot
 *   한 줄로 버틴다. 판정이 없으면 「영상 최종 판정 없음」이라고 **말한다** —
 *   빈칸은 「양성」으로 읽힌다 */
function ImagingCorrelation({ d }) {
  const lid = d.unit?.lesion ?? null;
  const q = useApi(async () => {
    if (lid == null) return null;
    const lesion = await path.lesion(lid);
    const sid = lesion?.study ?? lesion?.study_id ?? null;
    const rows = sid != null ? await path.assessments(sid).catch(() => []) : [];
    return { lesion, final: currentAssessment(rows) };
  }, [lid]);
  const L = q.data?.lesion ?? null;
  const A = q.data?.final ?? null;
  const snap = d.unit?.target_snapshot;
  const rs = d.radiology_summary;

  return (
    <section className="corr" aria-label="영상 대조">
      <h3>영상 대조</h3>
      {lid != null && q.loading ? <p className="muted small">영상 판정을 불러오는 중…</p> : (
        <>
          {L ? (
            <Facts items={[
              ["병변", L.label ?? `#${L.lesion_id ?? lid}`],
              ["모달리티", label(MODALITY, asModality(L.modality))],
              ["위치", lesionWhere(L)],
              ["크기", lesionSize(L)],
            ]} />
          ) : snap ? <p className="corr-snap">{snap}</p> : null}

          {A ? (
            <div className="corr-final">
              <b>영상 최종 · BI-RADS {label(BIRADS_LABEL, A.category) || "—"}</b>
              {A.finding_note && <p className="quote">{A.finding_note}</p>}
            </div>
          ) : (
            <p className="corr-none">
              {q.error ? "영상 판정을 불러오지 못했습니다" : "영상 최종 판정 없음"}
            </p>
          )}
          {!A && rs && (
            <p className="muted small">영상 요약 — BI-RADS {rs.birads ?? "—"}{rs.note ? ` · ${rs.note}` : ""}</p>
          )}
        </>
      )}
      <p className="muted small">영상 판정(BI-RADS)과 병리 등급(B 분류)은 다른 체계입니다.</p>
    </section>
  );
}

/* 병변 위치 — Lesion 에 좌우 칸이 없다. AI 결과에서 옮겨 온 detail 을 본다 */
function lesionWhere(L) {
  const dt = L.detail ?? {};
  const lat = { left: "좌측", right: "우측", l: "좌측", r: "우측" }[
    String(L.laterality ?? dt.laterality ?? dt.image?.laterality ?? "").toLowerCase()] ?? null;
  const at = dt.quadrant ?? dt.location ?? dt.clock ?? null;
  return [lat, at].filter(Boolean).join(" ") || null;
}

/* 크기 — 판독의 측정값이 AI 값보다 먼저. 초음파는 mm 가 없어 px 로만 */
function lesionSize(L) {
  const mm = L.measured_size_mm ?? L.ai_size_mm;
  if (mm != null && mm !== "") return `${Number(mm).toFixed(1)} mm${L.measured_size_mm != null ? "" : " (AI)"}`;
  const px = L.measured_size_px ?? L.ai_size_px;
  return px != null && px !== "" ? `${Number(px).toFixed(0)} px (AI)` : null;
}
