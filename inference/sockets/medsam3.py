"""MedSAM3 백본 한 벌 — 소켓 4·5(초음파)와 3(MRI)이 어댑터만 갈아 끼운다.

같은 병합본(medsam3_merged.pt · 3.37GB)을 소켓마다 따로 올리고 있었다.
둘 다 상주하면 9GB 인데, 한 벌만 두고 LoRA 어댑터(74MB)를 바꿔 끼우면 4.1GB 다.

왜 남의 코드를 안 고치나
  us·mri 의 load_model 은 우리 레포 밖이다 — models/us 는 .gitignore 에 걸려
  있고 models/mri 는 남의 작업본 심볼릭 링크다. 고쳐도 커밋이 안 되고 남이
  덮어쓰면 사라진다. 대신 둘이 공통으로 거치는 M["load_merged_model"] 을
  캐시판으로 바꿔 끼운다.

교체가 되는 근거 — 2026-09-07 실측
  us·mri·mammo 세 어댑터를 한 백본에 다섯 번 갈아 끼우며(us → mammo → mri →
  mammo → us) 시각 백본 출력을 각각 따로 올린 것과 비교했다. 다섯 번 전부
  비트 단위로 같았다(max 0.000e+00). 교체는 0.06~0.28초다.

  따로 올릴 때  us 4,454 + mri 4,534 + mammo 4,614 = 13,602 MiB
  한 벌         4,148 MiB 상주 · 순전파 중 4,942 MiB

⚠ lora_B 를 0 으로 미는 것이 이 파일의 핵심이다
  어댑터마다 채우는 슬롯이 다르다 — us·mri 는 458개, mammo 는 278개다.
  좁은 어댑터를 얹을 때 밀지 않으면 이전 어댑터 값이 나머지 180개에 그대로
  남아 조용히 틀린 결과가 나온다. 오류가 아니라 그럴듯한 숫자로 나오므로
  위험하다. strict=False 는 "없는 키는 건너뛴다"이지 "0 으로 만든다"가 아니다.

맘모는 아직 넣지 않는다
  ① build_descriptor 가 load_merged_model 을 부른 뒤 vision_backbone 만 떼어
     del full 한다. 캐시판을 쓰면 공용 백본의 일부를 떼어 가게 되어 어댑터
     교체가 서술어 트렁크에도 번진다.
  ② 맘모의 LoRA 설정이 좁다(10종·3부위). 맘모가 먼저 올라오면 그 설정으로
     백본이 세워져 us·mri 어댑터가 안 들어간다.
  둘 다 남의 build_detector 를 고쳐야 풀린다 — 2단계로 미룬다.
"""
import threading

import torch

# 상주 백본. 처음 부른 소켓이 세우고 그 뒤로는 모두 이것을 쓴다.
_MODEL = None

# 지금 얹혀 있는 어댑터 경로. 같은 소켓이 이어서 판독하면 교체를 건너뛴다.
_ACTIVE = None

# 읽어 둔 어댑터 state_dict. CPU 에 둔다 — us 74MB · mri 74MB.
# 매번 디스크에서 읽으면 교체가 0.2초에서 1초대로 늘어난다.
_CACHE = {}

# patch() 가 여러 소켓에서 동시에 불릴 수 있다. gpu.LOCK 은 판독용이라
# 적재 경로를 다 덮지 못하므로 여기서 따로 잠근다.
_LOCK = threading.Lock()


def patch(M: dict) -> dict:
    """M["load_merged_model"] 을 캐시판으로 바꿔 그대로 돌려준다.

    소켓의 _load 가 import_medsam3() 직후 한 번 부르면, 그 뒤 load_model 이
    내부에서 부르는 load_merged_model 이 캐시를 탄다. 호출부는 바뀌지 않는다.

    같은 M 을 두 번 patch 해도 안전하다 — 이미 바꿔 놓았으면 그대로 둔다.
    소켓마다 import_medsam3 가 새 dict 를 만들지만 안의 함수는 같은 객체다.
    """
    if getattr(M.get("load_merged_model"), "_shared", False):
        return M
    orig = M["load_merged_model"]

    def cached(ckpt, cfg, device="cuda"):
        global _MODEL
        with _LOCK:
            if _MODEL is None:
                _MODEL = orig(ckpt, cfg, device=device)
        return _MODEL

    cached._shared = True
    M["load_merged_model"] = cached
    return M


def use(adapter_path: str) -> None:
    """어댑터를 얹는다. 판독 직전에 부른다 — gpu.LOCK 안이어야 한다.

    이미 얹혀 있으면 아무것도 안 한다. 한 소켓만 계속 쓰면 비용이 0 이다.
    백본을 아직 안 세웠으면(_MODEL is None) 조용히 넘어간다 — 공용화를 안 타는
    경로에서 불려도 터지지 않게.
    """
    global _ACTIVE
    if _MODEL is None or _ACTIVE == adapter_path:
        return
    sd = _CACHE.get(adapter_path)
    if sd is None:
        sd = _CACHE[adapter_path] = torch.load(adapter_path, map_location="cpu")
    with torch.no_grad():
        for name, p in _MODEL.named_parameters():
            if name.endswith("lora_B"):
                p.zero_()
        _MODEL.load_state_dict(sd, strict=False)
    _ACTIVE = adapter_path


def active() -> str | None:
    """지금 얹힌 어댑터 경로. healthz 가 보여준다."""
    return _ACTIVE


def loaded() -> bool:
    """공용 백본이 올라와 있나."""
    return _MODEL is not None
