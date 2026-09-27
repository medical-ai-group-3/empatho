import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import PortOne from "@portone/browser-sdk/v2";
import { api } from "../api";
import { Head } from "../lib/Screen";

/* 02 · 가입
 *
 * **아이디는 본인이 정한다.** 병원 기록과는 이름+생년월일+휴대폰이 모두
 * 같을 때만 잇는다(원무과가 먼저 등록해 둔 환자). 하나라도 다르면 새 환자다.
 * 병원코드 · 환자번호 · 주민등록번호는 묻지 않는다.
 *
 * 두 걸음이다.
 *   ① 본인 확인   이름 · 생년월일 · 성별 · 휴대폰 → 포트원(KG이니시스) 본인인증
 *                  → 서버가 인증 결과와 입력값을 대조해 verify_token 을 준다
 *   ② 아이디 정하기 그 표를 들고 가입을 마친다
 *
 * 입력값은 우리가 저장할 환자 정보다. 인증 결과와 하나라도 다르면 서버가
 * 거절하고 다시 받는다 — 조용히 인증값으로 바꾸면 잘못 넣은 줄 모른다.
 *
 * ⚠ 모바일은 인증창에서 **리다이렉트로** 돌아온다. 그때 화면이 새로 열려
 *   입력값이 사라지므로 sessionStorage(KEEP)에 잠깐 두고, 돌아오는 즉시
 *   지운다. localStorage 에는 넣지 않는다.
 */
const KEEP = "signup-form";

