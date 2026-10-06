#!/bin/bash
# 야간 순차 실행 — GPU 한 장이라 동시 불가.
#
#   1차  SAM3-UNet 분할 단독   ckpt/experiments/  logs/unet_<ts>.log
#   2차  증강 + batch 4 조인트  ckpt/             logs/aug_<ts>.log
#
# '&&' 가 아니라 ';' 로 잇는다 — 1차가 실패해도 2차는 돌아야 한다.
# set -e 도 쓰지 않는다. 아침에 최소 하나는 결과가 있어야 한다.
#
# 로그 파일은 각 스크립트의 start_run_log 가 직접 만든다.
# 헤더에 started, 푸터에 ended + 소요시간이 들어가고 tqdm 진행바는
# 마지막 상태만 남는다. 러너가 리다이렉트하면 파일이 두 벌 생기므로 하지 않는다.

US=/home/wsuser/workspace/breast/us
CODE=$US/code
mkdir -p "$US/logs" "$US/ckpt/experiments"

echo "########## 야간 실행 시작 $(date +'%Y-%m-%d %H:%M:%S') ##########"

echo
echo "########## 1차 · SAM3-UNet 분할 단독 (30 epoch) ##########"
T1=$(date +%s)
python3 -u "$CODE/experiments/train_sam3unet.py" \
    --epochs 30 --run-name unet --ckpt-dir "$US/ckpt/experiments"
R1=$?
echo "########## 1차 종료 exit=$R1  $(( ($(date +%s)-T1)/60 ))분 ##########"

echo
echo "########## 2차 · 증강 + batch 4 조인트 (30 epoch) ##########"
T2=$(date +%s)
python3 -u "$CODE/train_us_lora.py" \
    --run-name aug --best-metric grade_w1 --dice-gate 0.85
R2=$?
echo "########## 2차 종료 exit=$R2  $(( ($(date +%s)-T2)/60 ))분 ##########"

echo
echo "===================== 야간 실행 요약 ====================="
echo "  1차 SAM3-UNet  exit=$R1"
echo "  2차 증강+b4    exit=$R2"
echo "  종료 $(date +'%Y-%m-%d %H:%M:%S')"
ls -la "$US/logs" | grep -E "unet_|aug_"
echo "=========================================================="