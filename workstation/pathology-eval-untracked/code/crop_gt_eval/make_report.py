#!/usr/bin/env python3
"""리포트: 분석 1·2 결과 -> results/summary.md + 대표 이미지 3장.

대표 이미지 (원본 | GT 마스크 | nearest | bilinear 4단, 모든 패널 위에 GT/AI 점):
  good  = bilinear 간질 Dice 최고 (동률이면 GT 점 많은 순 -> GT 간질 면적 큰 순)
  bad   = GT 간질이 크롭의 5% 이상인 것 중 bilinear 간질 Dice 최저
  dense = 밀도 상위(high) 구간에서 1:1 recall 최저 (동률이면 GT 점 많은 순)
색은 test_single_image.CLASS_COLORS (정본) 를 import — 아래 SPEC 과 다르면 중단.
점: GT = 링(반경 = 매칭 반경 15px), 1:1 매칭됨 흰색 / 놓침 노랑
    AI(p_til>=0.5) = 점, 1:1 매칭됨 초록 / 매칭 안 됨 자홍

conclusion.md (이 폴더) 가 있으면 summary.md 끝에 붙인다 — 수치 확인 후 사람이 쓰는 해석.

실행: ~/miniconda3/envs/cellvitpp/bin/python code/crop_gt_eval/make_report.py
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
from scipy.stats import mannwhitneyu, wilcoxon

import common as C
import test_single_image as tsi  # noqa: E402  (색 정본 + 시각화 헬퍼, serving 은 import 안 됨)

SPEC = {0: (128, 128, 128), 1: (230, 50, 50), 2: (40, 110, 255)}
assert {k: tuple(v) for k, v in tsi.CLASS_COLORS.items()} == SPEC, \
    f"CLASS_COLORS 가 지정 색과 다름: {tsi.CLASS_COLORS}"

GT_OK, GT_MISS = (255, 255, 255), (255, 214, 0)
AI_OK, AI_FP = (0, 230, 118), (255, 64, 255)
MIN_SIDE = 420            # 작은 크롭은 이 크기까지 nearest 확대해서 그림 (점 좌표도 같이 스케일)
R = C.MATCH_RADIUS
NUC_R = 8.0              # 병합 판정 반경: 림프구 핵 반지름 규모 (~4µm @0.5mpp)
OUT = C.RESULTS


def f3(x):
    return "–" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.3f}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


# ───────────────────────── 이미지 ─────────────────────────
def draw_points(arr: np.ndarray, pts: dict, s: float) -> np.ndarray:
    im = Image.fromarray(arr)
    d = ImageDraw.Draw(im)
    rr = R * s
    for k, (x, y) in enumerate(pts["gt"]):
        c = GT_OK if k in pts["gt_matched"] else GT_MISS
        d.ellipse([x * s - rr, y * s - rr, x * s + rr, y * s + rr], outline=c, width=2)
    dr = max(2.5, 3 * s ** 0.5)
    for k, (x, y) in enumerate(pts["ai"]):
        c = AI_OK if k in pts["ai_matched"] else AI_FP
        d.ellipse([x * s - dr, y * s - dr, x * s + dr, y * s + dr], fill=c, outline=(0, 0, 0))
    return np.array(im)


def example_figure(kind: str, s1: pd.Series, s2: pd.Series) -> Image.Image:
    cid, stem = s1.crop_id, s1.stem
    img = np.array(C.load_image(stem))
    H, W = img.shape[:2]
    masks = {t: np.array(Image.open(OUT / "socket1_masks" / f"{cid}_{t}.png"))
             for t in ("gt", "nearest", "bilinear")}
    pj = json.loads((OUT / "socket2_points" / f"{cid}.json").read_text())
    ai_cells = [c for c in pj["cells"] if c["p_til"] >= pj["til_thr"]]
    pts = {"gt": pj["gt_points"], "ai": [(c["cx"], c["cy"]) for c in ai_cells],
           "gt_matched": {m[0] for m in pj["matches_1to1"]},
           "ai_matched": {m[1] for m in pj["matches_1to1"]}}

    s = max(1.0, MIN_SIDE / min(H, W))
    size = (round(W * s), round(H * s))

    def up(a):
        return np.array(Image.fromarray(a).resize(size, Image.NEAREST))

    base = up(img)
    panels = [
        ("original", base),
        ("GT mask", tsi.overlay(base, up(masks["gt"]))),
        (f"nearest  stroma Dice {f3(s1.stroma_dice_nearest)}", tsi.overlay(base, up(masks["nearest"]))),
        (f"bilinear stroma Dice {f3(s1.stroma_dice_bilinear)}", tsi.overlay(base, up(masks["bilinear"]))),
    ]
    row = tsi.hstack([tsi.labeled_panel(draw_points(a, pts, s), t) for t, a in panels], gap=6)
    row = tsi.hstack([row, tsi.legend_panel(row.height, masks["gt"])], gap=0)

    head_h = 58
    out = Image.new("RGB", (row.width, row.height + head_h), (24, 24, 27))
    out.paste(row, (0, head_h))
    d = ImageDraw.Draw(out)
    d.text((10, 8), f"[{kind}] {cid}  {W}x{H}px  {'socket2-train' if s1.in_socket2_train else 'socket2-UNSEEN'}"
           f"  GT stroma {s1.gt_stroma_frac * 100:.1f}%  density {s2.density_per_mm2:.0f}/mm2 ({s2.density_bin})",
           fill=(240, 240, 240), font=tsi._font(16))
    d.text((10, 32), f"GT pts {s2.n_gt}  AI TIL {s2.n_ai}  TP(1:1) {s2.tp_1to1}  "
           f"recall 1:1 {f3(s2.recall_1to1)} / radius {f3(s2.recall_radius)}   "
           f"ring=GT(r={R:.0f}px) white=matched yellow=missed | dot=AI green=matched magenta=unmatched",
           fill=(190, 190, 200), font=tsi._font(13))
    return out


# ───────────────────────── 집계 ─────────────────────────
def rp(sub: pd.DataFrame) -> dict:
    t = sub[["n_gt", "n_ai", "tp_1to1", "gt_hit_radius", "ai_hit_radius"]].sum()
    div = lambda a, b: a / b if b else np.nan  # noqa: E731
    return {"crops": len(sub), "GT": int(t.n_gt), "AI": int(t.n_ai),
            "recall 1:1": f3(div(t.tp_1to1, t.n_gt)), "prec 1:1": f3(div(t.tp_1to1, t.n_ai)),
            "recall 반경": f3(div(t.gt_hit_radius, t.n_gt)), "prec 반경": f3(div(t.ai_hit_radius, t.n_ai))}


def merge_area_rows(s2: pd.DataFrame) -> list[dict]:
    """AI TIL 점 반경 NUC_R 안의 GT 핵 수로 나눠 segment 면적 비교 — 병합이면 >=2 쪽이 커야 한다."""
    rows = []
    for b in ("low", "mid", "high"):
        one, multi = [], []
        for cid in s2.loc[s2.density_bin == b, "crop_id"]:
            j = json.loads((OUT / "socket2_points" / f"{cid}.json").read_text())
            g = np.asarray(j["gt_points"], float).reshape(-1, 2)
            ai = [c for c in j["cells"] if c["p_til"] >= j["til_thr"]]
            if not ai or not len(g):
                continue
            cnt = [len(x) for x in cKDTree(g).query_ball_point([[c["cx"], c["cy"]] for c in ai], NUC_R)]
            for c, k in zip(ai, cnt):
                (multi if k >= 2 else one if k == 1 else []).append(c["area_px"])
        p = mannwhitneyu(multi, one).pvalue if len(multi) > 3 else np.nan
        n_ai = int(s2.loc[s2.density_bin == b, "n_ai"].sum())
        rows.append({"밀도": {"low": "하", "mid": "중", "high": "상"}[b],
                     "GT 1개 덮는 AI": f"{len(one)} (중앙 {np.median(one):.0f}px²)",
                     "GT ≥2개 덮는 AI": f"{len(multi)} (중앙 {np.median(multi):.0f}px²)" if multi else "0",
                     "≥2 비중(전체 AI TIL 대비)": f"{len(multi) / max(1, n_ai) * 100:.1f}%",
                     "면적비 ≥2/1": f"{np.median(multi) / np.median(one):.2f}" if multi else "–",
                     "Mann-Whitney p": "–" if np.isnan(p) else f"{p:.1g}"})
    return rows


def main():
    s1 = pd.read_csv(OUT / "socket1_crop_gt.csv")
    # density_bin 의 "NA" 문자열이 NaN 으로 읽히지 않게
    s2 = pd.read_csv(OUT / "socket2_crop_gt.csv", keep_default_na=False, na_values=[""])
    pooled = json.loads((OUT / "socket1_pooled.json").read_text())
    meta2 = json.loads((OUT / "socket2_meta.json").read_text())
    assert len(s1) == len(s2) == C.EXPECTED_N_VAL and (s1.crop_id == s2.crop_id).all()
    n_ov = int(s1.in_socket2_train.sum())
    L = []
    L += ["# 크롭 단위 GT 검증 — 조직분할(socket1) · 림프구 검출(socket2)", "",
          f"- 대상: TIGER tissue-cells 조직분할 val **{len(s1)}장** "
          f"(remap_tissue_masks.py split 재현: sorted → Random(42).shuffle → 15%)",
          f"- socket2 학습셋(`cellvit_detection/splits/fold_0/train.csv`)과 겹침 **{n_ov}장** "
          f"(재현됨), 학습 미사용 **{len(s1) - n_ov}장**",
          "- GT 마스크: 7-class → REMAP 3-class (0 기타 / 1 종양 / 2 간질), 원본 해상도",
          f"- 크롭 크기: 최장변 중앙 {int(np.median(np.maximum(s1.W, s1.H)))}px, "
          f">512px 크롭 {int((np.maximum(s1.W, s1.H) > 512).sum())}장", ""]

    # ── 분석 1
    pd_ = pooled["pooled_dice"]
    t1 = pd.DataFrame([
        {"평가 기준": "16×16 격자 (기존 보고 방식)", "기타": f3(pd_["grid16"]["other"]),
         "종양": f3(pd_["grid16"]["tumor"]), "간질": f3(pd_["grid16"]["stroma"]),
         "pixel acc(크롭평균)": f3(pooled["pixel_acc_16_mean"])},
        {"평가 기준": "원본 해상도 · nearest (현 서빙)", "기타": f3(pd_["nearest"]["other"]),
         "종양": f3(pd_["nearest"]["tumor"]), "간질": f3(pd_["nearest"]["stroma"]),
         "pixel acc(크롭평균)": f3(pooled["pixel_acc_full_mean"]["nearest"])},
        {"평가 기준": "원본 해상도 · bilinear (수정안)", "기타": f3(pd_["bilinear"]["other"]),
         "종양": f3(pd_["bilinear"]["tumor"]), "간질": f3(pd_["bilinear"]["stroma"]),
         "pixel acc(크롭평균)": f3(pooled["pixel_acc_full_mean"]["bilinear"])},
    ])
    L += ["## 1. 조직분할 정확도 (분석 1)", "",
          f"> **기존 Dice 0.904 는 16×16 격자 기준** (GT 를 16×16 으로 NEAREST 축소해 비교). "
          f"이번 재현값 {f3(pd_['grid16']['stroma'])}. "
          f"같은 예측을 원본 해상도로 올려 원본 GT 와 비교하면 간질 Dice 는 "
          f"nearest **{f3(pd_['nearest']['stroma'])}** / bilinear **{f3(pd_['bilinear']['stroma'])}**.", "",
          "### 1-1. Pooled Dice (281장 전체 픽셀 누적, evaluate_socket1_dice.py 방식)", "", md_table(t1), ""]

    big = np.maximum(s1.W, s1.H) > 512
    px = s1.W * s1.H
    rows = []
    for cls in ("stroma", "tumor"):
        for name, m in (("전체", np.ones(len(s1), bool)), ("≤512px", ~big), (">512px", big)):
            a, b = s1.loc[m, f"{cls}_dice_nearest"], s1.loc[m, f"{cls}_dice_bilinear"]
            ok = a.notna() & b.notna()
            diff = (b - a)[ok]
            p = wilcoxon(b[ok], a[ok]).pvalue if (diff.abs() > 1e-12).sum() >= 5 else np.nan
            rows.append({"클래스": {"stroma": "간질", "tumor": "종양"}[cls], "크롭": name,
                         "n(정의됨)": int(ok.sum()), "픽셀 비중": f"{px[m].sum() / px.sum() * 100:.0f}%",
                         "평균 near": f3(a[ok].mean()), "평균 bil": f3(b[ok].mean()),
                         "중앙 near": f3(a[ok].median()), "중앙 bil": f3(b[ok].median()),
                         "bil↑/↓/=": f"{(diff > 1e-9).sum()}/{(diff < -1e-9).sum()}/{(diff.abs() <= 1e-9).sum()}",
                         "Wilcoxon p": "–" if np.isnan(p) else f"{p:.1g}",
                         "16×16 중앙": f3(s1.loc[m, f'{cls}_dice_16'].median())})
    L += ["### 1-2. 크롭별 Dice (nearest vs bilinear, 같은 로짓)", "",
          "크롭 Dice 는 GT·예측 모두 해당 클래스가 없으면 정의 불가(제외). "
          "Wilcoxon = 대응표본 부호순위 검정(bilinear vs nearest).", "", md_table(pd.DataFrame(rows)), ""]
    ar = s1[s1.gt_stroma_frac > 0]
    L += [f"- 간질 면적 비율 AI/GT (GT 간질>0 인 {len(ar)}장) 중앙값: nearest "
          f"{ar.stroma_area_ratio_nearest.median():.3f}, bilinear {ar.stroma_area_ratio_bilinear.median():.3f}; "
          f"GT 간질≥5% 크롭에서 AI/GT < 0.5 인 크롭: nearest "
          f"{int((s1[s1.gt_stroma_frac >= .05].stroma_area_ratio_nearest < .5).sum())}, bilinear "
          f"{int((s1[s1.gt_stroma_frac >= .05].stroma_area_ratio_bilinear < .5).sum())}",
          f"- nearest 와 bilinear 가 다른 픽셀 비율 (크롭 평균): {s1.near_bil_pixel_diff_frac.mean() * 100:.1f}%", ""]

    # ── 분석 2
    q1, q2 = meta2["density_cutoffs_per_mm2"]
    subsets = (("전체 281", np.ones(len(s2), bool)), ("socket2 학습 미사용", ~s2.in_socket2_train.values))
    t2 = []
    for sname, sm in subsets:
        for b in ("low", "mid", "high", "NA", "all"):
            m = sm & ((s2.density_bin == b).values if b != "all" else True)
            t2.append({"대상": sname, "밀도 구간": {"low": "하", "mid": "중", "high": "상",
                                                "NA": "N/A(GT간질 0 또는 GT점 0)", "all": "**합계**"}[b],
                       **rp(s2[m])})
    L += ["## 2. 림프구 검출 recall (분석 2)", "",
          f"GT 점 = tiger-coco.json bbox 중심, AI 점 = p_til ≥ {meta2['til_thr']} 세포 중심, "
          f"매칭 반경 {meta2['radius_px']:.0f}px. 밀도 = GT 점 수 / GT 간질 면적 "
          f"(mpp {meta2['mpp']}), 3분위 경계 {q1:.0f} / {q2:.0f} 개/mm² (전체 281 중 밀도 정의되는 크롭 기준). "
          "recall·precision 은 크롭 합산(micro).", "",
          "- **1:1** = 거리순 그리디 1:1 매칭 (기본) / **반경** = 반경 안에 상대 점이 하나라도 있으면 hit (비교용)",
          "", md_table(pd.DataFrame(t2)), ""]

    t3 = []
    for sname, sm in subsets:
        for b in ("low", "mid", "high"):
            sub = s2[sm & (s2.density_bin == b).values]
            miss = sub[["miss_taken", "miss_nontil", "miss_nodet"]].sum()
            nm = int(miss.sum())
            rec = sub.recall_1to1.dropna()
            t3.append({"대상": sname, "밀도": {"low": "하", "mid": "중", "high": "상"}[b],
                       "크롭 recall 중앙(1:1)": f3(rec.median()),
                       "놓친 GT": nm,
                       "선점됨(병합 또는 인접 누락)": f"{miss.miss_taken / nm * 100:.0f}%" if nm else "–",
                       "p_til<0.5 로 탈락": f"{miss.miss_nontil / nm * 100:.0f}%" if nm else "–",
                       "검출 없음": f"{miss.miss_nodet / nm * 100:.0f}%" if nm else "–",
                       "GT≥2개 덮는 AI점(15px, 간격효과 포함)": f"{sub.ai_multi_gt.sum() / max(1, sub.n_ai.sum()) * 100:.1f}%",
                       "AI/GT 개수비": f"{sub.n_ai.sum() / max(1, sub.n_gt.sum()):.2f}",
                       "TIL 핵면적 중앙(px²)": f"{sub.median_til_area_px.median():.0f}"})
    L += ["### 2-1. 1:1 에서 놓친 GT 의 원인 (핵 병합 가설 점검)", "",
          "- 선점됨: 반경 안에 TIL 점은 있으나 다른 GT 가 이미 가져감 → 한 검출이 여러 GT 를 덮음. "
          "병합일 수도, 이웃 세포를 그냥 못 찾은 것일 수도 있음 (2-2 에서 면적으로 구분)",
          "- p_til<0.5: 반경 안에 검출 세포는 있으나 비-TIL 로 분류 / 검출 없음: 반경 안에 세포 검출 자체가 없음",
          "", md_table(pd.DataFrame(t3)), ""]

    zero = s2[(s2.n_cells_all == 0) & (s2.n_gt > 0)]
    hi = s2[s2.density_bin == "high"]
    hi_nz = hi[hi.n_cells_all > 0]
    tot_cells = lambda d: d.n_cells_all.sum() / max(1, d.n_gt.sum())  # noqa: E731
    L += ["### 2-2. 병합 신호 직접 확인 — 검출 segment 면적", "",
          f"AI TIL 점마다 반경 {NUC_R:.0f}px(핵 반지름 규모) 안의 GT 핵 수로 나눠 CellViT contour 면적을 비교. "
          "핵 병합이면 GT ≥2개를 덮는 검출이 더 커야 한다. "
          "(15px 매칭 반경은 상위 구간 GT 최근접 간격 중앙값보다 커서 병합 판정엔 쓰지 않음)", "",
          md_table(pd.DataFrame(merge_area_rows(s2))), "",
          "- 전체 검출 세포 수 / GT 점 수 (p_til 무관): " + ", ".join(
              f"{k} {tot_cells(s2[s2.density_bin == b]):.2f}" for k, b in (("하", "low"), ("중", "mid"), ("상", "high"))),
          f"- 세포가 하나도 검출되지 않은 크롭 중 GT 점이 있는 것: {len(zero)}장 "
          f"({', '.join(f'{r.crop_id} GT {r.n_gt}점 [{r.density_bin}]' for r in zero.itertuples()) or '없음'}). "
          f"이를 빼면 상위 구간 recall 1:1 {hi_nz.tp_1to1.sum() / hi_nz.n_gt.sum():.3f} / "
          f"반경 {hi_nz.gt_hit_radius.sum() / hi_nz.n_gt.sum():.3f}", ""]

    # ── 대표 이미지
    m = s1.merge(s2.drop(columns=["stem", "W", "H", "in_socket2_train"]), on="crop_id")
    good = m.dropna(subset=["stroma_dice_bilinear"]).sort_values(
        ["stroma_dice_bilinear", "n_gt", "gt_stroma_frac"], ascending=[False, False, False]).iloc[0]
    n_tie = int((m.stroma_dice_bilinear >= good.stroma_dice_bilinear - 1e-12).sum())
    bad = m[m.gt_stroma_frac >= 0.05].dropna(subset=["stroma_dice_bilinear"]).sort_values(
        ["stroma_dice_bilinear", "n_gt"], ascending=[True, False]).iloc[0]
    dense = m[(m.density_bin == "high") & (m.n_gt > 0)].sort_values(
        ["recall_1to1", "n_gt"], ascending=[True, False]).iloc[0]
    L += ["## 3. 대표 이미지", "",
          "원본 | GT 마스크 | nearest | bilinear (+ 색 범례). "
          "링 = GT 점(반경 15px, 흰=매칭/노랑=놓침), 점 = AI TIL(초록=매칭/자홍=미매칭). "
          "작은 크롭은 짧은 변 420px 까지 nearest 확대.", ""]
    for kind, row, why in (
            ("good", good, f"bilinear 간질 Dice 최고 ({f3(good.stroma_dice_bilinear)}; 동률 {n_tie}장 → GT 점 많은 순)"),
            ("bad", bad, f"GT 간질≥5% 중 bilinear 간질 Dice 최저 ({f3(bad.stroma_dice_bilinear)})"),
            ("dense", dense, f"밀도 상위 구간 중 1:1 recall 최저 ({f3(dense.recall_1to1)}, GT {dense.n_gt}점)")):
        p = OUT / f"example_{kind}.png"
        example_figure(kind, s1[s1.crop_id == row.crop_id].iloc[0], s2[s2.crop_id == row.crop_id].iloc[0]).save(p)
        L += [f"- **{kind}** — {why}: `{row.crop_id}` `{row.stem}`", f"  ![{kind}]({p.name})"]
        print("saved", p)
    L += [""]

    concl = C.HERE / "conclusion.md"
    if concl.exists():
        L += [concl.read_text().rstrip(), ""]
    L += ["---", f"생성: make_report.py · 원자료 socket1_crop_gt.csv / socket2_crop_gt.csv · "
          f"fp16 socket1={pooled['fp16']} socket2={meta2['fp16']}"]
    (OUT / "summary.md").write_text("\n".join(L) + "\n")
    print("saved", OUT / "summary.md")


if __name__ == "__main__":
    main()
