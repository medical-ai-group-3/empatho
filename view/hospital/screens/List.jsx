import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Chip, Locked, Search, Split, Table, useCan } from "../lib/Parts";
import { SortSelect } from "../lib/ListCells";
import { useApi } from "../lib/useApi";
import { can, reportScope } from "../perm";
import SideDashboard from "../lib/SideDashboard";
import { Filters, applyFilters, filterQuery, useFilterParams } from "../lib/Filters";

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
      <Page crumb={[cfg.name, c.title]} title={c.title}>
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

  /* 고른 줄은 **주소에 적는다.** 화면 안의 state 로 두면 판독을 보고
     뒤로 왔을 때 고른 환자가 풀린다 — 오른쪽이 「목록에서 한 사람을
     고르면」으로 돌아가 버린다(09-23 확인). 주소에 있으면 뒤로가기가
     그대로 되살린다. 히스토리를 늘리지 않게 replace 로 바꾼다. */
  const [params, setParams] = useSearchParams();
  const picked = params.get("pick");
  /* Table 은 value === row.id 로 비교한다. 숫자 id 를 문자로 돌려주면
     아무 줄도 안 켜지므로 숫자꼴이면 숫자로 되돌린다. */
  const pick = picked == null ? null : (/^\d+$/.test(picked) ? Number(picked) : picked);
  const setPick = (id) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    if (id == null) next.delete("pick");
    else next.set("pick", String(id));
    return next;
  }, { replace: true });

  /* ⚠ 전에는 서버에 q 를 실어 보내면서 **deps 에는 sort 만** 두었다.
     그래서 글자를 쳐도 다시 안 부르고, 정렬을 바꾸는 순간에만 그때
     쳐 둔 글자가 뒤늦게 서버로 나갔다 — 언제 서버가 거르고 언제 화면만
     거르는지가 뒤죽박죽이었다.

     목록 끝에 「{total}건 중 {n}건 표시」가 붙는 화면이라 **서버가 거르는
     것이 맞다.** 지난 검체까지 전부 들어 있어서 화면에 온 것만 뒤지면
     옛 환자를 못 찾는다. 서버 질의는 api.js 에 진작 있었다.

     손이 멈추면 부른다 — 글자마다 부르지 않는다. 그 사이는 아래 match 가
     화면에 온 것을 즉시 걸러 메운다. */
  const qq = useDebounced(q, 300);
  /* 거르는 칩(list.filters) — 주소에 적는다. 홈의 「초안 n」 같은 줄이
     걸러진 목록으로 바로 온다. query 는 서버로, test 는 화면이 한 번 더
     (서버가 그 질의를 몰라도 맞게 보이도록 — lib/Filters) */
  const [fv, setFv] = useFilterParams(c.filters);
  const fq = filterQuery(c.filters, fv);
  const fqKey = JSON.stringify(fq);
  const { loading, data, error, reload } =
    /* ⚠ 09-28 page_size 가 없어 서버 기본 한 쪽(20건)에서 잘렸다 — 스크롤도
       「더 보기」도 없이 늘 같은 스무 명만 보였다. 서버 상한(200)까지 받고,
       그보다 많으면 아래 「n건 중 m건」이 말한다(검색은 서버가 거른다) */
    useApi(() => cfg.api.list({ ordering: sort, q: qq || undefined, page_size: 200, ...fq }), [sort, qq, fqKey]);
  /* 거르기에 쓰는 곁자료(병리: 열린 불일치) — 한 번만 */
  const ctx = useApi(() => (c.context ? c.context() : Promise.resolve({})), []);
  const shown = data
    ? applyFilters(data.items.filter((r) => match(r, q, c.search)), c.filters, fv, ctx.data ?? {})
    : [];

  const scope = reportScope();

  /* 09-28 — 고른 줄이 없으면 **맨 윗줄을 연다.** 오른쪽이 「목록에서 항목을
     선택하면…」 점선 상자 하나로 화면 절반 넘게 비어 있었다(PRODUCT.md
     「오른쪽 단을 비워 두지 않는다」). 주소에는 안 적는다 — 사람이 고른
     것만 적어야 뒤로가기가 그 사람의 선택을 되살린다 */
  const rowsShown = shown.map((r) => c.row(r));
  const open = pick ?? rowsShown[0]?.id ?? null;

  return (
    <Page crumb={[cfg.name, c.title]} title={c.title}
          right={scope && <Chip>{scope.label}</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && (
          <Split
            side={c.splitSide ?? "wide"}
            empty="목록에서 항목을 선택하면 상세 정보가 표시됩니다"
            left={
              <>
                <Card
                  title={c.listTitle}
                  right={<Search placeholder={c.searchHint} value={q} onChange={setQ} />}
                  pad={false}
                >
                  {/* 09-28 — 거르는 칩 · 정렬이 세 줄을 먹어 표가 한참 아래서
                      시작했다. 칩 묶음을 한 흐름으로 이어 접고, 정렬은 고르개
                      하나로 줄인다(.lst-top) */}
                  <div className="tbl-top lst-top">
                    <Filters groups={c.filters} value={fv} onChange={setFv} />
                    <SortSelect items={c.sorts} value={sort} onChange={setSort} />
                  </div>

                  <Table
                    cols={c.cols}
                    rows={rowsShown}
                    value={open}
                    onPick={setPick}
                    emptyText={c.filters ? "조건에 맞는 항목이 없습니다" : undefined}
                  />

                  <div className="tbl-foot">
                    <span>{data.total}건 중 {shown.length}건 표시</span>
                    {scope?.key === "own" && (
                      <span className="muted">내 담당 환자만 표시됩니다</span>
                    )}
                  </div>
                </Card>
                {/* 유방외과처럼 목록 아래에 둔다 — 환자 상세 자리가 아니다.
                    ⚠ 과가 hideDashboard 를 켜면 안 그린다 — 영상의학과는
                    상세가 뷰어까지 들어가서 목록:상세를 1:2로 넓히고
                    "내 업무"는 빼기로 했다(2026-09-18). */}
                {!c.hideDashboard && (
                  <SideDashboard stats={[
                    { label: "전체", value: data.total },
                    { label: "현재 표시", value: shown.length },
                  ]} />
                )}
              </>
            }
            right={open != null ? <Detail cfg={cfg} id={open} /> : null}
          />
        )}
      </Body>
    </Page>
  );
}

