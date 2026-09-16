/* 실제 MRI 모델(2D 슬라이스 + COCO + SAM3 텍스트쿼리 LoRA 단일모델)이
 * 서빙에서 뱉는 값을 그대로 보여준다 — report.ai_summary/ai_evidence/
 * ai_suggestion(합성된 서술문)과는 다른, 모델 원본 출력 구조다.
 *
 * 실제로 나오는 값(종양, 유방 밀도)만 보여준다. 케이스별 기권(abstained)은
 * "이번 케이스만" 판독을 보류한 것이라 경고색 노티스로 표시하지만, 모델
 * 구조상 아예 안 나오는 값(BI-RADS 등급, 양성/악성 병변 위치)은 화면에
 * 따로 나열하지 않는다 — 안 나오는 걸 안 나온다고 매번 말할 필요는 없다. */
export default function AIModelResult({ aiModel }) {
  if (!aiModel) {
    return <p style={{ fontSize: 13, color: "var(--muted)" }}>모델 결과가 없습니다</p>;
  }
  const { tumor_count, tumors, density, phases, thresholds,
    max_lesions_per_patient, lesions_dropped, post_path } = aiModel;

  return (
    <div>
      <p className="section-label" style={{ marginTop: 0 }}>종양</p>
      {tumor_count.abstained ? (
        <AbstainNotice text="이번 케이스에서는 종양 개수 판독을 보류했습니다(기권)." />
      ) : (
        <>
          <p className="card-text">종양 {tumor_count.value}개</p>
          {tumors.map((t) => (
            <div className="tumor-item" key={t.evidence_id}>
              <div className="head">
                <span className="id">{t.evidence_id}</span>
                <span className="lesion">{t.lesion_id}</span>
              </div>
              {t.abstained ? (
                <AbstainNotice text="이 병변은 이번 케이스에서 판독을 보류했습니다(기권)." />
              ) : (
                <div className="pt-info" style={{ marginTop: 8 }}>
                  <div className="row"><span className="k">위치</span><span className="v">{t.location}</span></div>
                  <div className="row"><span className="k">사분면</span><span className="v">{t.quadrant}</span></div>
                  <div className="row"><span className="k">부피</span><span className="v">{t.volume_mm3.toLocaleString()} mm³</span></div>
                  <div className="row"><span className="k">유두 거리</span><span className="v">{t.nipple_distance_mm} mm</span></div>
                  {t.mesh_image_id && (
                    <div className="row"><span className="k">3D 메시</span><span className="v">{t.mesh_image_id}</span></div>
                  )}
                </div>
              )}
            </div>
          ))}
        </>
      )}

      <p className="section-label">유방 밀도</p>
      {density.abstained ? (
        <AbstainNotice text="이번 케이스에서는 유방 밀도 판독을 보류했습니다(기권)." />
      ) : (
        <div className="pt-info">
          <div className="row"><span className="k">밀도</span><span className="v">{density.percent}%</span></div>
          <div className="row"><span className="k">카테고리</span><span className="v">{density.category}</span></div>
        </div>
      )}

      <details className="model-meta">
        <summary>모델 정보</summary>
        <ul>
          <li>임계값 — 종양 {thresholds.tumor} · 치밀조직 {thresholds.dense_tissue} · 유방 {thresholds.breast}</li>
          <li>Phase — {phases.join(", ")}</li>
          {post_path && <li>후처리 경로 — {post_path}</li>}
          <li>환자당 병변 최대 {max_lesions_per_patient}개(초과 시 조용히 드롭 · 이번엔 {lesions_dropped}개 드롭)</li>
          <li>Evidence ID 형식 — MR-01(1-based)</li>
          <li>평면 아티팩트 필터 — tumor·malignant lesion·benign lesion에만 적용(breast·dense tissue는 해부학적으로 평면이라 제외)</li>
        </ul>
      </details>
    </div>
  );
}

function AbstainNotice({ text }) {
  return (
    <div className="abstain-notice">
      <span aria-hidden="true">⏸</span>
      <span>{text}</span>
    </div>
  );
}
