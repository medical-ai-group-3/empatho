import { Component } from "react";

/* 화면이 터졌을 때 **하얀 화면 대신** 무언가를 남긴다.
 *
 * React 는 그리는 도중에 오류가 나면 트리를 통째로 내린다. 머리말도
 * 뒤로가기도 같이 사라져서 아무것도 없는 흰 판만 남는다 — 쓰는 사람은
 * «앱이 죽었다»고 밖에 못 읽고, 돌아갈 단추도 없다.
 *
 * 이 부품이 그것을 받아 낸다. 고쳐 주지는 않는다. **나갈 길을 남기는
 * 것**이 하는 일의 전부다 — 다시 불러오기 · 홈으로.
 *
 * ⚠ 이건 class 로 써야 한다. 오류를 받아 내는 자리(componentDidCatch ·
 *   getDerivedStateFromError)는 함수 부품에 없다. 앱에서 class 는 여기
 *   하나뿐이고, 이유가 이것이다.
 *
 * 시연 중에 어디가 터져도 화면이 하얗게 되지는 않는다. 그래도 터진
 * 것은 터진 것이라, 오류 글은 그대로 보여준다 — 우리가 봐야 고친다.
 */
export default class Boom extends Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  render() {
    const { err } = this.state;
    if (!err) return this.props.children;

    return (
      <div className="app">
        <div className="screens">
          <div className="top">
            <h2>화면을 열지 못했습니다</h2>
          </div>
          <div className="pane">
            <div className="card flag">
              <span className="k">화면 오류</span>
              <span className="s">{String(err.message || err)}</span>
            </div>

            {/* 새로고침이다. 앱 안에서 되돌리는 것이 아니라 **처음부터
                다시 세운다** — 무엇이 망가졌는지 모르는 상태라 반쯤
                살아 있는 화면을 이어 쓰게 두면 안 된다 */}
            <button
              className="btn"
              onClick={() => window.location.reload()}
            >
              다시 불러오기
            </button>

            {/* Link 가 아니라 a 다. 라우터까지 망가졌을 수 있어서, 주소를
                통째로 다시 여는 쪽이 확실하다 */}
            <a className="btn ghost" href="/">홈으로</a>

            <p className="note">
              같은 화면에서 계속 이러면 접수처에 알려 주세요.
            </p>
          </div>
        </div>
      </div>
    );
  }
}
