import { Suspense, lazy, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Card, Page } from "../lib/Page";
import { Chip, Locked, Save, Slide, Viewer } from "../lib/Parts";
import Stage, { MaskKeys } from "../lib/Stage";
import { useFile } from "../lib/files";
import { useApi } from "../lib/useApi";
import { can } from "../perm";
import * as H from "../dept/home";

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
 *   [저장]을 누르면 유방외과로 나간다. 되돌릴 수 없다.
 *
 * **여기에 「분석 중」이 없다.**
 *   분석은 2장에서 끝났다. 안 끝났으면 여기로 못 들어온다. 들어왔다는
 *   것은 AI 결과가 이미 있다는 뜻이다.
 *
 * **1차 판독 게이트가 없다.**
 *   「내 판독을 먼저 잠그고 그다음 AI 를 공개한다」는 순서는 팀 결정으로
 *   없앴다. 그래서 [AI 활성화] 버튼도 없다. AI 를 볼지 말지는 패널을
 *   접었다 펴는 것으로 정한다.
 *
 * **탭이 없다.**
 *   초안에 있던 상단 탭 다섯(전체 보기 · 조직 분할 · 세포 검출 · 히트맵 ·
 *   오버레이)을 뺐다. 나눠 보면 같은 자리를 다른 화면에서 봐야 해서
 *   「이 점이 저기 어디였지」가 생긴다. 원본 한 장에 마스크를 얹고
 *   투명도로 조절한다.
 *
 * **AI 값과 사람 값을 섞지 않는다.**
 *   AI 가 낸 등급·크기와 의사가 적은 등급·크기는 다른 컬럼이다.
 *   화면에서도 다른 자리에 둔다.
 */

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

  return (
    <Page className="read-page" crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}
          right={data && <Chip>{data.patient.name} · {data.unit.no}</Chip>}>
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner cfg={cfg} id={id} d={data} />}
      </Body>
    </Page>
  );
}

function Inner({ cfg, id, d }) {
  const c = cfg.read;
  const nav = useNavigate();

  const [mask, setMask] = useState(45);            // 투명도 — 저장하지 않는다
  const [bright, setBright] = useState(100);      // 화면 보정 — 저장하지 않는다
  const [contrast, setContrast] = useState(100);
  const [full, setFull] = useState(false);
  const [pick, setPick] = useState(null);          // 고른 병변
  const [pendingMark, setPendingMark] = useState(null);
  const [slide, setSlide] = useState(0);           // 고른 크롭 · 시리즈
  const [f, setF] = useState(d.doctor ?? {});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  /* 뷰어에 무엇을 얹을지는 과별 설정이 정한다.
       병리    PNG 마스크
       초음파  폴리곤 → SVG
       맘모    박스 → SVG
       MRI     원본이 한 장이 아니라 DICOM Series 전체(Volume)다 — 2D
               이미지 자리에 못 얹는다. stage()가 volume_manifest를
               주면 화면은 이미지 대신 유방외과 검사 종합 확인과 같은
               MRIReviewGrid(3D 병변 위치·3D 병변 + Axial/Coronal/
               Sagittal)를 그린다.
     화면은 어느 쪽인지 몰라도 된다 — 셋 다 같은 자리에 겹쳐 놓는다 */
  const view = c.stage ? c.stage(d, slide) : {};
  const isVolume = Boolean(view.volumeManifest);
  const isStack = Boolean(view.stackManifest);
  const isCornerstone = isVolume || isStack;

  /* 원본과 마스크는 Go 관문에서 온다.
     ⚠ <img src> 는 Authorization 헤더를 못 보낸다. 그래서 여기서 fetch 로
       받아 blob 주소로 바꾼다 — 자세한 이유는 lib/files.js 참고

     티켓이 열 범위를 같이 넘긴다. 과마다 단위가 달라서(병리는 검체,
     영상은 검사) 이름을 과별 설정이 들고 있다 */
  const scope = { kind: cfg.scopeKind, id };
  const img = useFile(view.image, cfg.api.ticket, scope);
  const msk = useFile(view.maskImage, cfg.api.ticket, scope);

  /* 임시저장은 여기 머문다. 저장은 다른 과로 나간다 — 둘의 차이가
     버튼 위 한 줄에 적혀 있어야 한다 */
  async function draft() {
    setBusy(true); setMsg(null);
    const payload = {
      lesion_id: f.lesion_id ?? null,
      finding_note: f.finding_note ?? "",
      category: f.category ?? null,
    };
    try { await cfg.api.draft(id, payload); setMsg("임시저장했습니다."); }
    catch (e) { setMsg(e.detail || "임시저장에 실패했습니다."); }
    finally { setBusy(false); }
  }

  async function finalize() {
    setBusy(true); setMsg(null);
    try { await cfg.api.finalize(id, f); nav(cfg.go.list()); }
    catch (e) { setMsg(e.detail || "저장에 실패했습니다."); setBusy(false); }
  }

  return (
    /* 4.4 히스토리 레일 — **판독은 이전과 견주는 일이다.**
       왼쪽에 이 환자의 지난 기록, 가운데가 뷰어, 오른쪽이 쓰는 칸.
       ⚠ 목업(Read.html)의 왼쪽 104px 은 **이번 검사의 섬네일 줄**인데
         4.4 가 거기를 「이 환자의 지난 검사」로 못 박았다. 섬네일은 이미
         뷰어 안에 있고(시리즈 전환), 화면을 나갔다 오지 않고 8mm → 12mm
         를 보려면 지난 기록이 그 자리에 있어야 한다.
       ⚠ 전체화면이면 레일을 접는다 — 그때는 영상만 본다 */
    <div className={`read-cols${full ? " readfull" : ""}`}>
      {!full && <PastRail cfg={cfg} patientId={d.patient?.id} />}
      <div className={`read-workspace${full ? " readfull" : ""}`}>
      <Card pad={false}>
        <Viewer
          infoName={c.infoName}
          info={<c.Info d={d} cfg={cfg} slide={slide} onSlide={setSlide} />}

          /* AI 소견은 **권한이 없으면 패널 자체가 없다.** 접힌 게 아니라
             없는 것이다 — 있는데 못 연다고 하면 계속 누르게 된다.

             pick·onPick 을 같이 넘긴다 — 소견 목록에서 병변 하나를
             고르면 뷰어가 그 도형을 밝힌다. 뷰어(Stage)와 도형 만드는
             자리(boxesFromLesions)는 진작 같은 id 로 맞춰져 있었는데,
             **패널에 손잡이를 안 줘서 서로 말을 못 하고 있었다.** */
          ai={can(c.need.ai)
            ? <c.Ai d={d} pick={pick} onPick={setPick} />
            : null}
          aiOpen={false}

          doctor={<c.Doctor d={d} f={f} set={set} pendingMark={pendingMark}
                             onLesionCreated={() => setPendingMark(null)} />}
          doctorOpen

          below={
            isCornerstone ? null : (
              <div className="vknobs">
                <Slide label={view.maskImage ? "마스크 투명도" : "표시 투명도"}
                       value={mask} onChange={setMask} />
                {/* 어느 색이 무엇인지 적는다. 색만 있고 뜻이 없으면
                    주황이 종양인지 간질인지 알 수 없다 */}
                {msk.src && <MaskKeys legend={view.maskLegend} colors={view.maskColors} />}
                {/* 원본이 서버에서 8bit PNG 로 변환돼 오므로 **창값 조절은
                    못 한다.** 이건 화면 보정일 뿐이고, 판독의가 창값으로
                    오해하지 않게 이름을 그렇게 붙였다.
                    AI 도 같은 8bit 변환본을 보고 판단한다 — 화면과 AI 가
                    같은 것을 보게 하려는 것이 이 선택의 이유다 */}
                <Slide label="밝기" value={bright} onChange={setBright}
                       min={30} max={200} />
                <Slide label="대비" value={contrast} onChange={setContrast}
                       min={30} max={250} />
                <span className="muted small">
                  화면 보정입니다. 창값(window/level)이 아닙니다
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
                  study={{ volume_manifest: view.volumeManifest, volume_base: view.volumeBase }}
                  mode="diagnostic"
                  onAnnotation={setPendingMark}
                />
              </Suspense>
            </div>
          ) : isStack ? (
            <div className="mri-viewer-slot">
              <Suspense fallback={<div className="mri-loading">맘모 뷰어 불러오는 중…</div>}>
                <DicomStackViewer
                  manifestUrl={view.stackManifest}
                  baseUrl={view.stackBase}
                  mode="diagnostic"
                  onAnnotation={setPendingMark}
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
              annotationTools={cfg.scopeKind === "study"}
              onAnnotation={setPendingMark}
              full={full} onFull={() => setFull((v) => !v)}
            />
          )}
        </Viewer>
      </Card>

      {msg && <div className="notice">{msg}</div>}

      <Save
        hint={c.saveHint}
        onDraft={draft} onSave={finalize} busy={busy}
        draftNeed={c.need.draft} saveNeed={c.need.finalize}
        canSave={c.ready ? c.ready(f, d) : true}
        saveLabel="저장"
      />
      </div>
    </div>
  );
}

