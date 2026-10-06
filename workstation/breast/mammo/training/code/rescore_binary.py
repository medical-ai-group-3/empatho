#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""이진 분류기로 검출 순위를 다시 매긴다 — 최종 판정.

무엇을 판정하나
  전이 확인에서 AUC 가 나왔다. 검출 점수만 0.7461 · 분류기만 0.7846 ·
  둘을 곱하면 0.7974. 미리 정한 문턱 0.80 을 0.0026 못 넘었다.

  그런데 **AUC 와 FROC 사이에는 환산이 없다.** AUC 는 검출 하나하나를
  가르는 능력이고, FROC 는 영상 안에서의 순위만 본다. AUC 가 조금
  올라도 순위가 안 바뀌면 재현율은 그대로고, AUC 가 그대로여도 순위가
  바뀌면 재현율은 움직인다. 그래서 마지막은 **같은 오탐 지점의 재현율**로
  잰다. 이 스크립트가 그 파일을 만든다.

  지금 값 (center 기준 · 종류당 오탐)
    미세석회  0.25 31.5 · 0.5 46.9 · 1 63.7 · 2 77.5 · 4 83.9
    종괴      0.25 36.0 · 0.5 52.3 · 1 66.0 · 2 76.7 · 4 84.3
  이보다 올라야 붙인다. 안 오르면 이 방향을 닫는다.

무엇을 곱하나
      새 점수 = 검출 점수 × 분류기 확률 ** w

  w=0 이면 원본과 **완전히 같다.** 이게 내장된 대조군이다 — w=0 줄이
  원본과 한 자리라도 다르면 어딘가 틀린 것이니 나머지를 믿으면 안 된다.
  w=1 이 전이 확인에서 0.7974 를 낸 조합이다. w 를 키울수록 분류기 쪽에
  무게가 실린다.

  절대 점수를 버리지 않는다 — 영상별 정규화와 교차 질의가 실패한 원인이
  절대 점수를 버린 것이었다. 곱하기는 원래 순서를 바탕에 깔고 있다.

왜 상위 k개만 다시 매기나
  작동점이 종류당 오탐 2개다. 영상당 상위 20개 밖에 있는 검출은 어차피
  그 문턱을 못 넘는다. 전부 다시 매기면 GPU 시간이 두 배가 되고 얻는 것이
  없다. 다만 **정말 못 넘는지 확인하고 넘어간다** — 아래 [확인] 참조.

  다시 안 매긴 검출은 버리지 않는다. 버리면 최대 재현율이 떨어져 비교가
  깨진다. 대신 그 종류의 **확률 중앙값**을 똑같이 곱해 눈금만 맞춘다.
  정보를 주지도 뺏지도 않으면서 다시 매긴 것들과 같은 자 위에 놓는다.

좌표계 — 여기서 틀리면 전부 무의미하다
  검출 파일의 상자는 **조직 상자 기준**이다. DICOM 을 읽어 조직 상자로
  자른 뒤 그 위에서 조각을 뜬다. 학습(2판)과 전이 확인이 쓴 것과 같은
  경로다. 원점은 docs/show_gt_cache.json 의 origin 을 그대로 쓴다.

확률은 캐시한다
  GPU 는 한 번만 쓴다. 확률을 캐시에 적어 두고, w 를 바꿔 가며 파일을
  만드는 것은 CPU 로 몇 초에 끝난다. w 를 다시 훑고 싶으면 --from-cache.

사용
  # 확인만 — GPU 안 쓴다. 상위 k개로 충분한지 먼저 본다
  python3 training/code/rescore_binary.py --dry

  # 본 계산 (GPU 30~40분)
  bash training/code/queue_gpu.sh rescore training/code -- \\
      python3 rescore_binary.py

  # w 만 다시 훑기 (GPU 안 쓴다)
  python3 training/code/rescore_binary.py --from-cache --weights 0,0.5,1,1.5,2,3
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    import numpy as np
    import pydicom
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

