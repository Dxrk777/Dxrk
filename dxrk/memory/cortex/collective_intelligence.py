"""
Collective Intelligence - Cerebro colectivo federado.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


@dataclass
class FederatedInsight:
    insight_type: str
    pattern_hash: str
    success_rate: float
    complexity_score: float
    domain: str
    contributor_count: int = 1


class CollectiveIntelligence:
    """Cerebro colectivo: cada usuario contribuye anónimamente."""

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url
        self.local_insights: list[FederatedInsight] = []
        self.global_iq_multiplier = 1.0
        self.local_iq = 100.0

    def create_insight(
        self,
        insight_type: str,
        pattern_data: str,
        success_rate: float,
        complexity_score: float,
        domain: str,
    ) -> FederatedInsight:
        pattern_hash = hashlib.sha256(pattern_data.encode()).hexdigest()[:16]
        return FederatedInsight(
            insight_type=insight_type,
            pattern_hash=pattern_hash,
            success_rate=success_rate,
            complexity_score=complexity_score,
            domain=domain,
        )

    def add_local_insight(self, insight: FederatedInsight):
        self.local_insights.append(insight)

    def calculate_network_multiplier(self, active_users: int) -> float:
        if active_users <= 1:
            return 1.0
        return 1.0 + math.log10(active_users)

    def get_collective_stats(self) -> dict:
        return {
            "local_insights_count": len(self.local_insights),
            "global_iq_multiplier": self.global_iq_multiplier,
            "local_iq": self.local_iq,
            "effective_iq": self.local_iq * self.global_iq_multiplier,
            "domains_covered": list({i.domain for i in self.local_insights}),
        }
