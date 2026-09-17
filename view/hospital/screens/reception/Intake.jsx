import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { reception as api } from "../../api";
import { go } from "../../nav";
import { Page, Card, Btn } from "../../lib/Page";
import { Body } from "../../lib/Body";
import Dialog from "../../lib/Dialog";
import { Chip, Table, Warn } from "../../lib/Parts";
import { useApi } from "../../lib/useApi";
import { can } from "../../perm";
import Calendar from "./Calendar";
import Register from "./Register";

/* 원무 1장 — 접수 · 방문 환자 모니터링
 * ════════════════════════════════════════════════════════════════
 *
 * **접수는 검색으로 시작한다.** 대부분은 앱으로 이미 가입하고 오기
 * 때문이다. 등록([+])은 앱을 못 쓰는 환자를 위한 예외 경로다.
 *
 *   칸 셋 중 하나 → [검색] → (여럿이면 팝업에서 고름) → 칸이 채워짐
 *                → [접수하기]
 *
 * ⚠ **한 명이 나와도 자동으로 접수하지 않는다.** 칸만 채워 주고 사람이
 *   확인한 뒤 누른다 — 오타로 엉뚱한 사람이 접수되는 것을 막는다.
 *
 * ⚠ **환자번호는 검색 칸에 없다.** 환자가 모르고 온다. 대신 결과와
 *   고른 사람 정보에는 보여준다.
 *
 * 서버는 q 하나만 받는다 (views/reception.py 의 PatientViewSet). 이름 ·
 * 전화 · 생년월일을 OR 로 한꺼번에 보므로, 채운 칸 중 하나를 골라 보낸다.
 * 동명이인은 팝업에서 사람이 고르니 필드별 검색이 필요 없다.
 *
 * 접수가 하는 일은 exam_order 를 requested 로 만들고 visited_at 을 찍는
 * 것뿐이다. 검사 종류(modality)는 정하지 않는다 — 의학적 판단이라
 * 유방외과 몫이고, DB CHECK 도 그렇게 열려 있다.
 */

const EMPTY = { name: "", phone: "", birth_date: "" };

