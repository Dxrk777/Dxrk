# SPDX-License-Identifier: MIT
from abc import ABC, abstractmethod
from typing import NamedTuple

from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy


class DetectResult(NamedTuple):
    installed: bool
    binary_path: str
    config_path: str
    config_found: bool


class Adapter(ABC):
    @property
    @abstractmethod
    def agent(self) -> AgentID: ...

    @property
    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def detect(self, home_dir: str = "") -> DetectResult:
        raise NotImplementedError

    @property
    def supports_auto_install(self) -> bool:
        return False

    def install_command(self, profile) -> list[list[str]]:
        raise NotImplementedError

    def global_config_dir(self, home_dir: str = "") -> str:
        return ""

    def system_prompt_dir(self, home_dir: str = "") -> str:
        return ""

    def system_prompt_file(self, home_dir: str = "") -> str:
        return ""

    def skills_dir(self, home_dir: str = "") -> str:
        return ""

    def settings_path(self, home_dir: str = "") -> str:
        return ""

    @property
    def system_prompt_strategy(self) -> SystemPromptStrategy:
        return SystemPromptStrategy.FILE_REPLACE

    @property
    def mcp_strategy(self) -> MCPStrategy:
        return MCPStrategy.SEPARATE_MCP_FILES

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return ""

    @property
    def supports_output_styles(self) -> bool:
        return False

    def output_style_dir(self, home_dir: str = "") -> str:
        return ""

    @property
    def supports_slash_commands(self) -> bool:
        return False

    def commands_dir(self, home_dir: str = "") -> str:
        return ""

    @property
    def supports_sub_agents(self) -> bool:
        return False

    def sub_agents_dir(self, home_dir: str = "") -> str:
        return ""

    def embedded_sub_agents_dir(self) -> str:
        return ""

    @property
    def supports_skills(self) -> bool:
        return False

    @property
    def supports_system_prompt(self) -> bool:
        return False

    @property
    def supports_mcp(self) -> bool:
        return False
