# SPDX-License-Identifier: MIT
"""Temporal knowledge graph — sqlite WAL, stdlib only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, date, datetime
from pathlib import Path

DEFAULT_KG_PATH = str(Path.home() / ".dxrk" / "knowledge_graph.sqlite3")


def _effective_tenant_id(tenant_id: str | None = None) -> str:
    import os

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


def _resolve_kg_path(tenant_id: str | None, db_path: str | None) -> str:
    if db_path is not None:
        s = str(db_path).strip()
        if s == "" or s == "memory-only":
            return s
        return s
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return str(tenant_root(tid) / "knowledge_graph.sqlite3")
        except OSError:
            return DEFAULT_KG_PATH
    try:
        from dxrk.tenant.migration import is_migrated, tenant_root

        if is_migrated():
            return str(tenant_root("default") / "knowledge_graph.sqlite3")
    except OSError:
        pass
    return DEFAULT_KG_PATH


def _sanitize_iso(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    # allow YYYY-MM-DD or ISO datetime
    try:
        # try parse date only
        if len(v) == 10 and v[4] == "-" and v[7] == "-":
            datetime.strptime(v, "%Y-%m-%d")
            return v
        # try iso datetime
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v
    except ValueError as e:
        raise ValueError(f"invalid {field} {value!r}: {e}") from e


def _is_date_only(v: str | None) -> bool:
    return isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-"


def _start_key(v: str | None) -> str | None:
    if v is None:
        return None
    if _is_date_only(v):
        return f"{v}T00:00:00Z"
    return v


def _end_key(v: str | None) -> str | None:
    if v is None:
        return None
    if _is_date_only(v):
        return f"{v}T23:59:59Z"
    return v


def _sql_start_expr(col: str) -> str:
    return f"CASE WHEN length({col})=10 AND substr({col},5,1)='-' AND substr({col},8,1)='-' THEN {col}||'T00:00:00Z' ELSE {col} END"


def _sql_end_expr(col: str) -> str:
    return f"CASE WHEN length({col})=10 AND substr({col},5,1)='-' AND substr({col},8,1)='-' THEN {col}||'T23:59:59Z' ELSE {col} END"


def _temporal_filter_sql(as_of: str) -> tuple[str, list[str]]:
    key = _start_key(as_of) or as_of
    return (
        f" AND (t.valid_from IS NULL OR {_sql_start_expr('t.valid_from')} <= ?) AND (t.valid_to IS NULL OR {_sql_end_expr('t.valid_to')} >= ?)",
        [key, key],
    )


class KnowledgeGraph:
    """SQLite-backed temporal KG. Tenant-aware via ~/.dxrk/tenants/{id}/ ."""

    def __init__(self, db_path: str | None = None, tenant_id: str | None = None) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        resolved = _resolve_kg_path(tenant_id, db_path)
        self.db_path = resolved if resolved else DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        try:
            Path(self.db_path).parent.chmod(0o700 if Path(self.db_path).parent == Path.home() / ".dxrk" else 0o750)
        except OSError:
            pass
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._conn_or_create()
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL DEFAULT 1.0,
                source_closet TEXT,
                source_file TEXT,
                source_drawer_id TEXT,
                adapter_name TEXT,
                extracted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );
            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
            CREATE INDEX IF NOT EXISTS idx_triples_valid ON triples(valid_from, valid_to);
            """
        )
        # migrate older schema: add missing columns
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(triples)").fetchall()}
            if "source_drawer_id" not in cols:
                conn.execute("ALTER TABLE triples ADD COLUMN source_drawer_id TEXT")
            if "adapter_name" not in cols:
                conn.execute("ALTER TABLE triples ADD COLUMN adapter_name TEXT")
        except sqlite3.Error:
            pass
        conn.commit()
        try:
            Path(self.db_path).chmod(0o600)
        except OSError:
            pass

    def _conn_or_create(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    def __enter__(self) -> KnowledgeGraph:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
        return None

    def _eid(self, name: str) -> str:
        return name.lower().replace(" ", "_").replace("'", "")

    def add_entity(self, name: str, entity_type: str = "unknown", properties: dict[str, object] | None = None) -> str:
        eid = self._eid(name)
        props = json.dumps(properties or {}, ensure_ascii=False)
        with self._lock:
            conn = self._conn_or_create()
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO entities (id, name, type, properties) VALUES (?,?,?,?)",
                    (eid, name, entity_type, props),
                )
        return eid

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_closet: str | None = None,
        source_file: str | None = None,
        source_drawer_id: str | None = None,
        adapter_name: str | None = None,
    ) -> str:
        valid_from = _sanitize_iso(valid_from, "valid_from")
        valid_to = _sanitize_iso(valid_to, "valid_to")
        if (
            valid_from is not None
            and valid_to is not None
            and (_end_key(valid_to) or "") < (_start_key(valid_from) or "")
        ):
            raise ValueError(f"valid_to {valid_to!r} before valid_from {valid_from!r}")
        sub_id = self._eid(subject)
        obj_id = self._eid(obj)
        pred = predicate.lower().replace(" ", "_")
        with self._lock:
            conn = self._conn_or_create()
            with conn:
                conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?,?)", (sub_id, subject))
                conn.execute("INSERT OR IGNORE INTO entities (id, name) VALUES (?,?)", (obj_id, obj))
                existing = conn.execute(
                    "SELECT id FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (sub_id, pred, obj_id),
                ).fetchone()
                if existing:
                    return str(existing["id"])
                tid = f"t_{sub_id}_{pred}_{obj_id}_{hashlib.sha256(f'{valid_from}{datetime.now(UTC).isoformat()}'.encode()).hexdigest()[:12]}"
                conn.execute(
                    "INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to, confidence, source_closet, source_file, source_drawer_id, adapter_name) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        tid,
                        sub_id,
                        pred,
                        obj_id,
                        valid_from,
                        valid_to,
                        confidence,
                        source_closet,
                        source_file,
                        source_drawer_id,
                        adapter_name,
                    ),
                )
                return tid

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str | None = None) -> None:
        sub_id = self._eid(subject)
        obj_id = self._eid(obj)
        pred = predicate.lower().replace(" ", "_")
        ended = _sanitize_iso(ended or date.today().isoformat(), "ended")
        with self._lock:
            conn = self._conn_or_create()
            with conn:
                rows = conn.execute(
                    "SELECT id, valid_from FROM triples WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (sub_id, pred, obj_id),
                ).fetchall()
                for r in rows:
                    vf = r["valid_from"]
                    if vf is not None and (_end_key(ended) or "") < (_start_key(vf) or ""):
                        raise ValueError(f"valid_to {ended!r} before valid_from {vf!r}")
                conn.execute(
                    "UPDATE triples SET valid_to=? WHERE subject=? AND predicate=? AND object=? AND valid_to IS NULL",
                    (ended, sub_id, pred, obj_id),
                )

    def query_entity(self, name: str, as_of: str | None = None, direction: str = "outgoing") -> list[dict[str, object]]:
        as_of = _sanitize_iso(as_of, "as_of") if as_of else None  # type: ignore[assignment]
        eid = self._eid(name)
        results: list[dict[str, object]] = []
        temporal_sql = ""
        temporal_params: list[str] = []
        if as_of:
            temporal_sql, temporal_params = _temporal_filter_sql(as_of)
        with self._lock:
            conn = self._conn_or_create()
            if direction in ("outgoing", "both"):
                q = (
                    "SELECT t.*, e.name as obj_name FROM triples t JOIN entities e ON t.object=e.id WHERE t.subject=?"
                    + temporal_sql
                )
                params: list[str] = [eid, *temporal_params]
                for row in conn.execute(q, params).fetchall():
                    results.append(
                        {
                            "direction": "outgoing",
                            "subject": name,
                            "predicate": row["predicate"],
                            "object": row["obj_name"],
                            "valid_from": row["valid_from"],
                            "valid_to": row["valid_to"],
                            "confidence": row["confidence"],
                            "source_closet": row["source_closet"],
                            "current": row["valid_to"] is None,
                        }
                    )
            if direction in ("incoming", "both"):
                q = (
                    "SELECT t.*, e.name as sub_name FROM triples t JOIN entities e ON t.subject=e.id WHERE t.object=?"
                    + temporal_sql
                )
                params = [eid, *temporal_params]
                for row in conn.execute(q, params).fetchall():
                    results.append(
                        {
                            "direction": "incoming",
                            "subject": row["sub_name"],
                            "predicate": row["predicate"],
                            "object": name,
                            "valid_from": row["valid_from"],
                            "valid_to": row["valid_to"],
                            "confidence": row["confidence"],
                            "source_closet": row["source_closet"],
                            "current": row["valid_to"] is None,
                        }
                    )
        return results

    def query_relationship(self, predicate: str, as_of: str | None = None) -> list[dict[str, object]]:
        as_of = _sanitize_iso(as_of, "as_of") if as_of else None  # type: ignore[assignment]
        pred = predicate.lower().replace(" ", "_")
        q = "SELECT t.*, s.name as sub_name, o.name as obj_name FROM triples t JOIN entities s ON t.subject=s.id JOIN entities o ON t.object=o.id WHERE t.predicate=?"
        params: list[str] = [pred]
        if as_of:
            ts, tp = _temporal_filter_sql(as_of)
            q += ts
            params.extend(tp)
        results: list[dict[str, object]] = []
        with self._lock:
            conn = self._conn_or_create()
            for row in conn.execute(q, params).fetchall():
                results.append(
                    {
                        "subject": row["sub_name"],
                        "predicate": pred,
                        "object": row["obj_name"],
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "current": row["valid_to"] is None,
                    }
                )
        return results

    def timeline(self, entity_name: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            conn = self._conn_or_create()
            if entity_name:
                eid = self._eid(entity_name)
                rows = conn.execute(
                    "SELECT t.*, s.name as sub_name, o.name as obj_name FROM triples t JOIN entities s ON t.subject=s.id JOIN entities o ON t.object=o.id WHERE (t.subject=? OR t.object=?) ORDER BY t.valid_from ASC LIMIT 100",
                    (eid, eid),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT t.*, s.name as sub_name, o.name as obj_name FROM triples t JOIN entities s ON t.subject=s.id JOIN entities o ON t.object=o.id ORDER BY t.valid_from ASC LIMIT 100"
                ).fetchall()
        return [
            {
                "subject": r["sub_name"],
                "predicate": r["predicate"],
                "object": r["obj_name"],
                "valid_from": r["valid_from"],
                "valid_to": r["valid_to"],
                "current": r["valid_to"] is None,
            }
            for r in rows
        ]

    def traverse(self, start: str, depth: int = 2, as_of: str | None = None) -> list[dict[str, object]]:
        """BFS traverse from start entity up to depth hops (temporal filtered if as_of set)."""
        visited: set[str] = set()
        frontier: list[tuple[str, int]] = [(start, 0)]
        out: list[dict[str, object]] = []
        while frontier:
            cur, d = frontier.pop(0)
            if cur in visited or d > depth:
                continue
            visited.add(cur)
            edges = self.query_entity(cur, as_of=as_of, direction="outgoing")
            for e in edges:
                out.append(e)
                obj = str(e.get("object", ""))
                if obj not in visited and d + 1 <= depth:
                    frontier.append((obj, d + 1))
        return out

    def stats(self) -> dict[str, object]:
        with self._lock:
            conn = self._conn_or_create()
            entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
            current = conn.execute("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL").fetchone()[0]
            expired = triples - current
            preds = [r[0] for r in conn.execute("SELECT DISTINCT predicate FROM triples ORDER BY predicate").fetchall()]
        return {
            "entities": entities,
            "triples": triples,
            "current_facts": current,
            "expired_facts": expired,
            "relationship_types": preds,
        }
