#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""이진 분류기가 **실전 상자**에서도 통하는지 값싸게 확인한다.

무엇이 걱정인가
  분류기는 검증에서 AUC 0.957 이 나왔다. 그런데 그 검증은 학습과 같은 종류의
  문제였다 — 「정답 병변 조각」 대 「무작위 조직 조각」.

  실전은 다른 문제다 — 「정답과 겹친 검출 상자」 대 「병변처럼 생겨서 검출기가
  올린 상자」. 뒤쪽이 훨씬 어렵다. 아무 조직이 아니라 **이미 병변처럼 보이는
  자리**들이기 때문이다.

  어긋남이 넷 있다.
    · 학습 조각은 1008px 타일에서, 실전 조각은 조직 상자로 자른 배열에서 온다
    · 잘리는 경계가 다르다 (타일 경계 vs 조직 상자 경계)
    · 타일 PNG 는 이미 한 번 정규화된 것이다
    · **음성의 성격이 다르다** — 무작위 조직 vs 검출기가 착각한 자리

  그래서 전체 재점수를 만들기 전에 이걸 먼저 잰다. 오늘 실패한 아홉 가지도
  중간 지표는 다 좋았다.

무엇을 재나
  test 검출 상자를 표본으로 뽑아 분류기에 넣고, **정답과 겹치는 것과 아닌 것을
  가르는지** 본다. 그 AUC 가 답이다.

    0.80 이상   전이된다. 전체 재점수를 만들 값어치가 있다
    0.60~0.80  약하지만 있다. 어려운 음성으로 다시 학습해야 한다
    0.50 근처  쉬운 음성만 배웠다. 학습 split 오탐이 반드시 필요하다

  표본은 정탐·오탐을 같은 수로 뽑는다. 실제 비율(1:40)대로 뽑으면 정탐이
  몇 개 안 들어와 AUC 가 흔들린다.

  검출 점수와의 비교도 같이 낸다. **분류기가 검출 점수보다 나은가**가
  진짜 질문이다 — 검출 점수만으로도 이미 가려지는 것을 다시 가리는 것이면
  얻는 게 없다.

사용
  python3 training/code/check_binary_transfer.py
  python3 training/code/check_binary_transfer.py --n 3000
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

try:
    import numpy as np
    import pydicom
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 저장소 뿌리를 스스로 찾는다. 작업 디렉터리가 어디든 상대 경로가 맞게
# 풀리도록 — 같은 실수를 세 번 했다.
ROOT = Path(__file__).resolve().parents[2]


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)

