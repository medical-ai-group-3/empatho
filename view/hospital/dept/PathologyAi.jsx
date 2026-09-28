import { Chip } from "../lib/Parts";
import { Gauge, PartBar, SplitBar, StripPlot } from "./AiViz";

/* 병리 AI 소견 — 등급이 아니라 정량 지표다
 * ────────────────────────────────────────────────────────────────
 *
 * 영상의학과 AI 소견과 자리는 같고 내용이 다르다. 병리 모델은 BI-RADS 를
 * 내지 않는다. 대신 숫자 넷을 낸다 — AI 계측값 · TSR · 세포 수 · 간질 상태.
 *
 * ⚠ 09-28 결정 — **이 패널이 내는 값은 "sTIL"이 아니다.**
 *   sTIL(임상 수치)은 병리의가 검체 단위로 직접 입력한다(Doctor 섹션,
 *   dept/pathology.jsx). 여기 stil_percent 는 모델이 낸 원시값이고
 *   "AI 계측값"으로만 부른다 — 이름을 "sTIL"로 쓰면 두 값이 같은
 *   척도인 것처럼 읽힌다. 보정계수는 안 쓴다(저장소 전체를 뒤져봐도
 *   실제로 곱하는 코드가 없었다 — 09-27 확인). 저/중/고 라벨도 안
 *   붙인다 — 그건 임상 판정의 언어라 AI 계측값에 붙이면 안 된다.
 *
 * ⚠ 지켜야 할 것 셋
 *
 *   1. **AI 계측값을 볼 때마다 안내 문구를 같이 낸다.**
 *      "병리의사 sTIL과 척도가 달라 직접 비교할 수 없습니다. 세포
 *      검출 누락으로 실제보다 낮게 나올 수 있습니다." — 척도가 다른
 *      숫자를 나란히 두면 누구나 비교하고 싶어진다.
 *
 *   2. **간질이 없으면 0% 가 아니라 「평가 불가」다.**
 *      stroma_status 가 absent 면 AI 계측값이 null 이다. 0% 로 그리면
 *      「면역 반응이 없다」는 정반대 뜻이 된다.
 *
 *   3. **크롭 여러 장을 평균 내지 않는다.**
 *      같은 슬라이드도 자른 자리에 따라 값이 0~36% 로 흔들린다
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
          않는다는 원칙을 그림으로 지킨다.

          ⚠ 이름표가 "sTIL"이 아니라 "AI 계측값"이다(09-28). 병리의가
            입력하는 sTIL 과 척도가 다르다 — 같은 이름으로 그리면 두
            값을 겹쳐 읽게 된다. 병리의 sTIL 과 분리해 덜 강조한다. */}
      <div className="muted">
        <StripPlot
          label="크롭별 AI 계측값 (참고용)"
          points={rows
            .filter((r) => !r.abstained && r.stroma_status !== "absent")
            .map((r, i) => ({ name: `${i + 1}`, value: r.stil_percent }))}
          note="장마다 점으로 찍습니다. 평균은 모델이 낸 값이 아닙니다." />
      </div>

      {/* 종양 비율은 보정 문제가 없다 — 크롭 사이 흔들림을 여기서 본다. */}
      <StripPlot
        label="크롭별 종양 비율"
        points={rows
          .filter((r) => !r.abstained && r.stroma_status !== "absent")
          .map((r, i) => ({ name: `${i + 1}`, value: r.tsr_tumor_percent }))}
        note="자른 자리에 따라 조직 구성이 달라집니다." />

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
              {/* ⚠ "sTIL"이 아니다 — 병리의가 입력하는 sTIL 은 Doctor
                  섹션에 따로 있다. 여기는 모델 원시값이고 이름도 값도
                  그쪽과 섞이지 않게 둔다(작은 글씨·회색, 등급 라벨 없음). */}
              <div>
                <dt>
                  AI 계측값{" "}
                  <span className="muted small">
                    ({r.immune_region_area_px != null
                      ? `간질 중 면역세포 주변 ${r.til_region_radius_um ?? 5}µm 영역 비율`
                      : "간질 대비 면역세포 면적 비율"})
                  </span>
                </dt>
                <dd className="muted">
                  {r.stroma_status === "absent" ? (
                    <span className="ai-na inline">평가 불가 — 간질 없음</span>
                  ) : r.stil_percent == null ? (
                    <span className="ai-na inline">값 없음</span>
                  ) : (
                    <>
                      {fmt1(r.stil_percent)}<i>%</i>{band(r.stil_percent)}
                      <p className="muted small">
                        병리의사 sTIL과 척도가 달라 직접 비교할 수 없습니다.
                        세포 검출 누락으로 실제와 다르게 나올 수 있습니다.
                        {band(r.stil_percent) && " ± 는 학습에 쓰지 않은 검증 이미지 27장 중 80%가 들어간 오차 범위입니다."}
                      </p>
                    </>
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
              {/* AI 계측값이 어떻게 나왔는지 — 분자 ÷ 분모를 그대로 보인다 */}
              <Gauge
                label="AI 계측값 풀이"
                percent={r.stil_percent}
                note={`${r.immune_region_area_px != null ? "면역세포 영역" : "면역세포 면적"} ${fmt(r.immune_region_area_px ?? r.immune_cell_area_px)} px ÷ 간질 ${fmt(r.stroma_area_px)} px`} />

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
                  { name: r.immune_region_area_px != null ? "면역세포 영역" : "면역세포",
                    value: r.immune_region_area_px ?? r.immune_cell_area_px },
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

/* 검증 오차 ± (09-28 · serving 1.1.0) — BCSS 중 **학습에 안 쓴 환자 27장**
   (0.5µm/px)에서 AI 값 구간마다 |AI − 정답| 의 80 백분위를 잰 값이다.
   정답 = 병리 인력이 칠한 림프구 침윤 면적 ÷ 간질 영역 면적.
   ⚠ BCSS 151장 중 124장은 학습 데이터(TIGER)와 같은 환자 · 같은 영역이라 뺐다
     (TIGER TCGA 크롭은 BCSS 영역에서 잘라 낸 조각이다). 27장이라 구간을 둘로만 나눈다.
   ⚠ 병리의사 육안 sTIL 점수 기준이 아니다. 조직 모델·계산식이 바뀌면 다시 잰다
     — 워크스테이션 ~/tmp_stil_rel/val11.json
   ponytail: 화면 상수. 모델 판마다 달라지면 서버 응답으로 옮긴다 */
const ERROR_BAND = [
  { upTo: 20, pm: 11.4 },          // 15장
  { upTo: Infinity, pm: 20.5 },    // 12장
];

function band(v) {
  if (typeof v !== "number" || !(v > 0)) return null;
  const pm = ERROR_BAND.find((b) => v <= b.upTo).pm;
  return <span className="muted small"> ± {pm.toFixed(1)}%p</span>;
}

function fmt(n) {
  return n == null ? "—" : n.toLocaleString("ko-KR");
}

/* AI 계측값은 소수 1자리로 낸다(09-28). 모델은 자릿수를 더 주지만
   그 아래 자리는 크롭을 조금만 다르게 잘라도 바뀌는 값이라, 있는 대로
   찍으면 없는 정밀도를 보여 주는 셈이 된다. */
function fmt1(n) {
  return typeof n === "number" && Number.isFinite(n) ? n.toFixed(1) : "—";
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
