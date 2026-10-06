#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""병변/정상 이진 분류기 — 동결 백본 + 작은 헤드.

무엇을 하나
  검출 상자 자리를 오려낸 조각 하나를 받아 「병변인가 정상 조직인가」에
  답한다. 그 답으로 검출 점수를 다시 매기는 것이 목적이다.

왜 동결 백본인가
  LoRA 를 쓰면 백본이 매 스텝 바뀌어 특징을 캐시할 수 없다. 동결해 두면
  **특징을 한 번만 뽑고 헤드 학습은 몇 초**라, 설정을 여러 개 시험할 수 있다.
  먼저 이 값싼 판으로 「신호가 있기는 한가」를 확인하고, 있으면 그때
  LoRA 를 붙일지 정한다.

조각 만드는 법을 서빙과 맞춘다
  서술어 모델이 검출 상자에 여백 20화소를 붙여 오리고 모델 입력 크기로
  늘린다. 여기서도 **같은 방식**을 쓴다. 다르면 학습 때 본 그림과 실전에서
  받는 그림이 달라져, 검증 점수는 좋은데 재점수에는 안 통한다.

무엇을 보고 판단하나
  AUC 만 보면 안 된다. 실제로 쓰는 방식은 **검출 점수를 재조정하는 것**이라,
  분류기가 정탐과 오탐을 갈라 주는지가 핵심이다. 그래서 검증에서
    · AUC
    · 양성 상위 몇 %에 음성이 얼마나 섞이나
  를 같이 낸다. 최종 판단은 test 에서 FROC 가 같은 오탐 지점에서 오르는지다.

사용
  python3 training/code/train_binary.py --cache            # 특징 뽑고 학습
  python3 training/code/train_binary.py --cache --epochs 40 --lr 3e-4
