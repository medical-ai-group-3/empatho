#!/bin/bash
REQUIRED_FREE_MB=15000
CHECK_INTERVAL=60
echo "GPU 여유 메모리 대기 시작... (필요: ${REQUIRED_FREE_MB}MB 이상)"
while true; do
    FREE_MB=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits)
    echo "$(date '+%H:%M:%S') - 현재 여유 메모리: ${FREE_MB}MB"
    if [ "$FREE_MB" -ge "$REQUIRED_FREE_MB" ]; then
        echo "충분한 GPU 메모리 확보됨. 학습을 시작합니다."
        break
    fi
    sleep $CHECK_INTERVAL
done
cd ~/models/cellvitpp
python3 ./cellvit/train_cell_classifier_head.py --config ~/workspace/breast/pathology/configs/tiger_samh_weighted.yaml
