#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# DxrkMemory + session recall — 60-second runnable demo.
#
# Non-interactive. Uses ONLY temp dirs (never touches the real ~/.dxrk):
#   HOME is redirected to a mktemp dir, so hooks_cli PALACE_ROOT
#   (~/.dxrk/memory), the session store (~/.dxrk/sessions) and the
#   identity file all land under $DEMO_TMP. DXRK_MEMORY_PATH points the
#   MCP server at the same temp palace.
#
# Run from anywhere:  bash demo/demo-60s.sh
# Every command below was verified to exit 0 (set -e enforces it).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

if [[ -x "$REPO/.venv/bin/python" ]]; then PY="$REPO/.venv/bin/python"; else PY="python3"; fi

DEMO_TMP="$(mktemp -d "${TMPDIR:-/tmp}/dxrk-demo-XXXXXX")"
trap 'rm -rf "$DEMO_TMP"' EXIT
export HOME="$DEMO_TMP/home"
export DXRK_MEMORY_PATH="$DEMO_TMP/home/.dxrk/memory"
export DXRK_SESSION_BACKEND=sqlite
unset DXRK_TENANT || true
mkdir -p "$HOME" "$DEMO_TMP/sample"

say() { printf '\n### %s\n' "$*"; }

# mcp <id> <tool> <json-args> — one MCP tools/call over stdio, prints the
# result text, exits non-zero when the tool reports isError.
mcp() {
  local id="$1" tool="$2" args="$3"
  printf '{"jsonrpc":"2.0","id":%s,"method":"tools/call","params":{"name":"%s","arguments":%s}}\n' \
    "$id" "$tool" "$args" |
    "$PY" -m dxrk.memory.mcp_server |
    "$PY" -c "
import json, sys
r = json.load(sys.stdin)
print(r['result']['content'][0]['text'])
sys.exit(1 if r['result'].get('isError') else 0)
"
}

say "[1/6] mine — ingest a tiny sample project into a temp palace"
cat > "$DEMO_TMP/sample/auth.py" <<'EOF'
"""JWT authentication middleware for protected routes."""
SECRET_KEY = "change-me-in-production"
TOKEN_TTL_SECONDS = 3600


def verify_bearer_token(headers):
    """Verify the bearer token and return the authenticated user record."""
    token = headers.get("Authorization", "").removeprefix("Bearer ")
    return decode_and_validate(token, SECRET_KEY)
EOF
cat > "$DEMO_TMP/sample/billing.py" <<'EOF'
"""Refund policy and billing helpers."""
REFUND_WINDOW_DAYS = 30


def request_reimbursement(customer_id, order_id):
    """Customers may request reimbursement within thirty days of purchase."""
    return issue_credit(customer_id, fetch_order(order_id).total)
EOF
cat > "$DEMO_TMP/sample/deploy.md" <<'EOF'
# Deployment pipeline

The release pipeline pushes containers to production via blue-green releases.
EOF
"$PY" -m dxrk.memory mine "$DEMO_TMP/sample" --wing demo

say "[2/6] hybrid search — a natural question grep cannot answer"
Q="how do I authenticate API users"
if grep -riF "$Q" "$DEMO_TMP/sample/" >/dev/null 2>&1; then
  echo "unexpected: keyword grep matched"
else
  echo "grep: no hits (keyword mismatch)"
fi
"$PY" -m dxrk.memory search "$Q" --wing demo --n 1

say "[3/6] pin + status — pin the auth drawer, budgets prove it stuck"
DID="$("$PY" -c "
from dxrk.memory.palace import DxrkMemory
dm = DxrkMemory('$DXRK_MEMORY_PATH'); dm.init()
from dxrk.memory.search import build_where_filter
col = dm._collection(create=False)
got = col.get(where=build_where_filter('demo', None), include=['documents'], limit=10)
for i, doc in zip(got.ids, got.documents):
    if 'authentication' in doc:
        print(i)
        break
")"
echo "pinning: $DID"
# Seed one episodic session entry first (same write path hook_stop uses:
# source_file='session:<id>'), so the timeline below shows session + pin.
"$PY" -c "
from dxrk.memory.palace import DxrkMemory
dm = DxrkMemory('$DXRK_MEMORY_PATH'); dm.init()
dm.add_drawer(wing='demo', room='2026-09-27',
    content='SESSION:2026-09-27|session:demo-001|msgs:4|recent:fixed the JWT expiry bug',
    source_file='session:demo-001', chunk_index=0)
print('session episode recorded')
"
echo "demo identity: Dxrk demo bot" > "$HOME/.dxrk/identity.txt"
mcp 2 dxrk_memory_pin "{\"drawer_id\":\"$DID\"}"
mcp 3 dxrk_memory_status '{}'

say "[4/6] timeline — episodic session + pin history, chronological"
mcp 4 dxrk_memory_timeline '{"limit":10}'

say "[5/6] session-start recall — hook returns L0 identity + L1 story"
printf '{"session_id":"demo-60s","transcript_path":""}' |
  "$PY" -m dxrk.memory.hooks_cli session-start dxrk

say "[6/6] sessions CLI — create/list/info on the sqlite backend"
"$PY" -c "from dxrk.commands import register_all; raise SystemExit(register_all().execute(['session', 'create', 'Demo']))"
"$PY" -c "from dxrk.commands import register_all; raise SystemExit(register_all().execute(['session', 'list', '--limit', '3']))"
SID="$("$PY" -c "from dxrk.commands.session import list_session_files; print(list_session_files()[0].id)")"
"$PY" -c "from dxrk.commands import register_all; raise SystemExit(register_all().execute(['session', 'info', '$SID']))"

say "DEMO OK — palace, sessions and hooks all lived under $DEMO_TMP (now cleaned up)"
