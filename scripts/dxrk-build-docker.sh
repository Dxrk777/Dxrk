#!/usr/bin/env bash
set -euo pipefail

echo "=== DXRK SYSTEM v1.0 - Docker Build ==="
echo ""

WORKDIR="/home/dxrk/DxrkMonorepo_final"
cd "$WORKDIR"

echo "[1/5] Installing Docker..."
if ! command -v docker &> /dev/null; then
    sudo apt-get update
    sudo apt-get install -y docker.io
fi

echo "[2/5] Starting Docker daemon..."
sudo systemctl start docker || sudo service docker start

echo "[3/5] Building DxrkControl in Docker..."
chmod +x docker/run-dxrk-control-build.sh
./docker/run-dxrk-control-build.sh

echo "[4/5] Verifying DxrkMaster ONLINE..."
python3 dxrk_master.py start
sleep 2
python3 dxrk_master.py status

echo ""
echo "=== BUILD COMPLETE ==="
echo "Logs saved to: docker/build.log"
echo "Test logs in: tests/"