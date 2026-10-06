#!/usr/bin/env bash
# 아침 점검 — 밤새 무엇이 돌았고 무엇이 나왔는지 한 번에 본다.
#
# 왜
#   확인할 게 로그 6개 · 산출물 5개 · GPU 상태다. 하나씩 치다 보면 빠뜨린다.
#   읽기만 한다. 아무것도 고치거나 지우지 않는다.
#
# 사용
#   bash morning.sh
#   bash morning.sh --full        # 로그를 더 길게 본다

set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
LOGS="$ROOT/training/logs"
OUT="$ROOT/archive/outputs"
CKPT="$ROOT/training/ckpt"
DOCS="$ROOT/docs"
N=${1:-}
TAIL=$([ "$N" = "--full" ] && echo 40 || echo 12)

line() { printf '%s\n' "──────────────────────────────────────────────────────────────────"; }
head2() { echo; line; echo "$1"; line; }

echo "=================================================================="
echo " 아침 점검   $(date '+%F %T')"
echo "=================================================================="

# ── 1. 지금 무엇이 돌고 있나 ──────────────────────────────────────────
head2 "1. 지금 상태"
if pgrep -f gpu_queue.sh > /dev/null; then
    echo "  큐        돌고 있다"
else
    echo "  큐        멈춰 있다 (전부 끝났거나 중단됐다 — 아래 4번을 봐라)"
fi
cur=$(pgrep -af "train_mammo_det|eval_mammo_det|eval_e2e|eval_end2end" \
      | sed 's/.*python3* -*u* *//' | head -3)
if [ -n "$cur" ]; then
    echo "  작업      돌고 있다:"
    echo "$cur" | sed 's/^/              /'
else
    echo "  작업      돌고 있는 것 없음"
fi
printf "  GPU       "
nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu \
    --format=csv,noheader 2>/dev/null || echo "(nvidia-smi 실패)"
printf "  디스크    "
df -h "$ROOT" | awk 'NR==2 {print $4" 남음 ("$5" 사용)"}'

# ── 2. 큐가 어디까지 갔나 ────────────────────────────────────────────
head2 "2. 큐 진행"
if [ -f "$LOGS/queue.log" ]; then
    grep -E "══ \[|완료 \(|! 실패|GPU 여유|전부 끝났다|중단" "$LOGS/queue.log" \
        | tail -30 | sed 's/^/  /'
else
    echo "  ! queue.log 가 없다 — 큐가 뜬 적이 없다"
fi

# ── 3. 작업별 결과 ───────────────────────────────────────────────────
head2 "3. 작업별"
show() {   # show <로그글롭> <이름> <성공을_알리는_문구>
    local f
    f=$(ls -t $1 2>/dev/null | head -1)
    if [ -z "$f" ]; then
        printf "  %-26s 시작 안 함\n" "$2"
        return
    fi
    if grep -qE "Traceback|Error|error:|CUDA out of memory" "$f"; then
        printf "  %-26s ! 오류 있음   %s\n" "$2" "$(basename "$f")"
        grep -E "Traceback|Error|error:" "$f" | tail -2 | sed 's/^/        /'
    elif [ -n "$3" ] && grep -q "$3" "$f"; then
        printf "  %-26s 끝남         %s\n" "$2" "$(basename "$f")"
    else
        printf "  %-26s 도는 중/미완  %s\n" "$2" "$(basename "$f")"
    fi
}
show "$LOGS/queue_1_*.log"  "1 서술어 재측정 calc"  "조직검사 판단"
show "$LOGS/queue_2_*.log"  "2 서술어 재측정 mass"  "조직검사 판단"
show "$LOGS/queue_3_*.log"  "3 끝에서 끝까지"       "읽는 법"
show "$LOGS/queue_5_*.log"  "5 에폭 12 학습"        "^완료$"
show "$LOGS/queue_6_*.log"  "6 에폭 12 평가"        "기준선"

# ── 4. 학습이 끝났나 ─────────────────────────────────────────────────
head2 "4. 에폭 12 학습"
tl=$(ls -t "$LOGS"/queue_5_*.log "$LOGS"/train_*.log 2>/dev/null | head -1)
if [ -z "$tl" ]; then
    echo "  로그 없음 — 아직 시작 안 했다 (GPU 를 기다리는 중일 수 있다)"
else
    echo "  로그  $(basename "$tl")   (마지막 기록 $(date -r "$tl" '+%F %H:%M'))"
    echo
    echo "  에폭별 손실 (학습 / 검증)"
    # 진행 줄('에폭 3 [ 120/3928]')이 아니라 에폭 요약 줄만 본다
    grep -E "■ 에폭|최고 검증 갱신|손실이 발산" "$tl" 2>/dev/null \
        | tail -16 | sed 's/^/    /'
    if grep -q "^완료$" "$tl" 2>/dev/null; then
        echo
        echo "  ▶ 학습 끝났다."
        echo
        echo "  에폭 6 (어제) 참고    ep0 60.6/5.04 · ep5 31.1/7.15"
        echo "  검증 손실이 올라도 검출은 좋아졌었다. 손실로 판단하지 마라 —"
        echo "  에폭 12 의 판단 기준은 아래 6번의 FROC 이다."
    else
        echo
        echo "  ▶ 아직 도는 중이다. 마지막 줄:"
        tail -3 "$tl" | sed 's/^/      /'
    fi
