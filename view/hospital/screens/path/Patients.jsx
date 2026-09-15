import { useMemo, useState } from "react";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Search, Sort, Split, Table } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { ROOT } from "../../nav";

/* 병리 24 · 전체 환자 목록
 *
 * 검체별 진행 상황과 유방외과 확인 여부를 함께 본다.
 *
 * ── 「유방외과 확인」이 왜 한 칸을 차지하나 ──────────────────
 * 병리 판독은 저장하면 유방외과로 나간다. 그런데 **나갔다고 읽힌 것은
 * 아니다.** 이 칸이 없으면 판독의가 자기 일이 끝났다고 여기는데 정작
 * 아무도 안 본 건이 쌓인다. 그래서 목록에 같이 둔다.
 *
 * ── 상태를 색으로 말하지 않는다 ───────────────────────────────
 * 진행 상황은 넷이다 — 슬라이드 제작 · AI 분석 중 · 판독 중 · 판독 완료.
 * 색을 넷 만들면 판독 영상 위의 병변 표시와 싸운다. 대신 셋으로 가른다:
 * **채움**(내가 지금 하는 것) · **시안 점**(기계가 도는 것) ·
 * **외곽선**(끝났거나 기다리는 것). 글자가 뜻을 지고 모양이 거든다.
 */

const COLS = [
  { key: "patient_no",  label: "환자 ID",     w: "17%" },
  { key: "specimen_no", label: "검체 ID",     w: "17%" },
  { key: "name",        label: "이름",        w: "12%" },
  { key: "who",         label: "나이 · 성별", w: "14%" },
  { key: "state",       label: "진행 상황",   w: "20%" },
  { key: "checked",     label: "유방외과 확인" },
];

/* 진행 상황 → 칩 모양. 여기 한 곳에서만 정한다 */
const TONE = {
  "슬라이드 제작": "line",
  "AI 분석 중":   "dot",
  "판독 중":      "fill",
  "판독 완료":    "line",
};

export default function Patients() {
  const { loading, data, error, reload } = useApi(() => api.cases());
  return (
    <Page crumb={["병리과", "환자 관리"]} title="전체 환자 목록"
          badge={data ? `판독 대기 ${data.waiting}` : undefined}
          sub="검체별 진행 상황과 유방외과 확인 여부를 함께 봅니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ d }) {
  const [pick, setPick] = useState(d.items[0]?.id ?? null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("접수 순서");

  /* 거르기와 정렬은 화면에서 한다. 목록이 열여덟 줄이라 서버를 다시
     부를 값어치가 없다 — 수천 줄이 되면 그때 서버로 옮긴다 */
  const rows = useMemo(() => {
    const key = q.trim().toLowerCase();
    const hit = (x) => !key ||
      [x.patient_no, x.specimen_no, x.name].some((v) => v.toLowerCase().includes(key));
    const by = {
      "이름순":        (a, b) => a.name.localeCompare(b.name, "ko"),
      "접수 순서":     (a, b) => a.seq - b.seq,
      "유방외과 확인": (a, b) => Number(a.checked) - Number(b.checked),
      "진행 상황":     (a, b) => a.state.localeCompare(b.state, "ko"),
    }[sort];
    return d.items.filter(hit).sort(by).map((x) => ({
      ...x,
      who: `${x.age} · ${x.sex}`,
      state: <Chip tone={TONE[x.state] ?? "line"}>{x.state}</Chip>,
      checked: x.checked ? <Chip tone="dot">확인</Chip> : <span className="src">미확인</span>,
    }));
  }, [d.items, q, sort]);

  return (
    <Split side="wide"
      left={
        <Card pad={false}
              right={<>
                <Search placeholder="환자 ID, 검체 ID, 이름" value={q} onChange={setQ} />
                <Sort items={["이름순", "접수 순서", "유방외과 확인", "진행 상황"]}
                      value={sort} onChange={setSort} />
              </>}>
          <Table cols={COLS} rows={rows} value={pick} onPick={setPick} />
          <div className="tbl-foot">
            <span>{d.total}명 중 1–{rows.length} 표시</span>
            <div className="pg">
              <button>‹</button>
              <button className="on">1</button><button>2</button><button>3</button>
              <button>›</button>
            </div>
          </div>
        </Card>
      }
      right={<Detail id={pick} />}
      empty="왼쪽에서 환자를 고르세요"
    />
  );
}

function Detail({ id }) {
  const { loading, data, error, reload } = useApi(() => api.caseDetail(id), [id]);
  return (
    <Card title="선택한 환자 상세 정보">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <DetailBody d={data} />}
      </Body>
    </Card>
  );
}

function DetailBody({ d }) {
  return (
    <>
      <div className="ph">
        <span className="ava" aria-hidden="true">{d.name[0]}</span>
        <div className="ph-tx">
          <b>{d.name}</b>
          <span>{d.patient_no} · {d.specimen_no}</span>
        </div>
      </div>

      <dl className="kv">
        <div><dt>성별 · 나이</dt><dd>{d.sex} · {d.age}세</dd></div>
        <div><dt>검체</dt><dd>{d.kind} · {d.site}</dd></div>
        <div><dt>스캔 일시</dt><dd>{d.scanned_at}</dd></div>
      </dl>

      <h3 className="seck">이미지 (원본)</h3>
      <div className="thumbs">
        {d.slides.map((s) => (
          <span className="thumb" key={s.label}><i aria-hidden="true" />{s.label}</span>
        ))}
      </div>

      {/* 판독이 끝난 건만 리포트가 있다. 없으면 **빈칸이 아니라** 왜
          없는지를 적는다 — 빈칸은 「봤는데 없음」으로 읽힌다 */}
      <h3 className="seck">판독 결과 (리포트)</h3>
      {d.report ? (
        <dl className="kv">
          <div><dt>진단</dt><dd>{d.report.diagnosis}</dd></div>
          <div><dt>IHC</dt><dd>{d.report.ihc}</dd></div>
          <div><dt>소견</dt><dd>{d.report.note}</dd></div>
        </dl>
      ) : (
        <p className="note">아직 판독하지 않았습니다.</p>
      )}

      <div className="rowb">
        <Btn to={`${ROOT}/pathology/read?case=${d.id}`}>판독 화면</Btn>
        <Btn kind="fill" to={`${ROOT}/pathology/amend?case=${d.id}`}>판독 수정</Btn>
      </div>
    </>
  );
}
