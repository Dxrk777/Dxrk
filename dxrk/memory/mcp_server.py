# SPDX-License-Identifier: MIT
"""DxrkMemory MCP server — stdlib-only stdio JSON-RPC 2.0.

Stdlib-only MCP engine backed by SqliteBackend (FTS5 trigram) + KnowledgeGraph.
Exposes ~23 tools under dxrk_memory_* namespace.

Transport: newline-delimited JSON (stdio). Handles initialize / tools/list / tools/call
and notifications. Designed for ``dxrk-mcp --palace <path>`` or env DXRK_MEMORY_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .graph import KnowledgeGraph
from .palace import DxrkMemory, _install_shutdown_signal_handlers
from .search import sanitize_query

SERVER_NAME = "dxrk-memory"
SERVER_VERSION = "2.0.0"

DEFAULT_PALACE_PATH = os.environ.get("DXRK_MEMORY_PATH") or str(Path.home() / ".dxrk" / "memory")


def _resolve_palace(palace: str | None) -> str:
    if palace and palace.strip():
        return str(Path(palace).expanduser().resolve())
    # env en call-time (no el DEFAULT import-time): los tests que fijan
    # DXRK_MEMORY_PATH con monkeypatch deben redirigir de verdad.
    env = (os.environ.get("DXRK_MEMORY_PATH") or "").strip()
    if env:
        return str(Path(env).expanduser().resolve())
    if DEFAULT_PALACE_PATH.strip():
        return str(Path(DEFAULT_PALACE_PATH).expanduser().resolve())
    return str(Path.home() / ".dxrk" / "memory")


# Write tools mutate palace state -> require ``mine`` op (fs.write).
# Read tools bypass (all roles hold fs.read). Tenant from ``tenant``
# arg or DXRK_TENANT env; user from DXRK_USER env.
_MCP_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "dxrk_memory_add_drawer",
        "dxrk_memory_update_drawer",
        "dxrk_memory_delete_drawer",
        "dxrk_memory_mine",
        "dxrk_memory_kg_add",
        "dxrk_memory_kg_invalidate",
        "dxrk_memory_consolidate",
        "dxrk_memory_forget",
        "dxrk_memory_pin",
    }
)


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
    require_op(tenant, resolve_user(), "mine")


def _get_memory(palace_path: str) -> DxrkMemory:
    dm = DxrkMemory(palace_path)
    dm.init()
    return dm


def _get_kg(db_path: str | None = None) -> KnowledgeGraph:
    if db_path:
        return KnowledgeGraph(db_path)
    return KnowledgeGraph()


# ---------------------------------------------------------------------------
# Tool definitions — inputSchema mirrors MCP spec (JSON Schema draft 7 subset)
# ---------------------------------------------------------------------------
TOOLS: dict[str, dict[str, Any]] = {
    "dxrk_memory_status": {
        "description": "Health + counts for the DxrkMemory palace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "palace": {"type": "string", "description": "Palace path override"},
            },
        },
    },
    "dxrk_memory_search": {
        "description": "Hybrid BM25 search over drawers with optional date window",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "n_results": {"type": "integer", "default": 5},
                "since": {"type": "string", "description": "ISO date YYYY-MM-DD inclusive"},
                "before": {"type": "string", "description": "ISO date YYYY-MM-DD exclusive"},
                "palace": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    "dxrk_memory_add_drawer": {
        "description": "Add a single drawer (verbatim chunk) to a wing/room",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "content": {"type": "string"},
                "source_file": {"type": "string"},
                "chunk_index": {"type": "integer", "default": 0},
                "palace": {"type": "string"},
                "supersedes": {
                    "type": "string",
                    "description": "Drawer id this version replaces (old row kept with valid_to)",
                },
                "importance": {"type": "number", "description": "Explicit importance for decay-aware ranking"},
            },
            "required": ["wing", "room", "content", "source_file"],
        },
    },
    "dxrk_memory_get_drawer": {
        "description": "Fetch a drawer by id",
        "inputSchema": {
            "type": "object",
            "properties": {"drawer_id": {"type": "string"}, "palace": {"type": "string"}},
            "required": ["drawer_id"],
        },
    },
    "dxrk_memory_list_drawers": {
        "description": "List drawers (paginated) optionally filtered by wing/room",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "palace": {"type": "string"},
            },
        },
    },
    "dxrk_memory_update_drawer": {
        "description": "Update drawer content/metadata (upsert)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string"},
                "content": {"type": "string"},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "palace": {"type": "string"},
            },
            "required": ["drawer_id"],
        },
    },
    "dxrk_memory_delete_drawer": {
        "description": "Delete drawer(s) by id or where filter",
        "inputSchema": {
            "type": "object",
            "properties": {"drawer_id": {"type": "string"}, "palace": {"type": "string"}},
            "required": ["drawer_id"],
        },
    },
    "dxrk_memory_check_duplicate": {
        "description": "Check if content already exists (BM25 duplicate threshold 0.15)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "threshold": {"type": "number", "default": 0.15},
                "palace": {"type": "string"},
            },
            "required": ["content"],
        },
    },
    "dxrk_memory_list_wings": {
        "description": "List wings present in palace",
        "inputSchema": {"type": "object", "properties": {"palace": {"type": "string"}}},
    },
    "dxrk_memory_list_rooms": {
        "description": "List rooms, optionally for a wing",
        "inputSchema": {"type": "object", "properties": {"wing": {"type": "string"}, "palace": {"type": "string"}}},
    },
    "dxrk_memory_taxonomy": {
        "description": "Wings → rooms → count taxonomy",
        "inputSchema": {"type": "object", "properties": {"palace": {"type": "string"}}},
    },
    "dxrk_memory_mine": {
        "description": "Mine a project directory into the palace (chunk + upsert)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_dir": {"type": "string"},
                "wing": {"type": "string", "default": "default"},
                "room": {"type": "string", "default": "general"},
                "dry_run": {"type": "boolean", "default": False},
                "palace": {"type": "string"},
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
        "description": "Palace graph overview (wings/rooms/tunnels)",
        "inputSchema": {"type": "object", "properties": {"palace": {"type": "string"}}},
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
        "description": "Merge drawers into one distilled drawer that supersedes them (extractive, no LLM)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer_ids": {"type": "array", "items": {"type": "string"}},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "palace": {"type": "string"},
            },
            "required": ["drawer_ids"],
        },
    },
    "dxrk_memory_forget": {
        "description": "Scoped erase honoring the supersede model (soft-mark by default; KG never deleted)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer_ids": {"type": "array", "items": {"type": "string"}},
                "wing": {"type": "string"},
                "room": {"type": "string"},
                "before": {"type": "string", "description": "ISO date: forget drawers filed strictly before"},
                "hard": {"type": "boolean", "default": False},
                "include_kg": {"type": "boolean", "default": False},
                "palace": {"type": "string"},
            },
        },
    },
    "dxrk_memory_pin": {
        "description": "Pin a drawer (or the L0 identity block) against decay-eviction; pinned drawers lead wake_up",
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer_id": {"type": "string"},
                "scope": {"type": "string", "enum": ["drawer", "identity"], "default": "drawer"},
                "pinned": {"type": "boolean", "default": True},
                "palace": {"type": "string"},
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
                "wing": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "palace": {"type": "string"},
            },
        },
    },
}


def _handle_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    palace_path = _resolve_palace(args.get("palace"))
    try:
        _check_mcp_op(name, args)
        if name == "dxrk_memory_status":
            dm = _get_memory(palace_path)
            h = dm.health()
            cnt = dm.count()
            wings = dm.list_wings()
            spine = dm.status()
            return {
                "ok": h.get("ok"),
                "detail": h.get("detail"),
                "count": cnt,
                "wings": wings,
                "budgets": dm.budgets(),
                "palace_path": palace_path,
                "quarantined": spine.get("quarantined", 0),
                "quarantine_warning": spine.get("quarantine_warning", False),
                "checksum_mismatches": spine.get("checksum_mismatches", 0),
                "needs_rehash": spine.get("needs_rehash", 0),
                "merkle_root": spine.get("merkle_root", ""),
            }

        if name == "dxrk_memory_search":
            q = str(args.get("query", "")).strip()
            # sanitize mirrors searcher guard
            q = sanitize_query(q)
            dm = _get_memory(palace_path)
            res = dm.search(
                q,
                wing=args.get("wing"),
                room=args.get("room"),
                n_results=int(args.get("n_results", 5)),
                since=args.get("since"),
                before=args.get("before"),
            )
            # normalize to list of docs for MCP clients expecting text
            return {"palace_path": palace_path, "query": q, "result": res}

        if name == "dxrk_memory_add_drawer":
            dm = _get_memory(palace_path)
            add_kwargs: dict[str, Any] = {}
            if args.get("supersedes") is not None:
                add_kwargs["supersedes"] = str(args.get("supersedes"))
            if args.get("importance") is not None:
                try:
                    add_kwargs["importance"] = float(args.get("importance"))  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    pass
            did = dm.add_drawer(
                wing=str(args.get("wing", "default")),
                room=str(args.get("room", "general")),
                content=str(args.get("content", "")),
                source_file=str(args.get("source_file", "")),
                chunk_index=int(args.get("chunk_index", 0)),
                **add_kwargs,  # type: ignore[arg-type]
            )
            return {"drawer_id": did, "palace_path": palace_path}

        if name == "dxrk_memory_get_drawer":
            dm = _get_memory(palace_path)
            got = dm.get_drawer(str(args["drawer_id"]))
            return {"drawer": got, "palace_path": palace_path}

        if name == "dxrk_memory_list_drawers":
            dm = _get_memory(palace_path)
            # brute via search empty query filtered
            where_wing = args.get("wing")
            where_room = args.get("room")
            lim = int(args.get("limit", 20))
            drawers = dm.list_drawers(
                wing=where_wing if isinstance(where_wing, str) and where_wing else None,
                room=where_room if isinstance(where_room, str) and where_room else None,
                limit=lim,
                include_quarantined=bool(args.get("include_quarantined", False)),
            )
            out = []
            for drawer in drawers:
                if drawer.get("quarantined"):
                    out.append({"id": drawer.get("id"), "metadata": drawer.get("metadata"), "quarantined": True})
                else:
                    doc = drawer.get("document")
                    out.append(
                        {
                            "id": drawer.get("id"),
                            "document": str(doc)[:500] if isinstance(doc, str) else "",
                            "metadata": drawer.get("metadata"),
                        }
                    )
            return {"drawers": out, "count": len(out), "palace_path": palace_path}

        if name == "dxrk_memory_update_drawer":
            dm = _get_memory(palace_path)
            did = str(args["drawer_id"])
            # fetch existing to preserve metadata if partial update
            existing = dm.get_drawer(did)
            if existing is None:
                return {"error": f"not found {did}"}
            meta: dict[str, Any] = dict(existing.get("metadata") or {})  # type: ignore
            if args.get("wing"):
                meta["wing"] = str(args["wing"])  # type: ignore[index]
            if args.get("room"):
                meta["room"] = str(args["room"])  # type: ignore[index]
            content = str(args.get("content", existing.get("document") or ""))  # type: ignore[arg-type]
            # Stable-id upsert: drawer_id is the PK, so wing/room/content changes
            # land on the same row. (A prior add_drawer() pre-call created an
            # orphan drawer under the new wing/room via make_id hash.)
            wing = str(meta.get("wing") or "default")  # type: ignore[arg-type]
            room = str(meta.get("room") or "general")  # type: ignore[arg-type]
            meta["wing"] = wing
            meta["room"] = room
            meta.setdefault("source_file", did)
            meta.setdefault("chunk_index", 0)
            if content != (existing.get("document") or ""):
                meta["filed_at"] = datetime.now(UTC).isoformat()
                # Spine integrity: a content change invalidates the checksum —
                # rehash here so the read-path gate does not auto-quarantine
                # our own write.
                from .migrate import content_sha256_of, ensure_spine_defaults

                ensure_spine_defaults(meta)
                meta["content_sha256"] = content_sha256_of(content)
            col = dm._collection(create=False)  # type: ignore[attr-defined]
            col.upsert(documents=[content], ids=[did], metadatas=[meta])  # type: ignore[arg-type]
            # Phase 3: every write path enforces the per-wing budget — a
            # wing/room move grows the destination wing, so cap it here.
            try:
                dm.enforce_wing_cap(wing)
            except Exception:
                pass
            return {"drawer_id": did, "updated": True}

        if name == "dxrk_memory_delete_drawer":
            dm = _get_memory(palace_path)
            did = str(args["drawer_id"])
            col = dm._collection(create=False)  # type: ignore[attr-defined]
            col.delete(ids=[did])
            return {"deleted": did}

        if name == "dxrk_memory_check_duplicate":
            content = str(args.get("content", ""))
            try:
                threshold = float(args.get("threshold", 0.15))
            except (TypeError, ValueError):
                threshold = 0.15
            dm = _get_memory(palace_path)
            # use search to approximate duplicate: exact containment either way
            # or high token overlap (>= threshold) against the top hit.
            sanitized = sanitize_query(content[:800])
            if not sanitized:
                return {"duplicate": False, "reason": "empty query"}
            res = dm.search(sanitized, n_results=3)
            hits = res.get("results", []) if isinstance(res, dict) else []
            if not isinstance(hits, list):
                hits = []
            duplicate = False
            top_preview: list[str] = []
            norm_content = content.strip().lower()
            content_tokens = {t for t in re.findall(r"\w{2,}", norm_content)}
            for h in hits:
                txt = h.get("text", "") if isinstance(h, dict) else ""
                if not isinstance(txt, str) or not txt:
                    continue
                top_preview.append(txt[:200])
                norm_txt = txt.strip().lower()
                if norm_content and (norm_content in norm_txt or norm_txt in norm_content):
                    duplicate = True
                    break
                if content_tokens:
                    hit_tokens = {t for t in re.findall(r"\w{2,}", norm_txt)}
                    overlap = len(content_tokens & hit_tokens) / len(content_tokens)
                    if overlap >= threshold:
                        duplicate = True
                        break
            return {"duplicate": duplicate, "top_docs": top_preview[:1]}

        if name == "dxrk_memory_list_wings":
            dm = _get_memory(palace_path)
            return {"wings": dm.list_wings(), "palace_path": palace_path}

        if name == "dxrk_memory_list_rooms":
            dm = _get_memory(palace_path)
            wing = args.get("wing")  # type: ignore[assignment]
            return {"rooms": dm.list_rooms(wing if isinstance(wing, str) else None), "palace_path": palace_path}  # type: ignore[arg-type]

        if name == "dxrk_memory_taxonomy":
            dm = _get_memory(palace_path)
            wings = dm.list_wings()
            taxonomy: dict[str, Any] = {}
            for w in wings:
                taxonomy[w] = dm.list_rooms(w)
            return {"taxonomy": taxonomy, "wings": wings, "palace_path": palace_path}

        if name == "dxrk_memory_mine":
            dm = _get_memory(palace_path)
            res = dm.mine(
                project_dir=str(args["project_dir"]),
                wing=str(args.get("wing", "default")),
                room=str(args.get("room", "general")),
                dry_run=bool(args.get("dry_run", False)),
            )
            return {"palace_path": palace_path, **res}

        if name == "dxrk_memory_kg_query":
            kg = _get_kg(args.get("kg_path"))  # type: ignore[arg-type]
            kg_res = kg.query_entity(
                str(args["entity"]),
                as_of=args.get("as_of"),
                direction=str(args.get("direction", "both")),  # type: ignore[arg-type]
            )
            kg.close()
            return {"entity": args["entity"], "results": kg_res}

        if name == "dxrk_memory_kg_add":
            kg = _get_kg(args.get("kg_path"))
            tid = kg.add_triple(
                str(args["subject"]),
                str(args["predicate"]),
                str(args["object"]),
                valid_from=args.get("valid_from"),
                valid_to=args.get("valid_to"),
            )
            kg.close()
            return {"triple_id": tid}

        if name == "dxrk_memory_kg_invalidate":
            kg = _get_kg(args.get("kg_path"))
            kg.invalidate(str(args["subject"]), str(args["predicate"]), str(args["object"]), ended=args.get("ended"))
            kg.close()
            return {"invalidated": True}

        if name == "dxrk_memory_kg_timeline":
            kg = _get_kg(args.get("kg_path"))
            tl = kg.timeline(args.get("entity") if isinstance(args.get("entity"), str) else None)
            kg.close()
            return {"timeline": tl}

        if name == "dxrk_memory_kg_stats":
            kg = _get_kg(args.get("kg_path"))
            st = kg.stats()
            kg.close()
            return st

        if name == "dxrk_memory_graph_stats":
            dm = _get_memory(palace_path)
            wings = dm.list_wings()
            # simple graph stats: counts per wing
            counts: dict[str, int] = {}
            for w in wings:
                counts[w] = len(dm.list_rooms(w))
            return {
                "wings": len(wings),
                "rooms_by_wing": counts,
                "total_drawers": dm.count(),
                "palace_path": palace_path,
            }

        if name == "dxrk_memory_traverse":
            kg = _get_kg(args.get("kg_path"))  # type: ignore[arg-type]
            traversed = kg.traverse(str(args["start"]), depth=int(args.get("depth", 2)), as_of=args.get("as_of"))  # type: ignore[arg-type]
            kg.close()
            return {"start": args["start"], "traversed": traversed}

        if name == "dxrk_memory_consolidate":
            dm = _get_memory(palace_path)
            raw_ids = args.get("drawer_ids") or []
            ids = [str(d) for d in raw_ids] if isinstance(raw_ids, list) else []
            res = dm.consolidate_drawers(
                ids,
                wing=str(args["wing"]) if args.get("wing") else None,
                room=str(args["room"]) if args.get("room") else None,
            )
            return {"palace_path": palace_path, **res}

        if name == "dxrk_memory_forget":
            dm = _get_memory(palace_path)
            raw_ids = args.get("drawer_ids")
            forget_ids = [str(d) for d in raw_ids] if isinstance(raw_ids, list) else None
            res = dm.forget(
                drawer_ids=forget_ids,
                wing=str(args["wing"]) if args.get("wing") else None,
                room=str(args["room"]) if args.get("room") else None,
                before=str(args["before"]) if args.get("before") else None,
                hard=bool(args.get("hard", False)),
                include_kg=bool(args.get("include_kg", False)),
            )
            return {"palace_path": palace_path, **res}

        if name == "dxrk_memory_pin":
            dm = _get_memory(palace_path)
            scope = str(args.get("scope", "drawer"))
            want_pinned = bool(args.get("pinned", True))
            if scope == "identity":
                if want_pinned:
                    return {"palace_path": palace_path, **dm.pin_identity()}
                return {"palace_path": palace_path, "unpinned": dm.unpin_identity()}
            drawer_id = str(args.get("drawer_id") or "")
            if not drawer_id:
                return {"error": "drawer_id required for scope=drawer"}
            ok = dm.pin_drawer(drawer_id) if want_pinned else dm.unpin_drawer(drawer_id)
            if not ok:
                return {"error": f"not found {drawer_id}"}
            return {"drawer_id": drawer_id, "pinned": want_pinned, "palace_path": palace_path}

        if name == "dxrk_memory_timeline":
            dm = _get_memory(palace_path)
            try:
                lim = int(args.get("limit", 50))
            except (TypeError, ValueError):
                lim = 50
            entries = dm.timeline(
                since=str(args["since"]) if args.get("since") else None,
                before=str(args["before"]) if args.get("before") else None,
                wing=str(args["wing"]) if args.get("wing") else None,
                limit=lim,
            )
            return {"entries": entries, "count": len(entries), "palace_path": palace_path}

        return {"error": f"unknown tool {name}"}
    except Exception as e:
        tb = traceback.format_exc()
        return {"error": str(e), "traceback": tb, "palace_path": palace_path}


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
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        if name not in TOOLS:
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
        # domain errors like update_drawer not-found without traceback)
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
        "--palace",
        dest="palace",
        default=None,
        help="Palace path override (default ~/.dxrk/memory or DXRK_MEMORY_PATH)",
    )
    args = parser.parse_args(argv)

    if args.palace:
        os.environ["DXRK_MEMORY_PATH"] = str(Path(args.palace).expanduser().resolve())

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
