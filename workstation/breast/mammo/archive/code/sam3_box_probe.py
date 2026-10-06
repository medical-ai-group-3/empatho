#!/usr/bin/env python
"""
전체 유방촬영에 SAM3 텍스트 프롬프트를 넣어 병변을 잡는지 본다.

두 가지를 한 번에 답한다
  1. 맘모 파이프라인에 검출(박스)을 붙일 수 있는가
  2. 프롬프트가 실제 레버인가 — 문구를 바꾸면 결과가 변하는가

  2번은 음성 대조군("airplane")이 있어야 해석이 갈린다.
    · 전부 같다              -> 텍스트 경로가 무력하다
    · airplane 만 나쁘다     -> 프롬프트는 작동하고 현재 문구가 안정 구간
    · 동의어끼리도 갈린다     -> 프롬프트 설계가 레버다

왜 지금 할 수 있게 됐나
  Sam3Processor 를 찾았다. set_image -> set_text_prompt 두 단계다.
  맘모 파이프라인은 vision_backbone 만 쓰고 나머지를 버리는데(del full),
  여기서는 전체 모델을 그대로 쓴다.

정답 기준
  CBIS 마스크는 원본 전체 크기다(4800x3024 등). 마스크의 0 아닌 영역이
  곧 병변 박스이므로 IoU 를 잴 수 있다.

첫 실행은 반환 구조를 모르므로 --inspect 로 무엇이 나오는지부터 본다.

사용
  python3 sam3_box_probe.py --inspect          # 반환 구조 확인 (1건)
  python3 sam3_box_probe.py --n 5              # 5건 x 프롬프트 전부
  python3 sam3_box_probe.py --n 5 --save out/  # 시각화 PNG 저장
"""

import argparse, sys, time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import torch
from train_mammo import load_merged_model, CFG, CKPT, INDEX_DIR

RAW = Path.home() / "workspace/breast/data/cbis/raw"

# 음성 대조군을 반드시 포함한다. 없으면 '전부 같음'과 '프롬프트 무력'을
# 구분할 수 없다.
#   1차 실측(n=30)에서 lesion 0.179 > mass 0.135 > breast mass 0.063 이었다.
#   구체적인 문구가 오히려 나빴다 — SAM3 개념 어휘에 "breast mass"가 없고
#   "lesion"·"mass"는 있는 것으로 보인다. 그래서 일반적인 어휘를 더 넣었다.
PROMPTS = {
    "mass": ["lesion", "mass", "nodule", "tumor", "opacity", "abnormality",
             "", "airplane"],
    "calc": ["calcification", "microcalcification", "lesion", "white spot",
             "bright spot", "abnormality", "", "airplane"],
}


def load_dicom(path):
    """
    DICOM 을 3채널 uint8 로 만든다. 축 순서는 호출부에서 정한다 —
    Sam3Processor 가 HWC 를 받는지 CHW 를 받는지 실측으로 확인하기 때문이다.
    반환: (H, W, 3)
    """
    import pydicom
    arr = pydicom.dcmread(str(path)).pixel_array.astype(np.float32)
    lo, hi = float(arr.min()), float(arr.max())
    arr = (arr - lo) / (hi - lo + 1e-8)
    u8 = (arr * 255).astype(np.uint8)
    return np.stack([u8, u8, u8], axis=-1)      # HxWx3


def downscale(img_hwc, max_side):
    """
    긴 변을 max_side 로 줄인다. 반환 (줄인 영상, 배율).

    왜 줄이는가
      마스크가 원본 해상도로 나온다. 질의 수백 개 x 4006 x 1846 x 4바이트면
      7GB 다. 실제로 OOM 이 났다. 백본은 어차피 내부에서 1008 로 줄이므로
      입력을 미리 줄여도 백본이 보는 것은 같다.

    박스는 같은 배율로 정답도 줄여서 비교하면 되므로 좌표 복원이 필요 없다.
    """
    H, W = img_hwc.shape[:2]
    m = max(H, W)
    if m <= max_side:
        return img_hwc, 1.0
    s = max_side / m
    nh, nw = max(1, round(H * s)), max(1, round(W * s))
    t = torch.from_numpy(img_hwc.transpose(2, 0, 1)).float()[None]
    t = torch.nn.functional.interpolate(t, size=(nh, nw), mode="bilinear",
                                        align_corners=False)
    out = t[0].clamp(0, 255).byte().numpy().transpose(1, 2, 0)
    return np.ascontiguousarray(out), s


