import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useApi } from "../lib/useApi";
import { Body, Head } from "../lib/Screen";

/* 07 · 안내문
 *
 * 잠긴 리포트는 **본문이 아예 오지 않는다**(narrative_text = null).
 * 화면에서 가리는 것이 아니라 서버가 안 보낸다 — 여기서 실수해도
 * 새어 나갈 것이 없다.
 */
export default function Report() {
  const { id } = useParams();
  const { loading, data, error, reload } = useApi(() => api.report(id), [id]);
  const locked = data?.lock_status === "locked";

  return (
    <>
      {/* 알림에서 바로 들어오면 되짚을 이력이 없다. 그때는 목록으로 올린다 */}
      <Head title={data?.title || "검사 안내"} up="/results" />
      <Body loading={loading} error={error} onRetry={reload}>
        {locked ? (
          <div className="card">
            <span className="k">열람 전</span>
            <span className="s">{data.locked_hint}</span>
          </div>
        ) : (
          <>
            <article className="letter">
              <h3>검사 결과를 안내드립니다</h3>
              <p className="by">
                {fmtDate(data.issued_at)} · 영상의학과 ·
                {" "}판독의 {data.issued_by_name}
              </p>
              {data.narrative_text.split("\n\n").map((para, i) => (
                <p key={i}>{para}</p>
              ))}
              <div className="stamp">
                ✓ {fmtDay(data.explained_at)} 대면 설명 후 열람 ·
                {" "}판독의 {data.explained_by_name}
              </div>
            </article>

            {data.notes?.length > 0 && (
              <p className="note">
                {data.notes.map((n) => n.text).join(" ")}
              </p>
            )}

            <div className="row2">
              <button className="btn soft" disabled={!data.pdf_available}>
                PDF 저장
              </button>
              <Link className="btn ghost" to="/chat">모르는 말 묻기</Link>
            </div>
          </>
        )}
        <p className="note">{data?.disclaimer}</p>
      </Body>
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
