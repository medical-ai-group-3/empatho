/* 코드 ↔ 한글 — 서버 값이 화면 글자가 되는 자리는 여기 하나다
 * ════════════════════════════════════════════════════════════════
 *
 * **여기 적힌 코드는 지어낸 것이 아니다.** empatho-app 의
 * `services/django/core/models.py` 맨 위 enum 목록을 그대로 옮겼다
 * (2026-09-17 확인). 서버가 DB CHECK 으로 강제하는 값들이라, 여기가
 * 어긋나면 화면이 «모르는 코드»를 날것으로 뱉는다.
 *
 * ── 왜 한 곳에 모았나 ────────────────────────────────────────
 *
 * 전에는 같은 표가 화면마다 따로 있었고 **서로 달랐다.**
 *
 *   modality  radiology.jsx 는 `ultrasound`, reception 두 곳은 `us`.
 *             서버는 `us` 다 — 영상 판독 화면이 초음파를 못 알아봤다
 *   modality  같은 코드에 「맘모」와 「유방촬영」 두 이름이 붙어 있었다
 *   sex       세 곳에 따로 있었고 한 곳만 F · M 을 알았다
 *
 * 표가 여럿이면 어느 것이 맞는지 아무도 모른다. 하나로 두고, 틀리면
 * 한 곳만 고친다.
 *
 * ── 서버가 라벨을 주기 시작하면 ──────────────────────────────
 *
 * ⚠ **지금 서버에는 `status_label` 같은 한글 칸이 없다.** 모델을 다
 *   훑어도 `*_label` 은 `specimen_label`(검체 식별자) 하나뿐이고 그건
 *   상태가 아니다. 목업이 지어낸 칸에 화면 열두 곳이 기대고 있었다 —
 *   실서버에 붙는 날 그 자리가 전부 빈칸이 된다.
 *
 *   그래서 `text()` 로 읽는다. **서버가 라벨을 주면 그것을 쓰고, 안
 *   주면 코드로 만든다.** 둘 중 어느 쪽이 와도 화면은 안 바뀐다 —
 *   서버가 준비되는 순서를 기다릴 필요가 없다.
 *
 *   서버가 나중에 코드표 자체를 내려주게 되면 `adopt()` 한 번으로
 *   덮는다. 화면 코드는 그대로다.
 */

/* ── 모달리티 ──────────────────────────────────────────────────
   서버 enum: ["mammo", "us", "mri"]

   ⚠ `ultrasound` 는 **별칭으로만** 둔다. 우리 목업 일부와 옛 화면이
     그 철자를 쓰고 있어서 받아는 주되, 내보낼 때는 `us` 로 맞춘다.
     두 철자를 나란히 «정답»으로 두면 비교문이 또 갈린다. */
export const MODALITY = {
  mammo: "유방촬영",
  us: "초음파",
  mri: "MRI",
};

const MODALITY_ALIAS = { ultrasound: "us", ultra: "us", mammography: "mammo" };

/** 어떤 철자로 오든 서버 코드로 맞춘다. 비교는 늘 이 결과로 한다. */
export const modality = (v) => MODALITY_ALIAS[v] ?? v ?? null;

/* ── 성별 ──────────────────────────────────────────────────────
   ⚠ 서버 칸이 `CharField(max_length=20)` 이고 **CHECK 이 없다.**
     무엇이 올지 모른다는 뜻이라 아는 철자를 넉넉히 받아 둔다.
     이미 한글이 오면 그대로 쓴다 (아래 label 의 마지막 갈래). */
export const SEX = {
  female: "여", male: "남",
  F: "여", M: "남",
  f: "여", m: "남",
};

/* ── 진행 상태 ─────────────────────────────────────────────────
   서버 enum 세 벌이 화면 하나에서 섞여 보인다. 코드는 서로 다르므로
   표도 따로 둔다 — 합치면 `pending` 이 어느 쪽 것인지 모른다. */

/** 판독 상태. 서버 enum: ["pending", "draft", "finalized"] */
export const READ_STATUS = {
  pending: "판독 대기",
  draft: "작성 중",
  finalized: "판독 완료",
};

