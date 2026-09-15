import { useState } from "react";
import { Card, Page, Slot, Btn } from "./lib/Page";
import { Bar, Chip, Drop, Modal, Queue, Save, Search, Sort,
         Split, Table, Viewer, Zoom } from "./lib/Parts";
import AiPanel from "./lib/AiPanel";

/* 뼈대 — nav.js 의 kind 하나에 하나씩.
 *
 * **화면 스물세 개를 파일 스물세 개로 만들지 않는다.** 지금은 자리를 잡는
 * 단계라 내용이 없고, 파일만 늘리면 나중에 공통 부품을 고칠 때 스물세 번
 * 손대게 된다. 뼈대를 아홉으로 묶고 화면은 표(nav.js)로 가른다.
 *
 * 화면 하나가 진짜로 만들어질 때 그 화면만 떼어 파일로 옮기면 된다.
 * 그때까지 여기 있는 것은 **자리와 동작**이다 — 목록을 누르면 오른쪽이
 * 바뀌고, 패널이 접히고, 팝업이 뜨는 것까지는 지금도 돈다.
 */

/* 껍데기가 쓰는 가짜 줄들. 서버가 붙으면 통째로 사라진다 */
const NAMES = ["이정민", "윤서현", "오세라", "박서연", "김도윤", "한지우", "최은영"];
const rows = (n, f) => Array.from({ length: n }, (_, i) => f(i));

const demoQueue = rows(7, (i) => ({
  id: i + 1,
  title: `${NAMES[i]}  P-2026-004${17 - i}`,
  sub: "좌측 유방 · Core Needle",
  chip: i === 0 ? "확인 완료" : "대기",
  chipTone: i === 0 ? "dot" : "line",
}));

const demoRows = rows(6, (i) => ({
  id: i + 1,
  pid: `P-2026-004${17 - i}`,
  name: NAMES[i],
  age: `${52 - i} · 여`,
  state: <Chip tone={i === 0 ? "fill" : i < 3 ? "line" : "dot"}>
           {i === 0 ? "판독 중" : i < 3 ? "판독 완료" : "AI 분석 중"}</Chip>,
  ok: i === 0 ? "미확인" : <Chip tone="dot">확인</Chip>,
}));

const COLS = [
  { key: "pid",  label: "환자 ID", w: "22%" },
  { key: "name", label: "이름",    w: "16%" },
  { key: "age",  label: "나이 · 성별", w: "16%" },
  { key: "state", label: "진행 상황", w: "24%" },
  { key: "ok",   label: "유방외과 확인" },
];

export default function Skeleton({ dept, screen }) {
  const crumb = screen.crumb ?? [dept.name, screen.title];
  const body  = BODY[screen.kind] ?? (() => <Slot what={screen.kind} />);

  return (
    <Page crumb={crumb} title={screen.title} badge={screen.badge} sub={screen.sub}
          right={<span className="src">설계서 p.{screen.page}</span>}>
      {body({ dept, screen })}
    </Page>
  );
}

/* ── 뼈대 아홉 ─────────────────────────────────────────────── */
const BODY = {

  dash: () => (
    <>
      <div className="stats">
        {[["대기", 7], ["진행", 2], ["분석 중", 4], ["완료", 11]].map(([k, v]) => (
          <div className="stat" key={k}><b>{v}</b><span>{k}</span></div>
        ))}
      </div>
      <div className="grid2">
        <Card title="오늘 접수"><Slot what="접수 목록" h={220} /></Card>
        <Card title="방문 환자 모니터링"><Slot what="방문 현황" h={220} /></Card>
      </div>
    </>
  ),

  queue: () => <QueueBody />,

  list: () => <ListBody />,

  cal: () => (
    <div className="grid2">
      <Card title="전체 예약 캘린더">
        <Slot what="달력" note="날짜를 누르면 그 날짜로 예약이 시작됩니다" h={320} />
      </Card>
      <Card title="예약 목록"><Slot what="날짜별 예약" h={320} /></Card>
    </div>
  ),

  form: ({ screen }) => (
    <div className="narrow">
      <Card title={screen.title}>
        <Slot what="입력 서식" note="칸 구성은 화면을 만들 때 채웁니다" h={240} />
        <Save hint="저장하면 다음 부서로 전달됩니다." />
      </Card>
    </div>
  ),

  upload: () => <UploadBody />,

  read: () => <ReadBody />,

  amend: () => (
    <>
      <Card className="callout">
        <b>정정된 판독은 기존 판독의 수정 이력을 남기며, 이전 판독 내용은 모두 보존됩니다.</b>
      </Card>
      <div className="grid3">
        <Card title="환자 기본 정보"><Slot what="환자 · 검체 정보" h={220} /></Card>
        <Card title="주요 이미지"><Slot what="기존 판독 시 참조된 영역" h={220} /></Card>
        <Card title="정정 사유"><Slot what="사유 · 세부 분류 · 세부 소견" h={220} /></Card>
      </div>
      <div className="grid2">
        <Card title="기존 판독 내용" right={<Btn>이전 판독 전문 보기</Btn>}>
          <Slot what="저장된 판독" h={200} />
        </Card>
        <Card title="정정 판독 내용 (수정 후)">
          <Slot what="편집기" h={200} />
          <Save hint="저장 시 유방외과에 정정 알림이 전송됩니다." />
        </Card>
      </div>
    </>
  ),

  report: () => (
    <>
      <Card title="환자 타임라인">
        <Slot what="맘모 · 초음파 · MRI · 병리 — 어디까지 진행되었는지" h={70} />
      </Card>
      <div className="grid2">
        <Card title="통합 뷰어" pad={false}>
          <Viewer
            tabs={<><button className="pill on">맘모</button>
                    <button className="pill">초음파</button>
                    <button className="pill">MRI</button>
                    <button className="pill">병리</button></>}
            rightPanel={<Slot what="검사별 요약" />} rightName="검사 요약">
            <div className="vart" />
          </Viewer>
        </Card>
        <Card title="종합 리포트"><Slot what="리포트 · 수술 여부" h={340} /></Card>
      </div>
    </>
  ),
};

