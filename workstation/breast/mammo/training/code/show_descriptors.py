#!/usr/bin/env python
"""
서술어가 어떻게 나오는지 눈으로 본다 — 병변 조각 몇 개를 골라 정답과 나란히.

왜 필요한가
  지금까지 낸 것은 전부 집계다 — 민감도 98.1%, 등급 일치 65.8%. 그 숫자가
  무엇을 뭐라고 불러서 나온 값인지는 아무 파일에도 안 남아 있다.
  발표에서 "이 사진을 이렇게 읽습니다" 를 보여주려면 낱개가 필요하고,
  틀린 것을 볼 때도 축 단위로 봐야 어디가 약한지 안다.

무엇을 보여주나
  조각마다 축별로  정답 / 예측 / 그 확률  을 나란히 놓는다.
  그 다음 규칙표를 태워 등급과 조직검사 여부를 내고 CBIS 정답 등급과 비교한다.

메모리
  서술어 백본 하나만 올린다(약 3GB). 검출기를 안 쓰므로 학습이 도는 중에도
  들어갈 수 있다. predict.py 는 검출기까지 올려서 지금은 못 돌린다.

사용
  python3 show_descriptors.py --kind calc --n 8
  python3 show_descriptors.py --kind mass --n 8 --png ../../docs/desc_mass.png
  python3 show_descriptors.py --kind calc --only-wrong --n 6    # 틀린 것만
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    import pandas as pd
    import torch
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

from eval_e2e import (build_model, find_rules, import_rules,   # noqa: E402
                      gt_onehot, level_of, to_category, to_onehot)
from eval_end2end import BIOPSY_CUT                            # noqa: E402
from mammo_data import MammoROIDataset, axis_slices, load_schema  # noqa: E402
from paths import CKPT, ROI_INDEX                              # noqa: E402
from train_mammo import SCHEMA, pool_feats                     # noqa: E402

AXIS_KO = {"shape": "모양", "margin": "경계", "finding": "소견",
           "calctype": "형태", "calcdist": "분포"}
GRADE_KO = {1: "정상", 2: "양성", 3: "양성 추정", 4: "악성 의심",
            5: "악성 강력 의심"}
DEFAULT_CKPT = {
    "calc": CKPT / "mammo_calc_trunk_last_grid4_pad0_clip999_lora.pt",
    "mass": CKPT / "mammo_mass_trunk_last_grid4_pad0_clip999_lora.pt"}


def find_col(df, *keys):
    """
    컬럼 이름을 추측하지 않고 찾는다.

    인덱스 CSV 는 CBIS 원본 라벨을 그대로 물려받아서 이름이 판마다 다르다
    ('pathology' 가 없어서 KeyError 를 낸 적이 있다). 없으면 없는 대로 둔다.
    """
    low = {c.lower(): c for c in df.columns}
    for k in keys:
        if k.lower() in low:
            return low[k.lower()]
    for k in keys:
        for c in df.columns:
            if k.lower() in c.lower():
                return c
    return None


def axis_of(col):
    return col.split("__", 1)[0]


def name_of(col):
    return col.split("__", 1)[1]


@torch.no_grad()
def run(ext, head, cfg, ds, rows, batch, device):
    """행 목록을 받아 확률을 돌려준다. 행 순서를 유지한다."""
    out, buf, keep = [], [], []

    def flush():
        if not buf:
            return
        x = torch.stack(buf).to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logit = head(pool_feats(ext(x), cfg["pool"], cfg["levels"],
                                    cfg["grid"]))
        p = torch.sigmoid(logit.float()).cpu().numpy()
        for k, r in enumerate(keep):
            out.append((r, p[k]))
        buf.clear(); keep.clear()

    for r in rows:
        a = ds._read_roi(r["roi_file"])
        if a is None:                 # 이진 = 마스크를 ROI 로 잘못 고른 행
            continue
        img = ds._resize(torch.from_numpy(a)[None, None])[0].repeat(3, 1, 1)
        buf.append((img - 0.5) / 0.5)
        keep.append(r)
        if len(buf) == batch:
            flush()
    flush()
    return out


def show(r, prob, cols, slices, thr, always, R, kind, idx, meta):
    gt = gt_onehot(np.array([float(r[c]) for c in cols]), cols)
    pr = to_onehot(prob, cols, slices, thr, always)
    g_cat = to_category(R, level_of(R, kind, gt))
    p_cat = to_category(R, level_of(R, kind, pr))
    truth = r.get(meta["assess"]) if meta["assess"] else None
    truth = float(truth) if truth is not None and truth == truth else None

    uid = str(r.get("roi_file", "")).split("/")[-2][:28]
    patho = str(r.get(meta["patho"], "?")) if meta["patho"] else "?"
    print(f"\n  [{idx}] {uid}")
    print(f"      병리 {patho[:18]:18s}"
          f" 정답 등급 {int(truth) if truth is not None else '—'}")
    print(f"      {'축':6s}{'정답':22s}{'예측':22s}{'확률':>6s}")
    print("      " + "-" * 56)
    for ax, (s, e) in slices.items():
        g = next((name_of(c) for c in cols[s:e] if gt.get(c)), "—")
        pi = int(np.argmax(prob[s:e]))
        pname = cols[s + pi]
        p = float(prob[s + pi])
        taken = pr.get(pname) == 1
        mark = "  ✓" if (taken and name_of(pname) == g) else \
               ("" if taken else "  (버림)")
        pshow = name_of(pname) if taken else "—"
        print(f"      {AXIS_KO.get(ax, ax):6s}{g:22s}{pshow:22s}{p:6.2f}{mark}")

    def line(tag, cat):
        b = cat is not None and cat >= BIOPSY_CUT
        return (f"      {tag:14s} BI-RADS {cat if cat is not None else '—'}"
                f"  {GRADE_KO.get(cat, '') if cat is not None else '판정 불가':10s}"
                f"  {'조직검사' if b else '추적'}")
    print(line("정답 서술어", g_cat))
    print(line("예측 서술어", p_cat))
    ok = (p_cat is not None and truth is not None
          and (p_cat >= BIOPSY_CUT) == (truth >= BIOPSY_CUT))
    print(f"      {'조직검사 판단 ' + ('일치' if ok else '불일치'):20s}"
          f"(정답 등급 {int(truth) if truth is not None else '—'})")
    return dict(gt_cat=g_cat, pred_cat=p_cat, truth=truth, ok=ok)


def montage(ds, rows, out, size=256, cols_n=4):
    """조각들을 격자로 붙여 한 장으로 만든다. 발표 슬라이드에 바로 쓸 수 있다."""
    try:
        import cv2
    except ImportError:
        print("  ! cv2 가 없어 이미지를 못 만든다")
        return
    tiles = []
    for i, r in enumerate(rows, 1):
        a = ds._read_roi(r["roi_file"])
        if a is None:
            continue
        im = (np.clip(a, 0, 1) * 255).astype(np.uint8)
        h, w = im.shape
        s = size / max(h, w)
        im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))))
        pad = np.zeros((size, size), np.uint8)
        y0, x0 = (size - im.shape[0]) // 2, (size - im.shape[1]) // 2
        pad[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
        pad = cv2.cvtColor(pad, cv2.COLOR_GRAY2BGR)
        cv2.putText(pad, f"#{i}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 220, 255), 2, cv2.LINE_AA)
        tiles.append(pad)
    if not tiles:
        return
    rows_n = (len(tiles) + cols_n - 1) // cols_n
    while len(tiles) < rows_n * cols_n:
        tiles.append(np.zeros_like(tiles[0]))
    grid = np.vstack([np.hstack(tiles[r * cols_n:(r + 1) * cols_n])
                      for r in range(rows_n)])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid)
    print(f"\n  조각 이미지 -> {out}   ({grid.shape[1]}x{grid.shape[0]})")
    print("    번호가 위 표의 [n] 과 같다.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="calc", choices=["calc", "mass"])
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--uid", default="", help="특정 시리즈 UID 만 본다")
    ap.add_argument("--only-wrong", action="store_true",
                    help="조직검사 판단이 틀린 것만 남겨 보여준다")
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--always", default="shape,margin,calctype,calcdist")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--png", default="")
    a = ap.parse_args()
    always = {s.strip() for s in a.always.split(",") if s.strip()}
    ck = Path(a.ckpt) if a.ckpt else DEFAULT_CKPT[a.kind]

    print("=" * 74)
    print(f"서술어 낱개 보기 — {a.kind} · {a.split}")
    print("=" * 74)

    R = import_rules(a.rules)
    ext, head, cfg = build_model(str(ck), "cuda")
    schema = load_schema(SCHEMA)
    slices = axis_slices(schema, a.kind)
    cols = cfg["cols"]

    csv = ROI_INDEX / f"roi_index_{a.kind}_{a.split}.csv"
    ds = MammoROIDataset(csv, SCHEMA, a.kind, size=cfg["size"], augment=False,
                         pad_square=cfg["pad"], clip_pct=cfg["clip"])
    df = ds.df
    meta = dict(assess=find_col(df, "assessment", "assess", "birads"),
                patho=find_col(df, "pathology", "patho"))
    print(f"  등급 컬럼 {meta['assess'] or '없음'} · 병리 컬럼 {meta['patho'] or '없음'}")
    if not meta["assess"]:
        print("  ! 등급 컬럼이 없다 — 예측만 보여주고 정답과는 비교하지 않는다")
    if a.uid:
        df = df[df.roi_file.astype(str).str.contains(a.uid)]
        if not len(df):
            sys.exit(f"그 UID 의 행이 없다: {a.uid}")
    # 틀린 것만 볼 때는 더 넉넉히 돌려서 골라낸다
    take = df.sample(min(len(df), a.n * (6 if a.only_wrong else 1)),
                     random_state=a.seed) if len(df) > a.n else df
    print(f"  조각 {len(take)}건 읽는다 (전체 {len(df)}건)")

    got = run(ext, head, cfg, ds, take.to_dict("records"), a.batch, "cuda")
    print(f"  판정 {len(got)}건")

    shown, picked = 0, []
    for r, prob in got:
        if shown >= a.n:
            break
        if a.only_wrong:
            # 먼저 조용히 채점해서 틀린 것만 고른다
            gt = gt_onehot(np.array([float(r[c]) for c in cols]), cols)
            pc = to_category(R, level_of(R, a.kind,
                                         to_onehot(prob, cols, slices,
                                                   a.thr, always)))
            t = r.get(meta["assess"]) if meta["assess"] else None
            t = float(t) if t is not None and t == t else None
            if pc is not None and t is not None and \
               (pc >= BIOPSY_CUT) == (t >= BIOPSY_CUT):
                continue
        shown += 1
        picked.append(r)
        show(r, prob, cols, slices, a.thr, always, R, a.kind, shown, meta)

    if not shown:
        print("\n  보여줄 것이 없다"
              + (" — 고른 표본이 전부 맞았다" if a.only_wrong else ""))
        return

    print("\n" + "=" * 74)
    print("읽는 법")
    print("=" * 74)
    print("  '축' 마다 확률 최고 클래스를 고른다. 규칙표가 축별로 하나씩 받기")
    print("  때문이다. 다만 소견(finding)처럼 대부분의 사진에 없는 축은 확률이")
    print(f"  {a.thr} 미만이면 비운다 — 없는 소견을 만들어내지 않으려는 것이다.")
    print("  '(버림)' 이 그 경우다.")
    print("\n  '정답 서술어' 줄과 '예측 서술어' 줄이 갈리면 서술어 예측이 틀린")
    print("  것이고, 둘이 같은데 정답 등급과 다르면 규칙표의 한계다.")
    print("  같은 서술어 조합이 실제로 여러 등급에 걸쳐 있어서, 어떤 규칙표로도")
    print("  그만큼은 못 맞힌다(측정한 상한 71.9%).")

    if a.png:
        montage(ds, picked, a.png)


if __name__ == "__main__":
    main()