# cwd 가 백본 세우는 중에 바뀐다(medsam3_cwd). 상대 경로는 그 순간 전부
# 어긋난다. 모든 경로를 저장소 뿌리에 대고 미리 절대 경로로 못 박는다.
ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402
import train_binary as TB                                     # noqa: E402
from eval_end2end import crop_to_tensor                       # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


# ── 상위 k개 고르기 ────────────────────────────────────────────────
def pick_topk(raw, k):
    """종류마다 영상별 상위 k개의 «원본 목록에서의 자리»를 돌려준다.

    자리(index)로 다루는 것이 중요하다. 나중에 원본 목록을 그대로 두고
    고른 자리만 점수를 갈아 끼워야 다른 항목이 흐트러지지 않는다.
    """
    sel, rest = {}, {}
    for kind in PROMPTS:
        by = defaultdict(list)
        for j, d in enumerate(raw.get(kind, [])):
            by[str(d["img"])].append(j)
        keep, drop = [], []
        for _u, idxs in by.items():
            idxs.sort(key=lambda j: -float(raw[kind][j]["score"]))
            keep += idxs[:k]
            drop += idxs[k:]
        sel[kind], rest[kind] = keep, drop
    return sel, rest


def check_enough(raw, rest, thr_ref, src_name):
    """다시 안 매긴 것들이 정말 작동점 아래인가.

    상위 k개만 다시 매기는 근거가 이것 하나다. 근거가 안 서면 k 를 올려야
    한다. 임계값은 지난 채점 결과(score_dets.json)에서 읽는다.
    """
    print("\n── [확인] 상위 k개로 충분한가")
    ref = None
    p = rp(thr_ref)
    if p.is_file():
        try:
            ref = json.loads(p.read_text()).get(src_name)
        except Exception:
            ref = None
    if not ref:
        print(f"  지난 채점 결과에서 이 파일({src_name})을 못 찾았다: {p}")
        print("  임계값을 모르니 «충분한가» 를 확인할 수 없다. k 를 넉넉히 줄 것.")
        return
    for kind in PROMPTS:
        node = (ref.get(kind) or {}).get("center_thr") or {}
        t4 = node.get("4.0", node.get("4", node.get(4)))
        left = [float(raw[kind][j]["score"]) for j in rest[kind]]
        hi = max(left) if left else 0.0
        if t4 is None:
            print(f"  {kind:<16} 임계값을 못 읽었다 — 남은 것 최고 점수 {hi:.3f}")
            continue
        over = sum(1 for s in left if s >= float(t4))
        mark = "충분하다" if over == 0 else f"**{over:,}개가 작동점 위에 있다 — k 를 올릴 것**"
        print(f"  {kind:<16} 오탐 4개 임계값 {float(t4):.3f} · "
              f"다시 안 매긴 것 {len(left):,}개 (최고 {hi:.3f}) → {mark}")


