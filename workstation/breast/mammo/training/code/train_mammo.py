#!/usr/bin/env python
"""
맘모 서술어 헤드 학습 — MedSAM3 병합본을 동결 백본으로 쓴다.

  ROI 1008x1008
    -> 특징 추출 (trunk / 넥 / 중간블록 중 택1)
    -> 풀링 -> 벡터
    -> 서술어 헤드 -> mass 12 / calc 13
    -> 축별 sigmoid + BCE   (label_schema.json 의 설계 그대로)

특징 출처 (--src)
  trunk   ViT 최종 출력 하나.  (B, 1024, 72, 72)
  vb      vision_backbone 전체 = trunk + 넥(convs).
          (B, 256, 288/144/72/36, ...) 네 레벨.
          단, trunk 가 평면 ViT(32블록 전부 72x72)라 288 레벨은 입력을 더 곱게
          처리한 결과가 아니라 72x72 를 넥이 키운 것이다. 공간 해상도 상한은
          여전히 stride 14 다. 그래도 SAM3 가 마스크에 실제로 쓰는 특징이다.
  blocks  trunk 중간 블록 4개(8/16/24/31). 해상도는 같고 추상화 수준이 다르다.
          margin 같은 저수준 기하 정보는 얕은 층에 더 남아 있다.
          ★ 이 출력은 (N,H,W,C) 채널 마지막이라 여기서 (N,C,H,W) 로 뒤집는다.

풀링 (--pool)
  gap        전역 평균. 경계에만 있는 정보가 배경에 희석된다.
  gapmax     평균 + 최댓값. 실측에서 오히려 나빴다(잡음 극값을 집는다).
  grid --grid N   NxN 격자 평균. 위치를 남긴다. 실측에서 유일하게 이득이 났다.

검증 (--val)
  train 에서 검증셋을 떼어 에폭 선택에 쓴다. 테스트는 선택에 관여하지 않는다.
  캐시 경로는 같은 사진의 4가지 뒤집기가 train/val 로 갈리면 누수이므로 원본
  사진 단위로 쪼갠다. LoRA 경로는 사진 한 장이 행 하나라 행 단위로 갈라도 되며,
  검증 쪽은 증강을 끈 별도 인스턴스를 쓴다. --val 0 으로 끄면 테스트로 고르지만,
  그 숫자는 낙관 편향이 섞이므로 보고용으로 쓰면 안 된다.

실측 결론 (2026-08, mass)
  풀링   grid4 > grid2 > gap > gapmax.  공간 해상도가 유일하게 작동한 축이다.
  출처   trunk > 중간블록 = 넥.  넥은 1024->256 압축이라 분류에 불리하다.
  전처리 정사각 패딩은 margin 을 깎고 finding 을 올리는 맞교환 — 채택하지 않는다.
         백분위 절단은 중립. 원리상 타당해 유지하되 개선 근거로 쓰면 안 된다.
  한계   일곱 구성의 테스트 F1 이 0.508~0.542 안에 전부 들어간다. 동결 특징을
         요약하는 방식으로는 여기까지다. 다음은 특징 자체를 바꾸는 LoRA 다.

지표
  F1    이진 라벨 micro-F1 (임계값 0.5).
  top1  축마다 확률 최고 클래스가 정답에 포함되는 비율.
        규칙표 mammo-v1.0 이 받는 값이 축별 서술어 하나이므로 이쪽이 파이프라인
        성능에 직결된다.

전처리 (--no-pad / --clip)
  check_preproc.py 실측 근거는 mammo_data.py 머리말에 있다.
  ★ 정사각 패딩은 실측에서 손해였다 — margin -0.016, finding +0.016 의 맞교환이다.
    규칙표가 세 축을 다 쓰고 SPICULATED 가 의심도를 결정하므로 margin 을 지킨다.
    기본값은 여전히 켬이니 --no-pad 를 명시해야 한다.
  전처리는 캐시 키에 들어가므로 서로 다른 설정의 특징이 섞이지 않는다.

사용
  # 확정 구성 — 헤드만 (30초, 캐시 재사용 시)
  python3 -u train_mammo.py --kind mass --cache --no-pad --pool grid --grid 4

  # 구조 비교용
  python3 -u train_mammo.py --kind mass --cache --no-pad --src vb     --levels all --pool grid --grid 2
  python3 -u train_mammo.py --kind mass --cache --no-pad --src blocks --levels all --pool gap

  # LoRA — 캐시 불가, 에폭당 수 분. 배경에서 돌려라
  nohup python3 -u train_mammo.py --kind mass --epochs 15 --lora --no-pad \
      --pool grid --grid 4 --batch 2 > lora.log 2>&1 &
"""

