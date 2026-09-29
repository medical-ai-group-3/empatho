import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { HOSPITAL, PRODUCT, deptPath, go, homeDept, menuScreens, myDepts, screenAt } from "../nav";
import { can } from "../perm";
import { acknowledgeNotification, apiInfo, noticeRef, notifications, path } from "../api";
import * as H from "../dept/home";
import { openNotifications } from "./live";
import { emitChange } from "./refresh";
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
/* 과마다 마지막으로 거쳐 온 메뉴 — deep 화면이 「어디서 왔나」를 고를 때 쓴다.
   탭을 누른 것만이 아니라 **그 화면이 떴으면** 적는다(아래 Top) — 대기 환자의
   「환자 상세」 단추처럼 화면 안 링크로 넘어가도 온 곳이 남는다.
   탭 세션(sessionStorage)에도 적어 둔다 — 상세 화면에서 새로고침해도 온 탭이
   그대로 켜진다. 못 적으면(사생활 창 등) 메모리만 쓰고, 그것도 없으면
   parent 의 첫째로 켜진다 */
const LAST_KEY = "hospital.lastMenu";
const lastMenu = new Map((() => {
  try { return Object.entries(JSON.parse(sessionStorage.getItem(LAST_KEY)) ?? {}); }
  catch { return []; }
})());
function rememberMenu(deptKey, menuKey) {
  if (lastMenu.get(deptKey) === menuKey) return;
  lastMenu.set(deptKey, menuKey);
  try { sessionStorage.setItem(LAST_KEY, JSON.stringify(Object.fromEntries(lastMenu))); }
  catch { /* 기억 못 해도 된다 — 첫째 parent 로 켜진다 */ }
}

/* 화면 줄에서 불을 켤 메뉴 key. NavLink 의 앞머리 맞춤에 맡기면
   patients/:id/review 가 「전체 환자(patients)」로 켜진다 — 주소 틀로 화면을
   찾고, deep 이면 nav.js 의 parent 로 올라간다. 과 바깥(환자 상세)은 null */
function activeMenu(dept, pathname) {
  const s = screenAt(dept, pathname);
  if (!s) return null;
  if (!s.deep) return s.key;
  const parents = [s.parent ?? []].flat();
  const last = lastMenu.get(dept.key);
  return parents.includes(last) ? last : (parents[0] ?? null);
}

