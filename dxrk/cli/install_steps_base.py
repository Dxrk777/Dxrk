# SPDX-License-Identifier: MIT
"""Shared base step and adapter resolution helpers for the install pipeline."""

from __future__ import annotations

import logging
from typing import Any

from dxrk.models import AgentID
from dxrk.pipeline import Step

log = logging.getLogger("dxrk.cli.install")


class NoopStep(Step):
    def __init__(self, step_id: str):
        self._id = step_id

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        return None


def _resolve_adapters(agent_ids: list[AgentID]) -> list[Any]:
    from dxrk.agents.registry import Registry

    reg = Registry()
    adapters: list[Any] = []
    for aid in agent_ids:
        try:
            adapter = reg.get(aid) or _create_agent_adapter(aid)
            if adapter:
                adapters.append(adapter)
        except Exception:
            continue
    return adapters


def _create_agent_adapter(agent_id: AgentID) -> Any:
    from dxrk.agents.factory import create_registry

    reg = create_registry()
    return reg.get(agent_id)
