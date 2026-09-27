import { useCallback, useEffect, useRef, useState } from 'react';
import './EmpathoLogin.css';
import { HOSPITAL, PRODUCT } from '../../nav';

/* ══════════════════════════════════════════════════════════════
   EMPATHO — 로그인 워크스루 전환 (React)

   실사 클립 한 컷에 문 열림부터 상담실이 드러나는 데까지 담겨 있고,
   이 컴포넌트는 재생 속도와 "언제 흰 화면으로 덮을지"만 정합니다.
   확대 보정은 걸지 않습니다.
   ══════════════════════════════════════════════════════════════

   ── 이 저장소로 들여오면서 고친 것 ────────────────────────────
   바깥 상자와 전환은 원본 그대로 두고 **패널 안쪽 내용만** 우리 것으로
   갈았다. 원본은 이메일·비밀번호를 받는 일반 로그인이고, 우리는 직원
   아이디를 받는다.

     Email          →  아이디 (type=text). 사번·아이디 계정이라
                       type=email 이면 브라우저 검증에서 막힌다
     minLength 8    →  뺐다. 길이 규칙은 서버가 정한다
     Keep me signed in → 뺐다. signIn({access}) 에 그 개념이 없다
     Forgot password?  →  「회원가입 신청」. 재설정 경로가 아직 없다
     Sign In        →  로그인
     Welcome back   →  환영합니다, ○○님
     (없던 것)      →  Caps Lock 알림. 비밀번호를 대문자로 계속
                       틀리는 것을 잡아 주던 자리라 옮겨 왔다

   `EmpathoLogin.css` 가 원본이다 (자동 생성 아님).
   ══════════════════════════════════════════════════════════════ */

/* 로그인 박스가 화면 밖으로 쓸려 나가는 시간.
   EmpathoLogin.css 의 `.is-entering .panel` transition 과 같은 값입니다. */
const PANEL_EXIT_MS = 1150;

/* 아래 세 값이 전환의 전부입니다. 클립을 바꾸면 여기만 조정하세요. */
const CLIP_RATE   = 1.30;   /* 재생 속도 — 5.04s 클립이 약 3.9s 가 됩니다 */
const PANEL_EXIT  = 0.42;   /* 이 진행률에서 로그인 패널이 비켜납니다 */
const VEIL_AT_END = 1.15;   /* 클립이 끝나기 몇 초 전에 덮을지 (클립 시간) */

const VEIL_MS  = 900;       /* EmpathoLogin.css 의 --veil-ms 와 같은 값 */
const DOLLY_MS = 1750;      /* --dolly-ms 와 같은 값 (폴백 확대 전용) */
const GUARD_MS = 9000;      /* 영상이 끝내 준비되지 않을 때의 탈출구 */

const DEFAULT_ASSETS = {
  clip:      '/empatho/consult-walkthrough.mp4',
  clipSmall: '/empatho/consult-walkthrough-720.mp4',
  poster:    '/empatho/door-poster.jpg',
  openStill: '/empatho/door-open.jpg',
};

const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

