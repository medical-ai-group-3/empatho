import { Chip } from "../lib/Parts";
import { STIL_LEVEL, label } from "../codes";

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
