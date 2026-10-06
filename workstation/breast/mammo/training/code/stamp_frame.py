#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""검출 JSON 에 좌표계를 박아 넣는다 — 읽는 쪽이 추측하지 않게.

왜
  검출 파일의 `box` 는 **조직 상자 기준**이다. 그런데 파일 어디에도 그 말이
  없고, 원본으로 되돌릴 원점도 없다. 읽는 쪽이 매번

      tissue_bbox(tissue_mask(norm8(arr, 99.9)), pad=32)

  를 다시 계산해야 하고, 하나라도 다르게 부르면 **영상마다 수백 화소씩
  어긋나는데 오류는 안 난다.** 이 프로젝트에서 좌표계로 세 번 사고 났다.

  DB 스키마 v8 이 `lesion.detail.frame` 과 `image.frame` 을 필수로 정했다.
  MRI 쪽은 이미 `evidence.frame` 에 `pixel` / `resampled_1mm` 을 적고 있다.
  우리도 같은 방식으로 맞춘다.

무엇을 넣나 — 기존 키는 안 건드린다
    {
      "frame": "tissue_crop",
      "frame_note": "원본 = box + origin[img][:2]",
      "origin": { "<img>": [cx0, cy0, w, h], ... },
      "origin_params": {"clip": 99.9, "pad": 32},
      "calcification": [...],      ← 그대로
      "mass": [...]                ← 그대로
    }

  **순수 추가라 기존 도구가 안 깨진다.** score_dets 는 raw.get(kind) 만 읽고,
  depth_rescore·rescore_* 는 종류가 아닌 키를 그대로 복사하므로 파생 파일에도
  frame 이 따라간다.

원점 구하기
  DICOM 을 읽어야 하지만 이미 만들어 둔 캐시가 있으면 그걸 쓴다.
    docs/show_gt_cache.json   (test · origin)
    docs/twoview_cache.json   (test · origin)
  없으면 직접 계산한다 (CPU · 598장에 몇 분).

검산도 한다
  박은 원점으로 상자를 원본 좌표로 되돌려 **영상 밖으로 나가지 않는지** 본다.
  원점이 틀리면 여기서 걸린다.

