/* 화면 표 — **이 파일이 콘솔의 중심이다.**
 *
 * 부서와 화면이 여기 한 곳에 적혀 있고, 상단 메뉴 · 라우팅 · 빵부스러기 ·
 * 쪽 머리가 전부 이 표에서 만들어진다. 화면을 더하려면 **줄 하나를 더하면
 * 된다** — 라우팅과 메뉴를 따로 손볼 자리가 없다.
 *
 * 화면 목록을 코드 여러 곳에 흩어 두면 새 화면을 더할 때마다 세 군데를
 * 고쳐야 하고, 한 곳을 잊으면 메뉴에는 있는데 안 열리는 화면이 생긴다.
 *
 * ── 각 줄이 갖는 것 ───────────────────────────────────────────
 *   key    주소 조각.  /console/pathology/read 의 'read'
 *   menu   상단 메뉴에 찍히는 **짧은** 이름
 *   title  쪽 머리의 큰 제목
 *   badge  제목 옆 배지. 지금 상태를 한 마디로
 *   sub    제목 아래 한 줄 설명
 *   crumb  빵부스러기. 메뉴로 못 가는 화면은 어디서 왔는지 적는다
 *   kind   어떤 뼈대로 그릴지 (아래 KINDS)
 *   page   설계서 쪽 번호 — 원본을 찾아볼 때 쓴다
 *
 * ⚠ badge 와 sub 는 **껍데기용 견본**이다. 화면이 실제로 만들어지면
 *   자료에서 온 값으로 바뀐다(판독 대기 4 · AI 분석 완료 같은 것).
 */

/* 뼈대 종류. 화면 스물한 개가 이 아홉 가지 안에 들어간다 —
   그래서 공통 부품을 만들 값어치가 있다. */
export const KINDS = {
  dash:   "대시보드",
  queue:  "대기열 + 오른쪽 상세",
  list:   "표 목록 + 오른쪽 상세",
  cal:    "달력 + 목록",
  form:   "서식",
  upload: "업로드",
  read:   "판독 — 뷰어 + AI · 의사 패널",
  amend:  "판독 정정 — 기존 대 정정",
  report: "종합 리포트",
};

export const HOSPITAL = "미래 대학병원";
export const PRODUCT  = "EMPATHO";

