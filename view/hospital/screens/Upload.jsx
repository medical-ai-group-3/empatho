import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Bar, Chip, Fold, Locked, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { can } from "../perm";

/* ═══ 2장 · 업로드 ═══════════════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   집은 환자의 영상·이미지를 올리고, 그 자리에서 AI 분석을 건다.
 *
 *   병리과  크롭 조직 이미지 (WSI 전체가 아니다. 여러 장 가능)
 *   영상의학과  촬영본. 맘모 4뷰 · 초음파 클립 · MRI 시퀀스(zip)
 *
 * **AI 분석은 여기서 시작하고 여기서 끝난다.**
 *   [AI 분석 시작]을 누르면 업로드가 확정되고 분석이 걸린다. 분석이
 *   끝나야 3장(판독)으로 넘어갈 수 있다. 그래서 판독 화면에는
 *   「분석 중」이라는 상태가 아예 없다 — 들어갔으면 이미 결과가 있다.
 *
 * **기다리는 동안 나가도 된다.**
 *   MRI 는 175초다. 화면 앞에 붙어 있을 필요가 없어서, 큐로 나갔다가
 *   다시 들어와도 진행 상태가 그대로 보인다. 클라이언트에 타임아웃을
 *   두지 않는다.
 *
 * **파일 바이트는 Django 를 안 거친다.**
 *   티켓을 발급받아 Go file-gateway 로 곧장 올린다.
 */

const POLL_MS = 5000;

/* 서버가 주는 진행 상태를 사람 말로 */
const STATUS = {
  queued:  { label: "대기 중",  tone: "dot"  },
  running: { label: "분석 중",  tone: "dot"  },
  done:    { label: "완료",     tone: "line" },
  failed:  { label: "실패",     tone: "fill" },
};

export default function UploadScreen({ cfg }) {
  const c = cfg.upload;
  const { id } = useParams();

  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}>
        <Locked what={c.title} />
      </Page>
    );
  }
  return <Inner cfg={cfg} id={id} />;
}

function Inner({ cfg, id }) {
  const c = cfg.upload;
  const { loading, data, error, reload } = useApi(() => cfg.api.uploadInfo(id), [id]);

  return (
    <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Work cfg={cfg} id={id} d={data} />}
      </Body>
    </Page>
  );
}

function Work({ cfg, id, d }) {
  const c = cfg.upload;
  const nav = useNavigate();
  const fileRef = useRef(null);
  const send = useCan(c.need.send);
  const run = useCan(c.need.run);

  /* 이미 올라간 것(서버가 알려준 것)과 방금 고른 것(아직 안 올라간 것)을
     **가른다.** 고른 것을 올라간 것처럼 그리면, 실패했을 때 올라간 줄
     알고 넘어간다 */
  const [picked, setPicked] = useState([]);
  const [prog, setProg] = useState(d.ai ?? null);   // { status, pct }
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const running = prog && (prog.status === "queued" || prog.status === "running");
  const done = prog?.status === "done";

  /* 분석이 도는 동안만 물어본다. 끝나면 멈춘다 */
  useEffect(() => {
    if (!running) return;
    const t = setInterval(async () => {
      try { setProg(await cfg.api.progress(id)); } catch { /* 다음 차례에 */ }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [running, id, cfg]);

  function choose(e) {
    const fs = [...(e.target.files ?? [])];
    setPicked((p) => [
      ...p,
      ...fs.map((f) => ({
        id: `${f.name}-${f.size}`,
        name: f.name,
        size: `${(f.size / 1048576).toFixed(1)} MB`,
      })),
    ]);
    e.target.value = "";     // 같은 파일을 다시 고를 수 있게
  }

  async function analyze() {
    setBusy(true);
    setMsg(null);
    try {
      if (cfg.api.complete) await cfg.api.complete(id);   // 영상: 오더 확정
      await cfg.api.analyze(id);
      setProg({ status: "queued", pct: 0 });
    } catch (e) {
      setMsg(e.detail || "분석을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid3">
      {/* ── 왼쪽 · 누구의 무엇인가 ─────────────────────────── */}
      <Card title={c.infoTitle}>
        <c.Info d={d} />
      </Card>

      {/* ── 가운데 · 올리는 곳 ──────────────────────────────── */}
      <Card title="파일 올리기">
        <div className="drop">
          <p className="drop-t">{c.dropText}</p>
          <input ref={fileRef} type="file" multiple accept={c.accept}
                 onChange={choose} hidden />
          <Btn onClick={() => fileRef.current?.click()}
               disabled={!send.ok} title={send.attrs.title}>파일 선택</Btn>
        </div>

        <ul className="files">
          {(d.files ?? []).map((f) => (
            <li key={f.id}>
              <b>{f.name}</b><span>{f.size}</span>
              <Chip tone="line">업로드 완료</Chip>
            </li>
          ))}
          {picked.map((f) => (
            <li key={f.id}>
              <b>{f.name}</b><span>{f.size}</span>
              <Chip tone="dot">전송 준비 중</Chip>
            </li>
          ))}
          {(d.files ?? []).length === 0 && picked.length === 0 && (
            <li className="none">아직 올린 파일이 없습니다</li>
          )}
        </ul>

        {picked.length > 0 && (
          <p className="hint">
            방금 고른 {picked.length}장은 아직 전송되지 않았습니다 —
            티켓 발급 규격이 정해지면 이 자리에서 Go 로 올라갑니다.
          </p>
        )}

        <Fold title="업로드 주의사항" open={false}>
          <ul className="bul">
            {c.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </Fold>
      </Card>

      {/* ── 오른쪽 · AI 분석 ───────────────────────────────── */}
      <Card title="AI 분석"
            right={prog && <Chip tone={STATUS[prog.status]?.tone}>{STATUS[prog.status]?.label}</Chip>}>
        {!prog && (
          <p className="muted">아직 분석을 걸지 않았습니다.</p>
        )}

        {prog && (
          <>
            <Bar value={prog.pct ?? 0} label={STATUS[prog.status]?.label} />
            {prog.status === "failed" && (
              <p className="hint">분석에 실패했습니다. 다시 걸어 보시고, 계속 실패하면 담당자에게 알려 주세요.</p>
            )}
            {prog.abstained && (
              <p className="hint">
                <b>판정하지 못했습니다.</b> {prog.abstain_reason}
                <br />분석 실패가 아닙니다. 직접 판독하시면 됩니다.
              </p>
            )}
          </>
        )}

        <p className="muted small">{c.estimate}</p>
        {msg && <p className="hint">{msg}</p>}

        <div className="stack">
          <Btn kind="fill" onClick={analyze}
               disabled={busy || running || !run.ok} title={run.attrs.title}>
            AI 분석 시작
          </Btn>
          <Btn kind="line" onClick={() => nav(cfg.go.read(id))} disabled={!done}>
            판독으로
          </Btn>
          {!done && <span className="muted small">분석이 끝나야 판독으로 넘어갈 수 있습니다</span>}
        </div>

        <div className="stack top">
          <Btn kind="ghost" onClick={() => nav(cfg.go.queue())}>이전 단계</Btn>
          {c.Extra && <c.Extra cfg={cfg} id={id} d={d} />}
        </div>
      </Card>
    </div>
  );
}
