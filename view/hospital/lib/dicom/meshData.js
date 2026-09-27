import { useEffect, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { fetchJson } from "../files";

/* MRI 판독이 만든 메시 JSON — { positions:[x,y,z…], indices:[…], frame:"pixel" }
 * 서버가 파생물 버킷에 두고 주소({key, derived, study_id})만 준다. */
export function jsonGeometry(m) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(m.positions, 3));
  if (m.indices?.length) g.setIndex(m.indices);
  return g;
}

/* 옛 STL 주소(목업) */
function stlUrl(lesion) {
  return (
    lesion?.mesh_url ||
    (lesion?.mesh_image_id?.endsWith(".stl")
      ? `/models/duke/${lesion.mesh_image_id}`
      : null)
  );
}

export const hasMesh = (lesion) => Boolean(lesion?.mesh_data || stlUrl(lesion));

/* JSON 이면 바로, STL 이면 받아서 onLoad(geometry) */
export function loadGeometry(lesion, onLoad, onError) {
  if (lesion?.mesh_data) return onLoad(jsonGeometry(lesion.mesh_data));
  new STLLoader().load(stlUrl(lesion), onLoad, undefined, onError);
}

/* 주소 목록 → 받은 JSON 목록(아직이거나 실패면 null) */
export function useMeshData(specs, issue) {
  const [data, setData] = useState([]);
  const sig = specs.map((s) => s?.key ?? s?.url ?? "").join("|");

  useEffect(() => {
    let live = true;
    setData([]);
    Promise.all(specs.map((s) =>
      s ? fetchJson(s, issue, { kind: "study", id: s.study_id }).catch((e) => {
        console.error("mesh load failed", s.key, e);
        return null;
      }) : null
    )).then((r) => { if (live) setData(r); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, issue]);

  return data;
}
