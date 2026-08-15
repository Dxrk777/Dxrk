# SPDX-License-Identifier: MIT
import os
import shutil
from pathlib import Path

from dxrk.agents.interface import Adapter, DetectResult
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy


def _vscode_user_dir(home_dir: str) -> str:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path(home_dir) / ".config")
    return str(Path(xdg) / "Code" / "User")


class VSCodeAdapter(Adapter):
    @property
    def agent(self) -> AgentID:
        return AgentID.VSCODE_COPILOT

    @property
    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def detect(self, home_dir: str = "") -> DetectResult:
        binary = shutil.which("code")
        installed = binary is not None
        config_path = self.global_config_dir(home_dir)
        config_found = os.path.isdir(config_path)
        return DetectResult(
            installed=installed,
            binary_path=binary or "",
            config_path=config_path,
            config_found=config_found,
        )

    @property
    def supports_auto_install(self) -> bool:
        return False

    def global_config_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".copilot")

    def system_prompt_dir(self, home_dir: str = "") -> str:
        return str(Path(_vscode_user_dir(home_dir)) / "prompts")

    def system_prompt_file(self, home_dir: str = "") -> str:
        return str(
            Path(_vscode_user_dir(home_dir)) / "prompts" / "gentle-ai.instructions.md"
        )

    def skills_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".copilot" / "skills")

    def settings_path(self, home_dir: str = "") -> str:
        return str(Path(_vscode_user_dir(home_dir)) / "settings.json")

    @property
    def system_prompt_strategy(self) -> SystemPromptStrategy:
        return SystemPromptStrategy.INSTRUCTIONS_FILE

    @property
    def mcp_strategy(self) -> MCPStrategy:
        return MCPStrategy.MCP_CONFIG_FILE

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return str(Path(_vscode_user_dir(home_dir)) / "mcp.json")

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
