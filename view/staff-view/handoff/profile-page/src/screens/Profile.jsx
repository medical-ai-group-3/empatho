import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Head, Body } from "../lib/Screen";

/* 내 정보 · 설정 ("/me") — 상단바 우측 프로필 칩에서 들어온다.
 * 의사 개인정보 수정 + 알림 설정 + 로그아웃. 과 화면이 아니라 계정
 * 전체에 걸친 화면이라 depts/ 밑이 아니라 screens/ 에 둔다(과가 늘어도
 * 이 화면은 하나만 있으면 된다). */
export default function Profile() {
  const nav = useNavigate();
  const { loading, data: me, error, reload } = useApi(() => api.me());

  return (
    <>
      <Head title="내 정보" sub="프로필 · 알림 설정 · 로그아웃" back={() => nav("/")} />
      <div className="pane">
        <Body loading={loading} error={error} onRetry={reload}>
          {me && <Inner me={me} />}
        </Body>
      </div>
    </>
  );
}

function Inner({ me }) {
  return (
    <div className="cols2">
      <ProfileCard me={me} />
      <div>
        <NotifyCard me={me} />
        <AccountCard me={me} />
      </div>
    </div>
  );
}

function ProfileCard({ me }) {
  const [name, setName] = useState(me.name);
  const [email, setEmail] = useState(me.email);
  const [phone, setPhone] = useState(me.phone);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save() {
    setSaving(true);
    try {
      await api.updateMe({ name, email, phone });
      setMsg("저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3>프로필</h3>
      <div className="pt-head" style={{ marginTop: 4, marginBottom: 16 }}>
        <span className="avatar" aria-hidden="true">{name[0]}</span>
        <span>
          <span className="name">{name}</span>
          <p className="sub">{me.hospital} · {me.dept} · {me.role}</p>
        </span>
      </div>

      <div className="field">
        <label>이름</label>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field">
        <label>소속</label>
        <input value={`${me.hospital} · ${me.dept}`} disabled />
      </div>
      <div className="field">
        <label>사번</label>
        <input value={me.staff_id} disabled />
      </div>
      <div className="field">
        <label>이메일</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div className="field">
        <label>연락처</label>
        <input value={phone} onChange={(e) => setPhone(e.target.value)} />
      </div>

      <div className="card-foot split">
        <span className="note">{msg}</span>
        <button className="btn ghost" onClick={save} disabled={saving}>
          {saving ? "저장 중…" : "저장"}
        </button>
      </div>
    </div>
  );
}

function NotifyCard({ me }) {
  const [discordance, setDiscordance] = useState(me.notify_discordance);
  const [specimen, setSpecimen] = useState(me.notify_specimen);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState(null);

  async function save(next) {
    setSaving(true);
    try {
      await api.updateMe(next);
      setMsg("알림 설정이 저장되었습니다");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <h3>알림 설정</h3>
      <label className="check-row">
        <input type="checkbox" checked={discordance}
          onChange={(e) => { setDiscordance(e.target.checked); save({ notify_discordance: e.target.checked }); }} />
        영상/병리 불일치 발생 시 알림
      </label>
      <label className="check-row">
        <input type="checkbox" checked={specimen}
          onChange={(e) => { setSpecimen(e.target.checked); save({ notify_specimen: e.target.checked }); }} />
        검체 등록 완료 시 알림
      </label>
      {msg && <p className="note" style={{ marginTop: 4 }}>{saving ? "저장 중…" : msg}</p>}
    </div>
  );
}

function AccountCard() {
  const [state, setState] = useState("idle"); // idle | working | done
  const [err, setErr] = useState(null);

  async function logout() {
    setState("working");
    setErr(null);
    try {
      await api.logout();
      setState("done");
    } catch (e) {
      setErr(e.detail || e.message);
      setState("idle");
    }
  }

  if (state === "done") {
    return (
      <div className="card">
        <h3>계정</h3>
        <p style={{ fontSize: 13.5, color: "var(--ok)" }}>로그아웃되었습니다. 창을 닫아 주세요.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h3>계정</h3>
      <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 12 }}>
        이 기기에서 로그아웃합니다.
      </p>
      {err && <p className="field err">{err}</p>}
      <button className="btn ghost" onClick={logout} disabled={state === "working"}>
        {state === "working" ? "로그아웃 중…" : "로그아웃"}
      </button>
    </div>
  );
}
