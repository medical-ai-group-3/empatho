import { useState } from "react";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Search, Sort, Split, Table } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";

/* 병리 4 · 전체 환자 목록  (명세 p.24)
 *
 * 영상의학과 목록과 같되 **검체 id 열이 하나 더** 있고 모달리티 정렬이
 * 없다 — 병리는 모달리티가 하나뿐이다.
 *
 * ── 「확인」이 아니라 「열람」이다 ────────────────────────────
 * report.last_viewed_at 은 유방외과가 리포트를 연 시각이 **자동으로**
 * 찍힌 것이다. 「확인했다」는 의도적 행위인데 이 값은 그것을 뜻하지
 * 않는다. 열어만 보고 넘어갔을 수도 있다.
 *
 * ── 진행상황은 두 값을 합친 것이다 ───────────────────────────
 *   bound                          접수 대기
 *   accessioned                    판독 대기
 *   accessioned + finalized_at     판독 완료
 *
 * unbound 는 이 목록에 안 뜬다 — 바인딩 전이라 병리 일이 아니다.
 * **「작성 중」은 따로 표시하지 않는다** — 임시저장은 내 서랍이지
 * 남이 알 일이 아니다.
 *
 * ── 정렬은 서버가 한다 ───────────────────────────────────────
 * 목록이 길어질 자리라 ?ordering= 으로 넘긴다. 큐(7행)와 달리 여기는
 * 화면에서 자를 수 없다.
 */

const COLS = [
  { key: "patient_no",  label: "환자 ID",       w: "15%" },
  { key: "specimen_no", label: "검체 ID",       w: "15%" },
  { key: "name",        label: "이름",          w: "11%" },
  { key: "who",         label: "나이 · 성별",   w: "13%" },
  { key: "state",       label: "진행상황",      w: "18%" },
  { key: "viewed",      label: "유방외과 열람" },
];

const SORTS = [
  { label: "이름",        value: "patient__name" },
  { label: "채취 순",     value: "collected_at" },
  { label: "접수 순",     value: "accessioned_at" },
  { label: "유방외과 열람", value: "report__last_viewed_at" },
  { label: "진행상황",    value: "accession_status" },
];

/* 진행상황 → 칩 모양. 색을 늘리지 않고 셋으로 가른다 */
const TONE = { "접수 대기": "line", "판독 대기": "fill", "판독 완료": "dot" };

export default function Patients() {
  const [q, setQ] = useState("");
  const [ordering, setOrdering] = useState("collected_at");
  const { loading, data, error, reload } =
    useApi(() => api.list({ ordering, q }), [ordering, q]);

  return (
    <Page crumb={["병리과", "환자 관리"]} title="전체 환자 목록"
          badge={data ? `판독 대기 ${data.waiting}` : undefined}
          sub="검체별 진행 상황과 유방외과 열람 여부를 함께 봅니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} q={q} setQ={setQ}
                        ordering={ordering} setOrdering={setOrdering} />}
      </Body>
    </Page>
  );
}

function Inner({ d, q, setQ, ordering, setOrdering }) {
  const [pick, setPick] = useState(d.items[0]?.id ?? null);

  const rows = d.items.map((x) => ({
    ...x,
    who: `${x.age} · ${x.sex}`,
    state: <Chip tone={TONE[x.state] ?? "line"}>{x.state}</Chip>,
    viewed: x.viewed_at
      ? <Chip tone="dot">열람</Chip>
      : <span className="src">미열람</span>,
  }));

  return (
    <Split side="wide"
      left={
        <Card pad={false}
              right={<>
                <Search placeholder="환자 ID, 검체 ID, 이름" value={q} onChange={setQ} />
                <Sort items={SORTS.map((s) => s.label)}
                      value={SORTS.find((s) => s.value === ordering)?.label}
                      onChange={(lb) =>
                        setOrdering(SORTS.find((s) => s.label === lb).value)} />
              </>}>
          <Table cols={COLS} rows={rows} value={pick} onPick={setPick} />
          {/* ⚠ 쪽 넘김을 안 그린다. 명세에 나누는 규격(page · cursor)이
              없어서, 눌러도 아무 일 없는 단추를 두느니 없는 편이 낫다.
              규격이 정해지면 여기에 붙인다 */}
          <div className="tbl-foot">
            <span>{d.total}건 중 {rows.length}건 표시</span>
          </div>
        </Card>
      }
      right={pick ? <Detail id={pick} /> : null}
      empty="왼쪽에서 검체를 고르세요"
    />
  );
}

function Detail({ id }) {
  /* ⚠ 고른 것이 없으면 **부르지 않는다.** 전에는 id 가 null 인 채로
     /specimens/null 을 불러 404 를 받았다. 큐가 비었을 때 오류 카드가
     뜨던 것이 이것이다. */
  const { loading, data, error, reload } =
    useApi(() => (id ? api.specimen(id) : Promise.resolve(null)), [id]);
  if (!id) return null;
  return (
    <Card title="선택한 환자 상세 정보">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <DetailBody d={data} />}
      </Body>
    </Card>
  );
}

function DetailBody({ d }) {
  const p = d.patient;
  return (
    <>
      <div className="ph">
        <span className="ava" aria-hidden="true">{p.name[0]}</span>
        <div className="ph-tx">
          <b>{p.name}</b>
          <span>{p.patient_no} · {d.specimen.no}</span>
        </div>
      </div>

      <dl className="kv wide">
        <div><dt>성별 · 나이</dt><dd>{p.sex} · {p.age}세</dd></div>
        <div><dt>검체 종류</dt><dd>{d.specimen.kind} · {d.specimen.site}</dd></div>
        <div><dt>채취일시</dt><dd>{d.specimen.collected_at}</dd></div>
      </dl>

      {d.crops?.length > 0 && (
        <>
          <h3 className="seck">이미지 (원본)</h3>
          <div className="thumbs">
            {d.crops.map((c, i) => (
              <span className="thumb" key={c.id}><i aria-hidden="true" />크롭 {i + 1}</span>
            ))}
          </div>
        </>
      )}

      <h3 className="seck">판독 결과 (리포트)</h3>
      {d.report ? (
        <dl className="kv wide">
          <div><dt>확진</dt><dd>{d.report.diagnosis}</dd></div>
          <div><dt>등급</dt><dd>{d.report.b_category}</dd></div>
          <div><dt>소견</dt><dd>{d.report.finding_note}</dd></div>
          <div><dt>판독</dt><dd>{d.report.reported_by} · {d.report.finalized_at}</dd></div>
        </dl>
      ) : (
        /* 빈칸으로 두지 않는다 — 빈칸은 「봤는데 없음」으로 읽힌다 */
        <p className="note">아직 판독하지 않았습니다.</p>
      )}

      <div className="rowb">
        <Btn to={go.read(d.specimen.id)}>판독 화면</Btn>
        {d.report && <Btn kind="fill" to={go.amend(d.specimen.id)}>판독 수정</Btn>}
      </div>
    </>
  );
}