import argparse, json, sys, time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as TF
from torch.utils.data import DataLoader, TensorDataset, Subset

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import (BASE_CFG, BASE_CKPT, CKPT as OUT_DIR, LABELS, MEDSAM3,
                   ROI_INDEX, medsam3_cwd)

# 재배치 전에는 이 파일이 mammo/ 에 있었고 거기에 sam3 · merge_medsam3 링크가
# 있어서 그냥 import 됐다. 지금은 training/code/ 이므로 명시적으로 붙인다.
if str(MEDSAM3) not in sys.path:
    sys.path.insert(0, str(MEDSAM3.resolve()))

from merge_medsam3 import load_merged_model                      # noqa: E402
from lora_layers import LoRALinear                               # noqa: E402
from mammo_data import (make_datasets, load_schema, label_columns,  # noqa: E402
                        axis_slices, MammoROIDataset)

# 주의: 이 컨테이너는 /dev/shm 이 64MB 다.
# file_system 전략도 결국 shm 을 쓰므로 워커를 띄우면 죽는다.
# --workers 0 이 기본값이며, 그대로 두는 것을 권한다.

INDEX_DIR = ROI_INDEX
SCHEMA = LABELS / "labels" / "label_schema.json"

# 상대경로였다. mammo/ 에서 실행할 때만 맞았고, 산출물이 공유 저장소
# (MedSAM3/ckpt) 에 저장되는 부작용도 있었다. 절대경로로 고정한다.
CKPT = str(BASE_CKPT)
CFG = str(BASE_CFG)

FLIPS = [(False, False), (True, False), (False, True), (True, True)]
BLOCK_PICKS = [8, 16, 24, 31]


# ────────────────────────── 특징 추출기 ──────────────────────────
def as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else [x]


def normalize_out(o):
    """vision_backbone 은 (list, list, None, None) 을 돌려준다. 앞의 리스트만 쓴다."""
    if isinstance(o, tuple) and len(o) and isinstance(o[0], (list, tuple)):
        o = o[0]
    return as_list(o)


class FeatExtractor(nn.Module):
    def __init__(self, vb, src):
        super().__init__()
        self.src = src
        self.net = vb if src == "vb" else vb.trunk

    def forward(self, x):
        if self.src != "blocks":
            return [t for t in normalize_out(self.net(x)) if torch.is_tensor(t)]

        grabbed = {}
        hs = [self.net.blocks[i].register_forward_hook(
                  lambda m, inp, o, i=i: grabbed.__setitem__(i, o))
              for i in BLOCK_PICKS]
        try:
            self.net(x)
        finally:
            for h in hs:
                h.remove()
        # (N,H,W,C) -> (N,C,H,W). 넥 출력과 축 순서를 맞춰야 풀링이 맞는다.
        return [grabbed[i].permute(0, 3, 1, 2) for i in BLOCK_PICKS if i in grabbed]


# ────────────────────────────── 풀링 ──────────────────────────────
def pool_feats(fs, mode, levels, grid=2):
    if levels == "last":
        fs = fs[-1:]
    vecs = []
    for f in fs:
        f = f.float()
        if f.dim() == 3:                       # (B, N, C) 토큰 형태
            vecs.append(f.mean(dim=1))
            continue
        if f.dim() != 4:
            continue
        if mode == "gap":
            vecs.append(f.mean(dim=(2, 3)))
        elif mode == "gapmax":
            vecs.append(f.mean(dim=(2, 3)))
            vecs.append(f.amax(dim=(2, 3)))
        elif mode == "grid":
            vecs.append(TF.adaptive_avg_pool2d(f, grid).flatten(1))
        else:
            raise ValueError(f"모르는 풀링: {mode}")
    return torch.cat(vecs, dim=1)


