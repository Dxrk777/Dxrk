"""
DxrkIQ Engine - Motor de IQ Infinito
El IQ crece sin límites, basado en uso, aprendizaje y evolución.
No tiene techo: puede crecer infinitamente.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class DxrkIQEngine:
    """
    Motor de IQ vectorial infinito.
    Cada dimensión cognitiva puede crecer sin límite.
    El IQ total es un vector multidimensional, no un solo número.

    Dimensiones:
    - logical_reasoning: Razonamiento lógico
    - coding_mastery: Dominio de código
    - knowledge_depth: Profundidad de conocimiento
    - pattern_recognition: Reconocimiento de patrones
    - creative_synthesis: Síntesis creativa
    - strategic_planning: Planificación estratégica
    - self_awareness: Autoconsciencia
    - learning_velocity: Velocidad de aprendizaje
    - emotional_intelligence: Inteligencia emocional
    - abstraction_level: Nivel de abstracción
    - memory_recall: Capacidad de recuerdo
    - problem_solving_speed: Velocidad de resolución
    """

    DIMENSIONS = [
        "logical_reasoning",
        "coding_mastery",
        "knowledge_depth",
        "pattern_recognition",
        "creative_synthesis",
        "strategic_planning",
        "self_awareness",
        "learning_velocity",
        "emotional_intelligence",
        "abstraction_level",
        "memory_recall",
        "problem_solving_speed",
    ]

    def __init__(self, db_path: str = "~/.dxrk/memory/cortex.db"):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        """Inicializa las tablas de la base de datos."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS iq_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dimension TEXT NOT NULL,
                score REAL NOT NULL,
                measured_at TEXT NOT NULL,
                evolution_rate REAL DEFAULT 0,
                acceleration REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_iq_dim ON iq_history(dimension);
            CREATE INDEX IF NOT EXISTS idx_iq_time ON iq_history(measured_at);

            CREATE TABLE IF NOT EXISTS iq_skills_mastered (
                skill_id TEXT PRIMARY KEY,
                dimension TEXT,
                mastery_level REAL DEFAULT 0,
                first_learned TEXT,
                last_practiced TEXT,
                usage_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS iq_global_stats (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_iq REAL DEFAULT 100.0,
                total_interactions INTEGER DEFAULT 0,
                total_users INTEGER DEFAULT 1,
                network_multiplier REAL DEFAULT 1.0,
                learning_velocity REAL DEFAULT 0.1,
                last_updated TEXT
            );

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
            CREATE INDEX IF NOT EXISTS idx_interactions_type ON interactions(interaction_type);

            INSERT OR IGNORE INTO iq_global_stats (id, total_iq, last_updated)
            VALUES (1, 100.0, '');
        """)
        self.conn.commit()

    def measure_current_iq(self) -> dict:
        """
        Mide el IQ actual en todas las dimensiones.
        El IQ se calcula como:
        base (100) + bonus por skills + bonus por conocimiento +
        bonus por velocidad + bonus por interacciones
        """
        iq_vector = {}
        for dim in self.DIMENSIONS:
            base_iq = 100.0
            skills_bonus = self._calculate_skills_bonus(dim)
            knowledge_bonus = self._calculate_knowledge_bonus(dim)
            velocity_bonus = self._calculate_velocity_bonus(dim)
            interaction_bonus = self._calculate_interaction_bonus(dim)
            iq_vector[dim] = base_iq + skills_bonus + knowledge_bonus + velocity_bonus + interaction_bonus

        # IQ total: media geométrica + bonus por especialización
        total_iq = math.prod(iq_vector.values()) ** (1 / len(iq_vector))
        total_iq += max(iq_vector.values()) * 0.1

        return {
            "dimensions": iq_vector,
            "total_iq": round(total_iq, 2),
            "measured_at": datetime.now(UTC).isoformat(),
        }

    def _calculate_skills_bonus(self, dimension: str) -> float:
        """Bonus por skills dominadas en esta dimensión."""
        cursor = self.conn.execute(
            "SELECT SUM(mastery_level) FROM iq_skills_mastered WHERE dimension = ?",
            (dimension,),
        )
        row = cursor.fetchone()
        return math.log1p(row[0] or 0) * 3

    def _calculate_knowledge_bonus(self, dimension: str) -> float:
        """Bonus por conocimiento acumulado."""
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM iq_history WHERE dimension = ?",
            (dimension,),
        )
        count = cursor.fetchone()[0]
        return math.log1p(count) * 2

    def _calculate_velocity_bonus(self, dimension: str) -> float:
        """Bonus por velocidad de aprendizaje."""
        cursor = self.conn.execute(
            "SELECT evolution_rate FROM iq_history WHERE dimension = ? ORDER BY measured_at DESC LIMIT 1",
            (dimension,),
        )
        row = cursor.fetchone()
        if row is None:
            return 0.0
        return (row[0] or 0) * 5

    def _calculate_interaction_bonus(self, dimension: str) -> float:
        """Bonus por interacciones totales."""
        cursor = self.conn.execute("SELECT total_interactions FROM iq_global_stats WHERE id = 1")
        row = cursor.fetchone()
        return math.log1p(row[0] or 0) * 1.5

    def record_iq(self, iq_data: dict):
        """Registra una medición de IQ en el historial."""
        now = datetime.now(UTC).isoformat()
        for dim, score in iq_data["dimensions"].items():
            prev = self._get_latest_score(dim)
            evolution_rate = score - prev if prev else 0
            self.conn.execute(
                "INSERT INTO iq_history (dimension, score, measured_at, evolution_rate) VALUES (?, ?, ?, ?)",
                (dim, score, now, evolution_rate),
            )
        self.conn.execute(
            "UPDATE iq_global_stats SET total_iq = ?, last_updated = ? WHERE id = 1",
            (iq_data["total_iq"], now),
        )
        self.conn.commit()

    def _get_latest_score(self, dimension: str) -> float | None:
        """Obtiene el último score de una dimensión."""
        cursor = self.conn.execute(
            "SELECT score FROM iq_history WHERE dimension = ? ORDER BY measured_at DESC LIMIT 1",
            (dimension,),
        )
        row = cursor.fetchone()
        return float(row[0]) if row else None

    def calculate_evolution_trend(self, days: int = 30) -> dict[str, float]:
        """Calcula la tendencia de evolución del IQ (puntos por día)."""
        trends = {}
        cutoff = datetime.now(UTC).timestamp() - (days * 86400)
        cutoff_str = datetime.fromtimestamp(cutoff, tz=UTC).isoformat()

        for dim in self.DIMENSIONS:
            cursor = self.conn.execute(
                "SELECT score FROM iq_history WHERE dimension = ? AND measured_at > ? ORDER BY measured_at",
                (dim, cutoff_str),
            )
            scores = [row[0] for row in cursor.fetchall()]
            if len(scores) >= 2:
                n = len(scores)
                x = list(range(n))
                sum_x = sum(x)
                sum_y = sum(scores)
                sum_xy = sum(xi * yi for xi, yi in zip(x, scores))
                sum_x2 = sum(xi**2 for xi in x)
                denom = n * sum_x2 - sum_x**2
                slope = (n * sum_xy - sum_x * sum_y) / denom if denom != 0 else 0
                trends[dim] = round(slope, 4)
            else:
                trends[dim] = 0.0
        return trends

    def project_future_iq(self, days_ahead: int = 365) -> dict[str, float]:
        """Proyecta el IQ futuro basado en tendencias actuales."""
        current = self.measure_current_iq()
        trends = self.calculate_evolution_trend()
        projection = {}
        for dim in self.DIMENSIONS:
            current_score = current["dimensions"][dim]
            daily_growth = trends.get(dim, 0.0)
            acceleration_factor = 1.0 + (days_ahead * 0.0001)
            projected = current_score + (daily_growth * days_ahead * acceleration_factor)
            projection[dim] = round(projected, 2)
        return projection

    def get_weakest_dimensions(self, count: int = 3) -> list[str]:
        """Retorna las dimensiones más débiles."""
        current = self.measure_current_iq()
        sorted_dims = sorted(current["dimensions"].items(), key=lambda x: x[1])
        return [dim for dim, _ in sorted_dims[:count]]

    def get_strongest_dimensions(self, count: int = 3) -> list[str]:
        """Retorna las dimensiones más fuertes."""
        current = self.measure_current_iq()
        sorted_dims = sorted(current["dimensions"].items(), key=lambda x: x[1], reverse=True)
        return [dim for dim, _ in sorted_dims[:count]]

    def get_learning_velocity(self) -> float:
        """Retorna la velocidad de aprendizaje (IQ/día)."""
        trends = self.calculate_evolution_trend(days=7)
        return sum(trends.values()) / len(trends) if trends else 0.0

    def add_skill(self, skill_id: str, dimension: str, mastery_level: float = 1.0):
        """Registra una nueva skill dominada."""
        now = datetime.now(UTC).isoformat()
        self.conn.execute(
            """
            INSERT INTO iq_skills_mastered (skill_id, dimension, mastery_level, first_learned, last_practiced, usage_count)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(skill_id) DO UPDATE SET
                mastery_level = mastery_level + ?,
                last_practiced = ?,
                usage_count = usage_count + 1
        """,
            (skill_id, dimension, mastery_level, now, now, mastery_level, now),
        )
        self.conn.commit()

    def get_mastered_skills_count(self) -> int:
        """Retorna el número de skills dominadas."""
        cursor = self.conn.execute("SELECT COUNT(*) FROM iq_skills_mastered")
        return int(cursor.fetchone()[0])

    def close(self):
        """Cierra la conexión a la base de datos."""
        self.conn.close()
