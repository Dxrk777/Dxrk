"""
Usage-Based IQ - El IQ crece por USO, no por tiempo.
Cada interacción tiene un peso basado en su complejidad y novedad.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime


class UsageBasedIQ:
    """
    Motor de IQ basado en uso.
    Cada interacción suma puntos de IQ según su complejidad.

    Pesos por tipo de interacción:
    - read_file: 0.1
    - write_file: 0.5
    - debug_error: 3.0
    - solve_novel_problem: 10.0
    - design_architecture: 5.0
    """

    INTERACTION_WEIGHTS = {
        "read_file": 0.1,
        "list_directory": 0.05,
        "search_text": 0.2,
        "write_file": 0.5,
        "edit_file": 0.8,
        "run_tests": 1.0,
        "execute_command": 0.7,
        "debug_error": 3.0,
        "refactor_code": 2.5,
        "design_architecture": 5.0,
        "solve_novel_problem": 10.0,
        "learn_new_library": 4.0,
        "read_documentation": 1.5,
        "research_solution": 2.0,
        "share_insight": 5.0,
        "validate_insight": 2.0,
        "correct_mistake": 3.0,
        "create_skill": 4.0,
        "teach_agent": 6.0,
    }

    def __init__(self, db_conn):
        self.conn = db_conn
        self.total_interactions = 0
        self.total_iq_gained = 0.0
        self._seen_interactions = set()

    def record_interaction(
        self,
        interaction_type: str,
        complexity_score: float = 1.0,
        success: bool = True,
        user_id: str | None = None,
        domain: str | None = None,
        details: dict | None = None,
    ) -> float:
        """
        Registra una interacción y calcula cuánto IQ aporta.

        Args:
            interaction_type: Tipo de interacción
            complexity_score: Complejidad (0.5 a 3.0)
            success: Si fue exitosa
            user_id: ID del usuario
            domain: Dominio (python, web, etc.)
            details: Detalles adicionales

        Returns:
            Puntos de IQ ganados
        """
        base_weight = self.INTERACTION_WEIGHTS.get(interaction_type, 0.5)
        complexity_multiplier = min(3.0, max(0.5, complexity_score))
        success_multiplier = 1.0 if success else 0.3
        novelty_multiplier = self._calculate_novelty_bonus(interaction_type, details)

        iq_gained = base_weight * complexity_multiplier * success_multiplier * novelty_multiplier

        self._store_interaction(
            interaction_type=interaction_type,
            iq_gained=iq_gained,
            complexity=complexity_score,
            success=success,
            user_id=user_id,
            domain=domain,
            details=details,
        )

        self.total_interactions += 1
        self.total_iq_gained += iq_gained
        return round(iq_gained, 3)

    def _calculate_novelty_bonus(self, interaction_type: str, details: dict | None) -> float:
        """Bonus por novedad: si es algo nunca visto, vale 5x más."""
        interaction_hash = hashlib.md5(f"{interaction_type}:{details!s}".encode()).hexdigest()[:8]

        if interaction_hash not in self._seen_interactions:
            self._seen_interactions.add(interaction_hash)
            return 5.0
        elif len(self._seen_interactions) > 100:
            return 1.5
        return 1.0

    def _store_interaction(self, **kwargs):
        """Almacena la interacción en la base de datos."""
        now = datetime.now(UTC).isoformat()
        try:
            self.conn.execute(
                """
                INSERT INTO interactions
                (user_id, interaction_type, iq_gained, complexity_score, success, domain, timestamp, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    kwargs.get("user_id"),
                    kwargs["interaction_type"],
                    kwargs["iq_gained"],
                    kwargs["complexity"],
                    kwargs["success"],
                    kwargs.get("domain"),
                    now,
                    str(kwargs.get("details", {})),
                ),
            )
            self.conn.execute(
                """
                UPDATE iq_global_stats
                SET total_interactions = total_interactions + 1, last_updated = ?
                WHERE id = 1
            """,
                (now,),
            )
            self.conn.commit()
        except Exception:
            pass

    def calculate_current_iq(self) -> dict:
        """Calcula el IQ actual basado en todas las interacciones."""
        base_iq = 100.0
        interaction_bonus = math.log1p(self.total_interactions) * 5
        iq_bonus = self.total_iq_gained * 0.1
        diversity_bonus = self._calculate_diversity_bonus()
        complexity_bonus = self._calculate_complexity_bonus()

        total_iq = base_iq + interaction_bonus + iq_bonus + diversity_bonus + complexity_bonus

        return {
            "total_iq": round(total_iq, 2),
            "interactions_count": self.total_interactions,
            "iq_gained": round(self.total_iq_gained, 2),
            "diversity_score": round(diversity_bonus, 2),
            "complexity_score": round(complexity_bonus, 2),
        }

    def _calculate_diversity_bonus(self) -> float:
        """Bonus por diversidad de interacciones."""
        try:
            cursor = self.conn.execute("SELECT COUNT(DISTINCT interaction_type) FROM interactions")
            unique_types = cursor.fetchone()[0]
            return math.log1p(unique_types) * 3
        except Exception:
            return 0.0

    def _calculate_complexity_bonus(self) -> float:
        """Bonus por complejidad promedio."""
        try:
            cursor = self.conn.execute("SELECT AVG(complexity_score) FROM interactions")
            avg_complexity = cursor.fetchone()[0] or 1.0
            return avg_complexity * 2
        except Exception:
            return 2.0

    def get_interaction_history(self, limit: int = 100) -> list[dict]:
        """Retorna el historial de interacciones."""
        try:
            cursor = self.conn.execute(
                "SELECT * FROM interactions ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except Exception:
            return []
