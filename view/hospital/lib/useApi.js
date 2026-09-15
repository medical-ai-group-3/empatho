import { useCallback, useEffect, useState } from "react";

/* 서버를 부르고 세 가지 상태를 돌려준다 — 부르는 중 · 오류 · 자료.
 *
 * ⚠ **자료가 오기 전에 자료를 읽지 말 것.** 화면에서 반드시
 *   {data && <Inner d={data} />} 로 막는다. 안 막으면 첫 그림에서
 *   터지고, React 가 트리를 통째로 내려 빈 화면만 남는다.
 *   환자 앱에서 실제로 났던 사고다.
 */
export function useApi(fn, deps = []) {
  const [state, set] = useState({ loading: true, data: null, error: null });
  const run = useCallback(() => {
    let live = true;
    set((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (d) => live && set({ loading: false, data: d, error: null }),
      (e) => live && set({ loading: false, data: null, error: e }),
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);
  return { ...state, reload: run };
}
