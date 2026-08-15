# SPDX-License-Identifier: MIT
import shutil
from pathlib import Path

from dxrk.agents.interface import Adapter, DetectResult
from dxrk.models import AgentID, MCPStrategy, SupportTier, SystemPromptStrategy


class PiAdapter(Adapter):
    @property
    def agent(self) -> AgentID:
        return AgentID.PI

    @property
    def tier(self) -> SupportTier:
        return SupportTier.FULL

    def detect(self, home_dir: str = "") -> DetectResult:
        config_path = self.global_config_dir(home_dir)
        binary = shutil.which("pi")
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

    def install_command(self, profile) -> list[list[str]]:
        return [
            ["pi", "install", "npm:gentle-pi"],
            ["pi", "install", "npm:gentle-engram"],
            ["pi", "install", "npm:pi-mcp-adapter"],
            ["npm", "exec", "--yes", "--package", "gentle-engram", "--", "pi-engram", "init"],
            ["pi", "install", "npm:pi-subagents"],
            ["pi", "install", "npm:pi-intercom"],
            ["pi", "install", "npm:@juicesharp/rpiv-ask-user-question"],
            ["pi", "install", "npm:pi-web-access"],
            ["pi", "install", "npm:pi-lens"],
            ["pi", "install", "npm:@juicesharp/rpiv-todo"],
            ["pi", "install", "npm:pi-btw"],
        ]

    def global_config_dir(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".pi")

    def system_prompt_dir(self, home_dir: str = "") -> str:
        return ""

    def system_prompt_file(self, home_dir: str = "") -> str:
        return ""

    def skills_dir(self, home_dir: str = "") -> str:
        return ""

    def settings_path(self, home_dir: str = "") -> str:
        return str(Path(home_dir) / ".pi" / "agent" / "settings.json")

    @property
    def system_prompt_strategy(self) -> SystemPromptStrategy:
        return SystemPromptStrategy.APPEND_TO_FILE

    @property
    def mcp_strategy(self) -> MCPStrategy:
        return MCPStrategy.MCP_CONFIG_FILE

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return str(Path(home_dir) / ".pi" / "agent" / "mcp.json")

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
        return True
