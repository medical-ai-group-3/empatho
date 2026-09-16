import { useState } from "react";
import { CATALOG, getMe, reportScope, setMe } from "../perm";
import { useMe } from "../lib/useMe";
import { logout as apiLogout, updateMe } from "../api";
import { signOut } from "../lib/session";
import { Page, Card, Btn } from "../lib/Page";
import { Chip, Facts } from "../lib/Parts";

/* 내 정보 — 내가 누구이고, 무엇을 할 수 있고, 무엇을 바꿀 수 있는가
 * ════════════════════════════════════════════════════════════════
 *
 * 상단바 오른쪽의 이름을 누르면 여기로 온다.
 *
 * ⚠ **과에 속한 화면이 아니다.** 사람은 과에 딸린 것이 아니라서
 *   /hospital/me 로 과 바깥에 둔다. 다른 화면이 전부 /hospital/{과}/…
 *   밑에 있는 것과 여기만 다르다.
 *
 * 2026-09-16 — staff-view 의 Profile.jsx 와 합쳤다.
 *   유방외과 쪽에 같은 화면이 따로 있었다(정은님). 두 벌을 두면 「내 정보」가
 *   과마다 다르게 생기는 꼴이라 하나로 모았다. **양쪽 기능을 다 살렸다** —
 *     Profile.jsx 에서   프로필 수정 · 알림 설정 · 로그아웃
 *     여기 있던 것에서   권한 카탈로그
 *   스타일은 이 판(hospital.css)의 것으로 다시 입혔다. staff-view 는
 *   자체 CSS 클래스(.pane .cols2 .pt-head …)를 쓰는데, 그걸 들고 오면
 *   이 판에 두 번째 디자인 체계가 생긴다.
 *
 * 왜 권한 목록을 보여주나
 *   권한이 없는 화면은 **메뉴에서 아예 사라진다** (lib/Top.jsx).
 *   그래서 선생님 입장에서는 「원래 없는 기능」인지 「나에게 권한이
 *   없는 것」인지 구분할 방법이 없다. 여기서 카탈로그 전체를 펼쳐
 *   놓고 가진 것만 켜서 보여 주면, 관리자에게 무엇을 달라고 해야
 *   하는지 알 수 있다. 그래서 **없는 권한도 지우지 않고 회색으로
 *   남긴다** — 없는 줄이 보여야 요청할 것이 보인다.
 *
 * ⚠ 권한은 여기서 **못 바꾼다.** 부여는 관리자 화면 몫이다.
 *   소속 · 사번 · 직책도 마찬가지라 읽기 전용으로만 띄운다.
 */

/* 카탈로그를 사람이 읽을 묶음으로 가른다.
   key 앞머리로 가르므로 perm.js 에 권한이 늘어도 여기는 안 고친다 */
const GROUPS = [
  { key: "pathology", name: "병리과" },
  { key: "radiology", name: "영상의학과" },
  /* ⚠ 리포트는 **셋 중 하나만** 갖는 등급이다 (perm.js 참고). 나머지 둘이
     「없음」으로 뜨는 것이 결핍처럼 보이면 안 되므로 한 줄 적어 둔다 —
     이걸 안 적으면 관리자에게 「없는 권한 둘」을 달라고 하게 된다 */
  { key: "report",    name: "리포트 열람",
    note: "셋 중 하나만 갖습니다. 위로 갈수록 넓은 범위입니다." },
];

function groupOf(permKey) {
  const head = permKey.split(".")[0];
  return GROUPS.some((g) => g.key === head) ? head : "report";
}

export default function MeScreen() {
  const me = useMe();
  const scope = reportScope();

  /* 로그인 응답이 없으면 화면을 그릴 것이 없다. main.jsx 의 Boot 가
     막아 주므로 평소에는 안 뜨지만, 혹시를 대비해 둔다 */
  if (!me) {
    return (
      <Page crumb={["내 정보"]} title="내 정보">
        <div className="slot big">
          <b>로그인 정보가 없습니다</b>
          <span>다시 로그인해 주세요.</span>
        </div>
      </Page>
    );
  }

  return (
    <Page
      crumb={["내 정보"]}
      title="내 정보"
      sub="프로필과 알림을 고치고, 내 권한을 확인하는 자리입니다."
      right={scope && <Chip>{scope.label}</Chip>}
    >
      <ProfileCard me={me} />
      <NotifyCard me={me} />
      <PermsCard me={me} />
      <AccountCard />
    </Page>
  );
}

