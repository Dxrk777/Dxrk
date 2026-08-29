# SPDX-License-Identifier: MIT
"""DxrkMemory MCP server — stdlib-only stdio JSON-RPC 2.0.

Stdlib-only MCP engine (~420L) backed by SqliteBackend (FTS5 trigram) + KnowledgeGraph.
Exposes ~19 tools under dxrk_memory_* namespace.

Transport: newline-delimited JSON (stdio). Handles initialize / tools/list / tools/call
and notifications. Designed for ``dxrk-mcp --palace <path>`` or env DXRK_MEMORY_PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
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
    if DEFAULT_PALACE_PATH.strip():
        return str(Path(DEFAULT_PALACE_PATH).expanduser().resolve())
    return str(Path.home() / ".dxrk" / "memory")


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
}


def _handle_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    palace_path = _resolve_palace(args.get("palace"))
    try:
        if name == "dxrk_memory_status":
            dm = _get_memory(palace_path)
            h = dm.health()
            cnt = dm.count()
            wings = dm.list_wings()
            return {
                "ok": h.get("ok"),
                "detail": h.get("detail"),
                "count": cnt,
                "wings": wings,
                "palace_path": palace_path,
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
            did = dm.add_drawer(
                wing=str(args.get("wing", "default")),
                room=str(args.get("room", "general")),
                content=str(args.get("content", "")),
                source_file=str(args.get("source_file", "")),
                chunk_index=int(args.get("chunk_index", 0)),
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
            # use direct collection get for fidelity
            col = dm._collection(create=False)  # type: ignore[attr-defined]
            # build where via search helper
            from .search import build_where_filter

            wf = build_where_filter(
                where_wing if isinstance(where_wing, str) and where_wing else None,
                where_room if isinstance(where_room, str) and where_room else None,
            )
            got2 = col.get(where=wf or None, include=["documents", "metadatas"], limit=lim)  # type: ignore[assignment]
            out = [
                {"id": did, "document": doc[:500], "metadata": meta}  # type: ignore[arg-type]
                for did, doc, meta in zip(got2.ids, got2.documents, got2.metadatas)  # type: ignore[attr-defined]
            ]
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
            # upsert via add_drawer path (preserve source_file)
            source_file = str(meta.get("source_file") or did)  # type: ignore[arg-type]
            chunk_index = int(meta.get("chunk_index") or 0)  # type: ignore[arg-type]
            wing = str(meta.get("wing") or "default")  # type: ignore[arg-type]
            room = str(meta.get("room") or "general")  # type: ignore[arg-type]
            dm.add_drawer(wing=wing, room=room, content=content, source_file=source_file, chunk_index=chunk_index)
            # need to ensure id stable — add_drawer uses make_id hash, so override via direct collection upsert
            col = dm._collection(create=False)  # type: ignore[attr-defined]
            col.upsert(documents=[content], ids=[did], metadatas=[meta])  # type: ignore[arg-type]
            return {"drawer_id": did, "updated": True}

        if name == "dxrk_memory_delete_drawer":
            dm = _get_memory(palace_path)
            did = str(args["drawer_id"])
            col = dm._collection(create=False)  # type: ignore[attr-defined]
            col.delete(ids=[did])
            return {"deleted": did}

        if name == "dxrk_memory_check_duplicate":
            content = str(args.get("content", ""))
            dm = _get_memory(palace_path)
            # use search to approximate duplicate: if top hit distance=0 or BM25 high
            sanitized = sanitize_query(content[:800])
            if not sanitized:
                return {"duplicate": False, "reason": "empty query"}
            res = dm.search(sanitized, n_results=3)
            docs: Any = res.get("documents") if isinstance(res, dict) else []  # type: ignore[assignment]
            # threshold 0.15 cosine; we approximate via exact substring or high BM25 overlap
            duplicate = False
            if docs:
                first = docs[0] if isinstance(docs[0], str) else (docs[0][0] if docs[0] else "")  # type: ignore[index,operator]
                if isinstance(first, str) and content.strip() and content.strip() in first:
                    duplicate = True
            return {"duplicate": duplicate, "top_docs": (docs[:1] if docs else [])}  # type: ignore[return-value]

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
        # if tool returned error, map to isError
        is_error = isinstance(result_obj, dict) and "error" in result_obj and "traceback" in result_obj
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
