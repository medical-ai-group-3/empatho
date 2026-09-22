import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { breast as api } from "../../../api";
import { useApi } from "../../../lib/useApi";
import { Page, Btn } from "../../../lib/Page";
import { Body, Empty } from "../../../lib/Body";
import { Chip, useCan } from "../../../lib/Parts";
import { go } from "../../../nav";
import * as H from "../../home";

/* 유방외과 · 불일치 처분 — `docs/mockup/SurgeryDiscordance.html`
 * ════════════════════════════════════════════════════════════════
 *
 * 영상과 병리가 엇갈린 건만 모인다. 왼쪽에 엇갈린 목록, 오른쪽에 처분.
 *
 *   ┌ 1fr ─────────────────────────┬ 380px ─────────┐
 *   │ 환자 │번호│영상 │병리 │ [처분]│ 김민지 · 처분  │
 *   │ ──────────────────────────── │ ○ 재생검       │
 *   │ 김민지 … 4(악성 의심) 양성    │ ○ 절제         │
 *   │                              │ ○ 관찰         │
 *   │                              │ [처분 확정]    │
 *   └──────────────────────────────┴────────────────┘
 *
 * ⚠ **「판독 후 3일」을 안 쓴다.** 목업 표의 그 칸은 경과 시간이다.
 *   대신 판독 날짜를 적는다 — 언제 났는지는 서버가 준다.
 * ⚠ **목록은 이 건 하나다.** 서버에 `GET /discordances`(전체 목록)가
 *   있지만 api.js 에 없고 새 경로는 안 판다. 대신 주소로 들어온 한 건을
 *   펴 놓고, 나머지는 「내 환자」의 불일치 탭이 센다 — 거기가 목록이다.
 * ⚠ **되돌릴 수 없다.** 처분하면 flag 가 닫히고 치료 방침 결정이 열린다.
 */
const DISPOSE = [
  { v: "rebiopsy", label: "재조직검사" },
  { v: "excision", label: "수술적 절제" },
  { v: "followup", label: "단기 추적 (6개월)" },
  { v: "no_action", label: "불일치 아님 — 종결" },
];

export default function Discordance() {
  const { id } = useParams();
  const nav = useNavigate();
  const one = useApi(() => api.discordance(id), [id]);

  return (
    <Page className="disc-page" crumb={["유방외과", "불일치 처분"]}
          title="불일치 처분"
          right={<Btn to={go.breast.waiting()}>내 환자</Btn>}>
      <Body loading={one.loading && !one.data} error={one.error} onRetry={one.reload}>
        {one.data && (
          <div className="disc">
            <Compare d={one.data} />
            <Dispose d={one.data} done={one.data.flag_status !== "open"}
                     onDone={() => nav(go.breast.waiting())} />
          </div>
        )}
      </Body>
    </Page>
  );
}

/* 왼쪽 — 무엇이 엇갈렸나. 두 판독을 나란히 놓는다 */
function Compare({ d }) {
  const p = d.patient ?? {};
  const rad = d.radiology_reading ?? {};
  const pat = d.pathology_reading ?? {};

  return (
    <div className="disc-l">
      <header className="disc-h">
        <span className="work-1">
          <b>{H.nameOf(p)}</b>
          {H.who(p) && <span>{H.who(p)}</span>}
        </span>
        <span className="home-fill" />
        {d.lesion && (
          <Chip>{d.lesion.site} · {d.lesion.size_mm}mm</Chip>
        )}
      </header>

      {/* 규칙이 무엇을 걸었는지 — 사람이 읽는 한 줄이다 */}
      <p className="disc-rule">{d.violated_rule}</p>

      <div className="disc-vs">
        <Side title="영상 판독" r={rad} big={rad.assessment} />
        <Side title="병리 판독" r={pat} big={pat.assessment} />
      </div>
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
      await api.dispose(d.discordance_id, { disposition: pick, reason: why });
      onDone?.();
    } catch (e) { setErr(e.detail || e.message); }
    finally { setBusy(false); }
  }

  if (done) {
    return (
      <aside className="disc-r">
        <header className="bcol-h"><i className="hdot" aria-hidden="true" /><b>처분</b></header>
        <Empty title="이미 처분된 건입니다" />
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
