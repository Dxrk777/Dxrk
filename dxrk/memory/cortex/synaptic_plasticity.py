"""
Synaptic Plasticity - Aprendizaje Hebbiano Artificial.
Neuronas que se disparan juntas, se conectan juntas.
"""

from __future__ import annotations


class SynapticPlasticity:
    """
    El Knowledge Graph gana pesos sinápticos dinámicos.
    """

    def __init__(self, knowledge_graph=None):
        self.kg = knowledge_graph
        self.decay_factor = 0.995
        self.strengthen_delta = 0.1

    def update_synaptic_weights(self, current_context: list[str]):
        """Actualiza pesos sinápticos (Regla de Hebb)."""
        if not current_context or len(current_context) < 2:
            return
        for i, concept_a in enumerate(current_context):
            for concept_b in current_context[i + 1 :]:
                if concept_a != concept_b:
                    self._strengthen_connection(concept_a, concept_b)
        self._apply_decay()

    def _strengthen_connection(self, concept_a: str, concept_b: str):
        if self.kg:
            try:
                self.kg.strengthen_connection(concept_a, concept_b, self.strengthen_delta)
            except Exception:
                pass

    def _apply_decay(self):
        if self.kg:
            try:
                self.kg.apply_decay(factor=self.decay_factor)
            except Exception:
                pass

    def get_associative_thoughts(self, current_concept: str, limit: int = 5) -> list[str]:
        if self.kg:
            try:
                conns = self.kg.get_strongest_connections(concept=current_concept, limit=limit)
                return list(conns)
            except Exception:
                pass
        return []

    def get_synaptic_stats(self) -> dict:
        return {
            "decay_factor": self.decay_factor,
            "strengthen_delta": self.strengthen_delta,
            "total_connections": self._get_total_connections(),
            "avg_connection_strength": self._get_avg_strength(),
        }

    def _get_total_connections(self) -> int:
        if self.kg:
            try:
                return int(self.kg.get_total_connections())
            except Exception:
                pass
        return 0

    def _get_avg_strength(self) -> float:
        if self.kg:
            try:
                return float(self.kg.get_avg_connection_strength())
            except Exception:
                pass
        return 0.0