def scale_box(b, s):
    return None if b is None else tuple(float(v) * s for v in b)


def crop_breast(img_hwc, rel_thr=0.05, rel_line=0.1):
    """
    유방 영역만 잘라낸다. 반환 (잘린 영상, (ox, oy)).

    왜
      유방촬영은 검은 배경이 화면의 절반 가까이 차지한다. 그대로 넣으면
      병변이 화면에서 차지하는 비율이 더 작아진다. 실측에서 정답 박스가
      영상 면적의 0.3% 수준이었다.

    어떻게
      밝은 화소가 많은 행/열만 남긴다. 단순 임계값 bbox 는 모서리의 촬영
      표식 같은 작은 밝은 점에 끌려간다.

      기준을 '폭의 몇 %' 같은 절대값으로 두면 표식 크기에 따라 뚫린다
      (실제로 20픽셀 표식이 1% 기준 18픽셀을 넘겨 통과했다). 그래서 가장
      밝은 행 대비 상대값으로 잡는다 — 유방 크기에 자동으로 맞춰진다.
    """
    g = img_hwc[:, :, 0]
    bright = g > (g.max() * rel_thr)
    rc, cc = bright.sum(1), bright.sum(0)
    rows = rc > max(rc.max() * rel_line, 1)
    cols = cc > max(cc.max() * rel_line, 1)
    if not rows.any() or not cols.any():
        return img_hwc, (0, 0)
    y0, y1 = int(np.argmax(rows)), int(len(rows) - np.argmax(rows[::-1]))
    x0, x1 = int(np.argmax(cols)), int(len(cols) - np.argmax(cols[::-1]))
    return np.ascontiguousarray(img_hwc[y0:y1, x0:x1]), (x0, y0)


def pad_square(img_hwc):
    """
    우/하단에 0 을 채워 정사각으로 만든다. 좌표가 안 변하므로 정답 박스를
    손댈 필요가 없다.

    왜
      Sam3Processor 가 v2.Resize((1008,1008)) 로 정사각 변형한다. 유방촬영은
      세로가 2배 이상 길어서 그대로 넣으면 가로로 늘어난다. 미리 정사각으로
      만들어두면 리사이즈가 등방이 되어 모양이 안 뭉개진다.
    """
    H, W = img_hwc.shape[:2]
    S = max(H, W)
    if H == W:
        return img_hwc
    out = np.zeros((S, S, img_hwc.shape[2]), dtype=img_hwc.dtype)
    out[:H, :W] = img_hwc
    return out


def _slide(total, size, stride):
    """한 축의 시작점들. 마지막 타일은 끝에 붙여 빈틈을 없앤다."""
    if total <= size:
        return [0]
    pos = list(range(0, total - size + 1, stride))
    if pos[-1] != total - size:
        pos.append(total - size)
    return pos


def tile_positions(H, W, overlap, size=None):
    """
    타일 배치를 정한다. 정사각 타일을 겹쳐가며 깐다.

    한 변을 정하는 두 가지 방식
      · size 를 안 주면 짧은 쪽 길이 — 유방 영역(약 1000x3000)이면 4장이면 덮인다.
        종괴처럼 큰 표적에 맞는다.
      · size 를 주면 그 크기로 격자를 깐다. 미세석회처럼 작은 표적은
        타일을 작게 잡아야 확대율이 올라간다.

    확대율이 전부다. 3000px 를 1008 로 줄이면 60px 병변이 20px 가 되지만,
    1000px 타일이면 60px, 384px 타일이면 157px 가 된다.
    미세석회(0.3mm, 약 5px)는 전체 영상에서는 화소 하나 미만으로 사라진다.

    반환: [(x0, y0, size), ...]
    """
    if size is None:
        size = min(H, W)
    size = max(1, min(int(size), H, W))          # 영상보다 크면 줄인다
    stride = max(1, int(size * (1 - overlap)))
    ys = _slide(H, size, stride)
    xs = _slide(W, size, stride)
    return [(x, y, size) for y in ys for x in xs]


