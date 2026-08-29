# SPDX-License-Identifier: MIT
"""MemoryStack L0-L3 — wake-up stack, stdlib only."""

from __future__ import annotations

import os
import pathlib
from collections import defaultdict
from pathlib import Path

from .backend.base import BaseCollection
from .palace import Palace

# Limits
MAX_SCAN = 2000
MAX_DRAWERS_L1 = 15
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


def _resolve_palace_path(tenant_id: str | None, palace_path: str | None) -> str:
    if palace_path is not None:
        s = str(palace_path).strip()
        if s == "" or s == "memory-only":
            return s
        return str(palace_path)
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return str(tenant_root(tid) / "palace")
        except OSError:
            return str(pathlib.Path.home() / ".dxrk" / "palace")
    try:
        from dxrk.tenant.migration import is_migrated, tenant_root

        if is_migrated():
            return str(tenant_root("default") / "palace")
    except OSError:
        pass
    return str(pathlib.Path.home() / ".dxrk" / "palace")


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


def _get_collection(palace_path: str, *, create: bool = False) -> BaseCollection:
    pal = Palace(palace_path)
    return pal._collection(create=create)  # type: ignore[attr-defined]


class Layer0:
    """Identity — ~100 tokens, always loaded from ~/.dxrk/identity.txt (tenant-aware)."""

    def __init__(
        self, identity_path: str | None = None, tenant_id: str | None = None
    ) -> None:
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
    """Essential story — top drawers, auto-generated, ~500-800 tokens."""

    MAX_DRAWERS: int = MAX_DRAWERS_L1
    MAX_CHARS: int = MAX_CHARS_L1
    MAX_SCAN: int = MAX_SCAN

    def __init__(
        self,
        palace_path: str | None = None,
        wing: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.palace_path = _resolve_palace_path(tenant_id, palace_path)
        self.wing = wing

    def generate(self) -> str:
        try:
            col = _get_collection(self.palace_path, create=False)
        except Exception:
            return "## L1 — No palace found. Run: palace init"
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
            doc = doc or ""
            imp = 3.0
            for key in ("importance", "emotional_weight", "weight"):
                val = meta.get(key)
                if val is not None:
                    try:
                        imp = float(val)  # type: ignore[arg-type]
                    except (ValueError, TypeError):
                        pass
                    break
            scored.append((imp, meta, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self.MAX_DRAWERS]
        by_room: dict[str, list[tuple[float, dict[str, object], str]]] = defaultdict(list)
        for imp, meta, doc in top:
            room = str(meta.get("room", "general")) if isinstance(meta.get("room"), str) else "general"
            by_room[room].append((imp, meta, doc))
        lines: list[str] = ["## L1 — ESSENTIAL STORY"]
        total = 0
        for room, entries in sorted(by_room.items()):
            room_line = f"\n[{room}]"
            lines.append(room_line)
            total += len(room_line)
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
    """On-demand wing/room filtered retrieval."""

    def __init__(self, palace_path: str | None = None, tenant_id: str | None = None) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.palace_path = _resolve_palace_path(tenant_id, palace_path)

    def retrieve(self, wing: str | None = None, room: str | None = None, n_results: int = 10) -> str:
        try:
            col = _get_collection(self.palace_path, create=False)
        except Exception:
            return "No palace found."
        where: dict[str, object] = {}
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}
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
            label = f"wing={wing}" if wing else ""
            if room:
                label += f" room={room}" if label else f"room={room}"
            return f"No drawers found for {label}."
        lines = [f"## L2 — ON-DEMAND ({len(docs)} drawers)"]
        for doc, meta in zip(docs[:n_results], metas[:n_results]):
            meta = meta or {}
            if not isinstance(meta, dict):
                meta = {}
            doc = doc or ""
            room_name = str(meta.get("room", "?"))
            src = meta.get("source_file", "")
            src_name = Path(str(src)).name if isinstance(src, str) and src else ""
            snippet = doc.strip().replace("\n", " ")
            if len(snippet) > 300:
                snippet = snippet[:297] + "..."
            entry = f"  [{room_name}] {snippet}"
            if src_name:
                entry += f"  ({src_name})"
            lines.append(entry)
        return "\n".join(lines)


class Layer3:
    """Deep search via sqlite hybrid."""

    def __init__(
        self, palace_path: str | None = None, tenant_id: str | None = None
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.palace_path = _resolve_palace_path(tenant_id, palace_path)

    def search(self, query: str, wing: str | None = None, room: str | None = None, n_results: int = 5) -> str:
        from .search import hybrid_search

        try:
            col = _get_collection(self.palace_path, create=False)
        except Exception:
            return "No palace found."
        where: dict[str, object] | None = None
        if wing and room:
            where = {"$and": [{"wing": wing}, {"room": room}]}
        elif wing:
            where = {"wing": wing}
        elif room:
            where = {"room": room}
        res = hybrid_search(col, query, where=where, n_results=n_results)
        hits = res.get("results", [])
        if not hits:
            return "No results found."
        assert isinstance(hits, list)
        lines = [f'## L3 — SEARCH RESULTS for "{query}"']
        for i, hit in enumerate(hits, 1):
            if not isinstance(hit, dict):
                continue
            lines.append(f"  [{i}] {hit.get('wing', '?')}/{hit.get('room', '?')} (sim={hit.get('similarity', 0)})")
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
        palace_path: str | None = None,
        identity_path: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        self.palace_path = _resolve_palace_path(tenant_id, palace_path)
        self.identity_path = _resolve_identity_path(tenant_id, identity_path)
        self.l0 = Layer0(self.identity_path, tenant_id=tenant_id)
        self.l1 = Layer1(self.palace_path, tenant_id=tenant_id)
        self.l2 = Layer2(self.palace_path, tenant_id=tenant_id)
        self.l3 = Layer3(self.palace_path, tenant_id=tenant_id)

    def wake_up(self, wing: str | None = None) -> str:
        parts: list[str] = []
        parts.append(self.l0.render())
        parts.append("")
        if wing:
            self.l1.wing = wing
        parts.append(self.l1.generate())
        return "\n".join(parts)

    def recall(self, wing: str | None = None, room: str | None = None, n_results: int = 10) -> str:
        return self.l2.retrieve(wing=wing, room=room, n_results=n_results)

    def search(self, query: str, wing: str | None = None, room: str | None = None, n_results: int = 5) -> str:
        return self.l3.search(query, wing=wing, room=room, n_results=n_results)

    def status(self) -> dict[str, object]:
        result: dict[str, object] = {
            "palace_path": self.palace_path,
            "L0_identity": {
                "path": self.identity_path,
                "exists": os.path.exists(self.identity_path),
                "tokens": self.l0.token_estimate(),
            },
            "L1_essential": {"description": "Auto-generated from top drawers"},
            "L2_on_demand": {"description": "Wing/room filtered retrieval"},
            "L3_deep_search": {"description": "Full hybrid search via sqlite"},
        }
        try:
            col = _get_collection(self.palace_path, create=False)
            result["total_drawers"] = col.count()
        except Exception:
            result["total_drawers"] = 0
        return result
