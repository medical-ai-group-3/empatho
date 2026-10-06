#!/usr/bin/env python
"""
맘모 병변 검출 학습 — 초음파 파트와 같은 구조.

무엇이 초음파와 같나
  동결된 MedSAM3 병합본 위에 새 LoRA 만 학습한다. 저장소는 수정하지 않고
  import 로만 쓴다. 손실 구성과 가중치는 초음파 파트 build_loss 를 그대로
  옮겼다 — 임의로 정하면 두 파트가 다른 조건이 되어 비교가 안 된다.

무엇이 다른가
  마스크 정답이 없다      CBIS 타일은 박스만 있다. Masks 손실을 뺀다
  음성 타일이 절반이다     병변 없는 타일에도 두 종류 질의를 빈 정답으로 넣어
                          '여기엔 없다' 를 가르친다
  지표가 다르다           Dice 가 아니라 FROC 이다. 학습 중에는 손실만 보고,
                          FROC 은 eval_det_tiled.py 로 따로 잰다

왜 이 구조로 바꿨나
  기존 검출 학습은 838M 을 전부 학습했다. 학습 데이터가 2,220장인데 그건
  과하다. 이 구조는 11M(1.29%)만 학습한다.
  그리고 통합형 체크포인트(_fused.pt)가 필요 없어진다 — 어텐션 형식
  불일치라는 사고 종류 자체가 사라진다.

전제 (probe_unified.py 로 실측 확인)
  입력 1008x1008 · 패치 14 · 격자 72² · 질의 200개 · 학습 대상 1.287%

주의
  이 컨테이너의 /dev/shm 은 64MB 다. DataLoader 워커를 쓰면 배치를 넘기지
  못하고 조용히 멈춘다. num_workers 는 0 이어야 한다.

사용
  python3 train_mammo_det.py --check          # 두 배치만 돌려 확인
  python3 train_mammo_det.py --epochs 6
  python3 train_mammo_det.py --resume
"""

import argparse
import json
import math
import os
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import torch

try:
    from PIL import Image as PILImage
    from torch.utils.data import DataLoader, Dataset
    from torchvision.transforms import v2
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

import mammo_cfg                                                # noqa: E402
from paths import BASE_CFG, BASE_CKPT, DATA, MEDSAM3, TRAINING  # noqa: E402

DEF_DATA = DATA / "det_tile1008"
DEF_CKPT = BASE_CKPT
DEF_MERGE = BASE_CFG
OUT = TRAINING                       # ckpt/ 와 logs/ 는 초음파와 같은 자리다

RES = 1008          # probe 로 확인. 다르면 RoPE 표와 안 맞아 순전파가 죽는다
N_QUERIES = 200     # pred_boxes (B,200,4) 로 확인


# ── 로그 ─────────────────────────────────────────────────────────────────
class Tee:
    """
    셸 리다이렉트에 의존하지 않는다. `> train.log` 로 넘기면 다음 실행이
    이전 로그를 통째로 덮어쓴다 — 실제로 그렇게 에폭 0~3 기록을 잃었다.
    """

    def __init__(self, path):
        self.f = open(path, "a", buffering=1, encoding="utf-8")
        self.out = sys.stdout

    def write(self, s):
        self.out.write(s)
        self.f.write(s)

    def flush(self):
        self.out.flush()
        self.f.flush()


