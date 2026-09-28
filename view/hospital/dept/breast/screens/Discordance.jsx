import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";
import "../breast.css";
import ReviewViewer from "../components/ReviewViewer";
import ImagePopup from "../components/ImagePopup";

/* 유방외과 · 불일치 처분 — `docs/mockup/SurgeryDiscordance.html`
 * ════════════════════════════════════════════════════════════════
 *
 * 영상과 병리가 엇갈린 건만 모인다. 왼쪽에 엇갈린 것, 오른쪽에 처분.
 *
 *   ┌ 1fr ─────────────────────────┬ 380px ─────────┐
 *   │ 김민지 47·여   [영상 확인][상세]│ 처분            │
 *   │ 규칙 한 줄                    │ ○ 재조직검사    │
 *   │ ┌영상 판독────┬병리 판독────┐  │ ○ 수술적 절제   │
 *   │ └─────────────┴─────────────┘  │ ○ 종결          │
 *   │ 처분 기다리는 불일치 (내 담당)  │ 판단 근거       │
 *   │  · 김민지 …   보는 중          │                 │
 *   │  · 오세라 …   ›                │ [처분 확정]     │
 *   └──────────────────────────────┴────────────────┘
 *
 * ⚠ **「판독 후 3일」을 안 쓴다.** 목업 표의 그 칸은 경과 시간이다.
 *   대신 판독 날짜를 적는다 — 언제 났는지는 서버가 준다.
 * 왼쪽 아래에 **내 담당의 열린 불일치 목록**을 둔다(09-28). 전에는 주소로
 *   들어온 한 건뿐이라 그 아래가 통째로 비었고, 다음 건을 찾으려면 대기
 *   환자로 돌아가야 했다. GET /discordances?status=open&primary_staff=me —
 *   옛 서버가 primary_staff 를 모르면 과 전체 열린 것으로 물러난다(api.js).
 *   ⚠ 주소 없이 여는 목록 화면은 없다 — 경로(nav.js)가 한 건짜리뿐이다.
 * ⚠ **되돌릴 수 없다.** 처분하면 flag 가 닫히고 치료 방침 결정이 열린다.
 *   그래서 처분하면 **같은 환자의 치료 방침(수술 여부 칸)** 으로 간다 —
 *   전에는 대기 환자로 돌아가서, 방금 열린 결정을 다시 찾아 들어가야 했다.
 */
/* ⚠ **서버가 받는 값만 둔다** — DISPOSITION_TYPE 은 셋이다
     (rebiopsy · excision · no_action, models.py).
   ⚠ 「단기 추적 (6개월)」을 뺐다(09-23). 서버에 그 값이 없어서 고르면
     400 이었다 — 고를 수 있는데 안 되는 단추는 없는 단추보다 나쁘다.
     추적으로 처분하는 길이 필요하면 서버 enum 부터 늘려야 한다. */
const DISPOSE = [
  { v: "rebiopsy", label: "재조직검사" },
  { v: "excision", label: "수술적 절제" },
  { v: "no_action", label: "불일치 아님 — 종결" },
];

export default function Discordance() {
  const { id } = useParams();
  const nav = useNavigate();
  const one = useApi(() => api.discordance(id), [id]);

  return (
    <Page className="disc-page" crumb={["유방외과", "불일치 처분"]}
          title="불일치 처분"
          right={<Btn to={go.breast.waiting()}>대기 환자</Btn>}>
      <Body loading={one.loading && !one.data} error={one.error} onRetry={one.reload}>
        {one.data && (
          <div className="disc">
            <Compare key={one.data.discordance_id} d={one.data} />
            {/* ⚠ **처분 여부는 closed_at 이다.** flag_status 에는 "open" 이란
                값이 아예 없어서(pass·sev1·sev2·review·unbindable) 이 판단이
                늘 참이었다 — 어느 건을 열어도 「이미 처분된 건입니다」였다
                (09-23 확인). 서버가 열린 것을 고르는 기준도 closed_at 이다 */}
            <Dispose key={`d-${one.data.discordance_id}`} d={one.data}
                     done={Boolean(one.data.closed_at)}
                     onDone={() => {
                       const pid = one.data.patient?.patient_id ?? one.data.patient_id;
                       nav(pid != null ? go.breast.decision(pid, "decision") : go.breast.waiting());
                     }} />
          </div>
        )}
      </Body>
    </Page>
  );
}

/* 왼쪽 — 무엇이 엇갈렸나. 두 판독을 나란히 놓는다 */
function Compare({ d }) {
  const p = d.patient ?? {};
  const pid = p.patient_id ?? d.patient_id;
  const rad = d.radiology_reading ?? {};
  const pat = d.pathology_reading ?? {};
  const [seeing, setSeeing] = useState(false);

  return (
    <div className="disc-l">
      <header className="disc-h">
        <span className="work-1">
          <b>{H.nameOf(p)}</b>
          {H.who(p) && <span>{H.who(p)}</span>}
        </span>
        <span className="home-fill" />
        {d.lesion && (
          <Chip>{d.lesion.label ?? d.lesion.site ?? "병변"}
            {(d.lesion.measured_size_mm ?? d.lesion.ai_size_mm ?? d.lesion.size_mm) != null
              && ` · ${d.lesion.measured_size_mm ?? d.lesion.ai_size_mm ?? d.lesion.size_mm}mm`}
          </Chip>
        )}
        {/* 유방외과는 판독 화면 권한이 없다 — 영상 · 병리를 보는 길은 이 팝업 */}
        {pid != null && <Btn onClick={() => setSeeing(true)}>영상 확인</Btn>}
        {pid != null && <Btn to={go.breast.review(pid)}>환자 상세</Btn>}
      </header>

      {/* 규칙이 무엇을 걸었는지 — 사람이 읽는 한 줄이다 */}
      <p className="disc-rule">{d.violated_rule}</p>

      <div className="disc-vs">
        <Side title="영상 판독" r={rad} big={rad.assessment} />
        <Side title="병리 판독" r={pat} big={pat.assessment} />
      </div>

      <MyOpen here={d.discordance_id} />

      {seeing && (
        <ImagePopup name={H.nameOf(p)} onClose={() => setSeeing(false)}>
          <ReviewViewer patientId={pid}
                        specimenIds={[d.lesion?.specimen_id].filter((x) => x != null)} />
        </ImagePopup>
      )}
    </div>
  );
}

