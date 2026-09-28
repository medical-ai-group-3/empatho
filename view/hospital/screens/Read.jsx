import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Btn, Card, Page } from "../lib/Page";
import { Chip, Locked, Save, Slide, Viewer } from "../lib/Parts";
import Stage, { MaskKeys } from "../lib/Stage";
import { useFile } from "../lib/files";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import * as H from "../dept/home";
import { MODALITY, eventDetail, label, modality as asModality } from "../codes";

/* MRI 뷰어(유방외과 검사 종합 확인에서 쓰는 것과 같은 컴포넌트) — 병리에는
 * 안 쓰고, 영상의학과라도 맘모·초음파만 보면 필요 없다. 늦게 불러온다
 * (lazy) — cornerstone3D·three.js가 무거워서(~500kB+) 정적으로 얹으면
 * MRI를 한 번도 안 보는 선생님도 매번 같이 받는다. */
const MRIReviewGrid = lazy(() => import("../lib/dicom/MRIReviewGrid"));
/* 맘모 DICOM 뷰어 — 공통 영상 Viewer 설계 3단계. MRI와 같은 이유로 lazy */
const DicomStackViewer = lazy(() => import("../lib/dicom/DicomStackViewer"));

/* ═══ 3장 · 판독 ═════════════════════════════════════════════════
 *
 * **무엇을 하는 자리인가**
 *   원본 위에 AI 결과를 얹어 보고, 내 소견을 써서 확정한다.
 *   확정하면 유방외과로 나간다. 되돌릴 수 없다(영상은 정정 화면으로만).
 *
 * **자리 (09-28 재배치)**
 *   맨 위 한 줄   제목 · 환자 띠(누구 · 번호 · 알레르기 · 의뢰 질문 · 이전 등급)
 *   왼쪽          검사/검체 정보 · 이전 검사(영상) · 영상 대조(병리)
 *   가운데        뷰어
 *   오른쪽        AI 요약(늘 보임) → AI 자세히(접힘) → 의사 소견 → 저장 줄(붙박이)
 *   ⚠ AI 를 탭 뒤에 두었더니 안 열어 보고 확정했다. 요약 한 줄은 늘 보이고
 *     자세한 것만 접는다. 「먼저 내 판독, 그다음 AI」 게이트는 팀 결정으로
 *     없앤 그대로다.
 *   ⚠ 저장 줄은 쓰는 칸 바로 아래 붙박이다. 화면 위 오른쪽 끝에 두면
 *     눈이 뷰어 → 폼 → 화면 위로 세 번 옮겨 갔다.
 *
 * **확정된 건은 읽기 전용이다.**
 *   영상 — 현재 확정 판독(assessments?study=)을 보여 주고 [판독 정정]으로 보낸다.
 *          여기서 다시 확정하면 초안이 없어 409 거나, 조용히 판정이 바뀐다.
 *   병리 — 정정 경로가 없다(확정 사양서 §8-2). 새 검체로 다시 받는다.
 *
 * **여기에 「분석 중」이 없다.**  분석은 2장에서 끝났다.
 * **탭이 없다.**  원본 한 장에 마스크를 얹고 투명도로 조절한다.
 * **AI 값과 사람 값을 섞지 않는다.**  다른 컬럼이고 화면에서도 다른 자리다.
 */

/* 다른 사람이 먼저 확정했거나 이미 확정된 건 — 서버 409 코드 */
const FINALIZED = new Set(["STUDY_ALREADY_FINALIZED", "SPECIMEN_ALREADY_FINALIZED"]);

/* 「AI 다시 실행」 뒤 진행을 묻는 간격 · 최대 시간. 맘모 한 번이 약 34초,
   서버가 GPU 메모리 부족이면 20초 · 60초 뒤 두 번 더 건다(tasks.py) */
const AI_POLL_MS = 4000;
const AI_POLL_MAX_MS = 20 * 60 * 1000;

/* 최신 AI 결과가 아직 도는 중인가 — 영상은 d.ai 가 가장 최근 행이다
   (병리는 크롭마다 배열이라 여기서 보지 않는다 — 다시 실행이 없다) */