export default function Intake() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY);
  /* 고른 환자. 칸을 손으로 고치면 비운다 — 칸과 번호가 어긋난 채로
     접수되면 엉뚱한 사람이 큐에 오른다 */
  const [picked, setPicked] = useState(null);
  const [choices, setChoices] = useState(null);   // 팝업. null = 안 뜸
  const [empty, setEmpty] = useState(false);      // "없습니다" 를 띄울 때
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);
  const [regOpen, setRegOpen] = useState(false);
  /* 등록 팝업이 무엇을 하고 닫혔나 — "created" 면 새로 만든 것,
     "exists" 면 이미 있던 사람을 찾아 온 것. 안내 문구가 갈린다 */
  const [regDone, setRegDone] = useState(null);

  const today = useApi(() => api.todayStatus(), []);
  useEffect(() => {
    const t = setInterval(today.reload, 10_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function edit(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    setPicked(null);          // 손으로 고치면 고른 사람과 어긋난다
    setEmpty(false);
    setDone(null);
    setRegDone(null);
  }

  /* 고른 사람으로 칸을 채운다 — 생년월일까지.
     검색 결과에 birth_date 가 온다 (PatientListSerializer). 개인정보가 없는
     환자는 null 이라 그때만 비워 둔다 */
  function fill(patient) {
    setForm({
      name: patient.name ?? "",
      phone: patient.phone ?? "",
      birth_date: patient.birth_date ?? "",
    });
    setPicked(patient);
    setChoices(null);
    setEmpty(false);
  }

  /* 등록 팝업이 끝났다. 어느 갈래든 **그 환자를 고른 상태로** 두고 닫는다 —
     등록이 끝이 아니라 [접수하기] 로 이어지는 흐름이다 */
  function registered(patient, how) {
    fill(patient);
    setRegOpen(false);
    setRegDone(how);
    setDone(null);
    setError(null);
  }

  /* 채운 칸 중 하나를 q 로 보낸다. 서버가 q 하나만 받아서 여러 칸을
     AND 로 걸 수가 없다 — 좁히는 일은 팝업이 한다.
     전화 · 생년월일이 이름보다 사람을 잘 가르므로 그 순서로 고른다 */
  function term() {
    return form.phone.trim() || form.birth_date.trim() || form.name.trim();
  }

  async function search(e) {
    e?.preventDefault();
    const q = term();
    if (!q || busy) return;
    setBusy(true);
    setError(null);
    setDone(null);
    setEmpty(false);
    try {
      const rows = (await api.search(q)) ?? [];
      if (rows.length === 0) {
        setPicked(null);
        setEmpty(true);
      } else if (rows.length === 1) {
        fill(rows[0]);
      } else {
        setChoices(rows);
      }
    } catch (e2) {
      setError(e2);
    } finally {
      setBusy(false);
    }
  }

  async function checkIn() {
    if (!picked || busy) return;
    setBusy(true);
    setError(null);
    try {
      const order = await api.checkIn({ patient_id: picked.patient_id });
      setDone({ patient: picked, order });
      setForm(EMPTY);
      setPicked(null);
      today.reload();
    } catch (e2) {
      setError(e2);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page
      crumb={["원무과", "접수"]}
      title="접수 · 방문 환자 모니터링"
      sub="환자를 찾아 접수하면 간호 큐로 넘어갑니다. 검사 종류는 정하지 않습니다."
    >
      <div className="split">
        <div className="split-l">
          <Card
            title="접수"
            right={can("reception.patient.create")
              ? <Btn onClick={() => setRegOpen(true)}>+ 등록</Btn>
              : null}
          >
            <form onSubmit={search}>
              <div className="find">
                <label className="field">
                  <span>이름</span>
                  <input value={form.name} disabled={busy}
                         onChange={(e) => edit("name", e.target.value)} />
                </label>
                <label className="field">
                  <span>전화번호</span>
                  <input value={form.phone} disabled={busy} inputMode="tel"
                         onChange={(e) => edit("phone", e.target.value)} />
                </label>
                <label className="field">
                  <span>생년월일</span>
                  <input type="date" value={form.birth_date} disabled={busy}
                         onChange={(e) => edit("birth_date", e.target.value)} />
                </label>
              </div>
              <p className="hint">셋 중 하나만 넣어도 됩니다. 엔터로도 찾습니다.</p>
              <Btn kind="fill" type="submit" disabled={!term() || busy}>
                {busy ? "찾는 중…" : "검색"}
              </Btn>
            </form>

            {error && <Failed error={error} />}
            {done && <Done done={done} />}
            {empty && <NotFound onAdd={can("reception.patient.create")
              ? () => setRegOpen(true) : null} />}
            {regDone && <Registered how={regDone} />}

            {picked && <Picked patient={picked} busy={busy} onCheckIn={checkIn} />}
          </Card>
        </div>

        <div className="split-r">
          <Card title="방문 환자 모니터링" right={<Chip>10초마다</Chip>}>
            <Body loading={today.loading} error={today.error} onRetry={today.reload}>
              {today.data && <Monitor rows={today.data} />}
            </Body>
          </Card>
        </div>
      </div>

      {/* 날짜를 더블클릭하면 3장으로 가면서 그 날짜가 채워진다.
          **주소에 담는다** — 화면 상태로 넘기면 붙여 넣은 주소로 같은 자리가
          다시 안 열린다 */}
      <Calendar onOpenDate={(date) =>
        navigate(`${go.reception.patients()}?date=${date}`)} />

      {choices && (
        <Choose rows={choices} onPick={fill} onClose={() => setChoices(null)} />
      )}

      {regOpen && (
        <Register onClose={() => setRegOpen(false)} onDone={registered} />
      )}
    </Page>
  );
}


/* 여럿일 때 고르는 팝업. **더블클릭으로 고른다** — 한 번 눌러 바로
   정해지면 스치듯 누른 사람이 그대로 들어간다.
   키보드로는 Enter 다. 마우스만 되게 두면 손을 떼야 한다 */
function Choose({ rows, onPick, onClose }) {
  return (
    <Dialog
      title={`${rows.length}명이 찾아졌습니다`}
      sub="더블클릭하거나 Enter 로 고르세요"
      onClose={onClose}
      foot={<Btn onClick={onClose}>닫기</Btn>}
    >
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>이름</th><th>생년월일</th><th>전화번호</th><th>환자번호</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.patient_id} tabIndex={0}
                  onDoubleClick={() => onPick(r)}
                  onKeyDown={(e) => { if (e.key === "Enter") onPick(r); }}>
                <td><b>{r.name ?? "—"}</b></td>
                {/* 같은 해 태어난 동명이인을 가리는 자리다 — 연도만으로는
                    둘이 같아 보인다. birth_date 가 없으면 연도로 떨어진다 */}
                <td className="num">{r.birth_date ?? r.birth_year ?? "—"}</td>
                <td className="num">{r.phone ?? "—"}</td>
                <td className="num dim">{r.patient_number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Dialog>
  );
}

/* 고른 사람 + [접수하기].
   접수 전에 한 번 더 보여주는 자리다 — 오타를 잡는 마지막 지점이다.
   환자번호는 검색 칸에 없으니 여기서 보여줘야 한다 */
function Picked({ patient, busy, onCheckIn }) {
  return (
    <div className="picked">
      <dl className="kv">
        <dt>환자번호</dt><dd>{patient.patient_number}</dd>
        <dt>생년</dt><dd>{patient.birth_year ?? "—"}</dd>
        <dt>성별</dt><dd>{SEX[patient.sex] ?? "—"}</dd>
      </dl>
      <Btn kind="fill" onClick={onCheckIn}
           disabled={busy || !can("reception.checkin")}>
        {busy ? "접수하는 중…" : "접수하기"}
      </Btn>
    </div>
  );
}

const SEX = { female: "여", male: "남" };

/* 못 찾았을 때. **여기서 바로 등록으로 갈 수 있게 한다** — 「위 [+ 등록]
   을 누르세요」로 안내만 하면 눈이 다시 위로 올라갔다 와야 한다 */
function NotFound({ onAdd }) {
  return (
    <div className="slot">
      <b>등록된 환자가 없습니다</b>
      <span>앱을 안 쓰는 분이면 새로 등록할 수 있습니다.</span>
      {onAdd && <Btn onClick={onAdd}>+ 등록</Btn>}
    </div>
  );
}

/* 등록 팝업이 끝난 뒤의 안내. **두 갈래를 다르게 적는다** — 이미 있던
   사람인데 「등록했습니다」라고 하면 같은 사람을 두 번 만든 줄 안다 */
function Registered({ how }) {
  return how === "exists" ? (
    <div className="slot" role="status">
      <b>이미 등록된 환자입니다</b>
      <span>새로 만들지 않고 그 환자를 골랐습니다. 확인 후 접수하세요.</span>
    </div>
  ) : (
    <div className="slot ok" role="status">
      <b>환자를 등록했습니다</b>
      <span>검색 칸에 채웠습니다. 확인 후 접수하세요.</span>
    </div>
  );
}

function Done({ done }) {
  return (
    <div className="slot ok" role="status">
      <b>{done.patient.name ?? done.patient.patient_number} 접수했습니다</b>
      <span>간호 큐로 넘어갔습니다 · 오더 {done.order.exam_order_id}</span>
    </div>
  );
}

/* 오늘 온 사람이 지금 어디에 있나.
   이름은 patient_name 으로 온다 (PatientTodayStatusView). 개인정보가 없는
   환자는 null 이라 그때만 #41 로 떨어진다 */
function Monitor({ rows }) {
  if (!rows.length) {
    return <div className="slot"><b>오늘 접수한 환자가 없습니다</b></div>;
  }
  const nameless = rows.some((r) => !r.patient_name);
  return (
    <>
      <Table
        cols={[
          { key: "pid", label: "환자", w: "38%" },
          { key: "stage", label: "상태" },
          { key: "oid", label: "오더", w: "20%" },
        ]}
        rows={rows.map((r) => ({
          id: r.exam_order_id,
          pid: r.patient_name
            ? <b>{r.patient_name}</b>
            : <span className="dim">#{r.patient_id}</span>,
          stage: <Chip tone={r.stage === "접수 대기" ? "fill" : "line"}>{r.stage}</Chip>,
          oid: <span className="num dim">{r.exam_order_id}</span>,
        }))}
      />
      {nameless && <Warn>이름이 없는 환자는 번호로 표시합니다.</Warn>}
    </>
  );
}

function Failed({ error }) {
  return (
    <div className="slot bad" role="alert">
      <b>{error.detail || error.message}</b>
      <span>{error.code}{error.traceId && <> · {error.traceId}</>}</span>
    </div>
  );
}