export default function EmpathoLogin({
  /** 회원가입 신청으로 보내는 손잡이. 없으면 그 줄이 안 나온다 */
  onSignup,
  /** 실제 인증. 실패 시 throw 하면 메시지가 그대로 표시됩니다.
   *  넘기지 않으면 데모 모드로 동작합니다(연출만 시연). */
  onAuthenticate,
  /** 전환이 끝난 시점에 호출됩니다. 여기서 라우팅하세요.
   *  예: () => navigate('/dashboard') */
  onEnter,
  /** 자산 경로. public/ 아래에 두고 절대 경로로 넘기는 게 가장 간단합니다. */
  assets = DEFAULT_ASSETS,
  /** 전환 화면의 「환영합니다, ○○님」에 쓸 이름. 없으면 「환영합니다」만 */
  userName = '',
  /** 화면에 DEMO 배지를 띄울지 */
  showDemoBadge = true,
  /** 'full' = 영상이 화면 전체, 로그인 박스는 그 위 유리 패널 (권장)
   *  'split' = 영상 왼쪽 58%, 로그인 박스는 오른쪽 불투명 패널.
   *  분할에서는 인증 성공 시 영상이 패널을 밀어내고 화면을 차지합니다. */
  layout = 'full',
}) {
  const sceneRef = useRef(null);
  const videoRef = useRef(null);

  /* 전환 단계는 상태로 두되, 언마운트 이후 갱신을 막기 위해 ref 로 함께 추적 */
  const [phase, setPhase] = useState({
    opening: false, entering: false, leaving: false, fallback: false,
  });
  const aliveRef = useRef(true);
  const busyRef = useRef(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reveal, setReveal] = useState(false);
  /* Caps Lock 이 켜졌는지 — 원본에 없던 상태다(우리 옛 로그인에서 옮겨 왔다) */
  const [capsOn, setCapsOn] = useState(false);

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  /* 누를 때마다 지금 상태를 본다. keydown·keyup 둘 다 걸어야 Shift 로
     대문자 한 글자만 친 경우와 안 섞인다 */
  function checkCaps(e) {
    if (typeof e.getModifierState === 'function') {
      setCapsOn(e.getModifierState('CapsLock'));
    }
  }

  const mark = useCallback(patch => {
    if (aliveRef.current) setPhase(prev => ({ ...prev, ...patch }));
  }, []);

  /* ── 인증 ───────────────────────────────────────────────── */

  const authenticate = useCallback(async (loginId, password) => {
    if (!onAuthenticate) { await wait(320); return; }   /* 데모 모드 */
    await onAuthenticate({ loginId, password });
  }, [onAuthenticate]);

  /* ── 전환: 클립이 시계 노릇을 한다 ────────────────────────── */

  const playClip = useCallback(() => new Promise(resolve => {
    const video = videoRef.current;
    const reduceMotion =
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    /* 모션을 줄여 달라는 설정이면 영상을 돌리지 않고 짧게만 덮는다 */
    if (reduceMotion || !video) {
      mark({ fallback: true, leaving: true });
      setTimeout(resolve, 200);
      return;
    }

    let settled = false;
    let panelOut = false;
    let veiled = false;

    const cleanup = () => {
      clearTimeout(guard);
      cancelAnimationFrame(raf);
      video.removeEventListener('timeupdate', tick);
      video.removeEventListener('ended', onEnd);
      video.removeEventListener('error', degrade);
    };

    const finish = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve();
    };

    /* 재생이 막혀도 로그인 흐름은 멈추지 않는다 — 스틸 + 확대로 대체 */
    const degrade = async () => {
      if (settled) return;
      settled = true;
      cleanup();
      mark({ fallback: true, entering: true });
      await wait(DOLLY_MS - 420);
      mark({ leaving: true });
      await wait(VEIL_MS);
      resolve();
    };

    /* 전환 지점 판정은 두 군데서 돌립니다.
       rAF 는 프레임마다 확인해 정확하지만 탭이 가려지면 멈추고,
       timeupdate 는 초당 4번쯤이라 덜 정확하지만 계속 옵니다.
       tick 은 한 번 지난 단계를 다시 실행하지 않으므로 겹쳐도 안전합니다. */
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const { currentTime: t, duration: d } = video;
      if (!d || Number.isNaN(d)) return;

      if (!panelOut && t >= d * PANEL_EXIT) {
        panelOut = true;
        mark({ entering: true });
      }
      if (!veiled && d - t <= VEIL_AT_END) {
        veiled = true;
        mark({ leaving: true });
        /* 흰 화면이 다 덮이면 넘어간다 — 영상 끝을 기다리지 않는다 */
        setTimeout(finish, VEIL_MS);
      }
    };

    const onEnd = () => { mark({ leaving: true }); setTimeout(finish, VEIL_MS); };
    const guard = setTimeout(degrade, GUARD_MS);

    raf = requestAnimationFrame(tick);
    video.addEventListener('timeupdate', tick);
    video.addEventListener('ended', onEnd, { once: true });
    video.addEventListener('error', degrade, { once: true });

    try { video.currentTime = 0; } catch { /* 메타데이터 이전엔 탐색 불가 */ }
    video.playbackRate = CLIP_RATE;
    video.play()?.catch(degrade);
  }), [mark]);

  /* ── 제출 ───────────────────────────────────────────────── */

  const handleSubmit = useCallback(async event => {
    event.preventDefault();
    if (busyRef.current) return;

    const form = event.currentTarget;
    const loginId = form.elements.loginId;
    const password = form.elements.password;

    setError('');
    /* ⚠ **비었는지만 본다.** 길이·모양 규칙은 서버가 정한다 — 화면이
       먼저 막으면 규칙이 두 곳에 생기고, 기존 계정이 못 들어온다 */
    if (!loginId.validity.valid || !password.validity.valid) {
      setError('아이디와 비밀번호를 입력해 주세요.');
      (loginId.validity.valid ? password : loginId).focus();
      return;
    }

    busyRef.current = true;
    setBusy(true);

    try {
      await authenticate(loginId.value.trim(), password.value);
      password.value = '';          /* 성공 후 평문 비밀번호를 남기지 않는다 */

      mark({ opening: true });
      await playClip();

      if (aliveRef.current) onEnter?.();
    } catch (err) {
      busyRef.current = false;
      setBusy(false);
      mark({ opening: false, entering: false, leaving: false, fallback: false });
      videoRef.current?.pause();
      setError(err instanceof Error ? err.message : '로그인을 완료하지 못했습니다.');
    }
  }, [authenticate, playClip, mark, onEnter]);

  const className = [
    'empatho-scene',
    'mode-video',
    phase.opening && 'is-opening',
    phase.entering && 'is-entering',
    phase.leaving && 'is-leaving',
    phase.fallback && 'is-fallback',
  ].filter(Boolean).join(' ');

  return (
    <main className={className} data-layout={layout} ref={sceneRef}>

      <div className="stage">
        <div className="dolly">
          <video
            ref={videoRef}
            className="plate"
            poster={assets.poster}
            preload="auto"
            playsInline
            muted
            aria-hidden="true"
          >
            {/* 폰에서만 가벼운 720p 판본을 내려준다 */}
            <source src={assets.clipSmall} type="video/mp4" media="(max-width: 700px)" />
            <source src={assets.clip} type="video/mp4" />
          </video>
          {/* 영상 재생이 막힌 환경에서만 드러나는 스틸 */}
          <img className="plate plate--still" src={assets.openStill} alt="" aria-hidden="true" />
        </div>
        <div className="bloom" aria-hidden="true" />
      </div>

      <section className="panel" aria-labelledby="empatho-brand">
        <div className="panel__inner">

          <header className="brand">
            {/* 폭에 따라 한 줄/두 줄로 오락가락하지 않게 줄을 고정한다 */}
            <h1 className="brand__mark" id="empatho-brand">
              <span className="brand__hospital">{HOSPITAL}</span>{PRODUCT}
            </h1>
            <p className="brand__tag">의료진용</p>
          </header>

          {!phase.opening && (
            <form className="form" noValidate onSubmit={handleSubmit}>
              <div className="field">
                <label htmlFor="empatho-login-id">아이디</label>
                <div className="control">
                  {/* ⚠ type=text 다. 사번·아이디 계정이라 type=email 이면
                      브라우저가 먼저 막아 로그인 자체가 안 된다 */}
                  <input
                    id="empatho-login-id" name="loginId" type="text"
                    autoComplete="username" placeholder="사번 또는 아이디"
                    maxLength={254} required disabled={busy} autoFocus
                    aria-invalid={error ? 'true' : undefined}
                    onChange={() => error && setError('')}
                  />
                  <svg className="icon" viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="8.5" r="3.6" />
                    <path d="M4.8 19.6a7.4 7.4 0 0 1 14.4 0" />
                  </svg>
                </div>
              </div>

              <div className="field">
                <label htmlFor="empatho-password">비밀번호</label>
                <div className="control">
                  {/* ⚠ minLength 를 뺐다 — 길이 규칙은 서버가 정한다.
                      화면이 8자로 막으면 기존 계정이 못 들어온다 */}
                  <input
                    id="empatho-password" name="password"
                    type={reveal ? 'text' : 'password'}
                    autoComplete="current-password"
                    placeholder="비밀번호" required disabled={busy}
                    aria-invalid={error ? 'true' : undefined}
                    onKeyDown={checkCaps} onKeyUp={checkCaps}
                    onChange={() => error && setError('')}
                  />
                  <button
                    type="button" className="icon icon--btn" disabled={busy}
                    aria-pressed={reveal}
                    aria-label={reveal ? '비밀번호 숨기기' : '비밀번호 표시'}
                    onClick={() => setReveal(v => !v)}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M2.2 12S6 5.6 12 5.6 21.8 12 21.8 12 18 18.4 12 18.4 2.2 12 2.2 12Z" />
                      <circle cx="12" cy="12" r="3.1" />
                      <line className="slash" x1="4" y1="20" x2="20" y2="4" />
                    </svg>
                  </button>
                </div>
              </div>

              {/* Caps Lock 이 켜진 채로 치면 매번 실패하는데 본인은 눈치를
                  못 챈다 — 「아이디 또는 비밀번호가…」만 반복해 보인다.
                  ⚠ 원본에 없던 줄이지만 CSS 는 안 건드렸다. 이미 있는
                    .feedback 을 그대로 쓴다 */}
              {capsOn && (
                <p className="feedback" role="alert">⇪ Caps Lock이 켜져 있습니다.</p>
              )}

              {onSignup && (
                <div className="row">
                  <a
                    className="link" href="#signup"
                    onClick={event => { event.preventDefault(); onSignup(); }}
                  >
                    회원가입 신청
                  </a>
                </div>
              )}

              <p className="feedback" role="alert" aria-live="assertive">{error}</p>

              <button className="submit" type="submit" disabled={busy}>
                <span className="submit__label">{busy ? '확인하는 중…' : '로그인'}</span>
                <svg className="submit__arrow" viewBox="0 0 24 24" aria-hidden="true">
                  <line x1="4" y1="12" x2="19" y2="12" /><path d="m13 6 6 6-6 6" />
                </svg>
              </button>
            </form>
          )}

          {phase.opening && (
            <div className="entering" role="status" aria-live="polite">
              <span className="pulse" aria-hidden="true" />
              <strong>환영합니다{userName ? `, ${userName}님` : ''}</strong>
            </div>
          )}

          {showDemoBadge && (
            <footer className="panel__foot">
              <span className="demo-badge">목업</span>
            </footer>
          )}

        </div>
      </section>

      <div className="veil" aria-hidden="true" />
    </main>
  );
}
