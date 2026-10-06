#!/usr/bin/env bash
# 여러 장을 돌려 시연 이미지를 만든다. 정답 상자를 같이 그린다.
#
# 왜
#   한 장만 보고 '검출이 이상한데?' 를 판단할 수 없다. 정답이 안 그려져
#   있으면 더더욱 그렇다. 여러 장을 정답과 나란히 봐야 경향이 보인다.
#
# 사용
#   bash demo_batch.sh          # 석회 3장 + 종괴 3장
#   bash demo_batch.sh 5 mass   # 종괴만 5장

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/../.." && pwd)/docs/demo"
N=${1:-3}
KINDS=${2:-"calc mass"}

cd "$HERE" || exit 1
mkdir -p "$OUT"

for kind in $KINDS; do
    echo "══ $kind $N장"
    # 인덱스에서 원본 DICOM 경로를 뽑는다
    mapfile -t IMGS < <(python3 - "$kind" "$N" <<'EOF'
import sys
import pandas as pd
from paths import ROI_INDEX, RAW_CBIS
kind, n = sys.argv[1], int(sys.argv[2])
d = pd.read_csv(ROI_INDEX / f"roi_index_{kind}_test.csv")
seen = set()
for r in d.to_dict("records"):
    uid = str(r["image_path"]).strip().split("/")[-2]
    if uid in seen:
        continue
    fs = sorted((RAW_CBIS / uid).glob("*.dcm"))
    if not fs:
        continue
    seen.add(uid)
    print(fs[0])
    if len(seen) >= n:
        break
EOF
)
    i=0
    for img in "${IMGS[@]}"; do
        i=$((i + 1))
        echo "── [$i/${#IMGS[@]}] $(basename "$(dirname "$img")" | cut -c1-40)"
        python3 predict.py --image "$img" --topk 1 --score-calc 0.594 --score-mass 0.767 \
            --overlay "$OUT/${kind}_${i}.png" \
            --json "$OUT/${kind}_${i}.json" 2>&1 \
            | grep -E "정답 |^  \[|BI-RADS|판단 |영상 단위|미세석회 |종괴 " \
            | sed 's/^/    /'
    done
done

echo
echo "══ 끝났다.  $OUT"
ls -la "$OUT"/*.png 2>/dev/null | awk '{print "  "$9"  "$5" bytes"}'
echo
echo "  초록 = 정답 상자 (데이터셋)    빨강 = 조직검사 권고    노랑 = 추적 관찰"
echo "  검출 박스가 초록과 겹치는지, 엉뚱한 데 있는지를 본다."
