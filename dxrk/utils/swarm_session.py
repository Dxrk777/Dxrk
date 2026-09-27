# SPDX-License-Identifier: MIT
"""Swarm ↔ session linkage: durable task/result store.

Phase-4 scope is single-host thread-concurrency, so persistence is a
local SQLite sidecar (one file, WAL mode) — not the Phase-3 session
store itself, which owns session payloads. The coordinator records every
submitted task and every completed result here, keyed by ``session_id``,
so resume/summary can show in-flight vs completed swarm work even after
a process restart.

Tables
------

``swarm_tasks`` — one row per submitted task (upsert on re-record).
``swarm_results`` — one row per completed task (upsert).

``SessionSummary`` returns ``{"submitted": n, "completed": n,
"in_flight": n}``; ``SessionSummaryText`` renders one human line for
session resume/summary output.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import timedelta

from dxrk.utils.swarm_model import Task as Task
from dxrk.utils.swarm_model import TaskResult as TaskResult
from dxrk.utils.swarm_model import _now as _now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS swarm_tasks (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    payload BLOB,
    assigned_backend TEXT NOT NULL DEFAULT '',
    retries INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_swarm_tasks_session ON swarm_tasks(session_id);
CREATE TABLE IF NOT EXISTS swarm_results (
    task_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    backend_id TEXT NOT NULL DEFAULT '',
    output BLOB,
    duration_s REAL NOT NULL DEFAULT 0.0,
    timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_swarm_results_session ON swarm_results(session_id);
"""


class SwarmTaskStore:
    """SQLite sidecar persisting swarm tasks and results per session."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = os.path.join(os.path.expanduser("~"), ".dxrk", "swarm_tasks.db")
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, mode=0o700, exist_ok=True)
        self.db_path = db_path
        self._mu = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        with self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.executescript(_SCHEMA)
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass

    def RecordTask(self, task: Task) -> None:
        """Upsert a submitted task row (in-flight until a result lands)."""
        with task._mu:
            snapshot = (
                task.id,
                task.session_id,
                task.type,
                task.payload,
                task.assigned_backend,
                task.retries,
                task.max_retries,
                task.error,
            )
        with self._mu, self._conn:
            self._conn.execute(
                "INSERT INTO swarm_tasks "
                "(task_id, session_id, type, payload, assigned_backend, retries, max_retries, error, completed)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)"
                " ON CONFLICT(task_id) DO UPDATE SET session_id=excluded.session_id,"
                " type=excluded.type, payload=excluded.payload,"
                " assigned_backend=excluded.assigned_backend, retries=excluded.retries,"
                " max_retries=excluded.max_retries, error=excluded.error",
                snapshot,
            )

    def RecordResult(self, result: TaskResult) -> None:
        """Upsert a completed result row and mark its task completed."""
        duration_s = result.duration / timedelta(seconds=1) if result.duration else 0.0
        with self._mu, self._conn:
            self._conn.execute(
                "INSERT INTO swarm_results "
                "(task_id, session_id, backend_id, output, duration_s, timestamp)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(task_id) DO UPDATE SET session_id=excluded.session_id,"
                " backend_id=excluded.backend_id, output=excluded.output,"
                " duration_s=excluded.duration_s, timestamp=excluded.timestamp",
                (
                    result.task_id,
                    result.session_id,
                    result.backend_id,
                    result.output,
                    duration_s,
                    result.timestamp.isoformat() if result.timestamp else "",
                ),
            )
            self._conn.execute("UPDATE swarm_tasks SET completed=1 WHERE task_id=?", (result.task_id,))

    def GetResult(self, task_id: str) -> TaskResult | None:
        """Return the persisted result for a task, if any."""
        with self._mu:
            row = self._conn.execute(
                "SELECT task_id, session_id, backend_id, output, duration_s, timestamp"
                " FROM swarm_results WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskResult(
            task_id=str(row[0]),
            backend_id=str(row[2]),
            output=bytes(row[3]) if row[3] is not None else None,
            session_id=str(row[1]),
            duration=timedelta(seconds=float(row[4] or 0.0)),
            timestamp=_now(),
        )

    def ListSession(self, session_id: str) -> list[TaskResult]:
        """Return persisted results for a session, ordered by task id."""
        with self._mu:
            rows = self._conn.execute(
                "SELECT task_id, session_id, backend_id, output, duration_s"
                " FROM swarm_results WHERE session_id=? ORDER BY task_id",
                (session_id,),
            ).fetchall()
        return [
            TaskResult(
                task_id=str(r[0]),
                backend_id=str(r[2]),
                output=bytes(r[3]) if r[3] is not None else None,
                session_id=str(r[1]),
                duration=timedelta(seconds=float(r[4] or 0.0)),
                timestamp=_now(),
            )
            for r in rows
        ]

    def PendingTasks(self, session_id: str) -> list[str]:
        """Return task ids submitted under a session with no result yet."""
        with self._mu:
            rows = self._conn.execute(
                "SELECT task_id FROM swarm_tasks WHERE session_id=? AND completed=0 ORDER BY task_id",
                (session_id,),
            ).fetchall()
        return [str(r[0]) for r in rows]

    def SessionSummary(self, session_id: str) -> dict[str, int]:
        """Return submitted/completed/in-flight counts for a session."""
        with self._mu:
            submitted = self._conn.execute(
                "SELECT COUNT(*) FROM swarm_tasks WHERE session_id=?", (session_id,)
            ).fetchone()
            completed = self._conn.execute(
                "SELECT COUNT(*) FROM swarm_results WHERE session_id=?", (session_id,)
            ).fetchone()
        n_sub = int(submitted[0]) if submitted else 0
        n_done = int(completed[0]) if completed else 0
        return {"submitted": n_sub, "completed": n_done, "in_flight": max(0, n_sub - n_done)}

    def SessionSummaryText(self, session_id: str) -> str:
        """Render one human line describing a session's swarm work."""
        counts = self.SessionSummary(session_id)
        pending = self.PendingTasks(session_id)
        text = (
            f"session {session_id}: swarm {counts['completed']}/{counts['submitted']} tasks completed"
            f" ({counts['in_flight']} in flight)"
        )
        if pending:
            text += f"; pending: {', '.join(pending)}"
        return text

    def Close(self) -> None:
        """Close the store connection."""
        with self._mu:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass


def NewSwarmTaskStore(db_path: str = "") -> SwarmTaskStore:
    """Create a swarm task store backed by ``db_path``. Mirrors swarm constructors."""
    return SwarmTaskStore(db_path)
