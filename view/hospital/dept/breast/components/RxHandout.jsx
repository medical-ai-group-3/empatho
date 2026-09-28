import { useEffect, useState } from "react";
import { breast as api } from "../../../api";
import { ROUTE, label } from "../../../codes";
import Dialog from "../../../lib/Dialog";
import * as H from "../../home";
import { FREQ, freqOf, norm, sorted } from "../rx";

/* 복약 안내문 — 저장된 처방 한 건을 환자에게 건넬 종이로.
 *
 * 약마다 두 덩어리다.
 *   ① 처방 내용 · 처방한 사람의 설명(purpose · how · watch)
 *   ② 식약처 참고 정보(e약은요) — 따로 테를 두르고 출처 · 고지를 붙인다
 *
 * ⚠ **②를 ①에 섞지 않는다.** core/api/drugs.py 머리말 — 약전 문장을 처방
 *   설명칸에 끼워 넣는 순간 우리가 하는 의학적 조언이 된다. 종이 위에서도
 *   「이건 식약처 자료이고 내 처방 설명이 아니다」가 보여야 한다.
 * ⚠ e약은요는 **이름이 똑같은 품목만** 싣는다. 비슷한 이름으로 짐작해 붙이면
 *   남의 약 설명이 환자 손에 들린다 — 없으면 「없는 약」이라고 쓴다.
 * ⚠ 인쇄는 브라우저의 window.print() 다. 팝업(Dialog)은 body 에 포털로 붙어서
 *   @media print 가 나머지 화면을 걷어 내기 쉽다(breast.css 「복약 안내문」). */

/* e약은요 칸 → 종이의 제목. 경고와 주의는 한 칸으로 */
const REF = [
  ["efficacy", "효능"],
  ["how_to_use", "사용법"],
  [["warning", "caution"], "경고 · 주의"],
  ["interaction", "함께 쓰면 안 되는 약 · 음식"],
  ["side_effect", "이상반응"],
  ["storage", "보관법"],
];

const baseName = (name) => String(name ?? "").replace(/\([^()]*\)\s*$/, "").trim();

/* 이름이 같은 품목. 끝 괄호(성분)는 있어도 없어도 같은 약으로 본다 */
function sameDrug(item, name) {
  const a = norm(item?.name);
  return Boolean(a) && (a === norm(name) || norm(baseName(item.name)) === norm(baseName(name)));
}

function timesLine(times) {
  if (!Array.isArray(times) || !times.length) return null;
  const f = freqOf(times);
  const head = f ? FREQ.find((x) => x.k === f).label : `1일 ${times.length}회`;
  return `${head} · ${sorted(times).join(", ")}`;
}

/* 약마다 e약은요를 한 번씩 찾는다. 결과: index → {state, item, source, disclaimer} */
function useReference(drugs) {
  const [refs, setRefs] = useState({});
  const names = drugs.map((d) => d.name ?? "").join("\u0001");
  useEffect(() => {
    let live = true;
    names.split("\u0001").forEach((name, i) => {
      const q = baseName(name);
      if (!q) { setRefs((r) => ({ ...r, [i]: { state: "none" } })); return; }
      api.drugs(q)
        .then((res) => {
          if (!live) return;
          const item = (res?.items ?? []).find((it) => sameDrug(it, name)) ?? null;
          setRefs((r) => ({ ...r, [i]: {
            state: item ? "ok" : "none", item,
            source: res?.source, disclaimer: res?.disclaimer,
          } }));
        })
        .catch((e) => {
          if (live) setRefs((r) => ({ ...r, [i]: { state: e.status === 503 ? "off" : "fail" } }));
        });
    });
    return () => { live = false; };
  }, [names]);
  return refs;
}