const aiBusy = (d) => {
  const a = d?.ai;
  return Boolean(a && !Array.isArray(a) && (a.run_status === "queued" || a.run_status === "running"));
};

/* 주소의 물음표 앞이 같으면 앞의 것을 그대로 쓴다. 판독 응답을 다시 받을
   때마다 manifest 티켓이 새로 붙어 와서, 그대로 넘기면 뷰어가 처음부터
   다시 불러 보던 뷰 · 창값이 날아갔다(AI 진행을 묻는 동안 몇 초마다) */
const urlBase = (u) => String(u ?? "").split("?")[0];
function useStableUrl(url) {
  const [kept, setKept] = useState(url);
  if (!url) return url;
  if (!kept || urlBase(kept) !== urlBase(url)) { setKept(url); return url; }
  return kept;
}

export default function ReadScreen({ cfg }) {
  const c = cfg.read;
  const { id } = useParams();

  if (!can(c.need.view)) {
    return (
      <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}>
        <Locked what={c.title} />
      </Page>
    );
  }
  return <Load cfg={cfg} id={id} />;
}

function Load({ cfg, id }) {
  const c = cfg.read;
  const { loading, data, error, reload } = useApi(() => cfg.api.read(id), [id]);

  /* ⚠ 자료가 있으면 다시 부르는 중에도 Inner 를 그대로 둔다(reload(true)) —
     409 뒤에 읽기 전용으로 바꿔 열 때 안내 문구가 날아가면 안 된다 */
  if (data && !error) {
    return <Inner key={id} cfg={cfg} id={id} d={data} onStale={() => reload(true)}
                  onRefresh={() => reload(true)} />;
  }
  return (
    <Page className="read-page" title={c.title}>
      <Body loading={loading} error={error} onRetry={reload}>{null}</Body>
    </Page>
  );
}

