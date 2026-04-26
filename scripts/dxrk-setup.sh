#!/usr/bin/env bash
set -euo pipefail

# Local installer script for Dxrk v1.0 Phase 2 (OpenCode Desktop compatible)

ROOT_DIR=$(pwd)
DXRK_MEM="$ROOT_DIR/DxrkMemory"
DXRK_CTL="$ROOT_DIR/DxrkControl"
DXRK_MASTER="$ROOT_DIR/dxrk_master.py"
DXRK_INIT="$ROOT_DIR/dxrk_install.py"

echo "=== Dxrk Local Setup ==="
echo "Working dir: $ROOT_DIR"

# Step 1: Setup Python environment
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 is not installed"; exit 1
fi
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -U pytest pyyaml
echo "Python env ready."

# Step 2: Configure PYTHONPATH for DxrkMemory wrappers
if [ -z "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="$DXRK_MEM:$DXRK_MEM/dxrk_base:$DXRK_MEM/dxrk_sync"
else
  export PYTHONPATH="$DXRK_MEM:$DXRK_MEM/dxrk_base:$DXRK_MEM/dxrk_sync:$PYTHONPATH"
fi
echo "PYTHONPATH: $PYTHONPATH"

# Step 3: Install Node dependencies for DxrkControl (best effort in non-root envs)
echo "Setting up Node dependencies (DxrkControl)"
if command -v pnpm &>/dev/null; then
  (cd "$DXRK_CTL" && pnpm install) || true
elif command -v corepack &>/dev/null; then
  corepack enable pnpm 2>/dev/null || true
  (cd "$DXRK_CTL" && pnpm install) || true
fi

# Step 4: Run tests
echo "Running Python tests..."
pytest -q tests || true

# Step 5: Optional quick smoke test
echo "Running smoke test with master start/status..."
python3 dxrk_master.py start
python3 dxrk_master.py status

echo "=== Setup complete (local) ==="
