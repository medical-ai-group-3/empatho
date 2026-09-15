import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ERR, api } from "../../api";
import { Body } from "../../lib/Body";
import { Btn, Card, Page } from "../../lib/Page";
import { Chip, Fold, Queue, Split } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { go } from "../../nav";

/* 병리 1 · 검체 접수 대기  (명세 p.21)
 *
 * ── 이 화면은 «접수»지 «바인딩»이 아니다 ──────────────────────
 * 바인딩(검체를 병변에 잇는 일)은 간호과와 유방외과가 한다. 여기는 그것이
 * 끝난 검체를 병리가 **집어서 접수하는** 자리다. 그래서 제목이 「검체 접수
 * 대기」다.
 *
 * ── 선착순 큐 ────────────────────────────────────────────────
 * 병리과 전체가 같은 목록을 본다. 누가 집으면 다른 사람 화면에서 사라진다.
 * 그래서 셋을 지킨다.
 *
 *   · **순번은 표시 전용이다.** 끌어서 못 옮긴다 — 각자 순서를 바꾸면
 *     같은 화면이 아니게 된다. 대신 검색으로 건너뛴다
 *   · **폴링으로 갱신한다.** 남이 집어 간 것이 내 화면에 남아 있으면
 *     헛걸음한다
 *   · **동시에 집으면 하나만 성공한다.** 진 쪽은 409 를 받고, 그때
 *     「다른 선생님이 이미 맡았습니다」로 알린다
 *
 * ── 반려가 없다 ──────────────────────────────────────────────
 * 검체가 이상한지를 이 시스템이 판단할 수 없다. 물건은 이미 와 있고,
 * 문제가 있으면 사람이 전화로 푼다.
 */

const POLL_MS = 7000;   // 명세 「5~10초 폴링」

export default function Specimens() {
  const { loading, data, error, reload } = useApi(() => api.queue());

  /* 남이 집어 간 것을 내 화면에 남겨 두지 않는다 */
  useEffect(() => {
    const t = setInterval(reload, POLL_MS);
    return () => clearInterval(t);
  }, [reload]);

  return (
    <Page crumb={["병리과", "검체 관리"]} title="검체 접수 대기"
          badge={data ? `${data.items.length}건` : undefined}
          sub="간호과와 유방외과에서 바인딩을 마친 검체가 채취 순서대로 도착합니다. 확인 후 집어서 접수합니다.">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <Inner d={data} reload={reload} />}
      </Body>
    </Page>
  );
}