# ── 저장소 import — 초음파 파트와 같은 함수 ──────────────────────────────
def import_medsam3(repo_root):
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)

    from lora_layers import (LoRAConfig, apply_lora_to_model, count_parameters,
                             load_lora_weights, save_lora_weights)
    from merge_medsam3 import load_merged_model
    from sam3.model.model_misc import SAM3Output
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata, Object)
    from sam3.train.loss.loss_fns import CORE_LOSS_KEY, Boxes, IABCEMdetr
    from sam3.train.loss.sam3_loss import Sam3LossWrapper
    from sam3.train.matcher import (BinaryHungarianMatcherV2,
                                    BinaryOneToManyMatcher)

    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    return dict(
        load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
        apply_lora_to_model=apply_lora_to_model, count_parameters=count_parameters,
        save_lora_weights=save_lora_weights, load_lora_weights=load_lora_weights,
        SAM3Output=SAM3Output, collate_fn_api=collate_fn_api,
        Datapoint=Datapoint, FindQueryLoaded=FindQueryLoaded, Image=Image,
        InferenceMetadata=InferenceMetadata, Object=Object,
        CORE_LOSS_KEY=CORE_LOSS_KEY, Boxes=Boxes, IABCEMdetr=IABCEMdetr,
        Sam3LossWrapper=Sam3LossWrapper,
        BinaryHungarianMatcherV2=BinaryHungarianMatcherV2,
        BinaryOneToManyMatcher=BinaryOneToManyMatcher,
    )


# ── 데이터 ───────────────────────────────────────────────────────────────
class TileDataset(Dataset):
    """det_tile1008 의 COCO 를 Datapoint 로. 박스만 있고 마스크는 없다."""

    def __init__(self, root, split, M, res=RES, augment=False, seed=42):
        d = json.loads((Path(root) / "annotations" / f"{split}.json").read_text())
        self.images = {im["id"]: im for im in d["images"]}
        self.ids = sorted(self.images)
        self.cats = {c["id"]: c["name"] for c in d["categories"]}
        self.names = sorted({n.lower() for n in self.cats.values()})
        self.by_img = defaultdict(list)
        for a in d["annotations"]:
            self.by_img[a["image_id"]].append(a)
        self.dir = Path(root) / "images" / split
        self.res, self.M = res, M
        self.augment = augment
        self.rng = random.Random(seed)
        self.to_t = v2.Compose([v2.ToImage(),
                                v2.ToDtype(torch.float32, scale=True)])
        self.norm = v2.Normalize(mean=[0.5] * 3, std=[0.5] * 3)

        npos = sum(1 for i in self.ids if self.by_img.get(i))
        cnt = Counter(a["category_id"] for a in d["annotations"])
        print(f"  [{split}] 타일 {len(self.ids):,}  "
              f"(병변 있음 {npos:,} · 없음 {len(self.ids)-npos:,})")
        print(f"           병변 {len(d['annotations']):,}  "
              + " · ".join(f"{self.cats[c]} {k:,}" for c, k in sorted(cnt.items())))

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, idx):
        M, R = self.M, self.res
        iid = self.ids[idx]
        info = self.images[iid]
        pil = PILImage.open(self.dir / info["file_name"]).convert("RGB")
        ow, oh = pil.size
        if (ow, oh) != (R, R):
            pil = pil.resize((R, R), PILImage.BILINEAR)

        # 좌우 반전만 쓴다. 유방촬영은 좌우 유방을 같은 방식으로 찍으므로
        # 반전이 물리를 깨뜨리지 않는다. 상하 반전은 흉벽 위치를 바꾼다.
        flip = self.augment and self.rng.random() < 0.5
        if flip:
            pil = pil.transpose(PILImage.FLIP_LEFT_RIGHT)
        x = self.norm(self.to_t(pil))

        objects, names = [], []
        for i, an in enumerate(self.by_img.get(iid, [])):
            bx, by, bw, bh = an["bbox"]
            cx = (bx + bw / 2) / ow
            if flip:
                cx = 1.0 - cx
            box = torch.tensor([cx, (by + bh / 2) / oh, bw / ow, bh / oh],
                               dtype=torch.float32)
            objects.append(M["Object"](bbox=box, area=float(bw * bh / (ow * oh)),
                                       object_id=i, segment=None))
            names.append(self.cats.get(an["category_id"], "object").lower())

        image_obj = M["Image"](data=x, objects=objects, size=(R, R))

        by_class = defaultdict(list)
        for obj, nm in zip(objects, names):
            by_class[nm].append(obj.object_id)
        # 없는 종류도 빈 정답으로 넣는다 — '여기엔 없다' 를 가르쳐야
        # 오탐이 줄고 FROC 이 제대로 나온다
        for nm in self.names:
            by_class.setdefault(nm, [])

        meta = M["InferenceMetadata"](
            coco_image_id=iid, original_image_id=iid, original_category_id=0,
            original_size=(oh, ow), object_id=-1, frame_index=-1)
        queries = [M["FindQueryLoaded"](
            query_text=t, image_id=0, object_ids_output=ids,
            is_exhaustive=True, query_processing_order=0,
            inference_metadata=meta) for t, ids in sorted(by_class.items())]
        return M["Datapoint"](find_queries=queries, images=[image_obj])


