import { path } from "../api";
import { go } from "../nav";
import * as H from "./home";
import { Chip, Facts, Fold } from "../lib/Parts";
import { Body } from "../lib/Body";
import { useApi } from "../lib/useApi";
import { useFile } from "../lib/files";
import Stage from "../lib/Stage";
import PathologyAi from "./PathologyAi";
import { ACCESSION_STATUS, B_CATEGORY, B_CATEGORY_LABEL, DIAGNOSIS, SEX,
         label, text, tone } from "../codes";

/* 병리과 설정 — 공통 화면 다섯 장에 끼워 넣는 «다른 점»만 모은 파일
 * ════════════════════════════════════════════════════════════════
 *
 * 화면의 뼈대는 screens/ 에 있고 두 과가 같이 쓴다. 이 파일에는
 * 병리과에서만 다른 것이 들어간다.
 *
 * 영상의학과와 갈리는 지점
 *   판독 단위   검사(study) 가 아니라 **검체(specimen)**
 *   등급 체계   BI-RADS 가 아니라 **b_category (b1~b5)**
 *   AI 소견     등급·크기·확신도가 아니라 **sTIL · TSR · 세포 수 · 간질**
 *   없는 것     조영제 알레르기 · 재촬영 · 병변 추가 · 모달리티 구분 ·
 *               **판독 정정(5장)** — 확정 사양서 §8-2, 병리는 정정
 *               경로를 두지 않는다. 확정 후 오류는 새 검체로 처리한다
 */

/* ── 서버 부르는 자리를 공통 이름으로 맞춘다 ──────────────────
   공통 화면은 cfg.api.detail(id) 처럼 부른다. 실제 경로가 과마다
   달라도 화면은 몰라도 된다 */
const api = {
  queue:      ()      => path.queue(),
  detail:     (id)    => path.specimen(id),  /* 1장 큐 */
  listDetail: (id)    => path.specimen(id),  /* 4장 목록 — 병리는 둘 다 검체다 */
  assign:     (id)    => path.assign(id),
  uploadInfo: (id)    => path.uploadInfo(id),
  /* ⚠ 판독 화면(3장)이 원본·마스크를 받을 때 쓴다. 이게 빠져 있으면
     lib/files.js 의 useFile 이 티켓을 못 받아 **아무 말 없이 빈
     뷰어**가 된다 — 오류도 안 나고 「원본 영상이 아직 연결되지
     않았습니다」만 뜬다. 목업은 image.url 로 와서 티켓을 안 타기
     때문에 목업에서는 멀쩡해 보인다 */
  ticket:     (b)     => path.ticket(b),
  analyze:    (id)    => path.analyze(id),
  progress:   (id)    => path.progress(id),
  /* ⚠ 병리는 판독 조회 경로가 아직 없다 (2026-09-16 확인).
     있는 둘을 합쳐 화면이 쓰는 모양으로 만든다.
       GET /specimens/{id}          검체 · 판정 · 정정 이력
       GET /specimens/{id}/upload   올린 파일 목록 (여기에만 있다)
     /specimens/{id}/read 가 생기면 이 함수가 한 줄로 줄어든다 */
  read: async (id) => {
    const [s, up] = await Promise.all([path.specimen(id), path.uploadInfo(id)]);
    return toRead(s, up);
  },
  draft:      (id, b) => path.draft(id, b),
  finalize:   (id, b) => path.finalize(id, b),
  list:       (o)     => path.list(o),
  /* amend 없음 — 확정 사양서 §8-2: 병리는 판독 정정 경로를 두지 않는다.
     확정 후 오류는 새 검체로 처리한다 (services/django/core/views/
     pathology.py 상단 docstring) */
  /* complete 없음 — 병리에는 «오더 확정» 단계가 없다 */
};

/* GET /specimens/{id}/upload 이 주는 StorageObject 원본 필드를 화면이
 * 기대하는 {id, name, w, h, image} 모양으로 바꾼다 — api.js 의 radFile()과
 * 같은 자리다. 병리는 storage_objects 가 아니라 uploads 로 온다
 * ({specimen_id, uploads} — views/pathology.py 의 SpecimenUploadListView). */
