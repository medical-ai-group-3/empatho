#!/bin/bash
set -e

cd ~/mosec
source venv/bin/activate

# 이전 셸 세션에 FORCE_DUMMY=1이 남아있으면 진짜 ONNX 모델 대신 계속
# DummyUNet이 조용히 쓰인다 — 실제로 겪은 문제라 명시적으로 해제.
unset FORCE_DUMMY

export GOOGLE_CLOUD_PROJECT=model-platform-502402
export MOSEC_TIMEOUT=300000
export ENABLE_MEDGEMMA=1

export LD_LIBRARY_PATH=$(python3 -c "
import nvidia, os, glob
base = list(nvidia.__path__)[0]
dirs = glob.glob(os.path.join(base, '*', 'lib'))
print(':'.join(dirs))
"):$LD_LIBRARY_PATH

echo "=== 설정 확인 ==="
echo "FORCE_DUMMY=[$FORCE_DUMMY]  (비어있어야 정상)"
echo "ENABLE_MEDGEMMA=$ENABLE_MEDGEMMA"
echo "MOSEC_TIMEOUT=$MOSEC_TIMEOUT"
echo "=================="

python -m src.server 2>&1 | tee ~/server.log
