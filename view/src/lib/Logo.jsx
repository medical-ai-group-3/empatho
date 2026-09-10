import { useState } from "react";

/* 로고.
 *
 * 파일은 `public/logo.svg` 하나만 본다. **그 파일이 없으면 글자 로고가
 * 대신 나온다** — 빌드가 깨지지 않고, 파일을 넣는 순간 바뀐다.
 *
 * public/ 에 두는 이유 — import 로 끌어오면 파일이 없을 때 빌드가 통째로
 * 실패한다. 로고 하나 때문에 앱이 안 뜨면 안 된다.
 *
 * SVG 를 권한다. 폰마다 화면 배율이 달라서 PNG 는 어딘가에서 뭉갠다.
 *
 * ⚠ 시안의 로고는 「EMPATHO CDSS · CLINICAL DECISION SUPPORT SYSTEM」이다.
 *   그건 **의료진용 시스템 이름**이라, 환자 앱에는 EMPATHO 만 있는 판이
 *   더 맞을 수 있다. 팀에 확인할 것.
 */
export default function Logo({ size = "md" }) {
  const [failed, setFailed] = useState(false);

  if (failed) return <p className={`mark ${size}`}>EMPATHO</p>;

  return (
    <img
      className={`logo ${size}`}
      src="/logo.svg"
      alt="EMPATHO"
      onError={() => setFailed(true)}
    />
  );
}
