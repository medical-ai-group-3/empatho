#!/usr/bin/env python
"""
끝에서 끝까지 — 사진 한 장에서 조직검사 판단까지 한 사슬로 잇는다.

  원본 사진 → 검출기 → 박스 → 잘라내기 → 서술어 → 규칙표 → 등급 → 조직검사 여부

왜 필요한가
  지금 두 시스템이 따로 논다. 서술어 쪽 숫자(조직검사 민감도 85.3%)는
  '병변 위치를 사람이 알려줬을 때' 의 값이다. 발표에서 그 조건을 빼면
  질문 한 번에 드러난다. 실제 제품은 위치를 스스로 찾아야 하고, 검출기가
  놓친 병변은 서술어 단계에 도착조차 못 한다.

무엇을 재는가
  같은 표본에서 두 경로를 나란히 돌린다.

    ① 정답 박스 → 서술어 → 판단      위치를 알려줬을 때 (지금까지 쓰던 값)
    ② 검출 박스 → 서술어 → 판단      스스로 찾았을 때  (진짜 시스템 성능)

  ①-② 의 차이가 검출 오류가 최종 판단을 깎은 몫이다. 두 경로가 같은 영상 ·
  같은 병변 · 같은 서술어 모델을 쓰므로 차이의 원인이 검출 하나로 좁혀진다.

  단계별 생존율도 같이 낸다. 100개 병변이 각 단계에서 몇 개 남는지 —
  어디서 새는지가 다음에 무엇을 고칠지를 정한다.

검출기를 다시 돌리지 않는다
  이미 저장된 검출 JSON(eval_mammo_det.py --save-json)을 읽는다. 검출 추론은
  598장에 83분이고 이미 끝난 일이다. 같은 것을 두 번 돌리면 시간도 잃고
  두 결과가 미묘하게 달라져 비교가 흐려진다.

자르기
  서술어 모델은 우리가 자른 조각이 아니라 CBIS 가 준 ROI DICOM 으로 학습됐다.
  그래서 measure_crop.py 로 잰 규칙을 따른다. 규칙 파일이 없으면 여기서 멈춘다 —
  여백을 추측해서 넣으면 서술어 성능이 조용히 떨어지고, 그러면 '연결하니
  나빠졌다' 는 틀린 결론이 나온다. 성능이 내려간 게 아니라 다른 것을 넣은 것이다.

사용
  python3 measure_crop.py                        # 먼저 (CPU, 10분)
  python3 eval_end2end.py --dets ../../archive/outputs/tile_dets_last.json
  python3 eval_end2end.py --dets ... --topk 1 --save ../../docs/e2e.json
"""

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import numpy as np
    import pandas as pd
    import pydicom
    import torch
    import torch.nn.functional as F
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

# 서술어 쪽은 학습·평가와 같은 코드를 쓴다. 복사하면 한쪽만 고쳐졌을 때
# 조용히 어긋난다.
from eval_e2e import (build_model, find_rules, import_rules,   # noqa: E402
                      level_of, to_category, to_onehot, gt_onehot)
from eval_det import center_in, iou                            # noqa: E402
from mammo_data import MammoROIDataset, axis_slices, load_schema  # noqa: E402
# 조각 전처리는 서빙과 같은 구현을 쓴다. 아래 verify_preproc() 이 실제 ROI
# 파일로 이 함수를 검증한다 — 그 검증이 서빙 경로까지 덮는다는 뜻이다.
from mammo_io import crop_to_tensor                            # noqa: E402,F401
from make_tiles import mask_box, norm8, tissue_bbox, tissue_mask  # noqa: E402
from paths import RAW_CBIS, ROI_INDEX                          # noqa: E402
from train_mammo import SCHEMA, pool_feats                     # noqa: E402

# 검출 JSON 의 이름 ↔ 서술어 모델의 kind
KIND_OF = {"mass": "mass", "calcification": "calc"}
BIOPSY_CUT = 4          # 4·5 = 조직검사, 1·2·3 = 추적. eval_e2e 와 같은 기준


