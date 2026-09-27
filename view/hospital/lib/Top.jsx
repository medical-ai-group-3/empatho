import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { HOSPITAL, PRODUCT, deptPath, go, homeDept, menuScreens, myDepts } from "../nav";
import { can } from "../perm";
import { acknowledgeNotification, apiInfo, notifications, path } from "../api";
import * as H from "../dept/home";
import { openNotifications } from "./live";
import { useMe } from "./useMe";

/* 상단바 — 세 층
 * ────────────────────────────────────────────────────────────────
 *
 *   띠      로고 · 검색 · 시각 · 나        60px  검은 띠
 *   과 줄   과 전환                        56px  검은 띠
 *   화면 줄 그 과의 화면 + 요약 숫자        44px  흰 줄
 *
 * **위쪽을 아끼지 않는다.** 하루에 수백 번 누르는 자리라 작게 만들면
 * 손해다.
 *
 * **내비게이터는 두 층이다** — 과를 고르는 줄과 그 과의 화면을 고르는 줄.
 * 둘이 다른 모양이면 「내비게이터가 둘」로 보인다. 그래서 두 줄이 **같은
 * 부품(TabRow)** 을 쓴다. 다른 것은 크기와 바탕뿐이다.
 *
 * **요약 줄을 따로 두지 않는다.** 숫자는 화면 줄 오른쪽 끝에 붙인다 —
 * 줄을 하나 더 만들면 내비게이터가 너무 두꺼워진다.
 *
 * **권한이 없는 화면·과는 메뉴에 안 뜬다.** 눌러 봐야 「권한이 없습니다」만
 * 나올 자리를 띄워 두면 매번 헛걸음하게 된다. (버튼은 반대다 — 버튼은
 * 감추지 않고 끈다. 사라지면 고장으로 오해한다.)
 *
 * ⚠ **탭 건수는 지어내지 않는다.** 과마다 목록을 불러야 나오는 숫자라
 *   GET /home 이 붙기 전에는 셀 수가 없다. counts 에 들어온 것만 찍고
 *   없으면 뱃지를 안 단다 — 0 을 찍으면 「0건」인지 「모른다」인지
 *   구분이 안 된다.
 */
export default function Top({ dept, now, counts, summary }) {
  const me = useMe();
  const depts = myDepts();
  const screens = dept ? menuScreens(dept).filter((s) => can(s.need)) : [];

  return (
    <header className="top">
      <Band now={now} />

      {/* 과 줄 */}
      <TabRow className="tabs" label="과"
              items={depts.map((d) => ({
                key: d.key, to: deptPath(d), label: d.name,
                badge: counts?.[d.key], on: d.key === dept?.key,
              }))} />

      {/* 화면 줄 — 왼쪽에 화면, 오른쪽 끝에 요약 숫자 */}
      <TabRow className="tabs2" label={dept ? `${dept.name} 화면` : "화면"}
              items={screens.map((s) => ({
                key: s.key || "_",
                to: `${deptPath(dept)}${s.key ? `/${s.key}` : ""}`,
                label: s.menu, end: !s.key,
              }))}
              right={<Summary items={summary} />} />
    </header>
  );

  /* ── 1층 · 띠 ─────────────────────────────────────────────── */
  function Band({ now }) {
    return (
      <div className="band">
        {/* 로고는 첫 화면으로 돌아가는 구멍이다. 어디서든 빠져나올 길이
            하나는 있어야 한다.
            ⚠ **내가 갈 수 있는 과**로 보낸다. 첫 과로 고정하면 원무 계정이
              누를 때마다 권한 없는 병리과로 끌려간다 — 빠져나오는 구멍이
              오히려 가두는 구멍이 된다 */}
        <Link className="band-brand" to={deptPath(homeDept())}>
          <span className="mark" aria-hidden="true">◈</span>
          <b>{PRODUCT}</b>
        </Link>
        <span className="band-div" aria-hidden="true" />
        <span className="band-hosp">{HOSPITAL}</span>
        <span className="band-div" aria-hidden="true" />

        {/* 로그인한 사람 — **왼쪽에 크게.** 판독을 확정하고 결정을 남기는
            사람이 「지금 누구로 들어와 있나」를 매번 확인해야 하는 값이라
            오른쪽 구석에 작게 둘 자리가 아니다.
            ⚠ 로그인 정보가 없을 때는 **링크가 아니라 글자로 둔다** —
              누를 곳이 없는데 눌리면 빈 화면으로 보내게 된다 */}
        {me ? (
          <NavLink to={go.me()} title="내 정보"
                   className={({ isActive }) => `who${isActive ? " on" : ""}`}>
            <span className="who-ava" aria-hidden="true">{me.name?.[0]}</span>
            <b>{me.name}님</b>
            {/* ⚠ role 은 직책이 아니라 **역할 값**이다 — 진짜 서버는
                "pathology" 같은 값을 준다(MeSerializer 의 role). 그대로
                찍으면 「한지우 reception」이 된다. 한글 이름은 dept_name */}
            {me.dept_name && <em>{me.dept_name}</em>}
          </NavLink>
        ) : (
          <span className="who"><b>—</b><em>로그인 정보 없음</em></span>
        )}

        <PatientSearch dept={dept} />

        <div className="band-r">
          <span className="when">{now}</span>
          <Bell on={Boolean(me)} />
        </div>
      </div>
    );
  }
}

