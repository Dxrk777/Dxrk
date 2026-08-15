# SPDX-License-Identifier: MIT
"""Cost optimization with budget tracking and provider scoring"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .router import DEFAULT_COSTS, Capability, ProviderEntry, Router, SemanticCache
from .strconst import StrCritical

_logger = logging.getLogger("dxrk.costopt")

MAX_ALERTS = 100


@dataclass
class BudgetConfig:
    daily_limit_usd: float = 0.0
    monthly_limit_usd: float = 0.0
    alert_threshold: float = 0.0
    auto_switch: bool = False
    preferred_models: List[str] = field(default_factory=list)


@dataclass
class Alert:
    timestamp: float
    level: str
    message: str
    current: float
    limit: float


@dataclass
class ProviderScore:
    name: str
    model: str
    cost_per_1k_tokens: float
    latency_ms: int
    success_rate: float
    score: float


@dataclass
class BudgetStatus:
    daily_spent: float
    daily_limit: float
    daily_percent: float
    monthly_spent: float
    monthly_limit: float
    monthly_percent: float
    alerts: List[Alert]
    cache_hit_rate: float


class CostOptimizer:
    """Tracks spend against budgets and scores providers for selection."""

    def __init__(
        self,
        router: Router,
        cache: Optional[SemanticCache],
        budget: BudgetConfig,
        path: str,
    ) -> None:
        self.router = router
        self.cache = cache
        self.budget = budget
        self.path = path
        self.daily_spent: float = 0.0
        self.monthly_spent: float = 0.0
        self.last_reset: datetime = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        self.alerts: List[Alert] = []
        self._mu = threading.RLock()
        self._load()

    def record_usage(self, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._mu:
            cost = self._calculate_cost(model, input_tokens, output_tokens)
            self.daily_spent += cost
            self.monthly_spent += cost
            self._check_budget()
            self._save()

    def _calculate_cost(self, model: str, in_tokens: int, out_tokens: int) -> float:
        cfg = DEFAULT_COSTS.get(model)
        if cfg is None:
            return 0.0
        return (in_tokens / 1000.0) * cfg.input_price_per_1k + (
            out_tokens / 1000.0
        ) * cfg.output_price_per_1k

    def _check_budget(self) -> None:
        if self.budget.daily_limit_usd > 0 and (
            self.daily_spent
            >= self.budget.daily_limit_usd * self.budget.alert_threshold
        ):
            self.alerts.append(
                Alert(
                    timestamp=time.time(),
                    level="warning",
                    message=f"Daily budget at {self.daily_spent / self.budget.daily_limit_usd * 100:.0f}%",
                    current=self.daily_spent,
                    limit=self.budget.daily_limit_usd,
                )
            )
        if self.budget.monthly_limit_usd > 0 and (
            self.monthly_spent
            >= self.budget.monthly_limit_usd * self.budget.alert_threshold
        ):
            self.alerts.append(
                Alert(
                    timestamp=time.time(),
                    level=StrCritical,
                    message=f"Monthly budget at {self.monthly_spent / self.budget.monthly_limit_usd * 100:.0f}%",
                    current=self.monthly_spent,
                    limit=self.budget.monthly_limit_usd,
                )
            )
        if len(self.alerts) > MAX_ALERTS:
            self.alerts = self.alerts[-MAX_ALERTS:]

    def select_best_provider(self, required_caps: List[Capability]) -> ProviderEntry:
        with self._mu:
            best: Optional[ProviderEntry] = None
            best_score = 0.0
            for p in self.router.providers:
                if not self._has_capabilities(p, required_caps):
                    continue
                score = self._score_provider(p)
                if best is None or score > best_score:
                    best = p
                    best_score = score
            if best is None:
                raise ValueError("no provider matches capabilities")
            return best

    def _has_capabilities(self, p: ProviderEntry, req: List[Capability]) -> bool:
        if len(req) == 0:
            return True
        has = set(p.capabilities)
        return all(r in has for r in req)

    def _score_provider(self, p: ProviderEntry) -> float:
        cfg = DEFAULT_COSTS.get(p.model)
        if cfg is None:
            return 0.0
        cost = cfg.input_price_per_1k
        latency = 100.0
        success = 1.0
        if self.cache is not None:
            st = self.cache.stats()
            if st.size > 0:
                success *= 0.9 + 0.1 * float(st.hits) / float(st.size + 1)
        return (
            (1.0 / (cost + 0.0001)) * 0.5 + (1.0 / (latency + 1)) * 0.3 + success * 0.2
        )

    def get_budget_status(self) -> BudgetStatus:
        with self._mu:
            daily_pct = 0.0
            if self.budget.daily_limit_usd > 0:
                daily_pct = self.daily_spent / self.budget.daily_limit_usd * 100
            monthly_pct = 0.0
            if self.budget.monthly_limit_usd > 0:
                monthly_pct = self.monthly_spent / self.budget.monthly_limit_usd * 100
            return BudgetStatus(
                daily_spent=self.daily_spent,
                daily_limit=self.budget.daily_limit_usd,
                daily_percent=daily_pct,
                monthly_spent=self.monthly_spent,
                monthly_limit=self.budget.monthly_limit_usd,
                monthly_percent=monthly_pct,
                alerts=list(self.alerts),
                cache_hit_rate=self._cache_hit_rate(),
            )

    def _cache_hit_rate(self) -> float:
        if self.cache is None:
            return 0.0
        st = self.cache.stats()
        if st.size == 0:
            return 0.0
        return float(st.hits) / float(st.size)

    def get_provider_scores(self) -> List[ProviderScore]:
        with self._mu:
            scores: List[ProviderScore] = []
            for p in self.router.providers:
                cfg = DEFAULT_COSTS.get(p.model)
                if cfg is None:
                    continue
                scores.append(
                    ProviderScore(
                        name=p.name,
                        model=p.model,
                        cost_per_1k_tokens=cfg.input_price_per_1k,
                        latency_ms=100,
                        success_rate=1.0,
                        score=self._score_provider(p),
                    )
                )
            return scores

    def _save(self) -> None:
        if self.path == "":
            return
        data = {
            "daily_spent": self.daily_spent,
            "monthly_spent": self.monthly_spent,
            "last_reset": int(self.last_reset.timestamp()),
        }
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o750, exist_ok=True)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, json.dumps(data).encode("utf-8"))
            finally:
                os.close(fd)
        except OSError as exc:
            _logger.error("[costopt] failed to write state: %s", exc)

    def _load(self) -> None:
        if self.path == "":
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                s = json.load(f)
        except (OSError, ValueError):
            return
        self.daily_spent = float(s.get("daily_spent", 0.0))
        self.monthly_spent = float(s.get("monthly_spent", 0.0))
        self.last_reset = datetime.fromtimestamp(float(s.get("last_reset", 0.0)))
