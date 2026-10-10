# SPDX-License-Identifier: MIT
"""Coverage boost for dxrk.utils.swarm_session and dxrk.vault."""

from __future__ import annotations

import base64
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dxrk.utils import swarm_session as SS
from dxrk.utils.swarm_model import Task, TaskResult
from dxrk.vault import (
    SecretEntry,
    TenantVaultRegistry,
    Vault,
    _tenant_env_name,
    get_tenant_vault,
    new,
    tenant_vault_path,
    with_env_var,
    with_rotation,
)


def _store(tmp_path: Path, name: str = "swarm.db") -> SS.SwarmTaskStore:
    return SS.SwarmTaskStore(str(tmp_path / name))


def _task(tid: str, session: str = "sess-1", **kw) -> Task:
    base = dict(
        id=tid,
        session_id=session,
        type="work",
        payload=b"p",
        assigned_backend="b1",
        retries=1,
        max_retries=3,
        error="e",
    )
    base.update(kw)
    return Task(**base)  # type: ignore[arg-type]


def _result(tid: str, session: str = "sess-1", **kw) -> TaskResult:
    base = dict(
        task_id=tid,
        session_id=session,
        backend_id="b1",
        output=b"out",
        duration=timedelta(seconds=2),
        timestamp=datetime(2024, 5, 1, 12, 0, 0),
    )
    base.update(kw)
    return TaskResult(**base)  # type: ignore[arg-type]


# ─── swarm_session: timestamp parsing ──────────────────────────────────


def test_parse_result_timestamp_variants():
    assert SS._parse_result_timestamp("2024-01-02T03:04:05") == datetime(2024, 1, 2, 3, 4, 5)
    before = datetime.now().astimezone() if False else None  # noqa: F841
    assert isinstance(SS._parse_result_timestamp("not-a-date"), datetime)
    assert isinstance(SS._parse_result_timestamp(""), datetime)
    assert isinstance(SS._parse_result_timestamp(None), datetime)
    assert isinstance(SS._parse_result_timestamp(12345), datetime)


# ─── swarm_session: init ───────────────────────────────────────────────


def test_store_init_default_path_uses_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(SS.os.path, "expanduser", lambda p: str(tmp_path / "home"))
    st = SS.SwarmTaskStore()
    try:
        assert st.db_path.endswith(os.path.join(".dxrk", "swarm_tasks.db"))
        assert os.path.exists(st.db_path)
    finally:
        st.Close()


def test_store_init_chmod_failure_tolerated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(SS.os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("no chmod")))
    st = _store(tmp_path)
    st.Close()


def test_store_init_bare_filename_no_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    st = SS.SwarmTaskStore(":memory:")
    try:
        assert st.SessionSummary("none") == {"submitted": 0, "completed": 0, "in_flight": 0}
    finally:
        st.Close()


def test_new_swarm_task_store_ctor(tmp_path: Path):
    st = SS.NewSwarmTaskStore(str(tmp_path / "n.db"))
    st.Close()


# ─── swarm_session: tasks + results ────────────────────────────────────


def test_record_task_upsert_and_pending_order(tmp_path: Path):
    st = _store(tmp_path)
    try:
        st.RecordTask(_task("t-2"))
        st.RecordTask(_task("t-1"))
        assert st.PendingTasks("sess-1") == ["t-1", "t-2"]
        # upsert same id updates instead of duplicating
        st.RecordTask(_task("t-1", retries=2, error="boom"))
        assert st.PendingTasks("sess-1") == ["t-1", "t-2"]
        assert st.SessionSummary("sess-1")["submitted"] == 2
    finally:
        st.Close()


def test_record_result_branches(tmp_path: Path):
    st = _store(tmp_path)
    try:
        st.RecordTask(_task("t-1"))
        # zero duration + unset timestamp hits falsy branches
        r = _result("t-1", duration=timedelta(0), timestamp=None)  # type: ignore[arg-type]
        st.RecordResult(r)
        assert st.PendingTasks("sess-1") == []
        # re-record same result exercises ON CONFLICT update path
        st.RecordResult(_result("t-1", output=b"out2"))
        got = st.GetResult("t-1")
        assert got is not None and got.output == b"out2"
    finally:
        st.Close()


