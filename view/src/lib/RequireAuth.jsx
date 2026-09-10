import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { api } from "../api";
import { useApi } from "./useApi";
import { welcomeSeen } from "./seen";
import Splash from "../screens/Splash";

/* 로그인한 사람만 지나간다.
 *
 * 판정은 **서버가 한다.** GET /api/v1/me 가 401 이면 못 들어간다. 앱이
 * localStorage 같은 데 「로그인함」을 적어 두고 그걸 믿으면, 세션이 끝난
 * 뒤에도 화면은 열리고 그 안의 모든 요청이 하나씩 실패한다.
 *
 * 한 번만 묻는다 — 이 부품이 App 을 통째로 감싸므로, 화면을 옮겨 다녀도
 * 다시 묻지 않는다.
 *
 * 어디로 가려던 참이었는지 기억해 뒀다가 로그인 뒤에 그리로 보낸다.
 * 알림 링크로 안내문에 바로 들어왔는데 로그인이 풀려 있으면, 로그인만
 * 하고 홈에 떨궈 놓는 것은 불친절하다.
 */

/* 스플래시가 머무는 최소 시간. 확인이 이보다 빠르면 여기까지 기다린다 —
 * 30ms 만에 사라지면 화면이 «번쩍»한 것으로만 남는다. 이보다 오래 걸리면
 * 걸리는 만큼 더 머문다. 기다리게 하려고 두는 값이 아니다. */
const MIN_MS = 600;

export default function RequireAuth({ children }) {
  const loc = useLocation();
  const { loading, error } = useApi(() => api.me());
  const [held, setHeld] = useState(true);

  useEffect(() => {
    const t = setTimeout(() => setHeld(false), MIN_MS);
    return () => clearTimeout(t);
  }, []);

  if (loading || held) return <Splash />;

  if (error) {
    // 처음 온 사람에게는 로그인 창부터 들이밀지 않는다.
    return (
      <Navigate to={welcomeSeen() ? "/login" : "/welcome"} replace
                state={{ from: loc.pathname }} />
    );
  }
  return children;
}