def report_levels(fs, mode, levels, grid):
    print("    특징 레벨:")
    for i, f in enumerate(fs):
        print(f"      [{i}] {tuple(f.shape)}")
    d = pool_feats(fs, mode, levels, grid).shape[1]
    print(f"    levels={levels}  pool={mode}"
          f"{f'({grid}x{grid})' if mode == 'grid' else ''}  ->  특징 {d}차원")
    return d


# ────────────────────────────── 모델 ──────────────────────────────
def make_head(n_out, feat_dim, hidden=512, dropout=0.2):
    return nn.Sequential(
        nn.LayerNorm(feat_dim),
        nn.Linear(feat_dim, hidden),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(hidden, n_out),
    )


class DescriptorNet(nn.Module):
    """추출기 + 헤드. 캐시를 안 쓰는 경로(LoRA)에서만 쓴다."""

    def __init__(self, ext, head, pool, levels, grid):
        super().__init__()
        self.ext, self.head = ext, head
        self.pool, self.levels, self.grid = pool, levels, grid

    def forward(self, x):
        return self.head(pool_feats(self.ext(x), self.pool, self.levels, self.grid))


def inject_lora(module, rank, alpha, targets):
    n = 0
    for name, child in list(module.named_modules()):
        if isinstance(child, nn.Linear) and name.split(".")[-1] in targets:
            *parent_path, attr = name.split(".")
            parent = module
            for p in parent_path:
                parent = getattr(parent, p)
            setattr(parent, attr, LoRALinear(child, rank=rank, alpha=alpha, dropout=0.0))
            n += 1
    return n


# ────────────────────────── 특징 캐시 ──────────────────────────
@torch.no_grad()
def extract_features(ext, ds, batch, device, flips, pool, levels, grid, tag=""):
    """
    DICOM 을 한 번만 읽어 풀링 특징을 만든다. 백본이 동결이라 매 에폭 동일하다.
    원본 사진 번호(idx)와 뒤집기 번호(flip)를 같이 저장한다 — 검증셋을 사진
    단위로 갈라야 누수가 없기 때문이다.
    """
    ext.eval()
    ds.augment = False
    loader = DataLoader(ds, batch_size=batch, shuffle=False,
                        num_workers=0, pin_memory=True)

    feats, labels, idxs, fids = [], [], [], []
    t0, seen, shown = time.time(), 0, False
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        bs = x.size(0)
        for fi, (h, v) in enumerate(flips):
            xf = x
            if h:
                xf = torch.flip(xf, dims=[3])
            if v:
                xf = torch.flip(xf, dims=[2])
            with torch.autocast("cuda", dtype=torch.bfloat16):
                fs = ext(xf)
            if not shown:
                report_levels(fs, pool, levels, grid)
                shown = True
            feats.append(pool_feats(fs, pool, levels, grid).cpu())
            labels.append(y)
            idxs.append(torch.arange(seen, seen + bs))
            fids.append(torch.full((bs,), fi, dtype=torch.long))
        seen += bs
        el = time.time() - t0
        eta = el / max(seen, 1) * (len(ds) - seen)
        print(f"\r    {tag} {seen}/{len(ds)}   {el:.0f}s 경과 · 남은 {eta:.0f}s   ",
              end="", flush=True)
    print()
    return (torch.cat(feats), torch.cat(labels),
            torch.cat(idxs), torch.cat(fids))


