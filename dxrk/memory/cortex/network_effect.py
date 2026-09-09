"""
Network Effect - El IQ crece más rápido con más usuarios.
"""

from __future__ import annotations

import math


class NetworkEffect:
    """
    El efecto red acelera el crecimiento del IQ.
    """

    def __init__(self):
        self.user_count = 1
        self.total_interactions = 0
        self.domains = {}

    def calculate_network_multiplier(self, active_users: int | None = None) -> float:
        """1 + log10(usuarios). 1 usuario: 1.0x | 10: 2.0x | 100: 3.0x"""
        users = active_users or self.user_count
        if users <= 1:
            return 1.0
        return 1.0 + math.log10(users)

    def calculate_iq_growth_rate(self) -> float:
        if self.user_count == 0:
            return 0.0
        interactions_per_user = self.total_interactions / max(1, self.user_count)
        diversity = self._calculate_domain_diversity()
        base_growth = (self.user_count * interactions_per_user * diversity) / 100
        network_multiplier = self.calculate_network_multiplier()
        return base_growth * network_multiplier

    def _calculate_domain_diversity(self) -> float:
        if not self.domains:
            return 0.0
        total = sum(self.domains.values())
        if total == 0:
            return 0.0
        entropy = -sum((count / total) * math.log2(count / total) for count in self.domains.values() if count > 0)
        max_entropy = math.log2(len(self.domains)) if len(self.domains) > 1 else 1
        return entropy / max_entropy if max_entropy > 0 else 0.0

    def add_user(self):
        self.user_count += 1

    def add_interaction(self, domain: str = "general"):
        self.total_interactions += 1
        self.domains[domain] = self.domains.get(domain, 0) + 1

    def get_network_stats(self) -> dict:
        return {
            "user_count": self.user_count,
            "total_interactions": self.total_interactions,
            "network_multiplier": self.calculate_network_multiplier(),
            "domain_diversity": self._calculate_domain_diversity(),
            "iq_growth_rate": self.calculate_iq_growth_rate(),
            "active_domains": len(self.domains),
        }