# ── 확률 매기기 (GPU) ──────────────────────────────────────────────
def score_probs(raw, sel, a):
    """고른 자리마다 분류기 확률을 낸다. {kind: {index: p}}"""
    ck = torch.load(rp(a.head), map_location="cpu", weights_only=False)
    for k in ("head", "feat_dim", "mu", "sd"):
        if k not in ck:
            die(f"체크포인트에 {k} 가 없다. patch_binfix 적용 뒤 다시 "
                "학습한 것인지 확인할 것.")
    ha = ck.get("args") or {}
    # 특징 뽑는 설정은 **학습 때와 같아야 한다.** 다르면 헤드가 다른 그림을
    # 보게 되는데 오류는 안 난다 — 조용히 나빠진다. 체크포인트에서 읽는다.
    a.src = ha.get("src", "trunk")
    a.pool = ha.get("pool", "grid")
    a.grid = int(ha.get("grid", 4))
    a.levels = ha.get("levels", "last")
    a.size = int(ha.get("size", 1008))
    a.clip = float(ha.get("clip", 99.9))
    a.margin = float(ha.get("margin", 20.0))
    a.no_pad = bool(ha.get("no_pad", True))
    hidden = int(ha.get("hidden", 512))
    dropout = float(ha.get("dropout", 0.2))
    a.ckpt = ""
    # 백본도 학습 때와 같은 것이어야 한다. Mammo-CLIP 으로 학습한 머리를
    # SAM3 특징에 씌우면 오류 없이 엉뚱한 값이 나온다.
    a.mclip = ha.get("mclip") or ""
    print(f"  헤드 {rp(a.head)} · 특징 {ck['feat_dim']} · 학습 AUC "
          f"{float(ck.get('auc', float('nan'))):.4f}")
    print(f"    설정 src={a.src} pool={a.pool} grid={a.grid} levels={a.levels} "
          f"size={a.size} clip={a.clip} margin={a.margin} no_pad={a.no_pad}")
    print(f"    백본 {'Mammo-CLIP ' + Path(a.mclip).name if a.mclip else 'SAM3 (검출기와 같은 것)'}")
    if a.mclip and not Path(a.mclip).is_file():
        die(f"학습 때 쓴 Mammo-CLIP 체크포인트가 지금 없다: {a.mclip}")

    j = json.loads(rp(a.gt_cache).read_text())
    origin = {u: tuple(v) for u, v in j["origin"].items()}
    ents = E.load_gt(a.split)
    print(f"  원점 캐시 {rp(a.gt_cache)} · 영상 {len(origin):,}장")

    # 영상별로 모은다 — DICOM 을 한 장당 한 번만 읽는다
    work = defaultdict(list)                      # uid -> [(kind, index)]
    missing = 0
    for kind in PROMPTS:
        for jx in sel[kind]:
            u = str(raw[kind][jx]["img"])
            if u in origin and u in ents:
                work[u].append((kind, jx))
            else:
                missing += 1
    uids = sorted(work)
    if a.n:
        uids = uids[:a.n]
    total = sum(len(work[u]) for u in uids)
    print(f"  다시 매길 조각 {total:,}개 · 영상 {len(uids):,}장"
          + (f" · 원점을 못 찾아 뺀 것 {missing:,}개" if missing else ""))
    if not total:
        die("다시 매길 것이 없다.")

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        die("GPU 가 없다. 백본을 CPU 로 돌리면 몇 시간 걸린다.")
    print(f"\n■ 백본 세우기 ({dev})")
    ext = TB.build_backbone(a, dev)
    head = TB.TM.make_head(1, ck["feat_dim"], hidden=hidden,
                           dropout=dropout).to(dev)
    head.load_state_dict(ck["head"])
    head.eval()
    # 학습 때와 **같은 표준화**를 건다. 안 걸면 헤드가 못 보던 눈금을 본다.
    mu, sd = ck["mu"].to(dev), ck["sd"].to(dev)

    out = {k: {} for k in PROMPTS}
    buf, meta = [], []
    t0, done = time.time(), 0

    def flush():
        if not buf:
            return
        with torch.no_grad():
            xb = torch.stack(buf).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                f = TB.TM.pool_feats(ext(xb), a.pool, a.levels, a.grid)
            f = (f.float() - mu) / sd
            pr = torch.sigmoid(head(f).squeeze(-1)).cpu().numpy()
        for pv, (kk, jj) in zip(pr, meta):
            out[kk][jj] = float(pv)
        buf.clear()
        meta.clear()

    print("\n■ 조각 뜨고 확률 매기기")
    for i, uid in enumerate(uids, 1):
        try:
            a16 = pydicom.dcmread(str(ents[uid]["dcm"])).pixel_array
        except Exception:
            continue
        if a16.ndim != 2:
            continue
        cx0, cy0, w, h = origin[uid]
        arr = a16[cy0:cy0 + h, cx0:cx0 + w]
        for kind, jx in work[uid]:
            e = TB.expand(raw[kind][jx]["box"], a.margin, arr.shape)
            if e is None:
                continue
            buf.append(crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                      a.size, not a.no_pad, a.clip))
            meta.append((kind, jx))
            done += 1
            if len(buf) >= a.batch:
                flush()
        if i % 10 == 0 or i == len(uids):
            el = time.time() - t0
            print(f"\r    영상 {i}/{len(uids)} · 조각 {done:,}/{total:,}  "
                  f"{el/60:.1f}분 · 남은 {el/max(1,done)*(total-done)/60:.1f}분   ",
                  end="", flush=True)
    flush()
    print()
    return out


