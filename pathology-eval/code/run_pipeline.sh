#!/bin/bash
set -e

echo "===== 1단계: 라벨 수정 시작 ====="
python3 ~/workspace/breast/pathology/code/fix_v2_labels.py

echo "===== 2단계: 라벨 확인 ====="
COUNT=$(grep -c ",1," ~/data/tiger/cellvit_detection_v2/train/labels/*.csv | awk -F: '$2>0' | wc -l)
echo "TIL이 포함된 파일 수: $COUNT"

if [ "$COUNT" -eq 0 ]; then
    echo "경고: TIL 라벨이 여전히 0개입니다. 학습을 실행하지 않고 중단합니다."
    exit 1
fi

echo "===== 3단계: 학습 시작 ====="
cd ~/models/cellvitpp
python3 ./cellvit/train_cell_classifier_head.py --config ~/workspace/breast/pathology/configs/tiger_samh_fold_0_v2.yaml

echo "===== 전체 파이프라인 완료 ====="
