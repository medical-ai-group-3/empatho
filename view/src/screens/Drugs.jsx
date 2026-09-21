import { useState } from "react";
import { api } from "../api";
import Tilly from "../lib/Tilly";
import { Body, Head } from "../lib/Screen";
import Icon from "../lib/Icon";

/* 13-2 · 약 정보 찾기
 *
 * 식약처 「의약품개요정보(e약은요)」를 그대로 옮겨 주는 **사전**이다.
 * 서버(Django)가 공공데이터를 받아 칸 이름만 우리 것으로 바꿔 준다.
 *
 * ── 복약 관리(Meds)와 무엇이 다른가 ─────────────────────────
 *
 * ⚠ **처방 설명을 여기서 채우지 않는다.** Meds 의 purpose · how · watch
 *   는 처방한 사람이 이 환자를 보고 쓴 문장이고, 여기 오는 것은 그 약의
 *   일반 허가사항이다. 여기 문장을 저기로 옮기는 순간 앱이 **의학적
 *   조언**을 하게 된다 — Meds 의 머리말이 막으려던 그것이다.
 *
 *   그래서 두 화면을 잇는 것은 링크 하나뿐이다. 약 이름을 자동으로
 *   넣어 주지도 않는다 — 처방받은 약을 눌렀더니 일반 설명이 뜨면
 *   그게 내 약 설명인 줄 안다.
 *
 * ── 어디서 온 글인지 화면이 말한다 ──────────────────────────
 *
 * ⚠ source 와 disclaimer 를 **반드시 적는다.** 서버가 매번 실어 보내는
 *   이유가 그것이다(문구가 바뀌어도 앱 배포를 안 기다린다). 빼면
 *   환자에게는 병원이 해 준 설명으로 읽힌다.
 *
 * ── 누를 때만 찾는다 ────────────────────────────────────────
 *
 * 글자를 칠 때마다 부르지 않는다. 바깥 공공데이터라 **일일 호출 한도**가
 * 있고, 한 글자마다 한 번씩 부르면 「타이레놀」 한 번 찾는 데 네 번을
 * 쓴다. 한도를 넘기면 그날 하루 이 화면이 통째로 죽는다.
 *
 * 그리고 결과가 딱 맞는 이름일 때만 나온다 — 부분 일치라 한두 글자로는
 * 쓸모없는 목록이 길게 나올 뿐이다.
 */

/* 한 번에 받는 수. 더 있으면 「더 보기」로 이어 붙인다 — 페이지 번호를
   눌러 넘기게 하면 뒤로 돌아올 때마다 자리를 잃는다 */
const PAGE_SIZE = 10;

