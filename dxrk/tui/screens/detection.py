# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.tui.shared import STATE


class DetectionScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "continue", "Continue"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="detection-container"):
            yield Static("[bold]System Detection[/]", id="detection-title")
            yield VerticalScroll(id="detection-results")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#detection-results", VerticalScroll)
        scroll.remove_children()
        d = STATE.detection
        if not d:
            scroll.mount(Static("[red]Detection failed or not run yet.[/]"))
            return Widget._render(self)

        sys = d.system
        supported = "[green]Yes[/]" if sys.supported else "[red]No[/]"

        scroll.mount(Static(f"[bold]OS[/]  {sys.os} ({sys.arch})"))
        scroll.mount(Static(f"[bold]Shell[/]  {sys.shell}"))
        scroll.mount(Static(f"[bold]Supported[/]  {supported}"))
        scroll.mount(Static(""))

        if d.tools:
            scroll.mount(Static("[bold]Tools[/]"))
            for name, status in sorted(d.tools.items()):
                indicator = (
                    "[green]found[/]" if status.installed else "[red]not found[/]"
                )
                scroll.mount(Static(f"  {name}: {indicator}"))
            scroll.mount(Static(""))

        assert d.dependencies is not None, "detection did not populate dependencies"
        if d.dependencies.dependencies:
            scroll.mount(Static("[bold]Dependencies[/]"))
            for dep in d.dependencies.dependencies:
                if dep.installed:
                    v = dep.version or "found"
                    indicator = f"[green]{v}[/]"
                else:
                    label = "NOT FOUND (required)" if dep.required else "not found"
                    indicator = f"[red]{label}[/]"
                suffix = " [dim](optional)[/]" if not dep.required else ""
                scroll.mount(Static(f"  {dep.name}: {indicator}{suffix}"))
            if d.dependencies.missing_required:
                scroll.mount(
                    Static(
                        f"[yellow]Missing required: {', '.join(d.dependencies.missing_required)}[/]"
                    )
                )
            scroll.mount(Static(""))

        if d.configs:
            scroll.mount(Static("[bold]Detected Configs[/]"))
            for cfg in d.configs:
                indicator = "[green]present[/]" if cfg.exists else "[red]missing[/]"
                scroll.mount(Static(f"  {cfg.agent}: {indicator}"))
            scroll.mount(Static(""))

        actions = ["Continue", "Back"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navigate • enter: select • esc: back[/]"))

        return Widget._render(self)

    def _update_actions(self) -> None:
        if not hasattr(self, "_action_statics"):
            return
        actions = ["Continue", "Back"]
        for i, s in enumerate(self._action_statics):
            prefix = "▸" if i == self.cursor else " "
            s.update(f"{prefix} {actions[i]}")

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_actions()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1

    def action_continue(self) -> None:
        if self.cursor == 0:
            self.app.push_screen("agents")
        else:
            self.app.push_screen("welcome")

    def action_back(self) -> None:
        self.app.push_screen("welcome")
