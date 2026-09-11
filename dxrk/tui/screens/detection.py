# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.tui.context import get_ctx


class DetectionScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "continue", "Continuar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="detection-container"):
            yield Static("[bold]Detección del sistema[/]", id="detection-title")
            yield VerticalScroll(id="detection-results")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#detection-results", VerticalScroll)
        scroll.remove_children()
        d = get_ctx().detection
        if not d:
            scroll.mount(Static("[red]La detección falló o aún no se ejecutó.[/]"))
            return Widget._render(self)

        sys = d.system
        supported = "[green]Sí[/]" if sys.supported else "[red]No[/]"

        scroll.mount(Static(f"[bold]SO[/]  {sys.os} ({sys.arch})"))
        scroll.mount(Static(f"[bold]Shell[/]  {sys.shell}"))
        scroll.mount(Static(f"[bold]Compatible[/]  {supported}"))
        scroll.mount(Static(""))

        if d.tools:
            scroll.mount(Static("[bold]Herramientas[/]"))
            for name, status in sorted(d.tools.items()):
                indicator = "[green]encontrado[/]" if status.installed else "[red]no encontrado[/]"
                scroll.mount(Static(f"  {name}: {indicator}"))
            scroll.mount(Static(""))

        assert d.dependencies is not None, "detection did not populate dependencies"
        if d.dependencies.dependencies:
            scroll.mount(Static("[bold]Dependencias[/]"))
            for dep in d.dependencies.dependencies:
                if dep.installed:
                    v = dep.version or "encontrado"
                    indicator = f"[green]{v}[/]"
                else:
                    label = "NO ENCONTRADO (requerido)" if dep.required else "no encontrado"
                    indicator = f"[red]{label}[/]"
                suffix = " [dim](opcional)[/]" if not dep.required else ""
                scroll.mount(Static(f"  {dep.name}: {indicator}{suffix}"))
            if d.dependencies.missing_required:
                scroll.mount(Static(f"[yellow]Faltantes requeridos: {', '.join(d.dependencies.missing_required)}[/]"))
            scroll.mount(Static(""))

        if d.configs:
            scroll.mount(Static("[bold]Configuraciones detectadas[/]"))
            for cfg in d.configs:
                indicator = "[green]presente[/]" if cfg.exists else "[red]faltante[/]"
                scroll.mount(Static(f"  {cfg.agent}: {indicator}"))
            scroll.mount(Static(""))

        actions = ["Continuar", "Atrás"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navegar • enter: seleccionar • esc: atrás[/]"))

        return Widget._render(self)

    def _update_actions(self) -> None:
        if not hasattr(self, "_action_statics"):
            return
        actions = ["Continuar", "Atrás"]
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
