import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Capacitor } from "@capacitor/core";
import { PushNotifications } from "@capacitor/push-notifications";
import { api } from "../api";
import { SCALES, useScale, useTheme } from "../lib/theme";
import { Head } from "../lib/Screen";
import { clearSeen, COACH_HOME } from "../lib/seen";
import Switch from "../lib/Switch";

/* 11 · 설정
 *
 * 「내 정보」에서 갈라 나왔다. 둘은 성격이 다르다.
 *
 *   내 정보  나와 병원 사이의 것 — 이름 · 환자번호 · 담당 주치의
 *   설정     이 기기에서 앱이 어떻게 보이고 울릴지
 *
 * 앞의 것은 병원이 갖고 있는 자료라 앱에서 못 고친다. 뒤의 것은 언제든
 * 바꿔도 되는 것이다. 한 화면에 두면 「이건 고쳐도 되나」가 헷갈린다.
 *
 * 홈 머리말의 톱니에서 온다. 아래 탭에는 없다 — 매일 누를 것이 아니다.
 */
const THEMES = [
  { id: "system", label: "기기 설정" },
  { id: "light",  label: "라이트 모드" },
  { id: "dark",   label: "다크 모드" },
];

/* 알림 켜짐/꺼짐. **진짜 스위치는 서버의 push_token 이다** — 토큰이 있는
 * 계정에만 서버가 푸시를 보낸다(empatho-app core/delivery.py).
 *
 *   켜기  기기를 FCM 에 등록해 받은 토큰을 서버에 올린다
 *   끄기  서버의 토큰을 비운다
 *
 * 켜짐 여부는 이 기기에 적어 둔다(PUSH_KEY). 서버에 토큰을 묻는 자리가 없고,
 * 알림은 기기마다 켜고 끄는 것이라 그걸로 충분하다.
 * 웹에서는 기기 등록을 못 해서 스위치를 잠근다.
 */
const PUSH_KEY = "push-on";
const NATIVE = Capacitor.isNativePlatform();

function readPush() {
  try { return localStorage.getItem(PUSH_KEY) === "1"; } catch { return false; }
}

async function deviceToken() {
  const p = await PushNotifications.requestPermissions();
  if (p.receive !== "granted") {
    throw new Error("휴대폰 설정에서 EMPATHO 알림을 허용해 주세요");
  }
  try {
    return await new Promise((ok, no) => {
      PushNotifications.addListener("registration", (t) => ok(t.value));
      PushNotifications.addListener("registrationError", (e) => no(new Error(e.error)));
      PushNotifications.register();
    });
  } finally {
    await PushNotifications.removeAllListeners();
  }
}

export default function Settings() {
  return (
    <>
      <Head title="설정" />
      <div className="pane settings">
        <Inner />
      </div>
    </>
  );
}

function Inner() {
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const [scale, setScale] = useScale();
  const [push, setPush] = useState(readPush);
  const [pushBusy, setPushBusy] = useState(false);
  const [pushErr, setPushErr] = useState(null);

  async function togglePush(on) {
    setPushBusy(true); setPushErr(null);
    try {
      await api.registerPushToken(on ? await deviceToken() : "");
      setPush(on);
      try { localStorage.setItem(PUSH_KEY, on ? "1" : "0"); } catch { /* 이 기기에서만 잊는다 */ }
    } catch (e) {
      setPushErr(e.detail || e.message || "알림 설정을 바꾸지 못했습니다");
    } finally { setPushBusy(false); }
  }

  function replayGuide() {
    clearSeen(COACH_HOME);
    navigate("/");
  }

  return (
    <>
      <h3 className="sec">테마</h3>
      <div className="card">
        <div className="seg" role="radiogroup" aria-label="테마">
          {THEMES.map((t) => (
            <button key={t.id} type="button" role="radio"
                    aria-checked={theme === t.id}
                    className={theme === t.id ? "on" : undefined}
                    onClick={() => setTheme(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <span className="s">기기 설정은 휴대폰의 라이트·다크 모드를 따라갑니다.</span>
      </div>

      <h3 className="sec">글씨 크기</h3>
      <div className="card">
        <div className="seg" role="radiogroup" aria-label="글씨 크기">
          {SCALES.map((s) => (
            <button key={s.v} type="button" role="radio"
                    aria-checked={scale === s.v}
                    className={scale === s.v ? "on" : undefined}
                    onClick={() => setScale(s.v)}>
              {s.label}
            </button>
          ))}
        </div>
        {/* 고르는 즉시 이 문장부터 커진다. 「적용」 단추를 두면 바뀐 모습을
            못 보고 결정해야 한다 */}
        <span className="s">고르시면 앱 전체 글씨가 바로 바뀝니다.</span>
      </div>

      <h3 className="sec">알림</h3>
      <div className="card">
        <div className="row-sw">
          <span className="k">알림 받기</span>
          <Switch on={push} onChange={togglePush} label="알림 받기"
                  disabled={!NATIVE || pushBusy} />
        </div>
        <span className="s">
          {NATIVE
            ? "검사 결과 · 예약 · 복약 알림을 휴대폰으로 받습니다. 알림 목록에는 꺼 두어도 쌓입니다."
            : "알림은 휴대폰 앱에서만 켜고 끌 수 있습니다."}
        </span>
        {pushErr && <span className="s err">{pushErr}</span>}
      </div>

      <h3 className="sec">도움말</h3>
      <div className="card">
        <span className="k">앱 사용법</span>
        <span className="s">틸리가 주요 기능을 다시 안내해 드립니다.</span>
        <button className="btn ghost" type="button" onClick={replayGuide}>
          앱 사용법 다시 보기
        </button>
      </div>

      <p className="note">
        화면 설정은 이 기기에만 적용됩니다.
      </p>
    </>
  );
}
