# SPDX-License-Identifier: MIT
"""Feature flag management"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

_logger = logging.getLogger("dxrk.config")


@dataclass
class FeatureFlag:
    name: str
    enabled: bool = False
    description: str = ""
    rollout_percent: int = 0
    allowed_users: List[str] = field(default_factory=list)


class FeatureFlagManager:
    def __init__(self, config=None):
        self._mu = threading.RLock()
        self._flags: Dict[str, FeatureFlag] = {}
        self._config = config
        self.LoadDefaults()

    def LoadDefaults(self) -> None:
        self._flags = {}
        for flag in (
            FeatureFlag(
                name="yolo_mode",
                enabled=False,
                description="Skip confirmation prompts for all operations",
                rollout_percent=0,
            ),
            FeatureFlag(
                name="auto_compact",
                enabled=True,
                description="Automatically compact context when approaching limits",
                rollout_percent=100,
            ),
            FeatureFlag(
                name="voice_input",
                enabled=False,
                description="Enable voice input for commands",
                rollout_percent=0,
            ),
            FeatureFlag(
                name="experimental_tools",
                enabled=False,
                description="Enable experimental tool integrations",
                rollout_percent=10,
            ),
            FeatureFlag(
                name="remote_sessions",
                enabled=False,
                description="Enable remote session management",
                rollout_percent=25,
            ),
        ):
            self._flags[flag.name] = flag

    def IsEnabled(self, name: str) -> bool:
        with self._mu:
            flag = self._flags.get(name)
            return bool(flag and flag.enabled)

    def Enable(self, name: str) -> None:
        with self._mu:
            flag = self._flags.get(name)
            if flag is None:
                raise ValueError(f"unknown feature flag: {name}")
            flag.enabled = True
            flag.rollout_percent = 100

    def Disable(self, name: str) -> None:
        with self._mu:
            flag = self._flags.get(name)
            if flag is None:
                raise ValueError(f"unknown feature flag: {name}")
            flag.enabled = False
            flag.rollout_percent = 0

    def SetRollout(self, name: str, percent: int) -> None:
        if percent < 0 or percent > 100:
            raise ValueError(f"rollout percent must be 0-100, got {percent}")
        with self._mu:
            flag = self._flags.get(name)
            if flag is None:
                raise ValueError(f"unknown feature flag: {name}")
            flag.rollout_percent = percent
            flag.enabled = percent > 0

    def GetAll(self) -> List[FeatureFlag]:
        with self._mu:
            return [self._copy_flag(f) for f in self._flags.values()]

    def Get(self, name: str) -> Tuple[Optional[FeatureFlag], bool]:
        with self._mu:
            flag = self._flags.get(name)
            if flag is None:
                return None, False
            return self._copy_flag(flag), True

    @staticmethod
    def _copy_flag(flag: FeatureFlag) -> FeatureFlag:
        return FeatureFlag(
            name=flag.name,
            enabled=flag.enabled,
            description=flag.description,
            rollout_percent=flag.rollout_percent,
            allowed_users=list(flag.allowed_users),
        )

    def Register(self, flag: FeatureFlag) -> None:
        with self._mu:
            self._flags[flag.name] = flag

    def Remove(self, name: str) -> None:
        with self._mu:
            if name not in self._flags:
                raise ValueError(f"unknown feature flag: {name}")
            del self._flags[name]

    def IsEnabledForUser(self, name: str, user_id: str) -> bool:
        with self._mu:
            flag = self._flags.get(name)
            if flag is None:
                return False
            if user_id in flag.allowed_users:
                return True
            if flag.rollout_percent <= 0:
                return False
            if flag.rollout_percent >= 100:
                return flag.enabled
            h = 0
            for c in user_id:
                h = (h * 31 + ord(c)) % 100
            return flag.enabled and h < flag.rollout_percent

    def EnabledFlags(self) -> List[str]:
        with self._mu:
            return [name for name, f in self._flags.items() if f.enabled]


def NewFeatureFlagManager(config=None) -> FeatureFlagManager:
    return FeatureFlagManager(config)