# ─────────────────────── 자르기 규칙 ───────────────────────
def load_rule(path, override):
    if override is not None:
        print(f"  자르기  명령줄 지정 여백 {override:.0f}px")
        return dict(mode="fixed", margin_px=float(override), centered=True,
                    source="명령줄")
    p = Path(path)
    if not p.is_file():
        sys.exit(
            f"자르기 규칙이 없다: {p}\n"
            "  python3 measure_crop.py 를 먼저 돌려라 (CPU, 10분).\n"
            "  여백을 추측하면 서술어에 다른 것을 넣게 되고, 그러면 성능이\n"
            "  아니라 전처리 불일치를 재게 된다. --margin 으로 강제할 수는 있다.")
    r = json.loads(p.read_text())
    r["source"] = str(p)
    tot = r.get("pixel_total", 1) or 1
    print(f"  자르기  {r['mode']}  여백 {r.get('margin_px', 0):.0f}px  "
          f"배율 {r.get('ratio', 1):.2f}x   n={r.get('n')}")
    # 판단은 정규화 후 일치도로 한다. 원시 16비트 동일성은 CBIS 가 조각마다
    # 밝기 척도를 따로 잡아 성립하지 않으며, 서술어 모델은 그 값을 보지 않는다.
    if "norm_ok" in r:
        ok = r["norm_ok"]
        print(f"          정규화 후 일치 {ok}/{tot} ({100*ok/tot:.0f}%) · "
              f"99퍼 차이 중앙 {r.get('norm_p99_median', 0):.4f} · "
              f"정합 {r.get('match_median', 0):.3f}")
        if ok < 0.9 * tot:
            print("          ! 정규화 후에도 조각과 다르다. 이대로 재면 서술어가")
            print("            학습 때와 다른 입력을 받는다. 원인을 먼저 찾아라.")
    else:
        print("          ! 옛 규칙 파일이다 (정규화 후 일치도 없음). "
              "measure_crop.py 를 다시 돌려라.")
    return r


def expand(box, rule, kind, shape):
    """검출/정답 박스를 CBIS ROI 조각과 같은 크기로 넓힌다. 영상 밖은 자른다."""
    x0, y0, x1, y1 = [float(v) for v in box]
    per = (rule.get("per_kind") or {}).get(kind) or {}
    if rule["mode"] == "fixed":
        m = float(per.get("margin_px", rule.get("margin_px", 0.0)))
        x0, y0, x1, y1 = x0 - m, y0 - m, x1 + m, y1 + m
    else:
        k = float(per.get("ratio", rule.get("ratio", 1.0)))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w, h = (x1 - x0) * k / 2, (y1 - y0) * k / 2
        x0, y0, x1, y1 = cx - w, cy - h, cx + w, cy + h
    H, W = shape[:2]
    x0, y0 = max(0, int(round(x0))), max(0, int(round(y0)))
    x1, y1 = min(W, int(round(x1))), min(H, int(round(y1)))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return x0, y0, x1, y1


def verify_preproc(kind, cfg, n=3):
    """
    같은 ROI 파일을 데이터셋과 우리 함수에 각각 넣어 뺀다. 최대 차이 0 이어야 한다.

    0 이 아니면 서술어 모델은 학습 때와 다른 입력을 받는 것이고, 그 상태로 나온
    수치는 시스템 성능이 아니라 전처리 오류다. 몇 시간 뒤에 알아차리는 것보다
    지금 3초 쓰는 게 낫다.
    """
    csv = ROI_INDEX / f"roi_index_{kind}_test.csv"
    if not csv.is_file():
        print(f"    ! {kind} 인덱스가 없어 전처리 검증을 건너뛴다")
        return
    ds = MammoROIDataset(csv, SCHEMA, kind, size=cfg["size"], augment=False,
                         pad_square=cfg["pad"], clip_pct=cfg["clip"])
    worst, got = 0.0, 0
    for i in range(len(ds)):
        if got >= n:
            break
        row = ds.df.iloc[i]
        a = ds._read_roi(row["roi_file"])
        if a is None:
            continue
        ref = ((ds._resize(torch.from_numpy(a)[None, None])[0].repeat(3, 1, 1))
               - 0.5) / 0.5
        raw = pydicom.dcmread(str(row["roi_file"])).pixel_array
        mine = crop_to_tensor(raw, cfg["size"], cfg["pad"], cfg["clip"])
        worst = max(worst, float((ref - mine).abs().max()))
        got += 1
    print(f"    {kind:5s} 전처리 재현 {got}건 · 최대 차이 {worst:.2e}"
          + ("   ✓" if worst < 1e-5 else "   ✗ 학습과 다른 입력이다"))
    if worst >= 1e-5:
        sys.exit("전처리가 학습과 다르다. 이대로 재면 시스템 성능이 아니다.")


