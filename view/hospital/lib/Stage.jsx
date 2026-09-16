import { useCallback, useEffect, useRef, useState } from "react";

/* 판독 뷰어 — 원본 위에 AI 결과를 얹는다
 * ════════════════════════════════════════════════════════════════
 *
 * 얹는 것이 두 가지다. **둘 다 원본 픽셀 좌표계 위에 놓인다.**
 *
 *   PNG      병리 조직 분할 마스크. 이미지 한 장을 그대로 겹친다
 *   SVG      초음파 폴리곤 · 맘모 박스. 좌표를 받아 우리가 그린다
 *
 * 맘모가 박스인 이유 — 검출 모델이라 마스크를 안 낸다. 병변마다
 * 네 숫자(좌·상·우·하)를 낸다. 박스도 SVG 라 폴리곤과 같은 길로 간다.
 *
 * ── 좌표를 맞추는 방법 ───────────────────────────────────────
 * 화면에 보이는 크기는 확대·창 크기에 따라 계속 바뀌는데, AI 가 준
 * 좌표는 **원본 픽셀** 기준이다. 그래서 SVG 에 viewBox 를 원본 크기로
 * 걸고 원본 이미지와 같은 상자 안에 겹쳐 둔다. 그러면 확대하든 줄이든
 * 브라우저가 알아서 같이 움직인다. **우리가 좌표를 다시 계산하지 않는다.**
 *
 * ⚠ 그래서 원본의 픽셀 크기(w · h)가 반드시 필요하다. 없으면 좌표를
 *   놓을 기준이 없다.
 *
 * ── 투명도 ───────────────────────────────────────────────────
 * 저장하지 않는다. 보는 사람의 지금 형편이지 판독 내용이 아니다.
 */