def cached_split(ext, ds, batch, device, flips, pool, levels, grid, path, tag):
    if path.exists():
        d = torch.load(path, map_location="cpu")
        if "idx" not in d:
            sys.exit(f"{path.name} 은 구버전 캐시라 사진 번호가 없다. "
                     f"--recache 로 다시 뽑아라.")
        print(f"    {tag} 캐시 재사용 {tuple(d['x'].shape)}  ({path.name})")
        return d["x"], d["y"], d["idx"], d["flip"]
    x, y, i, f = extract_features(ext, ds, batch, device, flips,
                                  pool, levels, grid, tag=tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pt.tmp")     # 원자적 저장 — 중간에 죽어도 반쪽 캐시가 안 남는다
    torch.save({"x": x, "y": y, "idx": i, "flip": f}, tmp)
    tmp.replace(path)
    print(f"    {tag} 저장 {tuple(x.shape)}  ->  {path}")
    return x, y, i, f


# ────────────────────────────── 평가 ──────────────────────────────
def _prf(p, t):
    # float() 로 감싸는 이유: p.sum() 은 numpy float32 라 그대로 두면 지표가
    # numpy 스칼라가 되고, 체크포인트에 섞여 들어가 torch.load 의
    # weights_only=True (2.6 기본값) 에 걸린다.
    tp = float((p * t).sum())
    prec = tp / (float(p.sum()) + 1e-8)
    rec = tp / (float(t.sum()) + 1e-8)
    return prec, rec, 2 * prec * rec / (prec + rec + 1e-8)


def _top1(P, Y, a, b):
    sp, sy = P[:, a:b], Y[:, a:b]
    has = sy.sum(1) > 0
    n = int(has.sum())
    if n == 0:
        return float("nan")
    idx = sp[has].argmax(1)
    return float(sy[has][np.arange(n), idx].mean())


@torch.no_grad()
def evaluate(model, loader, device, slices, thr=0.5):
    model.eval()
    P, Y = [], []
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logit = model(x)
        P.append(torch.sigmoid(logit.float()).cpu())
        Y.append(y)
    P, Y = torch.cat(P).numpy(), torch.cat(Y).numpy()
    pred = (P >= thr).astype(np.float32)

    f1 = {"overall": _prf(pred, Y)}
    top1 = {}
    for ax, (a, b) in slices.items():
        f1[ax] = _prf(pred[:, a:b], Y[:, a:b])
        top1[ax] = _top1(P, Y, a, b)
    vals = [v for v in top1.values() if v == v]
    top1["mean"] = float(np.mean(vals)) if vals else float("nan")
    return f1, top1


def fmt(f1, top1):
    a = "  ".join(f"{k} {v[2]:.3f}" for k, v in f1.items())
    b = "  ".join(f"{k} {v:.3f}" for k, v in top1.items())
    return f"F1[{a}]  top1[{b}]"


def score_of(f1, top1, how):
    return f1["overall"][2] if how == "f1" else top1["mean"]


def show_pos_weight(cols, slices, pos, pw, pw_max):
    """
    어떤 서술어가 가중치 상한에 눌려 있는지 보인다.

    희소 클래스의 이론 가중치 (1-p)/p 는 상한을 넘으면 잘린다. 잘린 만큼
    그 클래스는 손실에서 과소평가되고, 모델은 그 서술어를 고를 이유가 줄어든다.
    종단 평가의 '한 번도 못 내는 등급' 이 데이터 부족 때문인지 손실 설정
    때문인지, 그 구분을 여기서 먼저 볼 수 있다.
    """
    raw = (1 - pos) / (pos + 1e-6)
    clipped = [i for i in range(len(cols)) if float(raw[i]) > pw_max]
    print(f"    pos_weight  상한 {pw_max:g}  ·  적용 범위 "
          f"{float(pw.min()):.2f} ~ {float(pw.max()):.2f}")
    if not clipped:
        print("    상한에 걸린 클래스 없음 — 모든 클래스가 이론 가중치대로 학습된다")
        return
    print(f"    ! 상한에 걸린 클래스 {len(clipped)}개 — 손실에서 과소평가되고 있다")
    print(f"      {'서술어':<30s}{'유병률':>9s}{'이론':>9s}{'적용':>8s}   축")
    for i in sorted(clipped, key=lambda j: float(pos[j])):
        ax = next((k for k, (s, e) in slices.items() if s <= i < e), "?")
        print(f"      {cols[i][:29]:<30s}{100*float(pos[i]):8.2f}%"
              f"{float(raw[i]):9.1f}{float(pw[i]):8.1f}   {ax}")


# ────────────────────────────── main ──────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["mass", "calc"], required=True)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--workers", type=int, default=0,
                    help="0 을 유지하라. /dev/shm 이 64MB 라 워커를 띄우면 죽는다")
    ap.add_argument("--size", type=int, default=1008)
    ap.add_argument("--ckpt", default=CKPT,
                    help="병합본 경로. alpha 스윕처럼 백본을 갈아끼울 때 쓴다. "
                         "구조(rank·target_modules)가 같아야 하므로 CFG 는 그대로 둔다")
    ap.add_argument("--no-pad", action="store_true",
                    help="정사각 패딩을 끄고 예전처럼 비율을 뭉갠다 (비교용)")
    ap.add_argument("--clip", type=float, default=99.9,
                    help="[100-p, p] 백분위 절단 후 정규화. 0 이면 순수 min-max")
    ap.add_argument("--src", choices=["trunk", "vb", "blocks"], default="trunk")
    ap.add_argument("--pool", choices=["gap", "gapmax", "grid"], default="grid")
    ap.add_argument("--grid", type=int, default=2)
    ap.add_argument("--levels", choices=["last", "all"], default="last")
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--val", type=float, default=0.15,
                    help="train 에서 뗄 검증 비율. 0 이면 테스트로 고른다(편향 주의)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cache", action="store_true")
    ap.add_argument("--recache", action="store_true")
    ap.add_argument("--head-batch", type=int, default=64)
    ap.add_argument("--select", choices=["f1", "top1"], default="f1")
    ap.add_argument("--lora", action="store_true")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--lora-lr", type=float, default=None,
                    help="백본 LoRA 전용 학습률. 생략하면 --lr 과 같다. "
                         "헤드에 맞춘 값을 사전학습 백본에 그대로 쓰면 대개 과하다")
    ap.add_argument("--init-head", default=None,
                    help="동결 특징으로 먼저 학습한 헤드 체크포인트를 초기값으로. "
                         "특징 공간과 헤드가 서로를 쫓는 상태를 피한다")
    ap.add_argument("--pw-max", type=float, default=20.0,
                    help="BCE pos_weight 상한. 기본 20 은 유병률 4.8%% 아래를 전부 "
                         "같은 값으로 눌러버린다. 희소 서술어가 안 뽑히는 것이 "
                         "데이터 부족 때문인지 이 상한 때문인지 가르려면 올려본다. "
                         "20 이 아니면 체크포인트 이름에 _pw 가 붙어 기준선을 안 덮는다")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.cache and a.lora:
        sys.exit("--cache 와 --lora 는 같이 못 쓴다. LoRA 는 백본이 매 스텝 바뀌므로 "
                 "특징을 고정할 수 없다.")

    device = "cuda"
    schema = load_schema(SCHEMA)
    cols = label_columns(schema, a.kind)
    slices = axis_slices(schema, a.kind)
    n_out = len(cols)
    ptag = f"{a.pool}{a.grid}" if a.pool == "grid" else a.pool
    pad = not a.no_pad
    # 전처리도 캐시 키에 넣는다. 다른 전처리로 뽑은 특징이 섞이면 안 된다.
    dtag = f"pad{int(pad)}_clip{'0' if not a.clip else str(a.clip).replace('.','')}"
    # 백본이 다르면 특징도 다르다. 캐시 키에 반드시 넣어야 섞이지 않는다.
    stem = Path(a.ckpt).stem
    ctag = "" if stem == Path(CKPT).stem else "_" + stem.replace(Path(CKPT).stem, "").lstrip("_")
    tag = f"{a.src}_{a.levels}_{ptag}_{dtag}{ctag}"

    print(f"■ {a.kind}  출력 {n_out}차원   src={a.src} levels={a.levels} pool={ptag}")
    print(f"    전처리  정사각패딩={'켬' if pad else '끔'}  "
          f"백분위절단={a.clip if a.clip else '끔(순수 min-max)'}")
    print(f"    백본    {a.ckpt}")
    for ax, (s, e) in slices.items():
        print(f"    {ax:9s} {e-s}개  {schema['axes'][ax]}")

    print("\n■ 데이터")
    tr_ds, te_ds = make_datasets(INDEX_DIR, SCHEMA, a.kind, size=a.size,
                                 pad_square=pad, clip_pct=a.clip)
    print(f"    train {len(tr_ds)}  ·  test {len(te_ds)}")

    print("\n■ 백본 로드")
    # SAM 3 의 토크나이저가 자산을 상대경로로 찾는다. 모델을 세우는 동안만
    # MedSAM3 저장소를 cwd 로 둔다. 블록을 나오면 원위치한다.
    with medsam3_cwd():
        full = load_merged_model(a.ckpt, CFG, device=device)
    vb = full.backbone.vision_backbone
    del full
    for p in vb.parameters():
        p.requires_grad = False
    ext = FeatExtractor(vb, a.src)

    # 손실 상한은 특징과 무관하므로 캐시 키(tag)에는 넣지 않는다.
    # 다만 결과물은 달라지므로 체크포인트 이름에는 넣어 기준선을 안 덮게 한다.
    wtag = "" if a.pw_max == 20.0 else f"_pw{a.pw_max:g}"
    out_path = Path(a.out) if a.out else (
        OUT_DIR / f"mammo_{a.kind}_{tag}"
                  f"{'_lora' if a.lora else '_head'}{wtag}.pt")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 경로 1: 특징 캐시 + 헤드만 ────────────────────────────────
    if a.cache:
        print("\n■ 특징 추출 (한 번만)")
        cdir = OUT_DIR / "feat"
        ctr = cdir / f"{a.kind}_train_{a.size}_{tag}_x{len(FLIPS)}.pt"
        cte = cdir / f"{a.kind}_test_{a.size}_{tag}.pt"
        if a.recache:
            for p in (ctr, cte):
                p.unlink(missing_ok=True)

        Xtr, Ytr, Itr, Ftr = cached_split(ext, tr_ds, a.batch, device, FLIPS,
                                          a.pool, a.levels, a.grid, ctr, "train")
        Xte, Yte, _, _ = cached_split(ext, te_ds, a.batch, device, [FLIPS[0]],
                                      a.pool, a.levels, a.grid, cte, "test")
        del ext, vb
        torch.cuda.empty_cache()

        # 검증셋은 원본 사진 단위로 가른다 (뒤집기 누수 방지)
        I = Itr.numpy()
        if a.val > 0:
            uniq = np.unique(I)
            rng = np.random.RandomState(a.seed)
            perm = rng.permutation(uniq)
            n_val = max(1, int(round(len(uniq) * a.val)))
            val_ids = set(perm[:n_val].tolist())
            is_val = np.array([i in val_ids for i in I])
            m_tr = torch.from_numpy(~is_val)
            # 검증은 원본만 쓴다 — 테스트와 동일 조건으로 재야 비교가 성립한다
            m_va = torch.from_numpy(is_val & (Ftr.numpy() == 0))
            Xva, Yva = Xtr[m_va], Ytr[m_va]
            Xtr, Ytr = Xtr[m_tr], Ytr[m_tr]
            print(f"    사진 {len(uniq)}장 -> 학습 {len(uniq)-n_val} / 검증 {n_val}")
        else:
            Xva = Yva = None
            print("    ! --val 0 : 테스트로 에폭을 고른다. 이 수치는 보고용으로 쓰지 마라")

        feat_dim = Xtr.shape[1]
        head = make_head(n_out, feat_dim, a.hidden, a.dropout).to(device)
        tr = DataLoader(TensorDataset(Xtr, Ytr), batch_size=a.head_batch,
                        shuffle=True, num_workers=0, drop_last=True)
        te = DataLoader(TensorDataset(Xte, Yte), batch_size=256, num_workers=0)
        va = (DataLoader(TensorDataset(Xva, Yva), batch_size=256, num_workers=0)
              if Xva is not None else None)
        model = head
        print(f"    학습 표본 {len(Xtr)}  검증 {0 if Xva is None else len(Xva)}  "
              f"테스트 {len(Xte)}   특징 {feat_dim}차원")
        pos = Ytr.mean(0)

    # ── 경로 2: 이미지에서 매번 forward (LoRA 학습용) ─────────────
    else:
        if a.lora:
            n = inject_lora(ext.net, a.rank, a.alpha, {"qkv", "proj", "fc1", "fc2"})
            # LoRALinear 가 새로 만드는 lora_A / lora_B 는 기본이 CPU 다.
            # 이미 GPU 에 올라간 trunk 안에 꽂히므로 여기서 장치를 다시 맞춰야 한다.
            # 빠뜨리면 forward 에서 "mat2 is on cpu" 로 죽는다.
            ext = ext.to(device)
            for name, p in ext.named_parameters():
                if "lora_A" in name or "lora_B" in name:
                    p.requires_grad = True
            print(f"    LoRA 주입 {n}개 층 (rank {a.rank} alpha {a.alpha})")

        with torch.no_grad():
            d = torch.zeros(1, 3, a.size, a.size, device=device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                feat_dim = report_levels(ext(d), a.pool, a.levels, a.grid)
            del d
        torch.cuda.empty_cache()

        head = make_head(n_out, feat_dim, a.hidden, a.dropout).to(device)
        te = DataLoader(te_ds, batch_size=a.batch, num_workers=a.workers,
                        pin_memory=True)
        model = DescriptorNet(ext, head, a.pool, a.levels, a.grid).to(device)

        if a.val > 0:
            # 이 경로는 사진 한 장이 행 하나다(증강은 매번 무작위) — 행 단위로 갈라도
            # 뒤집기 누수가 없다. 다만 검증은 증강을 꺼야 테스트와 조건이 같다.
            va_ds = MammoROIDataset(
                Path(INDEX_DIR) / f"roi_index_{a.kind}_train.csv", SCHEMA, a.kind,
                size=a.size, augment=False, pad_square=pad, clip_pct=a.clip)
            order = np.random.RandomState(a.seed).permutation(len(tr_ds))
            n_val = max(1, int(round(len(order) * a.val)))
            vi, ti = order[:n_val], order[n_val:]
            tr = DataLoader(Subset(tr_ds, ti.tolist()), batch_size=a.batch,
                            shuffle=True, num_workers=a.workers, pin_memory=True,
                            drop_last=True)
            va = DataLoader(Subset(va_ds, vi.tolist()), batch_size=a.batch,
                            num_workers=a.workers, pin_memory=True)
            pos = torch.tensor(tr_ds.df[cols].values[ti],
                               dtype=torch.float32).mean(0)
            print(f"    사진 {len(order)}장 -> 학습 {len(ti)} / 검증 {len(vi)}")
        else:
            tr = DataLoader(tr_ds, batch_size=a.batch, shuffle=True,
                            num_workers=a.workers, pin_memory=True, drop_last=True)
            va = None
            pos = torch.tensor(tr_ds.df[cols].values, dtype=torch.float32).mean(0)
            print("    ! --val 0 : 테스트로 에폭을 고른다. 이 수치는 보고용으로 쓰지 마라")

    if a.init_head:
        # 우리가 만든 파일이고 텐서 외에 지표·설정도 들어 있다.
        # 2.6 기본값 weights_only=True 로는 못 읽는다.
        d = torch.load(a.init_head, map_location="cpu", weights_only=False)
        if int(d.get("feat_dim", feat_dim)) != int(feat_dim):
            sys.exit(f"헤드 차원 불일치: 체크포인트 {d.get('feat_dim')} vs 현재 {feat_dim}. "
                     f"같은 --src/--levels/--pool/--grid 로 만든 헤드여야 한다.")
        head.load_state_dict(d["head"])
        print(f"    헤드 초기값 로드  {a.init_head}"
              f"  (ep {d.get('epoch')} · 테스트 F1 {d.get('test_f1', float('nan')):.4f})")

    trainable = [p for p in model.parameters() if p.requires_grad]
    n_tr = sum(p.numel() for p in trainable)
    n_all = sum(p.numel() for p in model.parameters())
    print(f"    학습 파라미터 {n_tr/1e6:.2f}M / 전체 {n_all/1e6:.1f}M "
          f"({100*n_tr/max(n_all,1):.2f}%)")

    pos_weight = ((1 - pos) / (pos + 1e-6)).clamp(0.5, a.pw_max).to(device)
    show_pos_weight(cols, slices, pos, pos_weight.detach().cpu(), a.pw_max)

    crit = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    # 백본 LoRA 와 헤드는 성격이 다르다. 헤드는 무작위에서 시작하지만 백본은
    # 이미 학습된 표현이라 같은 학습률을 주면 백본 쪽이 과하게 흔들린다.
    lora_p = [p for n, p in model.named_parameters()
              if p.requires_grad and "lora_" in n]
    other_p = [p for n, p in model.named_parameters()
               if p.requires_grad and "lora_" not in n]
    llr = a.lora_lr if a.lora_lr is not None else a.lr
    groups = [{"params": other_p, "lr": a.lr}]
    if lora_p:
        groups.append({"params": lora_p, "lr": llr})
        print(f"    학습률  헤드 {a.lr}  ·  LoRA {llr}")
    opt = torch.optim.AdamW(groups, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)

    print(f"\n■ 학습 시작  epochs {a.epochs}  lr {a.lr}  선택지표 {a.select}"
          f"{' (검증셋)' if va is not None else ' (테스트셋 — 편향)'}\n")
    best, best_ep, best_test = -1.0, 0, None
    for ep in range(1, a.epochs + 1):
        model.train()
        tot, nb, t0 = 0.0, 0, time.time()
        for x, y in tr:
            x = x.to(device, non_blocking=True)
            y = y.to(device, non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                loss = crit(model(x), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            opt.step()
            tot += loss.item(); nb += 1
        sched.step()

        tf1, ttop1 = evaluate(model, te, device, slices)
        if va is not None:
            vf1, vtop1 = evaluate(model, va, device, slices)
            sel = score_of(vf1, vtop1, a.select)
            line = (f"  ep {ep:3d}  loss {tot/max(nb,1):.4f}  "
                    f"val {sel:.3f}  test {fmt(tf1, ttop1)}")
        else:
            sel = score_of(tf1, ttop1, a.select)
            line = f"  ep {ep:3d}  loss {tot/max(nb,1):.4f}  test {fmt(tf1, ttop1)}"

        star = ""
        if sel > best:
            best, best_ep = sel, ep
            best_test = (tf1, ttop1)
            # 임시 파일에 쓰고 이름을 바꾼다. 제자리에 직접 쓰면 저장 도중
            # 죽었을 때 직전 체크포인트까지 깨진다. rename 은 같은 파일시스템에서
            # 원자적이라 중간 상태가 안 남는다.
            tmp_path = out_path.with_suffix(".pt.tmp")
            torch.save({
                "head": head.state_dict(),
                "lora": ({k: v for k, v in ext.state_dict().items()
                          if "lora_" in k} if a.lora else None),
                "kind": a.kind, "cols": cols, "epoch": int(ep),
                "val_score": float(sel),
                "test_f1": float(tf1["overall"][2]),
                "test_top1": float(ttop1["mean"]),
                "feat_dim": int(feat_dim), "args": vars(a),
            }, tmp_path)
            tmp_path.replace(out_path)
            star = "  *저장"
        print(line + star)

    print()
    if va is not None:
        print(f"검증 최고 {a.select} {best:.4f}  (ep {best_ep})")
        print(f"그 시점 테스트  {fmt(*best_test)}      <- 보고용")
    else:
        print(f"테스트 최고 {a.select} {best:.4f}  (ep {best_ep})  — 선택 편향 있음")
    print(f"마지막 에폭 테스트  {fmt(tf1, ttop1)}      <- 편향 없는 하한")
    print(f"-> {out_path}")


if __name__ == "__main__":
    main()
