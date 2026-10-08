# SPDX-License-Identifier: MIT
"""Phase 3: SQLite-WAL session store backend (opt-in) + shared conformance.

Written failing-first against the FileStorage-only code; verified
bidirectional via ``git stash`` (fail pre-fix, pass post-fix).

Conformance: the same behavioral suite runs against BOTH backends through
the ``store`` fixture. Any semantic difference found is pinned by an
explicit ``test_pinned_difference_*`` test, never silently absorbed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
import sys

import pytest

from dxrk.utils import session as S


def _mk(title: str = "T", sid: str = "s1", **kw: object) -> S.Session:
    s = S.new_session(S.SessionOpts(title=title, working_dir="/tmp", model=kw.get("model", "m")))  # type: ignore[arg-type]
    s.id = sid
    for k, v in kw.items():
        if k != "model":
            setattr(s, k, v)
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


@pytest.fixture(params=["file", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path):  # type: ignore[no-untyped-def]
    if request.param == "file":
        st = S.FileStorage(str(tmp_path / "file"))
    else:
        st = S.SQLiteSessionStorage(str(tmp_path / "sq"))  # type: ignore[attr-defined]
    yield st
    close = getattr(st, "close", None)
    if callable(close):
        close()


@pytest.fixture
def sqlstore(tmp_path):  # type: ignore[no-untyped-def]
    st = S.SQLiteSessionStorage(str(tmp_path / "sq"))  # type: ignore[attr-defined]
    yield st
    st.close()


# ─── conformance: identical semantics on both backends ───────────────────


def test_conformance_save_load_roundtrip(store):  # type: ignore[no-untyped-def]
    s = _mk(title="Hello", sid="r1")
    s.tags = ["a", "b"]
    store.save(s)
    got = store.load("r1")
    assert got.id == "r1"
    assert got.title == "Hello"
    assert got.model == "m"
    assert got.tags == ["a", "b"]
    assert got.version == S.CurrentVersion


def test_conformance_load_missing_raises(store):  # type: ignore[no-untyped-def]
    with pytest.raises(S.SessionError):
        store.load("ghost")


def test_conformance_exists(store):  # type: ignore[no-untyped-def]
    assert store.exists("r1") is False
    store.save(_mk(sid="r1"))
    assert store.exists("r1") is True


def test_conformance_delete_removes_and_is_idempotent(store):  # type: ignore[no-untyped-def]
    store.save(_mk(sid="r1"))
    store.delete("r1")
    assert store.exists("r1") is False
    with pytest.raises(S.SessionError):
        store.load("r1")
    store.delete("r1")  # missing delete must not raise (FileStorage parity)


def test_conformance_save_upserts(store):  # type: ignore[no-untyped-def]
    store.save(_mk(title="One", sid="r1"))
    store.save(_mk(title="Two", sid="r1"))
    assert store.load("r1").title == "Two"


def test_conformance_save_refreshes_updated_at(store):  # type: ignore[no-untyped-def]
    s = _mk(sid="r1")
    before = s.updated_at
    store.save(s)
    assert s.updated_at is not None and before is not None
    assert s.updated_at >= before


def test_conformance_load_rejects_traversal(store, tmp_path):  # type: ignore[no-untyped-def]
    with pytest.raises(S.SessionError):
        store.load("../../x")
    with pytest.raises(S.SessionError):
        store.load("")
    with pytest.raises(S.SessionError):
        store.load(str(tmp_path / "evil"))


def test_conformance_save_rejects_traversal(store):  # type: ignore[no-untyped-def]
    s = _mk()
    s.id = "../../x"
    with pytest.raises(S.SessionError):
        store.save(s)


def _seed(store, n: int = 3):  # type: ignore[no-untyped-def]
    out = []
    for i in range(n):
        s = _mk(title=f"T{i}", sid=f"s{i}")
        store.save(s)
        out.append(store.load(f"s{i}"))
    return out


def test_conformance_list_returns_summaries(store):  # type: ignore[no-untyped-def]
    _seed(store, 3)
    got = store.list()
    assert {x.id for x in got} == {"s0", "s1", "s2"}
    for x in got:
        assert x.title.startswith("T")
        assert x.created_at is not None
        assert x.status == S.SessionStatus.Active


def test_conformance_list_default_sorts_created_desc(store):  # type: ignore[no-untyped-def]
    _seed(store, 3)
    got = store.list()
    ts = [x.created_at for x in got]
    assert ts == sorted(ts, reverse=True)


def test_conformance_list_status_filter(store):  # type: ignore[no-untyped-def]
    a = _mk(title="A", sid="a")
    b = _mk(title="B", sid="b")
    b.status = S.SessionStatus.Archived
    store.save(a)
    store.save(b)
    got = store.list(S.ListOpts(status=int(S.SessionStatus.Archived)))
    assert [x.id for x in got] == ["b"]


def test_conformance_list_search_case_insensitive(store):  # type: ignore[no-untyped-def]
    store.save(_mk(title="Hello World", sid="a"))
    store.save(_mk(title="other", sid="b"))
    got = store.list(S.ListOpts(search_query="hello"))
    assert [x.id for x in got] == ["a"]


def test_conformance_list_after_before(store):  # type: ignore[no-untyped-def]
    seeded = _seed(store, 3)
    mid = seeded[1].created_at
    assert mid is not None
    after = store.list(S.ListOpts(after=mid))
    assert {x.id for x in after} == {"s1", "s2"}
    before = store.list(S.ListOpts(before=mid))
    assert {x.id for x in before} == {"s0", "s1"}


def test_conformance_list_sort_token_count(store):  # type: ignore[no-untyped-def]
    a = _mk(title="A", sid="a", token_count=5)
    b = _mk(title="B", sid="b", token_count=50)
    store.save(a)
    store.save(b)
    desc = store.list(S.ListOpts(sort_by="token_count"))
    assert [x.id for x in desc] == ["b", "a"]
    asc = store.list(S.ListOpts(sort_by="token_count", sort_dir="asc"))
    assert [x.id for x in asc] == ["a", "b"]


def test_conformance_list_sort_message_count(store):  # type: ignore[no-untyped-def]
    a = _mk(title="A", sid="a", message_count=1)
    b = _mk(title="B", sid="b", message_count=9)
    store.save(a)
    store.save(b)
    got = store.list(S.ListOpts(sort_by="message_count"))
    assert [x.id for x in got] == ["b", "a"]


def test_conformance_list_sort_updated_at(store):  # type: ignore[no-untyped-def]
    _seed(store, 2)
    got = store.list(S.ListOpts(sort_by="updated_at"))
    assert [x.id for x in got] == ["s1", "s0"]
    asc = store.list(S.ListOpts(sort_by="updated_at", sort_dir="asc"))
    assert [x.id for x in asc] == ["s0", "s1"]


def test_conformance_list_offset_limit(store):  # type: ignore[no-untyped-def]
    _seed(store, 4)
    all_ids = [x.id for x in store.list()]
    assert len(all_ids) == 4
    assert [x.id for x in store.list(S.ListOpts(limit=2))] == all_ids[:2]
    assert [x.id for x in store.list(S.ListOpts(offset=2))] == all_ids[2:]
    assert [x.id for x in store.list(S.ListOpts(limit=1, offset=1))] == all_ids[1:2]
    assert store.list(S.ListOpts(offset=99)) == []


def test_conformance_filestorage_load_migrates_v1(tmp_path):  # type: ignore[no-untyped-def]
    d = str(tmp_path)
    with open(os.path.join(d, "v1-old.json"), "w", encoding="utf-8") as f:
        f.write(_v1_payload())
    st = S.FileStorage(d)
    loaded = st.load("v1-old")
    assert loaded.version == S.CurrentVersion


# ─── sqlite specifics ────────────────────────────────────────────────────


def test_sqlite_uses_wal_mode(sqlstore, tmp_path):  # type: ignore[no-untyped-def]
    db = os.path.join(str(tmp_path / "sq"), "sessions.db")
    assert os.path.exists(db)
    con = sqlite3.connect(db)
    try:
        mode = con.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        con.close()
    assert str(mode).lower() == "wal"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only file permissions")
def test_sqlite_db_owner_only_permissions(sqlstore, tmp_path):  # type: ignore[no-untyped-def]
    db = os.path.join(str(tmp_path / "sq"), "sessions.db")
    assert stat.S_IMODE(os.stat(db).st_mode) == 0o600


def test_sqlite_model_column_roundtrips(sqlstore):  # type: ignore[no-untyped-def]
    s = _mk(title="M", sid="m1", model="gpt-x")
    sqlstore.save(s)
    assert sqlstore.load("m1").model == "gpt-x"


def test_sqlite_list_without_parsing_payload(sqlstore):  # type: ignore[no-untyped-def]
    sqlstore.save(_mk(title="Good", sid="good"))
    sqlstore.save(_mk(title="Doomed", sid="doomed"))
    con = sqlite3.connect(sqlstore.db_path)
    try:
        con.execute('UPDATE sessions SET payload = \'{"id": "doomed", "tit\' WHERE id = \'doomed\'')
        con.commit()
    finally:
        con.close()
    # list is served from indexed columns only: corrupt payload still lists
    ids = {x.id for x in sqlstore.list()}
    assert ids == {"good", "doomed"}
    with pytest.raises(S.SessionError):
        sqlstore.load("doomed")
    assert sqlstore.load("good").title == "Good"


def test_pinned_difference_corrupt_visibility(tmp_path):  # type: ignore[no-untyped-def]
    """PINNED DIFFERENCE: corrupt-payload visibility in list.

    FileStorage rebuilds its index by parsing files, so a torn ``.json``
    planted on disk is ABSENT from a fresh ``list`` (load raises).
    SQLite serves ``list`` from indexed columns without parsing payloads,
    so a row with a corrupt payload is still PRESENT in ``list``
    (load raises identically). Both raise SessionError on load.
    """
    d = str(tmp_path / "file")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "torn.json"), "w", encoding="utf-8") as f:
        f.write('{"id": "torn", "tit')
    fresh_file = S.FileStorage(d)
    assert [x.id for x in fresh_file.list()] == []
    with pytest.raises(S.SessionError):
        fresh_file.load("torn")

    sql = S.SQLiteSessionStorage(str(tmp_path / "sq"))
    try:
        sql.save(_mk(title="Torn", sid="torn"))
        con = sqlite3.connect(sql.db_path)
        try:
            con.execute('UPDATE sessions SET payload = \'{"id": "torn", "tit\' WHERE id = \'torn\'')
            con.commit()
        finally:
            con.close()
        assert "torn" in {x.id for x in sql.list()}
        with pytest.raises(S.SessionError):
            sql.load("torn")
    finally:
        sql.close()


# ─── one-shot importer JSON dir -> sqlite ────────────────────────────────


def test_importer_copies_json_gz_and_v1(tmp_path):  # type: ignore[no-untyped-def]
    src = str(tmp_path / "src")
    os.makedirs(src, exist_ok=True)
    fst = S.FileStorage(src)
    fst.save(_mk(title="Plain", sid="plain"))
    fst.save(_mk(title="Zipped", sid="zipped"))
    fst.compress_session("zipped")
    with open(os.path.join(src, "v1-old.json"), "w", encoding="utf-8") as f:
        f.write(_v1_payload())
    with open(os.path.join(src, "torn.json"), "w", encoding="utf-8") as f:
        f.write('{"id": "torn", "tit')

    sql = S.SQLiteSessionStorage(str(tmp_path / "sq"))
    try:
        res = S.migrate_json_dir_to_sqlite(src, sql)  # type: ignore[attr-defined]
        assert res.imported == 3
        assert res.skipped == 1
        assert sql.load("plain").title == "Plain"
        assert sql.load("zipped").title == "Zipped"
        migrated = sql.load("v1-old")
        assert migrated.version == S.CurrentVersion
        assert migrated.title == "Old"
        with pytest.raises(S.SessionError):
            sql.load("torn")
    finally:
        sql.close()


def test_importer_is_idempotent_and_preserves_timestamps(tmp_path):  # type: ignore[no-untyped-def]
    src = str(tmp_path / "src")
    os.makedirs(src, exist_ok=True)
    fst = S.FileStorage(src)
    fst.save(_mk(title="Keep", sid="keep"))
    before = fst.load("keep")

    sql = S.SQLiteSessionStorage(str(tmp_path / "sq"))
    try:
        first = S.migrate_json_dir_to_sqlite(fst, sql)  # type: ignore[attr-defined]
        second = S.migrate_json_dir_to_sqlite(src, sql)  # type: ignore[attr-defined]
        assert (first.imported, first.skipped) == (second.imported, second.skipped) == (1, 0)
        assert len(sql.list()) == 1
        got = sql.load("keep")
        assert got.created_at == before.created_at
        assert got.updated_at == before.updated_at
    finally:
        sql.close()


def test_importer_accepts_filestorage_or_dir(tmp_path):  # type: ignore[no-untyped-def]
    src = str(tmp_path / "src")
    os.makedirs(src, exist_ok=True)
    S.FileStorage(src).save(_mk(title="A", sid="a"))
    sql = S.SQLiteSessionStorage(str(tmp_path / "sq"))
    try:
        r1 = S.migrate_json_dir_to_sqlite(S.FileStorage(src), sql)  # type: ignore[attr-defined]
        assert r1.imported == 1
    finally:
        sql.close()


# ─── opt-in factory: JSON dir stays the default ──────────────────────────


def test_factory_defaults_to_filestorage(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DXRK_SESSION_BACKEND", raising=False)
    st = S.open_session_storage(str(tmp_path))  # type: ignore[attr-defined]
    try:
        assert isinstance(st, S.FileStorage)
    finally:
        close = getattr(st, "close", None)
        if callable(close):
            close()


def test_factory_opt_in_via_env(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DXRK_SESSION_BACKEND", "sqlite")
    st = S.open_session_storage(str(tmp_path))  # type: ignore[attr-defined]
    try:
        assert isinstance(st, S.SQLiteSessionStorage)  # type: ignore[attr-defined]
    finally:
        st.close()


def test_factory_unknown_value_stays_default(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DXRK_SESSION_BACKEND", "nonsense")
    st = S.open_session_storage(str(tmp_path))  # type: ignore[attr-defined]
    try:
        assert isinstance(st, S.FileStorage)
    finally:
        close = getattr(st, "close", None)
        if callable(close):
            close()


# ─── CLI honors DXRK_SESSION_BACKEND end-to-end ────────────────────────


def _cli_sdir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import dxrk.commands.session as CS

    path = str(tmp_path / "sessions")
    monkeypatch.setattr(CS, "session_dir", lambda: path)
    return path


def _cli_reg():  # type: ignore[no-untyped-def]
    import io

    from dxrk.commands.registry import Registry
    from dxrk.commands.session import register_session_command

    reg = Registry()
    register_session_command(reg)

    def run(args):  # type: ignore[no-untyped-def]
        out, err = io.StringIO(), io.StringIO()
        code = reg.execute(args, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    return run


def test_cli_defaults_to_filestorage_without_env(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import dxrk.commands.session as CS

    monkeypatch.delenv("DXRK_SESSION_BACKEND", raising=False)
    _cli_sdir(tmp_path, monkeypatch)
    st = CS._store()
    try:
        assert isinstance(st, S.FileStorage)
    finally:
        close = getattr(st, "close", None)
        if callable(close):
            close()


def test_cli_sqlite_list_info_load_against_sessions_db(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import dxrk.commands.session as CS

    monkeypatch.setenv("DXRK_SESSION_BACKEND", "sqlite")
    sdir = _cli_sdir(tmp_path, monkeypatch)
    run = _cli_reg()
    st = CS._store()
    try:
        assert isinstance(st, S.SQLiteSessionStorage)  # type: ignore[attr-defined]
    finally:
        st.close()
    code, out, err = run(["session", "create", "HelloSqlite"])
    assert code == 0, err
    assert os.path.exists(os.path.join(sdir, "sessions.db"))
    assert not [n for n in os.listdir(sdir) if n.endswith(".json")]
    code, out, err = run(["session", "list"])
    assert code == 0, err
    assert "HelloSqlite" in out
    prefix = out.splitlines()[1].split("\t")[0]
    assert len(prefix) == 8
    code, out, err = run(["session", "info", prefix])
    assert code == 0, err
    assert "HelloSqlite" in out
    assert CS.load_session(prefix).title == "HelloSqlite"


def test_cli_unknown_backend_value_falls_back_to_file(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import dxrk.commands.session as CS

    monkeypatch.setenv("DXRK_SESSION_BACKEND", "nonsense")
    sdir = _cli_sdir(tmp_path, monkeypatch)
    run = _cli_reg()
    assert isinstance(CS._store(), S.FileStorage)
    code, out, err = run(["session", "create", "HelloFile"])
    assert code == 0, err
    assert not os.path.exists(os.path.join(sdir, "sessions.db"))
    code, out, err = run(["session", "list"])
    assert code == 0, err
    assert "HelloFile" in out


def test_cli_sqlite_corrupt_row_counted_not_quarantined(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import sqlite3

    import dxrk.commands.session as CS

    monkeypatch.setenv("DXRK_SESSION_BACKEND", "sqlite")
    sdir = _cli_sdir(tmp_path, monkeypatch)
    run = _cli_reg()
    code, out, err = run(["session", "create", "Good"])
    assert code == 0, err
    st = CS._store()
    try:
        good_id = st.list()[0].id
        con = sqlite3.connect(st.db_path)  # type: ignore[attr-defined]
        try:
            con.execute("INSERT INTO sessions (id, payload) VALUES (?, ?)", ("corrupt-row", "{not json"))
            con.commit()
        finally:
            con.close()
    finally:
        st.close()
    sessions, corrupt = CS.list_session_files_with_quarantine()
    assert [s.id for s in sessions] == [good_id]
    assert corrupt == 1
    assert not os.path.exists(os.path.join(sdir, ".quarantine"))
    code, out, err = run(["session", "list"])
    assert code == 0, err
    assert "sin cuarentena en disco" in out
