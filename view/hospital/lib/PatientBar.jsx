import { useEffect, useState } from "react";
import { seen } from "./recent";

/* 환자 띠 — 지금 누구를 보고 있는가
 * ────────────────────────────────────────────────────────────────
 *
 * 환자 한 명을 다루는 화면이면 무조건 상단바 바로 아래에 온다.
 * 업로드 · 판독 · 판독 정정 · 검사 종합 · 수술 결정이 얹는다.
 *
 *   [김] 김서연  54 · 여  P-2024-0417 │ [조영제 알레르기] │ 담당 최민호
 *
 * **경고가 맨 앞이다.** 조영제 알레르기처럼 촬영 전에 반드시 보여야 하는
 * 값을 스크롤 아래에 숨기지 않는다.
 *
 * ⚠ **없는 값은 칩 자체를 안 만든다.** `undefined` 를 「없음」으로 찍으면
 *   「알레르기 없음을 확인했다」로 읽힌다 — 확인한 적이 없는데도.
 *
 * ⚠ **이 띠가 세로를 먹는다.** 판독 화면 뷰어가 잘리므로 접을 수 있게
 *   두었다. 접으면 이름과 경고만 남는다 — 그 둘은 접혀도 보여야 한다.
 *
 * 서버 응답의 이름이 화면마다 달라서(환자 상세는 pii 안에, 오더 목록은
 * 평평하게) **어느 쪽이든 읽는다.** 화면마다 풀어 넣게 하면 한 곳만
 * 빠뜨려도 이름이 사라진다.
 */
export default function PatientBar({ patient, right, children }) {
  const [shut, setShut] = useState(false);

  /* 띠가 뜬다는 건 그 환자를 열었다는 뜻이다. 그것만 기억해 홈의 「최근 본
     환자」에 올린다 — **메모리에만** 담는다(lib/recent.js).
     ⚠ 훅이라 이른 반환보다 위에 있어야 한다. 아래로 내리면 patient 가
       없는 판에서 훅 수가 달라져 리액트가 터진다 */
  useEffect(() => {
    if (!patient) return;
    const pii = patient.pii ?? {};
    seen({
      id: patient.patient_id ?? patient.id,
      name: patient.name ?? patient.patient_name ?? pii.name,
      no: patient.patient_number ?? patient.patient_no ?? pii.patient_number,
    });
  }, [patient]);

  if (!patient) return null;

  const p = patient;
  const pii = p.pii ?? {};
  const name = p.name ?? p.patient_name ?? pii.name ?? null;
  const no = p.patient_number ?? p.patient_no ?? pii.patient_number ?? null;
  const sex = sexOf(p.sex ?? pii.sex);
  const age = p.age ?? ageOf(p.birth_year ?? pii.birth_year, pii.birth_date);

  /* 경고 — 값이 «있다»고 말할 때만 띄운다 */
  const warns = [];
  if (p.has_allergy === true || p.contrast_allergy) {
    warns.push(p.allergy_note || p.contrast_allergy || "조영제 알레르기");
  }

  const staff = p.primary_staff_name ?? null;

  return (
    <div className={`pbar${shut ? " shut" : ""}`}>
      <span className="pb-ava" aria-hidden="true">{name?.[0] ?? "—"}</span>

      <b className="pb-nm">{name ?? "이름 없음"}</b>

      {!shut && (age != null || sex) && (
        <span className="pb-who">
          {age != null && `${age}세`}{age != null && sex && " · "}{sex}
        </span>
      )}

      {no && <span className="pb-no">{no}</span>}

      {warns.length > 0 && (
        <span className="pb-warns">
          {warns.map((w, i) => (
            <span className="pb-warn" key={i}>
              <i aria-hidden="true">⚠</i> {w}
            </span>
          ))}
        </span>
      )}

      {!shut && children && <span className="pb-mid">{children}</span>}
      {!shut && staff && <span className="pb-staff">주치의 {staff}</span>}

      <span className="pb-r">
        {!shut && right}
        <button className="pb-fold" onClick={() => setShut(!shut)}
                aria-expanded={!shut}
                title={shut ? "환자 정보 펼치기" : "접기 — 뷰어를 넓게 봅니다"}>
          {shut ? "▾" : "▴"}
        </button>
      </span>
    </div>
  );
}

/* 성별 값이 한 가지가 아니다 — 서버·목업이 F · female · 여를 섞어 준다.
   patient.sex 에는 값 집합(choices)이 없어서 무엇이 올지 코드로는 모른다.
   아는 것은 한글로 바꾸고, **모르는 값은 버리지 않고 그대로 보여준다** —
   지워 버리면 성별이 아예 없는 환자처럼 보인다. */
const SEX = { F: "여", M: "남", female: "여", male: "남" };

function sexOf(v) {
  if (!v) return null;
  return SEX[v] ?? String(v);
}

/* 나이는 서버가 주면 그것을 쓰고, 없으면 출생 정보로 센다.
   ⚠ 둘 다 없으면 **안 만든다.** 모르는 나이를 0 으로 찍지 않는다. */
function ageOf(year, birthDate) {
  const y = year ?? (birthDate ? Number(String(birthDate).slice(0, 4)) : null);
  if (!y) return null;
  return new Date().getFullYear() - y;
}
