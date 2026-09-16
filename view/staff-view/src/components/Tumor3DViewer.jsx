import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

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

function getLesionColor(lesion, index) {
  return lesion?.color || DEFAULT_COLORS[index % DEFAULT_COLORS.length];
}

function getMeshUrl(lesion) {
  return (
    lesion?.mesh_url ||
    (lesion?.mesh_image_id?.endsWith(".stl")
      ? `/models/duke/${lesion.mesh_image_id}`
      : null)
  );
}

export default function Tumor3DViewer({
  lesions = DEFAULT_LESIONS,
  selectedLesion = null,
}) {
  const containerRef = useRef(null);

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

    renderer.setPixelRatio(
      Math.min(window.devicePixelRatio, 2)
    );

    renderer.setSize(
      container.clientWidth,
      container.clientHeight
    );

    renderer.outputColorSpace =
      THREE.SRGBColorSpace;

    container.appendChild(renderer.domElement);

    scene.add(
      new THREE.HemisphereLight(
        0xffffff,
        0x25282b,
        2.0
      )
    );

    const light = new THREE.DirectionalLight(
      0xffffff,
      2.2
    );

    light.position.set(-1, 2, 4);
    scene.add(light);

    const root = new THREE.Group();
    scene.add(root);

    const controls = new OrbitControls(
      camera,
      renderer.domElement
    );

    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enablePan = false;
    controls.minPolarAngle = Math.PI * 0.20;
    controls.maxPolarAngle = Math.PI * 0.80;

    const loader = new STLLoader();
    const geometries = [];
    const materials = [];

    const visibleLesions =
      selectedLesion === null
        ? lesions
        : lesions.filter(
            (_, index) =>
              index === selectedLesion
          );

    let loaded = 0;

    const validLesions =
      visibleLesions.filter((x) =>
        getMeshUrl(x)
      );

    if (!validLesions.length) {
      camera.position.set(0, 0, 3);
      controls.target.set(0, 0, 0);
      controls.update();
    }

    function finishLoad() {
      loaded += 1;

      if (loaded === validLesions.length) {
        fitToTumors();
      }
    }

    validLesions.forEach((lesion) => {
      const originalIndex =
        lesions.indexOf(lesion);

      const url = getMeshUrl(lesion);

      loader.load(
        url,
        (geometry) => {
          geometry.computeVertexNormals();
          geometries.push(geometry);

          const color =
            getLesionColor(
              lesion,
              originalIndex
            );

          const material =
            new THREE.MeshPhysicalMaterial({
              color:
                new THREE.Color(color),
              emissive:
                new THREE.Color(color),
              emissiveIntensity:
                selectedLesion === null
                  ? 0.16
                  : 0.40,
              roughness: 0.30,
              metalness: 0,
              side: THREE.DoubleSide,
            });

          materials.push(material);

          const mesh =
            new THREE.Mesh(
              geometry,
              material
            );

          mesh.userData.lesionIndex =
            originalIndex;

          mesh.userData.lesionId =
            lesion.lesion_id;

          root.add(mesh);
          finishLoad();
        },
        undefined,
        (error) => {
          console.error(
            `Tumor STL loading failed: ${url}`,
            error
          );
          finishLoad();
        }
      );
    });

    function fitToTumors() {
      const box =
        new THREE.Box3().setFromObject(
          root
        );

      if (box.isEmpty()) return;

      const center =
        box.getCenter(
          new THREE.Vector3()
        );

      const size =
        box.getSize(
          new THREE.Vector3()
        );

      const maxSize =
        Math.max(
          size.x,
          size.y,
          size.z
        );

      // 병변을 화면 중앙으로 가져온다.
      root.position.set(
        -center.x,
        -center.y,
        -center.z
      );

      const fov =
        THREE.MathUtils.degToRad(
          camera.fov
        );

      const distance =
        (maxSize * 0.78) /
        Math.tan(fov / 2);

      camera.position.set(
        0,
        0,
        Math.max(distance, 1)
      );

      controls.target.set(
        0,
        0,
        0
      );

      controls.minDistance =
        Math.max(distance * 0.55, 0.1);

      controls.maxDistance =
        Math.max(distance * 4, 10);

      controls.update();
    }

    const resizeObserver =
      new ResizeObserver(() => {
        const width =
          container.clientWidth;
        const height =
          container.clientHeight;

        if (!width || !height) return;

        camera.aspect =
          width / height;

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
        requestAnimationFrame(
          animate
        );

      controls.update();

      renderer.render(
        scene,
        camera
      );
    }

    animate();

    return () => {
      cancelAnimationFrame(frameId);
      resizeObserver.disconnect();
      controls.dispose();

      geometries.forEach((g) =>
        g.dispose()
      );

      materials.forEach((m) =>
        m.dispose()
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
  }, [lesions, selectedLesion]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        minHeight: 320,
        background: "#111518",
      }}
    />
  );
}
