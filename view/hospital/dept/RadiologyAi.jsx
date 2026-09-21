import { Chip, Fold } from "../lib/Parts";
import { DESCRIPTOR_AXIS, LESION_KIND, label, modality as asModality } from "../codes";

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

export default function RadiologyAi({ d, pick, onPick }) {
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

  const m = asModality(ai.modality);

  return (
    <div className="ai">
      {/* ⚠ 서버 모달리티 코드는 `us` 다 — `ultrasound` 로 비교하면
          초음파 소견이 통째로 안 뜬다. asModality 가 철자를 맞춰 준다 */}
      {m === "us" && <Ultrasound a={ai} />}
      {m === "mammo" && <Mammo a={ai} pick={pick} onPick={onPick} />}
      {m === "mri" && <Mri a={ai} />}
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
function Mammo({ a, pick, onPick }) {
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

      {lesions.map((l, i) => {
        /* ⚠ 뷰어 도형의 id 와 **같은 규칙**이어야 한다.
           lib/Stage.jsx 의 boxesFromLesions 가 `l.id ?? \`b${i}\`` 로
           붙인다. 한쪽만 바꾸면 눌러도 아무 도형도 안 밝는다 */
        const sid = l.id ?? `b${i}`;
        const on = pick != null && pick === sid;
        return (
          <section className={on ? "ai-card on" : "ai-card"} key={l.id ?? i}>
            <div className="ai-h">
              <b>{l.id ?? `${label(LESION_KIND, l.kind) || "병변"} ${i + 1}`}</b>
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
                      <td>{label(DESCRIPTOR_AXIS, x.axis)}</td>
                      <td>{x.value}</td>
                      <td>{pct(x.confidence)}</td>
                      <td>{x.validated ? "됨" : "안 됨"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Fold>

            <div className="stack">
              {/* 뷰어에서 이 병변을 밝힌다. 박스는 이미 그려져 있고
                  Stage 가 고른 것에 .on 을 준다 — 여기서는 어느 것인지만
                  알려 주면 된다 */}
              <button className="btn ghost" aria-pressed={on}
                      disabled={!onPick}
                      title={onPick ? undefined : "뷰어와 연결되지 않았습니다"}
                      onClick={() => onPick?.(on ? null : sid)}>
                {on ? "선택 해제" : "영상에서 보기"}
              </button>
              {/* ⚠ 재어 주는 도구가 아직 없다. 눌러도 아무 일이 안 나면
                  고장으로 읽히므로 꺼 두고 이유를 붙인다 */}
              <button className="btn ghost" disabled
                      title="길이 재는 도구가 아직 없습니다">
                캘리퍼 측정
              </button>
            </div>
          </section>
        );
      })}

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
          <div><dt>치밀도</dt><dd>{pctOf(a.density?.percent, 1)}</dd></div>
        </dl>
      </Fold>

      {(a.lesions ?? []).map((l, i) => (
        <section className="ai-card" key={l.id ?? i}>
          <div className="ai-h"><b>병변 {i + 1}</b></div>
          <dl className="ai-m two">
            <div><dt>부피</dt><dd>{num(l.volume_cm3)} <i>cm³</i></dd></div>
            <div><dt>최대 직경</dt><dd>{num(l.max_diameter_mm)} <i>mm</i></dd></div>
            <div><dt>유두 거리</dt><dd>{num(l.nipple_distance_mm)} <i>mm</i></dd></div>
            <div><dt>사분면</dt><dd>{l.quadrant ?? "—"}</dd></div>
          </dl>
          <p className="muted small">
            현재 분석 결과에는 2D 단면 좌표가 없어 위치 표시는 제공하지 않습니다.
          </p>
        </section>
      ))}
    </>
  );
}

function num(n, digits = 1) {
  if (n == null) return "—";
  return typeof n === "number" ? Number(n.toFixed(digits)).toLocaleString("ko-KR") : n;
}

/* 0~1 짜리 **비율**을 백분율로. 확신도·신뢰도가 여기로 온다.
 *
 * ⚠ 전에는 「1 이하면 비율로 보고 100을 곱한다」로 짐작하고 있었다.
 *   확신도에는 맞지만 **이미 백분율인 값이 섞여 들어오면 틀린다** —
 *   치밀도 0.8%(희박하지만 가능한 값)가 80% 로 뜬다. 열 배 부풀린
 *   숫자를 판독의가 그대로 읽게 되는 자리라, 짐작을 걷어내고 부르는
 *   쪽이 어느 것인지 고르게 했다. */
function pct(n, digits = 0) {
  if (n == null) return "—";
  /* 초음파 서버의 등급·마스크 신뢰도는 현재 '높음'·'보통' 같은
     서술값으로 온다. 숫자 확신도로 가정해 곱하면 NaN%가 되므로 그대로
     보여 준다. 숫자(0~1)만 백분율로 바꾼다. */
  if (typeof n !== "number") return String(n);
  return `${(n * 100).toFixed(digits)}%`;
}

/* 이미 백분율(0~100)로 오는 값을 그대로 적는다. 치밀도가 여기다 */
function pctOf(n, digits = 0) {
  if (n == null) return "—";
  return `${Number(n).toFixed(digits)}%`;
}