# ─────────────────────── 정답 ───────────────────────
def load_lesions(split):
    """
    영상별 병변 목록. eval_mammo_det.load_gt 와 달리 등급·병리까지 들고 온다 —
    최종 판단을 채점하려면 병변 하나하나의 정답 등급이 필요하다.
    """
    out = defaultdict(list)
    for kind in ("mass", "calc"):
        csv = ROI_INDEX / f"roi_index_{kind}_{split}.csv"
        if not csv.is_file():
            print(f"  ! 인덱스 없음: {csv}")
            continue
        for r in pd.read_csv(csv).to_dict("records"):
            mp = str(r.get("mask_file") or "").strip()
            if not mp or not Path(mp).is_file():
                continue
            uid = str(r.get("image_path", "")).strip().split("/")[-2]
            d = RAW_CBIS / uid
            fs = sorted(d.glob("*.dcm")) if d.is_dir() else []
            if not fs:
                continue
            out[uid].append(dict(kind=kind, mask=mp, dcm=fs[0], row=r))
    return out


# ─────────────────────── 서술어 실행 ───────────────────────
@torch.no_grad()
def describe(models, kind, crops, device, batch):
    """조각 여러 장을 서술어 모델에 넣어 확률을 받는다."""
    ext, head, cfg = models[kind]
    out = []
    for i in range(0, len(crops), batch):
        x = torch.stack(crops[i:i + batch]).to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logit = head(pool_feats(ext(x), cfg["pool"], cfg["levels"],
                                    cfg["grid"]))
        out.append(torch.sigmoid(logit.float()).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, len(cfg["cols"])))


def decide(R, kind, prob, cols, slices, thr, always):
    """확률 → 축별 서술어 → 규칙표 → 등급. 판정 불가면 None."""
    return to_category(R, level_of(R, kind, to_onehot(prob, cols, slices,
                                                      thr, always)))


# ─────────────────────── 채점 ───────────────────────
def rate(x, d):
    return 100.0 * x / d if d else float("nan")


