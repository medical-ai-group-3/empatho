#!/usr/bin/env python
"""
초음파 파트와 같은 구조로 맘모 검출기를 세울 수 있는지 확인한다 — 학습 전에.

왜 확인부터인가
  초음파 파트는 학습 루프가 1,046줄이다. 그걸 맘모용으로 옮겨 쓴 뒤에
  모델이 안 세워지거나 배치가 안 흐르면 어디가 문제인지 찾기 어렵다.
  모르는 것만 먼저 확인한다.

무엇을 확인하나
  1. 병합본이 초음파 경로로 세워지는가      load_merged_model(분리형 체크포인트)
  2. LoRA 를 어디에 붙일 수 있는가          모델의 실제 선형 계층 이름을 센다
  3. LoRA 주입 후 학습 대상 비율            초음파 파트의 check_trainable 과 같은 검사
  4. 우리 타일 COCO 가 배치로 변환되는가    박스만 있고 마스크가 없다
  5. 순전파가 도는가                        출력 구조와 크기
  6. 손실이 계산되는가                      Boxes + IABCEMdetr (Masks 는 뺀다)

통합의 부수 효과
  이 경로는 medsam3_merged.pt(어텐션 분리형)를 쓴다. 지금 검출 학습이 쓰는
  _fused.pt 가 필요 없어진다 — 형식 불일치라는 버그 종류 자체가 사라진다.

무엇을 안 하나
  학습하지 않는다. 가중치를 저장하지 않는다. GPU 를 잠깐만 쓴다.

사용
  python3 probe_unified.py --list-modules          # 어디에 붙일 수 있는지만
  python3 probe_unified.py
  python3 probe_unified.py --res 1008 --n 2
"""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

try:
    from PIL import Image as PILImage
    from torchvision.transforms import v2
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from paths import BASE_CFG, BASE_CKPT, DATA, MEDSAM3  # noqa: E402

DEF_CKPT = BASE_CKPT                 # 분리형 — 초음파와 같은 파일
DEF_MERGE_CFG = BASE_CFG
DEF_COCO = DATA / "det_tile1008/annotations/train.json"
DEF_IMGS = DATA / "det_tile1008/images/train"


# ── 저장소 import — 초음파 파트의 함수를 그대로 쓴다 ────────────────────
def import_medsam3(repo_root):
    """
    저장소 코드가 상대경로를 하드코딩하므로 cwd 를 옮긴다.
    우리 경로는 전부 절대경로라 영향이 없다.
    """
    repo = str(Path(repo_root).resolve())
    if repo not in sys.path:
        sys.path.insert(0, repo)
    os.chdir(repo)

    from lora_layers import (LoRAConfig, apply_lora_to_model, count_parameters)
    from merge_medsam3 import load_merged_model
    from sam3.model.model_misc import SAM3Output
    from sam3.train.data.collator import collate_fn_api
    from sam3.train.data.sam3_image_dataset import (
        Datapoint, FindQueryLoaded, Image, InferenceMetadata, Object)
    from sam3.train.loss.loss_fns import CORE_LOSS_KEY, Boxes, IABCEMdetr
    from sam3.train.loss.sam3_loss import Sam3LossWrapper
    from sam3.train.matcher import (BinaryHungarianMatcherV2,
                                    BinaryOneToManyMatcher)

    # merge_medsam3 가 import 시점에 TF32 를 끈다(병합 검산용). 되돌린다.
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

    return dict(
        load_merged_model=load_merged_model, LoRAConfig=LoRAConfig,
        apply_lora_to_model=apply_lora_to_model, count_parameters=count_parameters,
        SAM3Output=SAM3Output,
        collate_fn_api=collate_fn_api, Datapoint=Datapoint,
        FindQueryLoaded=FindQueryLoaded, Image=Image,
        InferenceMetadata=InferenceMetadata, Object=Object,
        CORE_LOSS_KEY=CORE_LOSS_KEY, Boxes=Boxes, IABCEMdetr=IABCEMdetr,
        Sam3LossWrapper=Sam3LossWrapper,
        BinaryHungarianMatcherV2=BinaryHungarianMatcherV2,
        BinaryOneToManyMatcher=BinaryOneToManyMatcher,
    )


# ── 데이터 — 우리 타일 COCO 를 초음파 파트와 같은 형태로 ────────────────

