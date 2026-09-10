# SPDX-License-Identifier: MIT
"""Tests for the conversational chat TUI (option-2 interface)."""

from __future__ import annotations

import json
import stat

from dxrk.tui.chat_backend import (
    ChatBackend,
    ChatMessage,
    collect_text_chunks,
    find_opencode_binary,
    parse_json_events,
)
from dxrk.tui.screens.chat import ChatScreen


class FakeBackend(ChatBackend):
    def __init__(self, reply: str = "fake reply") -> None:
        super().__init__(binary="/nonexistent/opencode")
        self._reply = reply
        self.sent: list[str] = []

    def send(self, message: str) -> ChatMessage:
        self.sent.append(message)
        return ChatMessage(role="assistant", text=self._reply)


def _make_backend(**kwargs: object) -> ChatBackend:
    backend = ChatBackend(binary="/nonexistent/opencode")
    for key, value in kwargs.items():
        setattr(backend, key, value)
    return backend


class TestFindBinary:
    def test_env_override(self, tmp_path, monkeypatch):
        fake = tmp_path / "opencode"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setenv("DXRK_OPENCODE_BIN", str(fake))
        assert find_opencode_binary() == str(fake)

    def test_env_override_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DXRK_OPENCODE_BIN", str(tmp_path / "nope"))
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr("os.path.expanduser", lambda p: str(tmp_path / "home"))
        assert find_opencode_binary() == ""


class TestParseEvents:
    def test_text_delta(self):
        raw = json.dumps({"type": "text.delta", "delta": "hola"})
        assert parse_json_events(raw) == "hola"

    def test_assistant_role(self):
        raw = json.dumps({"role": "assistant", "content": "mundo"})
        assert parse_json_events(raw) == "mundo"

    def test_user_echo_ignored(self):
        raw = "\n".join(
            [
                json.dumps({"role": "user", "message": "digame algo"}),
                json.dumps({"type": "text", "text": "respuesta"}),
            ]
        )
        assert parse_json_events(raw) == "respuesta"

    def test_plain_line_kept(self):
        assert parse_json_events("plain output") == "plain output"

    def test_empty(self):
        assert parse_json_events("\n  \n") == ""

    def test_nested(self):
        raw = json.dumps({"type": "wrapper", "event": {"type": "text", "text": "x"}})
        assert "x" in parse_json_events(raw)

    def test_collect_depth_guard(self):
        deep: object = {"type": "text", "text": "ok"}
        for _ in range(10):
            deep = {"type": "wrapper", "child": deep}
        assert collect_text_chunks(deep) == []


class TestSend:
    def test_no_binary(self):
        backend = ChatBackend(binary="")
        backend.binary = ""
        reply = backend.send("hola")
        assert reply.role == "system"
        assert "not found" in reply.text

    def test_fake_script(self, tmp_path):
        script = tmp_path / "opencode"
        line = json.dumps({"type": "text", "text": "script reply"})
        script.write_text(f"#!/bin/sh\necho '{line}'\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        backend = ChatBackend(binary=str(script))
        reply = backend.send("hola")
        assert reply.role == "assistant"
        assert reply.text == "script reply"

    def test_failing_script(self, tmp_path):
        script = tmp_path / "opencode"
        script.write_text("#!/bin/sh\necho boom >&2\nexit 3\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        backend = ChatBackend(binary=str(script))
        reply = backend.send("hola")
        assert reply.role == "system"
        assert "boom" in reply.text


class TestSlash:
    def test_help(self):
        result = _make_backend().handle_slash("/help")
        assert result.handled and "/memory" in result.reply

    def test_clear(self):
        result = _make_backend().handle_slash("/clear")
        assert result.handled and result.clear

    def test_model_get_set(self):
        backend = _make_backend()
        assert "default" in backend.handle_slash("/model").reply
        result = backend.handle_slash("/model anthropic/claude")
        assert backend.model == "anthropic/claude"
        assert "anthropic/claude" in result.reply

    def test_session_get_set(self):
        backend = _make_backend()
        assert "new" in backend.handle_slash("/session").reply
        backend.handle_slash("/session abc123")
        assert backend.session == "abc123"

    def test_memory_usage(self):
        result = _make_backend().handle_slash("/memory")
        assert "usage" in result.reply

    def test_unknown(self):
        result = _make_backend().handle_slash("/nope")
        assert result.handled and "unknown command" in result.reply


class TestChatScreen:
    async def test_submit_replies(self):
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        ctx = TUIContext(version="1.1.0")
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await app.push_screen(ChatScreen(backend=FakeBackend("hola mundo")))
            await pilot.pause()
            composer = app.screen.query_one("#chat-composer")
            composer.focus()
            await pilot.press(*"ping")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            texts = [m.text for m in app.screen.history]
            assert "ping" in texts
            assert "hola mundo" in texts

    async def test_slash_clear(self):
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        ctx = TUIContext(version="1.1.0")
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await app.push_screen(ChatScreen(backend=FakeBackend()))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ChatScreen)
            screen.action_clear()
            await pilot.pause()
            assert screen.history[-1].text == "Transcript cleared."

    async def test_escape_pops(self):
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, ctx_var

        ctx = TUIContext(version="1.1.0")
        ctx_var.set(ctx)
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await app.push_screen(ChatScreen(backend=FakeBackend()))
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ChatScreen)

    def test_welcome_binding(self):
        from dxrk.tui.app import WelcomeScreen

        keys = [b.key for b in WelcomeScreen.BINDINGS]
        assert "c" in keys

    def test_registered(self):
        from dxrk.tui.app import DxrkApp

        assert DxrkApp.SCREENS["chat"] is ChatScreen
