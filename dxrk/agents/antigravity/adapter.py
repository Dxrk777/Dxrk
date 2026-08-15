# SPDX-License-Identifier: MIT
import os
from pathlib import Path

from dxrk.agents.interface import Adapter, DetectResult
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy


class AntigravityAdapter(Adapter):
    @property
    def agent(self) -> AgentID:
        return AgentID.ANTIGRAVITY

    @property
    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def detect(self, home_dir: str = "") -> DetectResult:
        config_path = self.global_config_dir(home_dir)
        config_found = os.path.isdir(config_path)
        return DetectResult(
            installed=config_found,
            binary_path="",
            config_path=config_path,
            config_found=config_found,
        )

    @property
    def supports_auto_install(self) -> bool:
        return False

    def global_config_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".gemini" / "antigravity")

    def system_prompt_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".gemini")

    def system_prompt_file(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".gemini" / "GEMINI.md")

    def skills_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".gemini" / "antigravity" / "skills")

    def settings_path(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".gemini" / "antigravity" / "settings.json")

    @property
    def system_prompt_strategy(self) -> SystemPromptStrategy:
        return SystemPromptStrategy.APPEND_TO_FILE

    @property
    def mcp_strategy(self) -> MCPStrategy:
        return MCPStrategy.MCP_CONFIG_FILE

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return str(Path(home_dir) / ".gemini" / "antigravity" / "mcp_config.json")

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
        return True

    @property
    def supports_system_prompt(self) -> bool:
        return True

    @property
    def supports_mcp(self) -> bool:
        return True