function pathFile(raw = {}) {
  const bytes = raw.byte_size;
  const size = typeof bytes === "number" ? `${(bytes / 1048576).toFixed(1)} MB` : "";
  const image = raw.image ?? (raw.object_key ? { key: raw.object_key } : null);
  return {
    ...raw,
    id: raw.storage_object_id ?? raw.id,
    name: raw.name ?? raw.object_key ?? `파일 ${raw.storage_object_id ?? ""}`,
    size,
    w: raw.w ?? raw.width_px,
    h: raw.h ?? raw.height_px,
    image,
  };
}

/* 서버 두 응답 → 판독 화면이 쓰는 한 덩어리.
 *
 * **서버 모양이 바뀌면 여기만 고친다.** 화면 다섯 장은 이 모양만 안다. */
function toRead(s, up) {
  const files = (up.uploads ?? []).map(pathFile);
  return {
    patient: {
      name: s.patient_name, age: s.age, sex: s.sex,
      no: s.patient_no, birth: s.birth,
    },
    unit: {
      id: s.id, no: s.specimen_no, kind: s.kind, method: s.method,
      collected_at: s.collected_at, site: s.site,
      /* ⚠ 서버는 코드(accession_status)만 준다 — 4장 목록(list.row)과
         같은 방식으로 여기서도 라벨을 입힌다. s.status_label 을 그대로
         읽던 전 코드는 그런 필드가 서버에 없어 항상 빈칸이었다. */
      reported_by: s.reported_by,
      status_label: text(s, "accession_status", ACCESSION_STATUS, "status_label"),
      amend_history: s.amend_history ?? [],
    },
    radiology_summary: s.radiology_summary ?? null,
    /* 크롭 한 장 = 원본 + (있으면) 마스크.
       ⚠ 마스크는 아직 생산자가 없다. 판독 서버가 조직 마스크 생성을
         꺼 두었다. 없으면 「마스크 없음」으로 뜨고 원본만 보인다.
         StorageObject 에 mask 칸이 없어서 항상 null 이다 */
    crops: files.map((f) => ({
      id: f.id, name: f.name,
      w: f.w ?? 512, h: f.h ?? 512,      /* 크롭은 512×512 */
      image: f.image,
      mask: f.mask ?? null,
    })),
    images: files.map((f) => ({ id: f.id, name: f.name })),
    ai: s.ai ?? [],
    doctor: s.doctor ?? {},
  };
}

