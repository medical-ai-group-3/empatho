#!/usr/bin/env python3
"""연결 점검 — 진짜 DICOM 한 장으로 file-gateway 전 경로를 태운다.

시험(go test)은 내가 지어낸 바이트로 돌린다. 이 스크립트는 **실제 촬영 파일**로
같은 경로를 태워서, 시험이 못 보는 것을 잡는다.

    ① 저장소에 진짜로 들어가는가        (Garage 든 로컬 디스크든)
    ② 내려받은 바이트가 올린 것과 같은가  (sha256 대조)
    ③ Range 요청이 되는가               (뷰어가 이걸 쓴다)
    ④ 티켓 범위 밖은 막히는가            (권한 경계)
    ⑤ **G-F7 이 머리말을 읽는가**        ← 오늘의 핵심
       실제 CBIS 파일에서 좌우·촬영방향·화소 간격이 나오는지

의존성 없음. 표준 라이브러리만 쓴다.

사용
    python3 smoke.py --file ~/workspace/breast/mammo/.../000000.dcm
    python3 smoke.py --file x.dcm --gw http://127.0.0.1:8091 --key dev-key
"""

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

C = {"g": "\033[32m", "r": "\033[31m", "y": "\033[33m",
     "b": "\033[1m", "d": "\033[2m", "0": "\033[0m"}
PASS, FAIL = [], []


def ok(msg):
    PASS.append(msg)
    print(f"  {C['g']}✓{C['0']} {msg}")


def bad(msg, detail=""):
    FAIL.append(msg)
    print(f"  {C['r']}✗ {msg}{C['0']}")
    if detail:
        for line in str(detail).splitlines()[:6]:
            print(f"      {C['d']}{line}{C['0']}")


def req(method, url, data=None, headers=None, want=None):
    r = urllib.request.Request(url, data=data, method=method,
                               headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=300) as res:
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:
        if want is not None:
            bad(f"{method} {url} 연결 실패", e)
        raise


