import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Bar, Chip, Fold, Split } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";

/* 병리 2 · 조직 이미지 업로드  (명세 p.22)
 *
 * ── WSI 전체가 아니라 크롭이다 ───────────────────────────────
 * 추론 서버가 **크롭 한 장씩** 받는다. WSI 타일 피라미드는 시연 범위
 * 밖이다. 화면 문구도 그에 맞춘다 — 「WSI 파일」이라고 적어 두면 올리는
 * 사람이 슬라이드 통파일을 찾는다.
 *
 * ── 여러 장을 올린다 ─────────────────────────────────────────
 * 같은 슬라이드라도 **자른 자리에 따라 sTIL 이 0~36% 로 요동친다**(CV≈1.0).
 * 한 장만 돌리면 그 한 자리의 값이고, 여러 장을 돌려야 분포가 보인다.
 * 크롭 3장이면 ai_result 3행이고 specimen_id 가 같아 묶인다.
 *
 * ── 분석이 여기서 시작되고 여기서 끝난다 ─────────────────────
 * 끝나야 판독으로 넘어갈 수 있다. 그래서 **판독 화면에는 「분석 중」이
 * 없다.** 건너뛰는 길도 없다 — 일단 돌리고, 결과를 볼지 말지는 판독
 * 화면에서 패널로 정한다.
 */

const POLL_MS = 3000;

export default function Upload() {
  const { id } = useParams();
  const { loading, data, error, reload } = useApi(() => api.uploadInfo(id), [id]);
  return (
    <Page crumb={["병리과", "조직 이미지 업로드"]} title="조직 이미지 업로드"
          sub="크롭한 조직 이미지를 올리고 AI 분석을 시작합니다. 여러 장을 올릴 수 있습니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} />}
      </Body>
    </Page>
  );
}

/* 대기중 → 분석중 → 완료. 소켓을 나누지 않는다 —
   추론 서버가 조직 분할과 세포 검출을 한 번에 낸다 */
const RUN = {
  queued:  { label: "대기중", tone: "line" },
  running: { label: "분석중", tone: "dot"  },
  done:    { label: "완료",   tone: "line" },
  failed:  { label: "실패",   tone: "fill" },
};

function Inner({ d }) {
  const nav = useNavigate();
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState(d.ai_run ?? null);

  /* 분석이 도는 동안만 물어본다 */
  useEffect(() => {
    if (run?.status !== "queued" && run?.status !== "running") return;
    const t = setInterval(async () => {
      try { setRun(await api.aiResults(d.id)); } catch { /* 다음 번에 */ }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [run?.status, d.id]);

  const uploaded = d.crops.filter((c) => c.done).length;
  const canAnalyze = uploaded > 0 && uploaded === d.crops.length
                     && run?.status !== "running" && run?.status !== "queued";
  const canRead = run?.status === "done";

  async function analyze() {
    setBusy(true);
    try { setRun(await api.analyze(d.id)); } finally { setBusy(false); }
  }

  return (
    <Split
      left={
        <>
          <Card title="조직 이미지"
                right={<span className="src">크롭 {d.crops.length}장</span>}>
            <div className="drop">
              <i aria-hidden="true">↥</i>
              <b>조직 이미지를 드래그하세요 (여러 장 가능)</b>
              <span>크롭한 조직 이미지를 올립니다. 슬라이드 통파일이 아닙니다.</span>
              <Btn>파일 선택</Btn>
              <small>지원 형식: {d.accept}</small>
            </div>

            <Fold title="업로드 주의사항" open={false}>
              <ul className="bul">
                {d.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            </Fold>
          </Card>

          <Card title="올린 이미지 목록" pad={false}>
            <ul className="crops">
              {d.crops.map((c, i) => (
                <li key={c.id}>
                  <i className="thumb sm" aria-hidden="true" />
                  <span className="crop-tx">
                    <b>크롭 {i + 1}</b>
                    <span>{c.name} · {c.size}</span>
                  </span>
                  {c.done
                    ? <Chip tone="line">업로드 완료</Chip>
                    : <span className="crop-bar"><Bar value={c.pct} /></span>}
                </li>
              ))}
              {d.crops.length === 0 && (
                <li><div className="q-empty">아직 올린 이미지가 없습니다</div></li>
              )}
            </ul>
          </Card>
        </>
      }
      right={
        <>
          <Card title="AI 분석">
            {run ? (
              <>
                <div className="ph-tx">
                  <b>{RUN[run.status]?.label ?? run.status}</b>
                  <span>{run.note}</span>
                </div>
                <Bar value={run.pct ?? 0} />
              </>
            ) : (
              <p className="note">아직 분석하지 않았습니다.</p>
            )}
            <div className="rowb">
              <Btn to={go.queue()}>이전 단계</Btn>
              {canRead
                ? <Btn kind="fill" onClick={() => nav(go.read(d.id))}>판독으로</Btn>
                : <Btn kind="fill" disabled={!canAnalyze || busy} onClick={analyze}>
                    AI 분석 시작
                  </Btn>}
            </div>
            <p className="hint">
              올린 이미지를 전부 분석합니다. 한 장에 약 {d.eta} 걸립니다.
            </p>
          </Card>

          <Card title="검체 정보">
            <div className="ph">
              <span className="ava" aria-hidden="true">{d.patient.name[0]}</span>
              <div className="ph-tx">
                <b>{d.patient.name}</b>
                <span>{d.patient.patient_no} · {d.patient.sex} / {d.patient.age}세</span>
              </div>
            </div>
            <dl className="kv wide">
              <div><dt>검체번호</dt><dd>{d.specimen.no}</dd></div>
              <div><dt>검체 종류</dt><dd>{d.specimen.kind}</dd></div>
              <div><dt>검체 상태</dt><dd>{d.specimen.state}</dd></div>
              <div><dt>병변 위치</dt><dd>{d.specimen.lesion}</dd></div>
            </dl>
            {d.imaging && (
              <>
                <h3 className="seck">영상 판독 요약</h3>
                <dl className="kv wide">
                  <div><dt>{d.imaging.modality}</dt><dd>{d.imaging.finding}</dd></div>
                  <div><dt>BI-RADS</dt><dd>{d.imaging.birads}</dd></div>
                </dl>
              </>
            )}
            {d.guide_images?.length > 0 && (
              <>
                <h3 className="seck">유도 영상</h3>
                <div className="thumbs">
                  {d.guide_images.map((g) => (
                    <span className="thumb" key={g.label}><i aria-hidden="true" />{g.label}</span>
                  ))}
                </div>
              </>
            )}
          </Card>
        </>
      }
    />
  );
}
