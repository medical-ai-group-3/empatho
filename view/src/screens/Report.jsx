import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { HOSPITAL } from "../brand";
import { deptSuffix } from "../lib/dept";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";
import { fmtDay } from "../lib/when";

/* 07 · 안내문
 *
 * 잠긴 리포트는 **본문이 아예 오지 않는다**(narrative_text = null).
 * 화면에서 가리는 것이 아니라 서버가 안 보낸다 — 여기서 실수해도
 * 새어 나갈 것이 없다.
 *
 * ── 왜 본문을 딴 부품으로 뺐나 ────────────────────────────────
 * 전에는 <Body> 안에 자료를 바로 읽어 썼는데, 그러면 **첫 그림에서
 * 터진다.** JSX 의 자식은 Body 가 「불러오는 중」을 고르기 **전에** 이미
 * 만들어지기 때문이다. 그 순간 data 는 아직 null 이라 data.issued_at
 * 에서 멎었고, React 가 트리를 통째로 내려서 머리말과 뒤로가기까지
 * 같이 사라졌다 — 하얀 화면.
 *
 * 그래서 {data && <Letter />} 로 막는다. 자료가 온 뒤에만 이 부품이
 * 만들어지므로 안에서는 r 이 있다고 믿고 써도 된다. 다른 화면(Me)도
 * 같은 모양이다.
 */
export default function Report() {
  const { id } = useParams();
  const { loading, data, error, reload } = useApi(() => api.report(id), [id]);

  return (
    <>
      {/* 알림에서 바로 들어오면 되짚을 이력이 없다. 그때는 목록으로 올린다 */}
      <Head title={data?.title || "검사 안내"} up="/results" />
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Letter r={data} />}
      </Body>
    </>
  );
}

function Letter({ r }) {
  if (r.lock_status === "locked") {
    return (
      <>
        <div className="card">
          <span className="k">열람 전</span>
          <span className="s">{r.locked_hint}</span>
        </div>
        <p className="note">{r.disclaimer}</p>
      </>
    );
  }

  /* 잠기지 않았는데 본문이 안 온 경우. 서버가 그럴 리 없지만, 그때
     화면이 죽는 것보다는 한 줄이라도 남는 편이 낫다 */
  const paras = (r.narrative_text || "").split("\n\n").filter(Boolean);

  return (
    <>
      {/* 인쇄에만 나오는 머리. 화면에서는 위에 머리말(.top)이 있지만
          인쇄에서는 그것을 숨기므로, 그냥 두면 종이에 «어디서 온
          무엇인지»가 하나도 없이 본문만 남는다 */}
      <p className="printhead" aria-hidden="true">{HOSPITAL} · 검사 안내문</p>

      <article className="letter">
        <h3>검사 결과를 안내드립니다</h3>
        {/* 판독의와 주치의는 **다른 사람**이다. 사진을 읽은 사람과
            진료를 보는 사람이라, 이름만 나란히 두면 누가 누군지
            모른다. 줄을 나누고 각각에 이름표를 붙인다 */}
        <p className="by">
          {fmtDay(r.issued_at)} · 영상의학과 ·
          {" "}판독의 {r.issued_by_name}
          {r.primary_staff_name && (
            <>
              <br />
              담당 주치의 {r.primary_staff_name}
              {deptSuffix(r.primary_staff_dept)}
            </>
          )}
        </p>

        {paras.length > 0 ? (
          paras.map((para, i) => <p key={i}>{para}</p>)
        ) : (
          <p>안내문 본문을 불러오지 못했습니다. 접수처에 문의해 주세요.</p>
        )}

        {/* 대면 설명 기록이 있을 때만 찍는다. 없는데 도장을 찍으면
            «설명을 들었다»고 잘못 말하는 것이 된다 */}
        {r.explained_at && (
          <div className="stamp">
            ✓ {shortDay(r.explained_at)} 대면 설명 후 열람 ·
            {" "}판독의 {r.explained_by_name}
          </div>
        )}
      </article>

      {r.notes?.length > 0 && (
        <p className="note">{r.notes.map((n) => n.text).join(" ")}</p>
      )}

      <div className="row2">
        {/* 브라우저의 인쇄를 부른다. 인쇄 창에서 「PDF 로 저장」을 고르면
            파일이 남고, 종이로 뽑을 수도 있다 — 접수처에 들고 갈 사람도
            있다.

            서버에서 PDF 를 받아 오는 길(GET …/pdf)은 아직 없다. 생기면
            여기만 그쪽으로 바꾸면 된다. 그때까지 단추가 아무 일도 안 하는
            것보다는 이 편이 낫다.

            @media print 가 앱 껍데기를 걷어 내고 안내문만 남긴다
            (index.css 맨 아래). */}
        <button className="btn soft" disabled={!r.pdf_available}
                onClick={() => window.print()}>
          PDF 저장
        </button>
        <Link className="btn ghost" to="/chat">모르는 말 묻기</Link>
      </div>

      <p className="note">{r.disclaimer}</p>
    </>
  );
}

/* 도장에만 쓰는 짧은 날짜 — 09.15. 연도가 빠진다.
 *
 * ⚠ 이 화면은 lib/when 의 fmtDay(2026.09.15)도 같이 쓴다. 이름이
 *   비슷해서 헷갈리기 쉬운데 **다른 것**이다. 전에는 이 짧은 쪽이
 *   fmtDay 라는 이름을 갖고 있어서, 공용 fmtDay 를 이 파일에 들여오는
 *   순간 조용히 가려졌다 — 어느 쪽이 불린 건지 모른 채 연도가 사라진다.
 *   그래서 이름을 갈랐다. 연도까지 나오는 것은 lib/when 에서 가져다 쓴다. */
function shortDay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const p2 = (n) => String(n).padStart(2, "0");
  return `${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}
