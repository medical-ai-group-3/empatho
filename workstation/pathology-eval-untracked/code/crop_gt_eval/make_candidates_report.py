#!/usr/bin/env python3
"""eval_socket1_candidates.py 결과 -> results/candidates_summary.md (GPU 불필요).

기준(reference) = lin_nearest (현재 서빙). 크롭 그룹: 전체 / ≤512px / >512px (최장변).
  - pooled Dice: 그룹 전체 픽셀 누적 (2I)/(P+T)
  - 부트스트랩: 크롭 재표집 B=2000 (seed 0), pooled 간질 Dice 차이(방식 − 기준) 95% 백분위 구간
  - 대응표본: 크롭별 간질/종양 Dice, 둘 다 정의된 크롭만, Wilcoxon 부호순위
실행: ~/miniconda3/envs/cellvitpp/bin/python code/crop_gt_eval/make_candidates_report.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

import common as C

REF = "lin_nearest"
METHODS = ["lin_nearest", "lin_bilinear", "lin_tiled", "dpt", "effunet", "ptc"]
LABEL = {"lin_nearest": "(1) linear_tand · nearest [현 서빙]",
         "lin_bilinear": "(1) linear_tand · bilinear",
         "lin_tiled": "(2a) linear_tand · 224 조각(원본 배율)",
         "dpt": "(0) DPT", "effunet": "(0) EfficientNet-UNet", "ptc": "(0) PTC-EfficientUNet"}
SEL_KEY = {"lin_nearest": "lin@16", "lin_bilinear": "lin@16", "dpt": "dpt@224",
           "effunet": "effunet@224", "ptc": "ptc@224"}
B, SEED = 2000, 0
OUT = C.RESULTS


def f3(x):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"


def md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    return "\n".join(["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
                     + ["| " + " | ".join(str(v) for v in r) + " |" for r in df.itertuples(index=False)])


def pooled(d: pd.DataFrame, m: str, c: int, pre: str = "") -> float:
    i, p, t = (d[f"{m}_{pre}{k}{c}"].sum() for k in "IPT")
    return 2 * i / (p + t) if (p + t) else np.nan


def boot_diff(d: pd.DataFrame, m: str, c: int, rng, ref: str = REF) -> tuple[float, float, float]:
    """pooled Dice(m) − pooled Dice(ref), 크롭 재표집."""
    arr = {k: d[[f"{mm}_{k}{c}" for mm in (m, ref)]].to_numpy(float) for k in "IPT"}
    idx = rng.integers(0, len(d), size=(B, len(d)))
    s = {k: arr[k][idx].sum(1) for k in "IPT"}               # (B, 2)
    dice = 2 * s["I"] / (s["P"] + s["T"])
    diff = dice[:, 0] - dice[:, 1]
    return float(np.nanmean(diff)), *np.nanpercentile(diff, [2.5, 97.5])


def main():
    d = pd.read_csv(OUT / "cand_crop.csv")
    sel = json.loads((OUT / "cand_selection.json").read_text())
    s1 = json.loads((OUT / "socket1_pooled.json").read_text())
    groups = {"전체": np.ones(len(d), bool), "≤512px": ~d.big.values, ">512px": d.big.values}
    px = d.W * d.H
    L = ["# 조직분할 후보 원본 해상도 비교 — 재학습 없이", "",
         f"- val {len(d)}장 (crop_gt_eval 분석1 과 동일), GT 7-class → REMAP 3-class 원본 해상도",
         f"- 크롭 그룹: ≤512px {int((~d.big).sum())}장 (픽셀 {px[~d.big].sum() / px.sum() * 100:.0f}%) / "
         f">512px {int(d.big.sum())}장 (픽셀 {px[d.big].sum() / px.sum() * 100:.0f}%)",
         "- 인코더 Virchow2 fp16, 헤드 fp32. 기준(reference) = **lin_nearest (현 서빙)**",
         "- ⚠ 모든 체크포인트는 이 281장 val_acc 로 best epoch 를 고른 것 — 절대값은 모두 약간 낙관적(조건 동일).", ""]

    # 1. 해상도별 순위
    rows = []
    for m in METHODS:
        k = SEL_KEY.get(m)
        rows.append({"방식": LABEL[m],
                     "선정 당시 기준": {"lin@16": "16×16", None: "–"}.get(k, "224×224"),
                     "선정기준 간질": f3(sel[k]["stroma"]) if k else "–",
                     "선정기준 종양": f3(sel[k]["tumor"]) if k else "–",
                     "16×16 공통 간질": f3(pooled(d, m, 2, "g16")),
                     "16×16 공통 종양": f3(pooled(d, m, 1, "g16")),
                     "원본해상도 간질": f3(pooled(d, m, 2)), "원본해상도 종양": f3(pooled(d, m, 1)),
                     "원본해상도 기타": f3(pooled(d, m, 0))})
    t = pd.DataFrame(rows)
    for col in ("선정기준 간질", "16×16 공통 간질", "원본해상도 간질"):
        v = pd.to_numeric(t[col], errors="coerce")
        rk = v.rank(ascending=False, method="min")
        t[col] = [f"{s} ({int(r)}위)" if not np.isnan(r) else s for s, r in zip(t[col], rk)]
    L += ["## 1. 평가 해상도에 따라 순위가 바뀌는가 (pooled Dice, 281장)", "",
          "- **선정 당시 기준**: evaluate_socket1_dice.py 재현 — linear 계열은 16×16, 나머지는 224×224 "
          "(크롭 전체를 224로 축소한 격자). 즉 DPT 등은 처음부터 16×16 이 아니라 224×224 로 선정됐다.",
          "- **16×16 공통**: 모든 방식의 확률을 16×16 으로 면적 평균해 같은 격자에서 비교.",
          "- **원본해상도**: 원본 크롭 크기로 올려 원본 GT 와 비교 (sTIL 분모가 실제로 쓰는 해상도).",
          f"- 참고: 분석1(fp32) 재현값 — 16×16 간질 {f3(s1['pooled_dice']['grid16']['stroma'])}, "
          f"원본 nearest {f3(s1['pooled_dice']['nearest']['stroma'])} / bilinear {f3(s1['pooled_dice']['bilinear']['stroma'])}",
          "", md(t), ""]

    # 2. 그룹별 pooled 간질 Dice + 부트스트랩 차이
    rng = np.random.default_rng(SEED)
    rows = []
    for m in METHODS:
        r = {"방식": LABEL[m]}
        for g, gm in groups.items():
            dg = d[gm]
            base = f"{f3(pooled(dg, m, 2))}"
            if m != REF:
                mu, lo, hi = boot_diff(dg, m, 2, rng)
                base += f" (Δ {mu:+.3f} [{lo:+.3f}, {hi:+.3f}])"
            r[f"간질 {g}"] = base
        rows.append(r)
    L += ["## 2. 크기 그룹별 pooled 간질 Dice (Δ = 기준 대비, 부트스트랩 95% 구간)", "",
          f"크롭 재표집 {B}회. 구간이 0 을 넘지 않으면 기준보다 확실히 낫거나(양수)/못함(음수).", "", md(pd.DataFrame(rows)), ""]
    rows = []
    for m in METHODS:
        r = {"방식": LABEL[m]}
        for g, gm in groups.items():
            dg = d[gm]
            base = f3(pooled(dg, m, 1))
            if m != REF:
                mu, lo, hi = boot_diff(dg, m, 1, rng)
                base += f" (Δ {mu:+.3f} [{lo:+.3f}, {hi:+.3f}])"
            r[f"종양 {g}"] = base
        rows.append(r)
    L += ["### 2-1. 같은 방식, pooled 종양 Dice", "", md(pd.DataFrame(rows)), ""]

    rows = []
    for m in ("lin_tiled", "dpt", "effunet", "ptc"):
        r = {"방식": LABEL[m]}
        for c, nm in ((2, "간질"), (1, "종양")):
            for g in ("전체", ">512px"):
                mu, lo, hi = boot_diff(d[groups[g]], m, c, rng, ref="lin_bilinear")
                r[f"{nm} {g}"] = f"{mu:+.3f} [{lo:+.3f}, {hi:+.3f}]"
        rows.append(r)
    L += ["### 2-2. lin_bilinear (재학습 없는 수정안) 대비 pooled Dice 차이", "",
          "교체 후보는 비용 없는 bilinear 보다 나아야 의미가 있다.", "", md(pd.DataFrame(rows)), ""]

    z = d[d.gt_stroma_px == 0]
    rows = []
    for m in METHODS:
        fp = z[f"{m}_P2"] / (z.W * z.H)
        rows.append({"방식": LABEL[m], "크롭 수": len(z),
                     "간질 오검출 크롭(>1%)": int((fp > 0.01).sum()),
                     "오검출 면적 합 / 크롭 면적 합": f"{z[f'{m}_P2'].sum() / (z.W * z.H).sum() * 100:.1f}%",
                     ">512 중 오검출 크롭": f"{int((fp[z.big] > 0.01).sum())}/{int(z.big.sum())}",
                     "최대": f"{fp.max() * 100:.0f}%"})
    L += ["### 2-3. GT 간질이 없는 크롭의 간질 오검출 (크롭별 Dice 가 못 잡는 실패)", "",
          "GT·예측 둘 다 간질이 없으면 크롭 Dice 가 정의되지 않아 3절 대응표본에서 빠진다. "
          "그 크롭에서 예측이 간질을 만들면 sTIL 분모가 생겨 '평가 불가'가 '값 있음'으로 바뀐다.", "",
          md(pd.DataFrame(rows)), ""]

    # 3. 크롭별 대응표본
    rows = []
    for cls, nm in (("stroma", "간질"), ("tumor", "종양")):
        for g, gm in groups.items():
            dg = d[gm]
            ref = dg[f"{REF}_{cls}_dice"]
            for m in METHODS:
                v = dg[f"{m}_{cls}_dice"]
                ok = v.notna() & ref.notna()
                diff = (v - ref)[ok]
                if m == REF:
                    p, wl = "–", "–"
                else:
                    nz = (diff.abs() > 1e-12).sum()
                    p = f"{wilcoxon(v[ok], ref[ok]).pvalue:.1g}" if nz >= 5 else "–"
                    wl = f"{(diff > 1e-9).sum()}/{(diff < -1e-9).sum()}/{(diff.abs() <= 1e-9).sum()}"
                rows.append({"클래스": nm, "그룹": g, "방식": LABEL[m], "n": int(ok.sum()),
                             "평균": f3(v[ok].mean()), "중앙": f3(v[ok].median()),
                             "Δ중앙(대응)": "–" if m == REF else f"{diff.median():+.3f}",
                             "나음/못함/같음": wl, "Wilcoxon p": p})
    L += ["## 3. 크롭별 Dice (기준 대비 대응표본)", "",
          "크롭 Dice 는 GT·예측 모두 해당 클래스가 없으면 정의 불가(제외).", "", md(pd.DataFrame(rows)), ""]

    # 4. 간질 면적 AI/GT
    rows = []
    for m in METHODS:
        r = {"방식": LABEL[m]}
        for g, gm in groups.items():
            dg = d[gm & (d.gt_stroma_px > 0).values]
            ai = dg[f"{m}_P2"]
            ratio = ai / dg.gt_stroma_px
            r[f"{g} ΣAI/ΣGT"] = f"{ai.sum() / dg.gt_stroma_px.sum():.3f}"
            r[f"{g} 크롭 중앙"] = f"{ratio.median():.3f}"
        big5 = d[d.big & (d.gt_stroma_px > 0)]
        r[">512 크롭 AI/GT 범위"] = f"{(big5[f'{m}_P2'] / big5.gt_stroma_px).min():.2f}–{(big5[f'{m}_P2'] / big5.gt_stroma_px).max():.2f}"
        rows.append(r)
    L += ["## 4. 간질 면적 AI/GT (sTIL 분모) — GT 간질 > 0 인 크롭", "", md(pd.DataFrame(rows)), ""]

    # 5. 시간
    rows = []
    for m in METHODS:
        rows.append({"방식": LABEL[m],
                     "전체 중앙(ms)": f"{d[f'{m}_ms'].median():.1f}",
                     "≤512 중앙": f"{d.loc[~d.big, f'{m}_ms'].median():.1f}",
                     ">512 중앙": f"{d.loc[d.big, f'{m}_ms'].median():.1f}",
                     ">512 최대": f"{d.loc[d.big, f'{m}_ms'].max():.1f}"})
    L += ["## 5. 크롭당 추론 시간 (조직분할만, GPU 동기화 포함)", "",
          "lin/dpt/effunet/ptc 는 크롭 전체 입력이 같아 인코더 1회를 측정해 각자에 더함 (인코더 + 해당 헤드 + 업샘플). "
          "lin_tiled 는 조각 수만큼 인코더 반복. 이미지 로드·지표 계산 제외. fp16 인코더, 배치 ≤16.", "",
          f"- lin_tiled 조각 수: ≤512 중앙 {d.loc[~d.big, 'n_tiles'].median():.0f}, "
          f">512 중앙 {d.loc[d.big, 'n_tiles'].median():.0f} / 최대 {d.n_tiles.max()}", "",
          md(pd.DataFrame(rows)), ""]

    concl = C.HERE / "candidates_conclusion.md"
    if concl.exists():
        L += [concl.read_text().rstrip(), ""]
    L += ["---", "생성: make_candidates_report.py · 원자료 cand_crop.csv / cand_selection.json · 마스크 cand_masks/{방식}/"]
    (OUT / "candidates_summary.md").write_text("\n".join(L) + "\n")
    print("saved", OUT / "candidates_summary.md")


if __name__ == "__main__":
    main()