/* 값이 멎기를 기다렸다 내준다. 서버 질의를 글자마다 보내지 않으려고 */
function useDebounced(v, ms = 300) {
  const [out, setOut] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setOut(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return out;
}

/* 서버가 거른 것을 화면에서 한 번 더 거른다 — 타자와 응답 사이를 메운다.
 *
 * **찾는 칸을 정해 둔다.** 전에는 행을 통째로 JSON 으로 만들어 훑었는데
 * 두 가지가 나빴다.
 *
 *   · 사람이 안 보는 값까지 걸린다 — id · 상태 코드 · 시각의 초 단위가
 *     다 문자열 안에 있어서, 「1」 한 글자에 거의 모든 행이 걸린다.
 *     걸러 주는 것이 검색인데 아무것도 안 걸러진다
 *   · 글자 하나 칠 때마다 행 수만큼 JSON.stringify 를 돈다
 *
 * 화면에 적힌 것만 본다 — 화면 위 「검색」이 짚는 것도 그것이다.
 * 과마다 찾을 칸이 다르면 dept/*.jsx 의 list.search 로 넘기면 된다. */
const FIELDS = ["patient_name", "patient_no", "specimen_no", "accession_no"];

function match(r, q, fields = FIELDS) {
  const k = q.trim().toLowerCase();
  if (!k) return true;
  return fields.some((f) => String(r[f] ?? "").toLowerCase().includes(k));
}

/* ⚠ id 가 없으면 서버를 부르지 않는다 */
function Detail({ cfg, id }) {
  const c = cfg.list;
  const nav = useNavigate();
  /* ⚠ 병리는 cfg.amend 가 없다 (확정 사양서 §8-2 — 정정 경로를 두지
     않는다). useCan 은 훅이라 조건부로 못 부르니 항상 부르지만,
     아래 "판독 정정" 버튼은 cfg.amend 가 있을 때만 렌더링된다 —
     이 값은 병리에서는 그냥 안 쓰인다 */
  const amend = useCan(cfg.amend?.need?.view);
  const { loading, data, error, reload } =
    useApi(() => (id ? cfg.api.listDetail(id) : Promise.resolve(null)), [id]);

  if (!id) return null;

  /* ⚠ 09-28 — **단추를 머리로 올렸다.** 전에는 뷰어(820px) 아래라 화면
     밖이었다 — 목록에서 고르고 판독으로 가려면 늘 스크롤해야 했다 */
  const acts = data && (
    <span className="stack">
      {cfg.amend && !data.finalized && (
        <span className="muted small">확정된 판독이 있어야 정정할 수 있습니다</span>
      )}
      <Btn kind={cfg.amend && data.finalized ? "line" : "fill"}
           onClick={() => nav(cfg.go.read(id))}>판독 화면</Btn>
      {cfg.amend && (
        <Btn kind="fill" onClick={() => nav(cfg.go.amend(id))}
             disabled={!amend.ok || !data.finalized}
             title={amend.attrs.title}>판독 정정</Btn>
      )}
    </span>
  );

  return (
    <Card title={data ? (c.detailTitle?.(data) ?? "상세") : "상세"} right={acts}>
      <Body loading={loading} error={error} onRetry={reload}>
        {/* ⚠ key 를 준다. 안 주면 환자를 바꿔도 같은 부품이 그대로
            남아서, 접었다 편 상태(Fold)가 앞 환자 것으로 이어진다 */}
        {data && <c.Detail key={id} d={data} cfg={cfg} />}
      </Body>
    </Card>
  );
}
