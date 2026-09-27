# SPDX-License-Identifier: MIT
"""Phase 2 unification tests: CLI on FileStorage, one error contract,
store-layer id sanitization, migration wired into the load path.

Written failing-first against the pre-unification code; verified
bidirectional via ``git stash`` (fail pre-fix, pass post-fix).
"""

from __future__ import annotations

import gzip
import io
import json
import os
import stat

import pytest

from dxrk.commands import session as CS
from dxrk.commands.registry import Registry
from dxrk.commands.session import (
    delete_session_file,
    list_session_files_with_quarantine,
    load_session,
    register_session_command,
    save_session,
)
from dxrk.utils import session as S


@pytest.fixture
def reg() -> Registry:
    r = Registry()
    register_session_command(r)
    return r


@pytest.fixture
def sdir(tmp_path, monkeypatch) -> str:
    path = str(tmp_path / "sessions")
    os.makedirs(path, exist_ok=True)
    monkeypatch.setattr(CS, "session_dir", lambda: path)
    return path


def _run(reg, args):
    out, err = io.StringIO(), io.StringIO()
    code = reg.execute(args, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def _mk(title: str = "T", sid: str = "s1") -> S.Session:
    s = S.new_session(S.SessionOpts(title=title, working_dir="/tmp", model="m"))
    s.id = sid
    return s


def _v1_payload(sid: str = "v1-old", title: str = "Old") -> str:
    return json.dumps(
        {
            "version": 1,
            "id": sid,
            "title": title,
            "working_dir": "/tmp",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "message_count": 0,
            "token_count": 0,
            "model": "m",
            "status": 0,
        }
    )


# ─── single error type: commands and store raise the same SessionError ───


def test_session_error_is_single_type():
    assert CS.SessionError is S.SessionError


# ─── store-layer id sanitization: no path traversal ──────────────────────


def test_filestorage_load_rejects_traversal(tmp_path):
    st = S.FileStorage(str(tmp_path))
    with pytest.raises(S.SessionError):
        st.load("../../x")


def test_filestorage_save_rejects_traversal(tmp_path):
    st = S.FileStorage(str(tmp_path))
    s = _mk()
    s.id = "../../x"
    with pytest.raises(S.SessionError):
        st.save(s)


def test_traversal_cannot_escape_session_dir(tmp_path):
    # a valid session file planted OUTSIDE the store dir must never be read
    outside = tmp_path / "evil.json"
    s = _mk(title="Evil", sid="evil")
    outside.write_text(json.dumps(S._session_to_dict(s)), encoding="utf-8")
    st = S.FileStorage(str(tmp_path / "store"))
    with pytest.raises(S.SessionError):
        st.load("../evil")


def test_cli_load_traversal_no_escape(sdir, tmp_path):
    plant = tmp_path / "planted.json"
    s = _mk(title="Planted", sid="planted")
    plant.write_text(json.dumps(S._session_to_dict(s)), encoding="utf-8")
    with pytest.raises(CS.SessionError):
        load_session("../planted")


# ─── migration wired into the load path ──────────────────────────────────


def test_filestorage_load_migrates_v1(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, "v1-old.json"), "w", encoding="utf-8") as f:
        f.write(_v1_payload())
    st = S.FileStorage(d)
    loaded = st.load("v1-old")
    assert loaded.id == "v1-old"
    assert loaded.version == S.CurrentVersion
    assert loaded.status == S.SessionStatus.Active
    assert loaded.messages == []


def test_cli_load_reads_v1_file(sdir):
    with open(os.path.join(sdir, "v1-old.json"), "w", encoding="utf-8") as f:
        f.write(_v1_payload())
    got = load_session("v1-old")
    assert got.id == "v1-old"
    assert got.version == S.CurrentVersion


def test_cli_list_includes_v1_session(reg, sdir):
    with open(os.path.join(sdir, "v1-old.json"), "w", encoding="utf-8") as f:
        f.write(_v1_payload())
    code, out, err = _run(reg, ["session", "list"])
    assert code == 0
    assert "v1-old" in out


