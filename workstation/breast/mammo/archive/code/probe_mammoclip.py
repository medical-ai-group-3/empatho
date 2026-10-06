#!/usr/bin/env python
"""
Mammo-CLIP 을 우리 파이프라인에 붙일 수 있는지 확인한다.

왜
  우리 서술어 모델은 SAM3 시각 백본으로 특징을 뽑는다. 그 백본은 맘모그래피를
  배운 적이 없다 — 오늘 검출 실험에서 확인한 그 문제다.
  Mammo-CLIP 은 맘모 영상과 판독문 쌍으로 사전학습된 모델이다.
  백본만 갈아끼우고 --cache 로 머리만 다시 학습하면 4분이면 비교가 끝난다.

확인한 규격 (공식 저장소 기준)
  백본     timm  tf_efficientnet_b5_ns   in_chans=1
  입력     1520 x 912  (종횡비 유지, 정사각 아님)
  정규화   평균 0.3089279  표준편차 0.25053555408335154
  라이선스 CC BY-NC-SA 4.0  — 비영리 연구용, 동일조건변경허락

무엇을 보나
  1. timm 이 있고 해당 모델을 만들 수 있는가
  2. 체크포인트 파일이 있는가, 어떤 구조인가
  3. 체크포인트의 시각 인코더 가중치가 timm 모델과 맞물리는가
  4. 특징 지도 크기 — 4x4 격자 풀링을 붙일 수 있는가

GPU 를 쓰지 않는다. CPU 로 구조만 본다.

사용
  python3 probe_mammoclip.py                       # 환경만
  python3 probe_mammoclip.py --ckpt b5-...tar      # 체크포인트까지
"""

import argparse
import sys
from pathlib import Path

HOME = Path.home()
DEF_CKPT = HOME / "workspace/breast/mammo/ckpt/mammoclip/b5-model-best-epoch-7.tar"

# 공식 설정에서 확인한 값
ARCH = "tf_efficientnet_b5_ns"
IN_H, IN_W = 1520, 912
NORM_MEAN, NORM_STD = 0.3089279, 0.25053555408335154


