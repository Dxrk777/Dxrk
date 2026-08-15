# SPDX-License-Identifier: MIT
import shutil
from pathlib import Path

from dxrk.agents.interface import Adapter, DetectResult
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy


class OpenCodeAdapter(Adapter):
    @property
    def agent(self) -> AgentID:
        return AgentID.OPENCODE

    @property
    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def detect(self, home_dir: str = "") -> DetectResult:
        config_path = self.global_config_dir(home_dir)
        binary = shutil.which("opencode")
        installed = binary is not None
        config_found = Path(config_path).is_dir()
        return DetectResult(
            installed=installed,
            binary_path=binary or "",
            config_path=config_path,
            config_found=config_found,
        )

    @property
    def supports_auto_install(self) -> bool:
        return True

    def global_config_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode")

    def system_prompt_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode")

    def system_prompt_file(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "AGENTS.md")

    def skills_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "skills")

    def settings_path(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "settings.json")

    @property
    def system_prompt_strategy(self) -> SystemPromptStrategy:
        return SystemPromptStrategy.FILE_REPLACE

    @property
    def mcp_strategy(self) -> MCPStrategy:
        return MCPStrategy.MERGE_INTO_SETTINGS

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "mcp.json")

    @property
    def supports_output_styles(self) -> bool:
        return False

    @property
    def supports_slash_commands(self) -> bool:
        return True

    def commands_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "commands")

    @property
    def supports_sub_agents(self) -> bool:
        return True

    def sub_agents_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".config" / "opencode" / "agents")

    def embedded_sub_agents_dir(self) -> str:
        return "opencode/agents"

    @property
    def supports_skills(self) -> bool:
        return True

    @property
    def supports_system_prompt(self) -> bool:
        return True

    @property
    def supports_mcp(self) -> bool:
        return True
