import { useState } from "react";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Bar, Chip, Drop, Split, Table } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";

/* 병리 22 · 슬라이드 업로드
 *
 * 스캔한 전체 슬라이드 이미지(WSI)를 올리고 AI 분석을 시작한다.
 *
 * ── ⚠ 파일이 크다 ────────────────────────────────────────────
 * WSI 는 낱장이 **기가바이트 단위**다. 화면은 진행률만 그리지만 받는
 * 쪽이 그 크기를 받도록 맞춰져 있어야 한다.
 *
 *   · nginx  client_max_body_size 기본값은 1MB — 안 올리면 413
 *   · nginx  proxy_read_timeout 기본 60초 — 20GB ZIP 은 그보다 오래 걸린다
 *   · file-gateway 가 본문을 메모리에 올리는 구조면 프로세스가 죽는다
 *
 * 화면을 아무리 잘 만들어도 이 셋이 안 맞으면 업로드가 막힌다.
 *
 * ── 분석은 되돌릴 수 없다 ─────────────────────────────────────
 * 누르면 GPU 가 몇 분 돈다. 그래서 무엇이 실행되는지와 얼마나 걸리는지를
 * 단추 바로 위에 적는다 — 누르고 나서 알게 되면 늦다.
 */
export default function Upload() {
  const id = new URLSearchParams(location.search).get("case") ?? "current";
  const { loading, data, error, reload } = useApi(() => api.upload(id), [id]);

  return (
    <Page crumb={["병리과", "슬라이드 업로드"]} title="촬영 파일 업로드" badge="WSI"
          sub="스캔한 전체 슬라이드 이미지를 올리고 AI 분석을 시작합니다."
          right={<Btn>업로드 가이드 보기</Btn>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

const FCOLS = [
  { key: "name",  label: "파일명",     w: "28%" },
  { key: "series", label: "시리즈 설명", w: "15%" },
  { key: "site",  label: "촬영 부위",   w: "13%" },
  { key: "at",    label: "촬영일시",    w: "14%" },
  { key: "size",  label: "파일 크기",   w: "12%" },
  { key: "state", label: "상태",        w: "12%" },
  { key: "memo",  label: "비고" },
];

function Inner({ d }) {
  const [busy, setBusy] = useState(false);
  const done = d.files.filter((f) => f.done).length;
  const all  = d.files.length;

  return (
    <Split
      left={
        <>
          <Card title="촬영 파일 업로드"
                right={<><Chip tone="fill">파일 업로드</Chip><Chip>업로드 가이드</Chip></>}>
            <div className="grid2">
              <Drop title="낱장 파일 올리기" note="WSI 파일을 하나씩 업로드합니다."
                    accept=".svs, .tiff, .ndpi" max="4GB" />
              <Drop title="ZIP 파일 올리기" note="여러 슬라이드를 한 번에 업로드합니다."
                    accept=".zip" max="20GB" />
            </div>
            <Bar value={all ? Math.round((done / all) * 100) : 0}
                 label={`업로드 진행률 — ${done} / ${all} 완료`} />
          </Card>

          <Card title="업로드된 파일 목록"
                right={<><span className="src">총 {all}개 파일</span>
                         <Btn>선택 삭제</Btn></>} pad={false}>
            <Table cols={FCOLS} rows={d.files.map((f) => ({
              ...f,
              state: f.done
                ? <Chip tone="line">완료</Chip>
                : <Chip tone="dot">업로드 중</Chip>,
              memo: f.done ? "—" : `${f.pct}%`,
            }))} />
            <div className="tbl-foot">
              {/* 누르기 전에 무엇이 도는지 · 얼마나 걸리는지 */}
              <span>분석을 시작하면 {d.pipeline} 이(가) 실행됩니다 (약 {d.eta}).</span>
              <Btn kind="fill" disabled={done < all || busy}
                   onClick={() => { setBusy(true); api.analyze(d.id).finally(() => setBusy(false)); }}>
                분석
              </Btn>
            </div>
          </Card>
        </>
      }
      right={
        <Card title="환자 정보" right={<Btn>환자 상세 보기</Btn>}>
          <div className="ph">
            <span className="ava" aria-hidden="true">{d.patient.name[0]}</span>
            <div className="ph-tx">
              <b>{d.patient.name} <span className="src">({d.patient.sex} / {d.patient.age}세)</span></b>
              <span>{d.patient.patient_no} · {d.patient.specimen_no}</span>
            </div>
          </div>
          <dl className="kv wide">
            <div><dt>성별 · 나이</dt><dd>{d.patient.sex} · {d.patient.age}세 ({d.patient.birth_date})</dd></div>
            <div><dt>등록번호</dt><dd>{d.patient.patient_no}</dd></div>
            <div><dt>Accession No.</dt><dd>{d.patient.specimen_no}</dd></div>
            <div><dt>요청 검사</dt><dd className="row-chips">
              {d.requested.map((r) => <Chip key={r} tone="fill">{r}</Chip>)}
            </dd></div>
            <div><dt>주치의</dt><dd>{d.doctor}</dd></div>
            <div><dt>요청일</dt><dd>{d.requested_at}</dd></div>
            <div><dt>검사 목적</dt><dd>{d.purpose}</dd></div>
            <div><dt>특이사항</dt><dd>{d.remark || "없음"}</dd></div>
          </dl>
        </Card>
      }
    />
  );
}
