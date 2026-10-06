import { useEffect, useState } from "react";
import { getMe, setMe, subscribeMe } from "../perm";
import { me as fetchMe } from "../api";

/* 로그인한 사람을 화면에서 읽는 자리.
 *
 * perm.js 가 값을 들고 있고, 여기서는 그것이 바뀔 때 다시 그리게만 한다.
 * 화면은 대부분 can() 만 쓰면 되고, 이름·직책을 찍을 때만 이걸 쓴다.
 */
export function useMe() {
  const [v, set] = useState(getMe);
  useEffect(() => subscribeMe(set), []);
  return v;
}

/* 앱이 켜질 때 한 번 부른다 — perms 가 여기 실려 온다.
 *
 * ⚠ 응답이 오기 전에는 can() 이 전부 false 다. 잠깐 버튼이 없다가
 *   생기는 편이, 눌러 놓고 403 을 맞는 것보다 낫다.
 */
export function useLoadMe() {
  const [state, setState] = useState({ loading: true, error: null });

  useEffect(() => {
    let live = true;
    fetchMe().then(
      (d) => { if (live) { setMe(d); setState({ loading: false, error: null }); } },
      (e) => { if (live) setState({ loading: false, error: e }); },
    );
    return () => { live = false; };
  }, []);

  return state;
}
