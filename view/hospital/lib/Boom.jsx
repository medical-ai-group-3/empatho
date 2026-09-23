import { Component } from "react";

const RELOADED = "empatho.stale-chunk-reloaded";

/* 배포로 사라진 조각 파일을 부른 것인가. 브라우저마다 문구가 달라
   모두 잡는다 — Chrome 「Failed to fetch dynamically imported module」,
   Firefox 「error loading dynamically imported module」,
   Safari 「Importing a module script failed」. */
function isStaleChunk(err) {
  const m = String(err?.message ?? err);
  return /dynamically imported module|Importing a module script failed/i.test(m);
}

/* 오류 그물.
 *
 * 화면 하나가 그리다가 터지면 React 는 **트리를 통째로 내린다.** 그러면
 * 상단바까지 사라지고 하얀 화면만 남아서, 쓰는 사람은 뒤로 갈 수조차
 * 없다. 환자 앱에서 실제로 났던 사고다.
 *
 * 여기서 받아 두면 터진 자리만 메시지로 바뀌고 나머지는 남는다.
 */
export default class Boom extends Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err, info) {
    /* 개발 중에는 콘솔에 남겨야 어디서 터졌는지 찾는다 */
    console.error("화면이 그리다가 멈췄습니다", err, info);

    /* 배포하면 옛 조각 파일이 지워진다. 화면을 열어 둔 사람의 브라우저는
       옛 이름을 계속 부르고, nginx 는 없는 파일에 404 대신 index 를
       200 으로 돌려준다 — JS 자리에 HTML 이 와서 import 가 거부된다.
       다시 그려도 같은 이름을 또 부르니 영영 안 풀린다. 새로 받아야
       한다(index 는 no-store 라 새로고침이면 확실히 바뀐다).
       한 번만 한다 — 진짜 고장이면 되풀이가 되어 더 나쁘다. */
    if (isStaleChunk(err) && !sessionStorage.getItem(RELOADED)) {
      sessionStorage.setItem(RELOADED, "1");
      window.location.reload();
    }
  }

  render() {
    if (!this.state.err) return this.props.children;

    const stale = isStaleChunk(this.state.err);
    return (
      <div className="boot">
        <b>화면을 그리다가 멈췄습니다</b>
        <span>{stale
          ? "새로 배포되어 이 화면의 파일이 바뀌었습니다. 새로고침하면 열립니다."
          : String(this.state.err?.message ?? this.state.err)}</span>
        <button className="btn line"
                onClick={() => (stale
                  ? window.location.reload()
                  : this.setState({ err: null }))}>
          {stale ? "새로 받기" : "다시 그리기"}
        </button>
        <span className="muted small">
          같은 자리에서 반복되면 이 메시지를 그대로 알려 주세요.
        </span>
      </div>
    );
  }
}