import eval_mammo_det as E                                    # noqa: E402
import train_binary as TB                                     # noqa: E402
from eval_end2end import crop_to_tensor                       # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets",
                    default="archive/outputs/"
                            "tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json")
    ap.add_argument("--head", default="training/ckpt/binary_head.pt")
    ap.add_argument("--gt-cache", default="docs/show_gt_cache.json")
    ap.add_argument("--n", type=int, default=1000,
                    help="종류당 정탐·오탐 각각 이만큼")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--margin", type=float, default=20.0)
    ap.add_argument("--size", type=int, default=1008)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    a.no_pad = True
    a.src, a.pool, a.grid, a.levels = "trunk", "grid", 4, "last"
    a.ckpt = ""

    rnd = random.Random(a.seed)

    print("=" * 80)
    print("이진 분류기 전이 확인 — 학습한 문제가 아니라 실전 문제로 잰다")
    print("=" * 80)

    # ── 헤드 ────────────────────────────────────────────────────
    hp = Path(a.head)
    if not hp.is_file():
        sys.exit(f"[중단] 없는 파일: {hp}")
    ck = torch.load(hp, map_location="cpu", weights_only=False)
    for k in ("head", "feat_dim", "mu", "sd"):
        if k not in ck:
            sys.exit(f"[중단] 체크포인트에 {k} 가 없다. "
                     "patch_binfix 적용 뒤 다시 학습했는지 확인할 것.")
    print(f"  헤드 {hp} · 특징 {ck['feat_dim']} · 학습 AUC {ck.get('auc'):.4f}")
    # 특징 뽑는 설정과 **백본**은 학습 때와 같아야 한다. 손으로 적으면
    # 백본을 하나 더 늘리는 순간 어긋난다 — 실제로 그렇게 터졌다.
    # 차원이 안 맞으면 죽지만, 우연히 맞으면 조용히 틀린 값이 나온다.
    _ha = ck.get("args") or {}
    a.src = _ha.get("src", a.src)
    a.pool = _ha.get("pool", a.pool)
    a.grid = int(_ha.get("grid", a.grid))
    a.levels = _ha.get("levels", a.levels)
    a.size = int(_ha.get("size", a.size))
    a.clip = float(_ha.get("clip", a.clip))
    a.margin = float(_ha.get("margin", a.margin))
    a.no_pad = bool(_ha.get("no_pad", a.no_pad))
    a.hidden = int(_ha.get("hidden", 512))
    a.dropout = float(_ha.get("dropout", 0.2))
    a.mclip = _ha.get("mclip") or ""
    print(f"    설정 src={a.src} pool={a.pool} grid={a.grid} "
          f"levels={a.levels} size={a.size} margin={a.margin}")
    print("    백본 " + (f"Mammo-CLIP {Path(a.mclip).name}" if a.mclip
                       else "SAM3 (검출기와 같은 것)"))
    if a.mclip and not Path(a.mclip).is_file():
        sys.exit(f"[중단] 학습 때 쓴 Mammo-CLIP 체크포인트가 지금 없다: "
                 f"{a.mclip}")

    # ── 정답 ────────────────────────────────────────────────────
    gp = Path(a.gt_cache)
    if not gp.is_file():
        sys.exit(f"[중단] 정답 캐시가 없다: {gp}\n"
                 "  show_eval.py 를 한 번 돌리면 만들어진다.")
    j = json.loads(gp.read_text())
    gts = {k: {u: [tuple(b) for b in v] for u, v in d.items()}
           for k, d in j["gts"].items()}
    origin = {u: tuple(v) for u, v in j["origin"].items()}
    print(f"  정답 캐시 {gp} · 영상 {len(origin):,}장")

    ents = E.load_gt("test")
    raw = json.loads(Path(a.dets).read_text())
    print(f"  검출 {Path(a.dets).name}")

    # ── 표본 뽑기 ────────────────────────────────────────────────
    #    정탐·오탐을 같은 수로. 실제 비율(1:40)대로 뽑으면 정탐이 몇 개 안
    #    들어와 AUC 가 흔들린다.
    picks = []
    for kind in TB.__dict__.get("PROMPTS", ["calcification", "mass"]):
        g = gts.get(kind, {})
        tp, fp = [], []
        for d in raw.get(kind, []):
            u = str(d["img"])
            if u not in origin or u not in ents:
                continue
            b = tuple(map(float, d["box"]))
            hit = any(E.center_in(b, q) for q in g.get(u, ()))
            (tp if hit else fp).append((u, b, float(d["score"]), kind))
        rnd.shuffle(tp); rnd.shuffle(fp)
        n = min(a.n, len(tp), len(fp))
        picks += tp[:n] + fp[:n]
        print(f"  {kind:<16} 정탐 {len(tp):>6,} · 오탐 {len(fp):>7,}"
              f"  -> 각 {n:,}개 뽑음")
    if not picks:
        sys.exit("[중단] 표본이 비었다.")

    # 영상별로 모아 DICOM 을 한 번씩만 읽는다
    picks.sort(key=lambda x: x[0])
    labels = {id(p): (1.0 if any(E.center_in(p[1], q)
                                 for q in gts[p[3]].get(p[0], ())) else 0.0)
              for p in picks}

    # ── 백본 ────────────────────────────────────────────────────
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    if dev == "cpu":
        sys.exit("[중단] GPU 가 없다. 백본을 CPU 로 돌리면 몇 시간 걸린다.")
    print(f"\n■ 백본 세우기 ({dev})")
    ext = TB.build_backbone(a, dev)
    head = TB.TM.make_head(1, ck["feat_dim"], hidden=a.hidden,
                           dropout=a.dropout).to(dev)
    head.load_state_dict(ck["head"]); head.eval()
    mu, sd = ck["mu"].to(dev), ck["sd"].to(dev)

    # ── 조각 만들고 점수 내기 ────────────────────────────────────
    print("\n■ 조각 만들고 점수 내기")
    P, S, Y = [], [], []
    buf, meta = [], []
    cur_uid, arr = None, None
    t0 = time.time()

    def flush():
        if not buf:
            return
        with torch.no_grad():
            xb = torch.stack(buf).to(dev)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                f = TB.TM.pool_feats(ext(xb), a.pool, a.levels, a.grid)
            f = (f.float() - mu) / sd
            p = torch.sigmoid(head(f).squeeze(-1)).cpu().numpy()
        for pv, (sc, yv) in zip(p, meta):
            P.append(float(pv)); S.append(sc); Y.append(yv)
        buf.clear(); meta.clear()

    for i, (uid, box, score, kind) in enumerate(picks, 1):
        if uid != cur_uid:
            flush()
            try:
                a16 = pydicom.dcmread(str(ents[uid]["dcm"])).pixel_array
            except Exception:
                cur_uid, arr = uid, None
                continue
            cx0, cy0, w, h = origin[uid]
            arr = a16[cy0:cy0 + h, cx0:cx0 + w]
            cur_uid = uid
        if arr is None:
            continue
        e = TB.expand(box, a.margin, arr.shape)
        if e is None:
            continue
        buf.append(crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                  a.size, not a.no_pad, a.clip))
        meta.append((score, labels[id(picks[i - 1])]))
        if len(buf) >= a.batch:
            flush()
        if i % 100 == 0 or i == len(picks):
            el = time.time() - t0
            print(f"\r    {i}/{len(picks)}  {el/60:.1f}분 · "
                  f"남은 {el/i*(len(picks)-i)/60:.1f}분   ", end="", flush=True)
    flush()
    print()

    P, S, Y = np.array(P), np.array(S), np.array(Y)
    if len(P) < 100:
        sys.exit(f"[중단] 점수를 낸 것이 {len(P)}개뿐이다.")

    # ── 결과 ────────────────────────────────────────────────────
    a_cls = TB.auc(P, Y)
    a_det = TB.auc(S, Y)
    a_mix = TB.auc(S * P, Y)

    print("\n" + "=" * 80)
    print(f"결과 — 표본 {len(P):,}개 (정탐 {int(Y.sum()):,} · 오탐 {int((1-Y).sum()):,})")
    print("=" * 80)
    print(f"\n  {'무엇으로 가르나':<28}{'AUC':>8}")
    print(f"  {'검출 점수만':<28}{a_det:>8.4f}   ← 기준선")
    print(f"  {'분류기만':<28}{a_cls:>8.4f}")
    print(f"  {'검출 점수 × 분류기':<28}{a_mix:>8.4f}")

    print("\n" + "-" * 80)
    if a_cls < 0.6:
        print("  분류기가 실전 상자를 못 가른다.")
        print("  **쉬운 음성만 배웠다.** 무작위 조직과 병변은 갈랐지만,")
        print("  검출기가 병변으로 착각한 자리는 못 가린다.")
        print("  -> 학습 split 오탐(어려운 음성)이 반드시 필요하다.")
    elif a_cls < 0.8:
        print("  신호는 있는데 약하다.")
        print("  -> 어려운 음성을 섞어 다시 학습하면 오를 여지가 있다.")
    else:
        print("  전이된다. 전체 재점수를 만들 값어치가 있다.")

    if a_mix <= a_det + 0.005:
        print("\n  ⚠ 다만 **검출 점수와 곱해도 기준선을 못 넘는다.**")
        print("    분류기가 검출 점수와 같은 것을 보고 있다는 뜻이라,")
        print("    재점수로 얻을 것이 없다. 이게 실패한 아홉 가지의 모습이다.")
    else:
        print(f"\n  검출 점수 단독보다 {a_mix - a_det:+.4f} 낫다.")
        print("    이 차이가 재점수의 상한이다. 실제 FROC 이득은 이보다 작다.")

    print("""
  ※ 이 AUC 는 검출 하나하나를 가르는 능력이다. FROC 이득과 직접 이어지지
    않는다 — 순위가 영상 안에서만 바뀌면 되기 때문이다. 최종 판정은
    재점수한 검출 파일을 score_dets 에 넣어 **같은 오탐 지점의 재현율**로
    한다.""")


if __name__ == "__main__":
    main()
