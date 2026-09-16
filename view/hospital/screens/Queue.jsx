import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Chip, Locked, Queue as QueueList, Split, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import { ERR } from "../api";

/* ═══ 1장 · 대기 큐 ══════════════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   아직 아무도 맡지 않은 일이 도착한 순서대로 쌓여 있다. 과 전체가
 *   같은 목록을 본다. 내가 집으면 다른 선생님 화면에서는 사라진다.
 *
 *   병리과  간호·유방외과가 바인딩을 끝낸 **검체**
 *   영상의학과  유방외과가 낸 **촬영 오더**
 *
 * **여기서 하지 않는 일**
 *   · 순서 바꾸기 — 순번은 표시 전용이다. 여럿이 보는 큐라 내가 끌어
 *     옮기면 나만 다른 화면을 보게 된다. 대신 검색으로 건너뛴다
 *   · 반려 — 검체나 오더가 이상한지 시스템이 판단할 수 없다
 *
 * **다음 화면**  집으면 곧바로 2장(업로드)으로 넘어간다
 */

const POLL_MS = 7000;   // 명세 5~10초

export default function QueueScreen({ cfg }) {
  const c = cfg.queue;

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
  const c = cfg.queue;
  const nav = useNavigate();
  const { loading, data, error, reload } = useApi(() => cfg.api.queue(), []);
  const [pick, setPick] = useState(null);
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const take = useCan(c.need.assign);

  /* 큐는 남이 집어가면 줄어든다. 가만히 두면 화면이 거짓말을 하므로
     주기적으로 다시 부른다. SSE 는 쓰지 않기로 했다 — 목록이 짧다 */
  useEffect(() => {
    const t = setInterval(reload, POLL_MS);
    return () => clearInterval(t);
  }, [reload]);

  return (
    <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}
          badge={data ? `${data.items.length}건 대기` : null}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <>
            {msg && <div className="notice">{msg}</div>}
            <Split
              side="wide"
              empty="왼쪽 목록에서 한 사람을 고르면 여기에 상세가 보입니다"
              left={<List cfg={cfg} data={data} q={q} setQ={setQ} pick={pick}
                          setPick={setPick} take={take} busy={busy}
                          onTake={onTake} />}
              right={pick ? <Detail cfg={cfg} id={pick} /> : null}
            />
          </>
        )}
      </Body>
    </Page>
  );

  /* ── 집기 ─────────────────────────────────────────────────
     **큐 맨 앞을 집는다.** 화면에서 고른 것이 아니라 큐 선두다.
     검색으로 걸러 놓으면 둘이 다를 수 있어서, 버튼 아래에 누구를
     집을지 이름을 적어 둔다.

     동시에 두 사람이 누르면 먼저 닿은 하나만 성공하고 나머지는 409 다.
     그때 「다른 선생님이 이미 맡았습니다」를 띄우고 목록을 새로 부른다. */
  async function onTake(head) {
    if (!head || busy) return;
    setBusy(true);
    setMsg(null);
    try {
      await cfg.api.assign(head.id);

      /* ⚠ 과에 따라 **집은 것과 다음 화면의 단위가 다르다.**
         병리   검체를 집으면 그 검체로 바로 간다
         영상   오더를 집은 뒤 Study 를 만들어야 한다. start-study 가
                Study 행을 만드는 유일한 경로이고, 업로드·판독은
                오더 id 가 아니라 study_id 로 움직인다.

         cfg.api.start 가 있는 과만 이 단계를 탄다. 없으면 집은 id 를
         그대로 쓴다 — 병리가 그렇다.

         집기 다음에 부르는 이유: 순서를 바꾸면 두 사람이 동시에 눌렀을 때
         둘 다 Study 를 만들어 놓고 한쪽만 409 로 떨어져 고아 행이 남는다. */
      let goId = head.id;
      if (cfg.api.start) {
        const st = await cfg.api.start(head.id);
        goId = st?.study_id ?? st?.id ?? head.id;
      }
      nav(cfg.go.upload(goId));
    } catch (e) {
      if (e.code === ERR.ALREADY_ASSIGNED) {
        setMsg("다른 선생님이 이미 맡았습니다. 목록을 새로 불러왔습니다.");
      } else if (e.code === ERR.NETWORK) {
        setMsg("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      } else {
        setMsg(e.detail || "집기에 실패했습니다.");
      }
      reload();
    } finally {
      setBusy(false);
    }
  }
}

function List({ cfg, data, q, setQ, pick, setPick, take, busy, onTake }) {
  const c = cfg.queue;

  /* 검색은 **순서를 바꾸지 않는다.** 걸러 보여줄 뿐이다 */
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    const rows = data.items.map((it, i) => ({ ...c.row(it), no: i + 1, raw: it }));
    if (!k) return rows;
    return rows.filter((r) => `${r.title} ${r.sub ?? ""}`.toLowerCase().includes(k));
  }, [data.items, q, c]);

  const head = data.items[0];   /* 큐 선두 — 집기 대상 */

  return (
    <Card title={c.listTitle} pad={false}>
      <QueueList
        items={shown} value={pick} onPick={setPick}
        q={q} onSearch={setQ}
        searchHint={c.searchHint} emptyText={c.emptyText}
        foot={
          <>
            <Btn kind="fill" onClick={() => onTake(head)}
                 disabled={!head || busy || !take.ok} title={take.attrs.title}>
              다음 환자 받기
            </Btn>
            {head && (
              <span className="q-next">
                다음은 <b>{c.row(head).title}</b> · {c.row(head).sub}
              </span>
            )}
            {!head && <span className="q-next">대기 중인 건이 없습니다</span>}
          </>
        }
      />
    </Card>
  );
}

/* 오른쪽 상세 — 아직 집은 것이 아니다. 보기만 한다.
   ⚠ id 가 없으면 서버를 부르지 않는다. 부르면 /…/null 로 나가 404 다 */
function Detail({ cfg, id }) {
  const { loading, data, error, reload } =
    useApi(() => (id ? cfg.api.detail(id) : Promise.resolve(null)), [id]);

  if (!id) return null;

  return (
    <Card title="상세" right={<Chip>아직 맡지 않음</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <cfg.queue.Detail d={data} cfg={cfg} />}
      </Body>
    </Card>
  );
}