def move(o, dev):
    if torch.is_tensor(o):
        return o.to(dev, non_blocking=True)
    if isinstance(o, (list, tuple)):
        return type(o)(move(x, dev) for x in o)
    if isinstance(o, dict):
        return {k: move(v, dev) for k, v in o.items()}
    if hasattr(o, "__dataclass_fields__"):
        for f in o.__dataclass_fields__:
            setattr(o, f, move(getattr(o, f), dev))
        return o
    return o


# ── 모델 ─────────────────────────────────────────────────────────────────
def build_model(a, M, dev):
    ck, mc = Path(a.ckpt).resolve(), Path(a.merge_cfg).resolve()
    for p in (ck, mc):
        if not p.exists():
            sys.exit(f"✗ 없다: {p}")
    print(f"\n[1/4] 병합본 로드  {ck.name}  {ck.stat().st_size/1e9:.2f}GB")
    model = M["load_merged_model"](str(ck), str(mc), device=dev)

    # eval_mode=True 로 병합되어 내부 matcher 가 비어 있다 (손실용과는 별개다)
    if getattr(model, "matcher", None) is None:
        model.matcher = M["BinaryHungarianMatcherV2"](
            focal=True, cost_class=2.0, cost_bbox=5.0, cost_giou=2.0,
            alpha=0.25, gamma=2, stable=False)
        print("      내부 matcher 주입")

    print(f"\n[2/4] LoRA 주입  rank={a.rank} alpha={a.alpha}")
    print("      MHA 교체 0건이 정상 — 병합본은 이미 그 구조다")
    tgt = [s.strip() for s in a.target_modules.split(",") if s.strip()]
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=a.rank, alpha=a.alpha, dropout=a.dropout, target_modules=tgt,
        apply_to_vision_encoder=bool(a.vision),
        apply_to_text_encoder=bool(a.text),
        apply_to_geometry_encoder=False,
        apply_to_detr_encoder=bool(a.detr_enc),
        apply_to_detr_decoder=bool(a.detr_dec),
        apply_to_mask_decoder=bool(a.mask_dec)))
    return model.to(dev)


def check_trainable(model, M, lo, hi):
    c = M["count_parameters"](model)
    pct = c["trainable_percentage"]
    print(f"\n[3/4] 학습 대상  {c['trainable_parameters']:,} / "
          f"{c['total_parameters']:,}  =  {pct:.3f}%   (정상 {lo}~{hi}%)")
    if not (lo <= pct <= hi):
        sys.exit("✗ 범위 밖이다. 동결이 안 됐거나 target_modules 가 안 맞는다.\n"
                 "  학습을 시작하지 않는다 — 몇 시간 뒤에 알아차리는 것보다 낫다.")
    print("      ✓ 동결된 본체 위에서 LoRA 만 학습된다")


def build_loss(M):
    """가중치는 초음파 파트 build_loss 그대로. Masks 만 뺀다."""
    matcher = M["BinaryHungarianMatcherV2"](
        cost_class=2.0, cost_bbox=5.0, cost_giou=2.0, focal=True)
    wrapper = M["Sam3LossWrapper"](
        loss_fns_find=[
            M["Boxes"](weight_dict={"loss_bbox": 5.0, "loss_giou": 2.0}),
            M["IABCEMdetr"](
                pos_weight=10.0,
                weight_dict={"loss_ce": 20.0, "presence_loss": 20.0},
                pos_focal=False, alpha=0.25, gamma=2,
                use_presence=True, pad_n_queries=N_QUERIES, weak_loss=False),
        ],
        matcher=matcher,
        o2m_matcher=M["BinaryOneToManyMatcher"](alpha=0.3, threshold=0.4, topk=4),
        o2m_weight=2.0,
        use_o2m_matcher_on_o2m_aux=False,
        normalization="local",
        normalize_by_valid_object_num=False,
    )
    return matcher, wrapper