def chain_table(rows, label):
    """
    병변 100개가 각 단계에서 몇 개 남는지. 어디서 새는지가 다음 할 일을 정한다.
    """
    n = len(rows)
    if not n:
        print(f"\n  ── {label} ── 병변이 없다")
        return None
    det = [r for r in rows if r["hit"]]
    desc = [r for r in det if r["pred"] is not None]
    need = [r for r in rows if r["gt_cat"] is not None and r["gt_cat"] >= BIOPSY_CUT]
    caught = [r for r in need if r["hit"] and r["pred"] is not None
              and r["pred"] >= BIOPSY_CUT]
    print(f"\n  ── {label} ──")
    print(f"    {'단계':28s}{'남은 병변':>10s}{'전체 대비':>10s}")
    print("    " + "-" * 48)
    print(f"    {'정답 병변':28s}{n:>10d}{100.0:>9.1f}%")
    print(f"    {'검출기가 찾음':28s}{len(det):>10d}{rate(len(det), n):>9.1f}%")
    print(f"    {'서술어가 판정 가능':28s}{len(desc):>10d}{rate(len(desc), n):>9.1f}%")
    print(f"\n    조직검사 대상 병변 {len(need)}건 중 끝까지 도달 {len(caught)}건"
          f"   = {rate(len(caught), len(need)):.1f}%")
    print("    (찾고 · 판정하고 · 조직검사라고 말한 것까지 전부 맞아야 한다)")

    # 손실을 두 단계로 정확히 나눈다.
    #
    # 전체 검출률로 곱해서 나누면 근사가 된다 — '조직검사 대상 병변의 검출률이
    # 전체와 같다' 고 가정하게 되기 때문이다. 그 가정이 틀리면 잔차가 검출
    # 탓인지 서술어 탓인지 구분이 안 된다. 실제로 topk 를 바꿨더니 잔차가
    # 0.6%p 와 3.6%p 사이에서 흔들렸다.
    #
    # 조직검사 대상 병변에 한정해 재면 아래 항등식이 성립한다. 가정이 없다.
    #     끝단 민감도 = 찾은 비율 × 찾은 것 중 옳게 판단한 비율
    nd = [r for r in need if r["hit"]]
    nd_ok = [r for r in nd if r["pred"] is not None and r["pred"] >= BIOPSY_CUT]
    r_find = rate(len(nd), len(need))
    r_call = rate(len(nd_ok), len(nd))
    print(f"\n    ── 손실을 나누면 ──")
    print(f"    조직검사 대상 중 검출됨        {len(nd):4d}/{len(need):<4d}"
          f" = {r_find:5.1f}%   ← 검출기 몫")
    print(f"    그중 조직검사라고 말함         {len(nd_ok):4d}/{len(nd):<4d}"
          f" = {r_call:5.1f}%   ← 서술어 몫")
    print(f"    곱하면 {r_find:.1f}% × {r_call:.1f}% = "
          f"{r_find*r_call/100:.1f}%  (위의 끝단 민감도와 같다)")
    return dict(n=n, detected=len(det), described=len(desc),
                need_biopsy=len(need), need_found=len(nd), caught=len(caught),
                find_rate=r_find, call_rate=r_call,
                e2e_sens=rate(len(caught), len(need)))


def paired(rows_o, rows_d):
    """
    같은 병변에서 정답 박스 경로와 검출 박스 경로를 짝지어 비교한다.
    검출이 성공한 병변만 본다 — 실패한 것은 위에서 이미 세었고, 여기서 다시
    세면 같은 손실을 두 번 벌점으로 매기게 된다.
    """
    key = lambda r: (r["uid"], r["li"])                          # noqa: E731
    O = {key(r): r for r in rows_o}
    both = [(O[key(r)], r) for r in rows_d if r["hit"] and key(r) in O
            and O[key(r)]["pred"] is not None and r["pred"] is not None]
    if not both:
        return None
    same = sum(1 for o, d in both if o["pred"] == d["pred"])
    obio = sum(1 for o, d in both if o["pred"] >= BIOPSY_CUT)
    dbio = sum(1 for o, d in both if d["pred"] >= BIOPSY_CUT)
    flip_dn = sum(1 for o, d in both
                  if o["pred"] >= BIOPSY_CUT and d["pred"] < BIOPSY_CUT)
    flip_up = sum(1 for o, d in both
                  if o["pred"] < BIOPSY_CUT and d["pred"] >= BIOPSY_CUT)
    print(f"\n  ── 같은 병변에서 두 박스를 짝지어 비교  (n={len(both)}) ──")
    print(f"    등급이 같음                  {same:5d}   {rate(same, len(both)):5.1f}%")
    print(f"    조직검사 판단  정답박스 {obio}건 · 검출박스 {dbio}건")
    print(f"    조직검사 → 추적 으로 뒤집힘  {flip_dn:5d}   ★ 이것이 연결의 대가다")
    print(f"    추적 → 조직검사 로 뒤집힘    {flip_up:5d}")
    print("    검출에 성공한 병변만 센다. 못 찾은 병변은 위 표에서 이미 빠졌다.")
    return dict(n=len(both), agree=rate(same, len(both)),
                flip_down=flip_dn, flip_up=flip_up)