function Inner({ cfg, id, d, onStale, onRefresh }) {
  const c = cfg.read;
  const nav = useNavigate();

  const [mask, setMask] = useState(45);            // 투명도 — 저장하지 않는다
  const [bright, setBright] = useState(100);      // 화면 보정 — 저장하지 않는다
  const [contrast, setContrast] = useState(100);
  const [full, setFull] = useState(false);
  const [pick, setPick] = useState(null);          // 고른 병변
  const [pendingMark, setPendingMark] = useState(null);
  const [slide, setSlide] = useState(0);           // 고른 크롭 · 시리즈
  const [inst, setInst] = useState(null);          // 스택 뷰어가 지금 보여 주는 장(SOP UID)
  const [f, setF] = useState(() => (c.seed ? c.seed(d) : d.doctor ?? {}));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  /* 상용구 — 판독 소견 끝에 한 줄로 붙인다 */
  const insert = (t) => setF((s) => {
    const prev = String(s.finding_note ?? "").trimEnd();
    return { ...s, finding_note: prev ? `${prev}\n${t}` : t };
  });

  const isFinal = Boolean(c.isFinal?.(d));
  /* 확정 판독 — 영상은 current_assessment 가 초안만 들고 있어 따로 받는다 */
  const fin = useApi(
    () => (isFinal && c.loadFinal ? c.loadFinal(id, d) : Promise.resolve(null)),
    [id, isFinal],
  );

  /* 환자 이력 한 번 — 지난 기록(드롭다운) · 이전 검사(왼쪽) · 이전 등급(띠)이 같이 쓴다 */
  const pid = d.patient?.id ?? null;
  const line = useApi(
    () => (pid != null && cfg.api.timeline ? H.soft(cfg.api.timeline(pid)) : Promise.resolve([])),
    [pid]);
  const events = H.rows(line.data);
  const priors = priorsOf(events, id);

  /* 뷰어에 무엇을 얹을지는 과별 설정이 정한다.
       병리 PNG 마스크 · 초음파 폴리곤 → SVG · 맘모 박스 → SVG ·
       MRI 는 원본이 DICOM Series 전체(Volume) — MRIReviewGrid 를 그린다.
     세 번째 값은 스택 뷰어의 지금 장 — 초음파처럼 장마다 AI 결과가 따로인
     과가 그 장의 것을 고른다(dept/radiology.jsx radStage) */
  const view = c.stage ? c.stage(d, slide, inst) : {};
  const stackManifest = useStableUrl(view.stackManifest);
  const isVolume = Boolean(view.volumeManifest);
  const isStack = Boolean(view.stackManifest);
  const isCornerstone = isVolume || isStack;

  /* ⚠ <img src> 는 Authorization 헤더를 못 보낸다 — fetch 로 받아 blob 주소로
     바꾼다(lib/files.js). 티켓이 열 범위 이름은 과별 설정이 들고 있다 */
  const scope = { kind: cfg.scopeKind, id };
  const img = useFile(view.image, cfg.api.ticket, scope);
  const msk = useFile(view.maskImage, cfg.api.ticket, scope);

  /* 과마다 임시저장 바디 모양이 다르다 — c.draftPayload 가 있으면 그걸 쓴다 */
  const payload = () => (c.draftPayload ? c.draftPayload(f) : {
    lesion_id: f.lesion_id ?? null,
    finding_note: f.finding_note ?? "",
    category: f.category ?? null,
  });

  /* 409 — 누가 먼저 확정했다. 읽기 전용으로 다시 연다 */
  function staleIf(e) {
    if (!FINALIZED.has(e?.code)) return false;
    setMsg("이미 확정된 판독입니다. 저장하지 않고 읽기 전용으로 다시 엽니다.");
    setBusy(false);
    onStale?.();
    return true;
  }

  async function draft() {
    setBusy(true); setMsg(null);
    try { await cfg.api.draft(id, payload()); setMsg("임시저장했습니다."); }
    catch (e) { if (!staleIf(e)) setMsg(e.detail || "임시저장에 실패했습니다."); }
    finally { setBusy(false); }
  }

  /* ⚠ **영상 확정은 바디를 안 읽는다.** 서버는 있는 임시저장 행을 final 로
       올릴 뿐이라, c.draftBeforeFinalize 인 과는 지금 값을 먼저 임시저장한다.
     병리는 확정이 바디를 읽는다 — 임시저장과 같은 모양(draftPayload)을 보낸다.
     확정 뒤에는 c.after 가 고른 다음 건으로 간다. 없으면 목록으로 */
  async function finalize() {
    setBusy(true); setMsg(null);
    const body = payload();
    if (c.draftBeforeFinalize) {
      try { await cfg.api.draft(id, body); }
      catch (e) {
        if (staleIf(e)) return;
        setMsg(`확정 전 임시저장에 실패해 확정하지 않았습니다 — ${e.detail || e.message || "다시 시도해 주세요."}`);
        setBusy(false);
        return;
      }
    }
    try { await cfg.api.finalize(id, body); }
    catch (e) {
      if (staleIf(e)) return;
      setMsg(c.draftBeforeFinalize
        ? `임시저장은 됐지만 확정에 실패했습니다 — ${e.detail || e.message || "다시 시도해 주세요."}`
        : e.detail || "확정에 실패했습니다.");
      setBusy(false);
      return;
    }
    /* 다음 건을 못 찾아도 확정은 끝났다 — 목록으로 */
    const next = c.after ? await c.after(id, d).catch(() => null) : null;
    nav(next != null ? cfg.go.read(next) : cfg.go.list());
  }

  const canAi = can(c.need.ai);

  /* ── AI 다시 실행 ─────────────────────────────────────────────
     서버가 잠깐 못 받아(GPU 메모리 부족 · 시간 초과 · 연결) 판정을 못 낸
     결과만 AI 소견 칸이 이 단추를 띄운다(dept/aiFailure.js). 권한 ·
     과 설정(c.need.run · cfg.api.analyze)이 있고 확정 전일 때만.
     POST 하면 새 행이 생긴다 — 판독 응답을 다시 받아 d.ai 가 그 행이 되면
     진행(GET /ai-results)을 묻다가, 끝나면 한 번 더 받아 결과를 그린다 */
  const canRun = Boolean(c.need.run && cfg.api.analyze && !isFinal && can(c.need.run));
  /* busy 는 누른 때의 d 에 묶는다 — 판독 응답을 다시 받으면(d 가 바뀌면) 풀린다 */
  const [rr, setRr] = useState({ busy: false, msg: null, at: null });
  const running = aiBusy(d);
  /* onRefresh 는 부를 때마다 새 함수다 — 의존성에 넣으면 그릴 때마다
     진행 묻기 타이머가 처음부터 다시 돈다 */
  const refresh = useRef(onRefresh);
  useEffect(() => { refresh.current = onRefresh; }, [onRefresh]);
  useEffect(() => {
    if (!running || !cfg.api.progress) return undefined;
    const t0 = Date.now();
    let stop = false;
    const t = setInterval(async () => {
      if (stop) return;
      if (Date.now() - t0 > AI_POLL_MAX_MS) { stop = true; clearInterval(t); return; }
      const p = await cfg.api.progress(id).catch(() => null);
      if (!stop && p && p.status !== "queued" && p.status !== "running") { stop = true; refresh.current?.(); }
    }, AI_POLL_MS);
    return () => { stop = true; clearInterval(t); };
  }, [running, id, cfg, d]);
  async function rerunAi() {
    setRr({ busy: true, msg: null, at: d });
    try {
      await cfg.api.analyze(id);
      refresh.current?.();
    } catch (e) {
      setRr({ busy: false, msg: e.detail || e.message || "AI를 다시 실행하지 못했습니다.", at: null });
    }
  }
  const rerun = canRun ? { run: rerunAi, busy: (rr.busy && rr.at === d) || running, msg: rr.msg } : null;
  const amendTo = cfg.amend && cfg.go.amend && can(cfg.amend.need.view) ? cfg.go.amend(id) : null;

  return (
    <Page className="read-page" title={c.title}
          right={<Strip cfg={cfg} d={d} priors={priors} events={events} isFinal={isFinal} />}>
      {msg && <div className="notice">{msg}</div>}
      {isFinal && (
        <div className="read-final" role="status">
          <b>확정된 {c.unitName ?? "판독"}입니다 · 읽기 전용</b>
          <span>{c.finalNote}</span>
          {amendTo && <Btn kind="fill" to={amendTo}>판독 정정</Btn>}
        </div>
      )}
      <div className={`read-cols${full ? " readfull" : ""}`}>
      <div className={`read-workspace${full ? " readfull" : ""}`}>
      <Card pad={false}>
        <Viewer
          stack
          infoName={c.infoName}
          info={<>
            <c.Info d={d} cfg={cfg} slide={slide} onSlide={setSlide} />
            {c.priors && <Priors cfg={cfg} rows={priors} loading={line.loading} />}
          </>}

          /* AI 소견은 **권한이 없으면 칸 자체가 없다.** 접힌 게 아니라 없는
             것이다. pick·onPick — 소견에서 병변을 고르면 뷰어가 밝힌다.
             slide·onSlide — 병리는 AI 카드가 크롭을 바꾼다 */
          ai={canAi ? <c.Ai d={d} view={view} pick={pick} onPick={setPick}
                            slide={slide} onSlide={setSlide} rerun={rerun}
                            summarized={Boolean(c.AiSummary)} /> : null}
          aiSummary={canAi && c.AiSummary
            ? <c.AiSummary d={d} view={view} pick={pick} onPick={setPick}
                           slide={slide} onSlide={setSlide} rerun={rerun} />
            : null}

          doctorName={isFinal ? "확정 판독" : "의사 소견"}
          doctor={isFinal
            ? <Body loading={fin.loading} error={null} skeleton="list">
                <c.Final d={d} fin={fin.data} failed={Boolean(fin.error)} />
              </Body>
            : <c.Doctor d={d} f={f} set={set} pendingMark={pendingMark}
                        onLesionCreated={() => setPendingMark(null)}
                        phrases={c.phrases} insert={insert} />}
          doctorOpen

          /* 확정된 건은 저장 줄이 없다 — [판독 정정]은 위 안내 띠에 있다 */
          foot={isFinal ? null
            : <Save
                hint={c.saveHint}
                onDraft={draft} onSave={finalize} busy={busy}
                draftNeed={c.need.draft} saveNeed={c.need.finalize}
                canSave={c.ready ? c.ready(f, d) : true}
                saveLabel={c.after ? "확정 → 다음 건" : "확정"}
              />}

          below={
            isCornerstone ? null : (
              <div className="vknobs">
                <Slide label={view.maskImage ? "마스크 투명도" : "표시 투명도"}
                       value={mask} onChange={setMask} />
                {/* 어느 색이 무엇인지 적는다. 색만 있고 뜻이 없으면 못 읽는다 */}
                {msk.src && <MaskKeys legend={view.maskLegend} colors={view.maskColors} />}
                {/* 원본이 서버에서 8bit PNG 로 와서 **창값 조절은 못 한다.**
                    이건 화면 보정일 뿐이다 — AI 도 같은 8bit 변환본을 본다 */}
                <Slide label="밝기" value={bright} onChange={setBright}
                       min={30} max={200} />
                <Slide label="대비" value={contrast} onChange={setContrast}
                       min={30} max={250} />
                <span className="muted small">
                  화면 표시용 보정입니다(W/L 조정 아님)
                  {view.window ? ` · 서버 변환 ${view.window}` : ""}
                </span>
              </div>
            )
          }
        >
          {isVolume ? (
            <div className="mri-viewer-slot">
              <Suspense fallback={<div className="mri-loading">MRI 뷰어 불러오는 중…</div>}>
                <MRIReviewGrid
                  lesions={d.lesions}
                  study={{ volume_manifest: view.volumeManifest, volume_base: view.volumeBase, anatomy_meshes: d.anatomy_meshes }}
                  issue={cfg.api.ticket}
                  focusSlice={pick && typeof pick === "object" ? pick.slice : null}
                  mode="diagnostic"
                  onAnnotation={setPendingMark}
                />
              </Suspense>
            </div>
          ) : isStack ? (
            <div className="mri-viewer-slot">
              <Suspense fallback={<div className="mri-loading">유방촬영 뷰어 불러오는 중…</div>}>
                <DicomStackViewer
                  manifestUrl={stackManifest}
                  baseUrl={view.stackBase}
                  views={view.views}
                  mode="diagnostic"
                  onAnnotation={setPendingMark}
                  overlay={view.overlay}
                  pick={pick}
                  focusSop={pick != null ? view.where?.(pick)?.sop ?? null : null}
                  onInstance={setInst}
                />
              </Suspense>
            </div>
          ) : (
            <Stage
              src={img.src} w={view.w} h={view.h} alt={view.alt}
              loading={img.loading} loadError={img.error}
              bright={bright} contrast={contrast}
              mask={msk.src} maskColors={view.maskColors} shapes={view.shapes ?? []}
              opacity={mask}
              pick={pick} onPick={setPick}
              annotationTools={cfg.scopeKind === "study" && !isFinal}
              onAnnotation={setPendingMark}
              full={full} onFull={() => setFull((v) => !v)}
            />
          )}
        </Viewer>
      </Card>
      </div>
      </div>
    </Page>
  );
}

