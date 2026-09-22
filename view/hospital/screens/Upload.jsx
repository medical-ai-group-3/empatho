import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Bar, Chip, Fold, Locked, useCan } from "../lib/Parts";
import { useApi } from "../lib/useApi";
import { uploadFile } from "../lib/files";
import { can } from "../perm";
import { RUN_STATUS, label, tone } from "../codes";

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

function isAccepted(file, accept) {
  const rules = String(accept || "").split(",").map((x) => x.trim().toLowerCase()).filter(Boolean);
  const name = String(file.name || "").toLowerCase();
  const type = String(file.type || "").toLowerCase();
  return rules.some((rule) => rule === "*/*"
    || (rule.startsWith(".") && name.endsWith(rule))
    || (rule.endsWith("/*") && type.startsWith(rule.slice(0, -1)))
    || rule === type);
}

export default function UploadScreen({ cfg }) {
  const c = cfg.upload;
  const { id } = useParams();

  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title}>
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
    <Page crumb={[cfg.name, c.title]} title={c.title}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Work cfg={cfg} id={id} d={data} reload={reload} />}
      </Body>
    </Page>
  );
}

function Work({ cfg, id, d, reload }) {
  const c = cfg.upload;
  const nav = useNavigate();
  const loc = useLocation();
  const fileRef = useRef(null);

  /* 큐에서 막 집어 온 길이면 오더 번호를 손에 들고 왔다 (1장 참고).
     새로고침해서 바로 들어오면 없다 — 그때는 조회 응답에 실려 온 것을
     쓰고, 그것도 없으면 과별 설정이 확정을 건너뛴다 */
  const fromQueue = loc.state?.orderId ?? null;
  const send = useCan(c.need.send);
  const run = useCan(c.need.run);
  const accept = c.acceptFor ? c.acceptFor(d) : c.accept;

  /* 이미 올라간 것(서버가 알려준 것)과 전송 중인 것을 가른다. 완료한
     파일은 반드시 uploadInfo를 다시 받아 표시한다 — 선택 목록만 보고
     "올라갔다"고 판단하면 실제 저장 실패를 놓친다. */
  const [picked, setPicked] = useState([]);
  const [dragging, setDragging] = useState(false);
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

  async function choose(e) {
    const fs = [...(e.target.files ?? [])];
    e.target.value = "";     // 같은 파일을 다시 고를 수 있게
    await queueFiles(fs);
  }

  async function queueFiles(fs) {
    if (fs.length === 0) return;
    const invalid = fs.find((file) => !isAccepted(file, accept));
    if (invalid) {
      setMsg(`이 검사에서 허용되지 않는 파일 형식입니다: ${invalid.name}`);
      return;
    }
    const uploads = fs.map((f, index) => ({
        /* 같은 파일을 두 번 골라도 각각의 전송 결과를 따로 보여 준다. */
        id: `${f.name}-${f.size}-${f.lastModified}-${index}-${Date.now()}`,
        file: f,
        name: f.name,
        size: `${(f.size / 1048576).toFixed(1)} MB`,
        state: "uploading",
        error: null,
    }));
    setPicked((p) => [...p, ...uploads]);

    for (const item of uploads) await sendFile(item);
  }

  async function sendFile(item) {
    setPicked((files) => files.map((file) => file.id === item.id
      ? { ...file, state: "uploading", error: null }
      : file));
    try {
      await uploadFile(
        cfg.api.ticket,
        { kind: cfg.scopeKind, id },
        item.file,
        cfg.scopeKind === "study" ? "dicom_upload" : "wsi_upload",
      );
      setPicked((files) => files.filter((file) => file.id !== item.id));
      reload(true);
    } catch (e) {
      setPicked((files) => files.map((file) => file.id === item.id
        ? { ...file, state: "failed", error: e.message || "파일을 올리지 못했습니다." }
        : file));
    }
  }

  /* 아직 전송 전인 파일은 즉시 목록에서 뺀다. 잘못 고른 촬영본을
     그대로 분석에 넘기지 않게 하는 마지막 확인 단계다. 실제 서버에
     올라간 파일의 삭제는 파일 게이트웨이 삭제 API가 준비된 뒤에만
     허용해야 한다 — 화면에서만 지운 척하면 더 위험하다. */
  function removePicked(fileId) {
    setPicked((files) => files.filter((file) => file.id !== fileId));
  }

  const uploadedCount = (d.files ?? []).length;
  const uploadBusy = picked.some((file) => file.state === "uploading");

  async function analyze() {
    setBusy(true);
    setMsg(null);
    try {
      /* 영상: 오더 확정. ⚠ 조회한 자료를 같이 넘긴다 — 확정은 이
         화면의 id(study_id)가 아니라 오더 번호로 걸어야 한다
         (dept/radiology.jsx 의 complete 참고). 큐에서 들고 온 번호가
         있으면 그것을 먼저 세운다 */
      if (cfg.api.complete) {
        await cfg.api.complete(id, {
          ...d,
          exam_order_id: fromQueue ?? d.exam_order_id ?? d.order_id ?? null,
        });
      }
      await cfg.api.analyze(id);
      setProg({ status: "queued", pct: 0 });
    } catch (e) {
      setMsg(e.detail || "분석을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  /* 배치는 `docs/mockup/RadiologyUpload.html` — **두 단이다.**
     왼쪽이 「올리는 일」(누구의 무엇인가 · 파일), 오른쪽이 「넘기는 일」
     (품질 확인 · AI 분석). 전에는 세 단이라 환자 정보가 한 단을 통째로
     먹고 정작 파일 줄이 좁았다. */
  return (
    <div className="up-cols">
      <div className="up-col">
      {/* ── 누구의 무엇인가 ─────────────────────────────────── */}
      <Card title={c.infoTitle}>
        <c.Info d={d} />
      </Card>

      {/* ── 올리는 곳 ──────────────────────────────────────── */}
      <Card title="파일 올리기">
        <div className={`drop ${dragging ? "dragging" : ""}`}
             onDragEnter={(e) => { e.preventDefault(); setDragging(true); }}
             onDragOver={(e) => e.preventDefault()}
             onDragLeave={(e) => { if (e.currentTarget === e.target) setDragging(false); }}
             onDrop={(e) => {
               e.preventDefault();
               setDragging(false);
               queueFiles([...e.dataTransfer.files]);
             }}>
          <p className="drop-t">{c.dropText}</p>
          <input ref={fileRef} type="file" multiple accept={accept}
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
              <Chip tone={f.state === "failed" ? "fill" : "dot"}>
                {f.state === "failed" ? "전송 실패" : "전송 중"}
              </Chip>
              <button className="btn ghost file-remove" type="button"
                      onClick={() => removePicked(f.id)}>
                제외
              </button>
              {f.state === "failed" && (
                <button className="btn line file-retry" type="button" onClick={() => sendFile(f)}>
                  재시도
                </button>
              )}
              {f.error && <small className="warnline">{f.error}</small>}
            </li>
          ))}
          {(d.files ?? []).length === 0 && picked.length === 0 && (
            <li className="none">아직 올린 파일이 없습니다</li>
          )}
        </ul>

        {uploadBusy && (
          <p className="hint">
            선택한 파일을 서버에 올리는 중입니다. 성공한 파일은 완료 목록에 표시됩니다.
          </p>
        )}

        <Fold title="업로드 주의사항" open={false}>
          <ul className="bul">
            {c.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </Fold>
      </Card>
      </div>

      <div className="up-col">
      {/* ── 품질 확인 — 목업이 라디오 둘로 둔 자리 ───────────
          「승인」은 아래 [AI 분석 시작] 이 곧 그것이라 여기서는
          **반려 · 재촬영**만 받는다. 같은 일을 두 자리에서 시키면
          어느 쪽이 진짜인지 헷갈린다.
          ⚠ **반려를 여기서 직접 부르면 안 된다.** `retake` 는 이 화면의
            id(study_id)가 아니라 **오더 번호**로 걸어야 하고, 그 번호를
            찾는 자리가 과별 설정(`c.Extra`)에 있다.
          ⚠ 병리에는 `Extra` 가 없다 — 칸은 두고 그렇게 적는다(8장) */}
      <Card title="품질 확인">
        <p className="muted small">
          승인은 아래 [AI 분석 시작] 입니다. 판독 대기로 넘어갑니다.
        </p>
        {c.Extra
          ? <c.Extra cfg={cfg} id={id} d={d} />
          : <p className="muted">이 과에는 반려 경로가 없습니다</p>}
      </Card>

      {/* ── AI 분석 ────────────────────────────────────────── */}
      <Card title="AI 분석"
            right={prog && <Chip tone={tone("run", prog.status)}>{label(RUN_STATUS, prog.status)}</Chip>}>
        {!prog && (
          <p className="muted">아직 분석을 걸지 않았습니다.</p>
        )}

        {prog && (
          <>
            <Bar value={prog.pct ?? 0} label={label(RUN_STATUS, prog.status)} />
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
               disabled={busy || running || uploadedCount === 0 || !run.ok}
               title={run.attrs.title}>
            AI 분석 시작
          </Btn>
          <Btn kind="line" onClick={() => nav(cfg.go.read(id))} disabled={!done}>
            판독으로
          </Btn>
          {!done && <span className="muted small">
            {uploadedCount === 0 ? "파일 업로드가 완료되어야 분석을 시작할 수 있습니다" : "분석이 끝나야 판독으로 넘어갈 수 있습니다"}
          </span>}
        </div>

        <div className="stack top">
          {/* 재촬영은 위 「품질 확인」 칸으로 옮겼다 — 목업 자리다 */}
          <Btn kind="ghost" onClick={() => nav(cfg.go.queue())}>이전 단계</Btn>
        </div>
      </Card>
      </div>
    </div>
  );
}
