# SPDX-License-Identifier: MIT
"""Cobertura 100% real para todo `dxrk/tui/`.

Cubre lo que el resto de la suite no toca (sin pragma, sin relleno):
- app.py: Welcome.on_screen_resume(except), bounds de cursor, Detection continue,
  Agents toggle/continue, loops de _update_focus, StrictTDD/Uninstall compose,
  Backups bounds, ModelPicker on_mount/bounds/edit, ModelSelect bounds,
  DxrkApp.action_chat/providers y run().
- chat_backend.py: candidatos de binario, collect con listas/otros, send con
  opciones y fallos, /free, /memory con query, _search_memory y _guess_session_id.
- screens/backups.py: compose/on_mount, paginación, guards, watch (3 ramas),
  bounds, no-ops fuera de rango, cursores de confirms, rename con descripción.
- screens/chat.py: welcome sin backend, submit vacío, slash clear/help/vacío,
  _deliver system y _drop_thinking mixto + no-op.
- screens/dependency_tree.py: plan mixto, guards, comp_count, watch custom,
  break, bounds, toggle (4 casos).
- screens/detection.py: compose/on_mount, fixtures vacías/llenas,
  _update_actions, watch, bounds.
- screens/providers.py: cursor up, select free/pago, submit ajeno, save con
  todas las ramas de error.

Patrones: helpers de tests/test_r05_p4_coverage.py + pilot run_test.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dxrk.tui.chat_backend import (
    FREE_DEFAULT_MODEL,
    ChatBackend,
    ChatMessage,
    SlashResult,
    _guess_session_id,
    collect_text_chunks,
    find_opencode_binary,
    parse_json_events,
)
from dxrk.tui.context import TUIContext, ctx_var

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_PROJECT_DIR", raising=False)
    return home


def _compose(screen) -> list:  # type: ignore[no-untyped-def]
    """Consume screen.compose() con active_app para evitar NoActiveAppError."""
    from unittest.mock import MagicMock as _MM

    from textual._context import active_app

    token = active_app.set(_MM())
    try:
        return list(screen.compose())  # type: ignore[attr-defined]
    finally:
        active_app.reset(token)


def _mock_app(monkeypatch: pytest.MonkeyPatch, screen) -> MagicMock:  # type: ignore[no-untyped-def]
    mock = MagicMock()
    monkeypatch.setattr(type(screen), "app", property(lambda s, m=mock: m))
    return mock


def _mock_scroll() -> MagicMock:
    m = MagicMock()
    m.remove_children = MagicMock()
    m.mount = MagicMock()
    return m


def _full_detection():  # type: ignore[no-untyped-def]
    from dxrk.system import (
        ConfigState,
        Dependency,
        DependencyReport,
        DetectionResult,
        SystemInfo,
        ToolStatus,
    )

    return DetectionResult(
        system=SystemInfo(os="Linux", arch="x64", shell="bash", supported=True),
        tools={
            "git": ToolStatus(name="git", installed=True, path="/usr/bin/git"),
            "foo": ToolStatus(name="foo", installed=False),
        },
        dependencies=DependencyReport(
            dependencies=[
                Dependency(name="uv", required=True, installed=True, version="0.5"),
                Dependency(name="node", required=True, installed=True, version=""),
                Dependency(name="fzf", required=False, installed=False),
                Dependency(name="docker", required=True, installed=False),
            ],
            missing_required=["docker"],
        ),
        configs=[
            ConfigState(agent="claude-code", exists=True),
            ConfigState(agent="opencode", exists=False),
        ],
    )


def _empty_detection():  # type: ignore[no-untyped-def]
    from dxrk.system import DependencyReport, DetectionResult, SystemInfo

    return DetectionResult(system=SystemInfo(os="Linux"), tools={}, dependencies=DependencyReport(), configs=[])


# ---------------------------------------------------------------------------
# app.py — WelcomeScreen
# ---------------------------------------------------------------------------


def test_app_welcome_resume_except_and_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import WELCOME_OPTIONS, WelcomeScreen

    ctx_var.set(TUIContext(version="test"))
    screen = WelcomeScreen()
    # sin montar no hay #tenant-badge -> except pass (136-137)
    screen.on_screen_resume()
    # up con cursor > 0 (165)
    screen.cursor = 2
    screen.action_cursor_up()
    assert screen.cursor == 1
    # up en 0 no baja
    screen.cursor = 0
    screen.action_cursor_up()
    assert screen.cursor == 0
    # down en el máximo no avanza (rama 168 false)
    screen.cursor = len(WELCOME_OPTIONS) - 1
    screen.action_cursor_down()
    assert screen.cursor == len(WELCOME_OPTIONS) - 1
    # down normal sí avanza
    screen.cursor = 0
    screen.action_cursor_down()
    assert screen.cursor == 1


# ---------------------------------------------------------------------------
# app.py — DetectionScreen (legacy de app.py)
# ---------------------------------------------------------------------------


def test_app_detection_continue_click(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import DetectionScreen

    ctx_var.set(TUIContext(version="test"))
    screen = DetectionScreen()
    mock = _mock_app(monkeypatch, screen)
    screen.on_continue_click()  # 320 -> action_continue -> 323
    mock.push_screen.assert_called_with("agents")
    mock.reset_mock()
    screen.action_continue()
    mock.push_screen.assert_called_with("agents")
    screen.action_back()
    mock.push_screen.assert_called_with("welcome")


# ---------------------------------------------------------------------------
# app.py — AgentsScreen (legacy de app.py)
# ---------------------------------------------------------------------------


def test_app_agents_toggle_and_continue(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import AGENT_OPTIONS, AgentsScreen

    ctx = TUIContext(version="test", selected_agents=[])
    ctx_var.set(ctx)
    screen = AgentsScreen()
    screen.cursor = 0
    # up en 0 (falso) y down en el máximo (falso)
    screen.action_cursor_up()
    assert screen.cursor == 0
    screen.cursor = len(AGENT_OPTIONS) - 1
    screen.action_cursor_down()
    assert screen.cursor == len(AGENT_OPTIONS) - 1
    # toggle agrega (399-400) y quita (396-397)
    screen.cursor = 0
    asyncio.run(screen.action_toggle())
    assert ctx.selected_agents == [AGENT_OPTIONS[0][0]]
    asyncio.run(screen.action_toggle())
    assert ctx.selected_agents == []
    # continue sin agentes no navega (403 falso)
    mock = _mock_app(monkeypatch, screen)
    screen.action_continue()
    mock.push_screen.assert_not_called()
    # continue con agentes navega (403-404)
    ctx.selected_agents = [AGENT_OPTIONS[0][0]]
    screen.action_continue()
    mock.push_screen.assert_called_with("persona")


# ---------------------------------------------------------------------------
# app.py — Persona / Preset / SDDMode (loops de focus + bounds)
# ---------------------------------------------------------------------------


def test_app_persona_preset_sddmode_focus_and_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import PERSONA_OPTIONS, PRESET_OPTIONS, PersonaScreen, PresetScreen, SDDModeScreen

    ctx_var.set(TUIContext(version="test"))
    kids = [MagicMock(), MagicMock(), MagicMock()]
    for k in kids:
        k.set_class = MagicMock()

    ps = PersonaScreen()
    monkeypatch.setattr(ps, "query", lambda *a, **k: list(kids))
    ps._update_focus()  # 452-453
    assert kids[0].set_class.called
    ps.cursor = 0
    ps.action_cursor_up()  # falso 442->444
    assert ps.cursor == 0
    ps.action_cursor_down()
    assert ps.cursor == 1
    ps.cursor = len(PERSONA_OPTIONS) - 1
    ps.action_cursor_down()  # falso 447->449
    assert ps.cursor == len(PERSONA_OPTIONS) - 1
    ps.cursor = 1
    ps.action_cursor_up()  # verdadero
    assert ps.cursor == 0

    pr = PresetScreen()
    monkeypatch.setattr(pr, "query", lambda *a, **k: list(kids))
    pr._update_focus()  # 511-512
    pr.cursor = 1
    pr.action_cursor_up()  # 501-502 verdadero
    assert pr.cursor == 0
    pr.cursor = 0
    pr.action_cursor_up()  # falso
    assert pr.cursor == 0
    pr.action_cursor_down()
    assert pr.cursor == 1
    pr.cursor = len(PRESET_OPTIONS) - 1
    pr.action_cursor_down()  # falso 506->508
    assert pr.cursor == len(PRESET_OPTIONS) - 1

    sdd = SDDModeScreen()
    monkeypatch.setattr(sdd, "query", lambda *a, **k: list(kids))
    sdd.on_mount()  # 555 -> _update_focus -> 561-562
    assert kids[0].set_class.called
    sdd.cursor = 1
    sdd.action_cursor_up()  # 565-566 verdadero
    assert sdd.cursor == 0
    sdd.cursor = 0
    sdd.action_cursor_up()
    assert sdd.cursor == 0
    sdd.action_cursor_down()
    assert sdd.cursor == 1
    sdd.action_cursor_down()  # falso 569 (máximo 1)
    assert sdd.cursor == 1


# ---------------------------------------------------------------------------
# app.py — StrictTDD / UninstallMode / Backups (compose + bounds)
# ---------------------------------------------------------------------------


def test_app_strict_tdd_compose_and_up_at_zero(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import StrictTDDScreen

    ctx_var.set(TUIContext(version="test"))
    screen = StrictTDDScreen()
    assert len(_compose(screen)) > 0  # 594-602
    screen.cursor = 0
    screen.action_cursor_up()  # falso 605
    assert screen.cursor == 0


def test_app_uninstall_compose_and_up(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import UninstallModeScreen

    ctx_var.set(TUIContext(version="test"))
    screen = UninstallModeScreen()
    assert len(_compose(screen)) > 0  # 658-669
    screen.cursor = 2
    screen.action_cursor_up()  # 673 verdadero
    assert screen.cursor == 1
    screen.cursor = 0
    screen.action_cursor_up()
    assert screen.cursor == 0


def test_app_backups_simple_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import BackupsScreen

    ctx_var.set(TUIContext(version="test"))
    screen = BackupsScreen()
    assert len(_compose(screen)) > 0
    screen.cursor = 1
    screen.action_cursor_up()  # 717 verdadero
    assert screen.cursor == 0
    screen.cursor = -1
    screen.action_cursor_down()  # 721 verdadero (guardia defensiva)
    assert screen.cursor == 0
    screen.cursor = 0
    screen.action_cursor_down()  # falso
    assert screen.cursor == 0


# ---------------------------------------------------------------------------
# app.py — ModelPicker / ModelSelect
# ---------------------------------------------------------------------------


def test_app_model_picker_mount_bounds_edit(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import SDD_PHASES, ModelPickerScreen

    ctx_var.set(TUIContext(version="test"))
    screen = ModelPickerScreen()
    screen.on_mount()  # 782 -> _render_list -> 785
    screen.cursor = 1
    screen.action_cursor_up()  # 789 verdadero
    assert screen.cursor == 0
    screen.cursor = 0
    screen.action_cursor_up()
    assert screen.cursor == 0
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.cursor = len(SDD_PHASES)
    screen.action_cursor_down()  # falso 792 (bug permite == len)
    assert screen.cursor == len(SDD_PHASES)
    mock = _mock_app(monkeypatch, screen)
    screen.action_edit()  # falso 796: cursor fuera de rango no empuja
    mock.push_screen.assert_not_called()
    screen.cursor = 0
    screen.action_edit()  # verdadero
    mock.push_screen.assert_called()


def test_app_model_select_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import MODEL_OPTIONS, ModelSelectScreen

    ctx_var.set(TUIContext(version="test"))
    screen = ModelSelectScreen(phase="sdd-init")
    screen.cursor = 3
    screen.action_cursor_up()  # 835 verdadero
    assert screen.cursor == 2
    screen.cursor = 0
    screen.action_cursor_up()
    assert screen.cursor == 0
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.cursor = len(MODEL_OPTIONS) - 1
    screen.action_cursor_down()  # falso 838
    assert screen.cursor == len(MODEL_OPTIONS) - 1


# ---------------------------------------------------------------------------
# app.py — DxrkApp actions + run()
# ---------------------------------------------------------------------------


def test_app_actions_and_run(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import DxrkApp, run

    ctx = TUIContext(version="test")
    ctx_var.set(ctx)
    app = DxrkApp(ctx=ctx)
    app.push_screen = MagicMock()
    app.action_chat()  # 1038
    app.push_screen.assert_called_with("chat")
    app.action_providers()  # 1041
    app.push_screen.assert_called_with("providers")
    calls: list[str] = []
    monkeypatch.setattr(DxrkApp, "run", lambda self: calls.append("ran"))
    run(version="cov100", initial_screen="welcome")  # 1048-1053
    assert calls == ["ran"]


def test_app_neon_theme_contract(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.app import DXRK_NEON, DxrkApp

    ctx = TUIContext(version="test")
    ctx_var.set(ctx)
    app = DxrkApp(ctx=ctx)

    assert DXRK_NEON.name == "dxrk-neon"
    assert DXRK_NEON.primary == "#00f0ff"
    assert DXRK_NEON.secondary == "#b026ff"
    assert DXRK_NEON.dark is True
    assert app.theme == "dxrk-neon"
    assert "dxrk-neon" in app.available_themes


# ---------------------------------------------------------------------------
# chat_backend.py
# ---------------------------------------------------------------------------


def test_chat_backend_find_candidate(tmp_path, monkeypatch):
    import shutil

    monkeypatch.delenv("DXRK_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path / "h"))
    monkeypatch.setattr("os.path.isfile", lambda _: True)
    monkeypatch.setattr("os.access", lambda *a: True)
    found = find_opencode_binary()  # 33
    assert found.endswith("opencode")


def test_chat_backend_collect_list_and_other():
    assert collect_text_chunks([{"type": "text", "text": "a"}, {"role": "user", "content": "x"}]) == ["a"]  # 65-66
    assert collect_text_chunks([]) == []
    assert collect_text_chunks("plain") == []  # ni dict ni lista
    assert collect_text_chunks(42) == []


class _FakeRun:
    def __init__(self, rc=0, out="", err=""):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


def _patch_run(monkeypatch, fake):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)


def test_chat_backend_send_with_all_options(tmp_path, monkeypatch):
    line = json.dumps({"type": "text", "text": "hola"})
    seen: dict[str, object] = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return _FakeRun(0, line + "\n", "Session abc12345 lista")

    monkeypatch.setattr(subprocess, "run", fake)
    b = ChatBackend(binary="/bin/opencode", model="m", session="", directory="/tmp", timeout=5)
    reply = b.send("hi")  # 124, 126, 128, 145-147
    assert reply.text == "hola"
    assert b.session == "abc12345"
    cmd = seen["cmd"]
    assert "--model" in cmd and "--session" not in cmd and "--dir" in cmd


def test_chat_backend_send_session_noise_keeps_empty(tmp_path, monkeypatch):
    line = json.dumps({"type": "text", "text": "ok"})
    _patch_run(monkeypatch, _FakeRun(0, line, "ruido sin id de sesion"))
    b = ChatBackend(binary="/bin/opencode")
    assert b.send("hi").text == "ok"
    assert b.session == ""  # 146->148: sin id no se guarda
    # con sesión ya fijada se envía --session (126)
    seen: dict[str, object] = {}

    def fake(cmd, **kw):
        seen["cmd"] = cmd
        return _FakeRun(0, line, "")

    monkeypatch.setattr(subprocess, "run", fake)
    b2 = ChatBackend(binary="/bin/opencode", session="ses-123")
    assert b2.send("hi").text == "ok"
    assert "--session" in seen["cmd"] and "ses-123" in seen["cmd"]


def test_chat_backend_send_failures(tmp_path, monkeypatch):
    b = ChatBackend(binary="/bin/opencode")
    _patch_run(monkeypatch, _FakeRun(3, "out-oops", ""))
    assert "out-oops" in b.send("hi").text  # stderr vacío -> stdout
    _patch_run(monkeypatch, _FakeRun(3, "", ""))
    assert "desconocido" in b.send("hi").text  # ambos vacíos

    def boom(*a, **k):
        raise OSError("no exec")

    monkeypatch.setattr(subprocess, "run", boom)
    assert "error del backend" in b.send("hi").text  # 138-139
    _patch_run(monkeypatch, _FakeRun(0, "\n", ""))
    assert ChatBackend(binary="/bin/opencode").send("hi").text == "(respuesta vacía)"


def test_chat_backend_slash_free_and_memory(tmp_path, monkeypatch):
    b = ChatBackend(binary="/nonexistent/opencode")
    r = b.handle_slash("/free")  # 168-169
    assert b.model == FREE_DEFAULT_MODEL and "gratuito" in r.reply
    assert "/memory" in b.handle_slash("/h").reply
    monkeypatch.setattr(b, "_search_memory", lambda q: f"hit:{q}")
    assert b.handle_slash("/memory alfa").reply == "hit:alfa"  # 184


def test_chat_backend_search_memory_branches(tmp_path, monkeypatch):
    b = ChatBackend(binary="/nonexistent/opencode")
    assert "uso:" in b.handle_slash("/memory").reply

    def boom(*a, **k):
        raise OSError("spawn fail")

    monkeypatch.setattr(subprocess, "run", boom)
    assert "error al buscar" in b._search_memory("q")  # 200-201
    _patch_run(monkeypatch, _FakeRun(1, "", "boom"))
    assert "boom" in b._search_memory("q")  # 203-205 stderr
    _patch_run(monkeypatch, _FakeRun(1, "solo-out", ""))
    assert "solo-out" in b._search_memory("q")  # detail = stdout
    _patch_run(monkeypatch, _FakeRun(1, "", ""))
    assert "desconocido" in b._search_memory("q")
    _patch_run(monkeypatch, _FakeRun(0, "  hit  ", ""))
    assert b._search_memory("q") == "hit"
    _patch_run(monkeypatch, _FakeRun(0, "   ", ""))
    assert "sin resultados" in b._search_memory("q")  # 206


def test_chat_backend_guess_session_id():
    assert _guess_session_id("") == ""  # 220->227
    assert _guess_session_id("hello world") == ""
    assert _guess_session_id("session ab") == ""  # token corto 222->220
    assert _guess_session_id("session abc12345 extra") == "abc12345"
    assert _guess_session_id("SESSION xyz-123_abc") == "xyz-123_abc"
    assert _guess_session_id("session abc!defg") == ""  # 223->220: char inválido
    assert parse_json_events("") == ""


def test_chat_backend_env_override_not_executable(tmp_path, monkeypatch):
    import shutil

    fake = tmp_path / "opencode"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(stat.S_IMODE(os.stat(fake).st_mode) & ~stat.S_IEXEC)
    monkeypatch.setenv("DXRK_OPENCODE_BIN", str(fake))
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path / "h2"))
    assert find_opencode_binary() == ""


# ---------------------------------------------------------------------------
# screens/backups.py (nuevo BackupsScreen rico + confirms)
# ---------------------------------------------------------------------------


def test_rich_backups_compose_and_mount(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from textual.widget import Widget

    from dxrk.tui.screens.backups import BackupsScreen

    ctx_var.set(TUIContext(version="test", backups=[{"id": "a", "display_label": "A"}]))
    monkeypatch.setattr(BackupsScreen, "watch_cursor", lambda self, o, n: None)
    assert len(_compose(BackupsScreen())) > 0  # 30-36
    monkeypatch.setattr(Widget, "_render", lambda self: "v")  # type: ignore[attr-defined]
    screen = BackupsScreen()
    q = MagicMock(side_effect=lambda *a, **k: _mock_scroll())
    monkeypatch.setattr(screen, "query_one", q)
    screen.on_mount()  # 39 -> _render
    assert q.called


def test_rich_backups_render_pagination(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from textual.widget import Widget

    from dxrk.tui.screens.backups import BackupsScreen

    monkeypatch.setattr(Widget, "_render", lambda self: "v")  # type: ignore[attr-defined]
    monkeypatch.setattr(BackupsScreen, "watch_cursor", lambda self, o, n: None)
    snaps = [
        {"id": f"s{i}", "display_label": f"L{i}", "created_by_version": "1.0", "description": "d"} for i in range(12)
    ]
    ctx_var.set(TUIContext(version="test", backups=list(snaps)))
    screen = BackupsScreen()
    screen.list_offset = 0
    q = MagicMock(side_effect=lambda *a, **k: _mock_scroll())
    monkeypatch.setattr(screen, "query_one", q)
    screen._render()  # con ↓ más (72-73)
    assert q.called
    screen.list_offset = 3
    screen._render()  # con ↑ más (56)
    # lista chica: sin ↓ (72->75)
    ctx_var.set(TUIContext(version="test", backups=[{"id": "solo"}]))
    screen2 = BackupsScreen()
    monkeypatch.setattr(screen2, "query_one", lambda *a, **k: _mock_scroll())
    screen2._render()


def test_rich_backups_update_list_guard_and_break(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.backups import BackupsScreen

    ctx_var.set(TUIContext(version="test", backups=[]))
    monkeypatch.setattr(BackupsScreen, "watch_cursor", lambda self, o, n: None)
    fresh = BackupsScreen()
    fresh._update_list()  # 82: sin _backup_statics
    # statics más largos que backups -> break (89)
    fresh._backup_statics = [MagicMock(), MagicMock()]
    for s in fresh._backup_statics:
        s.update = MagicMock()
    fresh._update_list()
    for s in fresh._backup_statics:
        s.update.assert_not_called()


def test_rich_backups_watch_three_branches(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.backups import BackupsScreen

    ctx_var.set(TUIContext(version="test", backups=[{"id": f"s{i}"} for i in range(12)]))
    real_watch = BackupsScreen.watch_cursor
    monkeypatch.setattr(BackupsScreen, "watch_cursor", lambda self, o, n: None)
    screen = BackupsScreen()
    rendered: list[str] = []
    updated: list[str] = []
    monkeypatch.setattr(screen, "_render", lambda: rendered.append("r"))
    monkeypatch.setattr(screen, "_update_list", lambda: updated.append("u"))
    screen.list_offset = 0
    real_watch(screen, 0, 3)  # else -> _update_list
    assert updated == ["u"]
    real_watch(screen, 0, 11)  # elif -> offset + _render
    assert screen.list_offset == 2 and rendered
    screen.list_offset = 5
    real_watch(screen, 5, 0)  # new < offset -> _render
    assert screen.list_offset == 0


def test_rich_backups_cursor_bounds_and_noops(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.backups import BackupsScreen

    ctx_var.set(TUIContext(version="test", backups=[{"id": "a"}, {"id": "b"}]))
    monkeypatch.setattr(BackupsScreen, "watch_cursor", lambda self, o, n: None)
    screen = BackupsScreen()
    mock = _mock_app(monkeypatch, screen)
    screen.cursor = 0
    screen.action_cursor_up()  # falso 111
    assert screen.cursor == 0
    screen.cursor = 2
    screen.action_cursor_up()
    assert screen.cursor == 1
    screen.cursor = 0
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.cursor = 2  # total = 2 + 1
    screen.action_cursor_down()  # falso 117
    assert screen.cursor == 2
    # fuera de rango: no-ops (133, 139, 145 falsos)
    screen.action_rename()
    screen.action_delete()
    screen.action_pin()
    mock.push_screen.assert_not_called()
    # select en "Atrás" -> welcome; con backup -> restore
    screen.action_select()
    mock.push_screen.assert_called_with("welcome")
    screen.cursor = 0
    screen.action_select()
    mock.push_screen.assert_called_with("restore_confirm")
    assert ctx_var.get().selected_backup == {"id": "a"}
    screen.action_rename()
    mock.push_screen.assert_called_with("rename_backup")
    screen.action_delete()
    mock.push_screen.assert_called_with("delete_confirm")
    before = ctx_var.get().backups[0].get("pinned", False)
    screen.action_pin()
    assert ctx_var.get().backups[0]["pinned"] is not before


def test_rich_backups_confirms_cursor_and_rename_desc(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.backups import DeleteConfirmScreen, RenameBackupScreen, RestoreConfirmScreen

    ctx_var.set(
        TUIContext(
            version="test",
            selected_backup={"id": "x", "display_label": "L", "description": "importante"},
        )
    )
    assert len(_compose(RenameBackupScreen())) > 0  # 261-262 con descripción
    rs = RestoreConfirmScreen()
    rs.cursor = 0
    rs.action_cursor_up()  # falso 184
    assert rs.cursor == 0
    rs.cursor = 1
    rs.action_cursor_up()  # 229-230 verdadero
    assert rs.cursor == 0
    rs.cursor = 0
    rs.action_cursor_down()
    assert rs.cursor == 1
    rs.cursor = 1
    rs.action_cursor_down()  # falso 188
    assert rs.cursor == 1
    ds = DeleteConfirmScreen()
    ds.cursor = 0
    ds.action_cursor_up()  # falso
    assert ds.cursor == 0
    ds.cursor = 1
    ds.action_cursor_up()  # 229-230 verdadero
    assert ds.cursor == 0
    ds.cursor = 0
    ds.action_cursor_down()  # 233-234 verdadero
    assert ds.cursor == 1
    ds.action_cursor_down()  # falso
    assert ds.cursor == 1


# ---------------------------------------------------------------------------
# screens/chat.py
# ---------------------------------------------------------------------------


def _chat_screen(monkeypatch, history=None):  # type: ignore[no-untyped-def]
    from dxrk.tui.screens.chat import ChatScreen

    b = ChatBackend(binary="/nonexistent/opencode")
    screen = ChatScreen(backend=b)
    log = MagicMock()
    log.write = MagicMock()
    log.clear = MagicMock()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: log)
    if history is not None:
        screen.history = list(history)
    return screen, log


def test_chat_welcome_without_backend(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.chat import ChatScreen

    b = ChatBackend(binary="")
    b.binary = ""  # fuerza no disponible tras __post_init__
    screen = ChatScreen(backend=b)
    assert "solo local" in screen._welcome_text()  # 56
    b2 = ChatBackend(binary="/nonexistent/opencode")
    assert "listo" in ChatScreen(backend=b2)._welcome_text().lower()


def test_chat_submit_empty_and_slash_branches(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    ctx_var.set(TUIContext(version="test"))
    screen, _ = _chat_screen(monkeypatch)

    def ev(value):  # type: ignore[no-untyped-def]
        return types.SimpleNamespace(value=value, input=types.SimpleNamespace(value=value))

    screen._on_composer_submitted(ev("   "))  # 78
    assert screen.history == []
    screen._on_composer_submitted(ev("/help"))  # 82-86 reply
    assert any("/memory" in m.text for m in screen.history)
    screen2, _ = _chat_screen(monkeypatch)
    screen2._on_composer_submitted(ev("/clear"))  # 83-84 clear
    assert screen2.history[-1].text == "Conversación borrada."
    screen3, _ = _chat_screen(monkeypatch)
    monkeypatch.setattr(screen3.backend, "handle_slash", lambda t: SlashResult(handled=True, reply="", clear=False))
    screen3._on_composer_submitted(ev("/x"))  # 85->87: ni clear ni reply
    assert len(screen3.history) == 1 and screen3.history[0].role == "user"


def test_chat_deliver_system_and_drop_mixed(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    ctx_var.set(TUIContext(version="test"))

    class _Sys(ChatBackend):
        def send(self, message: str) -> ChatMessage:
            return ChatMessage(role="system", text="sys-boom")

    from dxrk.tui.screens.chat import ChatScreen

    screen = ChatScreen(backend=_Sys(binary="/nonexistent/opencode"))
    log = MagicMock()
    log.write = MagicMock()
    log.clear = MagicMock()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: log)
    screen.history = [ChatMessage(role="system", text="pensando…")]
    asyncio.run(screen._deliver("hola"))  # 96-97 sistema
    assert [m.text for m in screen.history] == ["sys-boom"]

    screen2, log2 = _chat_screen(
        monkeypatch,
        [
            ChatMessage(role="user", text="u1"),
            ChatMessage(role="assistant", text="a1"),  # 112-114
            ChatMessage(role="system", text="nota"),
            ChatMessage(role="system", text="pensando…"),
        ],
    )
    screen2._drop_thinking()
    assert [m.text for m in screen2.history] == ["u1", "a1", "nota"]
    assert log2.clear.called and log2.write.call_count == 3

    screen3, log3 = _chat_screen(monkeypatch, [ChatMessage(role="user", text="x")])
    screen3._drop_thinking()  # 102 falso: no-op
    assert [m.text for m in screen3.history] == ["x"]
    log3.clear.assert_not_called()


# ---------------------------------------------------------------------------
# screens/dependency_tree.py
# ---------------------------------------------------------------------------


def test_dependency_tree_preset_mixed_steps(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from textual.widget import Widget

    from dxrk.models import PresetID
    from dxrk.tui.context import ctx_var as _cv
    from dxrk.tui.screens.dependency_tree import ALL_COMPONENTS, DependencyTreeScreen

    monkeypatch.setattr(Widget, "_render", lambda self: "v")  # type: ignore[attr-defined]
    known = ALL_COMPONENTS[0]
    step_ok = types.SimpleNamespace(id=known.id.value, name="Conocido")
    step_rare = types.SimpleNamespace(id="no-existe-tal-id", name="Raro")
    plan = types.SimpleNamespace(steps=[step_ok, step_rare])
    _cv.set(TUIContext(version="test", preset=PresetID.FULL_DXRK, plan=plan))  # type: ignore[arg-type]
    monkeypatch.setattr(DependencyTreeScreen, "watch_cursor", lambda self, o, n: None)
    screen = DependencyTreeScreen()
    scroll = _mock_scroll()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: scroll)
    screen._render()  # con descripción (68-69) y sin match (67->61 falso)
    assert scroll.mount.call_count >= 6
    assert len(screen._action_statics) == 2
    screen._update_actions()
    assert "Continuar" in str(screen._action_statics[0].content)
    # guard sin statics
    DependencyTreeScreen()._update_actions()  # 114


def test_dependency_tree_counts_watch_break_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.models import PresetID
    from dxrk.tui.screens.dependency_tree import ALL_COMPONENTS, DependencyTreeScreen

    ctx_var.set(TUIContext(version="test", preset=PresetID.FULL_DXRK))
    real_watch = DependencyTreeScreen.watch_cursor
    monkeypatch.setattr(DependencyTreeScreen, "watch_cursor", lambda self, o, n: None)
    screen = DependencyTreeScreen()
    assert screen._comp_count() == 0  # 123 no-custom
    ctx_var.set(TUIContext(version="test", preset=PresetID.CUSTOM))
    assert screen._comp_count() == len(ALL_COMPONENTS)
    assert screen._total_options() == len(ALL_COMPONENTS) + 2
    # watch custom llama a _update_component_list
    seen: list[str] = []
    monkeypatch.setattr(screen, "_update_component_list", lambda: seen.append("c"))
    monkeypatch.setattr(screen, "_update_actions", lambda: seen.append("a"))
    real_watch(screen, 0, 1)  # 130
    assert seen == ["c", "a"]
    # _update_component_list con statics de más -> break (136)
    many = [MagicMock() for _ in range(len(ALL_COMPONENTS) + 2)]
    for m in many:
        m.update = MagicMock()
    screen_b = DependencyTreeScreen()
    screen_b._component_statics = many
    screen_b._update_component_list()
    many[-1].update.assert_not_called()
    # guard sin statics
    DependencyTreeScreen()._update_component_list()  # 132 falso
    # bounds: up verdadero, down en máximo falso
    screen.cursor = 2
    screen.action_cursor_up()  # 147
    assert screen.cursor == 1
    screen.cursor = screen._total_options() - 1
    screen.action_cursor_down()  # 151 falso
    assert screen.cursor == screen._total_options() - 1


def test_dependency_tree_toggle_cases(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.models import PresetID
    from dxrk.tui.screens.dependency_tree import ALL_COMPONENTS, DependencyTreeScreen

    monkeypatch.setattr(DependencyTreeScreen, "watch_cursor", lambda self, o, n: None)
    # no-custom: return inmediato (156)
    ctx = TUIContext(version="test", preset=PresetID.FULL_DXRK, selected_components=[])
    ctx_var.set(ctx)
    screen = DependencyTreeScreen()
    screen._update_component_list = MagicMock()  # type: ignore[method-assign]
    asyncio.run(screen.action_toggle())
    screen._update_component_list.assert_not_called()
    # custom remove (160-161) y append
    first = ALL_COMPONENTS[0].id
    ctx2 = TUIContext(version="test", preset=PresetID.CUSTOM, selected_components=[first])
    ctx_var.set(ctx2)
    screen2 = DependencyTreeScreen()
    screen2._component_statics = []
    screen2.cursor = 0
    asyncio.run(screen2.action_toggle())
    assert first not in ctx2.selected_components
    screen2.cursor = 1
    asyncio.run(screen2.action_toggle())
    assert ALL_COMPONENTS[1].id in ctx2.selected_components
    # custom fuera de rango: no-op (157 falso)
    screen2.cursor = len(ALL_COMPONENTS) + 5
    asyncio.run(screen2.action_toggle())


# ---------------------------------------------------------------------------
# screens/detection.py (nuevo DetectionScreen rico)
# ---------------------------------------------------------------------------


def test_rich_detection_compose_mount_and_variants(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from textual.widget import Widget

    from dxrk.tui.screens.detection import DetectionScreen

    monkeypatch.setattr(Widget, "_render", lambda self: "v")  # type: ignore[attr-defined]
    ctx_var.set(TUIContext(version="test", detection=_full_detection()))
    assert len(_compose(DetectionScreen())) > 0  # 25-28
    screen = DetectionScreen()
    scroll = _mock_scroll()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: scroll)
    screen.on_mount()  # 31 -> _render lleno: tools, deps, missing, configs
    assert scroll.mount.call_count > 10
    # variantes vacías: tools {} (49->56), deps [] (57->72), configs [] (72->79)
    ctx_var.set(TUIContext(version="test", detection=_empty_detection()))
    screen2 = DetectionScreen()
    scroll2 = _mock_scroll()
    monkeypatch.setattr(screen2, "query_one", lambda *a, **k: scroll2)
    screen2._render()
    assert scroll2.mount.called


def test_rich_detection_update_watch_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.detection import DetectionScreen

    ctx_var.set(TUIContext(version="test", detection=_full_detection()))
    fresh = DetectionScreen()
    fresh._update_actions()  # 92-93 guard
    screen = DetectionScreen()
    scroll = _mock_scroll()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: scroll)
    from textual.widget import Widget

    monkeypatch.setattr(Widget, "_render", lambda self: "v")  # type: ignore[attr-defined]
    screen._render()
    assert len(screen._action_statics) == 2  # 94-97 loop
    screen._update_actions()
    assert "Continuar" in str(screen._action_statics[0].content)
    seen: list[str] = []
    monkeypatch.setattr(screen, "_update_actions", lambda: seen.append("u"))
    DetectionScreen.watch_cursor(screen, 0, 1)  # 100
    assert seen == ["u"]
    screen2 = DetectionScreen()
    monkeypatch.setattr(screen2, "_update_actions", lambda: None)
    screen2.cursor = 0
    screen2.action_cursor_up()  # falso
    assert screen2.cursor == 0
    screen2.cursor = 1
    screen2.action_cursor_up()
    assert screen2.cursor == 0
    screen2.action_cursor_down()
    assert screen2.cursor == 1
    screen2.action_cursor_down()  # falso 107
    assert screen2.cursor == 1


# ---------------------------------------------------------------------------
# screens/providers.py
# ---------------------------------------------------------------------------


def test_providers_up_select_submit_save(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens.providers import ProvidersScreen

    ctx_var.set(TUIContext(version="test"))
    screen = ProvidersScreen()
    screen.cursor = 2
    screen.action_cursor_up()  # 76
    assert screen.cursor == 1
    msg = MagicMock()
    msg.update = MagicMock()
    inp = MagicMock()
    inp.focus = MagicMock()
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: msg if "msg" in str(a) else inp)
    screen.cursor = 0
    screen.action_select()  # 82-86 free
    assert "sin token" in str(msg.update.call_args[0][0])
    screen.cursor = 1
    screen.action_select()  # pago -> foco al input
    assert inp.focus.called
    # submit ajeno se ignora (93)
    screen.on_input_submitted(types.SimpleNamespace(input=types.SimpleNamespace(id="otro"), value="x"))
    # save vacío (99-100)
    asyncio.run(screen._save_token("   "))
    assert "token" in str(msg.update.call_args[0][0]).lower()


def test_providers_save_branches(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui import providers_backend as backend
    from dxrk.tui.screens.providers import ProvidersScreen

    ctx_var.set(TUIContext(version="test"))
    screen = ProvidersScreen()
    screen.cursor = 1
    screen._connected = set()
    msg = MagicMock()
    msg.update = MagicMock()
    inp = MagicMock()
    inp.value = "x"
    monkeypatch.setattr(screen, "query", lambda *a, **k: [])
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: msg if "msg" in str(a) else inp)
    # "id token" (102) con backend ok
    saved: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(backend, "validate_provider_id", lambda *a, **k: True)
    monkeypatch.setattr(backend, "save_api_token", lambda p, t, path="": saved.setdefault("args", (p, t)) or "wrote")
    monkeypatch.setattr(backend, "connected_providers", lambda path="": {"openrouter"})
    asyncio.run(screen._save_token("openrouter tok-1"))
    assert saved["args"] == ("openrouter", "tok-1")
    assert inp.value == ""
    # proveedor inválido (108-109)
    asyncio.run(screen._save_token("nope tok"))
    assert "no válido" in str(msg.update.call_args[0][0])
    # opencode no lo reconoce (111-112)
    monkeypatch.setattr(backend, "validate_provider_id", lambda *a, **k: False)
    asyncio.run(screen._save_token("openrouter tok"))
    assert "no reconoce" in str(msg.update.call_args[0][0])
    # ValueError (115-117) y OSError (118-120)
    monkeypatch.setattr(backend, "validate_provider_id", lambda *a, **k: True)

    def vre(*a, **k):
        raise ValueError("token vacío")

    monkeypatch.setattr(backend, "save_api_token", vre)
    asyncio.run(screen._save_token("openrouter tok"))
    assert "token vacío" in str(msg.update.call_args[0][0])

    def ose(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(backend, "save_api_token", ose)
    asyncio.run(screen._save_token("openrouter tok"))
    assert "No se pudo guardar" in str(msg.update.call_args[0][0])


# ---------------------------------------------------------------------------
# pilot run_test: montaje real de las pantallas ricas + chat + providers
# ---------------------------------------------------------------------------


async def test_pilot_rich_screens_chat_providers(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from textual.widgets import Static

    from dxrk.tui.app import DxrkApp
    from dxrk.tui.chat_backend import ChatBackend
    from dxrk.tui.screens.backups import BackupsScreen as RichBackups
    from dxrk.tui.screens.chat import ChatScreen
    from dxrk.tui.screens.detection import DetectionScreen as RichDetection

    snaps = [
        {"id": f"s{i}", "display_label": f"L{i}", "created_by_version": "1.0", "description": "d"} for i in range(12)
    ]
    ctx = TUIContext(version="cov100", backups=list(snaps), detection=_full_detection())
    token = ctx_var.set(ctx)
    try:
        app = DxrkApp(ctx)
        async with app.run_test() as pilot:
            await app.push_screen(RichBackups())
            await pilot.pause()
            assert app.screen.query_one("#backup-list")
            await app.push_screen(RichDetection())
            await pilot.pause()
            assert app.screen.query_one("#detection-results")
            await app.push_screen(ChatScreen(backend=ChatBackend(binary="/nonexistent/opencode")))
            await pilot.pause()
            composer = app.screen.query_one("#chat-composer")
            composer.focus()
            await pilot.press(*"/help")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert any("/memory" in m.text for m in app.screen.history)
            await app.push_screen("providers")
            await pilot.pause()
            prov = app.screen
            prov.cursor = 0
            prov.action_select()
            await pilot.pause()
            assert "sin token" in str(prov.query_one("#providers-msg", Static).content)
    finally:
        ctx_var.reset(token)
