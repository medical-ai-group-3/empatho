import { useEffect, useState } from "react";

/* 서버에서 받아오는 동안의 세 상태를 한 곳에서 다룬다.
 *
 * 화면마다 로딩·오류를 따로 쓰면 열 개가 조금씩 달라진다. 여기 하나로
 * 모아 두면 «판독이 오래 걸립니다» 같은 문구도 한 자리에서 바뀐다.
 *
 *   const { loading, data, error, reload } = useApi(() => api.results());
 *
 * deps 가 바뀌면 다시 부른다. 화면을 떠나면 결과를 버린다(alive) —
 * 안 그러면 사라진 화면에 setState 를 해서 경고가 뜬다.
 */
export function useApi(loader, deps = []) {
  const [s, setS] = useState({ loading: true, data: null, error: null });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    setS({ loading: true, data: null, error: null });
    loader()
      .then((d) => { if (alive) setS({ loading: false, data: d, error: null }); })
      .catch((e) => { if (alive) setS({ loading: false, data: null, error: e }); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  return { ...s, reload: () => setNonce((v) => v + 1) };
}