/* ── 동작이 실제로 도는 뼈대 셋 ─────────────────────────────── */

function QueueBody() {
  const [list, setList] = useState(demoQueue);
  const [pick, setPick] = useState(1);
  const move = (a, b) => setList((l) => {
    const n = [...l]; n.splice(b, 0, ...n.splice(a, 1)); return n;
  });
  const step = (d) => {
    const i = list.findIndex((x) => x.id === pick);
    const j = Math.min(list.length - 1, Math.max(0, i + d));
    setPick(list[j].id);
  };

  return (
    <Split
      left={<Card title="대기 환자" right={<span className="src">환자 순서대로 배치</span>} pad={false}>
        <Queue items={list} value={pick} onPick={setPick} onMove={move}
               onPrev={() => step(-1)} onNext={() => step(1)} />
      </Card>}
      right={<Card title="선택한 환자">
        <Slot what="환자 · 검사 상세" note="왼쪽에서 고른 환자가 여기에 뜹니다" h={280} />
        <div className="rowb"><Btn>반려</Btn><Btn kind="fill">접수 · 업로드</Btn></div>
      </Card>}
    />
  );
}

function ListBody() {
  const [pick, setPick] = useState(1);
  const [sort, setSort] = useState("접수 순서");
  return (
    <Split side="wide"
      left={<Card
        right={<><Search placeholder="환자 ID, 검체 ID, 이름" />
                 <Sort items={["이름순", "접수 순서", "유방외과 확인", "진행 상황"]}
                       value={sort} onChange={setSort} /></>}
        pad={false}>
        <Table cols={COLS} rows={demoRows} value={pick} onPick={setPick} />
        <div className="tbl-foot"><span>18명 중 1–6 표시</span><Slot what="쪽 넘김" /></div>
      </Card>}
      right={<Card title="선택한 환자 상세 정보">
        <Slot what="환자 정보 · 원본 이미지 · 판독 결과" h={300} />
        <div className="rowb"><Btn>판독 화면</Btn><Btn kind="fill">판독 수정</Btn></div>
      </Card>}
    />
  );
}

function UploadBody() {
  const [pct] = useState(66);
  return (
    <Split
      left={<Card title="파일 업로드" right={<Btn>업로드 가이드</Btn>}>
        <div className="grid2">
          <Drop title="낱장 파일 올리기" note="파일을 하나씩 업로드합니다."
                accept=".svs, .tiff, .ndpi, .dcm" max="4GB" />
          <Drop title="ZIP 파일 올리기" note="여러 장을 한 번에 업로드합니다."
                accept=".zip" max="20GB" />
        </div>
        <Bar value={pct} label="업로드 진행률 — 2 / 3 완료" />
        {/* ⚠ 이 크기를 받는 쪽이 맞춰져 있어야 한다.
            nginx client_max_body_size 기본값은 1MB 다 */}
        <p className="hint">낱장 4GB · ZIP 20GB 까지 받습니다.</p>
      </Card>}
      right={<Card title="환자 정보">
        <Slot what="환자 · 요청 검사 · 주치의" h={260} />
      </Card>}
    />
  );
}

function ReadBody() {
  const [zoom, setZoom] = useState(40);
  const [open, setOpen] = useState(false);

  return (
    <>
      <Card pad={false}>
        <Viewer
          tabs={<><button className="pill on">전체 보기</button>
                  <button className="pill">조직 분할</button>
                  <button className="pill">세포 검출</button>
                  <button className="pill">분할 오버레이</button></>}
          tools={["⌖", "＋", "－", "✥", "✎", "⛶"].map((t, i) =>
            <button key={i} className="vtool">{t}</button>)}
          leftPanel={<AiPanel r={null} busy />}
          rightPanel={<>
            <Slot what="악성 / 양성 · 조직학적 진단 · 등급" h={200} />
            <Save hint="저장하면 유방외과로 소견이 전송됩니다." />
          </>}
          rightName="의사 소견">
          <div className="vart" />
          <Zoom value={zoom} onChange={setZoom} />
        </Viewer>
      </Card>

      <div className="rowb">
        <Btn onClick={() => setOpen(true)}>병변 등록</Btn>
      </div>

      <Modal open={open} title="병변 등록"
             sub="영역을 지정하고 소견을 답니다."
             onClose={() => setOpen(false)}
             foot={<><Btn onClick={() => setOpen(false)}>취소</Btn>
                     <Btn kind="fill" onClick={() => setOpen(false)}>등록</Btn></>}>
        <Slot what="병변 입력 서식" h={180} />
      </Modal>
    </>
  );
}
