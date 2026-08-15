# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Static
from typing import cast

from dxrk.models import AgentID
from dxrk.tui.shared import STATE

AGENT_OPTIONS: list[tuple[AgentID, str, str]] = [
    (AgentID.CLAUDE_CODE, "Claude Code", "Anthropic's CLI agent"),
    (AgentID.OPENCODE, "OpenCode", "Open-source coding agent"),
    (AgentID.KILOCODE, "Kilocode", "Lightweight agent"),
    (AgentID.GEMINI_CLI, "Gemini CLI", "Google's coding agent"),
    (AgentID.CURSOR, "Cursor", "AI-first IDE"),
    (AgentID.VSCODE_COPILOT, "VS Code Copilot", "GitHub's AI pair programmer"),
    (AgentID.CODEX, "Codex", "CLI coding agent"),
    (AgentID.ANTIGRAVITY, "Antigravity", "Agentic coding tool"),
    (AgentID.WINDSURF, "Windsurf", "AI IDE"),
    (AgentID.KIMI, "Kimi", "AI assistant with long context"),
    (AgentID.QWEN_CODE, "Qwen Code", "Alibaba's coding agent"),
    (AgentID.KIRO_IDE, "Kiro IDE", "AI-native IDE"),
]


class AgentsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("space", "toggle", "Toggle"),
        Binding("enter", "continue", "Continue"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="agents-container"):
            yield Static("[bold]Select AI Agents[/]", id="agents-title")
            yield Static("[dim]Use j/k to move, space to toggle, enter to continue.[/]")
            yield Static("")
            with VerticalScroll(id="agent-list"):
                for i, (aid, name, desc) in enumerate(AGENT_OPTIONS):
                    checked = "✓" if aid in STATE.selected_agents else " "
                    prefix = "▸" if i == 0 else " "
                    yield Static(f"{prefix}[{checked}] {name}")
            yield Static("")
            yield Static("  Continue")
            yield Static("  Back")
            yield Static("")
            yield Static("[dim]space: toggle • enter: confirm • esc: back[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._action_offset = len(AGENT_OPTIONS)
        self._update_list()

    def _update_list(self) -> None:
        items = list(self.query("#agent-list > Static"))
        for i, child in enumerate(items):
            if i >= len(AGENT_OPTIONS):
                continue
            aid, name, _ = AGENT_OPTIONS[i]
            checked = "✓" if aid in STATE.selected_agents else " "
            prefix = "▸" if i == self.cursor else " "
            cast(Static, child).update(f"{prefix}[{checked}] {name}")
            child.set_class(i == self.cursor, "focused")

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_list()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        total = self._action_offset + 2
        if self.cursor < total - 1:
            self.cursor += 1

    async def action_toggle(self, attribute_name: str = "") -> None:
        if self.cursor < self._action_offset:
            aid = AGENT_OPTIONS[self.cursor][0]
            if aid in STATE.selected_agents:
                STATE.selected_agents.remove(aid)
            else:
                STATE.selected_agents.append(aid)
            self._update_list()

    async def action_continue(self) -> None:
        if self.cursor == self._action_offset and STATE.selected_agents:
            self.app.push_screen("persona")
        elif self.cursor == self._action_offset + 1:
            self.app.push_screen("detection")
        elif self.cursor < self._action_offset:
            await self.action_toggle()

    def action_back(self) -> None:
        self.app.push_screen("detection")
