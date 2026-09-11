# SPDX-License-Identifier: MIT
from typing import cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Static

from dxrk.models import AgentID
from dxrk.tui.context import get_ctx

AGENT_OPTIONS: list[tuple[AgentID, str, str]] = [
    (AgentID.CLAUDE_CODE, "Claude Code", "Agente CLI de Anthropic"),
    (AgentID.OPENCODE, "OpenCode", "Agente de código abierto"),
    (AgentID.KILOCODE, "Kilocode", "Agente ligero"),
    (AgentID.GEMINI_CLI, "Gemini CLI", "Agente de código de Google"),
    (AgentID.CURSOR, "Cursor", "IDE con IA integrada"),
    (AgentID.VSCODE_COPILOT, "VS Code Copilot", "Pareja de programación con IA de GitHub"),
    (AgentID.CODEX, "Codex", "Agente de programación para CLI"),
    (AgentID.ANTIGRAVITY, "Antigravity", "Herramienta de programación agéntica"),
    (AgentID.WINDSURF, "Windsurf", "IDE con IA"),
    (AgentID.KIMI, "Kimi", "Asistente de IA con contexto amplio"),
    (AgentID.QWEN_CODE, "Qwen Code", "Agente de código de Alibaba"),
    (AgentID.KIRO_IDE, "Kiro IDE", "IDE nativo de IA"),
]


class AgentsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("space", "toggle", "Alternar"),
        Binding("enter", "continue", "Continuar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="agents-container"):
            yield Static("[bold]Seleccionar agentes de IA[/]", id="agents-title")
            yield Static("[dim]Usa j/k para moverte, espacio para alternar, enter para continuar.[/]")
            yield Static("")
            with VerticalScroll(id="agent-list"):
                for i, (aid, name, desc) in enumerate(AGENT_OPTIONS):
                    checked = "✓" if aid in get_ctx().selected_agents else " "
                    prefix = "▸" if i == 0 else " "
                    yield Static(f"{prefix}[{checked}] {name}")
            yield Static("")
            yield Static("  Continuar")
            yield Static("  Atrás")
            yield Static("")
            yield Static("[dim]espacio: alternar • enter: confirmar • esc: atrás[/]")
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
            checked = "✓" if aid in get_ctx().selected_agents else " "
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
            ctx = get_ctx()
            if aid in ctx.selected_agents:
                ctx.selected_agents.remove(aid)
            else:
                ctx.selected_agents.append(aid)
            self._update_list()

    async def action_continue(self) -> None:
        if self.cursor == self._action_offset and get_ctx().selected_agents:
            self.app.push_screen("persona")
        elif self.cursor == self._action_offset + 1:
            self.app.push_screen("detection")
        elif self.cursor < self._action_offset:
            await self.action_toggle()

    def action_back(self) -> None:
        self.app.push_screen("detection")
