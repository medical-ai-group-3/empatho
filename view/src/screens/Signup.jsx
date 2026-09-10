import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { Head } from "../lib/Screen";

/* 02 · 가입
 *
 * **아이디는 본인이 정한다.** 병원 기록과 잇는 것은 주민등록번호다 —
 * 병원이 그 고유번호로 이미 있는 환자를 찾아 준다. 그래서 병원코드도,
 * 환자번호도 묻지 않는다. 환자가 알 수 없는 값이다.
 *
 * 세 걸음이다.
 *   ① 본인 확인   이름 · 주민등록번호 · 휴대폰 → 인증번호를 보낸다
 *   ② 인증번호     맞으면 verify_token 을 받는다
 *   ③ 아이디 정하기 그 표를 들고 가입을 마친다
 *
 * 걸음을 나눈 이유 — 번호가 맞는지도 모르는 채로 아이디를 궁리하게 하면,
 * 마지막에 틀렸다는 말을 듣고 처음부터 다시 해야 한다.
 *
 * ⚠ 주민등록번호를 다루는 화면이다. 지키는 것 셋.
 *
 *   · **저장하지 않는다.** 화면 상태에만 있고, ①을 보내는 즉시 지운다.
 *     localStorage · sessionStorage 에 넣지 않는다
 *   · 뒷자리는 가린다. 어깨너머로 보이면 안 된다
 *   · 다시 화면에 띄우지 않는다. ②·③ 으로 넘어가면 그 칸은 사라진다
 */
export default function Signup() {
  const nav = useNavigate();
  const [step, setStep] = useState(1);

  // rrn2(뒷자리)는 여기 잠깐 머물다 ① 을 보내면 지워진다
  const [f, setF] = useState({
    name: "", rrn1: "", rrn2: "", phone: "",
    code: "", username: "", pw: "", pw2: "",
  });
  const [token, setToken] = useState(null);   // ② 가 준 표
  const [idOk, setIdOk] = useState(null);     // 아이디 중복 확인 결과
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [msg, setMsg] = useState(null);
  const [left, setLeft] = useState(0);

  const set = (k) => (e) => {
    setF({ ...f, [k]: e.target.value });
    if (k === "username") setIdOk(null);      // 고치면 확인이 무효다
  };
  const digits = (k) => (e) =>
    setF({ ...f, [k]: e.target.value.replace(/\D/g, "") });

  /* 인증번호 유효시간. 남은 시간을 안 보여주면 번호가 이미 죽었는지
     아직 사는지 알 길이 없다. */
  useEffect(() => {
    if (left <= 0) return;
    const t = setTimeout(() => setLeft(left - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);

  const ok1 = f.name.trim() && f.rrn1.length === 6 && f.rrn2.length === 7
              && f.phone.length >= 10;
  const ok3 = f.username.length >= 4 && f.pw.length >= 8 && f.pw === f.pw2;

  async function sendCode(e) {
    e.preventDefault();
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api.sendCode({
        name: f.name.trim(),
        rrn: f.rrn1 + f.rrn2,
        phone: f.phone,
      });
      // 보내자마자 지운다. 이 뒤로는 앱 어디에도 남지 않는다.
      setF((v) => ({ ...v, rrn1: "", rrn2: "" }));
      setLeft(r.expires_in_sec || 180);
      setMsg(r.detail || "인증번호를 보냈습니다");
      setStep(2);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
  }

  async function verify(e) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api.verifyCode({ phone: f.phone, code: f.code });
      setToken(r.verify_token);
      setMsg(r.detail || "본인 확인이 끝났습니다");
      setStep(3);
    } catch (e2) { setErr(e2); } finally { setBusy(false); }
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
          <form className="form" onSubmit={sendCode}>
            <p className="note">
              병원에 있는 기록과 이어 드립니다. 주민등록번호는 <b>확인에만
              쓰이고 앱에 저장되지 않습니다.</b>
            </p>

            <label className="field">
              <span>이름</span>
              <input value={f.name} onChange={set("name")}
                     autoComplete="name" disabled={busy} />
            </label>

            <div className="field">
              <span>주민등록번호</span>
              <div className="rrn">
                <input value={f.rrn1} onChange={digits("rrn1")}
                       inputMode="numeric" maxLength={6}
                       aria-label="주민등록번호 앞 여섯 자리" disabled={busy} />
                <i className="sep" aria-hidden="true">–</i>
                <input type="password" value={f.rrn2} onChange={digits("rrn2")}
                       inputMode="numeric" maxLength={7}
                       aria-label="주민등록번호 뒤 일곱 자리" disabled={busy} />
              </div>
              <em>뒷자리는 가려집니다</em>
            </div>

            <label className="field">
              <span>휴대폰 번호</span>
              <input value={f.phone} onChange={digits("phone")}
                     inputMode="tel" autoComplete="tel" maxLength={11}
                     placeholder="01012345678" disabled={busy} />
            </label>

            {err && <Err e={err} />}

            <button className="btn" type="submit" disabled={!ok1 || busy}>
              {busy ? "보내는 중…" : "인증번호 받기"}
            </button>
          </form>
        )}

        {step === 2 && (
          <form className="form" onSubmit={verify}>
            {msg && <div className="card accent"><span className="s">{msg}</span></div>}

            <label className="field">
              <span>인증번호</span>
              <input className="code" value={f.code} onChange={digits("code")}
                     inputMode="numeric" maxLength={6}
                     autoComplete="one-time-code" disabled={busy} />
              <em>
                {left > 0
                  ? `남은 시간 ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`
                  : "시간이 지났습니다. 처음부터 다시 해 주세요"}
              </em>
            </label>

            {err && <Err e={err} />}

            <button className="btn" type="submit"
                    disabled={f.code.length < 4 || left <= 0 || busy}>
              {busy ? "확인 중…" : "확인"}
            </button>
            <button className="btn ghost" type="button" disabled={busy}
                    onClick={() => { setStep(1); setErr(null); setLeft(0); }}>
              처음부터 다시
            </button>
          </form>
        )}

        {step === 3 && (
          <form className="form" onSubmit={finish}>
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

/* 지금 어디쯤인지. 세 걸음이라 끝이 보여야 시작한다. */
function Steps({ at }) {
  const names = ["본인 확인", "인증번호", "아이디 정하기"];
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