function Reference({ data: r }) {
  const body = !r ? <p className="rxh-muted">식약처 자료를 찾는 중…</p>
    : r.state === "off" ? <p className="rxh-muted">지금은 식약처 자료를 불러올 수 없습니다.</p>
    : r.state === "fail" ? <p className="rxh-muted">식약처 자료를 불러오지 못했습니다.</p>
    : r.state === "none" ? <p className="rxh-muted">식약처 자료에 없는 약입니다.</p>
    : (
      <dl className="rxh-ref-dl">
        {REF.map(([k, title]) => {
          const text = (Array.isArray(k) ? k : [k]).map((f) => r.item[f]).filter(Boolean).join("\n");
          return text ? <div key={title}><dt>{title}</dt><dd>{text}</dd></div> : null;
        })}
      </dl>
    );
  return (
    <section className="rxh-ref" aria-label="식약처 참고 정보">
      <h4>식약처 참고 정보 (e약은요)</h4>
      {r?.state === "ok" && r.item.name && <p className="rxh-ref-item">{r.item.name}{r.item.maker ? ` · ${r.item.maker}` : ""}</p>}
      {body}
      {r?.state === "ok" && (r.source || r.disclaimer) && (
        <p className="rxh-src">
          {r.source && <>출처: {r.source}. </>}
          {r.disclaimer}
        </p>
      )}
    </section>
  );
}

export default function RxHandout({ patient, rx, onClose }) {
  const drugs = rx?.content?.drugs ?? [];
  const refs = useReference(drugs);
  const date = String(rx?.prescribed_at ?? rx?.created_at ?? "").slice(0, 10) || "—";
  const busy = drugs.some((_, i) => !refs[i]);

  return (
    <Dialog wide title="복약 안내문" sub="인쇄하면 이 안내문만 A4 에 나옵니다"
            onClose={onClose}
            foot={(
              <>
                <button type="button" className="btn ghost" onClick={onClose}>닫기</button>
                <button type="button" className="btn" onClick={() => window.print()}>
                  {busy ? "인쇄 (식약처 자료 불러오는 중)" : "인쇄"}
                </button>
              </>
            )}>
      <article className="rxh rxh-print">
        <header className="rxh-head">
          <h2>복약 안내문</h2>
          <dl className="rxh-meta">
            <div><dt>환자</dt><dd>{patient?.name ?? "—"}{H.noOf(patient ?? {}) ? ` (${H.noOf(patient)})` : ""}</dd></div>
            <div><dt>처방일</dt><dd>{date}</dd></div>
            {rx?.prescriber && <div><dt>처방의</dt><dd>{rx.prescriber}</dd></div>}
          </dl>
        </header>

        {drugs.map((d, i) => {
          const route = [label(ROUTE, d.route), d.form].filter(Boolean).join(" · ");
          return (
            <section className="rxh-drug" key={i}>
              <h3>{i + 1}. {d.name}</h3>
              <dl className="rxh-facts">
                {d.ingredient && <div><dt>성분</dt><dd>{d.ingredient}</dd></div>}
                {route && <div><dt>투여 경로 · 제형</dt><dd>{route}</dd></div>}
                {d.dose && <div><dt>1회 용량</dt><dd>{d.dose}</dd></div>}
                <div><dt>복용 시간</dt><dd>{timesLine(d.times) ?? (d.times ? String(d.times) : "—")}</dd></div>
                {d.days && <div><dt>기간</dt><dd>{d.days}일</dd></div>}
              </dl>
              {/* 처방한 사람의 설명 — 이 칸만이 「내 처방 설명」이다 */}
              {d.purpose && <><h4>처방 목적</h4><p className="rxh-text">{d.purpose}</p></>}
              {d.how && <><h4>복용 안내</h4><p className="rxh-text">{d.how}</p></>}
              {d.watch && <><h4>주의사항</h4><p className="rxh-text rxh-watch">{d.watch}</p></>}
              <Reference data={refs[i]} />
            </section>
          );
        })}
        {!drugs.length && <p className="rxh-muted">이 처방에는 약이 없습니다.</p>}

        <footer className="rxh-foot">
          궁금한 점은 처방한 의료진에게 물어 주세요. 위 처방 설명과 식약처 참고 정보가 다르면 처방 설명을 따르세요.
        </footer>
      </article>
    </Dialog>
  );
}
