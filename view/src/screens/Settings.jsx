import { useNavigate } from "react-router-dom";
import { SCALES, useScale, useTheme } from "../lib/theme";
import { Head } from "../lib/Screen";
import { clearSeen, COACH_HOME } from "../lib/seen";

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

export default function Settings() {
  return (
    <>
      <Head title="설정" />
      <Inner />
    </>
  );
}

function Inner() {
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const [scale, setScale] = useScale();
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
        <span className="k">알림 수신 설정</span>
        <span className="s">
          알림 종류별 수신 설정은 준비 중입니다. 새 알림은 알림 목록에서 확인할 수 있습니다.
        </span>
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