function Side({ title, r, big }) {
  return (
    <section className="disc-side">
      <header>
        <h3>{title}</h3>
        <span className="home-fill" />
        {H.day(r.read_at) && <time>{H.day(r.read_at)}</time>}
      </header>
      <b className="disc-big">{big ?? "아직 없습니다"}</b>
      {r.finding && <p className="disc-find">{r.finding}</p>}
      {r.assessor && <span className="hcard-k">{r.assessor}</span>}
    </section>
  );
}

/* 내 담당의 열린 불일치 — 다음 건으로 바로 간다. 지금 보는 건은 표시만 */
function MyOpen({ here }) {
  const list = useApi(() => api.myDiscordances(), []);
  const rows = list.data ?? [];
  return (
    <section className="bf-odds">
      <header className="bcol-h">
        <i className="hdot ring" aria-hidden="true" />
        <b>처분 기다리는 불일치</b>
        <em>{rows.length}</em>
      </header>
      <Body loading={list.loading && !list.data} error={list.error} onRetry={list.reload}>
        {rows.length === 0
          ? <p className="hcard-k hpad">열린 불일치가 없습니다</p>
          : (
            <ul className="bf-odds-l">
              {rows.map((r) => {
                const on = String(r.discordance_id) === String(here);
                return (
                  <li key={r.discordance_id}>
                    <Link to={go.breast.discordance(r.discordance_id)}
                          className={on ? "on" : undefined} aria-current={on || undefined}>
                      <b>{r.patient_name ?? r.patient?.name ?? H.nameOf(r)}</b>
                      <span>{r.violated_rule ?? r.summary ?? "—"}</span>
                      <time>{H.day(r.created_at) ?? ""}</time>
                      <i aria-hidden="true">{on ? "보는 중" : "›"}</i>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
      </Body>
    </section>
  );
}

/* 오른쪽 — 처분. 고르는 것과 확정하는 것을 두 걸음으로 나눈다 */
function Dispose({ d, done, onDone }) {
  const [pick, setPick] = useState(null);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const may = useCan("breast.discordance.dispose");

  async function send() {
    if (!pick) return;
    setBusy(true);
    setErr(null);
    try {
      /* ⚠ 칸 이름이 서버와 달랐다 — disposition/reason 으로 보내고 있었는데
         DiscordanceDisposeSerializer 는 disposition_type/disposition_reason
         을 받는다. 늘 400 이었다(09-23 확인) */
      await api.dispose(d.discordance_id, {
        disposition_type: pick,
        disposition_reason: why,
      });
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  if (done) {
    const pid = d.patient?.patient_id ?? d.patient_id;
    return (
      <aside className="disc-r">
        <header className="bcol-h"><i className="hdot" aria-hidden="true" /><b>처분</b></header>
        <Empty title="이미 처분된 건입니다" />
        {pid != null && (
          <footer className="disc-f">
            <span className="home-fill" />
            <Btn kind="fill" to={go.breast.decision(pid, "decision")}>치료 방침으로 →</Btn>
          </footer>
        )}
      </aside>
    );
  }

  return (
    <aside className="disc-r">
      <header className="bcol-h">
        <i className="hdot" aria-hidden="true" />
        <b>처분</b>
      </header>
      <div className="disc-r-b">
        <div className="ndocs one" role="radiogroup" aria-label="처분">
          {DISPOSE.map((o) => (
            <button type="button" key={o.v} role="radio" aria-checked={o.v === pick}
                    className={`ndoc${o.v === pick ? " on" : ""}`}
                    disabled={!may.ok} onClick={() => setPick(o.v)}>
              <i aria-hidden="true" />
              <b>{o.label}</b>
            </button>
          ))}
        </div>

        <label className="disc-why">
          <span>판단 근거</span>
          <textarea value={why} onChange={(e) => setWhy(e.target.value)}
                    rows={3} disabled={!may.ok} />
        </label>

        {err && <p className="note err">{err}</p>}
      </div>

      <footer className="disc-f">
        {/* ⚠ 9장이 남기라고 한 되돌릴 수 없다는 말 */}
        <span className="hcard-k">확정하면 되돌릴 수 없습니다</span>
        <span className="home-fill" />
        <Btn kind="fill" onClick={send} {...may.attrs}
             disabled={!pick || busy || !may.ok}>
          {busy ? "확정하는 중…" : "처분 확정"}
        </Btn>
      </footer>
    </aside>
  );
}
