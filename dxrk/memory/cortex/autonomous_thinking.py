"""
Autonomous Thinking - El cerebro piensa en segundo plano.
Reflexiona sobre problemas, planifica estrategias, genera insights.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime


class AutonomousThinking:
    """
    El cerebro piensa en segundo plano sin que el usuario lo pida.
    """

    def __init__(self, memory=None, iq_engine=None):
        self.memory = memory
        self.iq = iq_engine
        self.thinking_enabled = True
        self.thought_log = []

    async def start_background_thinking(self, interval_minutes: int = 30):
        """Inicia el loop de pensamiento autónomo."""
        while self.thinking_enabled:
            await asyncio.sleep(interval_minutes * 60)
            await self._think_cycle()

    async def _think_cycle(self):
        """Un ciclo completo de pensamiento."""
        thought: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "reflections": [],
            "insights": [],
            "plans": [],
        }

        reflections = await self._reflect_on_unsolved_problems()
        thought["reflections"] = reflections

        plans = await self._plan_future_strategies()
        thought["plans"] = plans

        insights = await self._generate_spontaneous_insights()
        thought["insights"] = insights

        self.thought_log.append(thought)

    async def _reflect_on_unsolved_problems(self) -> list[dict]:
        reflections = []
        if self.memory:
            try:
                unsolved = self.memory.get_unresolved_tasks(limit=5)
                for problem in unsolved:
                    solutions = await self._generate_solutions(problem)
                    if solutions:
                        reflections.append(
                            {
                                "problem": problem,
                                "potential_solutions": solutions,
                                "confidence": 0.7,
                            }
                        )
            except Exception:
                pass
        return reflections

    async def _generate_solutions(self, problem: dict) -> list[str]:
        return [
            f"Break down '{problem}' into smaller sub-tasks",
            "Search for similar solved problems in memory",
            "Apply known patterns from related domains",
        ]

    async def _plan_future_strategies(self) -> list[dict]:
        plans = []
        if self.iq:
            weak_areas = self.iq.get_weakest_dimensions(count=2)
            for area in weak_areas:
                plans.append(
                    {
                        "area": area,
                        "strategy": f"Focus practice on {area}",
                        "priority": "high",
                    }
                )
        return plans

    async def _generate_spontaneous_insights(self) -> list[str]:
        return []

    def stop_thinking(self):
        self.thinking_enabled = False

    def get_thinking_stats(self) -> dict:
        total_insights = sum(len(t["insights"]) for t in self.thought_log)
        total_reflections = sum(len(t["reflections"]) for t in self.thought_log)
        return {
            "total_thought_cycles": len(self.thought_log),
            "total_insights": total_insights,
            "total_reflections": total_reflections,
            "is_thinking": self.thinking_enabled,
        }
