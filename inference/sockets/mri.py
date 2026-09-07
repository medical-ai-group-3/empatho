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

from sockets import base, gpu, medsam3

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

def _own(code_dir: pathlib.Path, *names: str) -> None:
    """내 code 폴더를 sys.path 맨 앞에 두고, 남이 차지한 모듈 이름을 비운다.

    us 와 mri 에 model_io 라는 같은 이름의 모듈이 있다. 파이썬은 모듈을 이름으로
    한 번만 올리므로, 초음파가 먼저 판독한 프로세스에서 MRI 를 부르면 MRI 의
    infer_mri 가 us 의 model_io 를 받는다.

      ImportError: cannot import name 'load_model' from 'model_io'
      (.../models/us/code/model_io.py)

    sys.path 를 앞에 꽂는 것만으로는 안 된다 — 이미 sys.modules 에 있으면
    파이썬이 경로를 다시 보지 않는다. 그 이름을 지워야 다시 찾는다.

    공용화 이전부터 있던 결함이다. 소켓을 하나만 올려 시험할 때는 안 드러났다.
    """
    d = str(code_dir)
    while d in sys.path:
        sys.path.remove(d)
    sys.path.insert(0, d)
    for n in names:
        mod = sys.modules.get(n)
        if mod is not None and not str(getattr(mod, "__file__", "")).startswith(d):
            del sys.modules[n]


def _load() -> dict:
    """번들을 올린다. 적재량과 시간은 아직 실측 전이다(담당자 README 도 TBD).

    load_model 이 안에서 os.chdir 한다(MedSAM3 가 상대경로를 하드코딩).
    기본값이 원위치시키므로 keep_cwd 는 건드리지 않는다.
    """
    _own(MRI_DIR / "serving" / "code", "model_io", "infer_mri", "normalize", "derived_io")
    from infer_mri import load_model, preprocess_raw_to_volume
    from infer_mri import predict as _predict

    # 초음파와 같은 병합본을 쓴다(sha c98faebf). 먼저 올린 쪽이 세우고 나눠 쓴다.
    medsam3.arm("model_io", "eval_mri_lora_v3")

    bundle = load_model(str(CONFIG))
    return {
        "bundle" : bundle,
        "predict": _predict,
        "preprocess": preprocess_raw_to_volume,
        "versions": {
            "model_name": "medsam3",
            "model_version": pathlib.Path(bundle["paths"]["weights"]).name,
        },
        # 판독 직전에 얹을 어댑터 — us.py 와 같은 이유다.
        "adapter": str(bundle["paths"]["weights"]),
    }

def _run(state, data, filename, post=None, post_filename=None, dataset_tag=None, **over) :
    """MRI 고유 부분. 락은 base 가 잡는다.

      post / post_filename   조영 후 볼륨. 없으면 밀도만 낸다 (phases=1)
      dataset_tag            09-04 에 폐지됐다. main.py 가 아직 넘기므로 받아서 버린다

    임시 폴더 안에서 읽어야 한다 — with 를 벗어나면 폴더가 지워진다.
    전처리까지 락 안에서 하는 이유 — 락 밖이면 그 사이 수거자가 프로세스를 끝낼 수 있다.
    """
    
    medsam3.use(state["adapter"])   # 다른 소켓이 쓰고 갔을 수 있다. 락 안이다
    with tempfile.TemporaryDirectory(prefix="mri_") as tmp: 
        tmp = pathlib.Path(tmp)
        pre_path = _materialize(data, filename, tmp / "pre")
        post_path = (_materialize(post, post_filename, tmp / "post")
                     if post is not None else None)
        tumor, density, geometry = state["preprocess"](
            str(pre_path), str(post_path) if post_path else None, 
            return_geometry=True
        )
        gpu.touch() 
        return state["predict"](state["bundle"], tumor, density, geometry=geometry, **over)

SOCKET = base.Socket(NAME, SOCKET_IDS, ENABLED, _load, _run, drop=())