import { Chip, Fold } from "../lib/Parts";

/* 영상의학과 AI 소견 — 모달리티마다 내용이 다르다
 * ────────────────────────────────────────────────────────────────
 *
 * 세 모델이 서로 다른 것을 낸다. 같은 틀에 억지로 맞추지 않고 갈라 둔다.
 *
 *   초음파  등급 + 확신도 2종 + 형태 지표 6개 + 방향 + 폴리곤
 *   맘모    병변마다 종류·박스·BI-RADS·생검 권고 + 서술어 5축 + 한계
 *   MRI     병변마다 부피·직경·좌표·유두거리·사분면 + 밀도. **등급 없음**
 *
 * ⚠ 지켜야 할 것 넷
 *
 *   1. **미검출은 정상이 아니다.**
 *      초음파 lesion_found=false, 맘모 abstained=true 는 「정상」이
 *      아니라 「판정 못 함」이다. 사유를 같이 띄운다.
 *
 *   2. **서술어를 만들지 않는다.**
 *      「경계가 불규칙합니다」 같은 문장을 화면이 지어내지 않는다.
 *      모델이 낸 값과 확신도만 보여준다. 문장은 판독의가 쓴다.
 *
 *   3. **초음파 크기는 px 뿐이다.** pixel spacing 이 없어 mm 로
 *      바꿀 수 없다. mm 로 적으면 없는 정밀도를 지어내는 것이다.
 *
 *   4. **악성 확률을 화면에 내지 않는다.** 초음파 모델이 값을 내지만
 *      판독을 끌고 가는 숫자라 띄우지 않기로 했다.
 */

export default function RadiologyAi({ d }) {
  const ai = d.ai;
  if (!ai) return <p className="muted">AI 결과가 없습니다.</p>;

  const abstained = ai.abstained ?? ai.summary?.abstained;
  if (abstained || ai.lesion_found === false) {
    return (
      <div className="ai-na">
        <b>판정하지 못했습니다</b>
        <span>{ai.abstain_reason ?? "임계값을 넘는 검출이 없습니다"}</span>
        <span className="muted small">
          「정상」이라는 뜻이 아닙니다. 분석 실패도 아닙니다. 직접 판독하시면 됩니다.
        </span>
      </div>
    );
  }

  return (
    <div className="ai">
      {ai.modality === "ultrasound" && <Ultrasound a={ai} />}
      {ai.modality === "mammo" && <Mammo a={ai} />}
      {ai.modality === "mri" && <Mri a={ai} />}
    </div>
  );
}

/* ── 초음파 ──────────────────────────────────────────────────── */
function Ultrasound({ a }) {
  return (
    <>
      <div className="ai-top">
        <span className="grade">{a.category}</span>
        <span className="muted small">
          {a.category === "4~5" && "4와 5는 영상만으로 구별되지 않습니다"}
        </span>
      </div>

      <dl className="ai-m">
        <div><dt>등급 확신도</dt><dd>{pct(a.category_confidence)}</dd></div>
        <div><dt>마스크 신뢰도</dt><dd>{pct(a.mask_confidence)}</dd></div>
      </dl>
      <p className="muted small">두 확신도는 서로 다른 축입니다. 합치거나 평균 내지 않습니다.</p>

      <Fold title="형태 지표">
        <dl className="ai-m two">
          <div><dt>면적</dt><dd>{num(a.shape?.area)} <i>px²</i></dd></div>
          <div><dt>최대 직경</dt><dd>{num(a.shape?.max_diameter)} <i>px</i></dd></div>
          <div><dt>종횡비</dt><dd>{num(a.shape?.aspect_ratio)}</dd></div>
          <div><dt>볼록성</dt><dd>{num(a.shape?.convexity)}</dd></div>
          <div><dt>요철도</dt><dd>{num(a.shape?.roughness)}</dd></div>
          <div><dt>원형도</dt><dd>{num(a.shape?.circularity)}</dd></div>
        </dl>
        <p className="muted small">
          서버가 계산한 값을 그대로 씁니다. 크기 단위는 px 뿐입니다 — pixel spacing 이 없어 mm 로 바꿀 수 없습니다.
        </p>
      </Fold>

      {a.orientation && (
        <dl className="ai-m"><div><dt>방향</dt><dd>{a.orientation}</dd></div></dl>
      )}
    </>
  );
}

/* ── 맘모 ──────────────────────────────────────────────────────
 *
 * 필드 이름은 serve_mammo.py 에서 확인한 것이다 (2026-09-16).
 *   summary = { n_lesions, biopsy, max_birads, abstained }
 *   lesion  = { id, kind, box, birads, biopsy, … }
 *
 * ⚠ birads 가 null 일 수 있다. 검출은 했지만 등급을 못 낸 경우다.
 *   빈칸으로 두지 않고 「등급 없음」이라고 적는다 — 빈칸은 «0» 이나
 *   «정상» 으로 읽힌다.
 */