"""

import argparse
import json
import sys
import time
from pathlib import Path

try:
    import cv2
    import numpy as np
    import torch
    import torch.nn as nn
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 저장소 뿌리를 스스로 찾는다. 작업 디렉터리가 어디든 상대 경로가 맞게
# 풀리도록 — 같은 실수를 세 번 했다.
ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)



# ── 다른 파일에서 가져오는 것들 ─────────────────────────────────────
def need(mod, *names):
    m = __import__(mod)
    miss = [n for n in names if not hasattr(m, n)]
    if miss:
        sys.exit(f"[중단] {mod} 에 {miss} 가 없다. 이름이 바뀌었으면 알려 달라.")
    return m


TM = need("train_mammo", "FeatExtractor", "pool_feats", "make_head")
E2 = need("eval_e2e", "build_model")

try:
    from eval_end2end import crop_to_tensor
except ImportError:
    sys.exit("[중단] eval_end2end.crop_to_tensor 를 못 가져왔다.")

# 여백 20화소로 넓히기 — 서술어 경로와 같은 함수를 쓴다.
_expand = None
for _mod in ("infer_mammo", "mammo_io", "eval_end2end"):
    try:
        _m = __import__(_mod)
        if hasattr(_m, "expand_box"):
            _expand = _m.expand_box
            print(f"  expand_box 를 {_mod} 에서 가져왔다")
            break
    except Exception:
        pass


def expand(box, margin, shape):
    """서빙과 같은 함수가 있으면 그것, 없으면 같은 규칙으로 직접."""
    if _expand is not None:
        return _expand(box, margin, shape)
    H, W = shape[:2]
    x0 = max(0, int(box[0] - margin)); y0 = max(0, int(box[1] - margin))
    x1 = min(W, int(box[2] + margin)); y1 = min(H, int(box[3] + margin))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return (x0, y0, x1, y1)


# ── 특징 뽑기 ──────────────────────────────────────────────────────
def _key(r, mode):
    """같은 바탕 그림을 연달아 읽지 않게 하는 열쇠."""
    return r["dcm"] if mode == "dcm" else r["file"]


def _load(r, root, mode):
    """조각을 뜰 바탕 그림.

    dcm 모드는 **조직 상자까지 잘라서** 돌려준다. 목록의 상자 좌표가 조직
    상자 기준이라 그래야 자리가 맞는다. 검출 파일과 같은 기준이다.
    """
    if mode == "dcm":
        import pydicom
        try:
            a16 = pydicom.dcmread(r["dcm"]).pixel_array
        except Exception:
            return None
        if a16.ndim != 2:
            return None
        cx0, cy0, w, h = r["crop"]
        return a16[cy0:cy0 + h, cx0:cx0 + w]
    img = cv2.imread(str(root / r["file"]), cv2.IMREAD_UNCHANGED)
    if img is not None and img.ndim == 3:
        img = img[:, :, 0]
    return img


@torch.no_grad()
def extract(rows, root, ext, a, dev, mode="tile"):
    """조각마다 특징 하나. 백본이 동결이라 한 번만 돌면 된다."""
    X, Y, keep = [], [], []
    cache_img, cache_name = None, None
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        k = _key(r, mode)
        if k != cache_name:
            cache_img = _load(r, root, mode)
            cache_name = k
        img = cache_img
        if img is None:
            continue
        e = expand(r["box"], a.margin, img.shape)
        if e is None:
            continue
        t = crop_to_tensor(img[e[1]:e[3], e[0]:e[2]], a.size, not a.no_pad, a.clip)
        X.append(t); Y.append(r["label"]); keep.append(i - 1)
        if len(X) >= a.batch or i == len(rows):
            xb = torch.stack(X[-len(X):]).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                f = TM.pool_feats(ext(xb), a.pool, a.levels, a.grid)
            yield f.float().cpu(), torch.tensor(Y[-len(X):], dtype=torch.float32)
            X = []
        if i % 200 == 0 or i == len(rows):
            el = time.time() - t0
            print(f"\r    {i}/{len(rows)}  {el/60:.1f}분 · "
                  f"남은 {el/i*(len(rows)-i)/60:.1f}분   ", end="", flush=True)
    print()


def gather(rows, root, ext, a, dev, mode="tile"):
    F, L = [], []
    for f, y in extract(rows, root, ext, a, dev, mode):
        F.append(f); L.append(y)
    if not F:
        sys.exit("[중단] 특징을 하나도 못 뽑았다. 타일 경로를 확인할 것.")
    return torch.cat(F), torch.cat(L)


# ── 지표 ───────────────────────────────────────────────────────────
def auc(score, label):
    # 순위합 공식은 **오름차순** 순위를 쓴다.
    # 내림차순으로 매기면 1 - AUC 가 나온다. 한 번 당했다.
    o = np.argsort(score)
    s, y = score[o], label[o]
    pos, neg = float(y.sum()), float((1 - y).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    # 순위합 방식. 동점은 평균 순위로 다룬다.
    r = np.empty(len(s), dtype=np.float64)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        r[i:j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((r[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def leak_at(score, label, q):
    """양성 상위 q 분위 점수 아래로 음성이 몇 %나 들어오나 (낮을수록 좋다)."""
    thr = np.percentile(score[label == 1], q)
    return 100.0 * float((score[label == 0] >= thr).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ds", default="data/binary_ds.json")
    ap.add_argument("--out", default="training/ckpt/binary_head.pt")
    ap.add_argument("--feat-cache", default="data/binary_feats.npz")
    ap.add_argument("--cache", action="store_true", help="특징을 캐시한다")
    ap.add_argument("--recache", action="store_true")
    ap.add_argument("--kind", choices=["all", "mass", "calc"], default="all",
                    help="양성을 종류로 거른다. 음성은 항상 전부 쓴다")
    # 서술어 모델과 같은 전처리 · 같은 뽑기 설정
    ap.add_argument("--size", type=int, default=1008)
    ap.add_argument("--no-pad", action="store_true", default=True)
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--margin", type=float, default=20.0)
    ap.add_argument("--src", default="trunk")
    ap.add_argument("--pool", default="grid")
    ap.add_argument("--grid", type=int, default=4)
    ap.add_argument("--levels", default="last")
    ap.add_argument("--batch", type=int, default=8)
    # 헤드
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--head-batch", type=int, default=256)
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--mclip", default="",
                    help="Mammo-CLIP 체크포인트(.tar). 주면 백본을 "
                         "SAM3 대신 이것으로 세운다. **절대 경로로 줄 것** "
                         "— 백본 세우는 중에 cwd 가 바뀐다")
    ap.add_argument("--repo", default="")
    a = ap.parse_args()

    ds = json.loads(Path(a.ds).read_text())
    # 1판은 타일 PNG, 2판은 DICOM. 목록이 스스로 밝힌다.
    mode = ds.get("mode", "tile")
    # cwd 가 백본 세우는 중에 바뀔 수 있다. 먼저 절대 경로로 못 박는다.
    root = Path(ds["images_root"]).resolve() if "images_root" in ds else None
    rows = ds["rows"]
    if a.kind != "all":
        want = "mass" if a.kind == "mass" else "calcification"
        rows = [r for r in rows if r["label"] == 0 or r["kind"] == want]

    tr = [r for r in rows if r["split"] == "train"]
    va = [r for r in rows if r["split"] == "val"]
    print("=" * 78)
    print("병변/정상 이진 분류기")
    print("=" * 78)
    print(f"  목록 {a.ds} · 모드 {mode}"
          + (f" · 조각 {root}" if root else ""))
    for nm, s in (("학습", tr), ("검증", va)):
        p = sum(1 for r in s if r["label"] == 1)
        src = {}
        for r in s:
            src[r.get("src", "?")] = src.get(r.get("src", "?"), 0) + 1
        bits = " · ".join(f"{k} {v:,}" for k, v in sorted(src.items()))
        print(f"  {nm} {len(s):,}개  (양성 {p:,} · 음성 {len(s)-p:,})  [{bits}]")
    if not tr or not va:
        sys.exit("[중단] 학습 또는 검증이 비었다.")

    cp = Path(a.feat_cache).resolve()
    if a.cache and cp.is_file() and not a.recache:
        z = np.load(cp)
        Xtr = torch.tensor(z["Xtr"]); Ytr = torch.tensor(z["Ytr"])
        Xva = torch.tensor(z["Xva"]); Yva = torch.tensor(z["Yva"])
        print(f"\n  특징 캐시 사용 — {cp}  (학습 {tuple(Xtr.shape)})")
    else:
        dev = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"\n■ 백본 세우기 ({dev}) — 동결")
        # eval_e2e.build_model 은 체크포인트에서 헤드까지 복원한다. 우리는
        # 백본만 필요하므로 같은 경로를 쓰되 헤드는 버린다.
        ext = build_backbone(a, dev)
        print(f"\n■ 특징 뽑기 — 학습  (모드 {mode})")
        Xtr, Ytr = gather(tr, root, ext, a, dev, mode)
        print("■ 특징 뽑기 — 검증")
        Xva, Yva = gather(va, root, ext, a, dev, mode)
        del ext
        torch.cuda.empty_cache()
        if a.cache:
            cp.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(cp, Xtr=Xtr.numpy(), Ytr=Ytr.numpy(),
                                Xva=Xva.numpy(), Yva=Yva.numpy())
            print(f"  특징 캐시 저장 -> {cp}")

    # ── 헤드 학습 ────────────────────────────────────────────────
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(a.seed)

    # 특징 표준화. 16,384차원에 표준편차 1.6 이라 그대로 넣으면 첫 층 출력이
    # 폭주해 시그모이드가 포화되고 기울기가 죽는다. 실제로 같은 캐시로 두 번
    # 돌렸는데 한 번은 학습되고 한 번은 상수만 냈다.
    #
    # ⚠ 통계는 **학습 집합에서만** 낸다. 검증을 섞으면 검증 점수가 부풀려진다.
    # ⚠ 이 평균·표준편차는 체크포인트에 같이 저장한다. 재점수할 때 같은 변환을
    #   걸어야 학습 때와 같은 그림을 본다.
    mu = Xtr.mean(dim=0, keepdim=True)
    sd = Xtr.std(dim=0, keepdim=True).clamp_min(1e-6)
    Xtr = (Xtr - mu) / sd
    Xva = (Xva - mu) / sd
    print(f"  특징 표준화 — 뒤 std {float(Xtr.std()):.3f} "
          f"(앞 {float(sd.mean()):.3f})")

    feat_dim = Xtr.shape[1]
    head = TM.make_head(1, feat_dim, hidden=a.hidden, dropout=a.dropout).to(dev)
    opt = torch.optim.AdamW(head.parameters(), lr=a.lr, weight_decay=1e-4)
    pos_w = float((Ytr == 0).sum()) / max(1.0, float((Ytr == 1).sum()))
    lossf = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_w, device=dev))
    print(f"\n■ 헤드 학습  특징 {feat_dim} · 양성 가중 {pos_w:.2f}")

    Xtr_d, Ytr_d = Xtr.to(dev), Ytr.to(dev)
    Xva_d = Xva.to(dev)
    yv = Yva.numpy()
    best, best_state = -1.0, None
    for ep in range(a.epochs):
        head.train()
        perm = torch.randperm(len(Xtr_d), device=dev)
        run = 0.0
        for i in range(0, len(perm), a.head_batch):
            idx = perm[i:i + a.head_batch]
            opt.zero_grad(set_to_none=True)
            out = head(Xtr_d[idx]).squeeze(-1)
            loss = lossf(out, Ytr_d[idx])
            loss.backward(); opt.step()
            run += float(loss) * len(idx)
        head.eval()
        with torch.no_grad():
            sv = torch.sigmoid(head(Xva_d).squeeze(-1)).cpu().numpy()
        A = auc(sv, yv)
        if A > best:
            best = A
            best_state = {k: v.detach().cpu().clone()
                          for k, v in head.state_dict().items()}
        print(f"  에폭 {ep:>3}  손실 {run/len(perm):.4f}  검증 AUC {A:.4f}"
              + ("  ✓" if A == best else ""))

    head.load_state_dict(best_state)
    head.eval()
    with torch.no_grad():
        sv = torch.sigmoid(head(Xva_d).squeeze(-1)).cpu().numpy()

    print("\n" + "=" * 78)
    print("검증 결과")
    print("=" * 78)
    print(f"  AUC {auc(sv, yv):.4f}")
    print("\n  양성 상위 분위 아래로 섞여 드는 음성 비율 (낮을수록 좋다)")
    for q in (10, 25, 50):
        print(f"    양성 {100-q}% 를 살리는 문턱에서 음성 {leak_at(sv, yv, q):5.1f}% 통과")

    op = Path(a.out).resolve()
    op.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"head": best_state, "feat_dim": feat_dim, "auc": best,
                # 재점수할 때 반드시 같은 변환을 걸 것
                "mu": mu.cpu(), "sd": sd.cpu(),
                "args": vars(a)}, op)
    print(f"\n  저장 -> {op}")

    print("""
  다음 — 이걸로 검출 점수를 다시 매긴다

    AUC 가 0.5 근처면 신호가 없는 것이다. 여기서 멈추고 다른 걸 보자.
    0.75 를 넘으면 재점수를 붙일 값어치가 있다.

    최종 판단은 AUC 가 아니다. test 검출 파일에 이 분류기를 걸어
    **같은 오탐 지점에서 FROC 재현율이 오르는지**로 정한다.
    오늘 실패한 아홉 가지도 대부분 중간 지표는 좋았다.""")


def _find(names, mods):
    """여러 모듈에서 이름을 찾는다. 어디에 있는지 확실치 않아서."""
    out = {}
    for n in names:
        for m in mods:
            try:
                mm = __import__(m)
            except Exception:
                continue
            if hasattr(mm, n):
                out[n] = getattr(mm, n)
                out[n + "__from"] = m
                break
    return out


def build_backbone(a, dev):
    """medsam3 병합본에서 시각 백본만 꺼내 동결한다.

    CKPT · CFG · load_merged_model 이 어느 파일에 있는지 확실치 않아
    여러 곳을 훑는다. 못 찾으면 어디를 봤는지 찍고 멈춘다 — 조용히 다른
    가중치를 쓰는 것이 제일 나쁘다.
    """
    from paths import medsam3_cwd
    # Mammo-CLIP 을 쓸 때는 **_find 보다 먼저** 갈아 끼워야 한다. 순서가
    # 바뀌면 원래 SAM3 함수를 잡아 두고 조용히 그걸로 돈다 — 오류가 안 난다.
    mc = getattr(a, "mclip", "")
    if mc:
        mp = Path(mc)
        if not mp.is_absolute():
            sys.exit(f"[중단] --mclip 은 절대 경로로 줄 것: {mc}\n"
                     "  백본 세우는 중에 cwd 가 바뀌어 상대 경로가 어긋난다.")
        if not mp.is_file():
            sys.exit(f"[중단] 없는 파일: {mp}")
        import train_mclip
        train_mclip.install()
        a.ckpt = str(mp)
        print("  백본을 Mammo-CLIP 으로 교체한다 (CC BY-NC-SA 4.0 · 비영리)")

    mods = ("train_mammo", "eval_e2e", "eval_end2end", "paths", "mammo_cfg")
    f = _find(("CKPT", "CFG", "load_merged_model"), mods)
    ck = a.ckpt or f.get("CKPT")
    if mc and f.get("load_merged_model__from") != "train_mammo":
        sys.exit("[중단] 갈아 끼운 load_merged_model 을 안 잡았다 "
                 f"({f.get('load_merged_model__from')}). 그대로 두면 SAM3 로 "
                 "돌면서 Mammo-CLIP 이라고 적힌다.")
    cfg = f.get("CFG")
    lm = f.get("load_merged_model")
    if lm is None:
        try:
            from merge_medsam3 import load_merged_model as lm  # noqa: F811
        except Exception:
            pass
    miss = [n for n, v in (("CKPT", ck), ("CFG", cfg),
                           ("load_merged_model", lm)) if v is None]
    if miss:
        sys.exit(f"[중단] {miss} 를 못 찾았다. 훑은 곳: {mods} · merge_medsam3\n"
                 f"  어디에 있는지 알려 주면 고치겠다.")
    print(f"  백본 {ck}")
    for n in ("CKPT", "CFG", "load_merged_model"):
        if f.get(n + "__from"):
            print(f"    {n} <- {f[n + '__from']}")
    with medsam3_cwd():
        full = lm(str(ck), cfg, device=dev)
    vb = full.backbone.vision_backbone
    del full
    for p in vb.parameters():
        p.requires_grad = False
    ext = TM.FeatExtractor(vb, a.src).to(dev).eval()
    return ext


if __name__ == "__main__":
    main()