def test_get_result_missing_and_null_output(tmp_path: Path):
    st = _store(tmp_path)
    try:
        assert st.GetResult("ghost") is None
        st.RecordResult(_result("t-n", output=None))
        got = st.GetResult("t-n")
        assert got is not None and got.output is None
    finally:
        st.Close()


def test_get_result_garbage_and_null_timestamp(tmp_path: Path):
    st = _store(tmp_path)
    try:
        st.RecordResult(_result("t-g"))
        st.RecordResult(_result("t-n"))
        with st._mu, st._conn:
            st._conn.execute("UPDATE swarm_results SET timestamp='garbage' WHERE task_id='t-g'")
            st._conn.execute("UPDATE swarm_results SET timestamp='' WHERE task_id='t-n'")
        assert isinstance(st.GetResult("t-g"), TaskResult)
        assert isinstance(st.GetResult("t-n"), TaskResult)
    finally:
        st.Close()


def test_list_session_ordered_and_empty(tmp_path: Path):
    st = _store(tmp_path)
    try:
        assert st.ListSession("empty") == []
        st.RecordResult(_result("b-2"))
        st.RecordResult(_result("b-1", output=None))
        rows = st.ListSession("sess-1")
        assert [r.task_id for r in rows] == ["b-1", "b-2"]
        assert rows[0].output is None
        assert st.ListSession("other") == []
    finally:
        st.Close()


def test_session_summary_counts_and_text(tmp_path: Path):
    st = _store(tmp_path)
    try:
        st.RecordTask(_task("t-1"))
        st.RecordTask(_task("t-2"))
        st.RecordResult(_result("t-1"))
        assert st.SessionSummary("sess-1") == {"submitted": 2, "completed": 1, "in_flight": 1}
        text = st.SessionSummaryText("sess-1")
        assert "1/2 tasks completed" in text
        assert "t-2" in text  # pending listed
        st.RecordResult(_result("t-2"))
        text2 = st.SessionSummaryText("sess-1")
        assert "2/2 tasks completed" in text2
        assert "pending" not in text2
    finally:
        st.Close()


def test_close_tolerates_sqlite_error(tmp_path: Path):
    st = _store(tmp_path)

    class _BadConn:
        def close(self) -> None:
            raise sqlite3.Error("already gone")

    st._conn = _BadConn()  # type: ignore[assignment]
    st.Close()  # must not raise


# ─── vault: entries ────────────────────────────────────────────────────


def test_secret_entry_dict_roundtrip_with_opts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DXRK_VAULT_KEY", "cov-master")
    path = str(tmp_path / "v.enc")
    v = new(path, "DXRK_VAULT_KEY")
    v.set("k", "val", with_rotation("weekly"), with_env_var("K_ENV"))
    entry = SecretEntry.from_dict(v._secrets["k"].to_dict())
    assert entry.rotation == "weekly"
    assert entry.env_var == "K_ENV"
    # reload exercises to_dict persistence path with rotation/env set
    v2 = new(path, "DXRK_VAULT_KEY")
    assert v2.get("k") == ("val", True)
    plain = SecretEntry.from_dict({"value": "x", "created": "2024-01-01T00:00:00", "updated": "2024-01-02T00:00:00"})
    assert plain.rotation == "" and plain.env_var == ""
    assert "rotation" not in plain.to_dict()


def test_validate_tenant_id_rejects():
    with pytest.raises(ValueError, match="invalid tenant"):
        tenant_vault_path("bad id!")
    with pytest.raises(ValueError, match="invalid tenant"):
        Vault.create("", tenant_id="bad id!")


def test_tenant_env_name_hyphen():
    assert _tenant_env_name("my-tenant") == "DXRK_VAULT_KEY_MY_TENANT"


def test_tenant_vault_path_ok_and_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tenant_vault_path("acme")
    assert p.endswith(os.path.join("acme", "vault.enc"))
    import dxrk.tenant.migration as mig

    monkeypatch.setattr(mig, "tenant_root", lambda _t: (_ for _ in ()).throw(RuntimeError("no mig")))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    p2 = tenant_vault_path("acme")
    assert p2.endswith(os.path.join("acme", "vault.enc"))


def test_vault_path_and_tenant_props(tmp_path: Path):
    v = new("", "")
    assert v.path == ""
    assert v.tenant_id == ""
    v2 = new(str(tmp_path / "x.enc"), "")
    assert v2.path.endswith("x.enc")