fi

# ── 5. 산출물 ────────────────────────────────────────────────────────
head2 "5. 나온 파일"
for f in "$OUT/tile_dets_ep12.json" "$OUT/tile_raw_ep12.json" \
         "$DOCS/e2e.json" "$DOCS/e2e_calc.json" "$DOCS/e2e_mass.json" \
         "$CKPT/last_lora.pt" "$CKPT/ep6/last_lora.pt"; do
    if [ -f "$f" ]; then
        printf "  ✓ %-34s %6s   %s\n" "$(basename "$f")" \
            "$(du -h "$f" | cut -f1)" "$(date -r "$f" '+%m-%d %H:%M')"
    else
        printf "  ✗ %-34s 없음\n" "$(basename "$f")"
    fi
done
echo
echo "  ep6/last_lora.pt 는 어제 결과(석회 50.2%)의 백업이다. 반드시 있어야 한다."

# ── 6. 핵심 수치 ─────────────────────────────────────────────────────
head2 "6. 핵심 수치"

e2e=$(ls -t "$LOGS"/queue_3_*.log 2>/dev/null | head -1)
if [ -n "$e2e" ] && grep -q "손실을 나누면" "$e2e"; then
    echo "  ── 끝에서 끝까지 (두 종류 합산) ──"
    grep -E "조직검사 대상 병변|조직검사 대상 중 검출됨|그중 조직검사라고 말함|곱하면|조직검사 민감도" \
        "$e2e" | sed 's/^/  /'
else
    echo "  끝단 결과 아직 없음 — 어제 종류별로 잰 값:"
    echo "    ① 위치를 알려줬을 때   석회 98.1% · 종괴 82.7% · 합계 90.0%"
    echo "    ② 스스로 찾았을 때     석회 65.3% · 종괴 41.2% · 합계 52.5%"
fi

ev=$(ls -t "$LOGS"/queue_6_*.log 2>/dev/null | head -1)
echo
if [ -n "$ev" ] && grep -q "중심 명중" "$ev"; then
    echo "  ── 에폭 12 FROC (중심 명중) ──"
    awk '/^=+$/{h=0} /정답 [0-9]+건/{name=$1} /── 중심 명중 ──/{p=1;print "  "name;next}
         p&&/^ *(0\.25|0\.5|1\.00|2\.00|4\.00)/{print "  "$0}
         p&&/^ *\(검출/{print "  "$0;p=0}' "$ev"
    echo
    echo "  에폭 6 (어제)   석회 1FP 50.2% · 4FP 84.2%   종괴 1FP 48.3% · 4FP 75.0%"
    echo "  기준선          석회 1FP 18.6% · 4FP 37.3%   종괴 1FP 57.3% · 4FP 61.3%"
else
    echo "  에폭 12 평가 결과 아직 없음"
    echo "  에폭 6 (어제)   석회 1FP 50.2% · 4FP 84.2%   종괴 1FP 48.3% · 4FP 75.0%"
fi

# ── 7. 다음에 할 것 ──────────────────────────────────────────────────
head2 "7. 다음"
if [ -f "$OUT/tile_raw_ep12.json" ]; then
    echo "  ▶ 합치기 전 박스가 나왔다. 겹침 합치기 실험을 할 수 있다 (CPU)."
    echo "    종괴 AP75 0.088->0.022 · 낮은 오탐 구간 · 끝단 박스 손실 4.4%p 를"
    echo "    한 번에 건드리는 자리다. 파일을 보고 코드를 짜면 된다."
elif [ -f "$OUT/tile_dets_ep12.json" ]; then
    echo "  ! 에폭 12 평가는 끝났는데 tile_raw_ep12.json 이 없다."
    echo "    --save-raw 가 안 붙었거나 저장에 실패했다. queue_6 로그를 봐라."
else
    echo "  ▶ 에폭 12 평가가 아직이다. 큐가 도는 중이면 그냥 기다린다."
fi
if [ -n "$(ls -t "$LOGS"/queue_6_*.log 2>/dev/null)" ]; then
    echo "  ▶ 에폭 12 mAP:  python3 tile_map.py --dets $OUT/tile_dets_ep12.json"
fi
echo "  ▶ 문서 갱신은 수치가 다 나온 뒤에 한 번에 한다."
echo
echo "  자세히 보려면:"
echo "    tail -60 $LOGS/queue.log"
echo "    less $LOGS/queue_5_train_mammo_det.py.log"
echo
