# SPDX-License-Identifier: MIT
"""MemoryStack L0-L3 — wake-up stack, stdlib only."""

from __future__ import annotations

import os
import pathlib
from collections import defaultdict
from pathlib import Path

from .backend.base import BaseCollection
from .legacy import migrate_legacy_malla
from .malla import Malla, _is_dead_meta
from .scoring import score_meta

# Limits
MAX_SCAN = 2000
MAX_FRAGMENTOS_L1 = 15
MAX_CHARS_L1 = 3200


def _effective_tenant_id(tenant_id: str | None = None) -> str:
    tid = (tenant_id if tenant_id is not None else os.environ.get("DXRK_TENANT", "")).strip()
    if tid:
        return tid
    try:
        from dxrk.tenant.migration import is_migrated

        if is_migrated():
            return "default"
        return ""
    except Exception:
        return ""


def _resolve_malla_path(tenant_id: str | None, malla_path: str | None) -> str:
    if malla_path is not None:
        s = str(malla_path).strip()
        if s == "" or s == "memory-only":
            return s
        return str(malla_path)
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return str(migrate_legacy_malla(tenant_root(tid)))
        except OSError:
            return str(pathlib.Path.home() / ".dxrk" / "malla")
    try:
        from dxrk.tenant.migration import is_migrated, tenant_root

        if is_migrated():
            return str(migrate_legacy_malla(tenant_root("default")))
    except OSError:
        pass
    return str(migrate_legacy_malla())


def _resolve_identity_path(tenant_id: str | None, identity_path: str | None) -> str:
    if identity_path is not None:
        s = str(identity_path).strip()
        if s:
            return str(pathlib.Path(identity_path).expanduser())
        return s
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return str(tenant_root(tid) / "identity.txt")
        except OSError:
            return str(pathlib.Path.home() / ".dxrk" / "identity.txt")
    try:
        from dxrk.tenant.migration import is_migrated, tenant_root

        if is_migrated():
            return str(tenant_root("default") / "identity.txt")
    except OSError:
        pass
    return str(pathlib.Path.home() / ".dxrk" / "identity.txt")


def _get_collection(malla_path: str, *, create: bool = False) -> BaseCollection:
    pal = Malla(malla_path)
    return pal._collection(create=create)  # type: ignore[attr-defined]


class Layer0:
    """Identity — ~100 tokens, always loaded from ~/.dxrk/identity.txt (tenant-aware)."""

    def __init__(self, identity_path: str | None = None, tenant_id: str | None = None) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.path = _resolve_identity_path(tenant_id, identity_path)
        self._text: str | None = None

    def render(self) -> str:
        if self._text is not None:
            return self._text
        if os.path.exists(self.path):
            try:
                self._text = Path(self.path).read_text(encoding="utf-8").strip()
            except OSError:
                self._text = "## L0 — IDENTITY\nNo identity configured."
        else:
            self._text = "## L0 — IDENTITY\nNo identity configured. Create ~/.dxrk/identity.txt"
        return self._text

    def token_estimate(self) -> int:
        return len(self.render()) // 4