def mint(script, key, **kw):
    args = [sys.executable, str(script), "--key", key]
    for k, v in kw.items():
        args += [f"--{k.replace('_','-')}", str(v)]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"티켓 발급 실패: {out.stderr}")
    return out.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="시험할 DICOM 파일")
    ap.add_argument("--gw", default="http://127.0.0.1:8091")
    ap.add_argument("--key", default="dev-key", help="TICKET_KEY")
    ap.add_argument("--patient", default="P-SMOKE")
    ap.add_argument("--scope", default="STUDY-SMOKE")
    a = ap.parse_args()

    path = Path(a.file).expanduser()
    if not path.exists():
        sys.exit(f"파일이 없다: {path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    prefix = f"patients/{a.patient}/studies/{a.scope}"
    minter = Path(__file__).with_name("mint_ticket.py")

    print(f"{C['b']}file-gateway 연결 점검{C['0']}")
    print(f"  파일   {path.name}  {len(raw):,} bytes")
    print(f"  sha256 {digest[:32]}…")
    print(f"  게이트 {a.gw}\n")

    # ── 0. health
    print(f"{C['b']}0. 살아 있는가{C['0']}")
    try:
        st, _, body = req("GET", f"{a.gw}/svc/v1/health")
    except Exception as e:
        sys.exit(f"  {C['r']}✗ file-gateway 에 못 붙는다: {e}{C['0']}\n"
                 f"    떠 있는지, 주소가 맞는지 확인할 것")
    if st == 200:
        info = json.loads(body)
        ok(f"응답  bucket={info.get('bucket')}")
    else:
        bad(f"health 가 {st}", body)

    # ── 1. 업로드 (G-F4 → I-1 → G-F7 → I-2)
    print(f"\n{C['b']}1. 업로드{C['0']}")
    tok = mint(minter, a.key, purpose="dicom_upload", patient=a.patient,
               scope=a.scope, prefix=prefix, max_bytes=max(len(raw) * 2, 1 << 20))
    st, _, body = req("POST", f"{a.gw}/svc/v1/files", data=raw, headers={
        "Authorization": f"Bearer {tok}",
        "X-Filename": path.name,
        "Content-Type": "application/dicom",
    })
    if st != 201:
        bad(f"업로드가 {st}", body.decode("utf-8", "replace"))
        summary()
        return
    res = json.loads(body)
    key = res["object_key"]
    ok(f"201  object_key={key}")

    if res.get("checksum_sha256") == digest:
        ok("sha256 일치 — 바이트가 안 상했다")
    else:
        bad("sha256 불일치", f"보낸 것 {digest}\n받은 것 {res.get('checksum_sha256')}")
    if res.get("byte_size") == len(raw):
        ok(f"크기 일치 {len(raw):,}")
    else:
        bad(f"크기 불일치 {res.get('byte_size')} (실제 {len(raw)})")
    if key.startswith(prefix + "/"):
        ok("키가 티켓 접두사 아래에 있다")
    else:
        bad(f"키가 접두사 밖이다: {key}")

    # ── 2. G-F7 — 오늘의 핵심
    print(f"\n{C['b']}2. G-F7 — DICOM 머리말{C['0']}")
    d = res.get("dicom")
    if not d:
        bad("DICOM 으로 인식 못 했다",
            "머리말이 다른 형식이거나 파서가 못 읽었다. "
            "file-gateway 로그를 볼 것")
    else:
        ok(f"인식  modality={d.get('modality')} "
           f"sop={str(d.get('sop_instance_uid'))[:28]}…")
        if d.get("metadata_registered") is True:
            ok("I-2 가 Django(가짜)에 등록됐다")
        elif d.get("metadata_registered") is False:
            bad("I-2 실패 — 가짜 Django 가 떠 있는지 확인")
        sp = d.get("pixel_spacing_mm")
        if sp:
            ok(f"화소 간격 {sp} mm/px")
        else:
            print(f"  {C['y']}◦{C['0']} 화소 간격 없음 "
                  f"{C['d']}— CBIS(필름 스캔)면 정상이다. "
                  f"VinDr 이면 파서를 봐야 한다{C['0']}")
        if "orthanc" in d:
            if d["orthanc"] == "failed":
                bad("Orthanc 전송 실패", "주소·인증을 확인할 것")
            else:
                ok(f"Orthanc 등록  id={d['orthanc']}")

    # ── 3. 다운로드 (G-F5)
    print(f"\n{C['b']}3. 다운로드{C['0']}")
    tok = mint(minter, a.key, purpose="download", patient=a.patient,
               scope=a.scope, prefix=prefix)
    st, hdr, got = req("GET", f"{a.gw}/svc/v1/files/{key}",
                       headers={"Authorization": f"Bearer {tok}"})
    if st != 200:
        bad(f"다운로드가 {st}", got.decode("utf-8", "replace"))
    elif hashlib.sha256(got).hexdigest() != digest:
        bad("내려받은 바이트가 다르다",
            f"{len(got):,} bytes (올린 것 {len(raw):,})")
    else:
        ok(f"바이트가 완전히 같다 ({len(got):,})")

    # ── 4. Range — 뷰어가 쓴다
    tok = mint(minter, a.key, purpose="download", patient=a.patient,
               scope=a.scope, prefix=prefix)
    st, hdr, part = req("GET", f"{a.gw}/svc/v1/files/{key}", headers={
        "Authorization": f"Bearer {tok}", "Range": "bytes=0-1023"})
    if st == 206 and len(part) == 1024 and part == raw[:1024]:
        ok(f"Range  206  {hdr.get('Content-Range')}")
    else:
        bad(f"Range 가 {st}, {len(part)} bytes")

    # ── 5. 권한 경계
    print(f"\n{C['b']}4. 티켓 범위 밖은 막히는가{C['0']}")
    tok = mint(minter, a.key, purpose="download", patient="P-OTHER",
               scope="S-OTHER", prefix="patients/P-OTHER/studies/S-OTHER")
    st, _, body = req("GET", f"{a.gw}/svc/v1/files/{key}",
                      headers={"Authorization": f"Bearer {tok}"})
    if st == 403:
        ok("남의 티켓으로는 403")
    else:
        bad(f"남의 티켓이 {st} 로 통과했다 — 권한 경계가 뚫렸다",
            body.decode("utf-8", "replace"))

    # ── 6. 티켓 재사용
    tok = mint(minter, a.key, purpose="download", patient=a.patient,
               scope=a.scope, prefix=prefix, nonce="smoke-fixed-nonce")
    req("GET", f"{a.gw}/svc/v1/files/{key}",
        headers={"Authorization": f"Bearer {tok}"})
    st, _, _ = req("GET", f"{a.gw}/svc/v1/files/{key}",
                   headers={"Authorization": f"Bearer {tok}"})
    if st == 401:
        ok("같은 티켓 재사용은 401")
    else:
        bad(f"티켓 재사용이 {st} 로 통과했다")

    summary()


def summary():
    print(f"\n{'='*70}")
    if FAIL:
        print(f"{C['r']}{C['b']}실패 {len(FAIL)}건{C['0']} · 통과 {len(PASS)}건")
        for f in FAIL:
            print(f"  {C['r']}·{C['0']} {f}")
        sys.exit(1)
    print(f"{C['g']}{C['b']}전부 통과 — {len(PASS)}건{C['0']}")
    print("실제 파일이 저장소를 왕복하고, 머리말이 Django 까지 갔다.")


if __name__ == "__main__":
    main()