/* ── 맨 위 환자 띠 ─────────────────────────────────────────────
 * 과별 설정(c.strip)이 [이름, 값, 강조] 줄을 준다. 이전 등급처럼 이력이
 * 있어야 아는 값은 priors 로 넘겨 준다. 지난 기록 드롭다운이 오른쪽 끝 */
function Strip({ cfg, d, priors, events, isFinal }) {
  const items = (cfg.read.strip?.(d, { priors }) ?? []).filter((x) => x && x[1] != null && x[1] !== "");
  return (
    <div className="read-strip">
      {items.map(([k, v, warn], i) => (
        <span key={i} className={`rs-i${warn ? " warn" : ""}`}>
          {k && <em>{k}</em>}<b title={typeof v === "string" ? v : undefined}>{v}</b>
        </span>
      ))}
      <span className="rs-end">
        {isFinal && <Chip tone="dot">확정</Chip>}
        <PastRail events={events} />
      </span>
    </div>
  );
}

/* 타임라인 → 이 환자의 다른 검사. 촬영 줄이 날짜 · 모달리티를, 판독 줄
   (초안 제외)이 BI-RADS 를 준다. study_id 가 없는 옛 서버 줄은 못 묶는다 */
function priorsOf(rows, currentId) {
  const by = new Map();
  for (const r of rows) {
    const sid = r?.study_id;
    if (sid == null) continue;
    const p = by.get(String(sid)) ?? { id: sid, at: null, modality: null, birads: null };
    if (r.modality) p.modality = r.modality;
    if (r.type === "촬영") { p.at = r.at; p.modality = r.modality ?? r.detail ?? p.modality; }
    else if (r.type === "판독" && r.read_stage !== "draft" && r.detail) p.birads = r.detail;
    if (!p.at) p.at = r.at;
    by.set(String(sid), p);
  }
  by.delete(String(currentId));
  return [...by.values()].sort((a, b) => String(b.at ?? "").localeCompare(String(a.at ?? "")));
}