def prepare(img_hwc, gt, max_side, crop=True, pad=True):
    """크롭 -> 축소 -> 정사각 패딩. 정답 박스도 같이 옮긴다."""
    steps = []
    if crop:
        img_hwc, (ox, oy) = crop_breast(img_hwc)
        if gt:
            gt = (gt[0] - ox, gt[1] - oy, gt[2] - ox, gt[3] - oy)
        steps.append(f"크롭 {img_hwc.shape[1]}x{img_hwc.shape[0]}")
    img_hwc, sc = downscale(img_hwc, max_side)
    gt = scale_box(gt, sc)
    steps.append(f"축소 x{sc:.3f}")
    if pad:
        img_hwc = pad_square(img_hwc)
        steps.append(f"패딩 {img_hwc.shape[1]}x{img_hwc.shape[0]}")
    return img_hwc, gt, "  ".join(steps)


def set_image_checked(proc, img_hwc, verbose=True):
    """
    set_image 를 부르되 프로세서가 크기를 제대로 읽었는지 확인한다.

    왜 PIL 로 넣는가 — SAM3 코드의 모순 때문이다.

        elif isinstance(image, (torch.Tensor, np.ndarray)):
            height, width = image.shape[-2:]     # CHW 를 가정
        ...
        image = v2.functional.to_image(image)    # HWC 를 기대

    넘파이 입력은 크기 읽기가 CHW 를, 변환이 HWC 를 가정한다. 그래서 어느
    축 순서로 넣어도 맞지 않는다. HWC 로 넣으면 width 가 채널 수(3)로 잡히고,
    CHW 로 넣으면 변환 단계에서 터진다. 둘 다 실측으로 확인했다.

    PIL 로 넣으면 첫 분기가 image.size 를 제대로 읽고 변환도 정상이다.

    크기 확인은 그대로 둔다. 조용히 틀리는 것이 이 실험에서 가장 위험하다 —
    폭 3픽셀 영상에 대한 IoU 도 숫자로는 그럴듯하게 나온다.
    """
    H, W = img_hwc.shape[:2]
    try:
        from PIL import Image
        img_in, how = Image.fromarray(img_hwc), "PIL"
    except ImportError:
        img_in, how = img_hwc, "numpy(HWC)"

    state = proc.set_image(img_in)
    gh, gw = state.get("original_height"), state.get("original_width")
    if (gh, gw) != (H, W):
        sys.exit(f"set_image 가 크기를 잘못 읽었다: H={gh} W={gw}, 기대 {H}x{W}\n"
                 f"  입력 방식 {how}. Pillow 가 없으면 설치해라: pip install pillow")
    if verbose:
        print(f"    입력 {how}  ·  프로세서가 읽은 크기 H={gh} W={gw}  확인")
    return state, how


def mask_bbox(path):
    """마스크에서 정답 박스를 뽑는다. 반환 (x0, y0, x1, y1) 또는 None."""
    import pydicom
    m = pydicom.dcmread(str(path)).pixel_array
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def iou(a, b):
    if a is None or b is None:
        return float("nan")
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    ar = (a[2] - a[0]) * (a[3] - a[1])
    br = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (ar + br - inter + 1e-9)


def resolve_full_image(image_path):
    """image_path 의 SeriesUID 로 실제 DICOM 을 찾는다."""
    uid = str(image_path).strip().split("/")[-2]
    d = RAW / uid
    if not d.exists():
        return None
    files = sorted(d.glob("*.dcm"))
    return files[0] if files else None


def describe(obj, indent=0, depth=0):
    """반환값 구조를 재귀로 찍는다. 첫 실행에서 형식을 파악하기 위한 것."""
    pad = "  " * (indent + 1)
    if depth > 3:
        print(f"{pad}...")
        return
    if isinstance(obj, dict):
        print(f"{pad}dict, 키 {list(obj.keys())}")
        for k, v in list(obj.items())[:8]:
            print(f"{pad}  [{k}]")
            describe(v, indent + 2, depth + 1)
    elif isinstance(obj, (list, tuple)):
        print(f"{pad}{type(obj).__name__}, 길이 {len(obj)}")
        for v in obj[:3]:
            describe(v, indent + 1, depth + 1)
    elif isinstance(obj, np.ndarray):
        print(f"{pad}ndarray {obj.shape} {obj.dtype} "
              f"min={obj.min() if obj.size else '-'} max={obj.max() if obj.size else '-'}")
    elif torch.is_tensor(obj):
        print(f"{pad}Tensor {tuple(obj.shape)} {obj.dtype}")
    else:
        s = repr(obj)
        print(f"{pad}{type(obj).__name__}: {s[:120]}")


