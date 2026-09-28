import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Bar, Chip, Locked, useCan } from "../lib/Parts";
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
 * **배치 — 일하는 순서대로 (09-28)**
 *   ┌ 누구의 무엇 — 한 줄 ─────────────────────────────────┐
 *   ├ 파일 올리기 (1.5fr) ───────┬ ① 품질 (영상만) ──────────┤
 *   │ 끌어 놓기 · 올린 것 · 올릴 것│ ② AI 분석                 │
 *   │                            │ ③ 판독으로                │
 *   └────────────────────────────┴───────────────────────────┘
 *   전에는 환자 정보 칸이 왼쪽 위를 통째로 먹어 정작 파일 칸이 화면 아래로
 *   밀려 있었다(1600×950 에서 스크롤해야 보였다). 누구의 무엇인지는 한 줄로
 *   충분하다 — 자세한 것은 큐 · 판독 화면이 보인다.
 *
 * **파일은 [업로드] 를 눌러야 전송된다.** 고르기만 하면 「올리기 전」
 *   으로 대기하고, 잘못 고른 것은 [제외] 로 뺀다. 서버 삭제 경로가 없어
 *   올라간 뒤에는 못 되돌리기 때문이다.
 *
 * **AI 분석은 여기서 시작하고 여기서 끝난다.** 분석이 끝나야 3장(판독)으로
 *   넘어갈 수 있다. **기다리는 동안 나가도 된다** — 다시 들어와도 진행
 *   상태가 그대로 보인다. 클라이언트에 타임아웃을 두지 않는다.
 */

const POLL_MS = 5000;
const STEP = ["①", "②", "③", "④"];

/* 조회 응답에 실려 온 AI 상태 → { status, pct }.
   ⚠ 모양이 여럿이다 — 진행({status,pct}) · 결과 봉투({run_status}) ·
   병리 검체의 결과 배열. 배열이나 상태 없는 것을 그대로 쓰면 칩이 빈
   글자로 떴다 */
/* 동시에 보내는 장수. 너무 크면 게이트웨이 · 브라우저 연결 수에 막힌다 */
const UPLOAD_PARALLEL = 3;

