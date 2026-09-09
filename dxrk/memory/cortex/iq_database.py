"""
IQ Database - Base de datos para el sistema de IQ.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class IQDatabase:
    """Base de datos completa para el sistema de IQ."""

    def __init__(self, db_path: str = "~/.dxrk/memory/cortex.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                interaction_type TEXT NOT NULL,
                iq_gained REAL NOT NULL,
                complexity_score REAL,
                success BOOLEAN,
                domain TEXT,
                timestamp TEXT NOT NULL,
                details TEXT
            );
            CREATE TABLE IF NOT EXISTS user_iq (
                user_id TEXT PRIMARY KEY,
                total_iq REAL DEFAULT 100.0,
                interactions_count INTEGER DEFAULT 0,
                last_active TEXT
            );
            CREATE TABLE IF NOT EXISTS iq_global_stats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_iq REAL DEFAULT 100.0,
                total_users INTEGER DEFAULT 1,
                total_interactions INTEGER DEFAULT 0,
                network_multiplier REAL DEFAULT 1.0,
                last_updated TEXT
            );
            CREATE TABLE IF NOT EXISTS shared_patterns (
                pattern_hash TEXT PRIMARY KEY,
                domain TEXT,
                success_rate REAL,
                contributor_count INTEGER,
                complexity_score REAL,
                created_at TEXT
            );
            INSERT OR IGNORE INTO iq_global_stats (id, total_iq, last_updated) VALUES (1, 100.0, '');
        """)
        self.conn.commit()

    def record_interaction(
        self,
        user_id: str,
        interaction_type: str,
        iq_gained: float,
        domain: str,
        success: bool = True,
    ):
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT INTO interactions (user_id, interaction_type, iq_gained, domain, success, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (user_id, interaction_type, iq_gained, domain, success, now),
        )
        self.conn.execute(
            """
            INSERT INTO user_iq (user_id, total_iq, interactions_count, last_active)
            VALUES (?, 100 + ?, 1, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                total_iq = total_iq + ?, interactions_count = interactions_count + 1, last_active = ?
        """,
            (user_id, iq_gained, now, iq_gained, now),
        )
        self.conn.execute(
            """
            UPDATE iq_global_stats SET total_iq = total_iq + ?, total_interactions = total_interactions + 1, last_updated = ? WHERE id = 1
        """,
            (iq_gained, now),
        )
        self.conn.commit()

    def get_user_iq(self, user_id: str) -> float:
        cursor = self.conn.execute("SELECT total_iq FROM user_iq WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return float(row[0]) if row else 100.0

    def get_global_iq(self) -> float:
        cursor = self.conn.execute("SELECT total_iq FROM iq_global_stats WHERE id = 1")
        row = cursor.fetchone()
        return float(row[0]) if row else 100.0

    def close(self):
        self.conn.close()