def run_batch(model, matcher, wrapper, M, batch, dev, amp_dtype):
    inp = move(batch["input"], dev)
    with torch.autocast("cuda", dtype=amp_dtype):
        out = model(inp)
        targets = [model.back_convert(t) for t in inp.find_targets]
        for t in targets:
            for k, v in t.items():
                if torch.is_tensor(v):
                    t[k] = v.to(dev)
        SO = M["SAM3Output"]
        with SO.iteration_mode(out, iter_mode=SO.IterMode.ALL_STEPS_PER_STAGE) as it:
            for stage_out, stage_tgt in zip(it, targets):
                for o in stage_out:
                    o["indices"] = matcher(o, stage_tgt)
                    for aux in o.get("aux_outputs", []):
                        aux["indices"] = matcher(aux, stage_tgt)
        ld = wrapper(out, targets)
    return ld[M["CORE_LOSS_KEY"]], ld


# ── 학습 ─────────────────────────────────────────────────────────────────
def main():
    # 설정을 먼저 읽어 argparse 기본값을 덮는다. 명령줄이 우선한다.
    # 평가기와 같은 함수(mammo_cfg.lora_args)를 쓰므로 두 쪽이 어긋날 수 없다.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(mammo_cfg.DEFAULT))
    known, _ = pre.parse_known_args()
    CFG = mammo_cfg.load(known.config)

    ap = argparse.ArgumentParser(parents=[pre])
    ap.add_argument("--repo", default=str(MEDSAM3))
    ap.add_argument("--data", default=str(DEF_DATA))
    ap.add_argument("--ckpt", default=str(DEF_CKPT))
    ap.add_argument("--merge-cfg", default=str(DEF_MERGE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--wd", type=float, default=1e-4)
    ap.add_argument("--warmup", type=int, default=300, help="스텝")
    ap.add_argument("--clip", type=float, default=1.0)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--target-modules",
                    default="q_proj,k_proj,v_proj,out_proj,qkv,proj,fc1,fc2,"
                            "linear1,linear2")
    ap.add_argument("--vision", type=int, default=1)
    ap.add_argument("--text", type=int, default=0)
    ap.add_argument("--detr-enc", type=int, default=1)
    ap.add_argument("--detr-dec", type=int, default=1)
    ap.add_argument("--mask-dec", type=int, default=0)
    ap.add_argument("--pct-lo", type=float, default=0.05)
    ap.add_argument("--pct-hi", type=float, default=5.0)
    ap.add_argument("--amp", default="bf16", choices=["bf16", "fp16", "off"])
    ap.add_argument("--no-augment", action="store_true")
    ap.add_argument("--val-batches", type=int, default=200,
                    help="검증에 쓸 배치 수 (0=전체)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--accum", type=int, default=1,
                    help="기울기 누적. 배치를 쪼개도 유효 배치는 "
                         "batch×accum 로 유지된다")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--check", action="store_true", help="두 배치만 돌려 확인")
    # 설정에 있는 항목만 덮는다. 없으면 위의 기본값이 남는다.
    ap.set_defaults(**mammo_cfg.lora_args(CFG), **mammo_cfg.train_args(CFG))
    a = ap.parse_args()

    outdir = Path(a.out)
    (outdir / "ckpt").mkdir(parents=True, exist_ok=True)
    (outdir / "logs").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logp = outdir / "logs" / f"train_{stamp}.log"
    sys.stdout = Tee(logp)
    latest = outdir / "logs" / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(logp.name)
    except OSError:
        pass

    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)

    print("=" * 76)
    print("맘모 병변 검출 학습 — 동결 본체 + LoRA (초음파 파트와 같은 구조)")
    print("=" * 76)
    print(f"  로그  {logp}")
    mammo_cfg.show(CFG, known.config)
    print(f"  데이터 {a.data}")

    dev = torch.device("cuda")
    M = import_medsam3(a.repo)          # cwd 가 바뀐다. 경로는 전부 절대경로다
    model = build_model(a, M, dev)
    check_trainable(model, M, a.pct_lo, a.pct_hi)

    print("\n[4/4] 데이터")
    tr = TileDataset(a.data, "train", M, augment=not a.no_augment, seed=a.seed)
    va = TileDataset(a.data, "val", M, augment=False)

    def collate(b):
        return M["collate_fn_api"](list(b), dict_key="input",
                                   with_seg_masks=False)

    # num_workers=0 은 선택이 아니다 — /dev/shm 이 64MB 라 워커를 쓰면
    # 배치를 넘기지 못하고 오류 없이 멈춘다. 8시간을 그렇게 날린 적이 있다.
    dl_tr = DataLoader(tr, batch_size=a.batch, shuffle=True, num_workers=0,
                       collate_fn=collate, drop_last=True)
    dl_va = DataLoader(va, batch_size=a.batch, shuffle=False, num_workers=0,
                       collate_fn=collate)

    matcher, wrapper = build_loss(M)
    wrapper = wrapper.to(dev) if hasattr(wrapper, "to") else wrapper

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=a.wd)
    total_steps = max(1, a.epochs * len(dl_tr))
    amp_dtype = {"bf16": torch.bfloat16, "fp16": torch.float16}.get(a.amp)
    scaler = torch.amp.GradScaler("cuda", enabled=(a.amp == "fp16"))

    def lr_at(step):
        if step < a.warmup:
            return a.lr * (step + 1) / a.warmup
        t = (step - a.warmup) / max(1, total_steps - a.warmup)
        return a.lr * 0.5 * (1 + math.cos(math.pi * min(1.0, t)))

    start_ep, step = 0, 0
    state_p = outdir / "ckpt" / "last_state.pt"
    if a.resume and state_p.is_file():
        st = torch.load(state_p, map_location="cpu")
        M["load_lora_weights"](model, str(outdir / "ckpt" / "last_lora.pt"))
        opt.load_state_dict(st["opt"])
        start_ep, step = st["epoch"] + 1, st["step"]
        print(f"\n  이어받기 — 에폭 {start_ep} 부터, 스텝 {step:,}")

    # 누적을 쓰면 «갱신» 하나가 스텝 하나다. 학습률 일정도 갱신 기준으로
    # 잡아야 배치를 쪼개기 전과 같은 곡선을 그린다.
    accum = max(1, getattr(a, "accum", 1))
    if accum > 1:
        total_steps = max(1, total_steps // accum)
    print(f"\n  배치 {a.batch}×누적 {accum} (유효 {a.batch*accum}) · "
          f"에폭 {a.epochs} · 미니배치/에폭 {len(dl_tr):,} · "
          f"갱신/에폭 {len(dl_tr)//accum:,} · 총 갱신 {total_steps:,}")
    print(f"  lr {a.lr} · warmup {a.warmup} · AMP {a.amp}")

    if a.check:
        print("\n■ 확인 — 두 배치만")
        model.train()
        for i, b in enumerate(dl_tr):
            loss, ld = run_batch(model, matcher, wrapper, M, b, dev, amp_dtype)
            print(f"  배치 {i}  손실 {float(loss):.4f}")
            for k, v in ld.items():
                if torch.is_tensor(v) and v.numel() == 1:
                    print(f"    {str(k):30s} {float(v):9.4f}")
            loss.backward()
            g = sum(p.grad.abs().sum().item() for p in params
                    if p.grad is not None)
            print(f"    LoRA 기울기 절대합 {g:.4f}"
                  + ("   ✓ 흐른다" if g > 0 else "   ✗ 0 이다 — 확인 필요"))
            opt.zero_grad(set_to_none=True)
            if i >= 1:
                break
        print(f"\n  메모리 {torch.cuda.max_memory_allocated()/2**30:.1f}GB")
        print("  확인 완료. --check 를 빼고 돌려라.")
        return

    best = float("inf")
    for ep in range(start_ep, a.epochs):
        model.train()
        t0, run, seen = time.time(), 0.0, 0
        micro = 0                       # 이번 갱신에 모인 미니배치 수
        opt.zero_grad(set_to_none=True)  # 지난 에폭의 남은 조각을 버린다
        for i, b in enumerate(dl_tr):
            if micro == 0:
                # 학습률은 «갱신» 단위다. 누적 중에는 건드리지 않는다.
                for g in opt.param_groups:
                    g["lr"] = lr_at(step)
            loss, _ = run_batch(model, matcher, wrapper, M, b, dev, amp_dtype)
            if not torch.isfinite(loss):
                print(f"    ! 손실이 발산했다 (스텝 {step}) — "
                      f"모아 둔 {micro}개까지 버린다")
                opt.zero_grad(set_to_none=True)
                micro = 0
                continue
            # accum 으로 나눈다. 안 나누면 기울기가 accum 배가 되어
            # 사실상 학습률을 그만큼 올린 것이 된다.
            scaled = loss / accum
            if scaler.is_enabled():
                scaler.scale(scaled).backward()
            else:
                scaled.backward()
            run += float(loss)
            seen += 1
            micro += 1
            if micro < accum:
                continue                # 아직 모으는 중 — 갱신하지 않는다

            if scaler.is_enabled():
                scaler.unscale_(opt)
                torch.nn.utils.clip_grad_norm_(params, a.clip)
                scaler.step(opt)
                scaler.update()
            else:
                torch.nn.utils.clip_grad_norm_(params, a.clip)
                opt.step()
            opt.zero_grad(set_to_none=True)
            micro = 0
            step += 1
            # 갱신 50번마다 찍는다. i 로만 세면 누적 중인 자리에 걸려
            # 한 번도 안 찍히는 일이 생긴다.
            if (i + 1) % (50 * accum) == 0:
                el = time.time() - t0
                eta = el / max(1, i + 1) * (len(dl_tr) - i - 1)
                print(f"  에폭 {ep} [{i:5d}/{len(dl_tr)}] "
                      f"손실 {run/seen:8.3f}  lr {lr_at(step):.2e}  "
                      f"{el/60:5.1f}분 · 남은 {eta/60:5.1f}분  "
                      f"메모리 {torch.cuda.max_memory_allocated()/2**30:.1f}GB")

        # ── 검증 ─────────────────────────────────────────────────────
        model.eval()
        vs, vn = 0.0, 0
        with torch.no_grad():
            for j, b in enumerate(dl_va):
                if a.val_batches and j >= a.val_batches:
                    break
                l, _ = run_batch(model, matcher, wrapper, M, b, dev, amp_dtype)
                if torch.isfinite(l):
                    vs += float(l)
                    vn += 1
        vl = vs / max(1, vn)
        print(f"\n■ 에폭 {ep}  학습 {run/max(1,seen):.3f}  검증 {vl:.3f}  "
              f"({(time.time()-t0)/60:.1f}분)")

        # LoRA 만 저장한다 — 11M 이라 44MB 다. 전체 미세조정의 9.4GB 와 비교된다
        M["save_lora_weights"](model, str(outdir / "ckpt" / "last_lora.pt"))
        torch.save(dict(epoch=ep, step=step, opt=opt.state_dict(),
                        val=vl, args=vars(a)),
                   outdir / "ckpt" / "last_state.pt")
        if vl < best:
            best = vl
            M["save_lora_weights"](model, str(outdir / "ckpt" / "best_lora.pt"))
            print(f"  최고 검증 갱신 → best_lora.pt")

    print("\n" + "=" * 76)
    print("완료")
    print("=" * 76)
    print(f"  가중치  {outdir/'ckpt'}")
    print("  다음    eval_det_tiled.py 로 FROC 을 재고 기준선과 비교해라")
    print("          기준선  종괴 57.3% · 석회 18.6%  (오탐 1개/영상 · 중심 명중)")


if __name__ == "__main__":
    main()