export const DEPTS = [
  {
    key: "signin", name: "로그인", en: "SIGN IN", bare: true,
    who: null,
    note: "전 직원 · 관리자 승인 후 이용",
    screens: [
      { key: "",       menu: "로그인",   title: "로그인",
        sub: "직원 계정으로 들어갑니다.", kind: "form", page: 2 },
      { key: "signup", menu: "회원가입", title: "직원 회원가입",
        badge: "승인 필요",
        sub: "가입 신청 후 관리자 승인이 있어야 이용할 수 있습니다.",
        kind: "form", page: 3 },
    ],
  },
  {
    key: "reception", name: "원무과", en: "RECEPTION",
    who: { name: "김하늘", role: "선생님" },
    note: "접수 · 예약 · 환자 관리",
    screens: [
      { key: "",         menu: "대시보드",   title: "방문 환자 모니터링",
        badge: "대기 3", sub: "오늘 접수와 방문 현황을 한눈에 봅니다.",
        kind: "dash", page: "4, 6" },
      { key: "calendar", menu: "예약 캘린더", title: "전체 예약 캘린더",
        sub: "날짜를 누르면 그 날짜로 예약을 시작합니다.",
        kind: "cal", page: 7 },
      { key: "patients", menu: "환자 목록",  title: "환자 목록",
        sub: "환자를 고르면 오른쪽에 상세가 뜨고 예약으로 이어집니다.",
        kind: "list", page: 8 },
      { key: "requests", menu: "예약 확인",  title: "예약 확인",
        badge: "요청 2",
        sub: "앱에서 들어온 방문 신청을 확인하고 검사를 배정합니다.",
        kind: "form", page: 9 },
    ],
  },
  {
    key: "nursing", name: "간호과", en: "NURSING",
    who: { name: "정다은", role: "간호사" },
    note: "내원 확인 · 문진 · 추적 관리",
    screens: [
      { key: "",          menu: "내원 대기",  title: "내원 대기 환자",
        badge: "대기 5",
        sub: "접수 순서대로 확인하고 유방외과 큐로 넘깁니다.",
        kind: "queue", page: 11 },
      { key: "followup",  menu: "추적 관리",  title: "추적 대상 관리",
        sub: "추적 회차를 만들고 안내 콜 기록을 남깁니다.",
        kind: "list", page: 12 },
      { key: "specimen",  menu: "검체 등록",  title: "검체 등록",
        sub: "생검 검체를 환자·병변과 이어 등록하면 병리과로 전달됩니다.",
        kind: "form", page: 13 },
    ],
  },
  {
    key: "radiology", name: "영상의학과", en: "RADIOLOGY",
    who: { name: "김지현", role: "교수" },
    note: "촬영 · 판독 · AI 대조",
    screens: [
      { key: "",         menu: "촬영 대기",  title: "촬영 대기 환자",
        badge: "대기 6",
        sub: "환자 순서대로 배치됩니다. 확인 후 촬영을 업로드합니다.",
        kind: "queue", page: 15 },
      { key: "patients", menu: "환자 목록",  title: "전체 환자 목록",
        sub: "검사별 진행 상황과 유방외과 확인 여부를 함께 봅니다.",
        kind: "list", page: 16 },
      { key: "upload",   menu: "촬영 업로드", title: "촬영 파일 업로드",
        badge: "DICOM",
        sub: "촬영본을 올리고 AI 판독을 시작합니다.",
        kind: "upload", page: 17 },
      { key: "read",     menu: "판독",       title: "영상 판독",
        badge: "AI 판독 완료",
        sub: "원본 위에 AI 검출을 겹쳐 보고, 소견을 저장해 유방외과로 전송합니다.",
        kind: "read", page: 18 },
      { key: "amend",    menu: "판독 정정",  title: "판독 정정",
        badge: "이력 보존",
        crumb: ["환자 목록", "환자 상세", "기존 판독 조회", "판독 정정"],
        sub: "이미 저장한 판독을 확인하고, 정정 내용을 입력합니다.",
        kind: "amend", page: 19 },
    ],
  },
  {
    key: "pathology", name: "병리과", en: "PATHOLOGY",
    who: { name: "박민재", role: "교수" },
    note: "검체 · 슬라이드 · AI 분석",
    screens: [
      { key: "",         menu: "검체 대기",      title: "검체 바인딩 대기",
        badge: "7건",
        sub: "간호과와 유방외과에서 등록한 검체가 순서대로 도착합니다. 확인 후 슬라이드를 업로드합니다.",
        kind: "queue", page: 21 },
      { key: "patients", menu: "환자 목록",      title: "전체 환자 목록",
        badge: "판독 대기 4",
        sub: "검체별 진행 상황과 유방외과 확인 여부를 함께 봅니다.",
        kind: "list", page: 24 },
      { key: "upload",   menu: "슬라이드 업로드", title: "촬영 파일 업로드",
        badge: "WSI",
        sub: "스캔한 전체 슬라이드 이미지를 올리고 AI 분석을 시작합니다.",
        kind: "upload", page: 22 },
      { key: "read",     menu: "판독",          title: "병리 판독",
        badge: "AI 분석 완료",
        sub: "WSI 위에 AI 분할 결과를 겹쳐 보고, 병변을 등록한 뒤 소견을 저장해 유방외과로 전송합니다.",
        kind: "read", page: 23 },
      { key: "amend",    menu: "판독 정정",     title: "판독 정정",
        badge: "이력 보존",
        crumb: ["환자 목록", "환자 상세", "기존 판독 조회", "판독 정정"],
        sub: "이미 작성하여 저장한 병리 판독을 확인하고, 정정 내용을 입력합니다.",
        kind: "amend", page: 25 },
    ],
  },
  {
    key: "surgery", name: "유방외과", en: "BREAST SURGERY",
    who: { name: "이수정", role: "교수" },
    note: "통합 진료 · 수술 결정",
    screens: [
      { key: "",        menu: "진료 대기",  title: "대기중 환자",
        badge: "대기 4",
        sub: "검사 진행 상황을 함께 보고, 진료 작성으로 들어갑니다.",
        kind: "queue", page: 27 },
      { key: "exams",   menu: "검사 종합",  title: "검사 종합 확인",
        sub: "맘모 · 초음파 · MRI · 병리를 한 화면에서 봅니다.",
        kind: "report", page: 28 },
      { key: "decision", menu: "수술 결정", title: "수술 결정 및 환자 설명",
        sub: "종합 리포트를 보고 수술 여부를 정한 뒤, 환자에게 설명합니다.",
        kind: "report", page: 29 },
      { key: "order",   menu: "검체 신청",  title: "검체 신청",
        badge: "팝업",
        crumb: ["진료 작성", "검체 신청"],
        sub: "조직검사를 신청합니다. 신청하면 간호과 검체 등록으로 이어집니다.",
        kind: "form", page: 30 },
    ],
  },
];

/* ── 아래는 표에서 뽑아 쓰는 것들 ───────────────────────────── */

export const ROOT = "/console";

/** 부서 하나의 주소.  /console/pathology */
export const deptPath = (d) => `${ROOT}/${d.key}`;

/** 화면 하나의 주소.  /console/pathology/read  (첫 화면은 key 가 빈 문자열) */
export const screenPath = (d, s) =>
  s.key ? `${deptPath(d)}/${s.key}` : deptPath(d);

export const findDept = (key) => DEPTS.find((d) => d.key === key);

/** 화면 수 — 「21개 화면」이 맞는지 세어 보는 자리 */
export const screenCount = DEPTS.reduce((n, d) => n + d.screens.length, 0);
