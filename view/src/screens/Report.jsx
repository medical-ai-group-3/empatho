import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";

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
      <article className="letter">
        <h3>검사 결과를 안내드립니다</h3>
        {/* 판독의와 주치의는 **다른 사람**이다. 사진을 읽은 사람과
            진료를 보는 사람이라, 이름만 나란히 두면 누가 누군지
            모른다. 줄을 나누고 각각에 이름표를 붙인다 */}
        <p className="by">
          {fmtDate(r.issued_at)} · 영상의학과 ·
          {" "}판독의 {r.issued_by_name}
          {r.attending_name && (
            <>
              <br />
              담당 주치의 {r.attending_name}
              {r.attending_dept ? ` · ${r.attending_dept}` : ""}
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
            ✓ {fmtDay(r.explained_at)} 대면 설명 후 열람 ·
            {" "}판독의 {r.explained_by_name}
          </div>
        )}
      </article>

      {r.notes?.length > 0 && (
        <p className="note">{r.notes.map((n) => n.text).join(" ")}</p>
      )}

      <div className="row2">
        <button className="btn soft" disabled={!r.pdf_available}>
          PDF 저장
        </button>
        <Link className="btn ghost" to="/chat">모르는 말 묻기</Link>
      </div>

      <p className="note">{r.disclaimer}</p>
    </>
  );
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}.${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}
function fmtDay(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${p2(d.getMonth() + 1)}.${p2(d.getDate())}`;
}
const p2 = (n) => String(n).padStart(2, "0");