/* ── 프로필 ───────────────────────────────────────────────────
   고칠 수 있는 것과 없는 것을 한 카드에 둔다. 못 고치는 값은 감추지 않고
   위쪽에 읽기 전용으로 적는다 — 사번이 아예 안 보이면 「어디서 보지」가
   되고, 보이되 입력칸이 아니면 「여기선 못 고치는구나」가 바로 읽힌다. */
function ProfileCard({ me }) {
  const [f, setF] = useState({
    name: me.name ?? "", email: me.email ?? "", phone: me.phone ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [err, setErr] = useState(null);

  const set = (k, v) => setF((o) => ({ ...o, [k]: v }));
  const dirty = f.name !== (me.name ?? "") ||
                f.email !== (me.email ?? "") ||
                f.phone !== (me.phone ?? "");

  async function save() {
    setBusy(true); setMsg(null); setErr(null);
    try {
      await updateMe(f);
      /* 저장한 값을 perm.js 에도 반영한다 — 상단바 이름이 곧바로 바뀐다.
         안 하면 새로고침할 때까지 옛 이름이 남는다 */
      setMe({ ...getMe(), ...f });
      setMsg("저장되었습니다.");
    } catch (e) {
      setErr(e.detail || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="프로필">
      <div className="me-head">
        <span className="ava lg" aria-hidden="true">{f.name?.[0]}</span>
        <Facts items={[
          ["소속", [me.hospital, me.dept_name ?? me.dept].filter(Boolean).join(" · ")],
          ["직책", me.role],
          me.staff_id && ["사번", me.staff_id],
        ]} />
      </div>

      <div className="me-form">
        <label className="field">
          <span>이름</span>
          <input value={f.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          <span>이메일</span>
          <input type="email" value={f.email}
                 onChange={(e) => set("email", e.target.value)} />
        </label>
        <label className="field">
          <span>연락처</span>
          <input value={f.phone} onChange={(e) => set("phone", e.target.value)} />
        </label>
      </div>

      <p className="muted small">
        소속 · 직책 · 사번은 관리자가 정합니다. 틀렸으면 관리자에게 문의하세요.
      </p>

      <div className="me-foot">
        <span className={err ? "note err" : "note"}>{err ?? msg}</span>
        <Btn kind="fill" onClick={save} disabled={busy || !dirty}>
          {busy ? "저장 중…" : "저장"}
        </Btn>
      </div>
    </Card>
  );
}

/* ── 알림 설정 ────────────────────────────────────────────────
   켜고 끄는 즉시 저장한다. 따로 [저장] 을 두면 눌렀는지 아닌지 헷갈린다.
   대신 **실패하면 되돌린다** — 껐다고 생각했는데 켜져 있는 것이 제일 나쁘다. */
const NOTIFY = [
  { key: "notify_discordance", label: "영상·병리 판정이 불일치할 때" },
  { key: "notify_specimen",    label: "검체 등록이 끝났을 때" },
];

function NotifyCard({ me }) {
  const [on, setOn] = useState(() =>
    Object.fromEntries(NOTIFY.map((r) => [r.key, Boolean(me[r.key])])));
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);

  async function flip(key, next) {
    setOn((o) => ({ ...o, [key]: next }));
    setBusy(key); setErr(null);
    try {
      await updateMe({ [key]: next });
      setMe({ ...getMe(), [key]: next });
    } catch (e) {
      setOn((o) => ({ ...o, [key]: !next }));   /* 되돌린다 */
      setErr(e.detail || e.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="알림 설정">
      <ul className="checks">
        {NOTIFY.map((r) => (
          <li key={r.key}>
            <label>
              <input type="checkbox" checked={on[r.key]}
                     disabled={busy === r.key}
                     onChange={(e) => flip(r.key, e.target.checked)} />
              <span>{r.label}</span>
            </label>
            {busy === r.key && <small className="muted small">저장 중…</small>}
          </li>
        ))}
      </ul>
      {err && <p className="note err">{err}</p>}
    </Card>
  );
}

/* ── 내 권한 ─────────────────────────────────────────────────── */
function PermsCard({ me }) {
  const mine = new Set(me.perms ?? []);
  const hasCount = CATALOG.filter((p) => mine.has(p.key)).length;

  return (
    <Card
      title="내 권한"
      right={<span className="muted small">{CATALOG.length}개 중 {hasCount}개</span>}
    >
      <p className="muted small">
        권한은 관리자가 계정마다 켜고 끕니다. 필요한 권한이 꺼져 있으면
        관리자에게 문의하세요. 꺼진 것도 무엇이 있는지 보이도록 함께 적어 둡니다.
      </p>

      {GROUPS.map((g) => {
        const rows = CATALOG.filter((p) => groupOf(p.key) === g.key);
        if (rows.length === 0) return null;
        const on = rows.filter((p) => mine.has(p.key)).length;

        return (
          <section key={g.key} className="perm-g">
            <h3>
              {g.name}
              <span className="muted small">{rows.length}개 중 {on}개</span>
            </h3>
            {g.note && <p className="muted small perm-note">{g.note}</p>}
            <ul className="perms">
              {rows.map((p) => {
                const has = mine.has(p.key);
                return (
                  <li key={p.key} className={has ? "on" : "off"}>
                    <i className="mk" aria-hidden="true">{has ? "●" : "○"}</i>
                    <span className="perm-tx">
                      <b>{p.label}</b>
                      <small>{p.where}</small>
                    </span>
                    {/* ⚠ Chip 을 안 쓴다. 이 판의 칩 세 톤은 「진행중·끝남·
                        기계가 도는 중」이라는 뜻이 정해져 있어서(Parts.jsx),
                        「권한 있음/없음」에 갖다 쓰면 그 어휘가 흐려진다.
                        모양으로 가르는 규칙은 왼쪽 ●/○ 가 지킨다 */}
                    <span className="perm-st">{has ? "있음" : "없음"}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </Card>
  );
}

/* ── 계정 ─────────────────────────────────────────────────────
   ⚠ 로그인 화면이 아직 없다. 그래서 로그아웃한 뒤 보낼 곳이 없어
     「창을 닫아 주세요」로 세워 둔다. 로그인 화면이 생기면 거기로 보낸다. */
function AccountCard() {
  const [state, setState] = useState("idle");   // idle · working · done
  const [err, setErr] = useState(null);

  async function go() {
    setState("working"); setErr(null);
    try {
      await apiLogout();
      setState("done");
    } catch (e) {
      /* ⚠ 서버가 실패해도 토큰은 이미 버려졌다 (api.js 의 logout).
         그래서 「로그아웃됨」으로 세우고, 서버에 못 알렸다는 것만 덧붙인다.
         여기서 idle 로 되돌리면 「아직 로그인된 것처럼」 보여서 더 위험하다 */
      setErr(e.detail || e.message);
      setState("done");
    } finally {
      /* ⚠ **저장소까지 비운다.** api.js 의 logout 은 api 층 토큰만 버리는데,
         session.js 가 sessionStorage 에도 들고 있어서 그것을 안 지우면
         새로고침했을 때 토큰이 되살아나 로그인된 것처럼 보인다.
         signOut 은 구독자에게도 알려서 Gate 가 로그인 화면으로 돌아간다 */
      signOut();
    }
  }

  if (state === "done") {
    return (
      <Card title="계정">
        <p><b>로그아웃되었습니다.</b> 창을 닫아 주세요.</p>
        {err && (
          <p className="note err">
            서버에 알리지는 못했습니다 ({err}). 이 기기에서는 로그아웃됐습니다.
          </p>
        )}
      </Card>
    );
  }

  return (
    <Card title="계정">
      <p className="muted small">이 기기에서 로그아웃합니다.</p>
      <div className="me-foot">
        <span className="note" />
        <Btn onClick={go} disabled={state === "working"}>
          {state === "working" ? "로그아웃 중…" : "로그아웃"}
        </Btn>
      </div>
    </Card>
  );
}
