import { Component } from "react";

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
  }

  render() {
    if (!this.state.err) return this.props.children;

    return (
      <div className="boot">
        <b>화면을 그리다가 멈췄습니다</b>
        <span>{String(this.state.err?.message ?? this.state.err)}</span>
        <button className="btn line" onClick={() => this.setState({ err: null })}>
          다시 그리기
        </button>
        <span className="muted small">
          같은 자리에서 반복되면 이 메시지를 그대로 알려 주세요.
        </span>
      </div>
    );
  }
}
