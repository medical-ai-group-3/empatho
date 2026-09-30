import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { hasMesh, loadGeometry } from "./meshData";

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

export default function Tumor3DViewer({
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
      visibleLesions.filter(hasMesh);

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

      loadGeometry(
        lesion,
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
        (error) => {
          console.error(
            "Tumor mesh loading failed",
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
