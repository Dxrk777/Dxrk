# SPDX-License-Identifier: MIT
"""R15 TUI TenantSwitcher — Next-gen modal with animations, live preview, and premium UX.

A tenant switcher that feels like a premium SaaS dashboard, not a terminal tool.
Features: live search, animated transitions, tenant preview cards, keyboard overlay,
smooth focus animations, context-aware badges, and buttery-smooth UX.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.events import Key
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Button, Footer, Input, Label, Static

from dxrk.tui.context import get_ctx


@dataclass
class TenantInfo:
    """Rich tenant information."""

    id: str
    path: str
    role: Literal["admin", "dev", "readonly"]
    is_current: bool
    drawer_count: int = 0
    last_accessed: str = ""
    size_mb: float = 0.0


def _get_tenants() -> list[str]:
    """Get list of available tenants."""
    try:
        from dxrk.tenant.migration import list_tenants
    except Exception:
        return []
    try:
        return list_tenants()
    except Exception:
        return []


def _get_tenant_details(tenant_id: str) -> TenantInfo:
    """Get rich tenant details for preview."""
    is_current = tenant_id == getattr(get_ctx(), "tenant_id", "")

    # Get role
    role: Literal["admin", "dev", "readonly"] = "readonly"
    try:
        from dxrk.security.rbac import TenantRoleResolver

        resolver = TenantRoleResolver(tenant_id)
        resolved = resolver.resolve("")
        if resolved in ("admin", "dev", "readonly"):
            role = resolved  # type: ignore[assignment]
    except Exception:
        pass

    # Get path
    try:
        from dxrk.tenant.migration import tenant_root

        path = str(tenant_root(tenant_id))
    except Exception:
        path = f"~/.dxrk/tenants/{tenant_id}"

    # Get drawer count (quick estimate)
    drawer_count = 0
    try:
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(Path(path).expanduser()))
        dm.init()
        drawer_count = dm.count()
        dm.close()
    except Exception:
        pass

    return TenantInfo(
        id=tenant_id,
        path=path,
        role=role,
        is_current=is_current,
        drawer_count=drawer_count,
    )


def _tenant_badge_text() -> str:
    """Generate badge text for current tenant."""
    ctx = get_ctx()
    tid = getattr(ctx, "tenant_id", "") or "default"
    role = getattr(ctx, "role", "") or "readonly"
    return f"tenant: {tid} · role: {role}"


class RoleBadge(Static):
    """Animated role badge with color coding."""

    DEFAULT_CSS = """
    RoleBadge {
        width: auto;
        min-width: 10;
        height: 3;
        content-align: center middle;
        padding: 0 2;
        border: solid $primary;
        text-style: bold;
    }
    
    RoleBadge.admin { background: $error 20%; border: solid $error; color: $error; }
    RoleBadge.dev { background: $warning 20%; border: solid $warning; color: $warning; }
    RoleBadge.readonly { background: $panel; border: solid $primary; color: $text-muted; }
    """

    def __init__(self, role: Literal["admin", "dev", "readonly"], **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.add_class(role)

    def compose(self) -> ComposeResult:
        icons = {"admin": "󰣇", "dev": "󰨞", "readonly": "󰌾"}
        yield Label(f"{icons.get(self.role, '')} {self.role.upper()}")


class TenantCard(Static):
    """Premium tenant card with hover preview, animated focus, and rich info."""

    DEFAULT_CSS = """
    TenantCard {
        layout: horizontal;
        height: auto;
        min-height: 7;
        padding: 1 2;
        margin: 0 1 1 1;
        background: $surface;
        border: solid $primary 30%;
        opacity: 1;
    }
    
    TenantCard:hover {
        background: $boost 50%;
        border: solid $accent;
    }
    
    TenantCard.focused {
        background: $boost;
        border: solid $accent;
    }
    
    TenantCard.active {
        border: solid $success;
        background: $success 10%;
    }
    
    TenantCard.animating {
        opacity: 0.5;
    }
    
    .card-main {
        width: 1fr;
        padding: 0 1;
        layout: vertical;
    }
    
    .card-header {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }
    
    .card-name {
        text-style: bold;
        color: $text;
        width: 1fr;
    }
    
    .card-name.active { color: $success; }
    .card-name.focused { color: $accent; }
    
    .card-badge { width: auto; margin-left: 1; }
    
    .card-path {
        color: $text-muted;
        text-style: dim;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .card-stats {
        layout: horizontal;
        height: 1;
        margin-top: 1;
    }
    
    .stat-item {
        width: auto;
        min-width: 12;
        padding: 0 1;
        color: $text-muted;
        text-style: dim;
        border-right: solid $primary 30%;
    }
    
    
    .stat-value { color: $text; text-style: bold; }
    
    .card-role {
        width: 16;
        height: 3;
        content-align: center middle;
        margin-left: 2;
    }
    """

    def __init__(self, info: TenantInfo, index: int, **kwargs):
        super().__init__(**kwargs)
        self.info = info
        self.index = info.id
        self.can_focus = True

    def compose(self) -> ComposeResult:
        with Horizontal(classes="card-header"):
            # Current indicator
            indicator = "󰄬" if self.info.is_current else "○"
            indicator_style = "success" if self.info.is_current else "text-muted"
            yield Label(
                f"[{indicator_style}]{indicator}[/]",
                classes="indicator",
            )

            # Main content
            with Vertical(classes="card-main"):
                # Name row with badge
                with Horizontal():
                    name_suffix = " 󰜴 ACTIVO" if self.info.is_current else ""
                    yield Label(f"{self.info.id}{name_suffix}", classes="card-name")

                # Path
                path_display = self.info.path
                if path_display.startswith(str(Path.home())):
                    path_display = "~" + path_display[len(str(Path.home())) :]
                yield Label(f"󰉋 {path_display}", classes="card-path")

                # Stats row
                with Horizontal(classes="card-stats"):
                    yield Label(f"󰈙 {self.info.drawer_count} drawers", classes="stat-item")
                    if self.info.size_mb > 0:
                        yield Label(f"󰋊 {self.info.size_mb:.1f} MB", classes="stat-item")
                    if self.info.last_accessed:
                        yield Label(f"󰃰 {self.info.last_accessed}", classes="stat-item")

            # Role badge
            yield RoleBadge(self.info.role)

    def on_mount(self) -> None:
        if self.info.is_current:
            self.add_class("active")

    def on_focus(self) -> None:
        self.add_class("focused")
        self._animate_focus_in()

    def on_blur(self) -> None:
        self.remove_class("focused")
        self._animate_focus_out()

    def _animate_focus_in(self) -> None:
        """Smooth focus animation."""
        self.styles.offset = (-1, 0)

    def _animate_focus_out(self) -> None:
        self.styles.offset = (0, 0)


class PreviewPane(Static):
    """Right-side preview pane showing detailed tenant info."""

    DEFAULT_CSS = """
    PreviewPane {
        width: 40;
        height: 1fr;
        background: $panel;
        border-left: solid $primary;
        padding: 1 2;
        layout: vertical;
        overflow-y: auto;
    }
    
    .preview-section {
        margin-bottom: 2;
        padding: 1 0;
        border-bottom: solid $primary 30%;
    }
    
    .preview-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    
    .preview-label {
        color: $text-muted;
        text-style: dim;
    }
    
    .preview-value {
        color: $text;
        margin-top: 0;
    }
    
    .preview-role {
        text-style: bold;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_info: TenantInfo | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("󰋼  VISTA PREVIA", classes="preview-title")
            yield Static("", id="preview-content")
            yield Static("Sin tenant seleccionado", id="empty-preview")

    def update_preview(self, info: TenantInfo | None) -> None:
        """Update preview with tenant info."""
        self.current_info = info
        try:
            content = self.query_one("#preview-content", Static)
            empty = self.query_one("#empty-preview", Static)

            if info is None:
                empty.styles.display = "block"
                self.query_one(Static).styles.display = "none"
                return

            empty.styles.display = "none"

            # Build rich preview
            path_display = info.path
            if path_display.startswith(str(Path.home())):
                path_display = "~" + path_display[len(str(Path.home())) :]

            role_icons = {"admin": "󰣇", "dev": "󰨞", "readonly": "󰌾"}

            content.update(
                f"""
[bold]Tenant:[/] {info.id}
[bold]Rol:[/] {role_icons.get(info.role, "")} {info.role.upper()}
[bold]Ruta:[/] {info.path}
[bold]Drawers:[/] {info.drawer_count}
[bold]Tamaño:[/] {info.size_mb:.1f} MB
[bold]Estado:[/] {"󰄬 ACTIVO" if info.is_current else "󰚰 Inactivo"}
            """.strip()
            )
        except NoMatches:
            pass


class SearchInput(Input):
    """Enhanced search input with live filtering."""

    DEFAULT_CSS = """
    SearchInput {
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        border: solid $primary;
        background: $panel;
    }
    
    SearchInput:focus {
        border: solid $accent;
        background: $surface;
    }
    
    SearchInput .input-cursor {
        color: $accent;
    }
    """


class ShortcutHelp(Static):
    """Collapsible keyboard shortcuts overlay."""

    DEFAULT_CSS = """
    ShortcutHelp {
        layout: grid;
        grid-size: 2;
        grid-gutter: 1 2;
        padding: 1 2;
        background: $panel;
        border: solid $primary;
        margin-top: 1;
        height: auto;
    }
    
    ShortcutHelp.hidden {
        display: none;
    }
    
    .shortcut-key {
        color: $accent;
        text-style: bold;
        width: 20;
    }
    
    .shortcut-desc {
        color: $text-muted;
    }
    """

    SHORTCUTS: ClassVar[list[tuple[str, str]]] = [
        ("↑ / k / j / ↓", "Navegar"),
        ("Enter", "Cambiar tenant"),
        ("/", "Buscar / Filtrar"),
        ("c", "Crear tenant"),
        ("r", "Actualizar lista"),
        ("h / ?", "Toggle ayuda"),
        ("Esc / t", "Volver"),
        ("Tab", "Cambiar panel"),
    ]

    def compose(self) -> ComposeResult:
        for key, desc in self.SHORTCUTS:
            with Horizontal():
                yield Label(key, classes="shortcut-key")
                yield Label(desc, classes="shortcut-desc")


class TenantSwitcherScreen(ModalScreen[None]):
    """Next-gen Tenant Switcher — Premium modal with live preview, animations, and premium UX."""

    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False, priority=True),
        Binding("down,j", "cursor_down", "Abajo", show=False, priority=True),
        Binding("enter", "switch", "Cambiar", show=True),
        Binding("c", "create", "Crear", show=True),
        Binding("escape", "back", "Atrás", show=True),
        Binding("t", "back", "Atrás", show=False),
        Binding("/", "search", "Buscar", show=True),
        Binding("r", "refresh", "Actualizar", show=False),
        Binding("h,question_mark", "help_toggle", "Ayuda", show=True),
        Binding("tab", "toggle_panel", "Panel", show=False),
    ]

    cursor: reactive[int] = reactive(0)
    search_query: reactive[str] = reactive("")
    show_help: reactive[bool] = reactive(True)
    panel_focus: reactive[Literal["list", "preview"]] = reactive("list")

    DEFAULT_CSS = """
    TenantSwitcherScreen {
        align: center middle;
        layer: modal;
        background: $background 95%;
    }
    
    #tenant-switcher-container {
        width: 130;
        max-width: 95%;
        height: 85%;
        max-height: 95%;
        background: $surface;
        border: thick $primary 80%;
        padding: 1 2;
        layout: horizontal;
        overflow: hidden;
    }
    
    #left-panel {
        width: 70%;
        height: 1fr;
        layout: vertical;
        padding-right: 1;
    }
    
    #right-panel {
        width: 30%;
        min-width: 40;
        height: 1fr;
        border-left: solid $primary 50%;
        background: $panel;
    }
    
    #tenant-switcher-title {
        text-style: bold;
        color: $primary;
        text-align: center;
        margin-bottom: 0;
        padding: 0 0 1 0;
    }
    
    #tenant-badge {
        text-align: center;
        color: $accent;
        text-style: italic;
        margin-bottom: 1;
        background: $boost;
        padding: 0 2;
        border: solid $primary;
    }
    
    #search-container {
        margin: 1 0;
        height: 3;
    }
    
    #search-input {
        width: 100%;
    }
    
    #tenant-list {
        height: 1fr;
        overflow-y: auto;
        border: solid $primary 30%;
        padding: 1;
    }
    
    #tenant-list:focus {
        border: solid $accent;
    }
    
    #empty-state {
        text-align: center;
        color: $warning;
        text-style: italic;
        padding: 3;
    }
    
    #create-row {
        height: auto;
        margin-top: 1;
        padding: 1 0;
        border-top: solid $primary;
        layout: horizontal;
    }
    
    #create-input {
        width: 1fr;
        margin-right: 1;
    }
    
    #create-btn {
        width: 14;
    }
    
    #right-panel-content {
        height: 1fr;
        layout: vertical;
        padding: 1;
    }
    
    #preview-pane {
        height: 1fr;
    }
    
    #shortcut-help {
        margin-top: 1;
    }
    
    #shortcut-help.hidden {
        display: none;
    }
    
    #footer-hints {
        text-align: center;
        color: $text-muted;
        text-style: dim;
        margin-top: 1;
        padding: 1 0 0 0;
        border-top: solid $primary 30%;
        height: auto;
    }
    
    .help-toggle {
        text-align: center;
        color: $text-muted;
        text-style: dim;
        margin-top: 1;
    }
    
    /* Focus states (no keyframes: this Textual version rejects @keyframes) */
    
    #search-input:focus {
        border: solid $accent;
        background: $surface;
    }
    """

    def __init__(self):
        super().__init__()
        self._tenants: list[str] = []
        self._filtered: list[str] = []
        self._details: dict[str, dict] = {}
        self._refresh_timer: Timer | None = None
        self._debounce_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        with Container(id="tenant-switcher-container"):
            # Header
            with Horizontal():
                yield Static("󰌆  Selector de Tenant", id="tenant-switcher-title")
                yield Static("", id="spacer")
                yield Static(_tenant_badge_text(), id="tenant-badge")

            # Search
            with Container(id="search-container"):
                yield SearchInput(
                    placeholder="🔍  Buscar tenant... (/)  ·  Escribe para filtrar en tiempo real", id="search-input"
                )

            # Main content - split view
            with Horizontal():
                # Left: Tenant list
                with Vertical(id="left-panel"):
                    with VerticalScroll(id="tenant-list"):
                        yield Static("", id="empty-state")

                    # Create row
                    with Horizontal(id="create-row"):
                        yield SearchInput(
                            placeholder="nuevo tenant id (a-z, 0-9, -, _) · Enter para crear", id="tenant-create-input"
                        )
                        yield Button("󰐕 Crear", id="create-btn", variant="success")

                # Right: Preview pane
                with Vertical(id="right-panel"):
                    yield Static("󰋼  VISTA PREVIA", id="preview-title")
                    yield PreviewPane(id="preview-pane")

                    # Keyboard shortcuts
                    yield ShortcutHelp(id="shortcut-help")

            # Footer hints
            yield Static(
                "↑/k · ↓/j: navegar  ·  Enter: cambiar  ·  /: buscar  ·  c: crear  ·  r: actualizar  ·  Tab: panel  ·  h/?: ayuda  ·  Esc/t: volver",
                id="footer-hints",
            )

        yield Footer()

    def on_mount(self) -> None:
        self._load_tenants()
        try:
            self._refresh_timer = self.set_interval(30, self._auto_refresh_tenants)
        except Exception:
            self._refresh_timer = None
        self.call_later(self._focus_list)

    def _focus_list(self) -> None:
        try:
            self.query_one("#tenant-list", VerticalScroll).focus()
        except (NoMatches, Exception):
            pass
        self._focus_current_card()

    def _focus_search(self) -> None:
        try:
            self.query_one("#search-input", Input).focus()
        except (NoMatches, Exception):
            pass

    def on_unmount(self) -> None:
        if self._refresh_timer:
            self._refresh_timer.stop()

    def _load_tenants(self) -> None:
        """Load tenants (ids) plus a details cache for rich cards."""
        tenants = _get_tenants()
        self._tenants = list(tenants)
        self._details = {}
        for tid in tenants:
            try:
                info = _get_tenant_details(tid)
            except Exception:
                continue
            self._details[tid] = {
                "id": tid,
                "path": info.path,
                "role": info.role,
                "is_current": info.is_current,
                "drawer_count": info.drawer_count,
                "size_mb": info.size_mb,
            }

        self._filter_tenants()

    def _details_for(self, tenant_id: str) -> dict[str, Any]:
        """Return cached details, fetching on demand."""
        cache: dict[str, dict[str, Any]] = getattr(self, "_details", {})
        details: dict[str, Any] | None = cache.get(tenant_id)
        if details is not None:
            return details
        try:
            info = _get_tenant_details(tenant_id)
        except Exception:
            return {"id": tenant_id, "path": "", "role": "readonly", "is_current": False}
        details = {
            "id": tenant_id,
            "path": info.path,
            "role": info.role,
            "is_current": info.is_current,
            "drawer_count": info.drawer_count,
            "size_mb": info.size_mb,
        }
        try:
            self._details[tenant_id] = details
        except Exception:
            pass
        return details

    def _filter_tenants(self) -> None:
        """Filter tenants based on search query with debounce."""
        try:
            if self._debounce_timer:
                self._debounce_timer.stop()
        except Exception:
            pass

        try:
            self._debounce_timer = self.set_timer(0.1, self._apply_filter)
        except RuntimeError:
            self._apply_filter()

    def _apply_filter(self) -> None:
        if not self.search_query:
            self._filtered = self._tenants[:]
        else:
            query = self.search_query.lower()
            matches: list[str] = []
            for tid in self._tenants:
                if query in tid.lower():
                    matches.append(tid)
                    continue
                try:
                    if query in self._details_for(tid).get("path", "").lower():
                        matches.append(tid)
                except Exception:
                    pass
            self._filtered = matches

        self._render_list()

    def _render_list(self) -> int:
        """Render tenant cards with animations. Returns number of cards rendered."""
        try:
            list_container = self.query_one("#tenant-list", VerticalScroll)
            empty_state = self.query_one("#empty-state", Static)
        except (NoMatches, Exception):
            return 0

        try:
            list_container.remove_children()
        except Exception:
            pass

        if not self._filtered:
            try:
                empty_state.update(
                    f"[yellow]No hay tenants que coincidan con '{self.search_query}'[/]"
                    if self.search_query
                    else "[yellow]Aún no hay tenants. Escribe un id y pulsa Enter/Crear para crear.[/]"
                )
                empty_state.styles.display = "block"
            except Exception:
                pass
            return 0

        empty_state.styles.display = "none"

        ctx = get_ctx()
        current_tid = getattr(ctx, "tenant_id", "")

        for i, tenant in enumerate(self._filtered):
            tid = tenant["id"] if isinstance(tenant, dict) else tenant
            details = self._details_for(tid) if isinstance(tenant, str) else tenant
            is_current = (details.get("id", tid) if isinstance(details, dict) else tid) == current_tid
            card = TenantCard(
                info=TenantInfo(
                    id=details.get("id", tid),
                    path=details.get("path", ""),
                    role=details.get("role", "readonly"),
                    is_current=is_current,
                    drawer_count=details.get("drawer_count", 0),
                    size_mb=details.get("size_mb", 0.0),
                ),
                index=i,
            )
            card.id = f"card-{details.get('id', tid)}"
            try:
                self.query_one("#tenant-list", VerticalScroll).mount(card)
            except (NoMatches, Exception):
                pass

        # Clamp cursor
        if self.cursor >= len(self._filtered):
            self.cursor = max(0, len(self._filtered) - 1)

        try:
            self._focus_current_card()
        except Exception:
            pass
        try:
            self._update_preview()
        except Exception:
            pass
        return len(self._filtered)

    def _focus_current_card(self) -> None:
        if not self._filtered:
            return
        try:
            tenant = self._filtered[self.cursor]
            # Handle both dict and string tenant formats
            tenant_id = tenant["id"] if isinstance(tenant, dict) else tenant
            card = self.query_one(f"#card-{tenant_id}", TenantCard)
            card.focus(scroll_visible=True)
        except (NoMatches, IndexError, KeyError, TypeError):
            pass

    def watch_cursor(self, old: int, new: int) -> None:
        self._focus_current_card()
        self._update_preview()

    def watch_search_query(self, old: str, new: str) -> None:
        self._filter_tenants()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self.search_query = event.value
        elif event.input.id == "tenant-create-input" and event.value:
            # Live validation feedback
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self.action_switch()
        elif event.input.id == "tenant-create-input":
            self.action_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "create-btn":
            self.action_create()

    def _update_preview(self) -> None:
        """Update the preview pane."""
        try:
            preview = self.query_one("#preview-pane", PreviewPane)
            if self._filtered and 0 <= self.cursor < len(self._filtered):
                t = self._filtered[self.cursor]
                tid = t["id"] if isinstance(t, dict) else t
                details = self._details_for(tid) if isinstance(t, str) else t
                tenant_id = details.get("id", tid)
                tenant_path = details.get("path", "")
                tenant_role = details.get("role", "readonly")
                is_current = details.get("is_current", False)
                drawer_count = details.get("drawer_count", 0)
                size_mb = details.get("size_mb", 0.0)

                info = TenantInfo(
                    id=tenant_id,
                    path=tenant_path,
                    role=tenant_role,
                    is_current=is_current,
                    drawer_count=drawer_count,
                    size_mb=size_mb,
                )
                preview.update_preview(info)
            else:
                preview.update_preview(None)
        except NoMatches:
            pass

    def _update_badge(self) -> None:
        try:
            badge = self.query_one("#tenant-badge", Static)
            badge.update(_tenant_badge_text())
        except (NoMatches, Exception):
            pass

    def _auto_refresh_tenants(self) -> None:
        self._load_tenants()

    def action_refresh(self) -> None:
        self._load_tenants()
        self.notify("Lista actualizada", title="✓")

    def action_search(self) -> None:
        try:
            inp = self.query_one("#search-input", Input)
            inp.focus()
        except (NoMatches, Exception):
            pass

    def action_cursor_up(self) -> None:
        if self.panel_focus == "preview":
            self.panel_focus = "list"
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.panel_focus == "preview":
            self.panel_focus = "list"
        if self.cursor < len(self._filtered) - 1:
            self.cursor += 1

    def action_toggle_panel(self) -> None:
        """Toggle focus between list and preview."""
        self.panel_focus = "preview" if self.panel_focus == "list" else "list"
        if self.panel_focus == "preview":
            try:
                self.query_one("#preview-pane", PreviewPane).focus()
            except NoMatches:
                pass
        else:
            self._focus_current_card()

    def action_switch(self) -> None:
        if not self._filtered:
            return
        if self.cursor < 0 or self.cursor >= len(self._filtered):
            return
        selected = self._filtered[self.cursor]
        tid = selected["id"] if isinstance(selected, dict) else selected
        self._do_switch_sync(tid)

    async def _do_switch(self, tid: str) -> None:
        """Perform the tenant switch with smooth transition."""
        self._do_switch_sync(tid)
        await asyncio.sleep(0.15)
        self.app.push_screen("welcome")

    def _do_switch_sync(self, tid: str) -> None:
        """Perform the tenant switch synchronously."""
        _tenant_root: Any
        try:
            from dxrk.tenant.migration import tenant_root as _imported_root

            _tenant_root = _imported_root
        except Exception:
            _tenant_root = None

        ctx = get_ctx()
        ctx.tenant_id = tid

        if _tenant_root is not None:
            try:
                p = _tenant_root(tid)
                ctx.tenant_path = str(p)
            except Exception:
                ctx.tenant_path = tid
        else:
            ctx.tenant_path = tid

        # Resolve role
        try:
            from dxrk.security.rbac import TenantRoleResolver

            resolver = TenantRoleResolver(tid)
            role = resolver.resolve("")
            ctx.role = role
        except Exception:
            ctx.role = getattr(ctx, "role", "readonly") or "readonly"

        # Persist
        os.environ["DXRK_TENANT"] = tid
        try:
            active = Path.home() / ".dxrk" / "tenants" / "_active"
            active.parent.mkdir(parents=True, exist_ok=True)
            active.parent.chmod(0o750)
            active.write_text(tid, encoding="utf-8")
            active.chmod(0o600)
        except Exception:
            pass

        # Update badge (best-effort: may run without mounted app in tests)
        try:
            self._update_badge()
        except Exception:
            pass

        # Notify and return (best-effort without active app)
        try:
            self.notify(f"Cambiado a [bold]{tid}[/]", title="✓ Tenant cambiado")
        except Exception:
            pass

        # Return to welcome screen (best-effort without active app)
        try:
            self.app.push_screen("welcome")
        except Exception:
            pass

    def action_create(self) -> None:
        """Create new tenant from input."""
        try:
            inp = self.query_one("#tenant-create-input", Input)
            self.query_one("#create-btn", Button)
        except NoMatches:
            return

        tid = inp.value.strip()
        if not tid:
            inp.focus()
            return

        # Validate
        _validate_id: Any
        try:
            from dxrk.security.jwt import validate_id as _imported_validate

            _validate_id = _imported_validate
        except Exception:
            _validate_id = None

        if _validate_id is not None and not _validate_id(tid):
            inp.value = ""
            inp.placeholder = f"id no válido {tid!r} — usa [a-zA-Z0-9_-] 1..256"
            return

        # Create tenant
        try:
            from dxrk.tenant.migration import ensure_tenant

            ensure_tenant(tid)
        except Exception as e:
            self.notify(f"Error creando tenant: {e}", severity="error")
            return

        # Ensure RBAC defaults
        try:
            from dxrk.security.rbac import TenantRoleResolver

            resolver = TenantRoleResolver(tid)
            resolver.ensure_default()
        except Exception:
            pass

        # Clear input, refresh, and switch
        inp.value = ""
        self._load_tenants()
        self._do_switch_sync(tid)

    def action_help_toggle(self) -> None:
        """Toggle help visibility."""
        self.show_help = not self.show_help
        try:
            help_widget = self.query_one("#shortcut-help", ShortcutHelp)
            if self.show_help:
                help_widget.remove_class("hidden")
            else:
                help_widget.add_class("hidden")
        except NoMatches:
            pass

    def on_key(self, event: Key) -> None:
        if event.key in ("h", "question_mark"):
            self.action_help_toggle()
        elif event.key == "tab":
            self.action_toggle_panel()

    def on_focus(self, event: events.Focus) -> None:
        widget = getattr(event, "widget", None)
        widget_id = getattr(widget, "id", None)
        if self.show_help and widget_id in ("search-input", "tenant-create-input"):
            self.show_help = False
            try:
                self.query_one("#shortcut-help", ShortcutHelp).add_class("hidden")
            except (NoMatches, Exception):
                pass

    def action_back(self) -> None:
        self.app.push_screen("welcome")