export const pathology = {
  key: "pathology",
  name: "병리과",
  api,
  go: go.pathology,

  /* ── 홈 (docs/mockup/PathologyHome.html) ────────────
   *
   * 영상과 같은 틀이다. 다른 것은 판독 단위가 검체라는 것뿐이다.
   */
  home: {
    load: () => Promise.all([api.queue(), H.soft(api.list({}))])
      .then(([queue, list]) => ({ queue: H.rows(queue), specimens: H.rows(list) })),

    primary: { label: "다음 검체 받기", to: go.pathology.queue(),
               need: "pathology.queue.view" },

    queue: ({ queue }) => ({
      title: "검체 대기",
      hint: "바인딩 순서대로",
      empty: "접수 대기 검체가 없습니다",
      rows: queue.map((r) => ({
        id: r.id,
        name: H.nameOf(r),
        no: H.noOf(r),
        meta: H.who(r),
        chip: r.kind,
        chipTone: "fill",
        /* ⚠ 목업은 「· 영상 4C · 마스크 완료」까지 적는다. 영상 판정도 AI
           마스크 상태도 검체 목록에 없다 — 검체번호만 적는다 */
        sub: r.specimen_no ?? "",
        at: H.at(r.collected_at),
        to: go.pathology.read(r.id),
        why: "검체 접수",
      })),
    }),

    stuck: ({ specimens }) => [
      { tag: "초안", text: "집었는데 아직 확정 안 한 검체",
        count: specimens.filter(
          (r) => r.assigned_to && !(r.finalized_at || r.finalized)).length,
        to: go.pathology.list() },
      /* ⚠ 목업의 「마스크 확인」·「영상 대조」는 못 센다. AI 마스크를 봤는지,
         영상 판정과 맞춰 봤는지를 남기는 칸이 서버에 없다 */
    ],

    done: ({ specimens }) => {
      const it = specimens.filter((r) => H.isToday(r.finalized_at));
      return {
        summary: `확정 ${it.length}`,
        items: it.map((r) => ({
          id: r.id,
          at: H.at(r.finalized_at),
          text: `${H.nameOf(r)} · ${r.diagnosis ?? "진단"} 확정`,
          to: go.pathology.read(r.id),
        })),
      };
    },

    /* ⚠ 목업의 「판독 당번 · 다학제 회의」는 서버에 표가 없다 */
    marks: () => [],
  },

  /* 티켓이 여는 범위의 단위. 서버가 `scope_kind` 로 받는 넷
     (study · specimen · report · account) 중 하나여야 한다 —
     병리는 검체다. lib/files.js 참고 */
  scopeKind: "specimen",

  /* ── 1장 · 검체 접수 대기 ─────────────────────────────── */
  queue: {
    title: "검체 접수",
    listTitle: "접수 대기 검체",
    searchHint: "환자 · 검체번호",
    emptyText: "접수 대기 중인 검체가 없습니다",
    need: { view: "pathology.queue.view", assign: "pathology.queue.assign" },

    row: (it) => ({
      id: it.id,
      title: `${it.patient_name} (${it.age}/${label(SEX, it.sex)})`,
      sub: `${it.specimen_no} · ${it.site}`,
      chip: it.method,
      chipTone: "line",
    }),

    Detail: ({ d }) => (
      <>
        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
          ["검체번호", d.specimen_no],
          ["종류", d.kind],
          ["채취 방식", d.method],
          ["채취일시", d.collected_at],
          ["요청 부위", d.site],
        ]} />

        {d.clinical_note && (
          <Fold title="유방외과 의뢰 문구">
            <p className="quote">{d.clinical_note}</p>
          </Fold>
        )}

        {d.radiology_summary && (
          <Fold title="영상의학과 판독 요약">
            <Facts items={[
              ["BI-RADS", d.radiology_summary.birads],
              ["소견", d.radiology_summary.note],
            ]} />
            <p className="muted small">영상 판정입니다. 병리 등급(B 분류)과 다른 체계입니다.</p>
          </Fold>
        )}

        <Fold title="유도 영상" open={false}>
          <ul className="thumbs">
            {(d.guide_images ?? []).map((im) => (
              <li key={im.id}><span className="thumb" aria-hidden="true" />{im.name}</li>
            ))}
            {(d.guide_images ?? []).length === 0 && <li className="none">유도 영상이 없습니다</li>}
          </ul>
        </Fold>

        {(d.other_specimens ?? []).length > 0 && (
          <p className="muted small">이 환자의 다른 검체 {d.other_specimens.length}건</p>
        )}
      </>
    ),
  },

  /* ── 2장 · 조직 이미지 업로드 ─────────────────────────── */
  upload: {
    title: "업로드",
    infoTitle: "검체 정보",
    dropText: "조직 이미지를 드래그하세요 (여러 장 가능)",
    accept: "image/png,image/jpeg,image/tiff",
    estimate: "크롭 한 장에 약 2.2초 걸립니다.",
    need: {
      view: "pathology.upload.view",
      send: "pathology.upload.send",
      run: "pathology.ai.run",
    },
    notes: [
      "WSI 전체가 아니라 잘라낸 조직 이미지를 올립니다.",
      "한 검체에 여러 장을 올릴 수 있습니다. 같은 슬라이드라도 자른 자리에 따라 sTIL 이 크게 달라져, 여러 장을 돌려 분포를 보는 쪽이 맞습니다.",
      "장마다 분석 결과가 한 건씩 생깁니다.",
      "파일은 Django 를 거치지 않고 Go 관문으로 곧장 올라갑니다.",
    ],

    Info: ({ d }) => (
      <>
        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
          ["검체번호", d.specimen_no],
          ["종류", d.kind],
          ["병변 위치", d.site],
        ]} />
        {d.radiology_summary && (
          <Fold title="영상 판독 요약" open={false}>
            <p>{d.radiology_summary.note}</p>
          </Fold>
        )}
      </>
    ),
  },

  /* ── 3장 · 판독 ───────────────────────────────────────── */
  read: {
    title: "판독",
    infoName: "검체 정보",
    saveHint: "저장하면 확진이 확정되고 유방외과로 소견이 전송됩니다. 되돌릴 수 없습니다.",
    need: {
      view: "pathology.read.view",
      ai: "pathology.ai.view",
      draft: "pathology.read.draft",
      finalize: "pathology.read.finalize",
    },
    ready: (f) => Boolean(f.b_category && f.diagnosis),

    /* 뷰어에 무엇을 얹나 — 병리는 **PNG 마스크** 한 장이다.
       조직 분할 결과를 픽셀마다 칠한 것이라 도형으로 못 그린다.
       크롭 한 장에 마스크 한 장이 짝이다 */
    stage: (d, i = 0) => {
      const c = (d.crops ?? [])[i];
      return {
        /* { url } 이면 그대로, { key } 면 티켓 받아 Go 에서 가져온다 */
        image: c?.image,
        maskImage: c?.mask,
        w: c?.w ?? 512, h: c?.h ?? 512,     /* 크롭은 512×512 */
        alt: `크롭 ${i + 1}`,
        shapes: [],            /* 병리는 도형이 없다 — 마스크가 그림이다 */
      };
    },

    Info: ({ d, slide, onSlide }) => (
      <>
        <Facts items={[
          ["환자", `${d.patient.name} (${d.patient.age}/${label(SEX, d.patient.sex)})`],
          ["검체번호", d.unit.no],
          ["종류", d.unit.kind],
          ["채취 방식", d.unit.method],
          ["채취일시", d.unit.collected_at],
          ["병변 위치", d.unit.site],
        ]} />
        {d.radiology_summary && (
          <Fold title="영상의학과 판독 요약" open={false}>
            <p>{d.radiology_summary.note}</p>
          </Fold>
        )}
        <Fold title={`올린 크롭 ${(d.crops ?? []).length}장`}>
          <ul className="slides">
            {(d.crops ?? []).map((c, i) => (
              <li key={c.id} className={slide === i ? "on" : undefined}>
                <button onClick={() => onSlide?.(i)}>
                  크롭 {i + 1} · {c.name}
                  {!c.mask && <small> · 마스크 없음</small>}
                </button>
              </li>
            ))}
          </ul>
        </Fold>
      </>
    ),

    Ai: PathologyAi,

    Doctor: ({ f, set }) => (
      <>
        <label className="field">
          <span>악성 / 양성 여부</span>
          <select value={f.diagnosis ?? ""} onChange={(e) => set("diagnosis", e.target.value)}>
            <option value="">선택하세요</option>
            {Object.entries(DIAGNOSIS).map(([v, t]) => (
              <option key={v} value={v}>{t}</option>
            ))}
          </select>
        </label>

        {/* ⚠ BI-RADS 가 아니다. BI-RADS 는 영상 체계이고 병리는 B 분류다 */}
        <label className="field">
          <span>등급 (B 분류)</span>
          <select value={f.b_category ?? ""} onChange={(e) => set("b_category", e.target.value)}>
            <option value="">선택하세요</option>
            {B_CATEGORY.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>

        <label className="field">
          <span>판독 소견</span>
          <textarea className="lg" rows={10} value={f.finding_note ?? ""}
                    placeholder="소견"
                    onChange={(e) => set("finding_note", e.target.value)} />
        </label>
      </>
    ),
  },

  /* ── 4장 · 전체 환자 목록 ─────────────────────────────── */
  list: {
    title: "환자 목록",
    /* 영상의학과 목록과 같은 목록 1 : 상세 2 구조다. 병리는 한 검체의
       조직 사진만 보므로 모달리티 탭 없이 첫 조직 사진을 고정으로 둔다. */
    splitSide: "third",
    hideDashboard: true,
    listTitle: "검체 목록",
    searchHint: "환자 · 검체번호",
    /* 검색이 훑는 칸. **검색창에 적어 둔 것과 같아야 한다** —
       「환자 · 검체번호」라고 써 놓고 다른 데까지 걸리면 왜 걸렸는지
       모른다 */
    search: ["patient_name", "specimen_no"],
    need: { view: "pathology.list.view" },

    sorts: [
      { key: "patient__name", label: "이름" },
      { key: "collected_at", label: "채취 순" },
      { key: "accessioned_at", label: "접수 순" },
      { key: "accession_status", label: "진행상황" },
      { key: "report__last_viewed_at", label: "유방외과 열람" },
    ],

    cols: [
      { key: "patient", label: "환자", w: "22%" },
      { key: "specimen", label: "검체번호", w: "20%" },
      { key: "collected", label: "채취일", w: "16%" },
      { key: "status", label: "진행상황", w: "18%" },
      { key: "viewed", label: "유방외과", w: "14%" },
    ],

    /* 진행상황은 accession_status 와 finalized_at 을 합쳐 한글로 낸다.
       unbound 는 이 목록에 안 뜬다 — 바인딩 전 검체다 */
    row: (r) => ({
      id: r.id,
      patient: `${r.patient_name} (${r.age}/${label(SEX, r.sex)})`,
      specimen: r.specimen_no,
      collected: r.collected_at,
      status: <Chip tone={tone("accession", r.accession_status)}>
        {text(r, "accession_status", ACCESSION_STATUS, "status_label")}
      </Chip>,
      /* 「확인」이 아니라 「열람」이다 — 자동 기록이라 의도적 확인이 아니다 */
      viewed: r.viewed_at
        ? <Chip tone="line">열람</Chip>
        : <Chip tone="dot">미열람</Chip>,
    }),

    Detail: ({ d, cfg }) => <PathologyListDetail d={d} cfg={cfg} />,
  },

  /* 5장(판독 정정) 없음 — 확정 사양서 §8-2: 병리는 정정 경로를 두지
     않는다. 확정 후 오류는 새 검체로 처리한다. List.jsx 가 cfg.amend
     존재 여부로 버튼을 감추고, nav.js 에도 이 과의 amend 라우트가 없다. */
};

