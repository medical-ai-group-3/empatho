import { CATALOG, reportScope } from "../perm";
import { useMe } from "../lib/useMe";
import { Page, Card } from "../lib/Page";
import { Chip, Facts } from "../lib/Parts";

/* 내 정보 — 내가 누구이고, 무엇을 할 수 있는가
 * ════════════════════════════════════════════════════════════════
 *
 * 상단바 오른쪽의 이름을 누르면 여기로 온다.
 *
 * ⚠ **과에 속한 화면이 아니다.** 사람은 과에 딸린 것이 아니라서
 *   /hospital/me 로 과 바깥에 둔다. 다른 화면이 전부 /hospital/{과}/…
 *   밑에 있는 것과 여기만 다르다.
 *
 * 왜 권한 목록을 보여주나
 *   권한이 없는 화면은 **메뉴에서 아예 사라진다** (lib/Top.jsx).
 *   그래서 선생님 입장에서는 「원래 없는 기능」인지 「나에게 권한이
 *   없는 것」인지 구분할 방법이 없다. 여기서 카탈로그 전체를 펼쳐
 *   놓고 가진 것만 켜서 보여 주면, 관리자에게 무엇을 달라고 해야
 *   하는지 알 수 있다. 그래서 **없는 권한도 지우지 않고 회색으로
 *   남긴다** — 없는 줄이 보여야 요청할 것이 보인다.
 *
 * ⚠ 여기서 권한을 **바꾸지 못한다.** 부여는 관리자 화면 몫이다.
 *   이 화면은 읽기 전용이고, 그 사실을 아래 한 줄로 적어 둔다.
 *
 * 아직 못 넣은 것 (서버에 자리가 없다 · 2026-09-16)
 *   비밀번호 변경 · 연락처 · 사번 — GET /me 에 필드가 없고 PATCH /me 도
 *   없다. 필드가 생기면 아래 Facts 에 한 줄씩 더하면 된다.
 */

/* 카탈로그를 사람이 읽을 묶음으로 가른다.
   key 앞머리로 가르므로 perm.js 에 권한이 늘어도 여기는 안 고친다 */
const GROUPS = [
  { key: "pathology", name: "병리과" },
  { key: "radiology", name: "영상의학과" },
  /* ⚠ 리포트는 **셋 중 하나만** 갖는 등급이다 (perm.js 참고). 나머지 둘이
     «없음»으로 뜨는 것이 결핍처럼 보이면 안 되므로 한 줄 적어 둔다 —
     이걸 안 적으면 관리자에게 «없는 권한 둘»을 달라고 하게 된다 */
  { key: "report",    name: "리포트 열람",
    note: "셋 중 하나만 갖습니다. 위로 갈수록 넓은 범위입니다." },
];

function groupOf(permKey) {
  const head = permKey.split(".")[0];
  return GROUPS.some((g) => g.key === head) ? head : "report";
}

export default function MeScreen() {
  const me = useMe();
  const scope = reportScope();

  /* 로그인 응답이 없으면 화면을 그릴 것이 없다. main.jsx 의 Boot 가
     막아 주므로 평소에는 안 뜨지만, 혹시를 대비해 둔다 */
  if (!me) {
    return (
      <Page crumb={["내 정보"]} title="내 정보">
        <div className="slot big">
          <b>로그인 정보가 없습니다</b>
          <span>다시 로그인해 주세요.</span>
        </div>
      </Page>
    );
  }

  const mine = new Set(me.perms ?? []);
  const hasCount = CATALOG.filter((p) => mine.has(p.key)).length;

  return (
    <Page
      crumb={["내 정보"]}
      title="내 정보"
      sub="계정과 권한을 확인하는 자리입니다. 여기서 바꾸지는 못합니다."
      right={scope && <Chip>{scope.label}</Chip>}
    >
      <Card title="계정">
        <div className="me-head">
          <span className="ava lg" aria-hidden="true">{me.name?.[0]}</span>
          <Facts items={[
            ["이름", me.name],
            ["직책", me.role],
            ["소속", me.dept_name ?? me.dept],
          ]} />
        </div>
      </Card>

      <Card
        title="내 권한"
        right={<span className="muted small">{CATALOG.length}개 중 {hasCount}개</span>}
      >
        <p className="muted small">
          권한은 관리자가 계정마다 켜고 끕니다. 필요한 권한이 꺼져 있으면
          관리자에게 문의하세요. 꺼진 것도 무엇이 있는지 보이도록 함께 적어 둡니다.
        </p>

        {GROUPS.map((g) => {
          const rows = CATALOG.filter((p) => groupOf(p.key) === g.key);
          if (rows.length === 0) return null;
          const on = rows.filter((p) => mine.has(p.key)).length;

          return (
            <section key={g.key} className="perm-g">
              <h3>
                {g.name}
                <span className="muted small">{rows.length}개 중 {on}개</span>
              </h3>
              {g.note && <p className="muted small perm-note">{g.note}</p>}
              <ul className="perms">
                {rows.map((p) => {
                  const has = mine.has(p.key);
                  return (
                    <li key={p.key} className={has ? "on" : "off"}>
                      <i className="mk" aria-hidden="true">{has ? "●" : "○"}</i>
                      <span className="perm-tx">
                        <b>{p.label}</b>
                        <small>{p.where}</small>
                      </span>
                      {/* ⚠ Chip 을 안 쓴다. 이 판의 칩 세 톤은 «진행중·끝남·
                          기계가 도는 중»이라는 뜻이 정해져 있어서(Parts.jsx),
                          «권한 있음/없음»에 갖다 쓰면 그 어휘가 흐려진다.
                          모양으로 가르는 규칙은 왼쪽 ●/○ 가 지킨다 */}
                      <span className="perm-st">{has ? "있음" : "없음"}</span>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })}
      </Card>
    </Page>
  );
}
