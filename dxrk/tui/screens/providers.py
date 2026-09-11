# SPDX-License-Identifier: MIT
"""Pantalla de proveedores de IA: gratis sin token, pago con token (opencode)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from dxrk.tui import providers_backend as backend


class ProvidersScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás", show=False),
    ]

    cursor = reactive(0)

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._connected: set[str] = set()

    def _row_detail(self, index: int) -> str:
        info = backend.ALL_PROVIDERS[index]
        if info.kind == "free":
            return f"{info.detail} Modelos: {', '.join(info.models)}"
        status = "conectado ✓" if info.id in self._connected else "sin conectar"
        return f"{info.detail} · {status}"

    def compose(self) -> ComposeResult:
        with Container(id="providers-container"):
            yield Static("[bold]IAs[/] Proveedores", id="title")
            yield Static(
                "Gratis sin token · pago pegando el token (como opencode)",
                id="providers-sub",
            )
            with VerticalScroll(id="providers-list"):
                for i, info in enumerate(backend.ALL_PROVIDERS):
                    with Container(classes=f"menu-item {'focused' if i == 0 else ''}"):
                        yield Static(f"[bold]{info.label}[/]", classes="option-title")
                        yield Static(self._row_detail(i), classes="option-desc")
            yield Input(
                placeholder="Token del seleccionado (o 'id token') ⏎",
                password=True,
                id="provider-token",
            )
            yield Static("", id="providers-msg")
        yield Footer()

    def on_mount(self) -> None:
        self._connected = backend.connected_providers()
        self._refresh_rows()

    def _rows(self):  # type: ignore[no-untyped-def]
        return list(self.query("#providers-list > Container"))

    def _refresh_rows(self) -> None:
        rows = self._rows()
        for i, row in enumerate(rows):
            row.set_classes(f"menu-item {'focused' if i == self.cursor else ''}")
            for static in row.query(Static):
                if static.has_class("option-desc"):
                    static.update(self._row_detail(i))

    def watch_cursor(self, old: int, new: int) -> None:
        self._refresh_rows()

    def action_cursor_up(self) -> None:
        self.cursor = max(0, self.cursor - 1)

    def action_cursor_down(self) -> None:
        self.cursor = min(len(backend.ALL_PROVIDERS) - 1, self.cursor + 1)

    def action_select(self) -> None:
        info = backend.ALL_PROVIDERS[self.cursor]
        if info.kind == "free":
            self._say(f"{info.label}: sin token. Usa /model en el chat.")
            return
        self.query_one("#provider-token", Input).focus()

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "provider-token":
            return
        self.run_worker(self._save_token(event.value), exclusive=True)

    async def _save_token(self, raw: str) -> None:
        value = (raw or "").strip()
        if not value:
            self._say("Pega un token primero.")
            return
        if " " in value:
            provider_id, _, token = value.partition(" ")
        else:
            provider_id = backend.ALL_PROVIDERS[self.cursor].id
            token = value
        info = next((p for p in backend.ALL_PROVIDERS if p.id == provider_id), None)
        if info is None or info.kind != "api":
            self._say(f"Proveedor '{provider_id}' no válido. Usa 'id token'.")
            return
        if not backend.validate_provider_id(provider_id):
            self._say(f"opencode no reconoce '{provider_id}'. Revisa el id.")
            return
        try:
            path = backend.save_api_token(provider_id, token)
        except ValueError as e:
            self._say(str(e))
            return
        except OSError as e:
            self._say(f"No se pudo guardar: {e}")
            return
        self._connected = backend.connected_providers()
        self._refresh_rows()
        self.query_one("#provider-token", Input).value = ""
        self._say(f"{info.label} conectado ✓ ({path})")

    def _say(self, msg: str) -> None:
        self.query_one("#providers-msg", Static).update(msg)