function firstProgress(ai) {
  if (Array.isArray(ai)) return ai.length ? { status: "done", pct: 100 } : null;
  if (!ai) return null;
  const status = ai.status ?? ai.run_status;
  if (!status) return null;
  return { ...ai, status, pct: ai.pct ?? (status === "done" ? 100 : 0) };
}

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
     쓰고, 그것도 없으면 과별 설정이 확정 · 재촬영을 건너뛴다 */
  const orderId = loc.state?.orderId ?? d.exam_order_id ?? d.order_id ?? null;
  const send = useCan(c.need.send);
  const run = useCan(c.need.run);
  const accept = c.acceptFor ? c.acceptFor(d) : c.accept;

  /* 이미 올라간 것(서버가 알려준 것)과 전송 중인 것을 가른다. 완료한
     파일은 반드시 uploadInfo를 다시 받아 표시한다 — 선택 목록만 보고
     "올라갔다"고 판단하면 실제 저장 실패를 놓친다. */
  const [picked, setPicked] = useState([]);
  const [dragging, setDragging] = useState(false);
  const [prog, setProg] = useState(() => firstProgress(d.ai));   // { status, pct }
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  /* 이번 [업로드] 한 번의 진행 — 파일 수 기준(fetch 는 한 장 안의 바이트 진행을 못 준다) */
  const [batch, setBatch] = useState(null);   // { total, done, failed }
  /* 품질 판정 — 영상만(upload.Quality). accepted · rejected · null */
  const [quality, setQuality] = useState(d.quality_status ?? null);

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
        state: "staged",     // 고르기만 하고 전송은 [업로드] 를 눌러야 한다
        error: null,
    }));
    setPicked((p) => [...p, ...uploads]);
  }

  /* [업로드] — 대기 중인 것만 실제로 보낸다. 고른 즉시 보내지 않는 이유:
     잘못 고른 촬영본을 전송 전에 [제외] 로 뺄 수 있어야 한다(서버 삭제
     경로가 없어, 올라간 뒤에는 못 되돌린다). */
  async function uploadAll() {
    const queue = picked.filter((f) => f.state === "staged");
    setBatch({ total: queue.length, done: 0, failed: 0 });
    /* 09-28 — 한 장씩 차례로 보내던 것을 UPLOAD_PARALLEL 장씩 동시에.
       목록은 끝나고 한 번만 다시 받는다(장마다 받으면 40장이면 40번) */
    const worker = async () => {
      for (let item = queue.shift(); item; item = queue.shift()) {
        const ok = await sendFile(item, false);
        setBatch((b) => b && { ...b, done: b.done + 1, failed: b.failed + (ok ? 0 : 1) });
      }
    };
    await Promise.all(Array.from({ length: UPLOAD_PARALLEL }, worker));
    reload(true);
  }

  async function sendFile(item, refresh = true) {
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
      if (refresh) reload(true);
      return true;
    } catch (e) {
      setPicked((files) => files.map((file) => file.id === item.id
        ? { ...file, state: "failed", error: e.message || "파일을 올리지 못했습니다." }
        : file));
      return false;
    }
  }

  /* 아직 전송 전인 파일은 즉시 목록에서 뺀다. 실제 서버에 올라간 파일의
     삭제는 파일 게이트웨이 삭제 API가 준비된 뒤에만 허용해야 한다 —
     화면에서만 지운 척하면 더 위험하다. */
  function removePicked(fileId) {
    setPicked((files) => files.filter((file) => file.id !== fileId));
  }

  const uploadedCount = (d.files ?? []).length;
  const uploadBusy = picked.some((file) => file.state === "uploading");
  const stagedCount = picked.filter((file) => file.state === "staged").length;
  /* 품질 칸이 있는 과는 승인해야 분석을 건다 — 반려한 촬영본을 분석에
     넘기지 않는다 */
  const gate = c.Quality ? quality === "accepted" : true;

  async function analyze() {
    if (stagedCount > 0) {
      setMsg("아직 업로드하지 않은 파일이 있습니다 — 먼저 업로드하세요.");
      return;
    }
    setBusy(true);
    setMsg(null);
    try {
      /* 영상: 오더 확정. ⚠ 조회한 자료를 같이 넘긴다 — 확정은 이
         화면의 id(study_id)가 아니라 오더 번호로 걸어야 한다
         (dept/radiology.jsx 의 complete 참고) */
      if (cfg.api.complete) {
        await cfg.api.complete(id, { ...d, exam_order_id: orderId });
      }
      await cfg.api.analyze(id);
      setProg({ status: "queued", pct: 0 });
    } catch (e) {
      setMsg(e.detail || "분석을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }

  let n = 0;
  const step = (t) => `${STEP[n++]} ${t}`;
  const why = !done && (uploadedCount === 0
    ? "파일을 올려야 분석을 시작할 수 있습니다"
    : !gate ? (quality === "rejected" ? "반려한 영상은 분석할 수 없습니다" : "먼저 품질을 승인하세요")
      : running ? "분석이 끝나면 판독으로 넘어갈 수 있습니다" : null);

  return (
    <>
      {/* ── 누구의 무엇인가 — 한 줄 ──────────────────────────── */}
      <div className="up-strip"><c.Info d={d} /></div>

      <div className="up-cols">
        <div className="up-col">
          {/* ── 올리는 곳 — 맨 위 ─────────────────────────────── */}
          <Card title="파일 올리기"
                right={<span className="muted small">업로드 {uploadedCount}</span>}>
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
              {c.hint && <small>{c.hint}</small>}
              <input ref={fileRef} type="file" multiple accept={accept}
                     onChange={choose} hidden />
              <Btn onClick={() => fileRef.current?.click()}
                   disabled={!send.ok} title={send.attrs.title}>파일 선택</Btn>
            </div>

            {/* 09-28 — 버튼 · 진행을 목록 위로. 파일이 많으면 목록 끝까지 내려가야 보였다 */}
            {(stagedCount > 0 || uploadBusy) && (
              <div className="up-actions">
                <Btn kind="fill" onClick={uploadAll} disabled={!send.ok || uploadBusy}>
                  {uploadBusy ? "업로드 중…" : `업로드 (${stagedCount})`}
                </Btn>
              </div>
            )}
            {batch && (uploadBusy || batch.done < batch.total) && (
              <div className="up-prog">
                <progress value={batch.done} max={batch.total} />
                <span>{batch.done} / {batch.total}장 · {Math.round((batch.done / batch.total) * 100)}%
                  {batch.failed > 0 && ` · 실패 ${batch.failed}`}</span>
              </div>
            )}

            <ul className="files up-files">
              {(d.files ?? []).map((f) => (
                <li key={f.id}>
                  <b>{f.name}</b><span>{f.size}</span>
                  <Chip tone="line">업로드 완료</Chip>
                </li>
              ))}
              {picked.map((f) => (
                <li key={f.id}>
                  <b>{f.name}</b><span>{f.size}</span>
                  <Chip tone={f.state === "failed" ? "fill" : f.state === "uploading" ? "dot" : "line"}>
                    {f.state === "failed" ? "전송 실패" : f.state === "uploading" ? "전송 중" : "업로드 전"}
                  </Chip>
                  {f.state !== "uploading" && (
                    <button className="btn ghost file-remove" type="button"
                            onClick={() => removePicked(f.id)}>
                      제외
                    </button>
                  )}
                  {f.state === "failed" && (
                    <button className="btn line file-retry" type="button" onClick={() => sendFile(f)}>
                      재시도
                    </button>
                  )}
                  {f.error && <small className="warnline">{f.error}</small>}
                </li>
              ))}
              {(d.files ?? []).length === 0 && picked.length === 0 && (
                <li className="none">아직 업로드한 파일이 없습니다</li>
              )}
            </ul>

          </Card>

          {c.Series && <c.Series d={d} />}
        </div>

        <div className="up-col">
          {/* ── ① 품질 — 영상만. 병리는 칸 자체가 없다(반려 경로가 없다) ── */}
          {c.Quality && (
            <Card title={step("품질 확인")}>
              <c.Quality cfg={cfg} id={id} d={d} orderId={orderId}
                         quality={quality} setQuality={setQuality} locked={Boolean(prog)} />
            </Card>
          )}

          {/* ── ② AI 분석 ────────────────────────────────────── */}
          <Card title={step("AI 분석")}
                right={prog && <Chip tone={tone("run", prog.status)}>{label(RUN_STATUS, prog.status)}</Chip>}>
            {prog ? (
              <>
                <Bar value={prog.pct ?? 0} label={label(RUN_STATUS, prog.status)} />
                {prog.status === "failed" && (
                  <p className="hint">분석에 실패했습니다. 다시 시도해 보시고, 계속 실패하면 담당자에게 알려 주세요.</p>
                )}
                {prog.abstained && (
                  <p className="hint">
                    <b>판정하지 못했습니다.</b> {prog.abstain_reason}
                    <br />분석 실패가 아닙니다. 직접 판독하시면 됩니다.
                  </p>
                )}
              </>
            ) : <p className="muted small">{c.estimate}</p>}
            {msg && <p className="hint">{msg}</p>}
            <div className="stack">
              <Btn kind={done ? "line" : "fill"} onClick={analyze}
                   disabled={busy || running || uploadedCount === 0 || !gate || !run.ok}
                   title={run.attrs.title}>
                {prog?.status === "failed" ? "다시 분석" : "AI 분석 시작"}
              </Btn>
            </div>
          </Card>

          {/* ── ③ 판독으로 ───────────────────────────────────── */}
          <Card title={step("판독")}>
            <div className="stack">
              <Btn kind={done ? "fill" : "line"} onClick={() => nav(cfg.go.read(id))} disabled={!done}>
                판독으로
              </Btn>
              {why && <span className="muted small">{why}</span>}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
