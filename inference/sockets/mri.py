"""MRI 소켓 (3) — MedSAM3 + LoRA. 볼륨을 슬라이스별로 훑어 3D 마스크를 만든다.

다른 소켓과 다른 점이 둘이다.

  ① 파일이 둘이다. 조영 전(pre)과 조영 후(post)를 함께 받아 (2,Z,Y,X) 로
     쌓는다. 정규화가 두 phase 를 합쳐서 mean/std 를 내므로 채널을 따로
     만들어 붙이면 학습 때와 분포가 달라진다.
  ② dataset_tag 를 호출부가 정해 준다. 값에 따라 내는 것이 통째로 다르다 —
     mamamia 는 종양 위치, duke 는 유방 밀도. 잘못 넘기면 오류가 아니라
     엉뚱한 값이 나온다. 우리가 짐작하지 않는다.

슬라이스가 150~250장이고 그만큼 추론을 반복한다. 초음파(장당 1회)나
맘모(20초)와 달리 분 단위가 될 수 있다. 담당자 README 에도 아직 TBD 다.
"""

import os 
import pathlib 
import sys 
import tempfile 
import shutil 
import zipfile 
import io

from sockets import gpu 

MODEL_ROOT = pathlib.Path(os.getenv("MODEL_ROOT", "/models"))

# MRI 작업 폴더. 심볼릭 링크이고 실체는 워크스테이션의 학습 폴더다.
# infer_mri 가 MRI_ROOT = parents[2] 로 뿌리를 잡아 postprocess_3d 와
# training/code/preprocess 를 상대경로로 찾는다 — 복사하면 깊이가 어긋난다.
MRI_DIR = MODEL_ROOT / "mri"

# 서빙 설정. 안에 MedSAM3 백본 설정, ckpt_dir 경로가 절대경로로 저장되어있음 
CONFIG = MRI_DIR / "serving" / "configs" / "mri_lora.yaml"

NAME = "mri"

# 이 모듈이 담당하는 소켓 
SOCKET_IDS = {"3"}

# 적재 허용 스위치 꺼져 있으면 요청이 와도 기권한다 
ENABLED = os.getenv("LOAD_MRI", "0") == "1"

# 이 소켓이 판독하려면 있어야하는 파일 - MODEL_ROOT 기준 상대경로 
# 가중치를 안 넘기면 load_model 이 <ckpt_dir>/mri_lora_best.pt 를 쓴다 
REQUIRED = [
    "mri/serving/ckpt/mri_lora_best.pt",
    "mri/serving/configs/mri_lora.yaml",
]

_STATE = {}
_ERROR = {}

def _materialize(data: bytes, filename: str | None, dest: pathlib.Path) -> pathlib.Path: 
    """바이트를 SimpleITK 가 읽을 수 있는 경로로 내린다.

    .zip 이면 풀어서 폴더를 돌려준다. DICOM 시리즈는 슬라이스마다 파일이라
    200장쯤 되는데 한 요청에 파일 하나씩 올릴 수 없다. Go 가 Orthanc 에서
    꺼낸 시리즈를 그대로 묶어 보내면 여기서 푼다.
    .zip 이 아니면 파일 하나로 쓴다(.nii · .nii.gz).

    ── 압축을 풀 때 지키는 두 가지 ────────────────────────────────
    ① zip 안에 적힌 경로를 그대로 믿지 않는다. "../../etc/x" 같은 항목이
       섞이면 임시 폴더 밖에 파일을 쓰게 된다. 이름만 떼어 쓴다.
    ② 전부 한 폴더에 평평하게 푼다. GetGDCMSeriesFileNames 는 하위 폴더를
       내려가지 않으므로, 원본 폴더 구조를 살리면 파일을 못 찾는다.
       이름이 겹칠 수 있어 번호를 붙인다 — DICOM 순서는 파일명이 아니라
       헤더의 위치 태그로 정해지므로 이름을 바꿔도 안전하다.
    """
    name = filename or "volume.nii.gz"
    if not name.lower().endswith(".zip"):
        p = dest / pathlib.Path(name).name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for i, info in enumerate(z.infolist()):
            if info.is_dir():
                continue
            flat = dest / f"{i:05d}_{pathlib.Path(info.filename).name}"
            with z.open(info) as src, open(flat, "wb") as dst: 
                shutil.copyfileobj(src, dst)
    return dest

