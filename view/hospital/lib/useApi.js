import { useCallback, useEffect, useState } from "react";
import { useLive } from "./refresh";

/* 서버를 부르고 세 가지 상태를 돌려준다 — 부르는 중 · 오류 · 자료.
 *
 * ⚠ **자료가 오기 전에 자료를 읽지 말 것.** 화면에서 반드시
 *   {data && <Inner d={data} />} 로 막는다. 안 막으면 첫 그림에서
 *   터지고, React 가 트리를 통째로 내려 빈 화면만 남는다.
 *   환자 앱에서 실제로 났던 사고다.
 *
 * ── 조용한 다시 부르기 — reload(true) ────────────────────────
 * 그냥 reload() 는 **화면을 「불러오는 중」으로 되돌린다.** 사람이
 * [다시 시도]를 눌렀을 때는 그게 맞다 — 무언가 도는 것이 보여야 한다.
 *
 * 그런데 대기 큐처럼 **몇 초마다 저절로 다시 부르는 자리**에서 그러면,
 * 7초마다 목록이 통째로 사라졌다 돌아온다. 고른 환자의 상세도 같이
 * 내려갔다 다시 올라온다 — 읽던 중에 화면이 깜빡이는 셈이다.
 *
 * reload(true) 는 자료를 그대로 둔 채 뒤에서만 다녀온다. 그 사이에
 * 실패해도 **있던 자료를 지우지 않는다** — 네트워크가 한 번 끊겼다고
 * 보고 있던 큐를 치워 버리면 안 된다.
 */
/* opt.live — 새로고침 없이 따라간다(lib/refresh.js): 이 브라우저에서 무엇이
 * 저장되면 바로, 다른 컴퓨터의 변경은 보이는 동안 주기로. 늘 조용히 부른다.
 * true 면 기본 주기, 숫자면 그 ms. ⚠ 목록 · 대기열 · 판에만 — 입력 양식에는
 * 켜지 않는다(받아 온 값으로 칸을 채우면 쓰던 글을 덮는다) */
export function useApi(fn, deps = [], opt = {}) {
  const [state, set] = useState({ loading: true, data: null, error: null });
  const run = useCallback((quiet) => {
    /* ⚠ **정확히 true 일 때만** 조용하다. reload 를 onClick 에 그대로
       꽂는 자리가 있어서(lib/Body 의 [다시 시도]) 첫 인자로 클릭
       이벤트가 들어온다. truthy 로 보면 그때도 조용해져서, 눌러도
       아무 반응이 없는 단추가 된다 */
    const still = quiet === true;
    let live = true;
    if (!still) set((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (d) => live && set({ loading: false, data: d, error: null }),
      (e) => live && set((s) => (
        still && s.data ? s : { loading: false, data: null, error: e }
      )),
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);
  useLive(() => run(true), typeof opt.live === "number" ? opt.live : undefined, Boolean(opt.live));
  return { ...state, reload: run };
}