/* ── 왼쪽 · 이전 검사 (영상) ──────────────────────────────────
 * 누르면 **새 탭**에서 그 검사의 판독을 연다 — 쓰던 소견이 날아가면 안 된다.
 * ⚠ window.open 에 noopener 를 주지 않는다. 주면 sessionStorage(로그인)가
 *   새 탭으로 안 넘어가 로그인 화면이 뜬다. 같은 출처라 opener 는 바로 끊는다 */
function Priors({ cfg, rows, loading }) {
  const open = (sid) => {
    const w = window.open(cfg.go.read(sid), "_blank");
    if (w) w.opener = null;
  };
  return (
    <section className="priors" aria-label="이전 검사">
      <h3>이전 검사 <em>{loading ? "…" : rows.length}</em></h3>
      {!loading && rows.length === 0 && <p className="muted small">이전 검사가 없습니다</p>}
      {rows.map((p) => (
        <button type="button" key={p.id} className="prior" onClick={() => open(p.id)}
                title="새 탭에서 이 검사의 판독을 엽니다">
          <time>{H.day(p.at)}</time>
          <span>{label(MODALITY, asModality(p.modality)) || "검사"}</span>
          <b>{p.birads ? `BI-RADS ${String(p.birads).replace(/^BI-RADS\s*/i, "")}` : "판독 없음"}</b>
          <i aria-hidden="true">↗</i>
        </button>
      ))}
    </section>
  );
}