def _load() -> dict:
    """번들을 올린다. 적재량과 시간은 아직 실측 전이다(담당자 README 도 TBD).

    load_model 이 안에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩).
    기본값이 원위치시키므로 keep_cwd 는 건드리지 않는다.
    """
    sys.path.insert(0, str(MRI_DIR / "serving" / "code"))
    from infer_mri import load_model, preprocess_raw_to_volume
    from infer_mri import predict as _predict
    
    bundle = load_model(str(CONFIG))
    return {
        "bundle" : bundle,
        "predict": _predict,
        "preprocess": preprocess_raw_to_volume,
        "versions": {
            "model_name": "medsam3",
            "model_version": pathlib.Path(bundle["path"]["weights"]).name,
        },
    }

def ensure() -> None:
    """첫 요청 때 올린다. 실패하면 기록만 하고 다음 요청에서 다시 시도한다."""
    if _STATE: 
        return 
    with gpu.LOCK:
        # LOCK을 기다리는 동안 다른 요청이 올라왔을 수 있음 
        if _STATE:
            return 
        try: 
            _STATE.update(_load())
            gpu.mark(NAME)
            _ERROR.clear() 
        except Exception as exc:
            # 예외가 발생하면 요청이 500을 받음, 사유를 남기기고 기권 
            _ERROR["msg"] = f"{type(exc).__name__}: exc"
            
def is_loaded() -> bool:
    """GPU 에 올라와 있나 확인"""
    return bool(_STATE)

def error():
    """마지막 적재 실패 사유. 없으면 None"""
    return _ERROR.get("msg")

def versions() -> dict:
    """응답에 실을 가중치 식별자, 안 올라왔으면 emtpy dict"""
    return _STATE.get("versions", {})

def predict(data:bytes, filename: str | None = None, post: bytes | None=None, post_filename: str | None=None, dataset_tag: str | None=None, **over) -> dict: 
    """조영 전(+후) 볼륨 → 종양 위치 또는 유방 밀도.

      data           조영 전 볼륨 바이트 (nii · nii.gz)
      filename       확장자를 보고 형식을 정하므로 원본 이름이 필요하다
                     .zip 이면 DICOM 시리즈로 보고 풀어서 폴더로 넘긴다 
      post           조영 후 볼륨 바이트. mamamia 는 있어야 한다
      dataset_tag    "mamamia" 또는 "duke". 호출부가 정한다
      over           thresholds.yaml 의 mri: 항목. include_mesh 도 여기로 끈다

    바이트를 임시 파일로 내리는 이유 — SimpleITK 가 경로로만 읽는다.
    블록을 벗어나면 지워지므로 환자 영상이 워크스테이션에 남지 않는다.

    geometry 를 넘기는 이유 — evidence 박스를 원본 DICOM 좌표로 되돌린다.
    안 넘기면 리샘플링된 1mm 좌표로 나가서 화면에 겹쳐 그릴 수 없다.

    patient_id 는 넘기지 않는다. 환자 정보를 여기까지 옮기지 않기로 했다.

    전처리(리샘플링·정규화)까지 락 안에서 하는 이유 — CPU 일이라 GPU 를
    놀리지만, 락 밖에 두면 그 사이 수거자가 프로세스를 끝낼 수 있다.
    긴 요청이 조용히 끊기는 것보다 다른 소켓이 기다리는 편이 낫다.
    """
    if not dataset_tag: 
        raise ValueError("dataset_tag 가 필요하다 (mammia 또는 duke)")
    with gpu.LOCK:
        if not _STATE:
            raise RuntimeError("모델이 내려감")
        gpu.touch()
        with tempfile.TemporaryDirectory(prefix="mri_") as tmp:
            tmp = pathlib.Path(tmp)
            pre_path = _materialize(data, filename, tmp / "pre")
            post_path = (_materialize(post, post_filename, tmp / "post")
                        if post is not None else None)
                
        volume, geometry = _STATE["preprocess"](
            str(pre_path), str(post_path) if post_path else None,
            return_geometry=True
        )
        gpu.touch() # 전처리가 길다. 추론 직전에 시계를 한 번 더 민다
        return _STATE["predict"](_STATE["bundle"], volume, dataset_tag, geometry=geometry, **over)