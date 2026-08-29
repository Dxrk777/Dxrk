# SPDX-License-Identifier: MIT
"""R15 TUI TenantSwitcher — modal list/create/switch.

Uses ``dxrk.tenant.migration.tenant_root`` / ``list_tenants`` and
``dxrk.tui.context.get_ctx`` for AppState.tenant_id/tenant_path/role.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from dxrk.tui.context import get_ctx


def _get_tenants() -> list[str]:
    try:
        from dxrk.tenant.migration import list_tenants
    except Exception:
        return []
    try:
        return list_tenants()
    except Exception:
        return []


def _tenant_badge_text() -> str:
    ctx = get_ctx()
    tid = getattr(ctx, "tenant_id", "") or "default"
    role = getattr(ctx, "role", "") or "readonly"
    # path for badge optional
    return f"tenant: {tid} · role: {role}"


class TenantSwitcherScreen(ModalScreen[None]):
    """Modal tenant switcher with list/create/switch.

    Bindings match spec: up/k, down/j, enter=switch, esc=back.
    Extra: c=create, t=back shortcut.
    """

    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "switch", "Switch"),
        Binding("c", "create", "Create"),
        Binding("escape", "back", "Back"),
        Binding("t", "back", "Back", show=False),
    ]

    cursor: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="tenant-switcher-container"):
            yield Static("[bold]Tenant Switcher[/]", id="tenant-switcher-title")
            yield Static(_tenant_badge_text(), id="tenant-badge")
            yield Static("")
            with VerticalScroll(id="tenant-list"):
                yield Static("")
            yield Static("")
            # inline create row: Input + hint
            yield Input(
                placeholder="new tenant id (a-z,0-9,-,_) — press c to focus, enter to create", id="tenant-create-input"
            )
            yield Static("[dim]j/k: navigate • enter: switch • c: create • esc/back • t: back[/]", id="tenant-help")
        yield Footer()

    def on_mount(self) -> None:
        self._tenants: list[str] = _get_tenants()
        self._render_list()

    def _render_list(self) -> Visual:
        try:
            scroll = self.query_one("#tenant-list", VerticalScroll)
        except Exception:
            return Widget._render(self)
        scroll.remove_children()
        if not self._tenants:
            scroll.mount(Static("[yellow]No tenants yet. Type an id and press c/enter to create.[/]"))
            return Widget._render(self)
        ctx = get_ctx()
        current = getattr(ctx, "tenant_id", "")
        for i, tid in enumerate(self._tenants):
            marker = " (active)" if tid == current else ""
            prefix = "▸" if i == self.cursor else " "
            style = "[bold green]" if tid == current else ""
            end_style = "[/]" if style else ""
            # also show path hint
            line = f"{prefix} {style}{tid}{marker}{end_style}"
            s = Static(line)
            s.set_class(i == self.cursor, "focused")
            scroll.mount(s)
        return Widget._render(self)

    def watch_cursor(self, old: int, new: int) -> None:
        self._render_list()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(self._tenants) - 1:
            self.cursor += 1

    def action_switch(self) -> None:
        """Switch to selected tenant, update ctx and env, refresh badge."""
        if not self._tenants:
            return
        if self.cursor < 0 or self.cursor >= len(self._tenants):
            return
        tid = self._tenants[self.cursor]
        self._do_switch(tid)

    def _do_switch(self, tid: str) -> None:
        try:
            from dxrk.tenant.migration import tenant_root
        except Exception:
            tenant_root = None  # type: ignore[assignment]
        ctx = get_ctx()
        ctx.tenant_id = tid
        if tenant_root is not None:
            try:
                p = tenant_root(tid)
                ctx.tenant_path = str(p)
            except Exception:
                ctx.tenant_path = tid
        else:
            ctx.tenant_path = tid
        # resolve role via rbac — default_role if no user yet
        try:
            from dxrk.security.rbac import TenantRoleResolver

            resolver = TenantRoleResolver(tid)
            # use empty user -> default_role
            role = resolver.resolve("")
            ctx.role = role
        except Exception:
            ctx.role = getattr(ctx, "role", "readonly") or "readonly"
        # persist active + env (mirror commands/tenant)
        try:
            os.environ["DXRK_TENANT"] = tid
        except Exception:
            pass
        try:
            from pathlib import Path

            active = Path.home() / ".dxrk" / "tenants" / "_active"
            active.parent.mkdir(parents=True, exist_ok=True)
            try:
                active.parent.chmod(0o750)
            except OSError:
                pass
            active.write_text(tid, encoding="utf-8")
            try:
                active.chmod(0o600)
            except OSError:
                pass
        except Exception:
            pass
        # update badge if still mounted
        try:
            badge = self.query_one("#tenant-badge", Static)
            badge.update(_tenant_badge_text())
        except Exception:
            pass
        self.app.push_screen("welcome")

    def action_create(self) -> None:
        """Create tenant from Input value and switch."""
        try:
            inp = self.query_one("#tenant-create-input", Input)
        except Exception:
            return
        tid = inp.value.strip()
        if not tid:
            # focus input if empty
            try:
                inp.focus()
            except Exception:
                pass
            return
        # validate id
        try:
            from dxrk.security.jwt import validate_id
        except Exception:
            validate_id = None  # type: ignore[assignment]

        if validate_id is not None and not validate_id(tid):
            inp.value = ""
            try:
                inp.placeholder = f"invalid id {tid!r} — use [a-zA-Z0-9_-] 1..256"
            except Exception:
                pass
            return
        # ensure tenant
        try:
            from dxrk.tenant.migration import ensure_tenant

            ensure_tenant(tid)
        except Exception:
            return
        # ensure rbac default roles.json exists (0o600)
        try:
            from dxrk.security.rbac import TenantRoleResolver

            resolver = TenantRoleResolver(tid)
            resolver.ensure_default()
            # assign creator as admin if possible? keep default readonly unless set
        except Exception:
            pass
        # refresh list and switch
        self._tenants = _get_tenants()
        # find new cursor position
        try:
            idx = self._tenants.index(tid)
            self.cursor = idx
        except ValueError:
            self.cursor = 0
        self._render_list()
        inp.value = ""
        self._do_switch(tid)

    def action_back(self) -> None:
        self.app.push_screen("welcome")
