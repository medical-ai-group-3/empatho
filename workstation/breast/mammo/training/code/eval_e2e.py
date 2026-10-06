#!/usr/bin/env python
"""
종단 평가 — 사진에서 BI-RADS 등급까지 전체 사슬을 한 번에 돌린다.

  ROI 사진 → 학습된 모델 → 축별 서술어 → 규칙표 → 등급  ↔  CBIS 정답 등급

왜 필요한가
  val2.txt 의 60.5% 는 '정답 서술어를 넣었을 때' 규칙표의 성능이다.
  사람이 완벽하게 서술어를 달아줬다고 가정한 값이라 시스템 성능이 아니다.
  실제 시스템은 모델이 예측한 서술어를 넣으므로 그 오류가 등급으로 전파된다.
  이 스크립트가 재는 것이 발표에서 '우리 시스템 성능'이라 부를 수 있는 수치다.

같은 부분집합에서 두 가지를 다 돌려 나란히 놓는다.
  ① 정답 서술어 → 규칙표   (규칙표만의 성능)
  ② 예측 서술어 → 규칙표   (시스템 성능)
  ①-② 의 차이가 곧 서술어 예측 오류가 등급 정확도를 깎은 몫이다.

규칙표는 복사하지 않고 validate_rules.py 에서 함수를 그대로 불러온다.
모듈 수준 argparse 만 잠시 우회한다. 규칙을 고치면 이 평가도 따라간다.
"""

import argparse, sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from train_mammo import (FeatExtractor, pool_feats, make_head, inject_lora,
                         load_merged_model, CFG, CKPT, INDEX_DIR, SCHEMA)
from paths import medsam3_cwd
from mammo_data import MammoROIDataset, load_schema, label_columns, axis_slices

def find_rules():
    """
    규칙표 위치를 찾는다. 스크립트와 같은 폴더를 가장 먼저 본다 — 파일을 옮겨도
    따라오게 하려는 것이다. 없으면 알려진 옛 경로를 차례로 확인한다.
    경로를 코드에 박아두면 폴더를 정리할 때마다 스크립트가 깨진다.
    """
    for c in (HERE / "validate_rules.py",
              Path.home() / "workspace/breast/mammo/validate_rules.py",
              Path.home() / "workspace/breast/code/validate_rules.py"):
        if c.exists():
            return c
    return HERE / "validate_rules.py"      # 없으면 여기서 찾다 에러를 낸다


def import_rules(path):
    """validate_rules.py 를 불러온다. 모듈 수준 argparse 가 sys.argv 를 읽으므로 잠시 비운다."""
    sys.path.insert(0, str(Path(path).parent))
    saved = sys.argv
    sys.argv = [str(path)]
    try:
        import validate_rules as R
    finally:
        sys.argv = saved
    need = ["level_mass", "level_calc", "LEVEL_TO_CAT", "FOLD"]
    missing = [n for n in need if not hasattr(R, n)]
    if missing:
        sys.exit(f"{path} 에 없는 이름: {missing}")
    return R


def level_of(R, kind, row):
    fn = R.level_mass if kind == "mass" else R.level_calc
    out = fn(row)
    return out[0] if isinstance(out, tuple) else out


def to_category(R, lv):
    """FOLD 까지 간 정수. **채점이 쓰는 것은 이쪽이다.**

    정답 라벨도 FOLD 된 값이라 여기를 세분류로 바꾸면 지표가 통째로
    흔들린다. 세분류가 필요하면 to_category_fine 을 쓸 것.
    """
    if lv is None:
        return None
    cat = R.LEVEL_TO_CAT.get(lv)
    return R.FOLD.get(cat) if cat is not None else None


# BI-RADS 등급의 순서. 문자열 대소 비교는 이 집합에서 우연히 맞을 뿐이고
# "0" · "1" · "6" 이 섞이면 깨진다. 비교는 반드시 이 색인으로 한다.
CAT_ORDER = ("0", "1", "2", "3", "4a", "4b", "4c", "5", "6")


