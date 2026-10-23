# SPDX-License-Identifier: MIT
"""DxrkMemory MCP server — stdlib-only stdio JSON-RPC 2.0.

Stdlib-only MCP engine backed by SqliteBackend (FTS5 trigram) + KnowledgeGraph.
Exposes 35 tools under dxrk_memory_* namespace.

Transport: newline-delimited JSON (stdio). Handles initialize / tools/list / tools/call
and notifications. Designed for ``dxrk-mcp --malla <path>`` or env DXRK_MEMORY_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from .malla import _install_shutdown_signal_handlers
from .mcp_handlers import TOOL_HANDLERS
from .mcp_handlers import _get_kg as _get_kg
from .mcp_handlers import _project_meta_for_mcp as _project_meta_for_mcp

SERVER_NAME = "dxrk-memory"
SERVER_VERSION = "2.0.0"

# Old tool names stay callable (silent deprecation) so MCP clients with a
# cached tool list keep working after the malla/partition/subgroup/recall rename.
_LEGACY_TOOL_NAMES: dict[str, str] = {
    "dxrk_memory_add_fragmento": "dxrk_memory_add_recall",
    "dxrk_memory_get_fragmento": "dxrk_memory_get_recall",
    "dxrk_memory_list_fragmentos": "dxrk_memory_list_recalls",
    "dxrk_memory_update_fragmento": "dxrk_memory_update_recall",
    "dxrk_memory_delete_fragmento": "dxrk_memory_delete_recall",
    "dxrk_memory_list_nodos": "dxrk_memory_list_partitions",
    "dxrk_memory_list_celdas": "dxrk_memory_list_subgroups",
    "dxrk_memory_add_drawer": "dxrk_memory_add_recall",
    "dxrk_memory_get_drawer": "dxrk_memory_get_recall",
    "dxrk_memory_list_drawers": "dxrk_memory_list_recalls",
    "dxrk_memory_update_drawer": "dxrk_memory_update_recall",
    "dxrk_memory_delete_drawer": "dxrk_memory_delete_recall",
    "dxrk_memory_list_rooms": "dxrk_memory_list_subgroups",
    "dxrk_memory_add_relic": "dxrk_memory_add_recall",
    "dxrk_memory_get_relic": "dxrk_memory_get_recall",
    "dxrk_memory_list_relics": "dxrk_memory_list_recalls",
    "dxrk_memory_update_relic": "dxrk_memory_update_recall",
    "dxrk_memory_delete_relic": "dxrk_memory_delete_recall",
    "dxrk_memory_list_chambers": "dxrk_memory_list_subgroups",
    "dxrk_memory_add_globulo": "dxrk_memory_add_recall",
    "dxrk_memory_get_globulo": "dxrk_memory_get_recall",
    "dxrk_memory_list_globulos": "dxrk_memory_list_recalls",
    "dxrk_memory_update_globulo": "dxrk_memory_update_recall",
    "dxrk_memory_delete_globulo": "dxrk_memory_delete_recall",
    "dxrk_memory_list_venas": "dxrk_memory_list_subgroups",
    "dxrk_memory_list_capilares": "dxrk_memory_list_subgroups",
}

# Old argument spellings are accepted as aliases; the canonical key wins if
# both are supplied. Three legacy generations stay callable in silence.
_LEGACY_ARG_ALIASES: dict[str, str] = {
    "nodo": "partition",
    "celda": "subgroup",
    "fragmento": "recall",
    "fragmento_id": "recall_id",
    "fragmento_ids": "recall_ids",
    "wing": "partition",
    "vena": "partition",
    "room": "subgroup",
    "chamber": "subgroup",
    "capilar": "subgroup",
    "drawer": "recall",
    "relic": "recall",
    "globulo": "recall",
    "drawer_id": "recall_id",
    "relic_id": "recall_id",
    "globulo_id": "recall_id",
    "drawer_ids": "recall_ids",
    "relic_ids": "recall_ids",
    "globulo_ids": "recall_ids",
    "palace": "malla",
    "crypt": "malla",
    "sangre": "malla",
    "palace_path": "malla_path",
    "crypt_path": "malla_path",
    "sangre_path": "malla_path",
}


def _normalize_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    """Return ``args`` with legacy hierarchy keys renamed to canonical ones."""
    normalized = dict(args)
    for legacy, canonical in _LEGACY_ARG_ALIASES.items():
        if legacy not in normalized:
            continue
        value = normalized.pop(legacy)
        normalized.setdefault(canonical, value)
    return normalized


DEFAULT_MALLA_PATH = os.environ.get("DXRK_MEMORY_PATH") or str(Path.home() / ".dxrk" / "memory")


def _resolve_malla(malla: str | None) -> str:
    if malla and malla.strip():
        return str(Path(malla).expanduser().resolve())
    # env en call-time (no el DEFAULT import-time): los tests que fijan
    # DXRK_MEMORY_PATH con monkeypatch deben redirigir de verdad.
    env = (os.environ.get("DXRK_MEMORY_PATH") or "").strip()
    if env:
        return str(Path(env).expanduser().resolve())
    if DEFAULT_MALLA_PATH.strip():
        return str(Path(DEFAULT_MALLA_PATH).expanduser().resolve())
    return str(Path.home() / ".dxrk" / "memory")


# Write tools mutate malla state -> require ``mine`` op (fs.write).
# Read tools bypass (all roles hold fs.read). Tenant from ``tenant``
# arg or DXRK_TENANT env; user from DXRK_USER env.
_MCP_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "dxrk_memory_add_recall",
        "dxrk_memory_update_recall",
        "dxrk_memory_delete_recall",
        "dxrk_memory_mine",
        "dxrk_memory_kg_add",
        "dxrk_memory_kg_invalidate",
        "dxrk_memory_consolidate",
        "dxrk_memory_forget",
        "dxrk_memory_pin",
        "dxrk_memory_quarantine",
    }
)


# Per-tool RBAC op: quarantine/policy tools need ``memory.maintain``
# (denied by default, explicit grant only); every other write tool
# keeps the legacy ``mine`` op.
_MCP_TOOL_OPS: dict[str, str] = {
    "dxrk_memory_quarantine": "memory.maintain",
}


def _check_mcp_op(name: str, args: dict[str, Any]) -> None:
    """R12 gate: deny prohibited write combos with RBAC_DENIED.

    Raises ``PermissionError("RBAC_DENIED: ...")`` when ``DXRK_USER``
    lacks the ``mine`` op in the resolved tenant. Empty tenant/user
    bypasses (local trusted mode). Called inside ``_handle_tool``'s
    try block so denial surfaces as ``{"error": ...}`` with
    ``isError=true`` at the JSON-RPC layer.
    """
    if name not in _MCP_WRITE_TOOLS:
        return
    from dxrk.security.enforcement import require_op, resolve_user

    tenant = str(args.get("tenant") or os.environ.get("DXRK_TENANT", "") or "").strip()
    require_op(tenant, resolve_user(), _MCP_TOOL_OPS.get(name, "mine"))


# MCP reads project recall metadata: the score ledger ships truncated to
# the last entries (with score_ledger_dropped adjusted so the visible
# slice stays hash-chain verifiable) and the raw access_history list is
# replaced by its length — timestamps are bookkeeping, not read payload.
# Projection lives in ``mcp_handlers``; re-exported above for callers that
# import it from this module.


# ---------------------------------------------------------------------------
# Tool definitions — inputSchema mirrors MCP spec (JSON Schema draft 7 subset)
# ---------------------------------------------------------------------------
TOOLS: dict[str, dict[str, Any]] = {
    "dxrk_memory_status": {
        "description": "Health + counts for the DxrkMemory malla",
        "inputSchema": {
            "type": "object",
            "properties": {
                "malla": {"type": "string", "description": "Malla path override"},
            },
        },
    },
    "dxrk_memory_search": {
        "description": "Hybrid BM25 search over recalls with optional date window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "n_results": {"type": "integer", "default": 5},
                "since": {"type": "string", "description": "ISO date YYYY-MM-DD inclusive"},
                "before": {"type": "string", "description": "ISO date YYYY-MM-DD exclusive"},
                "malla": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "dxrk_memory_add_recall": {
        "description": "Add a single recall (verbatim chunk) to a partition/subgroup",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "content": {"type": "string"},
                "source_file": {"type": "string"},
                "chunk_index": {"type": "integer", "default": 0},
                "malla": {"type": "string"},
                "supersedes": {
                    "type": "string",
                    "description": "Recall id this version replaces (old row kept with valid_to)",
                },
                "importance": {"type": "number", "description": "Explicit importance for decay-aware ranking"},
            },
            "required": ["partition", "subgroup", "content", "source_file"],
        },
    },
    "dxrk_memory_get_recall": {
        "description": "Fetch a recall by id",
        "inputSchema": {
            "type": "object",
            "properties": {"recall_id": {"type": "string"}, "malla": {"type": "string"}},
            "required": ["recall_id"],
        },
    },
    "dxrk_memory_list_recalls": {
        "description": "List recalls (paginated) optionally filtered by partition/subgroup",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_update_recall": {
        "description": "Update recall content/metadata (upsert)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recall_id": {"type": "string"},
                "content": {"type": "string"},
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["recall_id"],
        },
    },
    "dxrk_memory_delete_recall": {
        "description": "Delete recall(s) by id or where filter",
        "inputSchema": {
            "type": "object",
            "properties": {"recall_id": {"type": "string"}, "malla": {"type": "string"}},
            "required": ["recall_id"],
        },
    },
    "dxrk_memory_check_duplicate": {
        "description": "Check if content already exists (BM25 duplicate threshold 0.15)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "threshold": {"type": "number", "default": 0.15},
                "malla": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    "dxrk_memory_list_partitions": {
        "description": "List partitions present in malla",
        "inputSchema": {"type": "object", "properties": {"malla": {"type": "string"}}},
    },
    "dxrk_memory_list_subgroups": {
        "description": "List subgroups, optionally for a partition",
        "inputSchema": {"type": "object", "properties": {"partition": {"type": "string"}, "malla": {"type": "string"}}},
    },
    "dxrk_memory_taxonomy": {
        "description": "Partitions → subgroups → count taxonomy",
        "inputSchema": {"type": "object", "properties": {"malla": {"type": "string"}}},
    },
    "dxrk_memory_mine": {
        "description": "Mine a project directory into the malla (chunk + upsert)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
                "partition": {"type": "string", "default": "default"},
                "subgroup": {"type": "string", "default": "general"},
                "dry_run": {"type": "boolean", "default": False},
                "malla": {"type": "string"},
            },
            "required": ["project_dir"],
        },
    },
    "dxrk_memory_kg_query": {
        "description": "Query temporal KG for entity (outgoing/incoming/both) with optional as_of",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string"},
                "as_of": {"type": "string"},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"], "default": "both"},
                "kg_path": {"type": "string"},
            },
            "required": ["entity"],
        },
    },
    "dxrk_memory_kg_add": {
        "description": "Add triple to temporal KG",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "valid_from": {"type": "string"},
                "valid_to": {"type": "string"},
                "kg_path": {"type": "string"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    "dxrk_memory_kg_invalidate": {
        "description": "Invalidate (soft-delete) a KG triple by setting valid_to",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "ended": {"type": "string"},
                "kg_path": {"type": "string"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    "dxrk_memory_kg_timeline": {
        "description": "Chronological timeline of KG facts",
        "inputSchema": {"type": "object", "properties": {"entity": {"type": "string"}, "kg_path": {"type": "string"}}},
    },
    "dxrk_memory_kg_stats": {
        "description": "KG stats (entities/triples/current/expired)",
        "inputSchema": {"type": "object", "properties": {"kg_path": {"type": "string"}}},
    },
    "dxrk_memory_graph_stats": {
        "description": "Malla graph overview (partitions/subgroups/tunnels)",
        "inputSchema": {"type": "object", "properties": {"malla": {"type": "string"}}},
    },
    "dxrk_memory_traverse": {
        "description": "Traverse KG from start entity up to depth hops",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "string"},
                "depth": {"type": "integer", "default": 2},
                "as_of": {"type": "string"},
                "kg_path": {"type": "string"},
            },
            "required": ["start"],
        },
    },
    "dxrk_memory_consolidate": {
        "description": "Merge recalls into one distilled recall that supersedes them (extractive, no LLM)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recall_ids": {"type": "array", "items": {"type": "string"}},
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["recall_ids"],
        },
    },
    "dxrk_memory_forget": {
        "description": "Scoped erase honoring the supersede model (soft-mark by default; KG never deleted)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recall_ids": {"type": "array", "items": {"type": "string"}},
                "partition": {"type": "string"},
                "subgroup": {"type": "string"},
                "before": {"type": "string", "description": "ISO date: forget recalls filed strictly before"},
                "hard": {"type": "boolean", "default": False},
                "include_kg": {"type": "boolean", "default": False},
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_pin": {
        "description": "Pin a recall (or the L0 identity block) against decay-eviction; pinned recalls lead wake_up",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recall_id": {"type": "string"},
                "scope": {"type": "string", "enum": ["recall", "identity"], "default": "recall"},
                "pinned": {"type": "boolean", "default": True},
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_timeline": {
        "description": "Chronological session + file-episode + pin timeline with [since, before) window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO date inclusive"},
                "before": {"type": "string", "description": "ISO date exclusive"},
                "partition": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_quarantine": {
        "description": "Quarantine (or release) a recall fail-closed; gated by the memory.maintain cap",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recall_id": {"type": "string"},
                "reason": {"type": "string", "default": ""},
                "unquarantine": {"type": "boolean", "default": False},
                "malla": {"type": "string"},
            },
            "required": ["recall_id"],
        },
    },
    # Fase 2: Eval Harness
    "dxrk_memory_eval_run": {
        "description": "Run evaluation harness on a partition (recall@k, MRR, NDCG, ECE)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "n_queries": {"type": "integer", "default": 10},
                "malla": {"type": "string"},
            },
            "required": ["partition"],
        },
    },
    "dxrk_memory_eval_synthetic": {
        "description": "Generate synthetic evaluation queries from malla content",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "n": {"type": "integer", "default": 20},
                "malla": {"type": "string"},
            },
            "required": ["partition"],
        },
    },
    # Fase 2: Metacognición Avanzada
    "dxrk_memory_metacog_predict": {
        "description": "Get metacognitive prediction (confidence, difficulty, ECE)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "partition": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["query", "partition"],
        },
    },
    "dxrk_memory_calibrate_fit": {
        "description": "Fit temperature scaling or isotonic regression calibration",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "method": {"type": "string", "enum": ["temperature", "isotonic"], "default": "temperature"},
                "malla": {"type": "string"},
            },
            "required": ["partition"],
        },
    },
    # Fase 2: Multi-Tenant Calibrate
    "dxrk_memory_calibrate_tenant": {
        "description": "Get or set calibration for a tenant+partition combination",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant": {"type": "string"},
                "partition": {"type": "string"},
                "a": {"type": "number"},
                "b": {"type": "number"},
                "c": {"type": "number"},
                "pe_lambda": {"type": "number"},
                "score": {"type": "number"},
                "malla": {"type": "string"},
            },
            "required": ["tenant", "partition"],
        },
    },
    "dxrk_memory_calibrate_chain": {
        "description": "Get calibration chain with fallback (tenant+partition → global → default)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tenant": {"type": "string"},
                "partition": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["tenant", "partition"],
        },
    },
    # Fase 2: Production Hardening
    "dxrk_memory_circuit_breaker_status": {
        "description": "Get circuit breaker state for external dependencies",
        "inputSchema": {
            "type": "object",
            "properties": {
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_slo_check": {
        "description": "Check SLO compliance (latency, recall, MRR, ECE)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["partition"],
        },
    },
    "dxrk_memory_rollback_check": {
        "description": "Check if auto-rollback should trigger (regression detection)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "partition": {"type": "string"},
                "malla": {"type": "string"},
            },
            "required": ["partition"],
        },
    },
    # Fase 2: Judge Externo Continuo
    "dxrk_memory_judge_status": {
        "description": "Get continuous judge status (last run, passes, failures, rollbacks)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "malla": {"type": "string"},
            },
        },
    },
    "dxrk_memory_judge_run": {
        "description": "Run continuous judge verification cycle manually",
        "inputSchema": {
            "type": "object",
            "properties": {
                "malla": {"type": "string"},
            },
        },
    },
}


def _handle_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Validate, dispatch to the tool registry, and map failures to payloads."""
    args = _normalize_tool_args(args)
    malla_path = _resolve_malla(args.get("malla"))
    try:
        _check_mcp_op(name, args)
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": f"unknown tool {name}"}
        return handler(args, malla_path)
    except Exception as e:
        tb = traceback.format_exc()
        return {"error": str(e), "traceback": tb, "malla_path": malla_path}


