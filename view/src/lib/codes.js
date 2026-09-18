/* 코드 ↔ 한글 — 환자 앱에서 서버 값이 화면 글자가 되는 자리
 * ════════════════════════════════════════════════════════════════
 *
 * 병원 웹의 `hospital/codes.js` 와 **같은 일을 하지만 파일을 갈랐다.**
 * 두 앱은 서로의 코드를 import 하지 않는다(README 참고) — 토큰 이름이
 * 겹치고 입구가 다르다. 그리고 환자에게 보여줄 말은 직원용과 다르다:
 * 직원 화면의 「유방촬영」이 여기서는 「유방 엑스레이 촬영」이 되는 식이다.
 *
 * ⚠ **코드 자체는 서버 것을 그대로 쓴다.** empatho-app 의
 *   `core/models.py` 에서 옮겼다 (2026-09-17 확인).
 *
 * ── 왜 필요했나 ──────────────────────────────────────────────
 *
 * 화면이 `r.status_label` · `r.modality_label` 처럼 **서버가 한글을
 * 보내 줄 것**을 기대하고 있었다. 그런데 서버 모델에는 그런 칸이 없다 —
 * 목업이 지어낸 것이다. 실서버에 붙는 날 그 자리가 전부 빈칸이 된다.
 *
 * 그래서 `text()` 로 읽는다. 서버가 라벨을 주면 그것을 쓰고, 안 주면
 * 코드로 만든다. **어느 쪽이 와도 화면은 그대로다.**
 */

/** 서버 enum: ["mammo", "us", "mri"]
 *
 * 환자에게는 기계 이름 대신 무엇을 하는 검사인지로 적는다 — 「맘모」는
 * 병원 안에서 쓰는 줄임말이라 받는 사람이 모른다. */
export const MODALITY = {
  mammo: "유방촬영",
  us: "유방초음파",
  mri: "유방 MRI",
};

/* 목업 일부와 옛 화면이 쓰던 철자. 서버 코드는 `us` 다 */
const ALIAS = { ultrasound: "us", ultra: "us", mammography: "mammo" };
export const modality = (v) => ALIAS[v] ?? v ?? null;

/** 예약·검사 상태. 서버 enum 일곱 (ORDER_STATUS)
 *
 * ⚠ 환자에게 보이는 말이라 **병원 내부 용어를 그대로 쓰지 않는다.**
 *   `ordered` 는 직원에게 「검사 확정」이지만 환자에게는 그냥 「예약
 *   확정」이다. `accepted` · `in_progress` 는 접수처·검사실 안의 단계라
 *   환자 화면에서는 굳이 갈라 보여줄 이유가 없다. */
export const ORDER_STATUS = {
  requested: "확인 중",
  scheduled: "예약 확정",
  ordered: "예약 확정",
  accepted: "접수 완료",
  in_progress: "검사 중",
  completed: "검사 완료",
  cancelled: "취소됨",
};

/** 「새 소식」처럼 눈에 띄어야 하는 상태인가 — 알약 모양을 가른다.
 *  확정된 다음 일정만 강조한다. 지난 것과 취소는 가라앉힌다. */
export const LIVE_ORDER = new Set(["scheduled", "ordered", "accepted", "in_progress"]);

/** 코드 하나를 한글로. 모르는 코드는 감추지 않고 그대로 낸다 —
 *  빈칸은 「값이 없다」로 읽히는데 실제로는 「모르는 값이 왔다」다. */
export function label(table, code) {
  if (code == null || code === "") return "";
  return table[code] ?? String(code);
}

/** 서버 라벨이 있으면 그것, 없으면 코드로 만든 라벨.
 *
 *   text(r, "order_status", ORDER_STATUS)
 *     → r.status_label 이 있으면 그것 (서버가 줄 때)
 *     → 없으면 label(ORDER_STATUS, r.order_status)
 *
 * base 와 라벨 칸 이름이 다를 수 있어 둘째 인자로 라벨 칸을 따로 받는다. */
export function text(row, base, table, labelKey) {
  const given = row?.[labelKey ?? `${base}_label`];
  if (given) return given;
  return label(table, row?.[base]);
}

/* 서버가 코드표를 내려주면 얹는다. 병원 웹 쪽과 같은 규칙이다 */
const TABLES = { modality: MODALITY, order_status: ORDER_STATUS };

export function adopt(payload = {}) {
  for (const [name, rows] of Object.entries(payload)) {
    const table = TABLES[name];
    if (!table || !rows || typeof rows !== "object") continue;
    Object.assign(table, rows);
  }
}