/** 검체 접수 상태. 서버 enum: ["unbound", "bound", "accessioned"] */
export const ACCESSION_STATUS = {
  unbound: "등록 전",
  bound: "접수 대기",
  accessioned: "접수 완료",
};

/** 오더 상태. 서버 enum 일곱 */
export const ORDER_STATUS = {
  requested: "신청 · 확인 중",
  scheduled: "일정 확정",
  ordered: "검사 확정",
  accepted: "접수됨",
  in_progress: "진행 중",
  completed: "완료",
  cancelled: "취소",
};

/** AI 실행 상태. 서버 enum: ["queued", "running", "done", "failed"] */
export const RUN_STATUS = {
  queued: "대기 중",
  running: "분석 중",
  done: "완료",
  failed: "실패",
};

/** 추적 상태. 서버 enum: ["open","resolved","escalated","declined","overdue"]
 *
 *  ⚠ `candidate` 는 서버가 **낼 수 없는 값이다** (2026-09-17 확인).
 *     followup.status 에 DB CHECK(followup_status_ck)이 걸려 있어 저 다섯
 *     말고는 저장 자체가 안 된다.
 *
 *     간호과 화면(Followups.jsx)은 f.status 를 displayStatus() 로 한 번
 *     거치는데, 그 함수가 내는 값은 "overdue" 아니면 f.status 그대로다 —
 *     candidate 를 만들어 내지 않는다. 즉 **지금 경로로는 이 라벨이 화면에
 *     뜰 수 없다.** 목업(mock/hospital.json)에만 그 값이 있어서 목업에서는
 *     보이고, 실서버에서는 「추적 대상」 필터가 늘 0건이 된다.
 *
 *     지울지 살릴지는 제품 결정이다 — 서버 enum 에 candidate 를 더하든지,
 *     화면이 「아직 회차가 없는 건」을 파생시키든지 둘 중 하나여야 한다.
 *     정해지기 전까지는 라벨을 남겨 둔다. 지우면 그 논의가 사라진다. */
export const FOLLOWUP_STATUS = {
  candidate: "추적 대상",
  open: "추적 중",
  overdue: "기한 초과",
  resolved: "종결",
  declined: "거절 · 상급전원",
  escalated: "거절 · 상급전원",
};

/* ── 판정 · 소견 ───────────────────────────────────────────────
   <select> 에 그대로 넣는 자리가 있어 **순서가 있는 목록**으로 둔다.
   순서가 곧 등급 순서라 객체로 두면 그 뜻이 사라진다. */

/** 서버 enum: ["b1" … "b5"] */
export const B_CATEGORY = [
  { value: "b1", label: "B1 — 정상 조직 또는 부적합 검체" },
  { value: "b2", label: "B2 — 양성" },
  { value: "b3", label: "B3 — 악성 가능성이 불확실한 병변" },
  { value: "b4", label: "B4 — 악성 의심" },
  { value: "b5", label: "B5 — 악성" },
];

/** 서버 enum: ["0","1","2","3","4","4a","4b","4c","5","6"]
 *  ⚠ 모달리티마다 고를 수 있는 값이 다르다 — ACR BI-RADS MRI 는 4 를
 *    세분하지 않는다. 맘모 · 초음파는 BIRADS(4a · 4b · 4c), MRI 는
 *    BIRADS_MRI(4). 선택지는 biradsFor(modality)로 고른다. 서버도 같은
 *    규칙으로 막는다(core/services/birads.py) */
