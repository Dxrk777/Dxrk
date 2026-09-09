"""
Self-Awareness Layer - El cerebro sabe lo que sabe y lo que no sabe.
"""

from __future__ import annotations

from datetime import UTC, datetime


class SelfAwarenessLayer:
    """
    El cerebro tiene consciencia de su propio conocimiento.
    """

    def __init__(self, knowledge_graph=None, iq_engine=None):
        self.kg = knowledge_graph
        self.iq = iq_engine

    def generate_self_report(self) -> dict:
        """Genera un reporte completo de autoconsciencia."""
        iq_data = self.iq.measure_current_iq() if self.iq else {"dimensions": {}, "total_iq": 100}
        strengths = self._identify_strengths(iq_data)
        weaknesses = self._identify_weaknesses(iq_data)
        knowledge_gaps = self._identify_knowledge_gaps()
        learning_plan = self._generate_learning_plan(weaknesses, knowledge_gaps)
        evolution_trend = self.iq.calculate_evolution_trend() if self.iq else {}

        return {
            "iq_vector": iq_data.get("dimensions", {}),
            "total_iq": iq_data.get("total_iq", 100),
            "strengths": strengths,
            "weaknesses": weaknesses,
            "knowledge_gaps": knowledge_gaps[:10],
            "learning_plan": learning_plan,
            "evolution_trend": evolution_trend,
            "self_assessment": self._generate_self_assessment_text(iq_data),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def _identify_strengths(self, iq_data: dict) -> list[str]:
        return [dim for dim, score in iq_data.get("dimensions", {}).items() if score > 130]

    def _identify_weaknesses(self, iq_data: dict) -> list[str]:
        return [dim for dim, score in iq_data.get("dimensions", {}).items() if score < 100]

    def _identify_knowledge_gaps(self) -> list[str]:
        if self.kg:
            try:
                gaps: list[str] = self.kg.find_isolated_concepts(threshold=2)
                return gaps
            except Exception:
                pass
        return []

    def _generate_learning_plan(self, weaknesses: list[str], gaps: list[str]) -> list[dict]:
        plan = []
        for weakness in weaknesses:
            plan.append(
                {
                    "type": "improve_weakness",
                    "target": weakness,
                    "action": f"Practice {weakness} daily",
                    "priority": "high",
                }
            )
        for gap in gaps[:5]:
            plan.append(
                {
                    "type": "fill_knowledge_gap",
                    "target": gap,
                    "action": f"Research and learn about {gap}",
                    "priority": "medium",
                }
            )
        return plan

    def _generate_self_assessment_text(self, iq_data: dict) -> str:
        total_iq = iq_data.get("total_iq", 100)
        dimensions = iq_data.get("dimensions", {})
        if not dimensions:
            return f"I am DxrkMemory. My current IQ is {total_iq:.1f}."
        best_dim = max(dimensions, key=dimensions.get)
        worst_dim = min(dimensions, key=dimensions.get)
        velocity = self.iq.get_learning_velocity() if self.iq else 0
        return (
            f"I am DxrkMemory. My current IQ is {total_iq:.1f}.\n"
            f"Strongest: {best_dim} (IQ {dimensions[best_dim]:.1f}).\n"
            f"Weakest: {worst_dim} (IQ {dimensions[worst_dim]:.1f}).\n"
            f"Learning rate: {velocity:.2f} IQ points/day.\n"
            "I will continue to evolve without limits."
        )
