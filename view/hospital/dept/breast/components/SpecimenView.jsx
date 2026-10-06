import { useState } from "react";
import { useApi } from "../../../lib/useApi";
import { useFile } from "../../../lib/files";
import { Body } from "../../../lib/Body";
import Stage, { MaskKeys, PATHOLOGY_MASK_COLORS } from "../../../lib/Stage";
import { pathology as cfg, translateLegend } from "../../pathology";

/* 병리 탭 — 검체의 크롭 사진 위에 조직 분할 마스크를 얹어 본다.
 *
 * 병리 판독 화면과 **같은 조회**(pathology.jsx 의 cfg.api.read)와 같은
 * 뷰어(Stage)를 쓴다. 유방외과는 판독 화면 권한이 없지만 검체 파일은
 * 읽을 수 있다(서버 권한표 specimen_pathology: 유방외과 R).
 *
 * 검체가 여럿이면 위에서 고르고, 크롭이 여럿이면 그 아래에서 고른다.
 * 기본은 가장 최근 검체의 첫 크롭이다.
 */
export default function SpecimenView({ specimenIds = [] }) {
  const [sid, setSid] = useState(specimenIds[0] ?? null);
  const [crop, setCrop] = useState(0);
  const read = useApi(() => (sid == null ? Promise.resolve(null) : cfg.api.read(sid)), [sid]);

  if (specimenIds.length === 0) return <p className="spec-empty">확정된 병리 검체가 없습니다</p>;

  const d = read.data;
  const crops = d?.crops ?? [];
  return (
    <div className="spec-view">
      <div className="spec-picks">
        {specimenIds.length > 1 && specimenIds.map((id) => (
          <button key={id} type="button" className={id === sid ? "on" : ""}
                  onClick={() => { setSid(id); setCrop(0); }}>검체 {id}</button>
        ))}
        {crops.map((c, i) => (
          <button key={c.id ?? i} type="button" className={i === crop ? "on" : ""}
                  onClick={() => setCrop(i)}>크롭 {i + 1}</button>
        ))}
      </div>
      <Body loading={read.loading} error={read.error} onRetry={read.reload}>
        {d && <Crop d={d} i={crop} />}
      </Body>
    </div>
  );
}

function Crop({ d, i }) {
  const c = d.crops?.[i] ?? null;
  const scope = { kind: cfg.scopeKind, id: d.unit.id };
  const img = useFile(c?.image, cfg.api.ticket, scope);
  const mask = useFile(c?.mask, cfg.api.ticket, scope);
  if (!c) return <p className="spec-empty">업로드된 크롭 이미지가 없습니다</p>;
  return (
    <>
      <div className="spec-stage">
        <Stage src={img.src} w={c.w ?? 512} h={c.h ?? 512} alt={`크롭 ${i + 1}`}
               loading={img.loading} loadError={img.error}
               mask={mask.src} maskColors={PATHOLOGY_MASK_COLORS} mode="review" />
      </div>
      {mask.src && (
        <MaskKeys legend={translateLegend(d.ai?.[i]?.mask_legend)} colors={PATHOLOGY_MASK_COLORS} />
      )}
    </>
  );
}
