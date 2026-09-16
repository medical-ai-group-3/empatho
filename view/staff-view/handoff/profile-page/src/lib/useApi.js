import { useEffect, useState } from "react";

/* 서버에서 받아오는 동안의 세 상태를 한 곳에서 다룬다. empatho-view와 동일.
 *   const { loading, data, error, reload } = useApi(() => api.waitingPatients());
 * deps 가 바뀌면 다시 부른다. 화면을 떠나면 결과를 버린다(alive). */
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
