import { useState } from "react";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Queue, Split } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";

/* 병리 21 · 검체 바인딩 대기
 *
 * 간호과와 유방외과에서 등록한 검체가 순서대로 도착한다. 확인하고 접수하면
 * 슬라이드 업로드로 넘어간다.
 *
 * ── 왜 오른쪽이 이렇게 긴가 ───────────────────────────────────
 * 검체를 접수한다는 것은 **이 유리 조각이 이 환자의 이 병변에서 나온
 * 것이 맞는가**를 확인하는 일이다. 틀리면 남의 결과를 받게 된다.
 * 그래서 요청한 쪽이 보낸 것을 전부 펴 놓는다 — 요청 정보 · 임상 정보 ·
 * 영상 판독 요약 · 첨부. 접수 단추는 그것들을 다 지나야 나온다.
 *
 * 「반려」가 「접수」와 나란히 있는 이유도 같다. 확인해 보니 아니면
 * 돌려보낼 수 있어야 한다.
 */
export default function Specimens() {
  const { loading, data, error, reload } = useApi(() => api.specimens());
  return (
    <Page crumb={["병리과", "검체 관리"]} title="검체 바인딩 대기"
          badge={data ? `${data.items.length}건` : undefined}
          sub="간호과와 유방외과에서 등록한 검체가 순서대로 도착합니다. 확인 후 슬라이드를 업로드합니다."
          right={data && <Stats s={data.stats} />}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner items={data.items} />}
      </Body>
    </Page>
  );
}

function Stats({ s }) {
  if (!s) return null;
  return (
    <div className="stats" style={{ gridTemplateColumns: `repeat(${s.length},auto)` }}>
      {s.map((x) => <div className="stat" key={x.label}><b>{x.n}</b><span>{x.label}</span></div>)}
    </div>
  );
}

function Inner({ items }) {
  const [list, setList] = useState(items);
  const [pick, setPick] = useState(items[0]?.id ?? null);

  const move = (a, b) => setList((l) => {
    const n = [...l]; n.splice(b, 0, ...n.splice(a, 1)); return n;
  });
  const step = (d) => {
    const i = list.findIndex((x) => x.id === pick);
    const j = Math.min(list.length - 1, Math.max(0, i + d));
    setPick(list[j].id);
  };

  return (
    <Split
      left={
        <Card title="검체 바인딩 대기 환자 리스트"
              right={<span className="src">환자 순서대로 배치</span>} pad={false}>
          <Queue
            items={list.map((x) => ({
              id: x.id,
              title: `${x.name}  ${x.patient_no} · ${x.sex} ${x.age}세`,
              sub: `${x.specimen_no} · ${x.site} · ${x.kind}`,
              chip: x.bound ? "바인딩 완료" : "대기",
              chipTone: x.bound ? "dot" : "line",
            }))}
            value={pick} onPick={setPick} onMove={move}
            onPrev={() => step(-1)} onNext={() => step(1)}
          />
        </Card>
      }
      right={<Detail id={pick} />}
      empty="왼쪽에서 검체를 고르세요"
    />
  );
}

/* 고른 검체 하나 — 접수 화면 */
function Detail({ id }) {
  const { loading, data, error, reload } = useApi(() => api.specimen(id), [id]);
  return (
    <Card title="검체 접수" right={<span className="src">대시보드 › 검체 접수</span>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <DetailBody d={data} />}
      </Body>
    </Card>
  );
}

function DetailBody({ d }) {
  const [busy, setBusy] = useState(false);
  const p = d.patient;

  return (
    <>
      <div className="ph">
        <span className="ava" aria-hidden="true">{p.name[0]}</span>
        <div className="ph-tx">
          <b>{p.name}</b>
          <span>{p.patient_no} · {p.sex} / {p.age}세 · {p.birth_date}</span>
        </div>
      </div>

      <dl className="kv two">
        <div><dt>요청 부서</dt><dd>{d.request.dept}</dd></div>
        <div><dt>요청일</dt><dd>{d.request.at}</dd></div>
        <div><dt>담당의</dt><dd>{d.request.doctor}</dd></div>
      </dl>

      <h3 className="seck">검체 정보 (요청 정보)</h3>
      <dl className="kv wide">
        <div><dt>검체번호</dt><dd><b>{d.specimen.no}</b></dd></div>
        <div><dt>검체 종류</dt><dd>{d.specimen.kind}</dd></div>
        <div><dt>채취 방식</dt><dd>{d.specimen.method}</dd></div>
        <div><dt>채취일시</dt><dd>{d.specimen.taken_at}</dd></div>
        <div><dt>요청 부위</dt><dd>{d.specimen.site}</dd></div>
        <div><dt>병변</dt><dd>{d.specimen.lesion}</dd></div>
      </dl>

      {/* 바인딩 여부 — **접수 가능한지를 가르는 값**이라 눈에 띄는 자리에
          둔다. 안 되어 있으면 접수 단추가 잠긴다 */}
      <div className="info">
        <i aria-hidden="true">{d.bound ? "✓" : "!"}</i>
        <div className="info-tx">
          <b>{d.bound ? "검체 바인딩 완료" : "병변과 연결되지 않았습니다"}</b>
          <span>{d.bound
            ? "이 검체는 병변과 연결되어 접수 가능합니다."
            : "요청한 부서에 병변 연결을 요청하십시오."}</span>
        </div>
      </div>

      <h3 className="seck">임상 정보 ({d.request.dept})</h3>
      <p className="note">{d.clinical}</p>

      {d.imaging && (
        <>
          <h3 className="seck">영상의학과 판독 요약</h3>
          <dl className="kv wide">
            <div><dt>검사 종류</dt><dd>{d.imaging.modality}</dd></div>
            <div><dt>판독일</dt><dd>{d.imaging.read_at}</dd></div>
            <div><dt>소견</dt><dd>{d.imaging.finding}</dd></div>
            {/* 영상 쪽 판정이라 「모델 BI-RADS」가 아니다. 사람이 낸 값이다 */}
            <div><dt>BI-RADS</dt><dd><b>{d.imaging.birads}</b></dd></div>
          </dl>
        </>
      )}

      <h3 className="seck">첨부 이미지 / 문서</h3>
      <div className="row-chips">
        {d.attachments.map((g) => (
          <Chip key={g.label} tone={g.n > 0 ? "fill" : "line"}>{g.label} {g.n}</Chip>
        ))}
      </div>
      <div className="files">
        {d.files.map((f) => (
          <span className="file" key={f.name}>
            <i aria-hidden="true">{f.kind === "image" ? "▣" : "▤"}</i>
            {f.name}<span>· {f.at}</span>
          </span>
        ))}
      </div>

      <div className="rowb">
        <Btn disabled={busy}
             onClick={() => { setBusy(true); api.rejectSpecimen(d.id, "").finally(() => setBusy(false)); }}>
          반려
        </Btn>
        {/* 화면당 하나뿐인 채움 단추. 이 화면에서 할 일은 접수다 */}
        <Btn kind="fill" disabled={!d.bound || busy}
             onClick={() => { setBusy(true); api.acceptSpecimen(d.id).finally(() => setBusy(false)); }}>
          접수 · 업로드
        </Btn>
      </div>
    </>
  );
}
