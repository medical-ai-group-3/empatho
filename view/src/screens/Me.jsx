import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";
import { deptSuffix } from "../lib/dept";
import { fmtDay, fmtDayKey } from "../lib/when";

/* 10 · 내 정보
 *
 * **나와 병원 사이의 것만** 둔다 — 이름 · 생년월일 · 담당 주치의.
 * 화면 밝기 · 글씨 크기 · 알림은 「설정」으로 갈라 나갔다(screens/Settings).
 *
 * ── 환자번호 대신 생년월일 ────────────────────────────────────
 * 환자번호(E_1029304)는 **병원 안에서 쓰는 번호**다. 본인이 봐도
 * 「내가 맞나」를 확인해 주지 못하고, 접수처에 전화할 때 부르는 것도
 * 보통 이름과 생년월일이다.
 *
 * 서버는 patient_number 를 계속 보낸다. 지운 것이 아니라 **화면에
 * 안 낼 뿐**이라, 나중에 필요해지면 되살리면 된다.
 *
 * ⚠ 주민등록번호는 여기 오지 않는다. 앱 어디에도 두지 않는다는 것이
 *   정해진 것이고, 생년월일은 그것과 다른 값이다.
 *
 * 가르는 기준은 «앱에서 고칠 수 있는가»다. 여기 있는 것은 병원이 갖고
 * 있는 자료라 앱에서 못 고친다. 저쪽은 언제든 바꿔도 되는 것이다.
 * 한 화면에 두면 「이건 고쳐도 되나」가 헷갈린다.
 *
 * ── 동의 내역을 화면에서 뺐다 ─────────────────────────────────
 * 환자가 자주 볼 자리가 아니라는 판단이다. 다만 **동의 철회 경로 자체를
 * 없앤 것은 아니다** — 맨 아래 문구가 접수처로 안내한다. 철회는 법으로
 * 보장되는 것이라 어디로든 길이 있어야 한다.
 *
 * API(api.withdrawConsent)와 목업 규격은 남겨 뒀다. 다시 넣기로 하면
 * 화면 한 조각만 되살리면 된다.
 */

export default function Me() {
  const { loading, data, error, reload } = useApi(() => api.me());

  return (
    <>
      <Head title="내 정보" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner me={data} />}
      </Body>
    </>
  );
}

function Inner({ me }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);

  async function logout() {
    setBusy(true);
    try { await api.logout(); } catch { /* 아래에서 어차피 나간다 */ }
    // 서버가 실패해도 로그인 화면으로 보낸다. 나가겠다고 누른 사람을
    // 붙잡아 두는 것이 더 나쁘다.
    nav("/login", { replace: true });
  }

  return (
    <>
      {/* 이름과 생년월일은 **카드에서 꺼내** 머리로 세웠다.
          작은 상자 둘로 시작하면 화면이 반 넘게 비는데, 정작 「누구의
          화면인가」가 제일 작은 글로 들어가 있었다. 동그라미는 홈
          머리말에서 쓰는 것과 같은 모양이라 같은 사람으로 읽힌다.

          아래 카드는 **병원과의 관계**다 — 담당 주치의와 내원 기록.
          한 상자에 다 넣으면 「생년월일」과 「담당 주치의」가 같은
          무게로 읽히는데, 하나는 나를 가리키는 값이고 하나는
          사람이다. */}
      <div className="pro">
        <span className="ava" aria-hidden="true">
          {me.display_name?.[0] ?? "·"}
        </span>
        <p className="nm">
          <b>{me.display_name} 님</b>
          {me.birth_date && <small>생년월일 {fmtDayKey(me.birth_date)}</small>}
        </p>
      </div>

      {(me.primary_staff_name || me.last_visit_at) && (
        <div className="card">
          {me.primary_staff_name ? (
            <>
              <span className="k">담당 주치의</span>
              <span className="v">
                {me.primary_staff_name}
                {deptSuffix(me.primary_staff_dept)}
              </span>
            </>
          ) : (
            <span className="k">내원 기록</span>
          )}
          {me.last_visit_at && (
            <span className="s">
              마지막 내원 {fmtDay(me.last_visit_at)}
              {deptSuffix(me.last_visit_dept)}
            </span>
          )}
        </div>
      )}

      {/* 밝기 · 글씨 크기 · 알림은 「설정」에 있다. 여기서 한 번 더
          안내하지 않는다 — 홈 톱니와 두 갈래가 되면 어느 쪽이 진짜인지
          헷갈린다 */}

      <button className="btn ghost" disabled={busy} onClick={logout}>
        로그아웃
      </button>

      <p className="note">
        회원 정보 수정이나 <b>동의 철회</b>는 접수처에 문의해 주세요.
        이름과 연락처는 병원 기록과 함께 관리됩니다.
      </p>
    </>
  );
}