def show(t):
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def best_prefix(sd, want, max_depth=3):
    """
    체크포인트 키에서 접두사를 벗겨가며 목표 키 집합과 가장 많이 겹치는 조합을 찾는다.

    왜 여러 단계인가
      image_encoder.model.conv_stem.weight  처럼 두 단계 이상 씌워진 경우가 흔하다.
      한 단계만 벗기면 model.conv_stem.weight 가 되어 여전히 안 맞는다.

    반환: (일치 개수, 접두사 문자열 또는 None, 벗긴 사전)
    """
    cands = {None: dict(sd)}
    for depth in range(1, max_depth + 1):
        seen = set()
        for k in sd:
            parts = k.split(".")
            if len(parts) <= depth:
                continue
            seen.add(".".join(parts[:depth]))
        for p in seen:
            stripped = {k[len(p) + 1:]: v for k, v in sd.items()
                        if k.startswith(p + ".")}
            if stripped:
                cands[p] = stripped

    best = (0, None, dict(sd))
    for p, c in cands.items():
        hit = len(want & set(c))
        if hit > best[0]:
            best = (hit, p, c)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(DEF_CKPT))
    ap.add_argument("--arch", default=ARCH)
    a = ap.parse_args()

    show("1. 의존 패키지")
    try:
        import torch
        print(f"  torch  {torch.__version__}")
    except ImportError:
        sys.exit("  torch 없음")
    try:
        import timm
        print(f"  timm   {timm.__version__}")
    except ImportError:
        print("  timm 없음  ->  pip install timm")
        print("\n  timm 이 있어야 백본을 만들 수 있다. 설치 후 다시 돌려라.")
        return

    show("2. 백본 생성 (사전학습 없이 구조만)")
    try:
        model = timm.create_model(a.arch, pretrained=False, in_chans=1)
    except Exception as e:
        print(f"  실패: {type(e).__name__}: {e}")
        print(f"\n  '{a.arch}' 를 못 만든다. timm 버전에 따라 이름이 다를 수 있다.")
        cands = [n for n in timm.list_models("*efficientnet_b5*")][:10]
        print(f"  비슷한 이름: {cands}")
        return
    n = sum(p.numel() for p in model.parameters())
    print(f"  {a.arch}   {n/1e6:.1f}M")
    print(f"  비교: SAM3 시각 백본 454.0M  ->  {454.0/(n/1e6):.1f}배 가볍다")

    show("3. 특징 지도 크기 — 격자 풀링을 붙일 수 있나")
    import torch
    model.eval()
    with torch.no_grad():
        x = torch.zeros(1, 1, IN_H, IN_W)
        try:
            f = model.forward_features(x)
            print(f"  입력 {tuple(x.shape)}")
            print(f"  forward_features -> {tuple(f.shape)}")
            if f.ndim == 4:
                _, c, h, w = f.shape
                print(f"    채널 {c}  공간 {h}x{w}")
                print(f"    4x4 격자 평균 -> 특징 {c*16}차원")
                print(f"    (현재 SAM3 경로는 grid4 를 쓴다 — 같은 방식으로 붙는다)")
        except Exception as e:
            print(f"  실패: {type(e).__name__}: {e}")

    show("4. 체크포인트")
    ck = Path(a.ckpt)
    if not ck.is_file():
        print(f"  없다: {ck}")
        print("\n  받는 법 — 저장소는 Hugging Face 다:")
        print("    mkdir -p ~/workspace/breast/mammo/ckpt/mammoclip")
        print("    cd ~/workspace/breast/mammo/ckpt/mammoclip")
        print("    wget https://huggingface.co/shawn24/Mammo-CLIP/resolve/main/"
              "Pre-trained-checkpoints/b5-model-best-epoch-7.tar")
        print("\n  가벼운 쪽으로 먼저 시험해도 된다:")
        print("    wget https://huggingface.co/shawn24/Mammo-CLIP/resolve/main/"
              "Pre-trained-checkpoints/b2-model-best-epoch-10.tar")
        print("\n  ! 라이선스 CC BY-NC-SA 4.0 — 비영리 연구용, 동일조건변경허락.")
        print("    외부 공개 시 같은 라이선스를 달아야 한다.")
        return

    print(f"  파일 {ck}  ({ck.stat().st_size/1e6:.0f}MB)")
    obj = torch.load(str(ck), map_location="cpu", weights_only=False)
    if not isinstance(obj, dict):
        print(f"  ! 예상과 다르다: {type(obj)}")
        return
    print(f"  최상위 키: {list(obj.keys())[:12]}")

    # 상태사전을 찾는다
    sd = None
    for k in ("model", "state_dict", "model_state_dict"):
        if k in obj and isinstance(obj[k], dict):
            sd, where = obj[k], k
            break
    if sd is None:
        sd, where = obj, "(최상위)"
    print(f"  가중치 위치: {where}   텐서 {len(sd)}개")

    # 접두사별로 묶어 본다 — 시각 인코더가 어디 있는지 찾는다
    from collections import Counter
    pref = Counter(k.split(".")[0] for k in sd)
    print(f"\n  접두사별 텐서 수:")
    for p, c in pref.most_common(10):
        tot = sum(v.numel() for k, v in sd.items()
                  if k.split(".")[0] == p and hasattr(v, "numel"))
        print(f"    {p:28s} {c:5d}개  {tot/1e6:8.1f}M")

    show("5. timm 모델과 맞물리는가")
    want = set(model.state_dict().keys())
    hit, pfx, cand = best_prefix(sd, want)
    print(f"  timm 모델 텐서 {len(want)}개")
    print(f"  가장 잘 맞는 접두사: {pfx!r}  ->  {hit}개 일치 (후보 {len(cand)}개)")
    if hit >= len(want) * 0.9:
        print(f"\n  -> 맞물린다. 접두사 {pfx!r} 를 벗기고 load_state_dict 하면 된다.")
    elif hit > 0:
        print(f"\n  -> 부분적으로 맞는다. 이름 규칙이 조금 다르다.")
        miss = sorted(want - set(cand))[:5]
        extra = sorted(set(cand) - want)[:5]
        print(f"     모델에 있는데 체크포인트에 없는 것: {miss}")
        print(f"     체크포인트에만 있는 것:            {extra}")
    else:
        print(f"\n  -> 안 맞는다. 저장소의 로딩 코드를 봐야 한다.")
        print(f"     체크포인트 키 표본: {sorted(sd)[:5]}")
        print(f"     timm 키 표본:      {sorted(want)[:5]}")

    print("\n" + "=" * 74)
    print("다음")
    print("=" * 74)
    print("  맞물리면 특징 추출기를 붙인다.")
    print("  --cache 모드로 특징을 다시 뽑고 머리만 4분 학습하면 비교가 끝난다.")
    print(f"  판단 기준: 2σ (종괴 0.009 · 석회 0.005) 를 넘어야 개선이다.")


if __name__ == "__main__":
    main()