def extract_boxes(result, W, H):
    """
    반환값에서 박스를 꺼낸다. 구조를 모르므로 흔한 형태를 차례로 시도한다.
    --inspect 로 실제 구조를 본 뒤 여기를 확정하면 된다.
    반환: [(x0,y0,x1,y1,score), ...]
    """
    def as_np(x):
        return x.detach().cpu().numpy() if torch.is_tensor(x) else np.asarray(x)

    boxes = scores = None
    if isinstance(result, dict):
        for k in ("boxes", "pred_boxes", "bbox", "bboxes"):
            if k in result:
                boxes = as_np(result[k]); break
        for k in ("scores", "confidence", "pred_scores", "logits"):
            if k in result:
                scores = as_np(result[k]); break
        if boxes is None:                       # 마스크만 있으면 마스크에서 박스
            for k in ("masks", "pred_masks", "segmentation"):
                if k in result:
                    m = as_np(result[k])
                    out = []
                    m = m if m.ndim == 3 else m[None]
                    for i in range(len(m)):
                        ys, xs = np.nonzero(m[i] > 0.5)
                        if len(xs):
                            out.append((int(xs.min()), int(ys.min()),
                                        int(xs.max()), int(ys.max()), 1.0))
                    return out
    elif isinstance(result, (list, tuple)) and len(result) >= 2:
        # predict_inst 계열: (masks, scores, boxes) 로 추정
        cand = [as_np(x) for x in result if x is not None]
        for c in cand:
            if c.ndim == 2 and c.shape[-1] == 4:
                boxes = c
            elif c.ndim == 1:
                scores = c

    if boxes is None:
        return []
    boxes = np.asarray(boxes, dtype=float).reshape(-1, 4)
    # 정규화 좌표면 화소로 되돌린다
    if boxes.size and boxes.max() <= 1.5:
        boxes = boxes * np.array([W, H, W, H])
    if scores is None or len(scores) != len(boxes):
        scores = np.ones(len(boxes))
    return [(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s))
            for b, s in zip(boxes, np.asarray(scores).reshape(-1))]