def fp_burden(fps, n_scan):
    """
    오탐이 조직검사로 넘어가는 양. 임상에서 이게 곧 불필요한 검사다.

    분모는 정답이 있는 영상이 아니라 '훑은 영상 전부' 다. 검출기는 병변이
    없는 영상에도 박스를 내놓으므로, 정답이 있는 영상만 세면 오탐이 낮게
    나온다. 1차 실행에서 598장 중 271장만 세어 그렇게 틀렸다.
    """
    dup = [f for f in fps if f.get("dup")]
    ok = [f for f in fps if f["pred"] is not None]
    bio = [f for f in ok if f["pred"] >= BIOPSY_CUT]
    print(f"\n  ── 오탐이 만드는 부담  (훑은 영상 {n_scan}장) ──")
    print(f"    정답과 안 겹친 검출        {len(fps):6d}   "
          f"영상당 {len(fps)/max(n_scan,1):.2f}개")
    print(f"      그중 같은 병변 중복 검출 {len(dup):6d}   "
          "(이미 다른 검출이 맞힌 병변을 또 맞힌 것)")
    print(f"    그중 서술어 판정이 나온 것 {len(ok):6d}")
    print(f"    그중 '조직검사' 로 간 것   {len(bio):6d}   "
          f"영상당 {len(bio)/max(n_scan,1):.2f}개")
    print("    규칙표가 오탐을 걸러주면 이 수가 위보다 작다. 그게 서술어 단계의")
    print("    부수적 효과이고, 검출기만으로는 얻을 수 없다.")
    print("    ※ 이 값은 --topk 설정에 달려 있다. 점수와 무관하게 상위 몇 개를")
    print("      넘길지 내가 정하기 때문이다. 발표에 쓸 오탐률은 --topk 0 과")
    print("      --score 를 FROC 곡선의 특정 지점으로 맞춰 다시 재야 한다.")
    return dict(fp=len(fps), fp_dup=len(dup), fp_scored=len(ok),
                fp_biopsy=len(bio), n_scan=n_scan,
                fp_biopsy_per_image=len(bio) / max(n_scan, 1))