class TileDataset:
    """
    det_tile 의 COCO 를 읽어 Datapoint 를 만든다.

    초음파와 다른 점 둘
      마스크가 없다     박스만 있다. segment=None 으로 두고 마스크 손실을 뺀다
      음성 타일이 있다  병변이 없는 타일이 절반이다. 그 타일에도 두 종류의
                        질의를 빈 정답으로 넣어야 '여기엔 없다' 를 배운다
    """

    def __init__(self, coco_path, img_dir, res, M, all_classes=True):
        d = json.loads(Path(coco_path).read_text())
        self.images = {im["id"]: im for im in d["images"]}
        self.ids = sorted(self.images)
        self.cats = {c["id"]: c["name"] for c in d["categories"]}
        self.by_img = defaultdict(list)
        for a in d["annotations"]:
            self.by_img[a["image_id"]].append(a)
        self.img_dir = Path(img_dir)
        self.res = res
        self.M = M
        self.all_classes = all_classes
        self.to_t = v2.Compose([v2.ToImage(),
                                v2.ToDtype(torch.float32, scale=True)])
        self.norm = v2.Normalize(mean=[0.5] * 3, std=[0.5] * 3)

        n_pos = sum(1 for i in self.ids if self.by_img.get(i))
        print(f"  영상 {len(self.ids):,}  (병변 있음 {n_pos:,} · 없음 "
              f"{len(self.ids)-n_pos:,})   범주 {self.cats}")

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, idx):
        M, R = self.M, self.res
        iid = self.ids[idx]
        info = self.images[iid]
        p = self.img_dir / info["file_name"]
        pil = PILImage.open(p).convert("RGB")
        ow, oh = pil.size
        if (ow, oh) != (R, R):
            pil = pil.resize((R, R), PILImage.BILINEAR)
        x = self.norm(self.to_t(pil))

        objects, names = [], []
        for i, an in enumerate(self.by_img.get(iid, [])):
            bx, by, bw, bh = an["bbox"]
            box = torch.tensor([(bx + bw / 2) / ow, (by + bh / 2) / oh,
                                bw / ow, bh / oh], dtype=torch.float32)
            objects.append(M["Object"](bbox=box, area=float(bw * bh / (ow * oh)),
                                       object_id=i, segment=None))
            names.append(self.cats.get(an["category_id"], "object").lower())

        image_obj = M["Image"](data=x, objects=objects, size=(R, R))

        by_class = defaultdict(list)
        for obj, nm in zip(objects, names):
            by_class[nm].append(obj.object_id)
        if self.all_classes:
            # 없는 종류도 빈 정답으로 넣는다 — '여기엔 없다' 도 가르쳐야 한다
            for nm in self.cats.values():
                by_class.setdefault(nm.lower(), [])

        meta = M["InferenceMetadata"](
            coco_image_id=iid, original_image_id=iid, original_category_id=0,
            original_size=(oh, ow), object_id=-1, frame_index=-1)
        queries = [M["FindQueryLoaded"](
            query_text=t, image_id=0, object_ids_output=ids,
            is_exhaustive=True, query_processing_order=0,
            inference_metadata=meta) for t, ids in by_class.items()]
        return M["Datapoint"](find_queries=queries, images=[image_obj])


# ── 모델 ─────────────────────────────────────────────────────────────────

def linear_suffixes(model, top=25):
    """LoRA 를 붙일 수 있는 선형 계층 이름을 센다 — 추측하지 않는다."""
    c = Counter()
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Linear) or type(mod).__name__.endswith("LoRA"):
            c[name.rsplit(".", 1)[-1]] += 1
    return c.most_common(top)


def patch_size(model):
    """패치 임베딩의 합성곱을 찾는다 — 커널과 보폭이 같고 큰 것."""
    for name, mod in model.named_modules():
        if isinstance(mod, torch.nn.Conv2d) and "patch" in name.lower() \
                and mod.kernel_size == mod.stride:
            return mod.kernel_size[0]
    for _, mod in model.named_modules():
        if isinstance(mod, torch.nn.Conv2d) and mod.kernel_size == mod.stride \
                and mod.kernel_size[0] >= 4:
            return mod.kernel_size[0]
    return None


