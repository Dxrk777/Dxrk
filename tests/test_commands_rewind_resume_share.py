# SPDX-License-Identifier: MIT
"""Tests for dxrk/commands/rewind.py, resume.py and share.py.

Determinista: sin red ni sleeps. Las sesiones se crean de verdad en un
directorio temporal (monkeypatch sobre dxrk.commands.session.session_dir,
que es el que usan list/load/save); los errores de I/O se simulan con
monkeypatch siguiendo el precedente de tests/test_commands_session.py.
"""

from __future__ import annotations

import io
import os

import pytest

from dxrk.commands.registry import Registry
from dxrk.commands.resume import _truncate, register_resume_command
from dxrk.commands.rewind import register_rewind_command
from dxrk.commands.session import SessionError, save_session
from dxrk.commands.share import _share_body, register_share_command, share_session
from dxrk.utils.session import Message, Session, new_session


@pytest.fixture
def reg() -> Registry:
    r = Registry()
    register_rewind_command(r)
    register_resume_command(r)
    register_share_command(r)
    return r


@pytest.fixture
def sdir(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "sessions")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr("dxrk.commands.session.session_dir", lambda: path)
    return path


def _run(reg: Registry, args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _mk(session_id: str, title: str = "T", texts: list[str] | None = None) -> Session:
    s = new_session()
    s.id = session_id
    s.title = title
    for t in texts or []:
        s.add_message(Message(role="user", content=t))  # type: ignore[arg-type]
    assert save_session(s)
    return s


def _boom_listdir(*a: object) -> object:
    raise OSError("nope")


# ---- rewind ----


def test_rewind_ok_truncates_long_content(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", texts=["hola", "x" * 100])
    code, out, err = _run(reg, ["rewind", "sess-aaa", "1"])
    assert code == 0
    assert "retrocedida en 1 mensaje(s) (1 restantes)" in out
    assert "..." in out  # contenido largo truncado a 80 chars
    assert "[user]" in out
    from dxrk.commands.session import load_session

    assert [m.content for m in load_session("sess-aaa").messages] == ["hola"]


def test_rewind_removes_all_when_count_exceeds(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", texts=["a", "b"])
    code, out, err = _run(reg, ["rewind", "sess-aaa", "9"])
    assert code == 0
    assert "(0 restantes)" in out


def test_rewind_invalid_count(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["rewind", "sess-aaa", "abc"])
    assert code == 1
    assert "cantidad de mensajes inválida" in err


def test_rewind_zero_count(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["rewind", "sess-aaa", "0"])
    assert code == 1
    assert ">= 1" in err


def test_rewind_list_error(reg: Registry, sdir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dxrk.commands.rewind.list_session_files", lambda: (_ for _ in ()).throw(SessionError("boom")))
    code, out, err = _run(reg, ["rewind", "sess-aaa", "1"])
    assert code == 1
    assert "boom" in err


def test_rewind_no_sessions(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["rewind", "sess-aaa", "1"])
    assert code == 1
    assert "no se encontraron sesiones" in err


def test_rewind_not_found(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", texts=["a"])
    code, out, err = _run(reg, ["rewind", "other", "1"])
    assert code == 1
    assert "no encontrada" in err


def test_rewind_empty_session(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa")
    code, out, err = _run(reg, ["rewind", "sess-aaa", "1"])
    assert code == 1
    assert "no tiene mensajes" in err


def test_rewind_save_error(reg: Registry, sdir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _mk("sess-aaa", texts=["a"])
    monkeypatch.setattr("dxrk.commands.rewind.save_session", lambda s: False)
    code, out, err = _run(reg, ["rewind", "sess-aaa", "1"])
    assert code == 1
    assert "al guardar" in err


# ---- resume ----


def test_truncate_short_and_long() -> None:
    assert _truncate("abc", 10) == "abc"
    assert _truncate("abc", 3) == "abc"
    assert _truncate("abcdef", 5) == "ab..."


def test_resume_list_recent(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="Mi sesion")
    code, out, err = _run(reg, ["resume"])
    assert code == 0
    assert "Sesiones recientes" in out
    assert "sess-aaa" in out
    assert "Reanuda con: dxrk resume <id-o-título>" in out


def test_resume_list_empty(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["resume"])
    assert code == 0
    assert "mostrando 0 de 0" in out


def test_resume_list_limit_flag(reg: Registry, sdir: str) -> None:
    for i in range(3):
        _mk(f"sess-00{i}")
    code, out, err = _run(reg, ["resume", "--limit=1"])
    assert code == 0
    assert "mostrando 1 de 3" in out


def test_resume_list_long_title_truncated(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="T" * 100)
    code, out, err = _run(reg, ["resume"])
    assert code == 0
    assert "T" * 47 + "..." in out


def test_resume_invalid_limit(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["resume", "--limit=abc"])
    assert code == 1
    assert "límite inválido" in err


def test_resume_list_error(reg: Registry, sdir: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dxrk.commands.resume.list_session_files", lambda: (_ for _ in ()).throw(SessionError("boom")))
    code, out, err = _run(reg, ["resume"])
    assert code == 1
    assert "boom" in err


def test_resume_by_id_prefix(reg: Registry, sdir: str) -> None:
    _mk("sess-abcdef", title="Docs", texts=["hola mundo"])
    code, out, err = _run(reg, ["resume", "sess-abc"])
    assert code == 0
    assert "reanudada" in out
    assert "Último mensaje (user): hola mundo" in out


def test_resume_by_title_substring(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="Mi Proyecto Grande")
    code, out, err = _run(reg, ["resume", "proyecto"])
    assert code == 0
    assert "Mi Proyecto Grande" in out


def test_resume_last_message_truncated(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="T", texts=["z" * 200])
    code, out, err = _run(reg, ["resume", "sess-aaa"])
    assert code == 0
    assert "z" * 77 + "..." in out


def test_resume_no_messages_ok(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="Vacia")
    code, out, err = _run(reg, ["resume", "sess-aaa"])
    assert code == 0
    assert "reanudada" in out
    assert "Último mensaje" not in out


def test_resume_no_match(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa", title="Docs")
    code, out, err = _run(reg, ["resume", "fantasma"])
    assert code == 1
    assert "ninguna sesión coincide" in err


# ---- share ----


def test_share_body_formats(sdir: str) -> None:
    s = _mk("sess-aaa", title="T", texts=["hola"])
    assert "# " in _share_body(s, "md")
    assert "# " in _share_body(s, "markdown")
    assert "<" in _share_body(s, "html")
    assert "{" in _share_body(s, "json")
    assert "<" in _share_body(s, "xml")


def test_share_session_bad_format(sdir: str) -> None:
    s = _mk("sess-aaa")
    with pytest.raises(SessionError, match="formato no compatible"):
        share_session(s, "/tmp/x.md", "pdf")


def test_share_session_write_error(sdir: str, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = _mk("sess-aaa")
    monkeypatch.setattr("dxrk.commands.share._write_private_file", lambda p, b: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(SessionError, match="al escribir"):
        share_session(s, str(tmp_path / "out.md"), "md")


def test_share_session_ok(tmp_path, sdir: str) -> None:
    s = _mk("sess-aaa", texts=["hola"])
    dest = str(tmp_path / "out.md")
    assert share_session(s, dest, "md") == "md"
    assert "hola" in open(dest, encoding="utf-8").read()


def test_share_run_output_flag(reg: Registry, sdir: str, tmp_path) -> None:
    _mk("sess-aaa", title="T", texts=["hola"])
    dest = str(tmp_path / "out.md")
    code, out, err = _run(reg, ["share", "sess-aaa", "--output", dest])
    assert code == 0
    assert f"compartida en {dest} (md)" in out


def test_share_run_positional_output_and_format_flag(reg: Registry, sdir: str, tmp_path) -> None:
    _mk("sess-aaa", title="T", texts=["hola"])
    dest = str(tmp_path / "out.txt")
    code, out, err = _run(reg, ["share", "sess-aaa", dest, "--format=json"])
    assert code == 0
    assert "(json)" in out


def test_share_run_missing_output(reg: Registry, sdir: str) -> None:
    _mk("sess-aaa")
    code, out, err = _run(reg, ["share", "sess-aaa"])
    assert code == 1
    assert "archivo de salida" in err


def test_share_run_missing_session_id(reg: Registry, sdir: str) -> None:
    code, out, err = _run(reg, ["share", "--output=x.md"])
    assert code == 1
    assert "id de la sesión" in err


def test_share_run_load_error(reg: Registry, sdir: str, tmp_path) -> None:
    code, out, err = _run(reg, ["share", "fantasma", str(tmp_path / "o.md")])
    assert code == 1
    assert "no encontrada" in err


def test_share_run_bad_format_from_ext(reg: Registry, sdir: str, tmp_path) -> None:
    _mk("sess-aaa")
    code, out, err = _run(reg, ["share", "sess-aaa", str(tmp_path / "o.pdf")])
    assert code == 1
    assert "formato no compatible" in err


def test_share_run_exists_needs_force(reg: Registry, sdir: str, tmp_path) -> None:
    _mk("sess-aaa", texts=["hola"])
    dest = str(tmp_path / "o.md")
    open(dest, "w", encoding="utf-8").write("previo")
    code, out, err = _run(reg, ["share", "sess-aaa", dest])
    assert code == 1
    assert "ya existe" in err
    code, out, err = _run(reg, ["share", "sess-aaa", dest, "--force"])
    assert code == 0
    assert "hola" in open(dest, encoding="utf-8").read()


def test_share_run_oserror_branch(reg: Registry, sdir: str, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _mk("sess-aaa", texts=["hola"])
    monkeypatch.setattr("dxrk.commands.share.share_session", lambda s, p, f: (_ for _ in ()).throw(OSError("disk")))
    code, out, err = _run(reg, ["share", "sess-aaa", str(tmp_path / "o.md")])
    assert code == 1
    assert "al escribir" in err