# ─────────────────────── 본체 ───────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dets", required=True, help="eval_mammo_det.py 가 저장한 검출 JSON")
    ap.add_argument("--calc", default="../ckpt/mammo_calc_trunk_last_grid4_pad0_clip999_lora.pt")
    ap.add_argument("--mass", default="../ckpt/mammo_mass_trunk_last_grid4_pad0_clip999_lora.pt")
    ap.add_argument("--rule", default="crop_rule.json")
    ap.add_argument("--margin", type=float, default=None,
                    help="규칙 파일 대신 고정 여백(px)을 강제한다")
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--split", default="test")
    ap.add_argument("--topk", type=int, default=2,
                    help="영상·종류당 점수 상위 몇 개를 서술어에 넘길지")
    ap.add_argument("--score", type=float, default=0.0, help="최소 검출 점수")
    ap.add_argument("--match", default="center", choices=["center", "iou"])
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--thr", type=float, default=0.5, help="희소 축 채택 확률")
    ap.add_argument("--always", default="shape,margin,calctype,calcdist")
    ap.add_argument("--clip", type=float, default=99.9, help="조직 영역 찾기용")
    ap.add_argument("--pad", type=int, default=32, help="조직 영역 여백")
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--only", default="", choices=["", "calc", "mass"],
                    help="한 종류만 돌린다. 서술어 백본을 하나만 올리므로 "
                         "GPU 여유가 적을 때 쓴다")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="5장만")
    ap.add_argument("--save", default="")
    a = ap.parse_args()

    a.dets = str(Path(a.dets).expanduser().resolve())
    if a.save:
        a.save = str(Path(a.save).expanduser().resolve())

    print("=" * 74)
    print("끝에서 끝까지 — 사진 → 검출 → 서술어 → 등급 → 조직검사")
    print("=" * 74)
    rule = load_rule(a.rule, a.margin)
    print(f"  검출    {a.dets}")
    print(f"  넘김    영상·종류당 상위 {a.topk}개 · 최소 점수 {a.score}")
    print(f"  명중    {'중심 포함' if a.match == 'center' else f'IoU>{a.iou}'}")

    raw = json.loads(Path(a.dets).read_text())
    by_img = defaultdict(lambda: defaultdict(list))
    for name, lst in raw.items():
        kind = KIND_OF.get(name)
        if kind is None:
            continue
        for d in lst:
            if float(d["score"]) >= a.score:
                by_img[d["img"]][kind].append(
                    (list(map(float, d["box"])), float(d["score"])))

    lesions = load_lesions(a.split)
    # 정답이 있는 영상은 **전부** 채점한다. 검출이 0건이라고 빼면
    # "못 찾은 것" 이 분모에서 사라져 민감도가 부풀려진다.
    #
    # 임계값을 적용하기 전에는 이 문제가 안 보였다 — 모든 영상에 검출이
    # 하나씩은 있었기 때문이다. 445줄 주석의 오탐 과소평가와 같은 실수를
    # 반대 방향으로 한 것이다.
    #
    # 반복문은 이미 이 경우를 처리한다. by_img 가 defaultdict 라 없는
    # 영상은 빈 항목이 되고, has_det 이 False 여도 gts 가 있으면
    # 건너뛰지 않는다.
    uids = sorted(lesions)
    missing = sorted(u for u in lesions if u not in by_img)
    if a.check:
        uids = uids[:5]
    elif a.n:
        uids = uids[:a.n]
    print(f"  영상    검출 {len(by_img)}장 · 정답 {len(lesions)}장 · 채점 {len(uids)}장"
          + (f"  (검출 0건 {len(missing)}장 포함 — 전부 놓친 것으로 센다)"
             if missing else ""))
    if not uids:
        sys.exit("겹치는 영상이 없다 — split 이나 검출 JSON 을 확인해라")

    device = "cuda"
    R = import_rules(a.rules)
    schema = load_schema(SCHEMA)
    always = {s.strip() for s in a.always.split(",") if s.strip()}

    print("\n■ 서술어 모델")
    models, slices = {}, {}
    want = [(k, c) for k, c in (("calc", a.calc), ("mass", a.mass))
            if not a.only or k == a.only]
    if a.only:
        print(f"    {a.only} 만 올린다 (--only) — 백본 하나 분량의 메모리만 쓴다")
    for kind, ck in want:
        p = Path(ck).expanduser()
        if not p.is_file():
            print(f"    ! {kind} 체크포인트 없음: {p} — 이 종류는 건너뛴다")
            continue
        ext, head, cfg = build_model(str(p), device)
        models[kind] = (ext, head, cfg)
        slices[kind] = axis_slices(schema, kind)
    if not models:
        sys.exit("서술어 모델이 하나도 없다")

    print("\n■ 전처리 재현 확인")
    for kind, (_, _, cfg) in models.items():
        verify_preproc(kind, cfg)

    print("\n■ 추론")
    rows_o, rows_d, fps = [], [], []      # 정답박스 경로 · 검출박스 경로 · 오탐
    n_img, n_scan, t0 = 0, 0, time.time()

    for i, uid in enumerate(uids, 1):
        ent = lesions[uid]
        try:
            arr = pydicom.dcmread(str(ent[0]["dcm"])).pixel_array
        except Exception as e:
            print(f"\n  ! {uid}: {e}")
            continue
        if arr.ndim != 2:
            continue

        # 검출 좌표는 '유방 영역을 잘라낸' 기준이다. 원본 좌표로 되돌린다 —
        # 정답 상자와 조각 잘라내기가 모두 원본 좌표계이기 때문이다.
        tb = tissue_bbox(tissue_mask(norm8(arr, a.clip)), a.pad)
        if tb is None:
            continue
        cx0, cy0 = tb[0], tb[1]

        gts = []
        for li, L in enumerate(ent):
            if L["kind"] not in models:
                continue
            b, shp = mask_box(L["mask"])
            if b is None or shp != arr.shape[:2]:
                continue
            g = L["row"].get("assessment")
            gts.append(dict(li=li, kind=L["kind"], box=b,
                            gt=float(g) if g == g else float("nan")))
        # 정답이 없는 영상도 건너뛰지 않는다. 검출기는 모든 영상에 박스를
        # 내놓으므로, 정답이 있는 영상만 보면 오탐이 과소평가된다.
        # (1차 실행에서 598장 중 271장만 세어 오탐이 낮게 나왔다.)
        has_det = any(by_img[uid].get(k) for k in models)
        if not gts and not has_det:
            continue
        n_scan += 1
        if gts:
            n_img += 1

        hit_fn = (lambda p, q: center_in(p, q)) if a.match == "center" \
            else (lambda p, q: iou(p, q) >= a.iou)

        # ── 두 경로의 조각을 모두 모아 종류별로 한 번에 넣는다 ──
        jobs = defaultdict(list)          # kind -> [(tag, meta, tensor)]
        for g in gts:                     # ① 정답 박스
            e = expand(g["box"], rule, g["kind"], arr.shape)
            if e is None:
                continue
            cfg = models[g["kind"]][2]
            jobs[g["kind"]].append(
                ("oracle", g, crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                             cfg["size"], cfg["pad"], cfg["clip"])))

        for kind in models:               # ② 검출 박스
            # 점수 내림차순으로 본다. 한 병변은 가장 높은 점수의 검출 하나만
            # 정탐으로 세고, 같은 병변을 또 맞힌 검출은 중복으로 센다.
            #
            # 1차 실행에서 이걸 안 해서 topk=2 의 두 검출이 같은 병변을 맞히면
            # 그 병변이 두 줄로 들어갔다 (정답 병변이 ①311 대 ②337 로 어긋난
            # 이유다). 검출에 성공한 병변만 중복되므로 ② 가 실제보다 좋아진다.
            # FROC 도 COCO 도 이렇게 센다 — 중복 검출은 오탐이다.
            claimed = set()
            cand = sorted(by_img[uid].get(kind, []), key=lambda t: -t[1])
            for box, sc in (cand[:a.topk] if a.topk else cand):
                full = (box[0] + cx0, box[1] + cy0, box[2] + cx0, box[3] + cy0)
                m, dup = None, False
                for g in gts:
                    if g["kind"] != kind or not hit_fn(full, g["box"]):
                        continue
                    if g["li"] in claimed:
                        dup = True          # 이미 다른 검출이 차지한 병변
                        continue
                    m = g
                    claimed.add(g["li"])
                    break
                e = expand(full, rule, kind, arr.shape)
                if e is None:
                    continue
                cfg = models[kind][2]
                jobs[kind].append(
                    ("det", dict(g=m, score=sc, dup=dup),
                     crop_to_tensor(arr[e[1]:e[3], e[0]:e[2]],
                                    cfg["size"], cfg["pad"], cfg["clip"])))

        for kind, items in jobs.items():
            if not items:
                continue
            cfg = models[kind][2]
            P = describe(models, kind, [t for _, _, t in items], device, a.batch)
            cols = cfg["cols"]
            for (tag, meta, _), prob in zip(items, P):
                pred = decide(R, kind, prob, cols, slices[kind], a.thr, always)
                if tag == "oracle":
                    rows_o.append(dict(uid=uid, li=meta["li"], kind=kind,
                                       hit=True, pred=pred, gt=meta["gt"],
                                       gt_cat=meta["gt"]))
                elif meta["g"] is not None:
                    rows_d.append(dict(uid=uid, li=meta["g"]["li"], kind=kind,
                                       hit=True, pred=pred, gt=meta["g"]["gt"],
                                       gt_cat=meta["g"]["gt"],
                                       score=meta["score"]))
                else:
                    fps.append(dict(uid=uid, kind=kind, pred=pred,
                                    score=meta["score"], dup=meta.get("dup", False)))

        # 검출이 아예 못 찾은 병변을 검출 경로에 '실패' 로 남긴다.
        # 빼버리면 찾은 것만 채점하게 되고 그건 시스템 성능이 아니다.
        found = {(r["uid"], r["li"]) for r in rows_d}
        for g in gts:
            if (uid, g["li"]) not in found:
                rows_d.append(dict(uid=uid, li=g["li"], kind=g["kind"],
                                   hit=False, pred=None, gt=g["gt"],
                                   gt_cat=g["gt"], score=0.0))

        if i % 5 == 0 or i == len(uids):
            el = time.time() - t0
            print(f"\r  {i}/{len(uids)}  병변 {len(rows_o)}  검출조각 "
                  f"{len(rows_d)+len(fps)}  {el/60:.1f}분 · 남은 "
                  f"{el/i*(len(uids)-i)/60:.0f}분   ", end="", flush=True)
    print()

    if not rows_o:
        sys.exit("채점할 병변이 없다")

    # 두 경로는 같은 병변을 봐야 한다. 개수가 다르면 한쪽이 중복이거나
    # 빠진 것이고, 그 상태의 비교는 무의미하다. 1차 실행에서 ①311 대 ②337
    # 이었고 원인이 중복 검출이었다. 여기서 다시 확인한다.
    uniq_d = {(r["uid"], r["li"]) for r in rows_d}
    uniq_o = {(r["uid"], r["li"]) for r in rows_o}
    if len(rows_d) != len(uniq_d) or uniq_o != uniq_d:
        print(f"\n  ! 두 경로의 병변 집합이 다르다 — ①{len(rows_o)}건 "
              f"(고유 {len(uniq_o)}) · ②{len(rows_d)}건 (고유 {len(uniq_d)})")
        print(f"    ① 에만 {len(uniq_o - uniq_d)}건 · ② 에만 "
              f"{len(uniq_d - uniq_o)}건 · ② 중복 {len(rows_d)-len(uniq_d)}건")
        print("    아래 표의 ①② 직접 비교는 근사다.")

    out = {}
    print("\n" + "=" * 74)
    print(f"단계별 생존   정답 있는 영상 {n_img}장 (훑은 영상 {n_scan}장) · "
          f"병변 {len(rows_o)}건")
    print("=" * 74)
    out["oracle"] = chain_table(rows_o, "① 정답 박스 → 서술어  (위치를 알려줬을 때)")
    out["detected"] = chain_table(rows_d, "② 검출 박스 → 서술어  (스스로 찾았을 때)")
    if out["oracle"] and out["detected"]:
        d = out["detected"]["e2e_sens"] - out["oracle"]["e2e_sens"]
        print(f"\n  ── 차이 ──")
        print(f"    조직검사 민감도 {out['oracle']['e2e_sens']:.1f}% → "
              f"{out['detected']['e2e_sens']:.1f}%   ({d:+.1f}%p)")
        print("    이 낙폭이 '위치를 알려줬을 때' 와 '스스로 찾을 때' 의 거리다.")
        print("    발표에서 85.3% 를 말할 때 반드시 같이 말해야 하는 수치다.")

    print("\n" + "=" * 74)
    print("종류별")
    print("=" * 74)
    for kind in models:
        ro = [r for r in rows_o if r["kind"] == kind]
        rd = [r for r in rows_d if r["kind"] == kind]
        if not ro:
            continue
        print(f"\n▪ {kind}")
        o = chain_table(ro, "  정답 박스")
        d = chain_table(rd, "  검출 박스")
        out.setdefault("per_kind", {})[kind] = dict(oracle=o, detected=d)

    print("\n" + "=" * 74)
    print("연결의 대가 — 무엇이 달라졌나")
    print("=" * 74)
    out["paired"] = paired(rows_o, rows_d)
    out["fp"] = fp_burden(fps, n_scan)

    print("\n" + "=" * 74)
    print("읽는 법")
    print("=" * 74)
    print("  ① 은 지금까지 발표 자료에 쓰던 조건이다. 사람이 병변 위치를 찍어준다.")
    print("  ② 가 시스템이 혼자 했을 때다. 두 수치를 나란히 놓는 것이 정직하다.")
    print("  둘의 차이는 서술어가 나빠져서가 아니라 검출기가 못 찾아서 생긴다 —")
    print("  '짝지어 비교' 표가 그것을 분리해서 보여준다. 거기서 등급이 크게")
    print("  안 흔들리면 다음에 고칠 곳은 서술어가 아니라 검출기다.")
    print("\n  CBIS 는 조직검사 확정 사례만 모은 집합이다. 이 수치는 '검진 성능'")
    print("  이 아니라 '조직검사 대상 병변에 대한 판단' 이다.")

    if a.save:
        p = Path(a.save)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(
            config=dict(dets=a.dets, topk=a.topk, match=a.match, thr=a.thr,
                        rule=rule, n_images=n_img, n_lesions=len(rows_o)),
            result=out), indent=2, ensure_ascii=False, default=float))
        print(f"\n  -> {p}")


if __name__ == "__main__":
    main()