export const BIRADS = [
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

/** MRI 판정 등급 — 4 에 세분이 없다 */
export const BIRADS_MRI = [
  { value: "0", label: "0 — 추가 검사 필요" },
  { value: "1", label: "1 — 음성" },
  { value: "2", label: "2 — 양성" },
  { value: "3", label: "3 — 양성 가능성 높음" },
  { value: "4", label: "4 — 악성 의심" },
  { value: "5", label: "5 — 악성 강력 시사" },
  { value: "6", label: "6 — 조직학적으로 확인된 악성" },
];

/** 이 검사의 모달리티에 맞는 BI-RADS 선택지 */
export const biradsFor = (m) => (modality(m) === "mri" ? BIRADS_MRI : BIRADS);

/** 서버 enum: ["benign", "malignant"] */
export const DIAGNOSIS = { benign: "양성 (benign)", malignant: "악성 (malignant)" };

/** 판독 단계. 서버 enum: ["draft", "final"] — READ_STATUS(검사의 상태)와 다르다.
 *  이쪽은 Assessment 한 행의 단계다 */
export const READ_STAGE = { draft: "임시저장", final: "확정" };

/* ── 치료 결정 · 리포트 ────────────────────────────────────────
   진료 이력의 「치료 결정」「리포트」 줄이 코드로 온다 */

/** 서버 enum: ["surgery", "biopsy", "imaging", "rebiopsy"] */
export const DECISION_TYPE = {
  surgery: "수술", biopsy: "조직검사", imaging: "추가 영상", rebiopsy: "재생검",
};
/** 서버 enum: ["yes", "no", "defer"] — 종류(위)와 붙여 「수술 · 시행」으로 읽는다 */
export const DECISION_VALUE = { yes: "시행", no: "하지 않음", defer: "보류" };
/* 판정 불일치 — 처분(DISPOSITION_TYPE 셋, models.py)과 대조 결과(flag_status).
   ⚠ flag_status 에는 "open" 이 없다. 열림 · 종결은 closed_at 으로 가른다 */
export const DISPOSITION_TYPE = { rebiopsy: "재조직검사", excision: "수술적 절제", no_action: "불일치 아님 · 종결" };
export const FLAG_STATUS = { pass: "일치", sev1: "심각도 1", sev2: "심각도 2", review: "검토 필요", unbindable: "대조 불가" };
/** 서버 enum: ["stage", "final"] */
export const REPORT_TYPE = { stage: "검사별 판독문", final: "종합 리포트" };
/** 서버 enum: ["clinician", "patient"] */
export const AUDIENCE = { clinician: "의료진용", patient: "환자용" };

/** 서버 enum: ["low", "mid", "high"] */
export const STIL_LEVEL = { low: "낮음", mid: "중등도", high: "높음" };

/** 서버 enum: ["mass", "calcification"] */
export const LESION_KIND = { mass: "종괴", calcification: "미세석회" };

/** 맘모 서술어 5축 — 모델 출력의 축 이름이다 (DB enum 이 아니다) */
export const DESCRIPTOR_AXIS = {
  shape: "모양", margin: "경계", calctype: "석회 종류",
  calcdist: "석회 분포", finding: "소견",
};

/** 검사 목적. 서버 enum: ["screening", "diagnostic"] (ExamOrder.exam_purpose).
 *  글자는 유방외과 오더 창(ExamOrderModal)의 선택지와 같게 둔다 */
export const EXAM_PURPOSE = { screening: "정기 검진", diagnostic: "이상 소견 확인" };

/* ── 판독 폼 보조 칸 (09-28) ─────────────────────────────────── */

/** 유방 밀도 범주. 서버 enum: ["a","b","c","d"] (Study.density_category) */
export const DENSITY_CATEGORY = [
  { value: "a", label: "a — 거의 지방" },
  { value: "b", label: "b — 산재성 섬유선 조직" },
  { value: "c", label: "c — 불균질 치밀" },
  { value: "d", label: "d — 극도 치밀" },
];

/** 권고. 서버가 정한 값(Assessment.recommendation · 09-28 B1) */
export const RECOMMENDATION = {
  routine_screening: "정기 검진",
  short_interval_followup: "단기 추적(6개월)",
  additional_imaging: "추가 영상",
  biopsy: "조직검사",
  surgical_excision: "수술적 절제",
};

/** 검체 종류 · 유도 방식. 서버 enum 그대로 (Specimen.specimen_type · guidance_route) */
export const SPECIMEN_TYPE = { core_needle: "중심 침 생검", surgical: "수술적 생검" };
export const GUIDANCE_ROUTE = {
  ultrasound: "초음파 유도", stereotactic: "정위 유도", mri: "MRI 유도", localization: "촉지 유도",
};

/** 조직형. 서버가 정한 값(Specimen.histologic_type · 09-28 B1) */
export const HISTOLOGIC_TYPE = {
  idc_nst: "침윤성 유관암 (IDC, NST)",
  ilc: "침윤성 소엽암 (ILC)",
  dcis: "관상피내암 (DCIS)",
  lcis: "소엽상피내암 (LCIS)",
  mucinous: "점액암",
  tubular: "관상암",
  papillary: "유두상암",
  metaplastic: "화생암",
  fibroadenoma: "섬유선종",
  phyllodes: "엽상종양",
  fibrocystic: "섬유낭종성 변화",
  other: "기타",
};

/** ER · PR. 서버 값: positive · negative · low_positive */
export const RECEPTOR = { positive: "양성", low_positive: "약양성 (1–10%)", negative: "음성" };
/** HER2. 서버 값: negative · low · equivocal · positive */
export const HER2 = { negative: "음성 (0)", low: "저발현 (1+ · 2+/ISH−)", equivocal: "경계 (2+)", positive: "양성 (3+ · ISH+)" };
/** Nottingham 등급 1~3 */
export const NOTTINGHAM = { 1: "1 — 고분화", 2: "2 — 중분화", 3: "3 — 저분화" };

/* 리포트를 낸 소켓 → 어느 과가 낸 판독인가. 서버 models.py 의
   REPORT_SOCKET_ID 주석 그대로다 — 1 병리 · 3 MRI · 4b 맘모 · 5 초음파 ·
   7 종합. 유방외과 화면은 이 글자에 「영상」·「병리」가 들어 있는지로
   두 칸을 가른다(Review.jsx 의 of("영상") / of("병리")).
   ⚠ Report 에는 title · modality 칸이 없다 — 판독문 이름은 이것뿐이다 */
export const REPORT_DEPT = {
  "1": "병리", "3": "영상 · MRI", "4b": "영상 · 유방촬영", "5": "영상 · 초음파",
};

/* 목록 표로 만들어 쓰는 자리 — {value,label} 을 코드→글자로 */
const flatten = (rows) =>
  Object.fromEntries(rows.map((r) => [r.value, r.label]));

export const B_CATEGORY_LABEL = flatten(B_CATEGORY);
/* 글자 표는 두 목록을 합친다 — 「4」도 풀려야 한다 */
export const BIRADS_LABEL = flatten([...BIRADS, ...BIRADS_MRI]);

/* ── 진료 이력 한 줄 ───────────────────────────────────────────
 * PatientTimelineView(core/views/surgery.py)의 줄 아래 글. 유방외과 ·
 * 영상 · 공용 환자 화면이 같이 쓴다.
 *
 * ⚠ 「촬영」은 `detail` 에 모달리티 **코드**(mammo · us · mri)를,
 *   「판독」은 BI-RADS 코드(4b)만 싣는다. 그대로 찍으면 「us」「4b」가
 *   화면에 뜬다. 둘 다 `modality` 를 같이 주므로 그것으로 푼다.
 * ⚠ 판독은 초안도 「판독」으로 온다 — 확정으로 읽히지 않게 단계를 붙인다 */
/* 이미 「BI-RADS …」로 온 글(목업 · 옛 서버)은 두 번 붙이지 않는다 */
const birads = (v) => (v == null || v === "" ? null
  : /^BI-RADS/i.test(String(v)) ? String(v) : `BI-RADS ${v}`);

export function eventDetail(e) {
  const mod = label(MODALITY, modality(e?.modality ?? (e?.type === "촬영" ? e?.detail : null)));
  const parts = e?.type === "촬영"
    ? [mod || e.detail]
    : e?.type === "판독"
      ? [mod, birads(e.detail),
        e.read_stage === "draft" ? label(READ_STAGE, e.read_stage) : null]
      : e?.type === "치료 결정"
        ? [[label(DECISION_TYPE, e.decision_type), label(DECISION_VALUE, e.decision_value)]
          .filter(Boolean).join(" · "), e.detail]
        : e?.type === "리포트"
          ? [label(REPORT_TYPE, e.report_type), label(AUDIENCE, e.audience), e.detail]
          : [e?.detail];
  const out = [...new Set(parts.filter(Boolean).map(String))].join(" · ");
  return out || null;
}

/* ── 상태 색 ───────────────────────────────────────────────────
 *
 * ⚠ **코드로 건다.** 전에는 한글 라벨을 열쇠로 썼다 —
 *     STATUS_TONE["판독 대기"]
 *   서버가 글자를 한 자만 다듬어도(「판독대기」) 조용히 안 걸리고,
 *   애초에 서버가 그 한글을 안 보낸다.
 *
 * 색을 새로 만들지 않는다는 판의 규칙대로 셋뿐이다 —
 *   fill 지금 하는 중 · line 끝남 · dot 기계가 도는 중 (tokens.css) */
export const TONE = {
  read: { pending: "line", draft: "fill", finalized: "dot" },
  accession: { unbound: "line", bound: "line", accessioned: "dot" },
  run: { queued: "dot", running: "dot", done: "line", failed: "fill" },
  order: {
    requested: "line", scheduled: "line", ordered: "fill",
    accepted: "fill", in_progress: "fill", completed: "dot", cancelled: "line",
  },
  followup: {
    candidate: "line", open: "dot", overdue: "fill",
    resolved: "line", declined: "line", escalated: "line",
  },
};

/* ── 읽는 법 ─────────────────────────────────────────────────── */

/** 코드 하나를 한글로.
 *
 * 모르는 코드는 **감추지 않고 그대로 낸다.** 빈칸으로 두면 화면에서
 * 「값이 없다」로 읽히는데, 실제로는 「우리가 모르는 값이 왔다」다.
 * 둘은 고치는 방법이 다르다.
 */
export function label(table, code) {
  if (code == null || code === "") return "";
  return table[code] ?? String(code);
}

/** 서버 라벨이 있으면 그것을, 없으면 코드로 만든 라벨을.
 *
 *   text(row, "status", READ_STATUS)
 *     → row.status_label 이 있으면 그것
 *     → 없으면 label(READ_STATUS, row.status)
 *
 * **이 함수가 스탠바이의 핵심이다.** 서버가 라벨 칸을 붙이든 안 붙이든
 * 화면은 그대로 돈다 — 붙는 날 코드를 고칠 일이 없다.
 */
export function text(row, base, table, labelKey) {
  /* ⚠ 서버(와 목업)가 쓰는 라벨 칸 이름이 코드 칸 이름과 짝이 안 맞는다 —
     코드는 `read_status` 인데 라벨은 `status_label` 이다. 그래서 라벨 칸
     이름을 넷째 인자로 따로 받는다. 짝을 짐작하면 조용히 빈칸이 된다 */
  const given = row?.[labelKey ?? `${base}_label`];
  if (given) return given;
  return label(table, row?.[base]);
}

/** 상태 칩 색. 코드가 없거나 모르면 외곽선으로 — 튀지 않는 쪽이 기본이다 */
export function tone(kind, code) {
  return TONE[kind]?.[code] ?? "line";
}

/* ── 서버가 코드표를 내려주면 ──────────────────────────────────
 *
 * 로그인 응답이나 `/codes` 같은 자리에서 표를 받게 되면 여기로 넘긴다.
 * 위 표들을 **덮어쓰지 않고 위에 얹는다** — 서버가 일부만 보내도
 * 나머지가 살아 있어야 화면이 안 빈다.
 *
 *   adopt({ modality: { us: "초음파(US)" }, read_status: {…} })
 *
 * 부르는 곳이 아직 없다. 생기면 main.jsx 의 부팅 자리에서 한 번 부른다.
 */
const TABLES = {
  modality: MODALITY,
  sex: SEX,
  read_status: READ_STATUS,
  accession_status: ACCESSION_STATUS,
  order_status: ORDER_STATUS,
  run_status: RUN_STATUS,
  followup_status: FOLLOWUP_STATUS,
  diagnosis: DIAGNOSIS,
  stil_level: STIL_LEVEL,
  lesion_kind: LESION_KIND,
  read_stage: READ_STAGE,
  decision_type: DECISION_TYPE,
  decision_value: DECISION_VALUE,
  report_type: REPORT_TYPE,
  audience: AUDIENCE,
  specimen_type: SPECIMEN_TYPE,
  guidance_route: GUIDANCE_ROUTE,
  recommendation: RECOMMENDATION,
  histologic_type: HISTOLOGIC_TYPE,
};

export function adopt(payload = {}) {
  for (const [name, rows] of Object.entries(payload)) {
    const table = TABLES[name];
    if (!table || !rows || typeof rows !== "object") continue;
    Object.assign(table, rows);
  }
}