def to_category_fine(R, lv):
    """세분류를 살린 등급 문자열 ("4a" · "4b" · "4c").

    규칙표가 L2->4a · L3->4b · L4->4c 로 나누는데 FOLD 가 전부 4 로 합친다.
    "왜 그 등급인가" 를 설명하려면 합치기 전 값이 있어야 한다.
    """
    if lv is None:
        return None
    return R.LEVEL_TO_CAT.get(lv)


def cat_rank(cat):
    """등급 비교용 순서. 모르는 값은 -1 이라 최대값 후보에서 빠진다."""
    try:
        return CAT_ORDER.index(cat)
    except (ValueError, TypeError):
        return -1


def max_category(cats):
    """가장 높은 등급 하나. 비교는 CAT_ORDER 색인으로 한다."""
    ok = [c for c in cats if cat_rank(c) >= 0]
    return max(ok, key=cat_rank) if ok else None


# ─────────────────────────── 모델 복원 ───────────────────────────
def build_model(ckpt_path, device):
    d = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    a = d.get("args", {}) or {}
    kind = d["kind"]
    src = a.get("src", "trunk")
    levels = a.get("levels", "last")
    pool = a.get("pool", "grid")
    grid = int(a.get("grid", 4))
    size = int(a.get("size", 1008))
    pad = not a.get("no_pad", False)
    clip = a.get("clip", 99.9)
    feat_dim = int(d["feat_dim"])
    backbone = a.get("ckpt", CKPT)

    print(f"■ 모델 복원  {ckpt_path}")
    print(f"    kind={kind}  src={src} levels={levels} pool={pool}{grid}")
    print(f"    전처리  패딩={'켬' if pad else '끔'}  절단={clip}")
    print(f"    백본    {backbone}")
    print(f"    저장 시점  ep {d.get('epoch')}  검증 {d.get('val_score')}  "
          f"테스트F1 {d.get('test_f1')}")

    # SAM 3 의 토크나이저가 자산을 상대경로로 찾는다. 모델을 세우는 동안만
    # MedSAM3 저장소를 cwd 로 둔다. 블록을 나오면 원위치한다.
    with medsam3_cwd():
        full = load_merged_model(backbone, CFG, device=device)
    vb = full.backbone.vision_backbone
    del full
    for p in vb.parameters():
        p.requires_grad = False
    ext = FeatExtractor(vb, src)

    lora_sd = d.get("lora")
    if lora_sd:
        n = inject_lora(ext.net, int(a.get("rank", 16)), int(a.get("alpha", 32)),
                        {"qkv", "proj", "fc1", "fc2"})
        ext = ext.to(device)
        missing, unexpected = ext.load_state_dict(lora_sd, strict=False)
        loaded = len([k for k in lora_sd if "lora_" in k])
        print(f"    LoRA  {n}개 층 주입 · 텐서 {loaded}개 로드")
        if unexpected:
            sys.exit(f"체크포인트에 모델이 모르는 키가 있다: {unexpected[:5]}")
    else:
        ext = ext.to(device)
        print("    LoRA 없음 — 동결 헤드 체크포인트다")

    head = make_head(len(d["cols"]), feat_dim).to(device)
    head.load_state_dict(d["head"])
    ext.eval(); head.eval()
    return ext, head, dict(kind=kind, cols=d["cols"], pool=pool, levels=levels,
                           grid=grid, size=size, pad=pad, clip=clip)