/* ── 왼쪽 레일 — 이 환자의 지난 기록 (4.4) ──────────────────────
 * 날짜를 크게, 그 아래 그날 무슨 일이 있었는지. **색을 쓰지 않는다.**
 *
 * ⚠ **지난 «검사»를 따로 부를 경로가 없다.** `/patients/{id}/studies` 는
 *   api.js 에서 유방외과 것으로만 열려 있고 새 경로는 안 판다. 대신
 *   `timeline(pid)` 이 촬영·판독·검체·확진을 날짜로 주고, 판독 줄은
 *   BI-RADS 를 `detail` 에 달고 온다 — 견주는 데 필요한 것이 그 값이다.
 * ⚠ **눌러도 화면을 안 옮긴다.** 쓰던 소견이 날아가면 안 된다. 그 날짜의
 *   영상을 가운데에 띄우려면 study 를 날짜로 찾는 경로가 있어야 한다(8장).
 */
function PastRail({ cfg, patientId }) {
  const line = useApi(
    () => (patientId ? H.soft(cfg.api.timeline(patientId)) : Promise.resolve([])),
    [patientId]);
  const rows = [...H.rows(line.data)].reverse();

  return (
    <nav className="prail" aria-label="이 환자의 지난 기록">
      <header className="prail-h">
        <b>지난 기록</b>
        <em>{rows.length}</em>
      </header>
      <div className="prail-b">
        {/* 맨 위는 항상 「지금」이다 — 돌아올 곳이 분명해야 한다 */}
        <p className="prail-now">지금 판독</p>
        {rows.length === 0
          ? <p className="hcard-k hpad">아직 없습니다</p>
          : rows.map((r, i) => (
            <article className="prail-day" key={`${r.at}-${i}`}>
              <time>{H.day(r.at)}</time>
              <span className="prail-k">{r.type}</span>
              {r.detail && <b>{r.detail}</b>}
            </article>
          ))}
      </div>
    </nav>
  );
}