# ── 파일 만들기 ────────────────────────────────────────────────────
def emit(raw, probs, w, src, out_dir, neutral):
    obj = {k: v for k, v in raw.items() if k not in PROMPTS}
    for kind in PROMPTS:
        pk = probs.get(kind, {})
        nb = neutral[kind]
        lst = []
        for j, d in enumerate(raw.get(kind, [])):
            p = pk.get(j, pk.get(str(j), nb))
            e2 = dict(d)
            e2["score"] = float(d["score"]) * (float(p) ** w)
            lst.append(e2)
        obj[kind] = lst
    dst = rp(out_dir) / f"{src.stem}_bin{int(round(w * 100)):03d}.json"
    if dst.resolve() == src.resolve():
        die("출력이 원본과 같다.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
    return dst


def emit_pure(raw, probs, src, out_dir, neutral):
    """검출 점수를 버리고 분류기 확률만으로 세운 파일 — 진단용.

    이게 원본보다 나으면 검출 점수가 오히려 방해가 되고 있다는 뜻이고,
    한참 못하면 분류기는 검출 점수를 «다듬는» 역할까지가 한계다.
    """
    obj = {k: v for k, v in raw.items() if k not in PROMPTS}
    for kind in PROMPTS:
        pk = probs.get(kind, {})
        nb = neutral[kind]
        obj[kind] = [dict(d, score=float(pk.get(j, pk.get(str(j), nb))))
                     for j, d in enumerate(raw.get(kind, []))]
    dst = rp(out_dir) / f"{src.stem}_binonly.json"
    dst.write_text(json.dumps(obj, ensure_ascii=False, default=float))
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/"
                            "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--head", default="training/ckpt/binary_head2.pt")
    ap.add_argument("--gt-cache", default="docs/show_gt_cache.json")
    ap.add_argument("--thr-ref", default="docs/score_dets.json")
    ap.add_argument("--cache", default="docs/rescore_binary_probs.json")
    ap.add_argument("--out-dir", default="archive/outputs")
    ap.add_argument("--split", default="test")
    ap.add_argument("--topk", type=int, default=20,
                    help="영상당 종류당 이만큼만 다시 매긴다")
    ap.add_argument("--weights", default="0,0.5,1,2",
                    help="score × p**w 의 w 들. 0 은 원본과 같아야 하는 대조군")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--n", type=int, default=0, help="영상 수 제한 (시험용)")
    ap.add_argument("--dry", action="store_true", help="확인만. GPU 안 쓴다")
    ap.add_argument("--from-cache", action="store_true",
                    help="캐시된 확률로 파일만 다시 만든다. GPU 안 쓴다")
    ap.add_argument("--repo", default="")
    a = ap.parse_args()

    src = rp(a.dets)
    if not src.is_file():
        die(f"없는 파일: {src}")
    raw = json.loads(src.read_text())

    print("=" * 84)
    print("이진 분류기로 검출 재점수 — 같은 오탐 지점의 재현율로 판정한다")
    print("=" * 84)
    print(f"  검출 {src}")
    for kind in PROMPTS:
        print(f"    {kind:<16} {len(raw.get(kind, [])):>8,}개")

    sel, rest = pick_topk(raw, a.topk)
    for kind in PROMPTS:
        print(f"  상위 {a.topk}개  {kind:<16} 다시 매길 것 {len(sel[kind]):>7,} · "
              f"그대로 둘 것 {len(rest[kind]):>8,}")
    check_enough(raw, rest, a.thr_ref, src.name)

    if a.dry:
        print("\n  --dry 라 여기까지. 위 [확인] 이 «충분하다» 면 그대로 돌리고,")
        print("  아니면 --topk 를 올려서 돌릴 것.")
        return

    cp = rp(a.cache)
    if a.from_cache:
        if not cp.is_file():
            die(f"캐시가 없다: {cp}")
        cj = json.loads(cp.read_text())
        probs = {k: {int(x): float(v) for x, v in cj["probs"].get(k, {}).items()}
                 for k in PROMPTS}
        print(f"\n  확률 캐시 사용 — {cp}")
        if cj.get("dets") != str(src):
            print(f"  ⚠ 캐시는 다른 검출 파일에서 나왔다: {cj.get('dets')}")
    else:
        probs = score_probs(raw, sel, a)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "dets": str(src), "head": str(rp(a.head)), "topk": a.topk,
            "split": a.split,
            "probs": {k: {str(x): v for x, v in probs[k].items()}
                      for k in PROMPTS},
        }, ensure_ascii=False))
        print(f"  확률 캐시 저장 -> {cp}")

    # 다시 안 매긴 것에 곱할 중립 계수 — 그 종류 확률의 중앙값.
    # 눈금만 맞춘다. 정보를 주지도 뺏지도 않는다.
    neutral = {}
    print(f"\n  {'종류':<16}{'다시 매긴 것':>12}{'확률 중앙값':>12}"
          f"{'5퍼':>8}{'95퍼':>8}")
    for kind in PROMPTS:
        v = np.array(list(probs[kind].values()), dtype=float)
        if not len(v):
            die(f"{kind} 확률이 하나도 없다.")
        neutral[kind] = float(np.median(v))
        print(f"  {kind:<16}{len(v):>12,}{neutral[kind]:>12.4f}"
              f"{np.percentile(v, 5):>8.3f}{np.percentile(v, 95):>8.3f}")

    ws = [float(x) for x in a.weights.split(",") if x.strip()]
    made = []
    print(f"\n■ 파일 만들기 — score × p**w")
    for w in ws:
        d = emit(raw, probs, w, src, a.out_dir, neutral)
        note = "  ← 대조군. 원본과 같아야 한다" if w == 0 else ""
        print(f"  w={w:<5g} {d.name}{note}")
        made.append(str(d))
    d = emit_pure(raw, probs, src, a.out_dir, neutral)
    print(f"  분류기만  {d.name}  ← 진단용")
    made.append(str(d))

    print("\n다음 — 채점한다 (GPU 안 쓴다, 15분쯤)")
    print("  python3 training/code/score_dets.py \\\n      " + str(src)
          + " \\\n      " + " \\\n      ".join(made)
          + " \\\n      --save docs/score_dets_binary.json")
    print("""
  읽는 법
    ① w=0 줄이 원본 줄과 **한 자리도 다르지 않아야 한다.** 다르면
       어딘가 틀린 것이니 나머지를 믿으면 안 된다.
    ② 판정은 center 기준 오탐 2개 칸이다. 지금 값은
         미세석회 77.5 · 종괴 76.7
       둘 다 오르면 붙인다. 하나만 오르면 그 종류에만 건다.
       둘 다 안 오르면 이 방향을 닫는다 — 값을 보고 문턱을 옮기지 않는다.
    ③ 붙이기로 하면 임계값을 **다시 뽑아야 한다.** 점수 눈금이 바뀌었으므로
       옛 임계값을 그대로 쓰면 검출이 확 줄어든다. score_dets 가 찍는
       «운영에 넣을 점수 임계값» 표에서 새 값을 읽어 infer_mammo.DEFAULTS
       의 score_calc · score_mass 에 넣는다.""")


if __name__ == "__main__":
    main()