# ─────────────────────────── 예측 ───────────────────────────
@torch.no_grad()
def predict(ext, head, cfg, device, batch=4):
    """
    테스트셋을 돌며 (확률, 정답라벨, 정답등급) 을 모은다.

    데이터셋의 __getitem__ 은 이진 마스크를 만나면 다음 행으로 대체하는데,
    평가에서는 그 대체가 행 정렬을 깨뜨린다. 그래서 내부 메서드를 직접 불러
    행을 명시적으로 붙들고, 이진이면 대체 대신 건너뛴다.
    """
    ds = MammoROIDataset(Path(INDEX_DIR) / f"roi_index_{cfg['kind']}_test.csv",
                         SCHEMA, cfg["kind"], size=cfg["size"], augment=False,
                         pad_square=cfg["pad"], clip_pct=cfg["clip"])
    if "assessment" not in ds.df.columns:
        sys.exit("인덱스에 assessment 컬럼이 없다")

    probs, ys, gts, skipped = [], [], [], 0
    buf_img, buf_row = [], []

    def flush():
        if not buf_img:
            return
        x = torch.stack(buf_img).to(device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            fs = ext(x)
            logit = head(pool_feats(fs, cfg["pool"], cfg["levels"], cfg["grid"]))
        p = torch.sigmoid(logit.float()).cpu().numpy()
        for k, r in enumerate(buf_row):
            probs.append(p[k])
            ys.append(np.array([float(r[c]) for c in cfg["cols"]], dtype=np.float32))
            gts.append(r["assessment"])
        buf_img.clear(); buf_row.clear()

    import time
    t0 = time.time()
    for i in range(len(ds)):
        row = ds.df.iloc[i]
        arr = ds._read_roi(row["roi_file"])
        if arr is None:                       # 이진 = 마스크 오인. 대체하지 않고 제외
            skipped += 1
            continue
        img = ds._resize(torch.from_numpy(arr)[None, None])[0].repeat(3, 1, 1)
        buf_img.append((img - 0.5) / 0.5)
        buf_row.append(row)
        if len(buf_img) == batch:
            flush()
        if (i + 1) % 50 == 0:
            print(f"\r    {i+1}/{len(ds)}  ({time.time()-t0:.0f}s)", end="", flush=True)
    flush()
    print(f"\r    {len(ds)}/{len(ds)}  ({time.time()-t0:.0f}s)  제외 {skipped}건"
          f" (이진 영상)      ")
    return np.array(probs), np.array(ys), np.array(gts, dtype=float)


# ─────────────────── 확률 → 서술어 원핫 ───────────────────
def to_onehot(vec, cols, slices, thr, always):
    """
    축마다 확률 최고 클래스를 고른다. 규칙표가 축별 서술어 하나를 받기 때문이다.
    다만 finding 처럼 대부분의 사진에 아예 없는 축이 있다 — 그런 축까지 무조건
    하나를 붙이면 없는 소견을 만들어내게 된다. 그래서 최고 확률이 thr 미만이면
    그 축은 비운다. always 에 든 축은 항상 하나를 고른다.
    """
    d = {}
    for ax, (s, e) in slices.items():
        sub = vec[s:e]
        j = int(np.argmax(sub))
        if ax in always or float(sub[j]) >= thr:
            d[cols[s + j]] = 1
    return d


def gt_onehot(y, cols):
    return {c: 1 for c, v in zip(cols, y) if v == 1}


# ─────────────────────────── 채점 ───────────────────────────
def score(pred, gt):
    pred, gt = np.asarray(pred, float), np.asarray(gt, float)
    ok = ~np.isnan(pred)
    p, g = pred[ok], gt[ok]
    if len(p) == 0:
        return None
    diff = p - g
    return dict(n=len(p), exact=float((diff == 0).mean()) * 100,
                within1=float((np.abs(diff) <= 1).mean()) * 100,
                signed=float(diff.mean()), unevaluable=int((~ok).sum()))


def confusion(pred, gt, lo=1, hi=5):
    m = np.zeros((hi - lo + 1, hi - lo + 1), dtype=int)
    for p, g in zip(pred, gt):
        if p != p or g != g:
            continue
        gi, pi = int(g) - lo, int(p) - lo
        if 0 <= gi < m.shape[0] and 0 <= pi < m.shape[1]:
            m[gi, pi] += 1
    return m


def show_confusion(m, lo=1):
    hdr = "".join(f"{lo+j:>7d}" for j in range(m.shape[1]))
    corner = "실제/예측"
    print(f"    {corner:<10s}{hdr}{'합':>8s}")
    for i in range(m.shape[0]):
        row = "".join(f"{v:>7d}" for v in m[i])
        print(f"    {lo+i:<10d}{row}{m[i].sum():>8d}")
    tot = "".join(f"{m[:, j].sum():>7d}" for j in range(m.shape[1]))
    print(f"    {'합':<10s}{tot}{m.sum():>8d}")
    # 3↔4 경계
    if m.shape[0] >= 5:
        cross = m[2, 3] + m[3, 2]     # 실제3→예측4, 실제4→예측3
        print(f"\n    3↔4 경계를 넘은 오류 {cross}건 "
              f"({100*cross/max(m.sum(),1):.1f}%) — 추적 대 조직검사가 갈리는 지점")


def per_class(pred, gt, lo=1, hi=5):
    """등급별 재현율과 예측 건수. '어떤 등급을 아예 못 내는지'가 여기서 드러난다."""
    pred, gt = np.asarray(pred, float), np.asarray(gt, float)
    out = {}
    for c in range(lo, hi + 1):
        is_c = gt == c
        n = int(is_c.sum())
        hit = int(((pred == c) & is_c).sum())
        out[c] = dict(n=n, recall=(100.0 * hit / n) if n else float("nan"),
                      predicted=int((pred == c).sum()))
    return out


def show_per_class(gt_stats, pr_stats, lo=1, hi=5):
    print(f"    {'등급':<6s}{'실제n':>7s}{'정답서술어':>12s}{'예측서술어':>12s}"
          f"{'예측된 건수':>13s}")
    print("    " + "-" * 50)
    for c in range(lo, hi + 1):
        g, p = gt_stats[c], pr_stats[c]
        if g["n"] == 0:
            continue
        mark = "  ★ 한 번도 못 냄" if p["recall"] == 0 else ""
        gr = f"{g['recall']:10.1f}%" if g["n"] else "         -"
        pr = f"{p['recall']:10.1f}%" if p["n"] else "         -"
        print(f"    {c:<6d}{g['n']:>7d}{gr}{pr}{p['predicted']:>13d}{mark}")


# ─────────────────── 조직검사 판단 (이진) ───────────────────
BIOPSY_CUT = 4      # 4 이상 = 조직검사, 3 이하 = 추적

def binary_decision(pred, gt, cut=BIOPSY_CUT):
    """
    6단계 등급 대신 임상에서 실제로 갈리는 결정 하나만 본다.

        1 · 2 · 3  ->  추적 관찰        4 · 5  ->  조직검사

    6단계 정확 일치는 4a 와 4b 를 헷갈린 것도 오답으로 센다. 그런데 둘은
    같은 처치로 이어진다. 임상 결정을 기준으로 재는 것이 과한 벌점을 걷어낸
    수치이자, 실제로 시스템이 하는 일에 더 가까운 질문이다.

    assessment 0 은 '추가 촬영 필요' 라 조직검사 여부를 물을 수 없다. 제외한다.
    """
    pred, gt = np.asarray(pred, float), np.asarray(gt, float)
    zeros = int((gt == 0).sum())
    ok = ~np.isnan(pred) & ~np.isnan(gt) & (gt >= 1)
    p, g = pred[ok] >= cut, gt[ok] >= cut
    n = len(p)
    if n == 0:
        return None
    tp = int((p & g).sum());  fn = int((~p & g).sum())
    fp = int((p & ~g).sum()); tn = int((~p & ~g).sum())

    def rate(x, d):
        return 100.0 * x / d if d else float("nan")

    return dict(n=n, tp=tp, tn=tn, fp=fp, fn=fn,
                acc=rate(tp + tn, n),
                sens=rate(tp, tp + fn),
                spec=rate(tn, tn + fp),
                ppv=rate(tp, tp + fp),
                npv=rate(tn, tn + fn),
                prev=rate(tp + fn, n),
                zeros=zeros,
                unevaluable=int((~ok).sum()) - zeros)


def show_binary(name, m):
    if m is None:
        print(f"\n  ── {name} ── 평가 가능한 행이 없다")
        return
    print(f"\n  ── {name} ──")
    print(f"    {'':14s}{'예측: 추적':>12s}{'예측: 조직검사':>16s}")
    print(f"    {'실제: 추적':<14s}{m['tn']:>12d}{m['fp']:>16d}")
    print(f"    {'실제: 조직검사':<14s}{m['fn']:>12d}{m['tp']:>16d}")
    print(f"\n    정확도   {m['acc']:5.1f}%   (n={m['n']})")
    print(f"    민감도   {m['sens']:5.1f}%   조직검사 대상을 놓치지 않은 비율 ★")
    print(f"    특이도   {m['spec']:5.1f}%   추적으로 충분한 것을 안 보낸 비율")
    print(f"    PPV      {m['ppv']:5.1f}%   조직검사라 했을 때 실제로 맞은 비율")
    print(f"    NPV      {m['npv']:5.1f}%   추적이라 했을 때 실제로 맞은 비율")


def show_binary_context(m):
    """
    이 수치를 혼자 두면 안 된다. CBIS 는 조직검사 확정 사례만 모은 데이터셋이라
    양성 비율이 높다. '전부 조직검사' 로 찍기만 해도 그만큼 나온다.
    """
    if m is None:
        return
    print("\n  ── 반드시 같이 볼 것 ──")
    print(f"    이 부분집합의 조직검사 실제 비율 {m['prev']:5.1f}%")
    print(f"    '전부 조직검사' 로 찍었을 때 정확도 {m['prev']:5.1f}%  "
          f"(민감도 100% · 특이도 0%)")
    print(f"    -> 정확도가 {m['prev']:.1f}% 를 의미 있게 넘지 못하면 자랑할 수치가 아니다.")
    if m["zeros"]:
        print(f"    assessment 0 ('추가 촬영 필요') {m['zeros']}건 제외")
    if m["unevaluable"]:
        print(f"    서술어가 안 잡혀 판정 불가 {m['unevaluable']}건 제외")
    print("    CBIS 는 조직검사 확정 사례 집합이다. 이 수치는 '검진 성능' 이 아니라")
    print("    '조직검사 대상 병변에 대한 판단 정확도' 다.")


def report(name, pred, gt):
    s = score(pred, gt)
    print(f"\n  ── {name} ──")
    if s is None:
        print("    평가 가능한 행이 없다")
        return None
    print(f"    n={s['n']}"
          + (f"  (서술어 없어 판정 불가 {s['unevaluable']}건 제외)" if s["unevaluable"] else ""))
    print(f"    정확 일치      {s['exact']:5.1f}%")
    print(f"    ±1 이내        {s['within1']:5.1f}%")
    print(f"    평균 부호 오차 {s['signed']:+.2f}   (양수 = 과대평가)")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True, help="학습된 헤드/LoRA 체크포인트")
    ap.add_argument("--rules", default=str(find_rules()))
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--thr", type=float, default=0.5,
                    help="희소 축을 채택할 최소 확률")
    ap.add_argument("--always", default="shape,margin,calctype,calcdist",
                    help="확률과 무관하게 항상 하나를 고를 축 (쉼표 구분)")
    ap.add_argument("--sweep", action="store_true",
                    help="thr 을 0.3~0.7 로 훑어 민감도를 본다")
    a = ap.parse_args()

    device = "cuda"
    R = import_rules(a.rules)
    ext, head, cfg = build_model(a.ckpt, device)
    schema = load_schema(SCHEMA)
    slices = axis_slices(schema, cfg["kind"])
    cols = cfg["cols"]
    always = {s.strip() for s in a.always.split(",") if s.strip()}

    print("\n■ 예측")
    P, Y, G = predict(ext, head, cfg, device, a.batch)

    print(f"\n■ 정답 서술어의 축별 존재율  (n={len(Y)})")
    for ax, (s, e) in slices.items():
        rate = float((Y[:, s:e].sum(1) > 0).mean()) * 100
        mode = "항상 선택" if ax in always else f"확률 {a.thr} 이상일 때만"
        print(f"    {ax:10s} {rate:5.1f}%   -> {mode}")

    thrs = [0.3, 0.4, 0.5, 0.6, 0.7] if a.sweep else [a.thr]
    best = None
    for t in thrs:
        pred_cat = np.array([to_category(R, level_of(
            R, cfg["kind"], to_onehot(P[i], cols, slices, t, always)))
            for i in range(len(P))], dtype=float)
        gt_cat = np.array([to_category(R, level_of(
            R, cfg["kind"], gt_onehot(Y[i], cols)))
            for i in range(len(Y))], dtype=float)

        print("\n" + "=" * 72)
        print(f"임계값 {t}")
        print("=" * 72)
        s_gt = report("① 정답 서술어 → 규칙표   (규칙표만의 성능)", gt_cat, G)
        s_pr = report("② 예측 서술어 → 규칙표   (우리 시스템 성능)", pred_cat, G)
        if s_gt and s_pr:
            print(f"\n  ── 차이 ──")
            print(f"    정확 일치  {s_gt['exact']:.1f}% → {s_pr['exact']:.1f}%"
                  f"   ({s_pr['exact']-s_gt['exact']:+.1f}%p)")
            print(f"    ±1 이내    {s_gt['within1']:.1f}% → {s_pr['within1']:.1f}%"
                  f"   ({s_pr['within1']-s_gt['within1']:+.1f}%p)")
            print("    이 낙폭이 서술어 예측 오류가 등급 정확도를 깎은 몫이다.")
        if s_pr and (best is None or s_pr["exact"] > best[1]["exact"]):
            best = (t, s_pr, pred_cat, gt_cat)

    if best is None:
        sys.exit("평가 가능한 행이 없다 — 서술어가 하나도 안 잡혔다")
    t, s_pr, pred_cat, gt_cat = best
    print("\n" + "=" * 72)
    print(f"혼동행렬 ① 정답 서술어 경로  (규칙표만의 성능)")
    print("=" * 72)
    show_confusion(confusion(gt_cat, G))

    print("\n" + "=" * 72)
    print(f"혼동행렬 ② 예측 서술어 경로  (우리 시스템, 임계값 {t})")
    print("=" * 72)
    show_confusion(confusion(pred_cat, G))

    print("\n" + "=" * 72)
    print("등급별 재현율 — 어느 등급을 아예 못 내는지")
    print("=" * 72)
    show_per_class(per_class(gt_cat, G), per_class(pred_cat, G))
    print("\n    ★ 가 있으면 규칙표는 그 등급을 만들어내는데 모델이 못 만든다는 뜻이다.")
    print("      그 등급을 담당하는 서술어가 희소 클래스라 학습되지 않은 것이다.")

    print("\n" + "=" * 72)
    print(f"조직검사 판단 — 1·2·3 추적  vs  {BIOPSY_CUT}·5 조직검사")
    print("=" * 72)
    print("  6단계 등급은 4a/4b 혼동까지 오답으로 센다. 임상에서 갈리는 결정은")
    print("  '조직검사를 할 것인가' 하나다. 그 기준으로 다시 잰다.")
    b_gt = binary_decision(gt_cat, G)
    b_pr = binary_decision(pred_cat, G)
    show_binary("① 정답 서술어 → 규칙표   (규칙표만의 성능)", b_gt)
    show_binary(f"② 예측 서술어 → 규칙표   (우리 시스템, 임계값 {t})", b_pr)
    if b_gt and b_pr:
        print(f"\n  ── 차이 ──")
        print(f"    정확도  {b_gt['acc']:.1f}% → {b_pr['acc']:.1f}%"
              f"   ({b_pr['acc']-b_gt['acc']:+.1f}%p)")
        print(f"    민감도  {b_gt['sens']:.1f}% → {b_pr['sens']:.1f}%"
              f"   ({b_pr['sens']-b_gt['sens']:+.1f}%p)")
        if b_gt["n"] != b_pr["n"]:
            print(f"    ! 두 경로의 평가 가능 행이 다르다 (①{b_gt['n']} vs ②{b_pr['n']}).")
            print(f"      예측 경로에서 서술어가 안 잡힌 행이 빠진 것이라 직접 비교는 근사다.")
    show_binary_context(b_pr)
    print("\n  ※ 임상에서는 민감도가 특이도보다 중요하다. 조직검사를 한 번 더 하는 것보다")
    print("    암을 놓치는 쪽이 훨씬 비싸다. FN 칸이 이 시스템의 진짜 위험 지점이다.")

    if a.sweep:
        print(f"\n  ※ 임계값은 검증셋에서 정해야 한다. 여기서 최고를 고르면"
              f" 테스트셋 선택 편향이 된다.")


if __name__ == "__main__":
    main()