/* 병리과 목록의 오른쪽 상세. 영상의학과 목록과 같은 «조회 전용 뷰어 ·
 * 상세 정보» 두 칸이지만, 병리는 검체의 첫 조직 사진만 고정으로 보인다.
 * 사진을 넘기거나 판독 도구를 여는 기능은 목록에 두지 않는다. */
function PathologyListDetail({ d, cfg }) {
  const read = useApi(() => cfg.api.read(d.id), [d.id]);

  return (
    <div className="list-detail-cols">
      <div className="list-detail-viewer">
        <Body loading={read.loading} error={read.error} onRetry={read.reload}>
          {read.data && <FixedTissueViewer read={read.data} cfg={cfg} />}
        </Body>
      </div>
      <div className="list-detail-info">
        <Facts items={[
          ["환자", `${d.patient_name} (${d.age}/${label(SEX, d.sex)})`],
          ["검체번호", d.specimen_no],
          ["종류", d.kind],
          ["채취일시", d.collected_at],
          ["담당 병리의", d.reported_by],
          ["진행상황", text(d, "accession_status", ACCESSION_STATUS, "status_label")],
          ["유방외과 열람", d.viewed_at ?? "미열람"],
        ]} />
        <Fold title="판독 결과" open={Boolean(d.finalized)}>
          {d.finalized ? (
            <>
              <Facts items={[
                ["진단", text(d, "diagnosis", DIAGNOSIS, "diagnosis_label")],
                ["등급", label(B_CATEGORY_LABEL, d.b_category)],
              ]} />
              <p className="quote">{d.finding_note}</p>
            </>
          ) : <p className="muted">아직 확정된 판독이 없습니다.</p>}
        </Fold>
      </div>
    </div>
  );
}

function FixedTissueViewer({ read, cfg }) {
  const crop = read.crops?.[0] ?? null;
  const original = useFile(crop?.image, cfg.api.ticket, { kind: cfg.scopeKind, id: read.unit.id });
  const mask = useFile(crop?.mask, cfg.api.ticket, { kind: cfg.scopeKind, id: read.unit.id });

  return (
    <div className="list-viewer pathology-fixed-viewer">
      <Stage src={original.src} w={crop?.w} h={crop?.h}
        alt={crop?.name ?? "조직 사진"} loading={original.loading} loadError={original.error}
        mask={mask.src} mode="review" />
    </div>
  );
}

