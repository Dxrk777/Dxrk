# SPDX-License-Identifier: MIT
from dxrk.agents.antigravity.adapter import AntigravityAdapter
from dxrk.agents.claude.adapter import ClaudeAdapter
from dxrk.agents.codex.adapter import CodexAdapter
from dxrk.agents.cursor.adapter import CursorAdapter
from dxrk.agents.gemini.adapter import GeminiCLIAdapter
from dxrk.agents.kilocode.adapter import KiloCodeAdapter
from dxrk.agents.kimi.adapter import KimiAdapter
from dxrk.agents.kiro.adapter import KiroAdapter
from dxrk.agents.openclaw.adapter import OpenClawAdapter
from dxrk.agents.opencode.adapter import OpenCodeAdapter
from dxrk.agents.pi.adapter import PiAdapter
from dxrk.agents.qwen.adapter import QwenCodeAdapter
from dxrk.agents.registry import Registry
from dxrk.agents.vscode.adapter import VSCodeAdapter
from dxrk.agents.windsurf.adapter import WindsurfAdapter


def create_registry() -> Registry:
    reg = Registry()
    reg.register(ClaudeAdapter())
    reg.register(OpenCodeAdapter())
    reg.register(GeminiCLIAdapter())
    reg.register(KiloCodeAdapter())
    reg.register(QwenCodeAdapter())
    reg.register(CursorAdapter())
    reg.register(VSCodeAdapter())
    reg.register(AntigravityAdapter())
    reg.register(WindsurfAdapter())
    reg.register(KimiAdapter())
    reg.register(KiroAdapter())
    reg.register(CodexAdapter())
    reg.register(OpenClawAdapter())
    reg.register(PiAdapter())
    return reg
