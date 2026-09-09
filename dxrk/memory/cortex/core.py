"""
DxrkMemory Cognitive Core - Orquestador maestro.
Une todos los sistemas cognitivos en un ciclo continuo.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from .autonomous_thinking import AutonomousThinking
from .collective_intelligence import CollectiveIntelligence
from .contribution_weighting import ContributionWeighting
from .dreaming_mode import DreamingMode
from .genetic_prompts import GeneticPromptEvolution
from .iq_engine import DxrkIQEngine
from .meta_learning import MetaLearningEngine
from .network_effect import NetworkEffect
from .self_awareness import SelfAwarenessLayer
from .synaptic_plasticity import SynapticPlasticity
from .usage_iq import UsageBasedIQ


class DxrkMemoryCognitiveCore:
    """
    El núcleo cognitivo completo de DxrkMemory 3.0.
    Orquesta todos los sistemas cognitivos.
    """

    def __init__(self, memory_engine=None, db_path: str = "~/.dxrk/memory/cortex.db"):
        self.memory = memory_engine
        self.iq_engine = DxrkIQEngine(db_path=db_path)
        self.usage_iq = UsageBasedIQ(self.iq_engine.conn)
        self.genetic = GeneticPromptEvolution()
        self.meta_learning = MetaLearningEngine()
        self.dreaming = DreamingMode(knowledge_graph=getattr(memory_engine, "knowledge_graph", None))
        self.autonomous_thinking = AutonomousThinking(memory=memory_engine, iq_engine=self.iq_engine)
        self.self_awareness = SelfAwarenessLayer(
            knowledge_graph=getattr(memory_engine, "knowledge_graph", None),
            iq_engine=self.iq_engine,
        )
        self.synaptic = SynapticPlasticity(knowledge_graph=getattr(memory_engine, "knowledge_graph", None))
        self.network = NetworkEffect()
        self.weighting = ContributionWeighting()
        self.collective = CollectiveIntelligence()
        self.cognitive_loop_active = False

    async def start_cognitive_loop(self):
        """Inicia el ciclo cognitivo completo."""
        self.cognitive_loop_active = True
        tasks = [
            asyncio.create_task(self.autonomous_thinking.start_background_thinking()),
            asyncio.create_task(self.dreaming.schedule_dreaming()),
            asyncio.create_task(self._evolution_cycle()),
            asyncio.create_task(self._iq_measurement_cycle()),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    def stop_cognitive_loop(self):
        self.cognitive_loop_active = False
        self.autonomous_thinking.stop_thinking()

    async def _evolution_cycle(self):
        while self.cognitive_loop_active:
            await asyncio.sleep(24 * 3600)
            performance = self.meta_learning.learning_history[-10:]
            await self.meta_learning.optimize_learning_pipeline(performance)

    async def _iq_measurement_cycle(self):
        while self.cognitive_loop_active:
            await asyncio.sleep(6 * 3600)
            iq_data = self.iq_engine.measure_current_iq()
            self.iq_engine.record_iq(iq_data)

    def record_interaction(
        self,
        interaction_type: str,
        complexity_score: float = 1.0,
        success: bool = True,
        domain: str | None = None,
    ) -> float:
        """Registra una interacción y actualiza el IQ."""
        iq_gained = self.usage_iq.record_interaction(
            interaction_type=interaction_type,
            complexity_score=complexity_score,
            success=success,
            domain=domain,
        )
        self.network.add_interaction(domain=domain or "general")
        return iq_gained

    def get_cognitive_status(self) -> dict:
        """Retorna el estado cognitivo completo."""
        iq_data = self.iq_engine.measure_current_iq()
        self_report = self.self_awareness.generate_self_report()
        return {
            "iq": iq_data,
            "evolution_rate": self.iq_engine.calculate_evolution_trend(),
            "self_awareness": self_report.get("self_assessment", ""),
            "learning_velocity": self.iq_engine.get_learning_velocity(),
            "skills_mastered": self.iq_engine.get_mastered_skills_count(),
            "network_stats": self.network.get_network_stats(),
            "dreaming_stats": self.dreaming.get_dream_stats(),
            "thinking_stats": self.autonomous_thinking.get_thinking_stats(),
            "meta_learning_stats": self.meta_learning.get_meta_learning_stats(),
            "synaptic_stats": self.synaptic.get_synaptic_stats(),
            "collective_stats": self.collective.get_collective_stats(),
            "status_timestamp": datetime.now(UTC).isoformat(),
        }

    def get_iq_report(self) -> dict:
        return {
            "current_iq": self.iq_engine.measure_current_iq(),
            "evolution_trend": self.iq_engine.calculate_evolution_trend(),
            "projection_1year": self.iq_engine.project_future_iq(365),
            "weakest_dimensions": self.iq_engine.get_weakest_dimensions(),
            "strongest_dimensions": self.iq_engine.get_strongest_dimensions(),
            "learning_velocity": self.iq_engine.get_learning_velocity(),
        }
