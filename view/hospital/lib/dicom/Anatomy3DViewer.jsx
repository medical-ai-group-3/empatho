import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { hasMesh, jsonGeometry, loadGeometry } from "./meshData";

const BODY_URL =
  "/models/duke/DUKE_001_body_silhouette.stl";

const DEFAULT_COLORS = [
  "#C9828C",
  "#8FA8C2",
  "#B59A6A",
  "#9B8FB5",
  "#7FA99A",
  "#C59B73",
];

const CROP = {
  bottomY: 105,
  topY: 315,
  leftX: 15,
  rightX: 146,
};

function getLesionColor(lesion, index) {
  return lesion?.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length];
}

export default function Anatomy3DViewer({
  /* ⚠ 기본값을 **빈 배열**로 둔다.
   *
   * 전에는 DEFAULT_LESIONS — DUKE 공개 데이터셋 환자의 종괴 메시 네 개가
   * 기본값이었다. 호출부가 lesions 를 안 넘기거나 서버가 병변을 안 주면
   * (undefined) 그 순간 **남의 환자 종괴가 이 환자 화면에 뜬다.**
   * 판독 화면에서 화면만 봐서는 진짜인지 구분할 수 없다.
   *
   * (그 .stl 파일들은 저장소에 없어서 지금은 404 로 안 그려질 뿐이었다.
   * 누가 public/models/duke/ 를 채우는 순간 조용히 진짜처럼 보이게 된다.)
   *
   * 비면 아무것도 안 그린다. 그게 맞는 상태다. */
  lesions = [],
  selectedLesion = null,
  showBody = true,
  /* 판독이 만든 몸 윤곽 메시(JSON). 있으면 DUKE STL 대신 이것을 쓰고,
     DUKE 좌표에 맞춘 CROP 자르기 · 카메라 대신 메시 상자에 맞춘다 */
  bodyMesh = null,
}) {
  const containerRef = useRef(null);
  const controlsRef = useRef(null);
  const lastPanXRef = useRef(0);
  const [panX, setPanX] = useState(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#111518");

    const camera = new THREE.PerspectiveCamera(
      28,
      Math.max(container.clientWidth, 1) /
        Math.max(container.clientHeight, 1),
      0.1,
      5000
    );

    const renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
    });

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(
      container.clientWidth,
      container.clientHeight
    );
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.localClippingEnabled = true;

    container.appendChild(renderer.domElement);

    scene.add(
      new THREE.HemisphereLight(0xffffff, 0x25282b, 2.0)
    );

    const keyLight = new THREE.DirectionalLight(
      0xffffff,
      2.0
    );
    keyLight.position.set(-1, 2, 4);
    scene.add(keyLight);

    const root = new THREE.Group();
    scene.add(root);

    const controls = new OrbitControls(
      camera,
      renderer.domElement
    );
    controlsRef.current = controls;
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minPolarAngle = Math.PI * 0.20;
    controls.maxPolarAngle = Math.PI * 0.80;

    const json = Boolean(bodyMesh) || lesions.some((l) => l?.mesh_data);
    const clipPlanes = json ? [] : [
      new THREE.Plane(
        new THREE.Vector3(0, 1, 0),
        -CROP.bottomY
      ),
      new THREE.Plane(
        new THREE.Vector3(0, -1, 0),
        CROP.topY
      ),
      new THREE.Plane(
        new THREE.Vector3(1, 0, 0),
        -CROP.leftX
      ),
      new THREE.Plane(
        new THREE.Vector3(-1, 0, 0),
        CROP.rightX
      ),
    ];

    const bodyMaterial = new THREE.MeshPhysicalMaterial({
      color: new THREE.Color("#aeb3b7"),
      transparent: true,
      opacity: 0.18,
      roughness: 0.94,
      metalness: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
      clippingPlanes: clipPlanes,
    });

    const outlineMaterial = new THREE.MeshBasicMaterial({
      color: new THREE.Color("#737a80"),
      transparent: true,
      opacity: 0.22,
      wireframe: true,
      clippingPlanes: clipPlanes,
      depthWrite: false,
    });

    const geometries = [];
    const materials = [bodyMaterial, outlineMaterial];
    let disposed = false;
    let loadCount = 0;

    const loader = new STLLoader();

    function addBody(geometry) {
      geometry.computeVertexNormals();

      geometries.push(geometry);

      const body = new THREE.Mesh(
        geometry,
        bodyMaterial
      );

      const outline = new THREE.Mesh(
        geometry,
        outlineMaterial
      );

      root.add(body);
      root.add(outline);
    }

    function addTumor(geometry, lesion, index) {
      geometry.computeVertexNormals();
      geometries.push(geometry);

      const color = getLesionColor(lesion, index);
      const isSelected =
        selectedLesion === index;

      const material = new THREE.MeshPhysicalMaterial({
        color: new THREE.Color(color),
        emissive: new THREE.Color(color),
        emissiveIntensity: isSelected ? 0.55 : 0.18,
        roughness: 0.34,
        metalness: 0,
        side: THREE.DoubleSide,
      });

      const mesh = new THREE.Mesh(
        geometry,
        material
      );

      mesh.userData.lesionIndex = index;
      mesh.userData.lesionId =
        lesion?.lesion_id || `L-${index + 1}`;

      root.add(mesh);
      materials.push(material);
    }

    const validLesions = lesions.filter(hasMesh);
    const stlBody = showBody && !json;
    const expected = validLesions.length + (stlBody || bodyMesh ? 1 : 0);

    function loaded() {
      loadCount += 1;
      if (loadCount >= expected) fitCamera();
    }

    if (bodyMesh) {
      addBody(jsonGeometry(bodyMesh));
      loaded();
    } else if (stlBody) {
      loader.load(
        BODY_URL,
        (geometry) => {
          if (!disposed) addBody(geometry);
          loaded();
        },
        undefined,
        (error) => {
          console.error(
            "Body STL loading failed:",
            error
          );
          loaded();
        }
      );
    }

    validLesions.forEach((lesion) => {
      const index = lesions.indexOf(lesion);
      loadGeometry(
        lesion,
        (geometry) => {
          if (!disposed) {
            addTumor(
              geometry,
              lesion,
              index
            );
          }
          loaded();
        },
        (error) => {
          console.error(
            "Tumor mesh loading failed",
            error
          );
          loaded();
        }
      );
    });

    function fitCamera() {
      if (json) return fitBox();
      const centerX =
        (CROP.leftX + CROP.rightX) / 2;
      const centerY =
        (CROP.bottomY + CROP.topY) / 2;

      const width =
        CROP.rightX - CROP.leftX;
      const height =
        CROP.topY - CROP.bottomY;

      const aspect =
        Math.max(container.clientWidth, 1) /
        Math.max(container.clientHeight, 1);

      const fov =
        THREE.MathUtils.degToRad(camera.fov);

      const distanceHeight =
        (height * 0.62) /
        Math.tan(fov / 2);

      const distanceWidth =
        (width * 0.62) /
        Math.tan(fov / 2) /
        Math.max(aspect, 0.01);

      const distance = Math.max(
        distanceHeight,
        distanceWidth
      );

      camera.position.set(
        centerX,
        centerY,
        distance
      );

      controls.target.set(
        centerX,
        centerY,
        0
      );

      controls.minDistance =
        distance * 0.65;
      controls.maxDistance =
        distance * 2.5;

      controls.update();

      lastPanXRef.current = panX;
    }

    /* JSON 메시는 판독 픽셀 좌표라 DUKE 용 CROP 이 안 맞는다 — 상자에 맞춘다 */
    function fitBox() {
      const box = new THREE.Box3().setFromObject(root);
      if (box.isEmpty()) return;
      const c = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const aspect =
        Math.max(container.clientWidth, 1) /
        Math.max(container.clientHeight, 1);
      const fov = THREE.MathUtils.degToRad(camera.fov);
      const distance =
        (Math.max(size.y, size.x / Math.max(aspect, 0.01)) * 0.62) /
          Math.tan(fov / 2) +
        size.z / 2;
      camera.position.set(c.x, c.y, c.z + Math.max(distance, 1));
      controls.target.copy(c);
      controls.minDistance = distance * 0.4;
      controls.maxDistance = distance * 3;
      controls.update();
      lastPanXRef.current = panX;
    }

    const resizeObserver =
      new ResizeObserver(() => {
        const width =
          container.clientWidth;
        const height =
          container.clientHeight;

        if (!width || !height) return;

        camera.aspect = width / height;
        camera.updateProjectionMatrix();

        renderer.setSize(
          width,
          height
        );
      });

    resizeObserver.observe(container);

    let frameId;

    function animate() {
      frameId =
        requestAnimationFrame(animate);

      controls.update();

      renderer.render(
        scene,
        camera
      );
    }

    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();

      controls.dispose();
      controlsRef.current = null;

      geometries.forEach((g) =>
        g.dispose()
      );

      materials.forEach((m) =>
        m.dispose?.()
      );

      renderer.dispose();

      if (
        renderer.domElement.parentNode ===
        container
      ) {
        container.removeChild(
          renderer.domElement
        );
      }
    };
  }, [
    lesions,
    selectedLesion,
    showBody,
    bodyMesh,
  ]);

  useEffect(() => {
    const controls = controlsRef.current;
    if (!controls) return;

    // 현재 카메라가 바라보는 화면의 가로 방향으로 패닝.
    // 월드 X축을 직접 움직이지 않기 때문에
    // 모델을 어떤 각도로 돌려도 "화면 좌우"가 유지된다.
    const delta =
      (panX - lastPanXRef.current) * 0.75;

    if (delta !== 0) {
      const camera = controls.object;
      const target = controls.target;

      const viewDirection =
        new THREE.Vector3()
          .subVectors(
            target,
            camera.position
          )
          .normalize();

      const screenRight =
        new THREE.Vector3()
          .crossVectors(
            viewDirection,
            camera.up
          )
          .normalize();

      camera.position.addScaledVector(
        screenRight,
        delta
      );

      target.addScaledVector(
        screenRight,
        delta
      );

      controls.update();
    }

    lastPanXRef.current = panX;
  }, [panX]);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        minHeight: 320,
        position: "relative",
        overflow: "hidden",
        background: "#111518",
      }}
    >
      <div
        ref={containerRef}
        style={{
          position: "absolute",
          inset: 0,
          bottom: 42,
        }}
      />

      <div
        style={{
          position: "absolute",
          left: 12,
          right: 12,
          bottom: 8,
          height: 28,
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "0 8px",
          borderRadius: 6,
          background:
            "rgba(17, 21, 24, 0.94)",
          border: "1px solid #343a40",
        }}
      >
        <span
          style={{
            color: "#8e959c",
            fontSize: 10,
          }}
        >
          화면
        </span>

        <span
          style={{
            color: "#596169",
            fontSize: 10,
          }}
        >
          ◀
        </span>

        <input
          aria-label="3D 화면 좌우 위치"
          type="range"
          min="-100"
          max="100"
          step="1"
          value={panX}
          onChange={(e) =>
            setPanX(
              Number(e.target.value)
            )
          }
          style={{
            flex: 1,
            minWidth: 0,
            accentColor: "#c9828c",
            cursor: "pointer",
          }}
        />

        <span
          style={{
            color: "#596169",
            fontSize: 10,
          }}
        >
          ▶
        </span>
      </div>
    </div>
  );
}
