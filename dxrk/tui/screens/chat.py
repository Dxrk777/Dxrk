# SPDX-License-Identifier: MIT
"""Conversational agent screen (option-2 interface).

Transcript + composer over ChatBackend. Enter sends; the reply arrives in a
worker so the UI never blocks. Local /commands never touch the backend.
"""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Input, RichLog, Static

from dxrk.tui.chat_backend import ChatBackend, ChatMessage


class ChatScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Atrás"),
        Binding("ctrl+l", "clear", "Limpiar"),
    ]

    def __init__(
        self,
        backend: ChatBackend | None = None,
        name: str | None = None,
        id: str | None = None,  # noqa: A002 - matches textual Screen signature
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.backend = backend or ChatBackend()
        self.history: list[ChatMessage] = []

    def compose(self) -> ComposeResult:
        with Container(id="chat-root"):
            yield Static("Dxrk Chat  ·  /help para ver los comandos", id="chat-title")
            yield RichLog(id="chat-transcript", highlight=True, markup=True)
            yield Input(placeholder="Escribe un mensaje, Enter para enviar…", id="chat-composer")
        yield Footer()

    def on_mount(self) -> None:
        self._write_system(self._welcome_text())
        composer = self.query_one("#chat-composer", Input)
        composer.focus()

    def _welcome_text(self) -> str:
        if self.backend.available:
            model = self.backend.model or "default"
            return f"Backend listo (modelo: {model}). Escribe /help para ver los comandos."
        return "CLI de opencode no encontrada: el chat funciona en modo solo local (/help, /memory)."

    def _write_user(self, text: str) -> None:
        self.history.append(ChatMessage(role="user", text=text))
        line = Text.from_markup("[bold cyan]tú:[/] ")
        line.append(text)
        self.query_one("#chat-transcript", RichLog).write(line)

    def _write_assistant(self, text: str) -> None:
        self.history.append(ChatMessage(role="assistant", text=text))
        line = Text.from_markup("[bold green]dxrk:[/] ")
        line.append(text)
        self.query_one("#chat-transcript", RichLog).write(line)

    def _write_system(self, text: str) -> None:
        self.history.append(ChatMessage(role="system", text=text))
        self.query_one("#chat-transcript", RichLog).write(Text(text))

    @on(Input.Submitted, "#chat-composer")
    def _on_composer_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        self._write_user(text)
        if text.startswith("/"):
            result = self.backend.handle_slash(text)
            if result.clear:
                self.action_clear()
            elif result.reply:
                self._write_system(result.reply)
            return
        self._write_system("pensando…")
        self.run_worker(self._deliver(text), exclusive=True)

    async def _deliver(self, text: str) -> None:
        # send() blocks on a subprocess: run it in a thread so the UI
        # stays responsive while the agent works.
        reply = await asyncio.to_thread(self.backend.send, text)
        self._drop_thinking()
        if reply.role == "system":
            self._write_system(reply.text)
        else:
            self._write_assistant(reply.text)

    def _drop_thinking(self) -> None:
        if self.history and self.history[-1].role == "system" and self.history[-1].text == "pensando…":
            self.history.pop()
            log = self.query_one("#chat-transcript", RichLog)
            log.clear()
            for msg in self.history:
                if msg.role == "user":
                    line = Text.from_markup("[bold cyan]tú:[/] ")
                    line.append(msg.text)
                    log.write(line)
                elif msg.role == "assistant":
                    line = Text.from_markup("[bold green]dxrk:[/] ")
                    line.append(msg.text)
                    log.write(line)
                else:
                    log.write(Text(msg.text))

    def action_clear(self) -> None:
        self.history.clear()
        self.query_one("#chat-transcript", RichLog).clear()
        self._write_system("Conversación borrada.")

    def action_back(self) -> None:
        self.app.pop_screen()
