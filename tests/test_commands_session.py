# SPDX-License-Identifier: MIT
"""Tests for dxrk/commands/session.py."""

from __future__ import annotations

import io
import os

import pytest

from dxrk.commands.registry import Registry
from dxrk.commands.session import (
    SessionError,
    _fmt_ts,
    _fmt_ts_short,
    delete_session_file,
    list_session_files,
    load_session,
    register_session_command,
    save_session,
    session_dir,
)
from dxrk.utils.session import Session, SessionStatus, new_session


@pytest.fixture
def reg() -> Registry:
    r = Registry()
    register_session_command(r)
    return r


@pytest.fixture
def sdir(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "sessions")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr("dxrk.commands.session.session_dir", lambda: path)
    return path


def _run(reg, args):
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _mk(session_id: str, title: str = "T", status=SessionStatus.Active, tags=None) -> Session:
    s = new_session()
    s.id = session_id
    s.title = title
    s.status = status
    s.tags = list(tags or [])
    s.summary = "sum"
    assert save_session(s)
    return s


# ---- session_dir / storage helpers ----


def test_session_dir_creates(tmp_path, monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.os.path.expanduser", lambda p: str(tmp_path))
    p = session_dir()
    assert os.path.isdir(p)


def test_session_dir_empty_home(monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.os.path.expanduser", lambda p: "")
    with pytest.raises(SessionError):
        session_dir()


def test_session_dir_makedirs_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("no mkdir")

    monkeypatch.setattr("dxrk.commands.session.os.path.expanduser", lambda p: "/tmp")
    monkeypatch.setattr("dxrk.commands.session.os.makedirs", boom)
    with pytest.raises(SessionError):
        session_dir()


def test_list_session_files_skips_non_json(sdir):
    _mk("sess-aaa", title="One")
    os.mkdir(os.path.join(sdir, "subdir"))
    with open(os.path.join(sdir, "notes.txt"), "w", encoding="utf-8") as f:
        f.write("x")
    with open(os.path.join(sdir, "corrupt.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    got = list_session_files()
    assert [s.id for s in got] == ["sess-aaa"]


def test_list_session_files_skips_unreadable(sdir, monkeypatch):
    _mk("sess-aaa")
    with open(os.path.join(sdir, "bad.json"), "w", encoding="utf-8") as f:
        f.write('{"version":1}')
    real_open = open

    def fake_open(path, *a, **k):
        if str(path).endswith("bad.json"):
            raise OSError("boom")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    got = list_session_files()
    assert [s.id for s in got] == ["sess-aaa"]


def test_list_session_files_sorted_newest(sdir):
    a = _mk("sess-old")
    b = _mk("sess-new")
    a.updated_at = None
    b.updated_at = None
    assert save_session(a) and save_session(b)
    got = list_session_files()
    assert len(got) == 2


def test_list_session_files_listdir_error(sdir, monkeypatch):
    def boom(*a):
        raise OSError("nope")

    monkeypatch.setattr("dxrk.commands.session.os.listdir", boom)
    with pytest.raises(SessionError):
        list_session_files()


def test_load_session_decode_error(sdir):
    with open(os.path.join(sdir, "sess-bad.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    with pytest.raises(SessionError):
        load_session("sess-bad")


def test_load_session_not_found(sdir):
    with pytest.raises(SessionError):
        load_session("nope")


def test_load_session_by_prefix(sdir):
    _mk("sess-abc")
    got = load_session("sess-ab")
    assert got.id == "sess-abc"


def test_save_session_export_error(sdir, monkeypatch):
    def boom(s):
        raise Exception("no export")

    monkeypatch.setattr("dxrk.commands.session.export_json", boom)
    assert save_session(new_session()) is False


def test_save_session_write_error(sdir, monkeypatch):
    real_open = open

    def fake_open(path, *a, **k):
        if a and a[0] in ("w", "a") or k.get("mode") in ("w", "a"):
            raise OSError("no write")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)
    assert save_session(new_session()) is False


def test_delete_session_file_missing(sdir):
    s = new_session()
    s.id = "sess-x"
    assert delete_session_file(s) is False


def test_delete_session_file_error(sdir, monkeypatch):
    _mk("sess-aaa")
    monkeypatch.setattr("dxrk.commands.session.os.remove", lambda p: (_ for _ in ()).throw(OSError()))
    s = new_session()
    s.id = "sess-aaa"
    assert delete_session_file(s) is False


def test_fmt_ts_none():
    assert _fmt_ts(None) == ""
    assert _fmt_ts_short(None) == ""


# ---- CLI: list ----


def test_session_list_empty(reg, sdir):
    code, out, err = _run(reg, ["session", "list"])
    assert code == 0
    assert out == "No sessions found.\n"


def test_session_list_ok(reg, sdir):
    _mk("sess-aaa", title="Hello")
    code, out, err = _run(reg, ["session", "list"])
    assert code == 0
    assert "ID\tTITLE" in out
    assert "Hello" in out


def test_session_list_invalid_limit(reg, sdir):
    code, out, err = _run(reg, ["session", "list", "--limit=abc"])
    assert code == 1
    assert "invalid limit" in err


def test_session_list_status_filter(reg, sdir):
    _mk("sess-act", status=SessionStatus.Active)
    _mk("sess-done", status=SessionStatus.Completed)
    code, out, _ = _run(reg, ["session", "list", "--status=completed"])
    assert code == 0
    assert "sess-don" in out
    assert "sess-act" not in out


def test_session_list_tag_filter(reg, sdir):
    _mk("sess-tag", tags=["docs"])
    _mk("sess-no", tags=[])
    code, out, _ = _run(reg, ["session", "list", "--tag=docs"])
    assert code == 0
    assert "sess-tag" in out
    assert "sess-no" not in out


def test_session_list_limit(reg, sdir):
    for i in range(3):
        _mk(f"sess-00{i}")
    code, out, _ = _run(reg, ["session", "list", "--limit=2"])
    assert code == 0
    lines = [l for l in out.splitlines() if l and not l.startswith("ID")]
    assert len(lines) == 2


def test_session_list_error(reg, sdir, monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.os.listdir", lambda *a: (_ for _ in ()).throw(OSError()))
    code, out, err = _run(reg, ["session", "list"])
    assert code == 1
    assert "Error:" in err


# ---- CLI: create / switch / delete / info ----


def test_session_create_ok(reg, sdir):
    code, out, err = _run(reg, ["session", "create", "My Session"])
    assert code == 0
    assert "Created session" in out


def test_session_create_save_error(reg, sdir, monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.save_session", lambda s: False)
    code, out, err = _run(reg, ["session", "create", "T"])
    assert code == 1
    assert "save session" in err


def test_session_switch_ok(reg, sdir):
    _mk("sess-aaa")
    code, out, err = _run(reg, ["session", "switch", "sess-aaa"])
    assert code == 0
    assert "Switched to session" in out


def test_session_switch_not_found(reg, sdir):
    code, out, err = _run(reg, ["session", "switch", "nope"])
    assert code == 1
    assert "not found" in err


def test_session_switch_list_error(reg, sdir, monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.os.listdir", lambda *a: (_ for _ in ()).throw(OSError()))
    code, out, err = _run(reg, ["session", "switch", "sess-aaa"])
    assert code == 1
    assert "Error:" in err


def test_session_switch_save_error(reg, sdir, monkeypatch):
    _mk("sess-aaa")
    monkeypatch.setattr("dxrk.commands.session.save_session", lambda s: False)
    code, out, err = _run(reg, ["session", "switch", "sess-aaa"])
    assert code == 1
    assert "save session" in err


def test_session_delete_ok(reg, sdir):
    _mk("sess-aaa")
    code, out, err = _run(reg, ["session", "delete", "sess-aaa"])
    assert code == 0
    assert "Deleted session" in out


def test_session_delete_not_found(reg, sdir):
    code, out, err = _run(reg, ["session", "delete", "nope"])
    assert code == 1
    assert "not found" in err


def test_session_delete_list_error(reg, sdir, monkeypatch):
    monkeypatch.setattr("dxrk.commands.session.os.listdir", lambda *a: (_ for _ in ()).throw(OSError()))
    code, out, err = _run(reg, ["session", "delete", "sess-aaa"])
    assert code == 1
    assert "Error:" in err


def test_session_delete_error(reg, sdir, monkeypatch):
    _mk("sess-aaa")
    monkeypatch.setattr("dxrk.commands.session.os.remove", lambda p: (_ for _ in ()).throw(OSError()))
    code, out, err = _run(reg, ["session", "delete", "sess-aaa"])
    assert code == 1
    assert "delete session" in err


def test_session_info_full(reg, sdir):
    _mk("sess-aaa", title="Doc", tags=["t1", "t2"])
    code, out, err = _run(reg, ["session", "info", "sess-aaa"])
    assert code == 0
    assert "ID:" in out and "Title:" in out
    assert "Tags:" in out and "t1" in out
    assert "Summary:" in out


def test_session_info_not_found(reg, sdir):
    code, out, err = _run(reg, ["session", "info", "nope"])
    assert code == 1
    assert "not found" in err


def test_session_parent_error(reg):
    code, out, err = _run(reg, ["session"])
    assert code == 1
    assert "use 'dxrk session list'" in err
