# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static
from typing import cast

from dxrk.planner import ResolvedPlan, build_review_payload
from dxrk.tui.shared import STATE


class ReviewScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="review-container"):
            yield Static("[bold]Review and Confirm[/]", id="review-title")
            with VerticalScroll(id="review-content"):
                yield Static("")
            yield Static("")
            yield Static("[dim]enter: install • esc: back[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#review-content", VerticalScroll)
        scroll.remove_children()

        plan = STATE.plan
        payload = (
            build_review_payload(
                selection=plan.selection,
                resolved=cast("ResolvedPlan", plan),
            )
            if plan and plan.selection
            else None
        )

        agents = STATE.selected_agents
        components = STATE.selected_components
        skills = STATE.selected_skills

        parts = []

        agent_str = ", ".join(a.value for a in agents) if agents else "none"
        parts.append(f"  [bold]Agents[/]  {agent_str}")
        parts.append(f"  [bold]Persona[/]  {STATE.persona.value}")
        parts.append(f"  [bold]Preset[/]  {STATE.preset.value}")
        parts.append("")

        if components:
            parts.append("[bold]Components[/]")
            for c in components:
                is_auto = payload and c in payload.added_dependencies
                badge = (
                    "[dim]selected[/]" if not is_auto else "[yellow]auto-dependency[/]"
                )
                parts.append(f"  {c.value} {badge}")

            if skills:
                parts.append("[bold]  Skills[/]")
                for s in skills:
                    parts.append(f"    [dim]{s.value}[/]")

            has_sdd = any(c.value == "sdd" for c in components)
            if has_sdd:
                tdd_label = "Enabled" if STATE.strict_tdd else "Disabled"
                parts.append(f"  [bold]Strict TDD[/]  {tdd_label}")

            parts.append("")

        unsupported = []
        if agents:
            from dxrk.catalog import is_supported_agent

            for a in agents:
                if not is_supported_agent(a):
                    unsupported.append(a.value)
        if unsupported:
            parts.append(f"[yellow]Unsupported agents: {', '.join(unsupported)}[/]")
            parts.append("")

        for line in parts:
            scroll.mount(Static(line))

        scroll.mount(Static("  ▸ Install"))
        scroll.mount(Static("   Back"))
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
        actions = ["Install", "Back"]
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
