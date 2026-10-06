#!/usr/bin/env python3
"""
MRI 파생물(3D 메시) 처리 — Go 파생물 게이트웨이 연동 + 로컬 저장 폴백.

★ 2026-09-04 재작성 — Go(file-gateway) 담당의 answer_mri.md 반영.
   이전 버전(2026-09-04 최초 작성분)은 요청 형식(multipart)·체크섬 계산 주체·
   응답 형식·인증을 전부 추측으로 짰고, **여섯 개 중 다섯 개가 실제와 달랐다.**
   특히 이전 코드는 `data={"meta":..., "checksum":...}`를 같이 보냈는데, 실제
   서버는 본문을 파일 바이트 그대로 받아 그대로 저장한다 — 부가 필드를 섞어
   보내면 그게 파일 내용의 일부로 저장되고 **오류 없이 201이 돌아왔을 것이다.**
   즉 이전 코드로 실제 호출했으면 깨진 메시가 체크섬까지 붙어서 조용히 등록됐다.

★ 실제 API (gosvc/cmd/file-gateway 기준, 2026-09-04 Go 담당 확인)
   POST /svc/v1/derived
     Authorization: Bearer <티켓 JWT>   (purpose=derived_upload)
     X-Filename: mesh.stl                 (확장자만 쓰인다 - 경로/이름은 서버가 난수로 생성)
     Content-Type: application/octet-stream
     본문 = 파일 바이트 그대로 (multipart 아님, 요청당 파일 하나)
   응답 201:
     {"object_key", "bucket", "byte_size", "checksum_sha256", "content_type"}
   체크섬은 서버가 계산해서 돌려준다 — 클라이언트는 보내는 게 아니라 로컬 값과
   대조해서 전송 손상을 검증하는 용도로만 쓴다.
   멱등키(Idempotency-Key)는 Go->Django 구간에서 Go가 붙이는 값이라 클라이언트가
   신경 쓸 필요 없다. 클라이언트->Go 1회성 보장은 티켓 nonce가 담당 — 같은 티켓을
   두 번 쓰면 401 TICKET_REPLAYED이므로, 재시도 시 반드시 새 티켓이 필요하다.

★ 갑안/을안 미결정 (A-1, 2026-09-04) — 이 파일의 upload_mesh()는 "MRI가 Go를
   직접 호출하는" 을안을 전제로 한다. STL 실제 크기 확인 후 갑안(응답에 메시를
   실어 Django/Celery가 대신 올림, derived_io.py를 아예 없애는 안)으로 갈 수도
   있다 — 그땐 이 파일의 upload 관련 부분은 통째로 삭제 대상이다. 결정 전까지는
   준비만 해둔다.

★ check_series_geometry()는 그대로 유지한다(Go 담당 권장, H-2/Q7·Q8). Django가
   시리즈 단위로 먼저 차단하기로 하더라도, 앱 서버 업로드 경로가 Go를 안 거치는
   재업로드·수동 투입에 열려 있을 수 있어 MRI 쪽 방어선을 겹으로 두는 게 맞다는
   판단이다. 정상 경로에서는 절대 안 걸리는 게 정상이고, 걸리면 차단이 새고
   있다는 신호로 보고 로그를 크게 남길 것.
"""

import hashlib
from pathlib import Path

import requests

from build_mesh_from_mask import save_stl, save_web_json  # noqa: E402


def check_series_geometry(series_meta):
    """Django/Go에서 받은 시리즈 메타(각 인스턴스의 has_geometry 등)를 검사한다.

    ⚠ 2026-09-04 최종 결론 (파트별_수정목록, "알아두실 것 — 기하 방어선이 지금은
    안 돕니다") — 이 함수는 **현재 호출할 방법이 없다.** 인자로 받는 series_meta는
    앱 서버가 안 준다 — 앱 서버는 파일만 넘긴다. "풀어놓은 폴더에 대고 직접
    호출하면 되지 않나"도 성립하지 않는다 — 그러려면 ImagePositionPatient(3개)·
    ImageOrientationPatient(6개)를 DICOM 헤더에서 직접 읽는 새 코드가 필요한데
    그건 없다.

    **최종 결정: 시리즈 단위 기하 판정·차단은 Django가 전담한다.** 걸린 시리즈는
    MRI 서빙에 아예 안 넘어온다(플래그만 붙여서 넘기지 않음 — 각 소켓이 플래그를
    볼지 말지 각자 정하게 하면 하나라도 안 보는 순간 조용히 틀리기 때문). Go(G-F7)는
    인스턴스 단위 has_geometry를 I-2 콜백에 올려 Django가 쓸 재료만 제공한다.

    이 함수는 그래서 **지금은 죽은 코드다.** 삭제하지 않고 남겨두는 이유는, 나중에
    MRI 서빙이 파일과 함께 시리즈 메타를 직접 받는 경로가 생기면(현재 계획엔 없음)
    바로 쓸 수 있게 하기 위해서다 — 이전 버전의 "방어선" 주석(정상 경로에선 안
    걸려야 하고 걸리면 상위 차단이 새는 것)은 **호출될 기회 자체가 없으므로 지금은
    적용되지 않는다.**

    series_meta: [{"instance_id": ..., "has_geometry": bool, "modality": "MR"|"MG", ...}, ...]
    맘모(MG)는 2D 낱장이라 has_geometry가 없는 게 정상이므로 검사하지 않는다.
    """
    mr_slices = [m for m in series_meta if m.get("modality") == "MR"]
    if not mr_slices:
        return
    missing = [m["instance_id"] for m in mr_slices if not m.get("has_geometry")]
    if missing:
        raise ValueError(
            f"[방어선 발동 - 상위 차단 우회 의심] 기하 정보 없는 MR 슬라이스 "
            f"{len(missing)}개: {missing[:5]}{'...' if len(missing) > 5 else ''} — "
            "3D 재구성이 어긋날 수 있어 추론을 진행하지 않습니다. "
            "Django 시리즈단위 차단을 우회한 경로가 있는지 확인 필요."
        )