function Mammo({ a }) {
  const lesions = a.lesions ?? [];
  const s = a.summary ?? a;          /* 봉투가 한 겹 더 있을 수도 */

  return (
    <>
      <dl className="ai-m">
        <div><dt>병변 수</dt><dd>{s.n_lesions ?? lesions.length}</dd></div>
        <div><dt>최고 등급</dt><dd>{s.max_birads ?? "—"}</dd></div>
        <div>
          <dt>생검 권고</dt>
          <dd><Chip tone={s.biopsy ? "fill" : "line"}>
            {s.biopsy ? "권고" : "해당 없음"}
          </Chip></dd>
        </div>
      </dl>

      {lesions.map((l, i) => (
        <section className="ai-card" key={l.id ?? i}>
          <div className="ai-h">
            <b>{l.id ?? `${l.kind === "calcification" ? "미세석회" : "종괴"} ${i + 1}`}</b>
            {l.birads != null
              ? <Chip tone={l.biopsy ? "fill" : "line"}>BI-RADS {l.birads}</Chip>
              : <Chip tone="dot">등급 없음</Chip>}
          </div>

          <dl className="ai-m two">
            <div><dt>크기</dt><dd>{num(l.size_mm)} <i>mm</i></dd></div>
            <div><dt>확신도</dt><dd>{pct(l.certainty)}</dd></div>
            <div><dt>생검</dt><dd>{l.biopsy ? "권고" : "해당 없음"}</dd></div>
          </dl>

          {/* 서술어 5축 — 값 · 확신도 · 검증 여부를 그대로 낸다.
              문장으로 바꾸지 않는다 */}
          <Fold title="서술어" open={false}>
            <table className="ai-tbl">
              <thead><tr><th>축</th><th>값</th><th>확신도</th><th>검증</th></tr></thead>
              <tbody>
                {(l.descriptors ?? []).map((x) => (
                  <tr key={x.axis}>
                    <td>{AXIS[x.axis] ?? x.axis}</td>
                    <td>{x.value}</td>
                    <td>{pct(x.confidence)}</td>
                    <td>{x.validated ? "됨" : "안 됨"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Fold>

          <div className="stack">
            <button className="btn ghost">영상에서 보기</button>
            <button className="btn ghost">캘리퍼 측정</button>
          </div>
        </section>
      ))}

      {/* 한계는 문장 그대로 보여준다 — 요약하면 뜻이 바뀐다 */}
      {(a.limitations ?? []).length > 0 && (
        <Fold title={`이 결과의 한계 ${a.limitations.length}건`} open={false}>
          <ul className="bul">
            {a.limitations.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </Fold>
      )}
    </>
  );
}

/* ── MRI ─────────────────────────────────────────────────────── */
function Mri({ a }) {
  return (
    <>
      <p className="muted small">
        MRI 모델은 등급(BI-RADS)을 내지 않습니다. 위치 값은 근사치입니다.
      </p>

      <Fold title="유방 밀도">
        <dl className="ai-m two">
          <div><dt>유방 복셀</dt><dd>{num(a.density?.breast_voxels)}</dd></div>
          <div><dt>치밀 복셀</dt><dd>{num(a.density?.dense_voxels)}</dd></div>
          <div><dt>치밀도</dt><dd>{pct(a.density?.percent, 1)}</dd></div>
        </dl>
      </Fold>

      {(a.lesions ?? []).map((l, i) => (
        <section className="ai-card" key={l.id ?? i}>
          <div className="ai-h"><b>병변 {i + 1}</b></div>
          <dl className="ai-m two">
            <div><dt>부피</dt><dd>{num(l.volume_mm3)} <i>mm³</i></dd></div>
            <div><dt>최대 직경</dt><dd>{num(l.max_diameter_mm)} <i>mm</i></dd></div>
            <div><dt>유두 거리</dt><dd>{num(l.nipple_distance_mm)} <i>mm</i></dd></div>
            <div><dt>사분면</dt><dd>{l.quadrant ?? "—"}</dd></div>
          </dl>
          <p className="muted small">중심좌표 {fmtXyz(l.centroid)}</p>
          <div className="stack">
            <button className="btn ghost">영상에서 보기</button>
          </div>
        </section>
      ))}
    </>
  );
}

const AXIS = {
  shape: "모양", margin: "경계", calctype: "석회 종류",
  calcdist: "석회 분포", finding: "소견",
};

function num(n, digits = 1) {
  if (n == null) return "—";
  return typeof n === "number" ? Number(n.toFixed(digits)).toLocaleString("ko-KR") : n;
}

function pct(n, digits = 0) {
  if (n == null) return "—";
  const v = n <= 1 ? n * 100 : n;
  return `${v.toFixed(digits)}%`;
}

function fmtXyz(c) {
  if (!c) return "—";
  return `(${c.x}, ${c.y}, ${c.z})`;
}