const MIN = 0.1;
const MAX = 12;
const STEP = 1.2;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export default function Stage({
  src, w, h, alt = "원본 영상",
  mask,                 /* PNG 마스크 주소 — 없으면 안 그린다 */
  shapes = [],          /* SVG 로 그릴 것들 */
  opacity = 45,         /* 0~100 */
  pick, onPick,         /* 고른 병변 — 목록과 뷰어가 같이 쓴다 */
  loading, loadError,
  bright = 100, contrast = 100,   /* 화면 보정 — 창값이 아니다 */
  onFull, full,
}) {
  const boxRef = useRef(null);
  const [t, setT] = useState({ z: 1, x: 0, y: 0 });
  const [drag, setDrag] = useState(null);
  const [broke, setBroke] = useState(false);

  /* 상자에 딱 맞게 — 처음 열 때와 [맞춤] 을 눌렀을 때 */
  const fit = useCallback(() => {
    const box = boxRef.current;
    if (!box || !w || !h) return;
    const { width, height } = box.getBoundingClientRect();
    const z = Math.min(width / w, height / h);
    setT({ z, x: (width - w * z) / 2, y: (height - h * z) / 2 });
  }, [w, h]);

  useEffect(() => { fit(); }, [fit, src, full]);

  /* 창 크기가 바뀌면 다시 맞춘다 — 패널을 접었다 펴면 폭이 달라진다 */
  useEffect(() => {
    const box = boxRef.current;
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit);
    ro.observe(box);
    return () => ro.disconnect();
  }, [fit]);

  /* 휠로 확대 — **커서 밑에 있던 지점이 그 자리에 남게** 한다.
     가운데 기준으로 확대하면 보던 곳이 화면 밖으로 달아난다 */
  function onWheel(e) {
    e.preventDefault();
    const r = boxRef.current.getBoundingClientRect();
    const cx = e.clientX - r.left;
    const cy = e.clientY - r.top;
    setT((p) => {
      const z = clamp(p.z * (e.deltaY < 0 ? STEP : 1 / STEP), MIN, MAX);
      const k = z / p.z;
      return { z, x: cx - (cx - p.x) * k, y: cy - (cy - p.y) * k };
    });
  }

  function zoom(dir) {
    const r = boxRef.current.getBoundingClientRect();
    const cx = r.width / 2;
    const cy = r.height / 2;
    setT((p) => {
      const z = clamp(p.z * (dir > 0 ? STEP : 1 / STEP), MIN, MAX);
      const k = z / p.z;
      return { z, x: cx - (cx - p.x) * k, y: cy - (cy - p.y) * k };
    });
  }

  function down(e) {
    if (e.button !== 0) return;
    setDrag({ x: e.clientX - t.x, y: e.clientY - t.y });
  }
  function move(e) {
    if (!drag) return;
    setT((p) => ({ ...p, x: e.clientX - drag.x, y: e.clientY - drag.y }));
  }
  const up = () => setDrag(null);

  const ready = Boolean(src && w && h);

  return (
    <div className="stage">
      <div className="vtools">
        <button className="vtool" onClick={fit} aria-label="화면에 맞춤" title="화면에 맞춤">⌖</button>
        <button className="vtool" onClick={() => zoom(1)} aria-label="확대" title="확대">＋</button>
        <button className="vtool" onClick={() => zoom(-1)} aria-label="축소" title="축소">－</button>
        <span className="vzoom">{Math.round(t.z * 100)}%</span>
        <button className="vtool" onClick={onFull}
                aria-label={full ? "전체화면 끄기" : "전체화면"}
                title={full ? "전체화면 끄기" : "전체화면"}>⛶</button>
      </div>

      <div
        ref={boxRef}
        className={`stage-box ${drag ? "grabbing" : ""}`}
        onWheel={onWheel} onMouseDown={down} onMouseMove={move}
        onMouseUp={up} onMouseLeave={up}
      >
        {!ready && (
          /* 원본이 없다. 격자만 두지 않고 **왜 비었는지 말한다** */
          <div className="vart">
            <p>
              {loading ? "영상을 불러오는 중…"
                : loadError ? `영상을 불러오지 못했습니다 (${loadError.status ?? "오류"})`
                : "원본 영상이 아직 연결되지 않았습니다"}
            </p>
          </div>
        )}

        {ready && (
          <div className="stage-tf"
               style={{ transform: `translate(${t.x}px, ${t.y}px) scale(${t.z})` }}>
            {broke
              ? <div className="vart" style={{ width: w, height: h }}>
                  <p>원본을 불러오지 못했습니다</p>
                </div>
              : <img className="stage-img" src={src} alt={alt} width={w} height={h}
                     draggable={false} onError={() => setBroke(true)}
                     /* ⚠ 보정은 **원본에만** 건다. 마스크와 도형에 같이
                        걸면 AI 결과 색까지 바뀌어 판단이 흔들린다 */
                     style={{ filter: `brightness(${bright}%) contrast(${contrast}%)` }} />}

            {/* ── PNG 마스크 (병리) ─────────────────────────── */}
            {mask && (
              <img className="stage-mask" src={mask} alt="" aria-hidden="true"
                   width={w} height={h} draggable={false}
                   style={{ opacity: opacity / 100 }} />
            )}

            {/* ── SVG 도형 (초음파 폴리곤 · 맘모 박스) ───────── */}
            {shapes.length > 0 && (
              <svg className="stage-svg" viewBox={`0 0 ${w} ${h}`}
                   width={w} height={h} style={{ opacity: opacity / 100 }}>
                {shapes.map((s) => (
                  <Shape key={s.id} s={s} on={pick === s.id} onPick={onPick}
                         scale={t.z} />
                ))}
              </svg>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* 도형 하나.
 *
 * ⚠ 선 굵기와 글자 크기를 **배율로 나눈다.** 안 나누면 확대할수록 선이
 *   같이 두꺼워져서, 작은 병변이 제 테두리에 덮여 안 보인다. */
function Shape({ s, on, onPick, scale }) {
  const sw = 2 / scale;
  const fs = 13 / scale;
  const cls = `shp ${on ? "on" : ""}`;
  const hit = onPick ? () => onPick(s.id) : undefined;

  /* 구멍 뚫린 덩어리 — evenodd 가 겹친 안쪽을 비운다 */
  if (s.kind === "path") {
    return (
      <g className={cls} onClick={hit}>
        <path d={s.d} fillRule="evenodd" strokeWidth={sw} />
        {s.label && <text x={s.x ?? 0} y={(s.y ?? 0) - sw * 3} fontSize={fs}>{s.label}</text>}
      </g>
    );
  }

  /* 박스 — 맘모 */
  return (
    <g className={cls} onClick={hit}>
      <rect x={s.x} y={s.y} width={s.w} height={s.h} strokeWidth={sw} rx={2 / scale} />
      {s.label && <text x={s.x} y={s.y - sw * 3} fontSize={fs}>{s.label}</text>}
    </g>
  );
}

/* ── 서버 값을 도형으로 바꾸는 자리 ─────────────────────────────
 *
 * 과별 설정(dept/*.jsx)에서 불러 쓴다. **여기 한 곳만 고치면** 좌표
 * 형식이 바뀌어도 화면은 안 건드려도 된다.
 */

/* 맘모 — 박스. 검출 모델이라 마스크가 없다.
 *
 * ── 서빙이 내는 모양 (2026-09-16, serve_mammo.py 확인) ──────
 *
 *   lesion.box = [x0, y0, x1, y1]     좌·상·우·하, **원본 픽셀**
 *
 *   serve_mammo.py 의 오버레이가 이렇게 쓴다 —
 *     x0, y0, x1, y1 = [int(v) for v in l["box"]]
 *     cv2.rectangle(img, (x0, y0), (x1, y1), …)
 *   그리고 그 img 는 read_mammogram() 이 읽은 **원본**이다.
 *   축소는 사각형을 그린 뒤에 일어난다.
 *
 * ⚠ 학습·채점 쪽 덤프(coco_predictions_bbox.json)는 COCO 라서
 *   bbox=[x, y, w, h] 다. **서빙과 형식이 다르다.** 둘을 헷갈리면
 *   박스가 엉뚱한 자리에 그려진다. 화면이 보는 것은 서빙 쪽이다.
 *
 * ── 타일 좌표가 아니다 ─────────────────────────────────────
 *   1008 타일로 훑기는 하지만(predict.py:18) 병합하면서 원본 좌표로
 *   돌아온다. 화면에서 배율을 곱할 일이 없다.
 *
 * ── 정규화 값도 받아 둔다 ──────────────────────────────────
 *   네 값이 모두 1 이하이면 0~1 로 보고 원본 크기를 곱한다.
 *   지금 서빙은 픽셀을 내지만, Django 를 거치며 바뀌어도 안 깨진다.
 */
const ORDER = "xyxy";        /* "xyxy" | "xywh" — 서빙은 xyxy */

export function boxesFromLesions(lesions = [], w = 0, h = 0) {
  return lesions
    .map((l, i) => {
      /* 서빙은 box, 학습 덤프는 bbox. 둘 다 받는다 */
      const raw = l.box ?? l.bbox;
      if (!Array.isArray(raw) || raw.length !== 4) return null;
      let [a, b, c, e] = raw;

      if (w && h && [a, b, c, e].every((v) => v >= 0 && v <= 1)) {
        a *= w; b *= h; c *= w; e *= h;
      }

      const box = ORDER === "xywh"
        ? { x: a, y: b, w: c, h: e }
        : { x: a, y: b, w: c - a, h: e - b };

      return {
        id: l.id ?? `b${i}`,
        kind: "box",
        ...box,
        /* birads 는 null 일 수 있다 — 등급을 못 낸 검출이다 */
        label: [
          l.kind === "calcification" ? "석회" : "종괴",
          l.birads != null ? `BI-RADS ${l.birads}` : "등급 없음",
          l.biopsy ? "생검" : null,
        ].filter(Boolean).join(" · "),
      };
    })
    .filter((s) => s && s.w > 0 && s.h > 0);
}

/* 초음파 — 폴리곤. 마스크 파일이 없어 좌표로 온다.
 *
 * 응답 모양 (2026-09-16 확인)
 *   outer          바깥 테두리
 *   holes          구멍. 병변 안에 뚫린 자리다
 *   n_components   덩어리 수. 둘 이상이면 outer 도 여럿이다
 *
 * **구멍이 있어서 polygon 으로 못 그린다.** <polygon> 은 구멍을 모른다.
 * 바깥과 구멍을 한 <path> 의 여러 조각으로 넣고 fill-rule="evenodd" 를
 * 걸면, 겹친 안쪽이 자동으로 뚫린다.
 *
 * 좌표는 **원본 픽셀** 기준이다 (274×351 정도). 추론은 1008² 로 늘려
 * 쓰지만 응답은 원본으로 되돌려 준다.
 *
 * ⚠ 형태 지표를 이 폴리곤에서 다시 계산하지 않는다. 표시용으로
 *   단순화돼 있어 서버가 준 값과 달라진다. 면적·직경은 서버 값을 쓴다.
 */
function rings(v) {
  if (!Array.isArray(v) || v.length === 0) return [];
  /* [[x,y], …] 한 겹인지 [[[x,y], …], …] 두 겹인지 가려낸다 */
  const flat = Array.isArray(v[0]) && typeof v[0][0] === "number";
  return flat ? [v] : v;
}

function ringPath(ring) {
  const pts = ring.map((p) => (Array.isArray(p) ? p : [p.x, p.y]));
  if (pts.length < 3) return "";
  return `M${pts.map(([x, y]) => `${x},${y}`).join("L")}Z`;
}

export function polygonsFromAi(ai) {
  const outer = rings(ai?.polygon?.outer ?? ai?.outer);
  const holes = rings(ai?.polygon?.holes ?? ai?.holes);
  if (outer.length === 0) return [];

  const d = [...outer, ...holes].map(ringPath).filter(Boolean).join(" ");
  if (!d) return [];

  const all = outer.flat().map((p) => (Array.isArray(p) ? p : [p.x, p.y]));
  const n = ai?.polygon?.n_components ?? ai?.n_components ?? outer.length;

  return [{
    id: "us-1",
    kind: "path",
    d,
    x: Math.min(...all.map((p) => p[0])),
    y: Math.min(...all.map((p) => p[1])),
    label: [
      ai.category ? `등급 ${ai.category}` : null,
      n > 1 ? `덩어리 ${n}` : null,
    ].filter(Boolean).join(" · ") || null,
  }];
}