export default function Signup() {
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  const [f, setF] = useState({
    name: "", birth: "", sex: "", phone: "",
    username: "", pw: "", pw2: "",
  });
  const [token, setToken] = useState(null);   // ① 이 준 표
  const [idOk, setIdOk] = useState(null);     // 아이디 중복 확인 결과
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);

  const set = (k) => (e) => {
    setF({ ...f, [k]: e.target.value });
    if (k === "username") setIdOk(null);      // 고치면 확인이 무효다
  };
  const digits = (k) => (e) =>
    setF({ ...f, [k]: e.target.value.replace(/\D/g, "") });

  const ok1 = f.name.trim() && f.birth && f.sex && f.phone.length >= 10;
  const ok3 = f.username.length >= 4 && f.pw.length >= 8 && f.pw === f.pw2;

  /* 서버가 포트원에 다시 묻고 입력값과 대조한다. 다르면 거절이 온다. */
  async function confirm(ivid, form) {
    setBusy(true); setErr(null);
    try {
      const r = await api.identity({
        identity_verification_id: ivid,
        name: form.name.trim(), birth_date: form.birth,
        sex: form.sex, phone: form.phone,
      });
      setToken(r.verify_token);
      setMsg(r.detail);
      setStep(2);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  /* 리다이렉트로 돌아온 경우. 결과는 주소 뒤에 붙어 오고, 입력값은
     sessionStorage 에서 되찾는다. */
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    const ivid = q.get("identityVerificationId");
    if (!ivid) return;
    let saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(KEEP)); sessionStorage.removeItem(KEEP); }
    catch { /* 못 읽으면 처음부터 */ }
    history.replaceState(null, "", location.pathname);
    if (!saved) return;
    setF((v) => ({ ...v, ...saved }));
    if (q.get("code")) setErr({ code: q.get("code"), detail: q.get("message") });
    else confirm(ivid, saved);
  }, []);

  async function verifyIdentity(e) {
    e.preventDefault();
    setErr(null);
    const ivid = `iv-${crypto.randomUUID()}`;
    const form = { name: f.name, birth: f.birth, sex: f.sex, phone: f.phone };
    try { sessionStorage.setItem(KEEP, JSON.stringify(form)); } catch { /* 없어도 PC 는 된다 */ }
    let r;
    try {
      r = await PortOne.requestIdentityVerification({
        storeId: import.meta.env.VITE_PORTONE_STORE_ID,
        channelKey: import.meta.env.VITE_PORTONE_CHANNEL_KEY,
        identityVerificationId: ivid,
        redirectUrl: `${location.origin}/signup`,
        bypass: { inicisUnified: { flgFixedUser: "N" } },
      });
    } catch (e2) {
      r = { code: "SDK", message: e2?.message || "본인인증 창을 열지 못했습니다" };
    }
    // 여기까지 오면 리다이렉트가 아니라 반환값 방식(PC)이다
    try { sessionStorage.removeItem(KEEP); } catch { /* 무시 */ }
    if (!r || r.code !== undefined) {
      setErr({ code: r?.code || "취소", detail: r?.message || "본인인증을 마치지 못했습니다" });
      return;
    }
    confirm(ivid, form);
  }

  async function checkId() {
    setBusy(true); setErr(null);
    try {
      const r = await api.checkId(f.username);
      setIdOk(r);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  async function finish(e) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.signup({
        verify_token: token,
        username: f.username,
        password: f.pw,
      });
      // 가입이 끝나면 그대로 로그인 상태다. 다시 로그인시키지 않는다.
      nav("/", { replace: true });
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  return (
    <>
      <Head title="가입" up="/login" />
      <div className="pane">
        <Steps at={step} />

        {step === 1 && (
          <form className="form" onSubmit={verifyIdentity}>
            <p className="note">
              병원 기록과 이어 드립니다. 입력하신 정보는 <b>본인인증 결과와
              같아야</b> 가입됩니다.
            </p>

            <label className="field">
              <span>이름</span>
              <input value={f.name} onChange={set("name")}
                     autoComplete="name" disabled={busy} />
            </label>

            <label className="field">
              <span>생년월일</span>
              <input type="date" value={f.birth} onChange={set("birth")}
                     autoComplete="bday" disabled={busy} />
            </label>

            <div className="field">
              <span>성별</span>
              <div className="rrn">
                {[["female", "여"], ["male", "남"]].map(([v, t]) => (
                  <button key={v} type="button" disabled={busy}
                          aria-pressed={f.sex === v}
                          className={`btn narrow ${f.sex === v ? "" : "ghost"}`}
                          onClick={() => setF({ ...f, sex: v })}>{t}</button>
                ))}
              </div>
            </div>

            <label className="field">
              <span>휴대폰 번호</span>
              <input value={f.phone} onChange={digits("phone")}
                     inputMode="tel" autoComplete="tel" maxLength={11}
                     placeholder="01012345678" disabled={busy} />
            </label>

            {err && <Err e={err} />}

            <button className="btn" type="submit" disabled={!ok1 || busy}>
              {busy ? "확인 중…" : "본인인증 하기"}
            </button>
          </form>
        )}

        {step === 2 && (
          <form className="form" onSubmit={finish}>
            {msg && <div className="card accent"><span className="s">{msg}</span></div>}
            <p className="note">
              <b>{f.name}</b> 님, 확인됐습니다. 앞으로 쓰실 아이디와 비밀번호를
              정해 주세요.
            </p>

            <div className="field">
              <span>아이디</span>
              <div className="rrn">
                <input value={f.username} onChange={set("username")}
                       autoComplete="username" autoCapitalize="off"
                       placeholder="영문 · 숫자 4자 이상" disabled={busy} />
                <button className="btn ghost narrow" type="button"
                        disabled={f.username.length < 4 || busy}
                        onClick={checkId}>
                  중복 확인
                </button>
              </div>
              {idOk && (
                <em>{idOk.available ? idOk.detail : "이미 쓰이고 있는 아이디입니다"}</em>
              )}
            </div>

            <label className="field">
              <span>비밀번호</span>
              <input type="password" value={f.pw} onChange={set("pw")}
                     autoComplete="new-password" disabled={busy} />
              <em>여덟 자 이상</em>
            </label>

            <label className="field">
              <span>비밀번호 확인</span>
              <input type="password" value={f.pw2} onChange={set("pw2")}
                     autoComplete="new-password" disabled={busy} />
              {f.pw2 && f.pw !== f.pw2 && <em>두 번 넣으신 값이 다릅니다</em>}
            </label>

            {err && <Err e={err} />}

            <button className="btn" type="submit"
                    disabled={!ok3 || idOk?.available !== true || busy}>
              {busy ? "가입 중…" : "가입 마치기"}
            </button>
          </form>
        )}
      </div>
    </>
  );
}

/* 지금 어디쯤인지. 끝이 보여야 시작한다. */
function Steps({ at }) {
  const names = ["본인 확인", "아이디 정하기"];
  return (
    <ol className="steps">
      {names.map((n, i) => (
        <li key={n} className={i + 1 === at ? "on" : i + 1 < at ? "done" : ""}>
          <b>{i + 1}</b>{n}
        </li>
      ))}
    </ol>
  );
}

function Err({ e }) {
  return (
    <div className="card flag">
      <span className="k">{e.code || "오류"}</span>
      <span className="s">{e.detail || e.message}</span>
    </div>
  );
}
