"""
Dreaming Mode - El cerebro sueña cuando está inactivo.
Combina conceptos aleatoriamente para generar insights nuevos.
"""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime


class DreamingMode:
    """
    Cuando el agente está inactivo, DxrkMemory 'sueña':
    combina conceptos aleatoriamente para generar insights nuevos,
    como el sueño REM humano.
    """

    def __init__(self, knowledge_graph=None):
        self.kg = knowledge_graph
        self.dream_history = []
        self.is_dreaming = False

    async def dream_cycle(self) -> list[str]:
        """Ejecuta un ciclo de sueño creativo."""
        self.is_dreaming = True
        insights = []

        try:
            random_concepts = self._get_random_concepts(count=10)
            if len(random_concepts) < 2:
                return []

            for i in range(len(random_concepts)):
                for j in range(i + 1, len(random_concepts)):
                    concept_a = random_concepts[i]
                    concept_b = random_concepts[j]

                    if not self._are_connected(concept_a, concept_b):
                        insight = await self._generate_insight(concept_a, concept_b)
                        if insight:
                            insights.append(insight)
                            self._create_connection(concept_a, concept_b, weight=0.1)

            self._consolidate_dream_connections()
            self.dream_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "insights_generated": len(insights),
                    "concepts_combined": len(random_concepts),
                }
            )
        finally:
            self.is_dreaming = False

        return insights

    def _get_random_concepts(self, count: int = 10) -> list[str]:
        if self.kg:
            try:
                concepts: list[str] = self.kg.get_random_concepts(count=count)
                return concepts
            except Exception:
                pass
        return [
            "algorithm",
            "database",
            "network",
            "security",
            "performance",
            "optimization",
            "architecture",
            "testing",
            "deployment",
            "monitoring",
        ]

    def _are_connected(self, concept_a: str, concept_b: str) -> bool:
        if self.kg:
            try:
                connected: bool = self.kg.are_connected(concept_a, concept_b)
                return connected
            except Exception:
                pass
        return False

    def _create_connection(self, concept_a: str, concept_b: str, weight: float = 0.1):
        if self.kg:
            try:
                self.kg.create_connection(concept_a, concept_b, weight=weight)
            except Exception:
                pass

    def _consolidate_dream_connections(self):
        if self.kg:
            try:
                self.kg.consolidate_dream_connections()
            except Exception:
                pass

    async def _generate_insight(self, concept_a: str, concept_b: str) -> str | None:
        templates = [
            f"Applying {concept_a} principles to {concept_b} could yield novel solutions.",
            f"The intersection of {concept_a} and {concept_b} suggests new optimization paths.",
            f"Combining {concept_a} with {concept_b} creates emergent properties.",
            f"Using {concept_a} as a metaphor for {concept_b} reveals hidden patterns.",
        ]
        return random.choice(templates)

    async def schedule_dreaming(self, interval_hours: float = 4.0):
        """Programa sueños periódicos."""
        while True:
            await asyncio.sleep(interval_hours * 3600)
            await self.dream_cycle()

    def get_dream_stats(self) -> dict:
        total_insights = sum(d["insights_generated"] for d in self.dream_history)
        return {
            "total_dreams": len(self.dream_history),
            "total_insights": total_insights,
            "avg_insights_per_dream": total_insights / len(self.dream_history) if self.dream_history else 0,
            "is_currently_dreaming": self.is_dreaming,
        }
