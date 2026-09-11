# SPDX-License-Identifier: MIT
from typing import cast

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.planner import ResolvedPlan, build_review_payload
from dxrk.tui.context import get_ctx


class ReviewScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="review-container"):
            yield Static("[bold]Revisar y confirmar[/]", id="review-title")
            with VerticalScroll(id="review-content"):
                yield Static("")
            yield Static("")
            yield Static("[dim]enter: instalar • esc: atrás[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#review-content", VerticalScroll)
        scroll.remove_children()

        ctx = get_ctx()
        plan = ctx.plan
        payload = (
            build_review_payload(
                selection=plan.selection,
                resolved=cast("ResolvedPlan", plan),
            )
            if plan and plan.selection
            else None
        )

        agents = ctx.selected_agents
        components = ctx.selected_components
        skills = ctx.selected_skills

        parts = []

        agent_str = ", ".join(a.value for a in agents) if agents else "ninguno"
        parts.append(f"  [bold]Agentes[/]  {agent_str}")
        parts.append(f"  [bold]Persona[/]  {ctx.persona.value}")
        parts.append(f"  [bold]Preset[/]  {ctx.preset.value}")
        parts.append("")

        if components:
            parts.append("[bold]Componentes[/]")
            for c in components:
                is_auto = payload and c in payload.added_dependencies
                badge = "[dim]seleccionado[/]" if not is_auto else "[yellow]dependencia automática[/]"
                parts.append(f"  {c.value} {badge}")

            if skills:
                parts.append("[bold]  Habilidades[/]")
                for s in skills:
                    parts.append(f"    [dim]{s.value}[/]")

            has_sdd = any(c.value == "sdd" for c in components)
            if has_sdd:
                tdd_label = "Activado" if ctx.strict_tdd else "Desactivado"
                parts.append(f"  [bold]TDD estricto[/]  {tdd_label}")

            parts.append("")

        unsupported = []
        if agents:
            from dxrk.catalog import is_supported_agent

            for a in agents:
                if not is_supported_agent(a):
                    unsupported.append(a.value)
        if unsupported:
            parts.append(f"[yellow]Agentes no compatibles: {', '.join(unsupported)}[/]")
            parts.append("")

        for line in parts:
            scroll.mount(Static(line))

        scroll.mount(Static("  ▸ Instalar"))
        scroll.mount(Static("   Atrás"))
        items = scroll.children
        self._action_statics = [
            cast(Static, items[-2]),
            cast(Static, items[-1]),
        ]

        return Widget._render(self)

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1
        self._update_actions()

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1
        self._update_actions()

    def _update_actions(self) -> None:
        if not hasattr(self, "_action_statics"):
            return
        actions = ["Instalar", "Atrás"]
        for i, s in enumerate(self._action_statics):
            prefix = "▸" if i == self.cursor else " "
            s.update(f"{prefix} {actions[i]}")

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_actions()

    def action_select(self) -> None:
        if self.cursor == 0:
            self.app.push_screen("installing")
        else:
            self.app.push_screen("dependency_tree")

    def action_back(self) -> None:
        self.app.push_screen("dependency_tree")
