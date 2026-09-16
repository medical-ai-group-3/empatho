import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Chip, Locked, Search, Sort, Split, Table, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can, reportScope } from "../perm";

/* ═══ 4장 · 전체 환자 목록 ═══════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   지난 것까지 전부 찾아보는 자리다. 1장(대기 큐)이 «아직 아무도 안
 *   맡은 것»만 보여주는 데 비해, 여기는 **끝난 것도 남아 있다.**
 *   판독 정정도 여기서 들어간다.
 *
 * **보이는 범위가 사람마다 다르다.**
 *   리포트 권한이 내 담당(own)이면 내가 맡은 환자만 보인다. 화면 위에
 *   그 사실을 적어 둔다 — 목록이 짧은 이유를 모르면 누락으로 오해한다.
 *   서버의 MatrixPermission own_only 와 짝이다.
 *
 * **「확인」이 아니라 「열람」이다.**
 *   유방외과가 리포트를 열면 시각이 자동으로 찍힌다. 사람이 「확인했다」고
 *   누른 것이 아니므로 확인이라고 쓰면 안 된다.
 */

export default function ListScreen({ cfg }) {
  const c = cfg.list;

  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}>
        <Locked what={c.title} />
      </Page>
    );
  }
  return <Inner cfg={cfg} />;
}

function Inner({ cfg }) {
  const c = cfg.list;
  const [sort, setSort] = useState(c.sorts[0].key);
  const [q, setQ] = useState("");
  const [pick, setPick] = useState(null);
  const { loading, data, error, reload } =
    useApi(() => cfg.api.list({ ordering: sort, q: q || undefined }), [sort]);

  const scope = reportScope();

  return (
    <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}
          right={scope && <Chip>{scope.label}</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <Split
            side="wide"
            empty="목록에서 한 사람을 고르면 여기에 상세가 보입니다"
            left={
              <Card
                title={c.listTitle}
                right={<Search placeholder={c.searchHint} value={q} onChange={setQ} />}
                pad={false}
              >
                <div className="tbl-top">
                  <Sort items={c.sorts} value={sort} onChange={setSort} />
                </div>

                <Table
                  cols={c.cols}
                  rows={data.items.filter((r) => match(r, q)).map((r) => c.row(r))}
                  value={pick}
                  onPick={setPick}
                />

                <div className="tbl-foot">
                  <span>{data.total}건 중 {data.items.length}건 표시</span>
                  {scope?.key === "own" && (
                    <span className="muted">내가 맡은 환자만 보입니다</span>
                  )}
                </div>
              </Card>
            }
            right={pick ? <Detail cfg={cfg} id={pick} /> : null}
          />
        )}
      </Body>
    </Page>
  );
}

/* 검색은 화면 안에서 거른다. 서버 질의(q)도 같이 보내지만, 응답이
   오기 전에도 손에 잡히게 */
function match(r, q) {
  const k = q.trim().toLowerCase();
  if (!k) return true;
  return JSON.stringify(r).toLowerCase().includes(k);
}

/* ⚠ id 가 없으면 서버를 부르지 않는다 */
function Detail({ cfg, id }) {
  const c = cfg.list;
  const nav = useNavigate();
  const amend = useCan(cfg.amend.need.view);
  const { loading, data, error, reload } =
    useApi(() => (id ? cfg.api.listDetail(id) : Promise.resolve(null)), [id]);

  if (!id) return null;

  return (
    <Card title="상세">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <>
            <c.Detail d={data} cfg={cfg} />
            <div className="stack top">
              <Btn kind="line" onClick={() => nav(cfg.go.read(id))}>판독 화면</Btn>
              <Btn kind="fill" onClick={() => nav(cfg.go.amend(id))}
                   disabled={!amend.ok || !data.finalized}
                   title={amend.attrs.title}>판독 정정</Btn>
            </div>
            {!data.finalized && (
              <p className="muted small">확정된 판독이 있어야 정정할 수 있습니다.</p>
            )}
          </>
        )}
      </Body>
    </Card>
  );
}
