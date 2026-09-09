"""
DxrkMemory Cortex - Cognitive Engine v3.0
El primer cerebro IA con IQ infinito y aprendizaje autónomo.

Componentes:
- DxrkIQEngine: Motor de IQ vectorial infinito
- UsageBasedIQ: IQ que crece por uso
- GeneticPromptEvolution: Prompts que evolucionan
- MetaLearningEngine: Aprende a aprender mejor
- DreamingMode: Sueño creativo
- AutonomousThinking: Pensamiento en segundo plano
- SelfAwarenessLayer: Autoconsciencia
- SynapticPlasticity: Plasticidad sináptica
- NetworkEffect: Efecto red
- ContributionWeighting: Pesos de contribución
- CollectiveIntelligence: Inteligencia colectiva
"""

from .autonomous_thinking import AutonomousThinking
from .collective_intelligence import CollectiveIntelligence
from .contribution_weighting import ContributionWeighting
from .core import DxrkMemoryCognitiveCore
from .dreaming_mode import DreamingMode
from .genetic_prompts import GeneticPromptEvolution
from .iq_database import IQDatabase
from .iq_engine import DxrkIQEngine
from .meta_learning import MetaLearningEngine
from .network_effect import NetworkEffect
from .self_awareness import SelfAwarenessLayer
from .synapse import SynapseTokenSaver
from .synaptic_plasticity import SynapticPlasticity
from .usage_iq import UsageBasedIQ

__all__ = [
    "CollectiveIntelligence",
    "ContributionWeighting",
    "DxrkIQEngine",
    "DxrkMemoryCognitiveCore",
    "DreamingMode",
    "AutonomousThinking",
    "GeneticPromptEvolution",
    "IQDatabase",
    "MetaLearningEngine",
    "NetworkEffect",
    "SelfAwarenessLayer",
    "SynapseTokenSaver",
    "SynapticPlasticity",
    "UsageBasedIQ",
]

__version__ = "3.0.0"