def upload_mesh(gateway_url: str, ticket: str, file_bytes: bytes,
                 filename: str, timeout: float = 60.0) -> dict:
    """파생물 파일 하나를 Go 게이트웨이(POST /svc/v1/derived)로 올린다.

    ⚠ 파일 하나 = 티켓 하나(Go 담당 확인, Q5-1). STL과 JSON을 각각 올리려면
    티켓이 두 장 필요하다 — Go 담당 권장대로, 작은 JSON(메타데이터)은 여기로
    올리지 말고 predict() 응답 본문에 그대로 담는 걸 권장한다(그러면 STL 하나만
    올리면 되어 티켓 한 장으로 끝난다).

    ⚠ 티켓은 1회용이다(nonce). 재시도할 때는 반드시 새 티켓으로 다시 호출할 것 —
    같은 티켓으로 재호출하면 401 TICKET_REPLAYED.

    실패 코드별 대응(Go 담당 확인):
        401 TICKET_EXPIRED/INVALID/REPLAYED -> 새 티켓 받고 재시도
        403 TICKET_SCOPE_MISMATCH           -> 재시도 무의미, Django 쪽 문제
        404 DERIVED_DISABLED                -> 재시도 무의미, 배포 설정 문제(파생물 버킷 미설정)
        413 UPLOAD_TOO_LARGE                -> 재시도 무의미, 더 큰 max_bytes로 티켓 재발급 필요
        500 PUT_FAILED                      -> 재시도 대상
        502 CALLBACK_FAILED                 -> 재시도 대상이나 파일은 이미 저장됨(중복 위험) -
                                                2회 정도로 제한하고 계속 실패하면 알릴 것
    """
    local_checksum = hashlib.sha256(file_bytes).hexdigest()

    resp = requests.post(
        f"{gateway_url}/svc/v1/derived",
        headers={
            "Authorization": f"Bearer {ticket}",
            "X-Filename": filename,  # 확장자만 쓰인다 - 실제 저장 경로는 서버가 난수로 생성
            "Content-Type": "application/octet-stream",
        },
        data=file_bytes,  # ⚠ multipart 아님 - 본문에 파일 바이트 그대로. 다른 필드 절대 섞지 말 것
        timeout=timeout,
    )
    if resp.status_code != 201:
        raise RuntimeError(f"파생물 업로드 실패 {resp.status_code}: {resp.text}")

    out = resp.json()
    if out["checksum_sha256"] != local_checksum:
        # 여기서 멈춘다 - 이미 DB에 등록된 뒤이므로 조용히 넘어가면 화면이 깨진 메시를 연다.
        raise RuntimeError(
            f"체크섬 불일치 — 보낸 것 {local_checksum}, 저장된 것 {out['checksum_sha256']}"
        )
    return out  # {"object_key", "bucket", "byte_size", "checksum_sha256", "content_type"}


def save_mesh_files(mesh, out_dir, patient_id, class_name, meta):
    """메시(정점·삼각형)를 로컬 디스크에 STL+JSON으로 저장한다(build_mesh_from_mask.py 재사용).
    Go 업로드 실패 시 폴백, 또는 로컬 테스트 경로로 계속 사용한다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{patient_id}_{class_name.replace(' ', '_')}"
    verts, faces, _normals = mesh
    stl_path = stem.with_suffix(".stl")
    json_path = stem.with_suffix(".json")
    save_stl(stl_path, verts, faces)
    save_web_json(json_path, verts, faces, meta=meta)
    return {"stl_path": str(stl_path), "json_path": str(json_path)}