export default function Drugs() {
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState(null);   // 실제로 찾은 말. 입력칸과 다르다
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const [more, setMore] = useState(false);    // 「더 보기」가 도는 중

  async function run(term, page = 1) {
    const name = term.trim();
    if (!name) return;
    setAsked(name);
    if (page === 1) setState({ loading: true, data: null, error: null });
    else setMore(true);
    try {
      const d = await api.drugs({ q: name, page, page_size: PAGE_SIZE });
      setState((s) => ({
        loading: false,
        error: null,
        /* 이어 붙인다. 갈아 끼우면 「더 보기」를 누른 순간 보고 있던
           약이 목록에서 사라진다 */
        data: page === 1 ? d
          : { ...d, items: [...(s.data?.items ?? []), ...(d.items ?? [])] },
      }));
    } catch (e) {
      /* 더 받다가 실패한 것은 지금까지 받은 목록을 지울 이유가 안 된다 */
      if (page === 1) setState({ loading: false, data: null, error: e });
      else setState((s) => ({ ...s, error: e }));
    } finally {
      setMore(false);
    }
  }

  const d = state.data;
  const shown = d?.items ?? [];
  const hasMore = d ? shown.length < (d.count ?? 0) : false;

  return (
    <>
      <Head title="약 정보" />
      {/* Body 의 loading · error 를 첫 검색에만 쓴다. 검색칸까지 사라지면
          「다시 찾기」를 하려고 뒤로 갔다 와야 한다 */}
      <Body loading={false} error={null}>
        <form className="search" onSubmit={(e) => { e.preventDefault(); run(q); }}>
          <Icon name="search" />
          <input value={q} placeholder="약 이름 (예: 타이레놀)"
                 aria-label="약 이름"
                 onChange={(e) => setQ(e.target.value)} />
          <button className="btn soft" type="submit" disabled={state.loading || !q.trim()}>
            {state.loading ? "찾는 중…" : "찾기"}
          </button>
        </form>

        <p className="note">
          처방받으신 약의 복용법은 <b>처방전과 담당 의료진의 안내</b>를 따라 주세요.
          이 화면은 약의 일반 정보를 찾아보는 곳입니다.
        </p>

        {state.error && (
          <div className="card flag">
            <span className="k">{state.error.code || "오류"}</span>
            <span className="s">
              {state.error.detail || state.error.message || "약 정보를 불러오지 못했습니다."}
            </span>
            <button className="btn ghost" onClick={() => run(asked)}>다시 시도</button>
          </div>
        )}

        {state.loading && (
          <div className="empty">
            <Tilly mood="loading" size="loading" alt="" />
            <p>찾는 중…</p>
          </div>
        )}

        {!state.loading && d && shown.length === 0 && (
          <div className="empty">
            <Tilly mood="rest" size="md" alt="" />
            <p>「{asked}」로 찾은 약이 없습니다.</p>
            <p className="s">제품 이름을 정확히 적어 보세요. 성분 이름으로는 찾지 못합니다.</p>
          </div>
        )}

        {shown.length > 0 && (
          <>
            <h3 className="sec">「{asked}」 검색 결과 {d.count}건</h3>
            {shown.map((it) => <Drug key={it.item_seq} it={it} />)}

            {hasMore && (
              <button className="btn ghost" disabled={more}
                      onClick={() => run(asked, (d.page ?? 1) + 1)}>
                {more ? "불러오는 중…" : `더 보기 (${shown.length} / ${d.count})`}
              </button>
            )}

            {/* 어디서 온 글인지. 목록 끝에 한 번만 적는다 — 약마다 붙이면
                읽는 자리를 밀어내면서 정작 눈에는 안 들어온다 */}
            <p className="note">
              {d.source}
              <br />
              {d.disclaimer}
            </p>
          </>
        )}
      </Body>
    </>
  );
}

/* 약 한 건. 이름과 제조사만 펴 두고 나머지는 접는다 — 한 건의 본문이
   화면 몇 개 분량이라, 펴 두면 두 번째 결과까지 닿지를 못한다 */
function Drug({ it }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="card drug-card">
      <div className="drug-h">
        <span className="tx">
          <b>{it.name}</b>
          <span>{it.maker}</span>
        </span>
        {/* 알약 사진. 없는 약이 많아서 있을 때만 자리를 낸다 */}
        {it.image && <img className="drug-pic" src={it.image} alt="" loading="lazy" />}
      </div>

      {/* 경고는 접지 않는다. 「이 약을 먹지 마세요」가 접힌 채로 있으면
          접힌 것만큼 안 읽힌다 */}
      {it.warning && (
        <div className="rx-period">
          <b>경고</b>
          <Paras text={it.warning} />
        </div>
      )}

      <button className="drug-more" aria-expanded={open}
              onClick={() => setOpen(!open)}>
        <Icon name={open ? "chevronDown" : "chevronRight"} />
        {open ? "접기" : "자세히 보기"}
      </button>

      {open && (
        <dl className="drug-info">
          <Field label="어떤 효능이 있나요" text={it.efficacy} />
          <Field label="어떻게 사용하나요" text={it.how_to_use} />
          <Field label="사용 전 알아야 할 것" text={it.caution} />
          <Field label="함께 쓰면 안 되는 약·음식" text={it.interaction} />
          <Field label="이런 증상이 나타날 수 있어요" text={it.side_effect} watch />
          <Field label="어떻게 보관하나요" text={it.storage} />
          {it.updated_at && (
            <><dt>자료 기준</dt><dd className="s">{it.updated_at}</dd></>
          )}
        </dl>
      )}
    </div>
  );
}

function Field({ label, text, watch }) {
  if (!text) return null;
  return (
    <>
      <dt>{label}</dt>
      <dd className={watch ? "watch" : undefined}><Paras text={text} /></dd>
    </>
  );
}

/* 원천이 문단을 줄바꿈으로 나눠 준다. 통째로 넣으면 한 덩어리가 되어
   읽을 수가 없다 — CSS 의 white-space 대신 문단으로 쪼갠다. 그래야
   문단 사이 간격을 다른 글과 똑같이 줄 수 있다 */
function Paras({ text }) {
  const lines = String(text ?? "").split("\n").filter(Boolean);
  return lines.map((line, i) => <p key={i}>{line}</p>);
}