/* ── 알림 종 ──────────────────────────────────────────────────
 *
 * 전에는 누를 곳만 있고 아무 일도 안 했다. 서버는 AI 판독이 끝나면
 * 요청한 선생님에게 SSE 로 알림을 보내는데(core/tasks.py), 받는 쪽이
 * 없어서 화면에는 한 번도 안 떴다.
 *
 *   · 로그인하면 SSE 를 연다(lib/live.js). 알림이 오면 잠깐 띄우고
 *     종의 숫자를 올린다
 *   · 종을 누르면 내 알림 목록(GET /notifications/). 누른 줄은 확인 처리
 *   · 숫자는 **서버 목록의 확인 안 된 것**이다 — 화면이 따로 세면
 *     새로고침할 때마다 어긋난다
 *
 * ⚠ 병리는 크롭마다 분석해서 같은 알림이 연달아 둘 온다(같은 리포트).
 *   띄우는 것만 하나로 줄인다. 목록에는 서버가 준 대로 둔다.
 * ⚠ 목업 모드는 허브가 없어서 열지 않는다.
 */
function Bell({ on }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const [toast, setToast] = useState(null);
  const load = () => notifications().then(setItems).catch(() => setItems([]));

  useEffect(() => {
    if (!on || apiInfo.mock) return;
    load();
    let last = "";
    return openNotifications({
      issue: path.ticket,
      onEvent: (ev) => {
        const p = ev.payload ?? {};
        const key = `${ev.type}:${p.ref_type}:${p.ref_id}`;
        if (key !== last) setToast(p.message || "새 알림이 왔습니다");
        last = key;
        load();
      },
      onResync: load,
    });
  }, [on]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const unread = (items ?? []).filter((n) => !n.acknowledged_at).length;

  function read(n) {
    if (n.acknowledged_at) return;
    acknowledgeNotification(n.notification_id).then(load).catch(() => {});
  }

  return (
    <div className="bell-wrap">
      <button className="bell" aria-label={`알림${unread ? ` ${unread}건` : ""}`}
              aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span aria-hidden="true">◍</span>
        {unread > 0 && <i>{unread}</i>}
      </button>
      {open && (
        <div className="notice-pop" role="dialog" aria-label="알림">
          <header>
            <b>알림</b>
            <button type="button" onClick={() => setOpen(false)} aria-label="닫기">×</button>
          </header>
          {items == null ? <p className="notice-state">불러오는 중…</p>
            : items.length === 0 ? <p className="notice-state">받은 알림이 없습니다</p>
            : (
              <ul>
                {items.map((n) => (
                  <li key={n.notification_id}>
                    <button type="button" className={n.acknowledged_at ? "" : "new"}
                            onClick={() => read(n)}>
                      <b>{n.message}</b>
                      <span>{H.at(n.sent_at || n.created_at)}</span>
                      {!n.acknowledged_at && <em>새 알림</em>}
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </div>
      )}
      {toast && (
        <p className="live-toast" role="status" onClick={() => setToast(null)}>{toast}</p>
      )}
    </div>
  );
}

/* ── 환자 찾기 ────────────────────────────────────────────────
 *
 * 이 시스템에서 제일 많이 하는 행동이라 가운데에 크고 길게 둔다.
 * `/` 를 누르면 어디서든 여기로 들어온다 — 글자를 치던 중이면 안 뺏는다.
 *
 * ⚠ **여기서 검색하지 않는다.** 누르면 목록 화면으로 넘기고 그쪽이
 *   서버에 묻는다(?q=). 상단바가 스스로 목록을 들고 있으면 화면마다
 *   결과가 두 벌이 된다.
 *
 * ⚠ **지금 보는 과의 목록으로 보낸다.** 한 과로 고정하면 다른 과 선생님이
 *   검색할 때마다 권한 없는 화면으로 끌려간다. 과 바깥 환자 목록은 아직
 *   없다 — 생기면 여기를 그쪽 하나로 바꾼다.
 *
 * ⚠ **과 이름을 여기 박지 않는다.** 어느 화면이 목록인지는 nav.js 의 등록
 *   표에서 읽는다(`key` 가 patients · specimens 인 줄). 과가 늘거나 합쳐져도
 *   이 파일은 안 고친다 — 박아 두면 표와 여기 두 곳을 같이 고쳐야 하고,
 *   한쪽만 고치면 검색이 엉뚱한 데로 간다.
 */
const LIST_KEYS = new Set(["patients", "specimens"]);

function listPath(dept) {
  if (!dept) return null;
  const s = menuScreens(dept).find((x) => LIST_KEYS.has(x.key) && can(x.need));
  return s ? `${deptPath(dept)}/${s.key}` : null;
}

function PatientSearch({ dept }) {
  const [q, setQ] = useState("");
  const box = useRef(null);
  const nav = useNavigate();
  const where = listPath(dept);

  useEffect(() => {
    const hit = (e) => {
      if (e.key !== "/") return;
      const t = e.target;
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      box.current?.focus();
    };
    document.addEventListener("keydown", hit);
    return () => document.removeEventListener("keydown", hit);
  }, []);

  function submit(e) {
    e.preventDefault();
    const v = q.trim();
    if (!v || !where) return;
    nav(`${where}?q=${encodeURIComponent(v)}`);
  }

  return (
    <form className="band-find" onSubmit={submit} role="search">
      <span aria-hidden="true">⌕</span>
      <input ref={box} value={q} onChange={(e) => setQ(e.target.value)}
             placeholder="환자 이름 · 환자번호 · 생년월일" aria-label="환자 찾기"
             disabled={!where}
             title={where ? undefined : "이 과에는 환자 목록 화면이 없습니다"} />
      <kbd aria-hidden="true">/</kbd>
    </form>
  );
}

/* ── 탭 줄 — 과 줄과 화면 줄이 **같은 부품**을 쓴다 ─────────────
 *
 * 둘이 다른 모양이면 「내비게이터가 둘」로 보인다. 그래서 여기 하나만
 * 두고 className 으로 크기·바탕만 가른다. 코드를 두 벌 쓰면 한쪽만
 * 고치는 날이 온다.
 *
 * **색을 늘리지 않고 무게와 움직임으로 낸다.** 고른 탭은 바탕이 바뀌고,
 * 아래 강조선 **하나**가 그 자리로 미끄러져 간다 — 어디로 갔는지가
 * 눈으로 따라와진다.
 *
 * ⚠ **선은 장식이다.** 상태는 aria-current 가 말한다. 선이 안 그려져도
 *   읽는 프로그램에는 아무 차이가 없어야 한다.
 *
 * ⚠ **위치를 재서 넣는다.** 이름 길이가 제각각이라 계산으로는 못 맞춘다.
 *   글꼴이 늦게 와서 너비가 변하는 일도 있어 ResizeObserver 로 다시 잰다 —
 *   한 번만 재면 처음 그림에서 선이 어긋난 채로 남는다.
 */
function TabRow({ className, label, items, right }) {
  const box = useRef(null);
  const [mark, setMark] = useState(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;

    const measure = () => {
      const on = el.querySelector(".tab.on");
      if (!on) { setMark(null); return; }
      setMark({ x: on.offsetLeft, w: on.offsetWidth });
    };

    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    el.querySelectorAll(".tab").forEach((t) => ro.observe(t));
    return () => ro.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <nav className={className} aria-label={label} ref={box}>
      {items.map((it) => (
        <NavLink key={it.key} to={it.to} end={it.end}
                 className={({ isActive }) => `tab${isActive ? " on" : ""}`}
                 aria-current={it.on ? "page" : undefined}>
          {it.label}
          {/* 0 이면 안 붙인다 — 「0건」인지 「아직 모른다」인지
              구분이 안 되는 숫자는 없느니만 못하다 */}
          {it.badge > 0 && <i className="tab-n">{it.badge}</i>}
        </NavLink>
      ))}
      {mark && (
        <span className="tab-mark" aria-hidden="true"
              style={{ width: mark.w, transform: `translateX(${mark.x}px)` }} />
      )}
      {right}
    </nav>
  );
}

/* ── 요약 숫자 — 화면 줄 오른쪽 끝 ────────────────────────────
 *
 * 줄을 따로 만들지 않는다. **카드로도 만들지 않는다** — 박스를 씌우면
 * 높이만 먹고 읽는 속도는 안 는다.
 *
 * **숫자가 앞이다.** 「오늘 접수 24」가 아니라 「24 오늘 접수」 —
 * 훑을 때 눈이 숫자만 따라간다.
 *
 * items 는 [["오늘 접수", 24], …]. **서버가 준 것만 넣는다.**
 */
function Summary({ items }) {
  if (!items?.length) return null;
  return (
    <p className="sum">
      {items.map(([k, v], i) => (
        <span key={k}>
          {i > 0 && <i aria-hidden="true">·</i>}
          <b>{v}</b> <em>{k}</em>
        </span>
      ))}
    </p>
  );
}