/* ── 지난 기록 (전체 타임라인) ─────────────────────────────────
 * 날짜를 크게, 그 아래 그날 무슨 일이 있었는지. 색을 쓰지 않는다.
 * ⚠ 눌러도 화면을 안 옮긴다 — 쓰던 소견이 날아가면 안 된다. 검사로 가는
 *   길은 왼쪽 「이전 검사」(새 탭)다 */
function PastRail({ events }) {
  const [open, setOpen] = useState(false);
  const rows = [...events].reverse();

  return (
    <div className="prail-drop">
      <button type="button" className="btn line sm" aria-expanded={open}
              onClick={() => setOpen((v) => !v)}>
        지난 기록 <em>{rows.length}</em> {open ? "▴" : "▾"}
      </button>
      {open && (
        <nav className="prail" aria-label="이 환자의 지난 기록">
          <div className="prail-b">
            {rows.length === 0
              ? <p className="hcard-k hpad">아직 없습니다</p>
              : rows.map((r, i) => (
                <article className="prail-day" key={`${r.at}-${i}`}>
                  <time>{H.day(r.at)}</time>
                  <span className="prail-k">{r.type}</span>
                  {eventDetail(r) && <b>{eventDetail(r)}</b>}
                </article>
              ))}
          </div>
        </nav>
      )}
    </div>
  );
}