class Layer1:
    """Essential story — top fragmentos, auto-generated, ~500-800 tokens."""

    MAX_FRAGMENTOS: int = MAX_FRAGMENTOS_L1
    MAX_CHARS: int = MAX_CHARS_L1
    MAX_SCAN: int = MAX_SCAN

    def __init__(
        self,
        malla_path: str | None = None,
        nodo: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.malla_path = _resolve_malla_path(tenant_id, malla_path)
        self.nodo = nodo

    def generate(self, nodo: str | None = None) -> str:
        effective_nodo = nodo or self.nodo
        try:
            col = _get_collection(self.malla_path, create=False)
        except Exception:
            return "## L1 — No malla found. Run: malla init"
        batch = 500
        docs: list[str] = []
        metas: list[dict[str, object]] = []
        offset = 0
        while True:
            try:
                got = col.get(include=["documents", "metadatas"], limit=batch, offset=offset)
            except Exception:
                break
            bdocs = got.documents
            bmetas = got.metadatas
            if not bdocs:
                break
            docs.extend(bdocs)
            metas.extend(bmetas)
            offset += len(bdocs)
            if len(bdocs) < batch or len(docs) >= self.MAX_SCAN:
                break
        if not docs:
            return "## L1 — No memories yet."
        scored: list[tuple[float, dict[str, object], str]] = []
        for doc, meta in zip(docs, metas):
            meta = meta or {}
            if not isinstance(meta, dict):
                meta = {}
            if effective_nodo and str(meta.get("nodo") or "") != effective_nodo:
                continue
            # Dead fragmentos (superseded / forgotten / quarantined) never
            # surface — the live revision is the current version.
            if _is_dead_meta(meta):
                continue
            doc = doc or ""
            # RDU rank: one formula everywhere (sqlite fusion, hybrid
            # rerank, Layer1). Missing importance defaults to 1.0.
            score = score_meta(meta, default_importance=1.0)
            scored.append((score, meta, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        if effective_nodo and not scored:
            return f"## L1 — No memories yet for nodo={effective_nodo}."
        # Phase 3: pinned fragmentos always surface in wake_up — they lead the
        # list (up to MAX_FRAGMENTOS), then top-scored fill remaining slots.
        pinned = [(s, m, d) for s, m, d in scored if isinstance(m, dict) and m.get("pinned")]
        rest = [(s, m, d) for s, m, d in scored if not (isinstance(m, dict) and m.get("pinned"))]
        top = (pinned + rest)[: self.MAX_FRAGMENTOS]
        by_celda: dict[str, list[tuple[float, dict[str, object], str]]] = defaultdict(list)
        for imp, meta, doc in top:
            celda = str(meta.get("celda", "general")) if isinstance(meta.get("celda"), str) else "general"
            by_celda[celda].append((imp, meta, doc))
        lines: list[str] = ["## L1 — ESSENTIAL STORY"]
        total = 0
        for celda, entries in sorted(by_celda.items()):
            celda_line = f"\n[{celda}]"
            lines.append(celda_line)
            total += len(celda_line)
            for _imp, meta, doc in entries:
                src = meta.get("source_file", "")
                src_name = Path(str(src)).name if isinstance(src, str) and src else ""
                snippet = doc.strip().replace("\n", " ")
                if len(snippet) > 200:
                    snippet = snippet[:197] + "..."
                entry_line = f"  - {snippet}"
                if src_name:
                    entry_line += f"  ({src_name})"
                if total + len(entry_line) > self.MAX_CHARS:
                    lines.append("  ... (more in L3 search)")
                    return "\n".join(lines)
                lines.append(entry_line)
                total += len(entry_line)
        return "\n".join(lines)

    def token_estimate(self) -> int:
        return len(self.generate()) // 4


class Layer2:
    """On-demand nodo/celda filtered retrieval."""

    def __init__(self, malla_path: str | None = None, tenant_id: str | None = None) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.malla_path = _resolve_malla_path(tenant_id, malla_path)

    def retrieve(self, nodo: str | None = None, celda: str | None = None, n_results: int = 10) -> str:
        try:
            col = _get_collection(self.malla_path, create=False)
        except Exception:
            return "No malla found."
        where: dict[str, object] = {}
        if nodo and celda:
            where = {"$and": [{"nodo": nodo}, {"celda": celda}]}
        elif nodo:
            where = {"nodo": nodo}
        elif celda:
            where = {"celda": celda}
        kwargs: dict[str, object] = {"include": ["documents", "metadatas"], "limit": n_results}
        if where:
            kwargs["where"] = where
        try:
            res = col.get(**kwargs)  # type: ignore[arg-type]
        except Exception as e:
            return f"Retrieval error: {e}"
        docs = res.documents
        metas = res.metadatas
        if not docs:
            label = f"nodo={nodo}" if nodo else ""
            if celda:
                label += f" celda={celda}" if label else f"celda={celda}"
            return f"No fragmentos found for {label}."
        # Dead fragmentos (superseded / forgotten / quarantined) are history only.
        kept: list[tuple[str, dict[str, object]]] = []
        for doc, meta in zip(docs[:n_results], metas[:n_results]):
            meta = meta or {}
            if not isinstance(meta, dict):
                meta = {}
            if _is_dead_meta(meta):
                continue
            kept.append((doc or "", meta))
        if not kept:
            label = f"nodo={nodo}" if nodo else ""
            if celda:
                label += f" celda={celda}" if label else f"celda={celda}"
            return f"No fragmentos found for {label}."
        lines = [f"## L2 — ON-DEMAND ({len(kept)} fragmentos)"]
        for doc, meta in kept:
            celda_name = str(meta.get("celda", "?"))
            src = meta.get("source_file", "")
            src_name = Path(str(src)).name if isinstance(src, str) and src else ""
            snippet = doc.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            entry = f"  [{celda_name}] {snippet}"
            if src_name:
                entry += f"  ({src_name})"
            lines.append(entry)
        return "\n".join(lines)


class Layer3:
    """Deep search via sqlite hybrid."""

    def __init__(self, malla_path: str | None = None, tenant_id: str | None = None) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.malla_path = _resolve_malla_path(tenant_id, malla_path)

    def search(self, query: str, nodo: str | None = None, celda: str | None = None, n_results: int = 5) -> str:
        from .search import hybrid_search

        try:
            col = _get_collection(self.malla_path, create=False)
        except Exception:
            return "No malla found."
        where: dict[str, object] | None = None
        if nodo and celda:
            where = {"$and": [{"nodo": nodo}, {"celda": celda}]}
        elif nodo:
            where = {"nodo": nodo}
        elif celda:
            where = {"celda": celda}
        res = hybrid_search(col, query, where=where, n_results=n_results)
        hits = res.get("results", [])
        if not hits:
            return "No results found."
        assert isinstance(hits, list)
        lines = [f'## L3 — SEARCH RESULTS for "{query}"']
        for i, hit in enumerate(hits, 1):
            if not isinstance(hit, dict):
                continue
            lines.append(f"  [{i}] {hit.get('nodo', '?')}/{hit.get('celda', '?')} (sim={hit.get('similarity', 0)})")
            txt = str(hit.get("text", ""))[:300]
            lines.append(f"      {txt}")
            src = hit.get("source_file")
            if src:
                lines.append(f"      src: {src}")
        return "\n".join(lines)


class MemoryStack:
    """Unified 4-layer stack. Tenant-aware."""

    def __init__(
        self,
        malla_path: str | None = None,
        identity_path: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.malla_path = _resolve_malla_path(tenant_id, malla_path)
        self.identity_path = _resolve_identity_path(tenant_id, identity_path)
        self.l0 = Layer0(self.identity_path, tenant_id=tenant_id)
        self.l1 = Layer1(self.malla_path, tenant_id=tenant_id)
        self.l2 = Layer2(self.malla_path, tenant_id=tenant_id)
        self.l3 = Layer3(self.malla_path, tenant_id=tenant_id)

    def wake_up(self, nodo: str | None = None) -> str:
        parts: list[str] = []
        parts.append(self.l0.render())
        parts.append("")
        parts.append(self.l1.generate(nodo=nodo))
        return "\n".join(parts)

    def recall(self, nodo: str | None = None, celda: str | None = None, n_results: int = 10) -> str:
        return self.l2.retrieve(nodo=nodo, celda=celda, n_results=n_results)

    def search(self, query: str, nodo: str | None = None, celda: str | None = None, n_results: int = 5) -> str:
        return self.l3.search(query, nodo=nodo, celda=celda, n_results=n_results)

    def status(self) -> dict[str, object]:
        result: dict[str, object] = {
            "malla_path": self.malla_path,
            "L0_identity": {
                "path": self.identity_path,
                "exists": os.path.exists(self.identity_path),
                "tokens": self.l0.token_estimate(),
            },
            "L1_essential": {"description": "Auto-generated from top fragmentos"},
            "L2_on_demand": {"description": "Nodo/celda filtered retrieval"},
            "L3_deep_search": {"description": "Full hybrid search via sqlite"},
        }
        try:
            col = _get_collection(self.malla_path, create=False)
            result["total_fragmentos"] = col.count()
        except Exception:
            result["total_fragmentos"] = 0
        return result