def test_restore_session_migrates_v1():
    s = S.Session(version=1, id="old1", title="Old", status=S.SessionStatus.Active)

    class _Stub:
        def load(self, _id: str) -> S.Session:
            return s

    restored = S.restore_session("old1", _Stub())  # type: ignore[arg-type]
    assert restored.id == "old1"
    assert restored.version == S.CurrentVersion


# ─── one error contract: store raises, CLI maps to exit codes ────────────


def test_save_strict_raises_and_shim_returns_false(sdir, monkeypatch):
    from dxrk.commands.session import save_session_strict

    s = _mk()
    monkeypatch.setattr(S.FileStorage, "save", lambda self, sess: (_ for _ in ()).throw(S.SessionError("disk")))
    with pytest.raises(S.SessionError):
        save_session_strict(s)
    assert save_session(s) is False


def test_cli_create_maps_store_error_to_exit_1(reg, sdir, monkeypatch):
    monkeypatch.setattr(S.FileStorage, "save", lambda self, sess: (_ for _ in ()).throw(S.SessionError("disk")))
    code, out, err = _run(reg, ["session", "create", "T"])
    assert code == 1
    assert "al guardar la sesión" in err


def test_delete_missing_raises_and_shim_false(sdir):
    from dxrk.commands.session import delete_session_strict

    s = _mk(sid="ghost")
    with pytest.raises(CS.SessionError):
        delete_session_strict(s)
    assert delete_session_file(s) is False


# ─── canonical writer: 0600, quarantine, lazy read of old files ──────────


def test_save_applies_owner_only_permissions(sdir):
    s = _mk()
    assert save_session(s) is True
    mode = stat.S_IMODE(os.stat(os.path.join(sdir, "s1.json")).st_mode)
    assert mode == 0o600


def test_old_stack_a_file_readable_via_new_list(sdir):
    # file written with the legacy export_json layout (no index involved)
    from dxrk.utils.session import export_json

    s = _mk(title="Legacy")
    with open(os.path.join(sdir, "s1.json"), "w", encoding="utf-8") as f:
        f.write(export_json(s))
    sessions, quarantined = list_session_files_with_quarantine()
    assert quarantined == 0
    assert [x.id for x in sessions] == ["s1"]


def test_quarantine_preserved_on_new_stack(sdir):
    s = _mk(title="Good", sid="good-aaa")
    assert save_session(s) is True
    with open(os.path.join(sdir, "torn.json"), "w", encoding="utf-8") as f:
        f.write('{"id": "torn", "tit')
    sessions, quarantined = list_session_files_with_quarantine()
    assert [x.id for x in sessions] == ["good-aaa"]
    assert quarantined == 1
    assert os.path.exists(os.path.join(sdir, ".quarantine", "torn.json"))


def test_index_sidecar_skipped_not_quarantined(sdir):
    s = _mk(title="Keep", sid="keep1")
    assert save_session(s) is True
    assert os.path.exists(os.path.join(sdir, ".index.json"))
    sessions, quarantined = list_session_files_with_quarantine()
    assert [x.id for x in sessions] == ["keep1"]
    assert quarantined == 0


def test_compressed_only_session_listed(sdir):
    s = _mk(title="Zipped", sid="zip1")
    assert save_session(s) is True
    st = S.FileStorage(sdir)
    st.compress_session("zip1")
    assert not os.path.exists(os.path.join(sdir, "zip1.json"))
    sessions, _ = list_session_files_with_quarantine()
    assert [x.id for x in sessions] == ["zip1"]
    assert load_session("zip1").title == "Zipped"


def test_gz_written_by_store_readable_via_cli(sdir):
    raw = _v1_payload(sid="v1gz", title="GzOld").encode("utf-8")
    with open(os.path.join(sdir, "v1gz.json.gz"), "wb") as f:
        f.write(gzip.compress(raw))
    got = load_session("v1gz")
    assert got.version == S.CurrentVersion
    assert got.title == "GzOld"
