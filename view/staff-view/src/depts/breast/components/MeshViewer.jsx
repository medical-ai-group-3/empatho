import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

/* 세그멘테이션 파이프라인이 뽑아 준 종양 표면 메시(mm 단위 실좌표,
 * positions/indices 삼각형 목록)를 그린다.
 *
 * ⚠ 임시 되돌림: Anatomy3DViewer.jsx를 GLB 로더 단독 컴포넌트로
 *   재작성하면서 그 파일이 내보내던 loadCroppedBody()가 없어졌다 —
 *   그 함수를 가져다 쓰던 이 파일이 깨지면 Vite ESM 그래프 전체가
 *   빌드 실패로 죽어서(모듈 하나의 named-export 에러가 앱 전체를
 *   내려버린다), 실제 GLB 인체 모델을 붙이기 전까지는 예전 방식의
 *   절차적(procedural) 몸통·유방 구체로 되돌려 둔다. layers prop은
 *   그대로 이 절차적 지오메트리의 표시 여부에 연결해서 하단 토글
 *   UI는 계속 동작한다. GLB 재연동은 다음 단계에서 진행. */
export default function MeshViewer({
  meshUrl, site, color = "#ff5da2",
  layers = { breast: true, chestWall: false, lesion: true },
}) {
  const wrapRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const [error, setError] = useState(null);
  const [meta, setMeta] = useState(null);
  const layersRef = useRef(layers);
  const sceneRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let renderer, scene, camera, controls, resizeObserver, frameId;
    let canvasEl;

    async function run() {
      setStatus("loading");
      setError(null);
      try {
        const res = await fetch(meshUrl);
        if (!res.ok) throw new Error(`mesh 요청 실패 (${res.status})`);
        const data = await res.json();
        if (cancelled) return;

        const el = wrapRef.current;
        const width = el.clientWidth || 300;
        const height = el.clientHeight || 300;

        scene = new THREE.Scene();
        scene.background = new THREE.Color(0x030405);

        camera = new THREE.PerspectiveCamera(38, width / height, 0.01, 100);

        renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setSize(width, height);
        renderer.localClippingEnabled = true;
        canvasEl = renderer.domElement;
        el.appendChild(canvasEl);

        // ── 종양 지오메트리 — 자기 중심으로만 정렬해 둔다(위치는 아래서 옮긴다) ──
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.Float32BufferAttribute(data.positions, 3));
        geometry.setIndex(data.indices);
        geometry.computeVertexNormals();
        geometry.computeBoundingBox();

        const tumorCenter = new THREE.Vector3();
        geometry.boundingBox.getCenter(tumorCenter);
        geometry.translate(-tumorCenter.x, -tumorCenter.y, -tumorCenter.z);

        const tumorSize = new THREE.Vector3();
        geometry.boundingBox.getSize(tumorSize);
        const tumorMaxDim = Math.max(tumorSize.x, tumorSize.y, tumorSize.z) || 1;

        const tumorMaterial = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide });
        const tumorGroup = new THREE.Group();
        tumorGroup.add(new THREE.Mesh(geometry, tumorMaterial));

        // ── 절차적 몸통(무채색·반투명) — 실제 GLB 인체 모델이 다시
        //    붙기 전까지의 자리 표시자. torsoR은 종양 크기 대비 사람
        //    몸통 정도 크기로 잡는다. ──
        const torsoR = Math.max(tumorMaxDim * 7, 100);
        const bodyColor = 0x9aa0a8;
        const bodyLine = 0xd8dadd;

        const torsoGeo = new THREE.SphereGeometry(torsoR, 40, 30);
        torsoGeo.scale(0.8, 1.3, 0.5);
        const torso = new THREE.Mesh(torsoGeo, new THREE.MeshStandardMaterial({
          color: bodyColor, transparent: true, opacity: 0.15, roughness: 0.7,
          side: THREE.DoubleSide, depthWrite: false,
        }));
        torso.position.set(0, torsoR * 0.02, -torsoR * 0.12);
        const torsoWire = new THREE.Mesh(torsoGeo, new THREE.MeshBasicMaterial({
          color: bodyLine, wireframe: true, transparent: true, opacity: 0.22,
        }));
        torsoWire.position.copy(torso.position);

        const neckGeo = new THREE.CylinderGeometry(torsoR * 0.11, torsoR * 0.15, torsoR * 0.32, 20);
        const neck = new THREE.Mesh(neckGeo, new THREE.MeshBasicMaterial({
          color: bodyLine, wireframe: true, transparent: true, opacity: 0.22,
        }));
        neck.position.set(0, torsoR * 1.15, -torsoR * 0.12);

        const breastR = torsoR * 0.38;
        const breastSep = torsoR * 0.48;
        const breastY = -torsoR * 0.02;
        const breastZ = torsoR * 0.32;
        const breastMat = new THREE.MeshStandardMaterial({
          color: bodyColor, transparent: true, opacity: 0.22, roughness: 0.5,
          side: THREE.DoubleSide, depthWrite: false, emissive: new THREE.Color(bodyColor), emissiveIntensity: 0.12,
        });
        const breastWireMat = new THREE.MeshBasicMaterial({
          color: bodyLine, wireframe: true, transparent: true, opacity: 0.26,
        });
        function makeBreast(xSign) {
          const g = new THREE.Group();
          const geo = new THREE.SphereGeometry(breastR, 28, 22);
          g.add(new THREE.Mesh(geo, breastMat), new THREE.Mesh(geo, breastWireMat));
          g.position.set(xSign * breastSep, breastY, breastZ);
          return g;
        }
        const leftBreast = makeBreast(1);
        const rightBreast = makeBreast(-1);

        const solidGroup = new THREE.Group();
        solidGroup.add(torso, leftBreast, rightBreast);
        const wireGroup = new THREE.Group();
        wireGroup.add(torsoWire, neck);
        scene.add(solidGroup, wireGroup, tumorGroup);

        // ── site 문자열(좌/우 + 사분면)로 어느 쪽 유방 안 어디에 병변을
        //    놓을지 정한다 ──
        const targetBreast = site?.includes("좌측") ? leftBreast
          : site?.includes("우측") ? rightBreast
          : rightBreast;
        const q = quadrantOffset(site);
        tumorGroup.position.set(
          q.x * breastR * 0.32,
          q.y * breastR * 0.32,
          breastR * 0.62
        );
        targetBreast.add(tumorGroup);
        // 실제 부피 그대로면 유방 대비 너무 작아 안 보이는 경우가 많아, 위치를
        // 분명히 읽을 수 있도록 시각적으로만 살짝 키운다.
        tumorGroup.scale.setScalar(1.8);

        solidGroup.visible = layersRef.current.breast;
        wireGroup.visible = layersRef.current.chestWall;
        tumorGroup.visible = layersRef.current.lesion;
        sceneRef.current = { solidGroup, wireGroup, tumorGroup };

        scene.add(new THREE.AmbientLight(0xffffff, 0.6));
        const key = new THREE.DirectionalLight(0xffffff, 1.1);
        key.position.set(1, 1.2, 1.6);
        scene.add(key);
        const fillLight = new THREE.DirectionalLight(0xbcd4ff, 0.45);
        fillLight.position.set(-1.3, -0.3, -1);
        scene.add(fillLight);
        const rim = new THREE.PointLight(color, 0.6, torsoR * 1.5);
        const tumorWorldPos = new THREE.Vector3();
        tumorGroup.getWorldPosition(tumorWorldPos);
        rim.position.copy(tumorWorldPos).add(new THREE.Vector3(0, 0, breastR * 0.8));
        scene.add(rim);

        const radius = Math.max(torsoR, breastR) * 1.6;
        camera.position.set(0, torsoR * 0.12, torsoR * 2.7);
        camera.lookAt(0, 0, 0);
        camera.near = radius * 0.02;
        camera.far = radius * 20;
        camera.updateProjectionMatrix();

        controls = new OrbitControls(camera, canvasEl);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.target.set(0, 0, 0);
        controls.minDistance = torsoR * 1.1;
        controls.maxDistance = torsoR * 7;
        controls.update();

        function animate() {
          if (cancelled) return;
          controls.update();
          renderer.render(scene, camera);
          frameId = requestAnimationFrame(animate);
        }
        animate();

        resizeObserver = new ResizeObserver(() => {
          const w = el.clientWidth, h = el.clientHeight;
          if (!w || !h || !renderer || !camera) return;
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          renderer.setSize(w, h);
        });
        resizeObserver.observe(el);

        if (!cancelled) {
          setMeta({
            className: data.class_name, patientId: data.patient_id,
            vertexCount: data.vertex_count, triangleCount: data.triangle_count,
          });
          setStatus("ready");
        }
      } catch (e) {
        console.error("[MeshViewer]", e);
        if (!cancelled) { setError(e.message || String(e)); setStatus("error"); }
      }
    }

    run();

    return () => {
      cancelled = true;
      if (frameId) cancelAnimationFrame(frameId);
      resizeObserver?.disconnect();
      controls?.dispose();
      renderer?.dispose();
      canvasEl?.remove();
      sceneRef.current = null;
    };
  }, [meshUrl, site, color]);

  // layers prop이 바뀌면 씬을 다시 만들지 않고 visibility만 토글한다.
  useEffect(() => {
    layersRef.current = layers;
    const s = sceneRef.current;
    if (!s) return;
    s.solidGroup.visible = layers.breast;
    s.wireGroup.visible = layers.chestWall;
    s.tumorGroup.visible = layers.lesion;
  }, [layers]);

  return (
    <div className="mesh3d">
      <div ref={wrapRef} className="mpr-canvas" />
      <span className="mesh3d-frame" aria-hidden="true" />
      {status === "loading" && (
        <div className="volume3d-overlay" style={{ position: "absolute", inset: 0 }}>
          <span>메시 불러오는 중…</span>
        </div>
      )}
      {status === "error" && (
        <div className="volume3d-overlay error" style={{ position: "absolute", inset: 0 }}>
          <span>메시를 불러오지 못했습니다</span>
          <span style={{ fontSize: 11 }}>{error}</span>
        </div>
      )}
      {status === "ready" && meta && (
        <p className="mesh3d-meta">{meta.className} · 정점 {meta.vertexCount.toLocaleString()} · 삼각형 {meta.triangleCount.toLocaleString()}</p>
      )}
    </div>
  );
}

/* "우측 유방 상외측(UOQ)" 같은 사분면 표기에서 상/하/외/내 글자를 읽어
 * 유방 안 어느 쪽에 병변을 둘지 방향 벡터로 바꾼다. 표기가 없거나
 * 못 읽으면 유방 정중앙에 둔다. */
function quadrantOffset(site) {
  if (!site) return { x: 0, y: 0 };
  const upper = site.includes("상");
  const lower = site.includes("하");
  const outer = site.includes("외");
  const inner = site.includes("내");
  const x = outer ? 1 : inner ? -1 : 0;
  const y = upper ? 1 : lower ? -1 : 0;
  const len = Math.hypot(x, y) || 1;
  return { x: x / len, y: y / len };
}