def expected_res(model, verbose=True):
    """
    모델이 기대하는 입력 크기를 RoPE 표에서 읽는다.

    주의 — ViTDet 은 대부분의 블록에서 창 단위 어텐션을 쓴다. 그 블록의 표는
    창 크기(예: 14²=196)만 담는다. 영상 크기를 알려주는 것은 전역 어텐션
    블록의 표이고, 그것이 가장 크다. 그래서 최댓값을 쓴다.
    """
    sizes = Counter()
    for name, mod in model.named_modules():
        f = getattr(mod, "freqs_cis", None)
        if torch.is_tensor(f) and f.ndim >= 1 and "vision" in name:
            sizes[int(f.shape[0])] += 1
    if not sizes:
        return None
    if verbose:
        parts = []
        for t, k in sorted(sizes.items()):
            s = int(round(t ** 0.5))
            parts.append(f"{t}({s}²)×{k}블록" if s * s == t else f"{t}×{k}블록")
        print(f"    RoPE 표 크기   {' · '.join(parts)}")
        print("      작은 것은 창 단위 어텐션, 가장 큰 것이 전체 격자다")

    toks = max(sizes)
    side = int(round(toks ** 0.5))
    if side * side != toks:
        return None
    patch = patch_size(model)
    if patch is None:
        return None
    return toks, patch, side * patch


def build(a, M, device):
    print("\n[1] 병합본 로드 — 초음파와 같은 경로")
    ck = Path(a.ckpt).resolve()
    mc = Path(a.merge_cfg).resolve()
    for p in (ck, mc):
        if not p.exists():
            sys.exit(f"  ✗ 없다: {p}")
    print(f"    체크포인트 {ck.name}  {ck.stat().st_size/1e9:.2f}GB")
    print(f"    구조       {mc}")
    model = M["load_merged_model"](str(ck), str(mc), device=device)
    print(f"    {type(model).__name__}   "
          f"{sum(p.numel() for p in model.parameters())/1e6:.1f}M")

    # 회전 위치 부호화(RoPE) 표는 입력 크기 하나에 맞춰 미리 계산돼 있다.
    # 다른 크기를 넣으면 순전파 도중 assert 로 죽는다 — 추측하지 말고 표에서 읽는다.
    exp = expected_res(model)
    if exp:
        toks, patch, R = exp
        print(f"    RoPE 표 토큰 {toks} = {int(round(toks**0.5))}²  "
              f"패치 {patch}  →  기대 입력 {R}×{R}")
        if a.res != R:
            print(f"    ! --res {a.res} 가 아니라 {R} 이어야 한다. {R} 로 맞춘다.")
            a.res = R

    # eval_mode=True 로 병합되어 matcher 가 없다. 초음파 파트와 같은 처리.
    if getattr(model, "matcher", None) is None:
        model.matcher = M["BinaryHungarianMatcherV2"](
            focal=True, cost_class=2.0, cost_bbox=5.0, cost_giou=2.0,
            alpha=0.25, gamma=2, stable=False)
        print("    matcher 가 None 이라 직접 주입했다 (eval_mode 병합의 결과)")
    return model


def inject(a, model, M):
    print(f"\n[2] LoRA 주입  rank={a.rank} alpha={a.alpha}")
    tgt = [s.strip() for s in a.target_modules.split(",") if s.strip()]
    print(f"    대상 이름 {tgt}")
    print(f"    붙일 곳   vision={a.vision} text={a.text} "
          f"detr_enc={a.detr_enc} detr_dec={a.detr_dec} mask_dec={a.mask_dec}")
    model = M["apply_lora_to_model"](model, M["LoRAConfig"](
        rank=a.rank, alpha=a.alpha, dropout=a.dropout, target_modules=tgt,
        apply_to_vision_encoder=a.vision, apply_to_text_encoder=a.text,
        apply_to_geometry_encoder=False,
        apply_to_detr_encoder=a.detr_enc, apply_to_detr_decoder=a.detr_dec,
        apply_to_mask_decoder=a.mask_dec))
    return model