export default function Top({ dept, now, counts, summary }) {
  const me = useMe();
  const { pathname } = useLocation();
  const depts = myDepts();
  const screens = dept ? menuScreens(dept).filter((s) => can(s.need)) : [];
  const onKey = activeMenu(dept, pathname);
  const here = screenAt(dept, pathname);
  if (here && !here.deep) rememberMenu(dept.key, onKey);

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
                label: s.menu, on: s.key === onKey,
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

        {/* 띠에는 환자 검색을 두지 않는다 — 과마다 환자 목록 · 접수 화면의
            검색이 그 자리를 한다(두 곳에서 찾게 하지 않는다) */}
        <span className="band-fill" />

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
 *   · 종을 누르면 확인 안 된 알림 목록(GET /notifications/). 누른 줄은
 *     확인 처리되고 목록에서 빠진다
 *   · 숫자는 **서버 목록의 확인 안 된 것**이다 — 화면이 따로 세면
 *     새로고침할 때마다 어긋난다
 *
 * ⚠ 병리는 크롭마다 분석해서 같은 알림이 연달아 둘 온다(같은 리포트).
 *   띄우는 것만 하나로 줄인다. 목록에는 서버가 준 대로 둔다.
 * ⚠ 목업 모드는 허브가 없어서 열지 않는다.
 *
 * **누르면 그 건으로 간다**(noticeTo). 전에는 확인만 되고 아무 데도 안
 * 갔다 — 「판독이 확정됐다」를 보고도 그 환자를 다시 찾아 들어가야 했다.
 */

/* 알림 한 줄 → 갈 주소. 못 정하면 null(확인만 하고 그 자리에 둔다).
 *
 *   discordance · discordance_flag   유방외과 불일치 처분 화면
 *   report (AI 끝 · 판독 확정)        리포트를 읽어 환자 · 검사 · 검체를 얻는다
 *   assessment (영상 판독 확정)       판독 → 검사 → 환자
 *   specimen (병리 확정, 09-28~)      유방외과 검사 종합(그 검체) · 병리 판독 · 그 밖 환자 상세
 *   ref 없음 (옛 병리 확정)           환자가 실려 있으면 검사 종합, 아니면 확인만
 *
 * 받는 사람 권한으로 고른다 — 유방외과(주치의)는 검사 종합에서 그 건을
 * 펴서(go.breast.review 의 ?study= · ?specimen=), 영상 · 병리는 제 판독
 * 화면으로. 둘 다 아니면 공용 환자 상세.
 * ⚠ 직원 알림은 patient 가 비어 온다 — api.js noticeRef 참고 */
async function noticeTo(n) {
  const type = n.notification_type ?? n.type;
  const ref = n.ref_type;
  const id = n.ref_id;
  if (type === "discordance" || ref === "discordance_flag") {
    return id != null && can("breast.discordance.view") ? go.breast.discordance(id) : null;
  }
  /* 옛 서버의 병리 확정 알림은 ref 가 비어 온다(REF_TYPE 에 specimen 이
     없었다 — views/pathology.py _notify_finalized). 환자도 안 실린다 → 확인만 한다 */
  let pid = n.patient ?? null;
  if (id == null) {
    return pid != null && can("breast.review.view") ? go.breast.review(pid) : null;
  }

  /* 09-28 병리 확정 알림이 ref_type "specimen" · ref_id 검체 번호를 싣는다.
     받는 사람마다 갈 곳이 다르다 —
       유방외과   검사 종합에서 그 검체를 펴서(환자 번호는 검체를 읽어 얻는다)
       병리       제 판독 화면 — 환자를 몰라도 되니 검체를 안 읽는다
       그 밖      공용 환자 상세
     ⚠ 권한 순서가 곧 우선순위다. 유방외과 열쇠가 있으면 병리 열쇠가 같이
       있어도 검사 종합으로 간다(주치의에게 온 알림이다) */
  if (ref === "specimen") {
    const review = can("breast.review.view");
    if (!review && can("pathology.read.view")) return go.pathology.read(id);
    if (pid == null) {
      const s = await noticeRef.specimen(id).catch(() => null);
      pid = s?.patient ?? s?.patient_id ?? null;
    }
    if (pid == null) return null;
    return review ? go.breast.review(pid, { specimen: id }) : go.patient(pid);
  }

  let study = null;
  let specimen = null;
  let assessment = null;
  if (ref === "report") {
    const r = await noticeRef.report(id);
    pid = r?.patient ?? pid;
    study = r?.study ?? null;
    specimen = r?.specimen ?? null;
  } else if (ref === "assessment") {
    /* 영상 판독 확정(views/radiology.py _notify_study_finalized). 판독 줄이
       patient_id · study 를 같이 싣는다 */
    const a = await noticeRef.assessment(id);
    assessment = id;
    study = a?.study ?? null;
    pid = a?.patient_id ?? pid;
  } else if (ref === "study") {
    study = id;
  }
  if (pid == null && specimen != null) pid = (await noticeRef.specimen(specimen))?.patient ?? null;
  if (pid == null && study != null) pid = (await noticeRef.study(study))?.patient ?? null;

  if (pid != null && can("breast.review.view")) {
    return go.breast.review(pid, study != null ? { study, assessment }
      : specimen != null ? { specimen } : null);
  }
  if (specimen != null && can("pathology.read.view")) return go.pathology.read(specimen);
  if (study != null && can("radiology.read.view")) return go.radiology.read(study);
  return pid != null ? go.patient(pid) : null;
}

function Bell({ on }) {
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState(null);
  const [toast, setToast] = useState(null);
  const load = () => notifications().then(setItems).catch(() => setItems([]));

  useEffect(() => {
    if (!on) return;
    load();
    /* 목업은 목록(GET /notifications/)만 있고 허브가 없다 — SSE 는 안 연다 */
    if (apiInfo.mock) return;
    let last = "";
    return openNotifications({
      issue: path.ticket,
      onEvent: (ev) => {
        const p = ev.payload ?? {};
        const key = `${ev.type}:${p.ref_type}:${p.ref_id}`;
        /* 띄운 것도 누르면 그 건으로 간다 — 알림 줄과 같은 모양으로 들고 있는다 */
        if (key !== last) {
          setToast({ text: p.message || "새 알림이 있습니다",
            n: { notification_type: ev.type, ref_type: p.ref_type, ref_id: p.ref_id } });
        }
        last = key;
        load();
        /* 알림은 곧 무엇이 바뀌었다는 뜻이다 — 다른 컴퓨터의 변경(결과 도착 ·
           판독 확정 …)을 열어 둔 목록 · 판이 주기를 기다리지 않고 바로
           다시 부르게 한다(lib/refresh.js) */
        emitChange();
      },
      onResync: load,
    });
  }, [on]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  /* 팝업에는 **확인 안 된 것만** 둔다 — 누른 알림은 목록에서 빠진다.
     종의 숫자와 줄 수가 늘 같다. 누르자마자 화면에서 먼저 빼고, 서버
     확인은 뒤에서 한다(실패하면 다음 목록에서 다시 나타난다) */
  const unreadList = (items ?? []).filter((n) => !n.acknowledged_at);
  const unread = unreadList.length;

  function read(n) {
    setItems((all) => (all ?? []).filter((x) => x.notification_id !== n.notification_id));
    acknowledgeNotification(n.notification_id).catch(load);
  }

  /* 확인하고 그 건으로 간다. 못 풀면(권한 · 지워진 행) 확인만 된다 */
  async function follow(n) {
    setOpen(false);
    setToast(null);
    try {
      const to = await noticeTo(n);
      if (to) nav(to);
    } catch { /* 못 푼 알림은 확인만 하고 그 자리에 둔다 */ }
  }

  return (
    <div className="bell-wrap">
      <button className="bell" aria-label={`알림${unread ? ` ${unread}건` : ""}`}
              aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {/* 09-28 — 「◍」 점이라 알림인지 몰랐다. 종 모양으로 */}
        <svg className="bell-ico" viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.6 1.6a.6.6 0 0 1-.42 1.02H4.82a.6.6 0 0 1-.42-1.02L6 16.5Z" />
          <path d="M9.8 20.6a2.3 2.3 0 0 0 4.4 0" />
        </svg>
        {unread > 0 && <i>{unread}</i>}
      </button>
      {open && (
        <div className="notice-pop" role="dialog" aria-label="알림">
          <header>
            <b>알림</b>
            <button type="button" onClick={() => setOpen(false)} aria-label="닫기">×</button>
          </header>
          {items == null ? <p className="notice-state">불러오는 중…</p>
            : unread === 0 ? <p className="notice-state">새 알림이 없습니다</p>
            : (
              <ul>
                {unreadList.map((n) => (
                  <li key={n.notification_id}>
                    <button type="button" className="new"
                            onClick={() => { read(n); follow(n); }}
                            title="누르면 읽음으로 표시되고 해당 화면으로 이동합니다">
                      <b>{n.message}</b>
                      <span>{H.at(n.sent_at || n.created_at)}</span>
                      <em>확인</em>
                    </button>
                  </li>
                ))}
              </ul>
            )}
        </div>
      )}
      {toast && (
        <p className="live-toast" role="status" onClick={() => follow(toast.n)}>{toast.text}</p>
      )}
    </div>
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
        /* ⚠ 불은 it.on 으로만 켠다. NavLink 의 isActive 는 앞머리 맞춤이라
           deep 주소에서 엉뚱한 탭을 켠다(activeMenu 참고) */
        <Link key={it.key} to={it.to}
              className={`tab${it.on ? " on" : ""}`}
              aria-current={it.on ? "page" : undefined}>
          {it.label}
          {/* 0 이면 안 붙인다 — 「0건」인지 「아직 모른다」인지
              구분이 안 되는 숫자는 없느니만 못하다 */}
          {it.badge > 0 && <i className="tab-n">{it.badge}</i>}
        </Link>
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