# ─── vault: create branches ────────────────────────────────────────────


def test_create_tenant_per_env_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DXRK_VAULT_KEY_ACME", "tenant-specific-secret")
    monkeypatch.delenv("DXRK_VAULT_KEY", raising=False)
    v = Vault.create("", tenant_id="acme")
    assert v.tenant_id == "acme"
    v.set("k", "v")
    assert v.get("k") == ("v", True)


def test_create_tenant_ephemeral_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("DXRK_VAULT_KEY_EPHEM", raising=False)
    monkeypatch.delenv("DXRK_VAULT_KEY", raising=False)
    v = Vault.create("", tenant_id="ephem")
    v.set("k", "v")
    assert v.get("k") == ("v", True)


def test_create_tenant_auto_path_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dxrk.tenant.migration as mig

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DXRK_VAULT_KEY", "master-for-fallback")
    monkeypatch.setattr(mig, "tenant_root", lambda _t: (_ for _ in ()).throw(RuntimeError("down")))
    v = Vault.create("", tenant_id="fb")
    assert v.path.endswith(os.path.join("fb", "vault.enc"))


def test_create_tenant_corrupt_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DXRK_VAULT_KEY", "master-x")
    path = str(tmp_path / "bad.enc")
    Path(path).write_text(base64.b64encode(b"tiny").decode())
    with pytest.raises(RuntimeError, match="load vault"):
        Vault.create(path, tenant_id="corrupt")


def test_create_legacy_missing_env_and_corrupt_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISSING_COV_ENV", raising=False)
    path = str(tmp_path / "bad2.enc")
    Path(path).write_text(base64.b64encode(b"tiny").decode())
    with pytest.raises(RuntimeError, match="load vault"):
        Vault.create(path, "MISSING_COV_ENV")


def test_create_legacy_short_ciphertext_raises(tmp_path: Path):
    path = str(tmp_path / "short.enc")
    Path(path).write_text(base64.b64encode(b"tiny").decode())
    with pytest.raises(RuntimeError, match="load vault"):
        Vault.create(path, "")


# ─── vault: save/load error paths ──────────────────────────────────────


def test_bind_to_env_existing_entry(tmp_path: Path):
    v = new(str(tmp_path / "b.enc"), "")
    v.set("k", "orig")
    v.bind_to_env("k", "K_ENV2")
    assert v._secrets["k"].env_var == "K_ENV2"
    assert v.get("k") == ("orig", True)


def test_save_encrypt_error_wrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    v = new(str(tmp_path / "e.enc"), "")
    monkeypatch.setattr(Vault, "_encrypt", lambda self, _p: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="encrypt vault"):
        v.set("k", "v")


def test_save_replace_error_cleans_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "r.enc")
    v = new(path, "")
    monkeypatch.setattr(SS.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("no replace")))
    with pytest.raises(OSError, match="no replace"):
        v.set("k", "v")
    assert not os.path.exists(path + ".tmp")


def test_save_replace_error_unlink_failure_swallowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = str(tmp_path / "r2.enc")
    v = new(path, "")
    monkeypatch.setattr(SS.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("no replace")))
    monkeypatch.setattr(SS.os, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("no unlink")))
    with pytest.raises(OSError, match="no replace"):
        v.set("k", "v")


def test_decrypt_short_raises():
    v = new("", "")
    with pytest.raises(ValueError, match="ciphertext too short"):
        v._decrypt(b"123")


# ─── vault: registry ───────────────────────────────────────────────────


def test_registry_alias_all_contains_getitem_len(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DXRK_VAULT_KEY", "reg-master")
    reg = TenantVaultRegistry()
    assert len(reg) == 0
    assert "acme" not in reg
    assert 123 not in reg  # type: ignore[operator]
    a = reg.get_tenant_vault("acme")
    assert reg.get("acme") is a  # cached
    assert reg["acme"] is a  # getitem
    assert "acme" in reg
    assert len(reg) == 1
    assert set(reg.all()) == {"acme"}
    reg.clear()
    assert len(reg) == 0


def test_global_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DXRK_VAULT_KEY", "global-master")
    v = get_tenant_vault("covglobal")
    v.set("g", "1")
    assert v.get("g") == ("1", True)
    v2 = new("", "")
    v2.set("z", "9", with_rotation("daily"))
    assert v2.resolve("z") == "9"
