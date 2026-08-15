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
from dxrk.tui.shared import STATE

ALL_COMPONENTS = mvp_components()


class DependencyTreeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("space", "toggle", "Toggle"),
        Binding("escape", "back", "Back"),
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

        if STATE.preset == PresetID.CUSTOM:
            self._render_custom_picker(scroll)
        else:
            self._render_preset_plan(scroll)

        return Widget._render(self)

    def _render_preset_plan(self, scroll: VerticalScroll) -> None:
        scroll.mount(Static("[bold]Install Plan[/]"))
        scroll.mount(Static(""))

        plan = STATE.plan
        ordered = plan.steps if plan else []
        added: set[str] = set()

        if not ordered:
            scroll.mount(Static("[yellow]No components selected yet.[/]"))
            scroll.mount(Static(""))
        else:
            scroll.mount(Static("[bold]Components to install[/]"))
            for idx, step in enumerate(ordered):
                num = f"[dim]{idx + 1}.[/]"
                name = step.name
                note = "[green]included[/]"
                if hasattr(step, "id") and step.id in added:
                    note = "[yellow]auto-dependency[/]"
                scroll.mount(Static(f"  {num} {name} {note}"))

                found = [c for c in ALL_COMPONENTS if c.id.value == step.id]
                if found and found[0].description:
                    scroll.mount(Static(f"[dim]     {found[0].description}[/]"))
            scroll.mount(Static(""))

        actions = ["Continue", "Back"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navigate • enter: select • esc: back[/]"))

    def _render_custom_picker(self, scroll: VerticalScroll) -> None:
        scroll.mount(Static("[bold]Select Components[/]"))
        scroll.mount(Static(""))
        scroll.mount(Static("[dim]Toggle components with enter or space.[/]"))
        scroll.mount(Static(""))

        selected_set = set(STATE.selected_components)
        self._component_statics = []
        for idx, comp in enumerate(ALL_COMPONENTS):
            checked = "✓" if comp.id in selected_set else " "
            prefix = "▸" if idx == self.cursor else " "
            s = Static(f"{prefix}[{checked}] {comp.id.value}")
            self._component_statics.append(s)
            scroll.mount(s)
            scroll.mount(Static(f"[dim]    {comp.description}[/]"))

        scroll.mount(Static(""))
        actions = ["Continue", "Back"]
        self._action_statics = []
        for i, label in enumerate(actions):
            prefix = "▸" if i == self.cursor - len(ALL_COMPONENTS) else " "
            s = Static(f"{prefix} {label}")
            self._action_statics.append(s)
            scroll.mount(s)

        scroll.mount(Static("[dim]j/k: navigate • space/enter: toggle • esc: back[/]"))

    def _update_actions(self) -> None:
        if not hasattr(self, "_action_statics"):
            return
        actions = ["Continue", "Back"]
        for i, s in enumerate(self._action_statics):
            prefix = "▸" if i == self.cursor - self._comp_count() else " "
            s.update(f"{prefix} {actions[i]}")

    def _comp_count(self) -> int:
        if STATE.preset == PresetID.CUSTOM:
            return len(ALL_COMPONENTS)
        return 0

    def _total_options(self) -> int:
        return self._comp_count() + 2

    def watch_cursor(self, old: int, new: int) -> None:
        if STATE.preset == PresetID.CUSTOM:
            self._update_component_list()
        self._update_actions()

    def _update_component_list(self) -> None:
        if not hasattr(self, "_component_statics"):
            return
        selected_set = set(STATE.selected_components)
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
        if STATE.preset != PresetID.CUSTOM:
            return
        if self.cursor < len(ALL_COMPONENTS):
            comp = ALL_COMPONENTS[self.cursor]
            if comp.id in STATE.selected_components:
                STATE.selected_components.remove(comp.id)
            else:
                STATE.selected_components.append(comp.id)
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
