"""
CBIS-DDSM 다운로드  —  SSH 전용 · sudo 불필요 · 이어받기 지원
──────────────────────────────────────────────────────────────
NBIA Data Retriever(GUI/Java/sudo 필요) 대신 TCIA 공식 파이썬 패키지를 쓴다.

    pip install tcia_utils
    python cbis_download.py

중간에 끊겨도 다시 실행하면 안 받은 것만 이어받는다.
tmux 안에서 돌릴 것 —  tmux new -s dl
"""

import argparse, json, os, sys, time

try:
    from tcia_utils import nbia
except ImportError:
    sys.exit("tcia_utils 가 없습니다 →  pip install tcia_utils")

ap = argparse.ArgumentParser()
ap.add_argument("--out",        default="./cbis/raw", help="저장 폴더")
ap.add_argument("--collection", default="CBIS-DDSM")
ap.add_argument("--chunk",      type=int, default=50,  help="한 번에 받을 시리즈 수")
ap.add_argument("--workers",    type=int, default=8,   help="병렬 다운로드 수")
ap.add_argument("--limit",      type=int, default=0,   help="테스트용: N개만 (0=전체)")
ap.add_argument("--list-only",  action="store_true",   help="목록만 뽑고 종료")
args = ap.parse_args()

OUT   = os.path.abspath(args.out)
CACHE = os.path.join(OUT, "_series_list.json")
os.makedirs(OUT, exist_ok=True)

# ── 1. 시리즈 목록 (한 번만 받아서 캐시) ────────────────────────
if os.path.exists(CACHE):
    series = json.load(open(CACHE, encoding="utf-8"))
    print(f"[목록] 캐시 사용 — {len(series)}개")
else:
    print(f"[목록] {args.collection} 조회 중…")
    series = nbia.getSeries(collection=args.collection)
    if not series:
        sys.exit("시리즈 목록을 못 받았습니다. 네트워크/컬렉션명을 확인하세요.")
    json.dump(series, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"[목록] {len(series)}개 → 캐시 저장 {CACHE}")

uids = [s["SeriesInstanceUID"] for s in series if s.get("SeriesInstanceUID")]
uids = sorted(set(uids))
if args.limit:
    uids = uids[:args.limit]

# 참고: 시리즈 설명 분포 (full / cropped / ROI mask 구성 확인용)
desc = {}
for s in series:
    d = (s.get("SeriesDescription") or "?").strip()
    desc[d] = desc.get(d, 0) + 1
print("[구성] SeriesDescription 분포:")
for k, v in sorted(desc.items(), key=lambda x: -x[1])[:10]:
    print(f"        {v:6d}  {k}")

if args.list_only:
    sys.exit(0)

# ── 2. 이미 받은 것 제외 ────────────────────────────────────────
def done(uid):
    d = os.path.join(OUT, uid)
    return os.path.isdir(d) and any(f.lower().endswith(".dcm") for f in os.listdir(d))

todo = [u for u in uids if not done(u)]
print(f"\n[진행] 전체 {len(uids)} · 완료 {len(uids)-len(todo)} · 남음 {len(todo)}")
if not todo:
    print("모두 완료됐습니다.")
    sys.exit(0)

# ── 3. 청크 단위 다운로드 (중간에 죽어도 이어받기 가능) ──────────
t0 = time.time()
for i in range(0, len(todo), args.chunk):
    chunk = todo[i:i + args.chunk]
    n = i + len(chunk)
    try:
        nbia.downloadSeries(chunk, input_type="list", path=OUT,
                            max_workers=args.workers)
    except KeyboardInterrupt:
        print("\n중단됨. 다시 실행하면 이어받습니다.")
        sys.exit(130)
    except Exception as e:
        print(f"  !! 청크 실패({type(e).__name__}: {e}) — 계속 진행, 마지막에 재시도하세요")
        continue

    el  = time.time() - t0
    rate = n / el if el else 0
    eta = (len(todo) - n) / rate / 60 if rate else 0
    print(f"[{n}/{len(todo)}]  경과 {el/60:.1f}분 · 남은 예상 {eta:.0f}분")

# ── 4. 마무리 확인 ──────────────────────────────────────────────
left = [u for u in uids if not done(u)]
size = sum(os.path.getsize(os.path.join(r, f))
           for r, _, fs in os.walk(OUT) for f in fs)
print(f"\n{'='*60}")
print(f"완료 {len(uids)-len(left)} / {len(uids)}   (미완료 {len(left)})")
print(f"총 용량 {size/1e9:.1f} GB   위치 {OUT}")
if left:
    print("미완료가 있습니다. 같은 명령을 다시 실행하면 이어받습니다.")
print("=" * 60)