def save_png(img, gt, preds, path, title):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
    except ImportError:
        return False
    fig, ax = plt.subplots(figsize=(6, 8))
    ax.imshow(img[:, :, 0], cmap="gray")
    if gt:
        ax.add_patch(patches.Rectangle((gt[0], gt[1]), gt[2]-gt[0], gt[3]-gt[1],
                                       fill=False, edgecolor="lime", lw=2))
    for (x0, y0, x1, y1, s) in preds[:5]:
        ax.add_patch(patches.Rectangle((x0, y0), x1-x0, y1-y0,
                                       fill=False, edgecolor="red", lw=1.5))
        ax.text(x0, max(y0 - 10, 0), f"{s:.2f}", color="red", fontsize=8)
    ax.set_title(title, fontsize=9)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["mass", "calc"], default="mass")
    ap.add_argument("--split", default="test")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--ckpt", default=CKPT)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--thr", type=float, default=0.5)
    ap.add_argument("--tile", action="store_true",
                    help="유방 폭 크기의 정사각 타일로 나눠 각각 추론한다")
    ap.add_argument("--tile-overlap", type=float, default=0.25)
    ap.add_argument("--tile-size", type=int, default=0,
                    help="타일 한 변(px). 0 이면 짧은 쪽 길이. "
                         "미세석회처럼 작은 표적은 384~512 를 권한다")
    ap.add_argument("--no-crop", action="store_true",
                    help="유방 영역 크롭을 끈다 (비교용)")
    ap.add_argument("--no-pad-square", action="store_true",
                    help="정사각 패딩을 끈다 (비교용)")
    ap.add_argument("--prompts", default="",
                    help="쉼표로 직접 지정. 빈 문자열 항목은 __empty__ 로 쓴다")
    ap.add_argument("--max-side", type=int, default=1024,
                    help="긴 변을 이만큼으로 줄인다. 원본 크기로 넣으면 마스크가 "
                         "원본 해상도로 나와 OOM 이 난다(실측 7GB 요구)")
    ap.add_argument("--inspect", action="store_true",
                    help="반환 구조만 찍고 끝낸다 (1건, 프롬프트 1개)")
    ap.add_argument("--save", default="", help="시각화 PNG 를 저장할 폴더")
    a = ap.parse_args()

    import pandas as pd
    idx = Path(INDEX_DIR) / f"roi_index_{a.kind}_{a.split}.csv"
    df = pd.read_csv(idx)
    print(f"■ 인덱스 {idx.name}  {len(df)}건")

    # 전체 영상과 마스크가 둘 다 있는 행만 고른다
    rows = []
    for r in df.to_dict("records"):
        if not str(r.get("mask_file", "")):
            continue
        full = resolve_full_image(r["image_path"])
        if full is None:
            continue
        rows.append((r, full))
        if len(rows) >= (1 if a.inspect else a.n):
            break
    if not rows:
        sys.exit("전체 영상을 못 찾았다 — image_path 의 SeriesUID 디렉터리가 없다.\n"
                 "  크롭과 마스크만 받아둔 상태라면 이 실험은 불가능하다.")
    print(f"  전체 영상 + 마스크가 모두 있는 행 {len(rows)}건 확보\n")

    print("■ 모델 로드 (전체 — vision 만이 아니다)")
    model = load_merged_model(a.ckpt, CFG, device=a.device)
    from sam3.model.sam3_image_processor import Sam3Processor
    proc = Sam3Processor(model, device=a.device, confidence_threshold=a.thr)
    print(f"  Sam3Processor 준비 완료 (resolution 기본 1008)\n")

    prompts = PROMPTS[a.kind]
    if a.prompts:
        prompts = ["" if x == "__empty__" else x for x in a.prompts.split(",")]
    if a.inspect:
        prompts = prompts[:1]

    outdir = Path(a.save) if a.save else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)

    # 프롬프트별 IoU 를 모은다
    table = {p: [] for p in prompts}

    for i, (r, full) in enumerate(rows):
        img0 = load_dicom(full)
        H0, W0 = img0.shape[:2]
        gt0 = mask_bbox(r["mask_file"])
        # 타일링일 때는 두 가지를 하지 않는다.
        #  · 정사각 패딩 — 패딩하면 min(H,W)==max(H,W) 라 타일이 1장이 되어 무효가 된다
        #  · 전체 축소 — 타일마다 따로 축소하므로 여기서 미리 줄이면 해상도만 버린다
        img, gt, steps = prepare(img0, gt0,
                                 10 ** 9 if a.tile else a.max_side,
                                 crop=not a.no_crop,
                                 pad=(not a.no_pad_square) and not a.tile)
        H, W = img.shape[:2]
        # 병변이 화면에서 차지하는 비율 — 작을수록 어려운 과제다
        frac = (((gt[2]-gt[0]) * (gt[3]-gt[1])) / (H * W) * 100) if gt else float("nan")
        print(f"[{i+1}/{len(rows)}] {r['patient_id']} {r['side']} {r['view']}  "
              f"{W0}x{H0}  {steps}")
        print(f"    정답박스 {tuple(int(v) for v in gt) if gt else None}  "
              f"(화면의 {frac:.2f}%)")

        if a.tile:
            tiles = tile_positions(H, W, a.tile_overlap,
                                   a.tile_size or None)
            if i == 0:
                zoom = 1008 / tiles[0][2]
                print(f"    타일 {len(tiles)}장  한 변 {tiles[0][2]}px  "
                      f"겹침 {a.tile_overlap:.0%}  확대 x{zoom:.1f}")
                if len(tiles) == 1:
                    sys.exit(
                        "\n! 타일이 1장이다 — 타일링이 아무 일도 하지 않는다.\n"
                        f"  영상이 {W}x{H} 로 정사각에 가깝다. 원인은 보통 정사각 패딩이다.\n"
                        "  --no-pad-square 를 붙이거나 크롭 결과를 확인해라.")
            per_prompt = {p: [] for p in prompts}
            t0 = time.time()
            for (tx, ty, tsz) in tiles:
                sub = np.ascontiguousarray(img[ty:ty+tsz, tx:tx+tsz])
                sub, _ = downscale(sub, a.max_side)
                sc_t = tsz / sub.shape[0]        # 타일 내부 좌표 -> 원래 배율
                st = set_image_checked(proc, sub, verbose=False)[0]
                for p in prompts:
                    try:
                        res = proc.set_text_prompt(p, st)
                    except Exception:
                        continue
                    for b in extract_boxes(res, sub.shape[1], sub.shape[0]):
                        per_prompt[p].append((b[0]*sc_t + tx, b[1]*sc_t + ty,
                                              b[2]*sc_t + tx, b[3]*sc_t + ty, b[4]))
            el = time.time() - t0
            for p in prompts:
                preds = per_prompt[p]
                best = max((iou(gt, b[:4]) for b in preds), default=0.0)
                table[p].append((best, len(preds)))
                print(f"    {p or '(빈 문자열)':22s} 박스 {len(preds):2d}개  "
                      f"최고 IoU {best:.3f}")
            print(f"    ({el:.1f}s / {len(tiles)}타일)")
            if outdir:
                allb = [b for p in prompts for b in per_prompt[p]]
                save_png(img, gt, allb, outdir / f"{a.kind}_{i}_tiled.png",
                         f"타일 {len(tiles)}장 · 전체 프롬프트")
            continue

        state, axis_order = set_image_checked(proc, img, verbose=(i == 0))
        for p in prompts:
            t0 = time.time()
            try:
                res = proc.set_text_prompt(p, state)
            except Exception as e:
                print(f"    '{p}' -> 호출 실패 {type(e).__name__}: {e}")
                continue

            if a.inspect:
                print(f"\n  ── set_text_prompt('{p}') 반환 구조 ──")
                describe(res)
                print(f"\n  ── state 키 ──")
                describe(state)
                print("\n  이 구조를 보고 extract_boxes() 를 확정하면 된다.")
                return

            preds = extract_boxes(res, W, H)
            # 박스가 없으면 IoU 0 이다. nan 으로 빼면 '박스를 적게 내는
            # 프롬프트' 가 평균에서 유리해진다 — 검출 실패도 실패다.
            best = max((iou(gt, b[:4]) for b in preds), default=0.0)
            table[p].append((best, len(preds)))
            print(f"    {p or '(빈 문자열)':22s} 박스 {len(preds):2d}개  "
                  f"최고 IoU {best:.3f}  ({time.time()-t0:.1f}s)")

            if outdir:
                png = outdir / f"{a.kind}_{i}_{(p or 'empty').replace(' ','_')}.png"
                save_png(img, gt, preds, png, f"{p or '(empty)'}  IoU {best:.3f}")

    # ── 정리 ──────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print(f"프롬프트별 결과  (n={len(rows)})")
    print("=" * 78)
    print(f"  {'프롬프트':22s}{'평균 IoU':>10s}{'검출률':>9s}"
          f"{'IoU>0.5':>9s}{'IoU>0.3':>9s}{'박스/건':>9s}")
    print("  " + "-" * 74)
    for p in prompts:
        vals = table[p]
        if not vals:
            continue
        ious = [v for v, _ in vals]
        nb = [n for _, n in vals]
        det = sum(1 for n in nb if n > 0) / len(nb)
        hit5 = sum(1 for v in ious if v > 0.5) / len(ious)
        hit3 = sum(1 for v in ious if v > 0.3) / len(ious)
        tag = "  <- 음성 대조군" if p == "airplane" else ""
        print(f"  {p or '(빈 문자열)':22s}{np.mean(ious):>10.3f}{det:>8.0%}"
              f"{hit5:>9.0%}{hit3:>9.0%}{np.mean(nb):>9.1f}{tag}")
    print("\n  ※ 박스가 없으면 IoU 0 으로 센다. 검출 실패도 실패다.")

    print("\n해석")
    print("  전부 비슷하다              -> 텍스트 경로가 무력하다")
    print("  airplane 만 낮다           -> 프롬프트는 작동하고 현재 문구가 안정 구간")
    print("  동의어끼리도 갈린다        -> 프롬프트 설계가 실제 레버다")
    print("\n  ※ 추론은 결정적이라 1회씩으로 비교가 성립한다 (학습과 다르다).")


if __name__ == "__main__":
    main()
