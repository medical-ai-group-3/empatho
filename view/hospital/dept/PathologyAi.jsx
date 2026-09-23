import { Chip } from "../lib/Parts";
import { STIL_LEVEL, label } from "../codes";
import { PartBar, SplitBar, StripPlot } from "./AiViz";

/* 병리 AI 소견 — 등급이 아니라 정량 지표다
 * ────────────────────────────────────────────────────────────────
 *
 * 영상의학과 AI 소견과 자리는 같고 내용이 다르다. 병리 모델은 BI-RADS 를
 * 내지 않는다. 대신 숫자 넷을 낸다 — sTIL · TSR · 세포 수 · 간질 상태.
 *
 * ⚠ 지켜야 할 것 셋
 *
 *   1. **stil_nucleus 를 화면에 내지 않는다.**
 *      보정 전 값이라 임상 기준의 1/12 로 나온다. 그대로 보여주면
 *      「면역 반응이 거의 없다」로 읽힌다. 화면에도 소견문에도 안 낸다.
 *      화면에 내는 것은 stil_calibrated 뿐이다.
 *
 *   2. **간질이 없으면 0% 가 아니라 「평가 불가」다.**
 *      stroma_status 가 absent 면 sTIL 이 null 이다. 0% 로 그리면
 *      「면역 반응이 없다」는 정반대 뜻이 된다.
 *
 *   3. **크롭 여러 장을 평균 내지 않는다.**
 *      같은 슬라이드도 자른 자리에 따라 sTIL 이 0~36% 로 흔들린다
 *      (변동계수 ≈ 1.0). 평균은 우리가 만든 값이지 모델이 낸 값이
 *      아니다. 장마다 나란히 놓고 판독의가 분포를 본다.
 */

export default function PathologyAi({ d }) {
  const rows = d.ai ?? [];

  if (rows.length === 0) {
    return <p className="muted">AI 결과가 없습니다.</p>;
  }

  return (
    <div className="ai">
      <p className="muted small">
        크롭 {rows.length}장. 자른 자리에 따라 값이 크게 달라지므로 평균을 내지 않고 장마다 보여 줍니다.
      </p>

      {/* 크롭이 두 장 이상일 때만 — 한 점은 분포가 아니다. 평균을 내지
          않는다는 원칙을 그림으로 지킨다(변동계수 ≈ 1.0). */}
      <StripPlot
        label="크롭별 sTIL"
        points={rows
          .filter((r) => !r.abstained && r.stroma_status !== "absent")
          .map((r, i) => ({ name: `${i + 1}`, value: r.stil_percent }))}
        note="장마다 점으로 찍습니다. 평균은 모델이 낸 값이 아닙니다." />

      {rows.map((r, i) => (
        <section className="ai-card" key={r.id ?? i}>
          <div className="ai-h">
            <b>크롭 {i + 1}</b>
            <span className="muted">{r.name}</span>
          </div>

          {r.abstained ? (
            <div className="ai-na">
              <b>판정하지 못했습니다</b>
              <span>{r.abstain_reason}</span>
              <span className="muted small">분석 실패가 아닙니다. 직접 판독하시면 됩니다.</span>
            </div>
          ) : (
            <dl className="ai-m">
              <div>
                <dt>sTIL</dt>
                <dd>
                  {r.stroma_status === "absent" ? (
                    <span className="ai-na inline">평가 불가 — 간질 없음</span>
                  ) : r.stil_calibrated == null ? (
                    <span className="ai-na inline">보정 전 — 표시하지 않음</span>
                  ) : (
                    <>{r.stil_calibrated}<i>%</i> <em>({label(STIL_LEVEL, r.stil_level)})</em></>
                  )}
                </dd>
              </div>

              <div>
                <dt>TSR</dt>
                <dd>
                  {r.tsr_percent == null
                    ? <span className="ai-na inline">평가 불가</span>
                    : <>{r.tsr_percent}<i>%</i></>}
                </dd>
              </div>

              <div>
                <dt>세포 수</dt>
                <dd className="cells">
                  <span>전체 {fmt(r.cell_counts?.total)}</span>
                  <span>TIL {fmt(r.cell_counts?.til)}</span>
                  <span>간질내 TIL {fmt(r.cell_counts?.til_stromal)}</span>
                </dd>
              </div>

              <div>
                <dt>간질 상태</dt>
                <dd>
                  <Chip tone={r.stroma_status === "absent" ? "fill" : "line"}>
                    {r.stroma_status === "absent" ? "없음" : "있음"}
                  </Chip>
                </dd>
              </div>
            </dl>
          )}

          {/* ── 산출값 그림 ─────────────────────────────────────
              값이 없으면 각 조각이 스스로 안 그린다. 간질이 없으면
              비율·세포 구성이 뜻을 잃으므로 통째로 건너뛴다. */}
          {!r.abstained && r.stroma_status !== "absent" && (
            <>
              <SplitBar
                label="조직 구성 (TSR)"
                parts={[
                  { name: "종양", value: r.tsr_tumor_percent },
                  { name: "간질", value: r.tsr_stroma_percent },
                ]} />

              <PartBar
                label="세포 구성"
                total={r.n_cells_total}
                parts={[
                  { name: "TIL", value: r.n_cells_til },
                  { name: "간질내 TIL", value: r.n_cells_til_stromal },
                ]} />

              <PartBar
                label={`면적 분해${r.mpp ? ` · ${mm2(r.tumor_area_px + r.stroma_area_px, r.mpp)}` : ""}`}
                total={sum(r.tumor_area_px, r.stroma_area_px)}
                unit=" px"
                parts={[
                  { name: "종양", value: r.tumor_area_px },
                  { name: "간질", value: r.stroma_area_px },
                  { name: "면역세포", value: r.immune_cell_area_px },
                ]} />
            </>
          )}
        </section>
      ))}

      <p className="muted small">
        TSR 에는 신뢰구간이 없습니다 — 모델에 dropout 이 없어 산출할 수 없습니다.
      </p>
    </div>
  );
}

function fmt(n) {
  return n == null ? "—" : n.toLocaleString("ko-KR");
}

function sum(...xs) {
  const use = xs.filter((x) => typeof x === "number" && Number.isFinite(x));
  return use.length ? use.reduce((a, b) => a + b, 0) : null;
}

/* 화소를 mm² 로. mpp 는 화소 한 변의 µm 다 — 면적이라 제곱하고,
   µm² → mm² 로 10^6 을 나눈다. */
function mm2(px, mpp) {
  if (typeof px !== "number" || typeof mpp !== "number") return "";
  const v = (px * mpp * mpp) / 1e6;
  return `${v < 0.01 ? v.toFixed(4) : v.toFixed(2)} mm²`;
}
