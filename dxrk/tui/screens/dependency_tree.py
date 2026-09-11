# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.catalog import mvp_components
from dxrk.models import PresetID
from dxrk.tui.context import get_ctx

ALL_COMPONENTS = mvp_components()


class DependencyTreeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("space", "toggle", "Alternar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="dep-tree-container"):
            with VerticalScroll(id="dep-tree-content"):
                yield Static("")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#dep-tree-content", VerticalScroll)
        scroll.remove_children()

        if get_ctx().preset == PresetID.CUSTOM:
            self._render_custom_picker(scroll)
        else:
            self._render_preset_plan(scroll)

        return Widget._render(self)

    def _render_preset_plan(self, scroll: VerticalScroll) -> None:
        scroll.mount(Static("[bold]Plan de instalación[/]"))
        scroll.mount(Static(""))

        plan = get_ctx().plan
        ordered = plan.steps if plan else []
        added: set[str] = set()

        if not ordered:
            scroll.mount(Static("[yellow]Aún no hay componentes seleccionados.[/]"))
            scroll.mount(Static(""))
        else:
            scroll.mount(Static("[bold]Componentes a instalar[/]"))
            for idx, step in enumerate(ordered):
                num = f"[dim]{idx + 1}.[/]"
                name = step.name
                note = "[green]incluido[/]"
                if hasattr(step, "id") and step.id in added:
                    note = "[yellow]dependencia automática[/]"
                scroll.mount(Static(f"  {num} {name} {note}"))

                found = [c for c in ALL_COMPONENTS if c.id.value == step.id]
                if found and found[0].description:
                    scroll.mount(Static(f"[dim]     {found[0].description}[/]"))
            scroll.mount(Static(""))

        actions = ["Continuar", "Atrás"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navegar • enter: seleccionar • esc: atrás[/]"))

    def _render_custom_picker(self, scroll: VerticalScroll) -> None:
        scroll.mount(Static("[bold]Seleccionar componentes[/]"))
        scroll.mount(Static(""))
        scroll.mount(Static("[dim]Alterna los componentes con enter o espacio.[/]"))
        scroll.mount(Static(""))

        selected_set = set(get_ctx().selected_components)
        self._component_statics = []
        for idx, comp in enumerate(ALL_COMPONENTS):
            checked = "✓" if comp.id in selected_set else " "
            prefix = "▸" if idx == self.cursor else " "
            s = Static(f"{prefix}[{checked}] {comp.id.value}")
            self._component_statics.append(s)
            scroll.mount(s)
            scroll.mount(Static(f"[dim]    {comp.description}[/]"))

        scroll.mount(Static(""))
        actions = ["Continuar", "Atrás"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor - len(ALL_COMPONENTS) else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navegar • espacio/enter: alternar • esc: atrás[/]"))

    def _update_actions(self) -> None:
        if not hasattr(self, "_action_statics"):
            return
        actions = ["Continuar", "Atrás"]
        for i, s in enumerate(self._action_statics):
            prefix = "▸" if i == self.cursor - self._comp_count() else " "
            s.update(f"{prefix} {actions[i]}")

    def _comp_count(self) -> int:
        if get_ctx().preset == PresetID.CUSTOM:
            return len(ALL_COMPONENTS)
        return 0

    def _total_options(self) -> int:
        return self._comp_count() + 2

    def watch_cursor(self, old: int, new: int) -> None:
        if get_ctx().preset == PresetID.CUSTOM:
            self._update_component_list()
        self._update_actions()

    def _update_component_list(self) -> None:
        if not hasattr(self, "_component_statics"):
            return
        selected_set = set(get_ctx().selected_components)
        for idx, s in enumerate(self._component_statics):
            if idx >= len(ALL_COMPONENTS):
                break
            comp = ALL_COMPONENTS[idx]
            checked = "✓" if comp.id in selected_set else " "
            prefix = "▸" if idx == self.cursor else " "
            s.update(f"{prefix}[{checked}] {comp.id.value}")

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        total = self._total_options()
        if self.cursor < total - 1:
            self.cursor += 1

    async def action_toggle(self, attribute_name: str = "") -> None:
        if get_ctx().preset != PresetID.CUSTOM:
            return
        if self.cursor < len(ALL_COMPONENTS):
            comp = ALL_COMPONENTS[self.cursor]
            ctx = get_ctx()
            if comp.id in ctx.selected_components:
                ctx.selected_components.remove(comp.id)
            else:
                ctx.selected_components.append(comp.id)
            self._update_component_list()

    async def action_select(self) -> None:
        if self.cursor < self._comp_count():
            await self.action_toggle()
        elif self.cursor == self._comp_count():
            self.app.push_screen("review")
        else:
            self.app.push_screen("preset")

    def action_back(self) -> None:
        self.app.push_screen("preset")
