"""
Meta-Learning Engine - Aprende a aprender mejor.
Analiza qué estrategias de aprendizaje funcionan y las refuerza.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime


class MetaLearningEngine:
    """
    El cerebro aprende a aprender mejor.
    Usa UCB1 (Upper Confidence Bound) para balancear exploración/explotación.
    """

    LEARNING_STRATEGIES = [
        "repetition_spaced",
        "active_recall",
        "interleaving",
        "elaboration",
        "self_explanation",
        "dual_coding",
        "chunking",
        "mind_mapping",
        "practice_testing",
        "reflective_journaling",
    ]

    def __init__(self):
        self.strategy_effectiveness = {s: 0.5 for s in self.LEARNING_STRATEGIES}
        self.strategy_attempts = {s: 0 for s in self.LEARNING_STRATEGIES}
        self.total_attempts = 0
        self.learning_history = []

    def record_learning_attempt(
        self,
        strategy: str,
        success_rate: float,
        time_spent_minutes: float,
        topic: str | None = None,
    ):
        """Registra un intento de aprendizaje."""
        if strategy not in self.strategy_effectiveness:
            self.strategy_effectiveness[strategy] = 0.5
            self.strategy_attempts[strategy] = 0

        current = self.strategy_effectiveness[strategy]
        alpha = 0.1
        self.strategy_effectiveness[strategy] = (1 - alpha) * current + alpha * success_rate
        self.strategy_attempts[strategy] += 1
        self.total_attempts += 1

        self.learning_history.append(
            {
                "strategy": strategy,
                "success_rate": success_rate,
                "time_spent": time_spent_minutes,
                "topic": topic,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def get_optimal_learning_strategy(self, topic: str | None = None) -> str:
        """Retorna la estrategia óptima usando UCB1."""
        best_strategy = None
        best_score: float = -1

        for strategy in self.LEARNING_STRATEGIES:
            effectiveness = self.strategy_effectiveness[strategy]
            attempts = self.strategy_attempts[strategy]

            if attempts == 0:
                exploration_bonus = float("inf")
            else:
                exploration_bonus = math.sqrt(2 * math.log(self.total_attempts + 1) / attempts)

            score = effectiveness + exploration_bonus
            if score > best_score:
                best_score = score
                best_strategy = strategy

        return best_strategy or random.choice(self.LEARNING_STRATEGIES)

    async def optimize_learning_pipeline(self, recent_performance: list[dict]):
        """Optimiza el pipeline de aprendizaje."""
        successful = [r["strategy"] for r in recent_performance if r.get("success_rate", 0) > 0.8]
        failed = [r["strategy"] for r in recent_performance if r.get("success_rate", 0) < 0.3]

        for strategy in successful:
            if strategy in self.strategy_effectiveness:
                self.strategy_effectiveness[strategy] = min(1.0, self.strategy_effectiveness[strategy] * 1.1)

        for strategy in failed:
            if strategy in self.strategy_effectiveness:
                self.strategy_effectiveness[strategy] = max(0.1, self.strategy_effectiveness[strategy] * 0.9)

    def get_strategy_rankings(self) -> list[dict]:
        """Retorna ranking de estrategias."""
        rankings: list[dict] = []
        for strategy, effectiveness in self.strategy_effectiveness.items():
            rankings.append(
                {
                    "strategy": strategy,
                    "effectiveness": effectiveness,
                    "attempts": self.strategy_attempts[strategy],
                }
            )
        rankings.sort(key=lambda x: x["effectiveness"], reverse=True)
        return rankings

    def get_meta_learning_stats(self) -> dict:
        """Retorna estadísticas."""
        return {
            "total_attempts": self.total_attempts,
            "best_strategy": self.get_optimal_learning_strategy(),
            "strategy_rankings": self.get_strategy_rankings()[:5],
            "learning_velocity": self._calculate_learning_velocity(),
        }

    def _calculate_learning_velocity(self) -> float:
        if len(self.learning_history) < 2:
            return 0.0
        recent = self.learning_history[-10:]
        return float(sum(r["success_rate"] for r in recent) / len(recent))
