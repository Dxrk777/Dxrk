# SPDX-License-Identifier: MIT
from dxrk.agents.errors import DuplicateAdapterError
from dxrk.agents.interface import Adapter
from dxrk.models import AgentID


class Registry:
    def __init__(self) -> None:
        self._adapters: dict[AgentID, Adapter] = {}

    def register(self, adapter: Adapter) -> None:
        agent = adapter.agent
        if agent in self._adapters:
            raise DuplicateAdapterError(f"{agent}")
        self._adapters[agent] = adapter

    def get(self, agent: AgentID) -> Adapter | None:
        return self._adapters.get(agent)

    @property
    def supported_agents(self) -> list[AgentID]:
        return sorted(self._adapters.keys())

    def __len__(self) -> int:
        return len(self._adapters)
