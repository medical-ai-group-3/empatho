import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const BODY_URL =
  "/models/duke/DUKE_001_body_silhouette.stl";

const DEFAULT_LESIONS = [
  {
    lesion_id: "L-001",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion01.stl",
    color: "#C9828C",
  },
  {
    lesion_id: "L-002",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion02.stl",
    color: "#8FA8C2",
  },
  {
    lesion_id: "L-003",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion03.stl",
    color: "#B59A6A",
  },
  {
    lesion_id: "L-004",
    mesh_url:
      "/models/duke/DUKE_001_tumor_lesion04.stl",
    color: "#9B8FB5",
  },
];

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

function getMeshUrl(lesion) {
  // 현재 mock에서는 mesh_url을 사용할 수 있고,
  // 기존 canonical 데이터에서는 mesh_image_id가 있을 수 있다.
  return (
    lesion?.mesh_url ||
    (lesion?.mesh_image_id?.endsWith(".stl")
      ? `/models/duke/${lesion.mesh_image_id}`
      : null)
  );
}

export default function Anatomy3DViewer({
  lesions = DEFAULT_LESIONS,
  selectedLesion = null,
  showBody = true,
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

    const clipPlanes = [
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

    function loaded() {
      loadCount += 1;

      if (loadCount >=
        lesions.filter((x) => getMeshUrl(x)).length +
        (showBody ? 1 : 0)
      ) {
        fitCamera();
      }
    }

    if (showBody) {
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

    const validLesions = lesions.filter((x) =>
      getMeshUrl(x)
    );

    validLesions.forEach((lesion) => {
      const index = lesions.indexOf(lesion);
      const url = getMeshUrl(lesion);

      loader.load(
        url,
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
        undefined,
        (error) => {
          console.error(
            `Tumor STL loading failed: ${url}`,
            error
          );
          loaded();
        }
      );
    });

    function fitCamera() {
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
