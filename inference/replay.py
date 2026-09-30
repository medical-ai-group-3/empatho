"""시연용 결과 재생 — 같은 입력이 다시 오면 저장해 둔 응답을 바로 돌려준다.

REPLAY_DIR 환경변수가 있을 때만 켜진다. 비어 있으면(기본) 아무 일도 하지 않는다.

    시연 전   시연에 쓸 파일을 한 번씩 실제로 판독 → 응답이 여기 저장된다
    시연 중   같은 파일이 새 환자로 올라오면 GPU 를 건너뛰고 저장된 응답을 준다
    시연 뒤   스위치를 끄고 REPLAY_DIR 을 지운다

저장하는 것은 판독 응답(수치 · 마스크 · 메시)이다. 영상 자체는 쓰지 않는다.

「같은 입력」은 DICOM 이면 픽셀 데이터만 본다. 새 환자로 다시 올리면 Orthanc ·
앱을 거치며 머리 정보(이름 · UID)가 바뀔 수 있어서다. MRI 는 시리즈를 zip 으로
받는데, zip 은 만들 때마다 시각이 달라지므로 안의 파일 내용만 모아 본다.
"""
import hashlib
import io
import json
import os
import pathlib
import zipfile

ROOT = os.getenv("REPLAY_DIR", "").strip()
_PIXEL_TAG = b"\xe0\x7f\x10\x00"          # DICOM (7FE0,0010) Pixel Data, little endian


def enabled() -> bool:
    return bool(ROOT)


def _fingerprint(data: bytes) -> bytes:
    """내용 지문. zip 은 안의 파일들, DICOM 은 픽셀 데이터, 나머지는 바이트 그대로."""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                parts = sorted(hashlib.sha256(_fingerprint(z.read(n))).digest()
                               for n in z.namelist() if not n.endswith("/"))
            return b"".join(parts)
        except zipfile.BadZipFile:
            return data
    if data[128:132] == b"DICM":
        at = data.rfind(_PIXEL_TAG)
        if at > 0:
            return data[at:]
    return data


def key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            p = b""
        h.update(_fingerprint(p) if isinstance(p, bytes) else str(p).encode())
        h.update(b"\x00")
    return h.hexdigest()


def load(kind: str, k: str):
    if not enabled():
        return None
    f = pathlib.Path(ROOT) / kind / f"{k}.json"
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def save(kind: str, k: str, payload: dict) -> None:
    """원자적으로 쓴다 — 쓰다 끊긴 파일을 다음에 읽어 깨진 응답을 주지 않게."""
    if not enabled():
        return
    d = pathlib.Path(ROOT) / kind
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{k}.tmp"
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / f"{k}.json")
