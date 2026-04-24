#!/usr/bin/env bash
set -euo pipefail
echo "Smoke test: starting Dxrk Master and checking status"
python3 /home/dxrk/DxrkMonorepo_final/dxrk_master.py start
python3 /home/dxrk/DxrkMonorepo_final/dxrk_master.py status
echo "Smoke test completed"
