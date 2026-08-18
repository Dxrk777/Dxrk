# SPDX-License-Identifier: MIT
"""Tests for dxrk/commands/hooks.py."""

from __future__ import annotations

import io
import json
import os

import pytest

from dxrk.commands.hooks import (
    HOOK_EVENTS,
    hooks_path,
    load_hooks,
    register_hooks_command,
    save_hooks,
)
from dxrk.commands.registry import Registry


@pytest.fixture
def reg() -> Registry:
    r = Registry()
    register_hooks_command(r)
    return r


@pytest.fixture
def hooks_file(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "hooks.json")
    monkeypatch.setattr("dxrk.commands.hooks.hooks_path", lambda: path)
    return path


def _run(reg, args):
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_hooks_path():
    p = hooks_path()
    assert p.endswith(os.path.join(".config", "dxrk", "hooks.json"))


def test_load_hooks_missing(hooks_file):
    assert load_hooks() == []


def test_load_hooks_corrupt_json(hooks_file):
    with open(hooks_file, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert load_hooks() == []


def test_load_hooks_oserror(tmp_path, monkeypatch):
    path = tmp_path / "dir.json"
    path.mkdir()
    monkeypatch.setattr("dxrk.commands.hooks.hooks_path", lambda: str(path))
    assert load_hooks() == []


def test_load_hooks_non_list(hooks_file):
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump({"name": "x"}, f)
    assert load_hooks() == []


def test_load_hooks_valid(hooks_file):
    data = [{"name": "fmt", "event": "pre-commit", "command": "ruff format", "enabled": True}]
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert load_hooks() == data


def test_save_hooks(hooks_file):
    hooks = [{"name": "fmt", "event": "pre-commit", "command": "ruff format", "enabled": True}]
    assert save_hooks(hooks) is True
    with open(hooks_file, encoding="utf-8") as f:
        assert json.load(f) == hooks


def test_save_hooks_oserror(tmp_path, monkeypatch):
    path = tmp_path / "blocked"
    path.write_text("x")
    monkeypatch.setattr("dxrk.commands.hooks.hooks_path", lambda: str(path / "hooks.json"))
    assert save_hooks([]) is False


def test_list_empty(reg):
    code, out, err = _run(reg, ["hooks", "list"])
    assert code == 0
    assert out == "No hooks configured.\n"
    assert err == ""


def test_list_with_hooks(reg, hooks_file):
    hooks = [
        {"name": "fmt", "event": "pre-commit", "command": "ruff format", "enabled": True},
        {"name": "push", "event": "pre-push", "command": "uv audit", "enabled": False},
    ]
    with open(hooks_file, "w", encoding="utf-8") as f:
        json.dump(hooks, f)
    code, out, err = _run(reg, ["hooks", "list"])
    assert code == 0
    assert out == (
        "NAME\tEVENT\tCOMMAND\tENABLED\nfmt\tpre-commit\truff format\ttrue\npush\tpre-push\tuv audit\tfalse\n"
    )
    assert err == ""


def test_add_valid(reg, hooks_file):
    code, out, err = _run(reg, ["hooks", "add", "fmt", "pre-commit", "ruff format"])
    assert code == 0
    assert out == 'Added hook "fmt" (pre-commit)\n'
    assert err == ""
    assert load_hooks() == [{"name": "fmt", "event": "pre-commit", "command": "ruff format", "enabled": True}]


def test_add_invalid_event(reg, hooks_file):
    code, out, err = _run(reg, ["hooks", "add", "fmt", "bogus", "echo hi"])
    assert code == 1
    assert out == ""
    assert err == 'Error: invalid event "bogus"\n'
    assert load_hooks() == []


def test_add_duplicate(reg, hooks_file):
    _run(reg, ["hooks", "add", "fmt", "pre-commit", "ruff format"])
    code, out, err = _run(reg, ["hooks", "add", "fmt", "pre-push", "uv audit"])
    assert code == 1
    assert out == ""
    assert err == 'Error: hook "fmt" already exists\n'
    assert len(load_hooks()) == 1


def test_add_save_failure(reg, hooks_file, monkeypatch):
    monkeypatch.setattr("dxrk.commands.hooks.save_hooks", lambda hooks: False)
    code, out, err = _run(reg, ["hooks", "add", "fmt", "pre-commit", "ruff format"])
    assert code == 1
    assert out == ""
    assert err == "Error: write hooks config\n"


def test_remove_valid(reg, hooks_file):
    _run(reg, ["hooks", "add", "fmt", "pre-commit", "ruff format"])
    code, out, err = _run(reg, ["hooks", "remove", "fmt"])
    assert code == 0
    assert out == 'Removed hook "fmt"\n'
    assert err == ""
    assert load_hooks() == []


def test_remove_not_found(reg, hooks_file):
    code, out, err = _run(reg, ["hooks", "remove", "nope"])
    assert code == 1
    assert out == ""
    assert err == 'Error: hook "nope" not found\n'


def test_remove_save_failure(reg, hooks_file, monkeypatch):
    _run(reg, ["hooks", "add", "fmt", "pre-commit", "ruff format"])
    monkeypatch.setattr("dxrk.commands.hooks.save_hooks", lambda hooks: False)
    code, out, err = _run(reg, ["hooks", "remove", "fmt"])
    assert code == 1
    assert out == ""
    assert err == "Error: write hooks config\n"


def test_hook_events_complete():
    assert HOOK_EVENTS == (
        "pre-commit",
        "post-commit",
        "pre-push",
        "pre-agent",
        "post-agent",
        "pre-tool",
        "post-tool",
        "session-start",
        "session-end",
    )
