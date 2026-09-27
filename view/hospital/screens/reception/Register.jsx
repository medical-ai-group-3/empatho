import { useState } from "react";
import { reception as api } from "../../api";
import { Btn } from "../../lib/Page";
import Dialog from "../../lib/Dialog";
import { Warn } from "../../lib/Parts";

/* 원무 1장 [+ 등록] — 앱을 못 쓰는 환자를 창구에서 만든다
 * ════════════════════════════════════════════════════════════════
 *
 * 예외 경로다. 대부분은 앱으로 가입하고 오므로 검색으로 끝난다.
 *
 * **환자번호는 받지 않는다.** 서버가 발급한다 (PatientRegisterSerializer 가
 * "P" + uuid4 앞 열 자리로 만든다). 화면에서 받으면 사람이 지은 번호와
 * 서버가 지은 번호가 섞인다.
 *
 * ── 왜 등록 전에 검색을 한 번 더 하나 ──────────────────────────
 * 서버가 이렇게 생겼다 (views/reception.py 의 PatientRegisterView).
 *
 *   patient = serializer.save(...)
 *   out = serializers.PatientDetailSerializer(patient)
 *   return Response(out.data, status=status.HTTP_201_CREATED)
 *
 * 그리고 serializer 안에서는 —
 *
 *   existing = PatientPii.objects.filter(name=…, birth_date=…, phone=…).first()
 *   if existing:
 *       return existing.patient          ← 새로 안 만들고 있던 것을 돌려준다
 *
 * ⚠ **두 갈래가 똑같이 201 이고, 응답에 구분할 칸이 없다.** 새로 만든 건지
 *   있던 건지 화면이 알 수가 없다. PatientDetailSerializer 는 AUDIT_FIELDS
 *   (created_at 포함)를 빼고 주므로 시각으로 재 볼 수도 없다.
 *   → 다희님께 `created` 같은 칸이나 200/201 구분을 요청해 두었다.
 *
 * ⚠ **전화번호가 겹치면 500 이 난다.** patient_pii.phone 이 unique 인데
 *   이 serializer 에는 validate_phone 이 없다 (PatientCreateSerializer 에는
 *   있다). 이름이나 생년월일만 다르고 전화가 같으면 위 filter 가 못 찾고,
 *   그대로 PatientPii 를 만들다 무결성 오류로 터진다.
 *
 * 그래서 [등록] 이 먼저 GET /patients?q=전화번호 를 부른다. 세 갈래로 갈린다 —
 *
 *   이름·전화 모두 같다   → 있던 환자다. POST 를 **안 보낸다**
 *   전화만 같다          → 막는다. 보내면 500 이다
 *   없다                → POST 한다. 새 환자다
 *
 * 서버가 구분 칸을 주면 첫 갈래는 응답만 보고 판정하면 되고 이 선검색은
 * 없앨 수 있다. 둘째 갈래는 서버가 validate_phone 을 넣을 때까지 남는다.
 */

/* 전화번호는 사람이 「010-1234-5678」로도 「01012345678」로도 친다.
   숫자만 뽑아 견준다 — 하이픈 때문에 같은 사람을 다른 사람으로 본다 */
const digits = (s) => (s ?? "").replace(/\D/g, "");

const EMPTY = { name: "", birth_date: "", phone: "" };

export default function Register({ onClose, onDone }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  /* 전화만 겹치는 경우. 막되 **누구와 겹치는지 보여준다** — 「안 됩니다」만
     띄우면 창구에서 다음에 뭘 할지 알 수가 없다 */
  const [clash, setClash] = useState(null);

  const set = (k) => (e) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    setError(null);
    setClash(null);
  };

  const ready = form.name.trim() && form.birth_date && digits(form.phone);

  async function submit(e) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    setClash(null);

    const name = form.name.trim();
    const phone = form.phone.trim();

    try {
      /* ① 이 전화번호로 이미 있는 사람이 있나 */
      const rows = (await api.search(phone)) ?? [];
      const same = rows.filter((r) => digits(r.phone) === digits(phone));

      const exact = same.find((r) => (r.name ?? "").trim() === name);
      if (exact) {
        /* ⚠ 생년월일은 **있던 사람 것**을 둔다. 예전엔 방금 친 값으로 덮어
           찾은 줄에 남의 생년월일처럼 보이는 값이 떴다 — 검색 응답에도 이제
           birth_date 가 온다(PatientListSerializer) */
        onDone({ ...exact, birth_date: exact.birth_date ?? form.birth_date }, "exists");
        return;
      }
      if (same.length > 0) {
        setClash(same[0]);
        return;
      }

      /* ② 새로 만든다 */
      const p = await api.register({ name, birth_date: form.birth_date, phone });
      onDone(flatten(p), "created");
    } catch (e2) {
      setError(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title="환자 등록"
      onClose={busy ? undefined : onClose}
      foot={
        <>
          <Btn onClick={onClose} disabled={busy} type="button">취소</Btn>
          <Btn kind="fill" type="submit" form="reg" disabled={!ready || busy}>
            {busy ? "등록하는 중…" : "등록"}
          </Btn>
        </>
      }
    >
      {/* 단추가 팝업 바닥(dlg-foot)에 있어 form 밖이다. form="reg" 로 이어
          붙이면 Enter 로도 바닥 단추로도 같은 곳으로 들어간다 */}
      <form id="reg" onSubmit={submit} className="reg">
        <label className="field">
          <span>이름</span>
          <input value={form.name} onChange={set("name")} disabled={busy} autoFocus />
        </label>
        <label className="field">
          <span>생년월일</span>
          <input type="date" value={form.birth_date} onChange={set("birth_date")}
                 disabled={busy} />
        </label>
        <label className="field">
          <span>전화번호</span>
          <input value={form.phone} onChange={set("phone")} disabled={busy}
                 inputMode="tel" placeholder="010-0000-0000" />
        </label>

        {clash && (
          <div className="slot bad" role="alert">
            <b>이 전화번호는 다른 이름으로 등록돼 있습니다</b>
            <span>
              {clash.name ?? "—"} · {clash.patient_number}
              {clash.birth_year && <> · {clash.birth_year}년생</>}
            </span>
            <Warn>
              전화번호가 같으면 새로 만들 수 없습니다. 같은 분이면 팝업을 닫고
              전화번호로 검색해 고르시고, 다른 분이면 전화번호를 확인해 주세요.
            </Warn>
          </div>
        )}

        {error && (
          <div className="slot bad" role="alert">
            <b>{error.detail || error.message}</b>
            <span>{error.code}{error.traceId && <> · {error.traceId}</>}</span>
          </div>
        )}
      </form>
    </Dialog>
  );
}

/* 등록 응답을 검색 결과와 같은 모양으로 편다.
   PatientDetailSerializer 는 이름·전화·생년월일을 pii 안에 넣어 준다 —
   검색(PatientListSerializer)은 얕게 펴서 준다. 화면 한 곳에서 둘을 같이
   받으므로 여기서 모양을 맞춘다.

   ⚠ 등록 응답에는 **birth_date 가 있다.** 검색 결과에는 birth_year 뿐이라
     생년월일 칸을 못 채웠는데, 새로 만든 환자는 채울 수 있다 */
function flatten(p) {
  const pii = p.pii ?? {};
  return {
    patient_id: p.patient_id,
    patient_number: p.patient_number,
    name: pii.name ?? null,
    phone: pii.phone ?? null,
    birth_date: pii.birth_date ?? null,
    birth_year: p.birth_year ?? (pii.birth_date ? Number(pii.birth_date.slice(0, 4)) : null),
    sex: p.sex ?? null,
  };
}