function Inner({ d, reload }) {
  const nav = useNavigate();
  const [pick, setPick] = useState(d.items[0]?.id ?? null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  /* 순서를 안 바꾸고 건너뛰어 찾는다 */
  const shown = useMemo(() => {
    const key = q.trim().toLowerCase();
    return d.items
      .map((x, i) => ({ ...x, no: i + 1 }))
      .filter((x) => !key ||
        [x.name, x.specimen_no, x.patient_no].some((v) => v.toLowerCase().includes(key)));
  }, [d.items, q]);

  /* 큐 맨 앞을 집는다. 고른 행이 아니라 **맨 앞**이다 — 선착순이라
     골라 집으면 큐가 아니게 된다 */
  const head = d.items[0];

  async function take() {
    if (!head) return;
    setBusy(true); setMsg(null);
    try {
      await api.assign(head.id);
      nav(go.upload(head.id));
    } catch (e) {
      if (e.code === ERR.ALREADY_ASSIGNED) {
        setMsg("다른 선생님이 이미 맡았습니다.");
        reload();
      } else {
        setMsg(e.detail || e.message);
      }
    } finally { setBusy(false); }
  }

  return (
    <Split
      left={
        <Card title="검체 접수 대기 리스트"
              right={<span className="src">채취 순서</span>} pad={false}>
          <Queue
            items={shown.map((x) => ({
              id: x.id, no: x.no,
              title: `${x.name}  ${x.patient_no} · ${x.sex} ${x.age}세`,
              sub: `${x.specimen_no} · ${x.site} · ${x.kind}`,
            }))}
            value={pick} onPick={setPick} q={q} onSearch={setQ}
            foot={
              <>
                {/* **누구를 집는지 미리 말한다.** 검색으로 걸러 놓으면
                    화면 맨 위와 큐 맨 앞이 달라서, 안 적으면 엉뚱한
                    사람을 집은 것처럼 보인다 */}
                <span>{msg ?? (head
                  ? `다음은 ${head.name} · ${head.specimen_no}`
                  : "대기 중인 검체가 없습니다")}</span>
                <Btn kind="fill" disabled={busy || d.items.length === 0}
                     onClick={take}>다음 환자</Btn>
              </>
            }
          />
        </Card>
      }
      right={pick ? <Detail id={pick} /> : null}
      empty="왼쪽에서 검체를 고르세요"
    />
  );
}

/* 고른 검체 — 아직 집은 것이 아니다. 보기만 한다 */
function Detail({ id }) {
  /* ⚠ 고른 것이 없으면 **부르지 않는다.** 전에는 id 가 null 인 채로
     /specimens/null 을 불러 404 를 받았다. 큐가 비었을 때 오류 카드가
     뜨던 것이 이것이다. */
  const { loading, data, error, reload } =
    useApi(() => (id ? api.specimen(id) : Promise.resolve(null)), [id]);
  if (!id) return null;
  return (
    <Card title="지금 확인할 환자 정보">
      <Body loading={loading} error={error} onRetry={reload}>
        {data && <DetailBody d={data} />}
      </Body>
    </Card>
  );
}

function DetailBody({ d }) {
  const p = d.patient;
  const [shot, setShot] = useState(0);

  return (
    <>
      <div className="ph">
        <span className="ava" aria-hidden="true">{p.name[0]}</span>
        <div className="ph-tx">
          <b>{p.name}</b>
          <span>{p.patient_no} · {p.sex} / {p.age}세 · {p.birth_date}</span>
        </div>
        {/* 「바인딩 완료」는 배지로 줄였다 — 큰 상자로 두면 정작 중요한
            검체 정보가 밀린다 */}
        {d.bound && <Chip tone="dot">바인딩 완료</Chip>}
      </div>

      <dl className="kv wide">
        <div><dt>검체번호</dt><dd><b>{d.specimen.no}</b></dd></div>
        <div><dt>검체 종류</dt><dd>{d.specimen.kind}</dd></div>
        <div><dt>채취 방식</dt><dd>{d.specimen.method}</dd></div>
        <div><dt>채취일시</dt><dd>{d.specimen.collected_at}</dd></div>
        <div><dt>요청 부위</dt><dd>{d.specimen.site}</dd></div>
        <div><dt>병변</dt><dd>{d.specimen.lesion}</dd></div>
        <div><dt>요청 부서</dt><dd>{d.request.dept} · {d.request.doctor}</dd></div>
      </dl>

      {d.clinical_note && (
        <>
          <h3 className="seck">임상 정보 ({d.request.dept})</h3>
          <p className="note">{d.clinical_note}</p>
        </>
      )}

      {d.imaging && (
        <>
          <h3 className="seck">영상의학과 판독 요약</h3>
          <dl className="kv wide">
            <div><dt>검사 종류</dt><dd>{d.imaging.modality}</dd></div>
            <div><dt>판독일</dt><dd>{d.imaging.read_at}</dd></div>
            <div><dt>소견</dt><dd>{d.imaging.finding}</dd></div>
            <div><dt>BI-RADS</dt><dd><b>{d.imaging.birads}</b></dd></div>
          </dl>
        </>
      )}

      {/* 채취 때 쓴 영상. 어느 자리를 찔렀는지 눈으로 봐야 검체가 맞는지
          안다 — specimen → lesion → study 로 타고 온다 */}
      {d.guide_images?.length > 0 && (
        <>
          <h3 className="seck">유도 영상</h3>
          <div className="thumbs">
            {d.guide_images.map((g, i) => (
              <button className={`thumb ${shot === i ? "on" : ""}`} key={g.label}
                      onClick={() => setShot(i)}>
                <i aria-hidden="true" />{g.label}
              </button>
            ))}
          </div>
        </>
      )}

      {/* 같은 환자의 다른 검체 — 한 번에 여러 자리를 뗀 경우가 있다 */}
      {d.siblings?.length > 0 && (
        <Fold title={`이 환자의 다른 검체 ${d.siblings.length}`} open={false}>
          <dl className="kv wide">
            {d.siblings.map((s) => (
              <div key={s.no}>
                <dt>{s.no}</dt><dd>{s.site} · {s.kind} · {s.state}</dd>
              </div>
            ))}
          </dl>
        </Fold>
      )}
    </>
  );
}
