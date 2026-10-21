# SPDX-License-Identifier: MIT
"""Per-tool handlers for the DxrkMemory MCP server.

Each handler receives the raw ``arguments`` object from ``tools/call`` plus
the already-resolved malla path, and returns the exact payload the MCP
layer serializes. ``mcp_server._handle_tool`` owns validation, dispatch and
error capture; this module owns only tool behaviour.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .graph import KnowledgeGraph
from .malla import DxrkMemory
from .search import sanitize_query

ToolHandler = Callable[[dict[str, Any], str], dict[str, Any]]


# MCP reads project fragmento metadata: the score ledger ships truncated to
# the last entries (with score_ledger_dropped adjusted so the visible
# slice stays hash-chain verifiable) and the raw access_history list is
# replaced by its length — timestamps are bookkeeping, not read payload.
_MCP_LEDGER_LAST = 5


def _project_meta_for_mcp(meta: dict[str, Any]) -> dict[str, Any]:
    """Copy ``meta`` safe for MCP read responses (never mutates the input)."""
    m = dict(meta)
    m.pop("_embedding", None)
    hist = m.get("access_history")
    if isinstance(hist, list):
        m = {k: v for k, v in m.items() if k != "access_history"}
        m["access_history_len"] = len(hist)
    ledger = m.get("score_ledger")
    if isinstance(ledger, list) and len(ledger) > _MCP_LEDGER_LAST:
        kept = ledger[-_MCP_LEDGER_LAST:]
        dropped_raw = m.get("score_ledger_dropped")
        dropped = dropped_raw if isinstance(dropped_raw, int) and not isinstance(dropped_raw, bool) else 0
        m["score_ledger"] = kept
        m["score_ledger_dropped"] = max(0, dropped) + (len(ledger) - len(kept))
    return m


def _get_memory(malla_path: str) -> DxrkMemory:
    dm = DxrkMemory(malla_path)
    dm.init()
    return dm


def _get_kg(db_path: str | None = None) -> KnowledgeGraph:
    if db_path:
        return KnowledgeGraph(db_path)
    return KnowledgeGraph()


def handle_status(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    h = dm.health()
    cnt = dm.count()
    nodos = dm.list_nodos()
    spine = dm.status()
    return {
        "ok": h.get("ok"),
        "detail": h.get("detail"),
        "count": cnt,
        "nodos": nodos,
        "budgets": dm.budgets(),
        "malla_path": malla_path,
        "quarantined": spine.get("quarantined", 0),
        "quarantine_warning": spine.get("quarantine_warning", False),
        "checksum_mismatches": spine.get("checksum_mismatches", 0),
        "needs_rehash": spine.get("needs_rehash", 0),
        "merkle_root": spine.get("merkle_root", ""),
    }


def handle_search(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    q = str(args.get("query", "")).strip()
    # sanitize mirrors searcher guard
    q = sanitize_query(q)
    dm = _get_memory(malla_path)
    res = dm.search(
        q,
        nodo=args.get("nodo"),
        celda=args.get("celda"),
        n_results=int(args.get("n_results", 5)),
        since=args.get("since"),
        before=args.get("before"),
    )
    # normalize to list of docs for MCP clients expecting text
    return {"malla_path": malla_path, "query": q, "result": res}


def handle_add_fragmento(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    add_kwargs: dict[str, Any] = {}
    if args.get("supersedes") is not None:
        add_kwargs["supersedes"] = str(args.get("supersedes"))
    if args.get("importance") is not None:
        try:
            add_kwargs["importance"] = float(args.get("importance"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            pass
    did = dm.add_fragmento(
        nodo=str(args.get("nodo", "default")),
        celda=str(args.get("celda", "general")),
        content=str(args.get("content", "")),
        source_file=str(args.get("source_file", "")),
        chunk_index=int(args.get("chunk_index", 0)),
        **add_kwargs,  # type: ignore[arg-type]
    )
    return {"fragmento_id": did, "malla_path": malla_path}


def handle_get_fragmento(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    got = dm.get_fragmento(str(args["fragmento_id"]))
    got_meta = got.get("metadata") if isinstance(got, dict) else None
    if isinstance(got, dict) and isinstance(got_meta, dict):
        projected_got = dict(got)
        projected_got["metadata"] = _project_meta_for_mcp(got_meta)
        got = projected_got
    return {"fragmento": got, "malla_path": malla_path}


def handle_list_fragmentos(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    # brute via search empty query filtered
    where_nodo = args.get("nodo")
    where_celda = args.get("celda")
    lim = int(args.get("limit", 20))
    fragmentos = dm.list_fragmentos(
        nodo=where_nodo if isinstance(where_nodo, str) and where_nodo else None,
        celda=where_celda if isinstance(where_celda, str) and where_celda else None,
        limit=lim,
        include_quarantined=bool(args.get("include_quarantined", False)),
    )
    out = []
    for fragmento in fragmentos:
        raw_meta = fragmento.get("metadata")
        projected = _project_meta_for_mcp(raw_meta) if isinstance(raw_meta, dict) else raw_meta
        if fragmento.get("quarantined"):
            out.append({"id": fragmento.get("id"), "metadata": projected, "quarantined": True})
        else:
            doc = fragmento.get("document")
            out.append(
                {
                    "id": fragmento.get("id"),
                    "document": str(doc)[:500] if isinstance(doc, str) else "",
                    "metadata": projected,
                }
            )
    return {"fragmentos": out, "count": len(out), "malla_path": malla_path}


def handle_update_fragmento(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    did = str(args["fragmento_id"])
    # fetch existing to preserve metadata if partial update
    existing = dm.get_fragmento(did)
    if existing is None:
        return {"error": f"not found {did}"}
    meta: dict[str, Any] = dict(existing.get("metadata") or {})  # type: ignore
    if args.get("nodo"):
        meta["nodo"] = str(args["nodo"])  # type: ignore[index]
    if args.get("celda"):
        meta["celda"] = str(args["celda"])  # type: ignore[index]
    content = str(args.get("content", existing.get("document") or ""))  # type: ignore[arg-type]
    # Stable-id upsert: fragmento_id is the PK, so nodo/celda/content changes
    # land on the same row. (A prior add_fragmento() pre-call created an
    # orphan fragmento under the new nodo/celda via make_id hash.)
    nodo = str(meta.get("nodo") or "default")  # type: ignore[arg-type]
    celda = str(meta.get("celda") or "general")  # type: ignore[arg-type]
    meta["nodo"] = nodo
    meta["celda"] = celda
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
    # Phase 3: every write path enforces the per-nodo budget — a
    # nodo/celda move grows the destination nodo, so cap it here.
    try:
        dm.enforce_nodo_cap(nodo)
    except Exception:
        pass
    return {"fragmento_id": did, "updated": True}


def handle_delete_fragmento(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    did = str(args["fragmento_id"])
    col = dm._collection(create=False)  # type: ignore[attr-defined]
    col.delete(ids=[did])
    return {"deleted": did}


def handle_check_duplicate(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    content = str(args.get("content", ""))
    try:
        threshold = float(args.get("threshold", 0.15))
    except (TypeError, ValueError):
        threshold = 0.15
    dm = _get_memory(malla_path)
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


def handle_list_nodos(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    return {"nodos": dm.list_nodos(), "malla_path": malla_path}


def handle_list_celdas(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    nodo = args.get("nodo")  # type: ignore[assignment]
    return {"celdas": dm.list_celdas(nodo if isinstance(nodo, str) else None), "malla_path": malla_path}  # type: ignore[arg-type]


def handle_taxonomy(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    nodos = dm.list_nodos()
    taxonomy: dict[str, Any] = {}
    for w in nodos:
        taxonomy[w] = dm.list_celdas(w)
    return {"taxonomy": taxonomy, "nodos": nodos, "malla_path": malla_path}


def handle_mine(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    res = dm.mine(
        project_dir=str(args["project_dir"]),
        nodo=str(args.get("nodo", "default")),
        celda=str(args.get("celda", "general")),
        dry_run=bool(args.get("dry_run", False)),
    )
    return {"malla_path": malla_path, **res}


def handle_kg_query(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    kg = _get_kg(args.get("kg_path"))  # type: ignore[arg-type]
    kg_res = kg.query_entity(
        str(args["entity"]),
        as_of=args.get("as_of"),
        direction=str(args.get("direction", "both")),  # type: ignore[arg-type]
    )
    kg.close()
    return {"entity": args["entity"], "results": kg_res}


def handle_kg_add(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
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


def handle_kg_invalidate(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    kg = _get_kg(args.get("kg_path"))
    kg.invalidate(str(args["subject"]), str(args["predicate"]), str(args["object"]), ended=args.get("ended"))
    kg.close()
    return {"invalidated": True}


def handle_kg_timeline(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    kg = _get_kg(args.get("kg_path"))
    tl = kg.timeline(args.get("entity") if isinstance(args.get("entity"), str) else None)
    kg.close()
    return {"timeline": tl}


def handle_kg_stats(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    kg = _get_kg(args.get("kg_path"))
    st = kg.stats()
    kg.close()
    return st


def handle_graph_stats(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    nodos = dm.list_nodos()
    # simple graph stats: counts per nodo
    counts: dict[str, int] = {}
    for w in nodos:
        counts[w] = len(dm.list_celdas(w))
    return {
        "nodos": len(nodos),
        "celdas_by_nodo": counts,
        "total_fragmentos": dm.count(),
        "malla_path": malla_path,
    }


def handle_traverse(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    kg = _get_kg(args.get("kg_path"))  # type: ignore[arg-type]
    traversed = kg.traverse(str(args["start"]), depth=int(args.get("depth", 2)), as_of=args.get("as_of"))  # type: ignore[arg-type]
    kg.close()
    return {"start": args["start"], "traversed": traversed}


def handle_consolidate(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    raw_ids = args.get("fragmento_ids") or []
    ids = [str(d) for d in raw_ids] if isinstance(raw_ids, list) else []
    res = dm.consolidate_fragmentos(
        ids,
        nodo=str(args["nodo"]) if args.get("nodo") else None,
        celda=str(args["celda"]) if args.get("celda") else None,
    )
    return {"malla_path": malla_path, **res}


def handle_forget(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    raw_ids = args.get("fragmento_ids")
    forget_ids = [str(d) for d in raw_ids] if isinstance(raw_ids, list) else None
    res = dm.forget(
        fragmento_ids=forget_ids,
        nodo=str(args["nodo"]) if args.get("nodo") else None,
        celda=str(args["celda"]) if args.get("celda") else None,
        before=str(args["before"]) if args.get("before") else None,
        hard=bool(args.get("hard", False)),
        include_kg=bool(args.get("include_kg", False)),
    )
    return {"malla_path": malla_path, **res}


def handle_pin(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    scope = str(args.get("scope", "fragmento"))
    want_pinned = bool(args.get("pinned", True))
    if scope == "identity":
        if want_pinned:
            return {"malla_path": malla_path, **dm.pin_identity()}
        return {"malla_path": malla_path, "unpinned": dm.unpin_identity()}
    fragmento_id = str(args.get("fragmento_id") or "")
    if not fragmento_id:
        return {"error": "fragmento_id required for scope=fragmento"}
    ok = dm.pin_fragmento(fragmento_id) if want_pinned else dm.unpin_fragmento(fragmento_id)
    if not ok:
        return {"error": f"not found {fragmento_id}"}
    return {"fragmento_id": fragmento_id, "pinned": want_pinned, "malla_path": malla_path}


def handle_timeline(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    try:
        lim = int(args.get("limit", 50))
    except (TypeError, ValueError):
        lim = 50
    entries = dm.timeline(
        since=str(args["since"]) if args.get("since") else None,
        before=str(args["before"]) if args.get("before") else None,
        nodo=str(args["nodo"]) if args.get("nodo") else None,
        limit=lim,
    )
    return {"entries": entries, "count": len(entries), "malla_path": malla_path}


def handle_quarantine(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    dm = _get_memory(malla_path)
    fragmento_id = str(args.get("fragmento_id") or "")
    if not fragmento_id:
        return {"error": "fragmento_id required"}
    if bool(args.get("unquarantine", False)):
        ok = dm.unquarantine_fragmento(fragmento_id)
        if not ok:
            return {"error": f"not found {fragmento_id}"}
        return {"fragmento_id": fragmento_id, "quarantined": False, "malla_path": malla_path}
    ok = dm.quarantine_fragmento(fragmento_id, reason=str(args.get("reason") or ""))
    if not ok:
        return {"error": f"not found {fragmento_id}"}
    return {"fragmento_id": fragmento_id, "quarantined": True, "malla_path": malla_path}


# Fase 2: Eval Harness
def handle_eval_run(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .eval_harness import EvalHarness, generate_synthetic_queries

    dm = _get_memory(malla_path)
    harness = EvalHarness(dm, Path(malla_path) / "eval")
    # Generate synthetic queries for evaluation
    n_q = int(args.get("n_queries", 10))
    queries = generate_synthetic_queries(dm, nodo=str(args["nodo"]), n=n_q)
    report = harness.run(nodo=str(args["nodo"]), queries=queries)
    return {
        "malla_path": malla_path,
        "report": {
            "nodo": report.nodo,
            "num_queries": report.num_queries,
            "recall_at_k": report.recall_at_k,
            "mrr": report.mrr,
            "ndcg": report.ndcg,
            "ece": report.ece,
            "latency_p50": report.latency_p50,
            "latency_p95": report.latency_p95,
            "latency_p99": report.latency_p99,
            "evaluated_at": report.evaluated_at,
        },
    }


def handle_eval_synthetic(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .eval_harness import generate_synthetic_queries

    dm = _get_memory(malla_path)
    queries = generate_synthetic_queries(dm, nodo=str(args["nodo"]), n=int(args.get("n", 20)))
    return {
        "malla_path": malla_path,
        "queries": [
            {
                "query": q.query,
                "expected_fragmento_ids": q.expected_fragmento_ids,
                "nodo": q.nodo,
                "difficulty": q.difficulty,
                "tags": q.tags,
            }
            for q in queries
        ],
    }


# Fase 2: Metacognición Avanzada
def handle_metacog_predict(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .metacog_v2 import MetacognitionV2

    dm = _get_memory(malla_path)
    meta_v2: MetacognitionV2 = MetacognitionV2(dm)
    pred = meta_v2.predict(str(args["query"]), nodo=str(args["nodo"]))
    return {
        "malla_path": malla_path,
        "confidence": pred.confidence,
        "difficulty": pred.difficulty,
        "ece": pred.ece,
    }


def handle_calibrate_fit(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .metacog_v2 import MetacognitionV2

    dm = _get_memory(malla_path)
    meta_v2_cal: MetacognitionV2 = MetacognitionV2(dm)
    result = meta_v2_cal.fit_calibration(nodo=str(args["nodo"]), method=str(args.get("method", "temperature")))
    return {"malla_path": malla_path, "method": args.get("method", "temperature"), "params": result}


# Fase 2: Multi-Tenant Calibrate
def handle_calibrate_tenant(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .calibrate_v2 import CalibrationParams, save_calibration

    malla = Path(malla_path)
    params = CalibrationParams(
        tenant=str(args["tenant"]),
        nodo=str(args["nodo"]),
        a=float(args.get("a", 1.0)),
        b=float(args.get("b", 0.0)),
        c=float(args.get("c", 1.0)),
        pe_lambda=float(args.get("pe_lambda", 0.0)),
        score=float(args.get("score", 0.5)),
    )
    save_calibration(malla, params)
    return {
        "malla_path": malla_path,
        "saved": True,
        "params": {
            "a": params.a,
            "b": params.b,
            "c": params.c,
            "pe_lambda": params.pe_lambda,
            "score": params.score,
        },
    }


def handle_calibrate_chain(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .calibrate_v2 import get_calibration_chain

    malla = Path(malla_path)
    chain = get_calibration_chain(malla, str(args["tenant"]), str(args["nodo"]))
    return {
        "malla_path": malla_path,
        "chain": [
            {
                "tenant": c.tenant,
                "nodo": c.nodo,
                "a": c.a,
                "b": c.b,
                "c": c.c,
                "pe_lambda": c.pe_lambda,
                "score": c.score,
            }
            for c in chain
        ],
    }


# Fase 2: Production Hardening
def handle_circuit_breaker_status(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .production import get_circuit_breakers

    breakers = get_circuit_breakers()
    return {
        "malla_path": malla_path,
        "breakers": {
            k: {"state": v.state, "failure_count": v._failure_count, "success_count": v._success_count}
            for k, v in breakers.items()
        },
    }


def handle_slo_check(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .production import SLOStatus, check_slo, load_slo_config

    dm = _get_memory(malla_path)
    config = load_slo_config(Path(malla_path))
    slo_result: SLOStatus = check_slo(dm, nodo=str(args["nodo"]), config=config)
    return {"malla_path": malla_path, "compliant": slo_result.compliant, "details": slo_result.details}


def handle_rollback_check(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .production import AutoRollbackManager

    # Malla init: legacy call kept for its side effects (creates the malla dir).
    _get_memory(malla_path)
    rollback_mgr = AutoRollbackManager(Path(malla_path))
    result = rollback_mgr.check_regression(nodo=str(args["nodo"]))
    return {
        "malla_path": malla_path,
        "should_rollback": result["should_rollback"],
        "severity": result["severity"],
        "details": result["details"],
    }


# Fase 2: Judge Externo Continuo
def handle_judge_status(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .judge_continuous import load_judge_state

    state = load_judge_state(Path(malla_path))
    return {
        "malla_path": malla_path,
        "last_run": state.last_run,
        "consecutive_passes": state.consecutive_passes,
        "consecutive_failures": state.consecutive_failures,
        "rollback_history": state.rollback_history[-10:],
    }


def handle_judge_run(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
    from .eval_harness import EvalHarness
    from .judge_continuous import ContinuousJudge

    dm = _get_memory(malla_path)
    harness = EvalHarness(dm, Path(malla_path) / "eval")
    judge = ContinuousJudge(Path(malla_path), harness, interval_hours=24)
    verdict = judge.run_once()
    return {
        "malla_path": malla_path,
        "verdict": {
            "passed": verdict.passed,
            "regression_detected": verdict.regression_detected,
            "severity": verdict.severity,
            "details": verdict.details,
            "auto_rollback": verdict.auto_rollback,
        },
    }


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "dxrk_memory_status": handle_status,
    "dxrk_memory_search": handle_search,
    "dxrk_memory_add_fragmento": handle_add_fragmento,
    "dxrk_memory_get_fragmento": handle_get_fragmento,
    "dxrk_memory_list_fragmentos": handle_list_fragmentos,
    "dxrk_memory_update_fragmento": handle_update_fragmento,
    "dxrk_memory_delete_fragmento": handle_delete_fragmento,
    "dxrk_memory_check_duplicate": handle_check_duplicate,
    "dxrk_memory_list_nodos": handle_list_nodos,
    "dxrk_memory_list_celdas": handle_list_celdas,
    "dxrk_memory_taxonomy": handle_taxonomy,
    "dxrk_memory_mine": handle_mine,
    "dxrk_memory_kg_query": handle_kg_query,
    "dxrk_memory_kg_add": handle_kg_add,
    "dxrk_memory_kg_invalidate": handle_kg_invalidate,
    "dxrk_memory_kg_timeline": handle_kg_timeline,
    "dxrk_memory_kg_stats": handle_kg_stats,
    "dxrk_memory_graph_stats": handle_graph_stats,
    "dxrk_memory_traverse": handle_traverse,
    "dxrk_memory_consolidate": handle_consolidate,
    "dxrk_memory_forget": handle_forget,
    "dxrk_memory_pin": handle_pin,
    "dxrk_memory_timeline": handle_timeline,
    "dxrk_memory_quarantine": handle_quarantine,
    "dxrk_memory_eval_run": handle_eval_run,
    "dxrk_memory_eval_synthetic": handle_eval_synthetic,
    "dxrk_memory_metacog_predict": handle_metacog_predict,
    "dxrk_memory_calibrate_fit": handle_calibrate_fit,
    "dxrk_memory_calibrate_tenant": handle_calibrate_tenant,
    "dxrk_memory_calibrate_chain": handle_calibrate_chain,
    "dxrk_memory_circuit_breaker_status": handle_circuit_breaker_status,
    "dxrk_memory_slo_check": handle_slo_check,
    "dxrk_memory_rollback_check": handle_rollback_check,
    "dxrk_memory_judge_status": handle_judge_status,
    "dxrk_memory_judge_run": handle_judge_run,
}
