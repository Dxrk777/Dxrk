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


class BackupsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
        Binding("r", "rename", "Rename", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("p", "pin", "Pin", show=False),
    ]

    cursor = reactive(0)
    list_offset = reactive(0)
    MAX_VISIBLE = 10

    def compose(self) -> ComposeResult:
        with Container(id="backups-container"):
            yield Static("[bold]Backup Management[/]", id="backups-title")
            with VerticalScroll(id="backup-list"):
                yield Static("")
            yield Static("")
            yield Static(
                "[dim]j/k: navigate • enter: restore • r: rename • d: delete • p: pin/unpin • esc: back[/]"
            )
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        scroll = self.query_one("#backup-list", VerticalScroll)
        scroll.remove_children()

        backups = STATE.backups
        if not backups:
            scroll.mount(Static("[yellow]No backups found yet.[/]"))
            scroll.mount(Static(""))
            scroll.mount(Static("  Back"))
            return Widget._render(self)

        end = self.list_offset + self.MAX_VISIBLE
        end = min(end, len(backups))

        if self.list_offset > 0:
            scroll.mount(Static("[dim]  ↑ more[/]"))

        self._backup_statics = []
        for i in range(self.list_offset, end):
            snap = backups[i]
            label = snap.get("display_label", snap.get("id", "unknown"))
            if snap.get("created_by_version"):
                label = f"{label}  [v{snap['created_by_version']}]"
            if snap.get("description"):
                label = f"{label}  — {snap['description']}"
            display = f"{snap['id']}  ({label})"
            prefix = "▸" if i == self.cursor else " "
            s = Static(f"{prefix} {display}")
            self._backup_statics.append(s)
            scroll.mount(s)

        if end < len(backups):
            scroll.mount(Static("[dim]  ↓ more[/]"))

        scroll.mount(Static(""))
        scroll.mount(Static("  Back"))

        return Widget._render(self)

    def _update_list(self) -> None:
        if not hasattr(self, "_backup_statics"):
            return
        backups = STATE.backups
        end = self.list_offset + self.MAX_VISIBLE
        end = min(end, len(backups))
        for idx, s in enumerate(self._backup_statics):
            i = self.list_offset + idx
            if i >= len(backups):
                break
            snap = backups[i]
            label = snap.get("display_label", snap.get("id", "unknown"))
            if snap.get("created_by_version"):
                label = f"{label}  [v{snap['created_by_version']}]"
            if snap.get("description"):
                label = f"{label}  — {snap['description']}"
            display = f"{snap['id']}  ({label})"
            prefix = "▸" if i == self.cursor else " "
            s.update(f"{prefix} {display}")

    def watch_cursor(self, old: int, new: int) -> None:
        backups = STATE.backups
        if new < self.list_offset:
            self.list_offset = new
            self._render()
        elif new >= self.list_offset + self.MAX_VISIBLE:
            self.list_offset = new - self.MAX_VISIBLE + 1
            self._render()
        else:
            self._update_list()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        backups = STATE.backups
        total = len(backups) + 1
        if self.cursor < total - 1:
            self.cursor += 1

    def action_select(self) -> None:
        backups = STATE.backups
        if self.cursor < len(backups):
            STATE.selected_backup = backups[self.cursor]
            self.app.push_screen("restore_confirm")
        else:
            self.app.push_screen("welcome")

    def action_back(self) -> None:
        self.app.push_screen("welcome")

    def action_rename(self) -> None:
        backups = STATE.backups
        if self.cursor < len(backups):
            STATE.selected_backup = backups[self.cursor]
            self.app.push_screen("rename_backup")

    def action_delete(self) -> None:
        backups = STATE.backups
        if self.cursor < len(backups):
            STATE.selected_backup = backups[self.cursor]
            self.app.push_screen("delete_confirm")

    def action_pin(self) -> None:
        backups = STATE.backups
        if self.cursor < len(backups):
            snap = backups[self.cursor]
            snap["pinned"] = not snap.get("pinned", False)
            self._update_list()


class RestoreConfirmScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Restore Backup[/]")
            yield Static("")
            snap = getattr(STATE, "selected_backup", None) or {}
            yield Static(f"[bold]Backup:[/] {snap.get('id', 'unknown')}")
            yield Static(f"[dim]{snap.get('display_label', '')}[/]")
            yield Static("")
            yield Static("[yellow]This will overwrite your current configuration.[/]")
            yield Static("")
            yield Static("  ▸ Restore")
            yield Static("   Cancel")
            yield Static("")
            yield Static("[dim]j/k: navigate • enter: select • esc: back[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        return Widget._render(self)

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1

    def action_select(self) -> None:
        if self.cursor == 0:
            self.app.push_screen("restore_result")
        else:
            self.app.push_screen("backups")

    def action_back(self) -> None:
        self.app.push_screen("backups")


class DeleteConfirmScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Delete Backup[/]")
            yield Static("")
            snap = getattr(STATE, "selected_backup", None) or {}
            yield Static(f"[bold]Backup:[/] {snap.get('id', 'unknown')}")
            yield Static(f"[dim]{snap.get('display_label', '')}[/]")
            yield Static("")
            yield Static(
                "[yellow]Are you sure you want to permanently delete this backup?[/]"
            )
            yield Static("[yellow]This action cannot be undone.[/]")
            yield Static("")
            yield Static("  ▸ Delete")
            yield Static("   Cancel")
            yield Static("")
            yield Static("[dim]j/k: navigate • enter: select • esc: back[/]")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1

    def action_select(self) -> None:
        if self.cursor == 0:
            self.app.push_screen("delete_result")
        else:
            self.app.push_screen("backups")

    def action_back(self) -> None:
        self.app.push_screen("backups")


class RenameBackupScreen(Screen):
    BINDINGS = [
        Binding("enter", "save", "Save"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Rename Backup[/]")
            yield Static("")
            snap = getattr(STATE, "selected_backup", None) or {}
            yield Static(f"[bold]Backup:[/] {snap.get('id', 'unknown')}")
            yield Static(f"[dim]{snap.get('display_label', '')}[/]")
            yield Static("")
            if snap.get("description"):
                yield Static(f"[dim]Current description:[/] {snap['description']}")
                yield Static("")
            yield Static("[bold]New description:[/]")
            yield Static("  > ")
            yield Static("")
            yield Static("[dim]enter: save • esc: cancel[/]")
        yield Footer()

    def action_save(self) -> None:
        self.app.push_screen("backups")

    def action_cancel(self) -> None:
        self.app.push_screen("backups")