def check_trainable(model, M, lo, hi):
    c = M["count_parameters"](model)
    tot, tr = c["total_parameters"], c["trainable_parameters"]
    pct = c["trainable_percentage"]
    print("\n[3] 학습 대상")
    print(f"    전체      {tot:,}")
    print(f"    학습 대상 {tr:,}")
    print(f"    비율      {pct:.3f}%   (정상 범위 {lo}~{hi}%)")
    if not (lo <= pct <= hi):
        print("    ✗ 범위 밖이다. 동결이 안 됐거나 target_modules 가 안 맞는다.")
        return False
    print("    ✓ 동결된 본체 위에서 LoRA 만 학습된다")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(MEDSAM3))
    ap.add_argument("--ckpt", default=str(DEF_CKPT))
    ap.add_argument("--merge-cfg", default=str(DEF_MERGE_CFG))
    ap.add_argument("--coco", default=str(DEF_COCO))
    ap.add_argument("--images", default=str(DEF_IMGS))
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--n", type=int, default=2, help="배치 크기")
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--target-modules", default="q_proj,k_proj,v_proj,out_proj")
    ap.add_argument("--vision", type=int, default=1)
    ap.add_argument("--text", type=int, default=0)
    ap.add_argument("--detr-enc", type=int, default=1)
    ap.add_argument("--detr-dec", type=int, default=1)
    ap.add_argument("--mask-dec", type=int, default=0)
    ap.add_argument("--pct-lo", type=float, default=0.05)
    ap.add_argument("--pct-hi", type=float, default=5.0)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--list-modules", action="store_true",
                    help="붙일 수 있는 선형 계층 이름만 세고 끝낸다")
    a = ap.parse_args()

    print("=" * 76)
    print("초음파 파트와 같은 구조로 맘모 검출기를 세울 수 있나")
    print("=" * 76)

    coco_p, img_p = Path(a.coco).resolve(), Path(a.images).resolve()
    M = import_medsam3(a.repo)          # 여기서 cwd 가 바뀐다
    model = build(a, M, a.device)

    print("\n[2-0] 붙일 수 있는 선형 계층 (이름별 개수)")
    for nm, k in linear_suffixes(model):
        print(f"    {nm:28s} {k:5d}")
    if a.list_modules:
        print("\n  --list-modules 라 여기서 끝낸다. "
              "위 이름 중에서 --target-modules 를 고르면 된다.")
        return

    model = inject(a, model, M)
    ok = check_trainable(model, M, a.pct_lo, a.pct_hi)

    # 병합 경로가 일부 텐서를 다른 장치에 남길 수 있다. 섞이면 순전파 도중
    # '두 장치' 오류로 죽는데, 어디서 죽는지로는 원인을 알 수 없다. 미리 센다.
    print("\n[3-1] 장치 확인")
    model = model.to(torch.device(a.device))
    cen = Counter()
    for p in model.parameters():
        cen[str(p.device)] += 1
    for b in model.buffers():
        cen[str(b.device)] += 1
    for d, k in cen.most_common():
        print(f"    {d:12s} {k:6d}개")
    if len(cen) > 1:
        print("    ! 텐서가 두 장치에 나뉘어 있다 — 순전파가 실패한다")
        for nm, t in list(model.named_buffers()) + list(model.named_parameters()):
            if str(t.device) != str(torch.device(a.device)):
                print(f"      {nm}  →  {t.device}")
                break
    else:
        print(f"    ✓ 전부 {a.device}")

    # ── 데이터 ───────────────────────────────────────────────────────────
    print("\n[4] 타일 COCO 를 배치로")
    for p in (coco_p, img_p):
        if not p.exists():
            sys.exit(f"    ✗ 없다: {p}")
    ds = TileDataset(coco_p, img_p, a.res, M)

    # 병변 있는 타일과 없는 타일을 섞어 담는다 — 둘 다 흘러야 한다
    pos = [i for i in range(len(ds)) if ds.by_img.get(ds.ids[i])]
    neg = [i for i in range(len(ds)) if not ds.by_img.get(ds.ids[i])]
    take = (pos[:max(1, a.n // 2)] + neg[:a.n - max(1, a.n // 2)])[:a.n]
    print(f"    표본 {len(take)}장  (병변 있음 {sum(1 for i in take if i in set(pos))})")
    dps = [ds[i] for i in take]
    q = sum(len(d.find_queries) for d in dps)
    print(f"    질의 {q}개  "
          f"({', '.join(sorted({fq.query_text for d in dps for fq in d.find_queries}))})")

    # 마스크가 없으므로 with_seg_masks=False
    batch = M["collate_fn_api"](dps, dict_key="input", with_seg_masks=False)
    print("    collate_fn_api(with_seg_masks=False) 통과")

    # ── 순전파 ───────────────────────────────────────────────────────────
    print("\n[5] 순전파")
    dev = torch.device(a.device)

    def to_dev(o):
        if torch.is_tensor(o):
            return o.to(dev)
        if isinstance(o, (list, tuple)):
            return type(o)(to_dev(x) for x in o)
        if isinstance(o, dict):
            return {k: to_dev(v) for k, v in o.items()}
        if hasattr(o, "__dataclass_fields__"):
            for f in o.__dataclass_fields__:
                setattr(o, f, to_dev(getattr(o, f)))
            return o
        return o

    model.train()
    inp = to_dev(batch["input"])
    ib = getattr(inp, "img_batch", None)
    if torch.is_tensor(ib):
        print(f"    실제 입력 {tuple(ib.shape)}")
    try:
        out = model(inp)
    except Exception as e:
        print(f"    ✗ 실패: {type(e).__name__}: {e}")
        print("      해상도 불일치면 --res 를 바꿔봐라 (1008 / 1024)")
        raise
    last = out[-1] if isinstance(out, (list, tuple)) else out
    print(f"    출력 단계 {len(out) if isinstance(out,(list,tuple)) else 1}개")
    keys = list(last.keys()) if isinstance(last, dict) else \
        [f for f in getattr(last, "__dataclass_fields__", {})]
    print(f"    마지막 단계 항목 {keys}")
    for k in keys:
        v = last[k] if isinstance(last, dict) else getattr(last, k)
        if torch.is_tensor(v):
            print(f"      {k:26s} {tuple(v.shape)}")

    # ── 손실 ─────────────────────────────────────────────────────────────
    # 가중치와 인자는 초음파 파트 build_loss 를 그대로 쓴다. 임의로 정하면
    # 두 파트의 학습이 다른 조건이 되어 나중에 비교가 안 된다.
    # 다른 점 하나 — Masks 를 뺀다. 우리 타일에는 마스크 정답이 없다.
    print("\n[6] 손실 — Boxes + IABCEMdetr (Masks 는 뺀다, 마스크 정답이 없다)")
    try:
        lm = M["BinaryHungarianMatcherV2"](
            cost_class=2.0, cost_bbox=5.0, cost_giou=2.0, focal=True)
        crit = M["Sam3LossWrapper"](
            loss_fns_find=[
                M["Boxes"](weight_dict={"loss_bbox": 5.0, "loss_giou": 2.0}),
                M["IABCEMdetr"](
                    pos_weight=10.0,
                    weight_dict={"loss_ce": 20.0, "presence_loss": 20.0},
                    pos_focal=False, alpha=0.25, gamma=2,
                    use_presence=True, pad_n_queries=200, weak_loss=False),
            ],
            matcher=lm,
            o2m_matcher=M["BinaryOneToManyMatcher"](alpha=0.3, threshold=0.4, topk=4),
            o2m_weight=2.0,
            use_o2m_matcher_on_o2m_aux=False,
            normalization="local",
            normalize_by_valid_object_num=False,
        )

        # 정답을 모델 내부 형식으로 되돌리고, 단계마다 짝짓기를 채워 넣는다.
        targets = [model.back_convert(t) for t in inp.find_targets]
        for t in targets:
            for k, v in t.items():
                if torch.is_tensor(v):
                    t[k] = v.to(dev)
        SO = M["SAM3Output"]
        with SO.iteration_mode(out, iter_mode=SO.IterMode.ALL_STEPS_PER_STAGE) as it:
            for stage_out, stage_tgt in zip(it, targets):
                for o in stage_out:
                    o["indices"] = lm(o, stage_tgt)
                    for aux in o.get("aux_outputs", []):
                        aux["indices"] = lm(aux, stage_tgt)

        ld = crit(out, targets)
        core = M["CORE_LOSS_KEY"]
        for k, v in ld.items():
            if torch.is_tensor(v) and v.numel() == 1:
                mark = "  ← 역전파 대상" if k == core else ""
                print(f"    {str(k):32s} {float(v):10.4f}{mark}")
        print("    ✓ 손실이 계산된다 — 학습 루프를 짤 수 있다")
    except Exception as e:
        import traceback
        print(f"    ! 손실 구성 실패: {type(e).__name__}: {e}")
        traceback.print_exc()

    print("\n" + "=" * 76)
    print("판정")
    print("=" * 76)
    print(f"  모델 구성       {'통과' if model is not None else '실패'}")
    print(f"  학습 대상 비율  {'통과' if ok else '확인 필요'}")
    print("  배치 · 순전파   위 출력 참조")
    print()
    print("  전부 통과하면 학습 루프는 기계적인 작업이다.")
    print("  초음파 파트의 train_us_lora.py 를 골격으로 삼되")
    print("  분할 지표(Dice) 대신 FROC 을 쓰고, 마스크 손실을 뺀다.")


if __name__ == "__main__":
    main()