사용
  python3 training/code/stamp_frame.py archive/outputs/*.json          # 확인만
  python3 training/code/stamp_frame.py archive/outputs/*.json --apply
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    import pydicom
except ImportError as e:
    sys.exit(f"필요 패키지 없음: {e}")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_mammo_det as E                                    # noqa: E402

PROMPTS = getattr(E, "PROMPTS", ["calcification", "mass"])
FRAME = "tissue_crop"
NOTE = ("box 는 조직 상자 기준이다. 원본 화소로 되돌리려면 "
        "origin[img] 의 앞 두 값을 더한다 — 원본 = box + (cx0, cy0). "
        "origin 은 tissue_bbox(tissue_mask(norm8(arr, clip)), pad) 로 정했다.")


def rp(p):
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p)


def die(*m):
    print("\n[중단]", *m)
    sys.exit(2)


def load_cached_origin(paths):
    """이미 만들어 둔 캐시에서 원점을 모은다. DICOM 을 안 읽어도 되면 안 읽는다."""
    out = {}
    for p in paths:
        f = rp(p)
        if not f.is_file():
            continue
        try:
            j = json.loads(f.read_text())
        except Exception:
            continue
        # show_gt_cache: {"origin": {uid: [x,y,w,h]}}
        if isinstance(j.get("origin"), dict):
            for u, v in j["origin"].items():
                out.setdefault(str(u), [int(x) for x in v])
        # twoview_cache: {"img": {uid: {"origin": [...]}}}
        for u, d in (j.get("img") or {}).items():
            if isinstance(d, dict) and "origin" in d:
                out.setdefault(str(u), [int(x) for x in d["origin"]])
    return out


def compute_origin(uids, split, clip, pad):
    """캐시에 없는 것만 DICOM 을 읽어 잰다."""
    ents = E.load_gt(split)
    out, miss, skipped = {}, [], 0
    todo = [u for u in uids if u in ents]
    miss = [u for u in uids if u not in ents]
    print(f"  DICOM 을 읽어 원점 계산 — {len(todo):,}장")
    for i, uid in enumerate(todo, 1):
        try:
            arr = pydicom.dcmread(str(ents[uid]["dcm"])).pixel_array
        except Exception:
            skipped += 1
            continue
        if arr.ndim != 2:
            skipped += 1
            continue
        tb = E.tissue_bbox(E.tissue_mask(E.norm8(arr, clip)), pad)
        if tb is None:
            skipped += 1
            continue
        cx0, cy0, cx1, cy1 = tb
        out[uid] = [int(cx0), int(cy0), int(cx1 - cx0), int(cy1 - cy0)]
        if i % 25 == 0 or i == len(todo):
            print(f"\r    {i}/{len(todo)}", end="", flush=True)
    if todo:
        print()
    if skipped:
        print(f"  못 읽어서 빠진 영상 {skipped}장")
    return out, miss


def check(raw, origin):
    """되돌린 상자가 조직 상자 밖으로 «얼마나» 나가나.

    개수만 세면 판단이 안 된다. 원점이 진짜 틀렸으면 **수백 화소씩, 거의
    모든 상자가** 어긋난다. 타일 경계에서 몇 화소 넘치는 것은 정상이라
    잘라내면 그만이다. 그래서 크기를 잰다.
    """
    over, seen = [], 0
    for kind in PROMPTS:
        for d in raw.get(kind, []):
            u = str(d["img"])
            o = origin.get(u)
            if not o:
                continue
            seen += 1
            x0, y0, x1, y1 = (float(v) for v in d["box"])
            e = max(-x0, -y0, x1 - o[2], y1 - o[3], 0.0)
            if e > 0:
                over.append(e)
    if not over:
        return seen, 0, 0.0, 0.0
    over.sort()
    return (seen, len(over), over[-1],
            over[min(len(over) - 1, int(len(over) * 0.99))])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--split", default="test")
    ap.add_argument("--clip", type=float, default=99.9)
    ap.add_argument("--pad", type=int, default=32)
    ap.add_argument("--cache", default="docs/show_gt_cache.json,docs/twoview_cache.json")
    ap.add_argument("--tol", type=float, default=64.0,
                    help="조직 상자 밖으로 이만큼까지는 정상으로 본다. "
                         "실측 최대 58화소(99퍼 15) — 타일 경계에서 "
                         "넘치는 몫이다")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    print("=" * 82)
    print("검출 JSON 에 좌표계 박기 — 읽는 쪽이 추측하지 않게")
    print("=" * 82)

    files = [rp(f) for f in a.files]
    files = [f for f in files if f.is_file()]
    if not files:
        die("파일이 하나도 없다.")

    uids = set()
    for f in files:
        raw = json.loads(f.read_text())
        for kind in PROMPTS:
            for d in raw.get(kind, []):
                uids.add(str(d["img"]))
    print(f"  파일 {len(files)}개 · 영상 {len(uids):,}장")

    origin = load_cached_origin(a.cache.split(","))
    have = {u: origin[u] for u in uids if u in origin}
    print(f"  캐시에서 원점 {len(have):,}장 확보")

    need = sorted(uids - set(have))
    if need:
        got, miss = compute_origin(need, a.split, a.clip, a.pad)
        have.update(got)
        if miss:
            print(f"  ⚠ split={a.split} 에 없는 영상 {len(miss)}장 — "
                  f"다른 split 파일이면 --split 을 줄 것 (예: {miss[:2]})")
    print(f"  최종 원점 {len(have):,}/{len(uids):,}장")
    if len(have) < len(uids):
        print("  ⚠ 원점을 못 구한 영상이 있다. 그 영상은 origin 에 안 들어간다.")

    off = sum(1 for v in have.values() if v[0] or v[1])
    print(f"  원점이 (0,0) 이 아닌 영상 {off}/{len(have)}장 "
          "— 이만큼이 좌표계를 틀리면 통째로 어긋나는 몫이다")

    print(f"\n  {'파일':<50}{'상자':>9}{'밖':>7}{'비율':>8}{'최대':>8}{'99퍼':>7}")
    plan, worst = [], 0.0
    for f in files:
        raw = json.loads(f.read_text())
        seen, n, mx, p99 = check(raw, have)
        worst = max(worst, mx)
        print(f"  {f.name[:50]:<50}{seen:>9,}{n:>7,}"
              f"{(100.0*n/seen if seen else 0):>7.1f}%{mx:>8.0f}{p99:>7.0f}")
        if "frame" in raw and raw["frame"] != FRAME:
            print(f"      ! 이미 frame={raw['frame']} 이 박혀 있다. 건너뛴다")
            continue
        plan.append((f, raw))

    print(f"\n  가장 많이 넘친 양 {worst:.0f}화소 (허용 {a.tol:.0f})")
    if worst > a.tol:
        die(f"상자가 조직 상자 밖으로 {worst:.0f}화소나 나갔다. 원점이 틀렸을 수 있다.\n"
            "  --split 이 맞는지, clip·pad 가 검출을 만들 때와 같은지 확인할 것.\n"
            "  타일 경계에서 넘친 것이 확실하면 --tol 을 올려서 넘어갈 수 있다.")
    print("  타일 경계에서 몇 화소 넘친 것이다 — 원점 문제가 아니다.")
    print("  화면에 그릴 때 조직 상자로 잘라 쓰면 된다.")

    print(f"\n  박을 파일 {len(plan)}개")
    if not a.apply:
        print("\n  --apply 를 줘야 실제로 고친다. 지금은 확인만 했다.")
        return

    for f, raw in plan:
        shutil.copy2(f, f.with_suffix(f.suffix + ".bak"))
        # 좌표계 키를 «앞에» 두고 나머지를 그대로 잇는다. 검출 목록은
        # 손대지 않는다 — 순수 추가여야 기존 도구가 안 깨진다.
        stamped = {
            "frame": FRAME,
            "frame_note": NOTE,
            "origin_params": {"clip": a.clip, "pad": a.pad, "split": a.split},
            "origin": {u: have[u] for u in sorted(have)},
        }
        for k, v in raw.items():
            if k not in stamped:
                stamped[k] = v
        f.write_text(json.dumps(stamped, ensure_ascii=False, default=float))
        print(f"  박았다 {f.name}  (원본 {f.name}.bak)")

    print("""
  확인 — 채점 결과가 그대로여야 한다 (키를 더하기만 했으므로)

    python3 training/code/score_dets.py \\
      archive/outputs/tile_dets_wbf03_tissue_t30_pwmix_calc015_mass035.json \\
      --save /tmp/score_check.json | tail -20

  석회 77.5 · 종괴 76.7 이 그대로 나와야 한다. 달라지면 되돌릴 것 —
  원본이 .bak 로 남아 있다.""")


if __name__ == "__main__":
    main()