def _dispatch(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    # notifications have no id → no response
    def is_notification() -> bool:
        return req_id is None

    # initialize
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
        if is_notification():
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        if is_notification():
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        tools: list[dict[str, Any]] = [
            {"name": k, "description": v["description"], "inputSchema": v["inputSchema"]} for k, v in TOOLS.items()
        ]
        if is_notification():
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        raw_name = params.get("name")
        name = _LEGACY_TOOL_NAMES.get(raw_name, raw_name) if isinstance(raw_name, str) else raw_name
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        if not isinstance(name, str) or name not in TOOLS:
            err = {"code": -32602, "message": f"unknown tool {name}"}
            if is_notification():
                return None
            return {"jsonrpc": "2.0", "id": req_id, "error": err}
        result_obj = _handle_tool(name, args)
        # MCP tools/call result wraps content array
        content = [{"type": "text", "text": json.dumps(result_obj, ensure_ascii=False, indent=2)}]
        if is_notification():
            return None
        # if tool returned error, map to isError (any "error" key, including
        # domain errors like update_recall not-found without traceback)
        is_error = isinstance(result_obj, dict) and "error" in result_obj
        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": content, "isError": bool(is_error)}}

    # fallback unknown
    if is_notification():
        return None
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main(argv: list[str] | None = None) -> int:
    _install_shutdown_signal_handlers()
    parser = argparse.ArgumentParser(prog="dxrk-memory-mcp", description="DxrkMemory MCP stdio server (stdlib-only)")
    parser.add_argument(
        "--malla",
        dest="malla",
        default=None,
        help="Malla path override (default ~/.dxrk/memory or DXRK_MEMORY_PATH)",
    )
    args = parser.parse_args(argv)

    if args.malla:
        os.environ["DXRK_MEMORY_PATH"] = str(Path(args.malla).expanduser().resolve())

    # stdio loop — line-delimited JSON
    # Protect stdout binary mode
    stdin = sys.stdin
    stdout = sys.stdout
    # Ensure unbuffered line handling
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            # per JSON-RPC, parse error
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
            continue
        # handle batch (array) or single
        if isinstance(req, list):
            responses = []
            for r in req:
                out = _dispatch(r)
                if out is not None:
                    responses.append(out)
            if responses:
                stdout.write(json.dumps(responses, ensure_ascii=False) + "\n")
                stdout.flush()
        else:
            out = _dispatch(req)
            if out is not None:
                stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
                stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
