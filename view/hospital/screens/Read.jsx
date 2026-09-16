import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Body } from "../lib/Body";
import { Card, Page } from "../lib/Page";
import { Chip, Locked, Save, Slide, Viewer } from "../lib/Parts";
import Stage from "../lib/Stage";
import { useFile } from "../lib/files";
import { useApi } from "../lib/useApi";
import { can } from "../perm";

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
    <Page crumb={[cfg.name, c.title]} title={c.title} sub={c.sub}
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
  const [slide, setSlide] = useState(0);           // 고른 크롭 · 시리즈
  const [f, setF] = useState(d.doctor ?? {});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));

  /* 뷰어에 무엇을 얹을지는 과별 설정이 정한다.
       병리    PNG 마스크
       초음파  폴리곤 → SVG
       맘모    박스 → SVG
     화면은 어느 쪽인지 몰라도 된다 — 둘 다 같은 자리에 겹쳐 놓는다 */
  const view = c.stage ? c.stage(d, slide) : {};

  /* 원본과 마스크는 Go 관문에서 온다.
     ⚠ <img src> 는 Authorization 헤더를 못 보낸다. 그래서 여기서 fetch 로
       받아 blob 주소로 바꾼다 — 자세한 이유는 lib/files.js 참고 */
  const img = useFile(view.image, cfg.api.ticket, id);
  const msk = useFile(view.maskImage, cfg.api.ticket, id);

  /* 임시저장은 여기 머문다. 저장은 다른 과로 나간다 — 둘의 차이가
     버튼 위 한 줄에 적혀 있어야 한다 */
  async function draft() {
    setBusy(true); setMsg(null);
    try { await cfg.api.draft(id, f); setMsg("임시저장했습니다."); }
    catch (e) { setMsg(e.detail || "임시저장에 실패했습니다."); }
    finally { setBusy(false); }
  }

  async function finalize() {
    setBusy(true); setMsg(null);
    try { await cfg.api.finalize(id, f); nav(cfg.go.list()); }
    catch (e) { setMsg(e.detail || "저장에 실패했습니다."); setBusy(false); }
  }

  return (
    <div className={full ? "readfull" : undefined}>
      <Card pad={false}>
        <Viewer
          infoName={c.infoName}
          info={<c.Info d={d} cfg={cfg} slide={slide} onSlide={setSlide} />}

          /* AI 소견은 **권한이 없으면 패널 자체가 없다.** 접힌 게 아니라
             없는 것이다 — 있는데 못 연다고 하면 계속 누르게 된다 */
          ai={can(c.need.ai) ? <c.Ai d={d} /> : null}
          aiOpen={false}

          doctor={<c.Doctor d={d} f={f} set={set} />}
          doctorOpen

          below={
            <div className="vknobs">
              <Slide label={view.maskImage ? "마스크 투명도" : "표시 투명도"}
                     value={mask} onChange={setMask} />
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
          }
        >
          <Stage
            src={img.src} w={view.w} h={view.h} alt={view.alt}
            loading={img.loading} loadError={img.error}
            bright={bright} contrast={contrast}
            mask={msk.src} shapes={view.shapes ?? []}
            opacity={mask}
            pick={pick} onPick={setPick}
            full={full} onFull={() => setFull((v) => !v)}
          />
        </Viewer>
      </Card>

      {msg && <div className="notice">{msg}</div>}

      <Save
        hint={c.saveHint}
        onDraft={draft} onSave={finalize} busy={busy}
        draftNeed={c.need.draft} saveNeed={c.need.finalize}
        canSave={c.ready ? c.ready(f) : true}
        saveLabel="저장"
      />
    </div>
  );
}
