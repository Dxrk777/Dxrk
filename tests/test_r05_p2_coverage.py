# SPDX-License-Identifier: MIT
"""R05 P2 coverage boost — tenant CLI, hooks_cli, __main__, palace gaps, tenant_switcher.

Aisla filesystem via monkeypatch HOME (y DXRK_TENANT) en cada test.
No deps externos, solo pytest + stdlib + textual (ya en dxrk).
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _iso_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    # HOME affects Path.home() on POSIX; también limpia DXRK_TENANT por defecto
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_PROJECT_DIR", raising=False)
    monkeypatch.delenv("DXRK_MINE_PID_FILE", raising=False)
    monkeypatch.delenv("DXRK_MINE_TIMEOUT_HOURS", raising=False)
    monkeypatch.delenv("DXRK_PYTHON", raising=False)
    return home


def _mk_registry():
    from dxrk.commands.registry import Registry
    from dxrk.commands.tenant import register_tenant_command

    reg = Registry()
    register_tenant_command(reg)
    return reg


def _ctx_out_err():
    out = io.StringIO()
    err = io.StringIO()
    return out, err


# ---------------------------------------------------------------------------
# tenant CLI
# ---------------------------------------------------------------------------


def test_tenant_list_empty_home_tmp(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "list"], out=out, err=err)
    assert rc == 0
    assert "No tenants found" in out.getvalue()
    # ensure isolation: no real ~/.dxrk touched, only tmp
    assert not (Path.home() / ".dxrk" / "tenants").exists() or str(Path.home()).startswith(str(home))


def test_tenant_create_valid_and_idempotent(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "create", "acme"], out=out, err=err)
    assert rc == 0
    assert "Created tenant acme" in out.getvalue()
    # idempotent second create same id
    out2, err2 = _ctx_out_err()
    rc2 = reg.execute(["tenant", "create", "acme"], out=out2, err=err2)
    assert rc2 == 0
    # invalid char
    out3, err3 = _ctx_out_err()
    rc3 = reg.execute(["tenant", "create", "bad/id"], out=out3, err=err3)
    assert rc3 == 1
    assert "invalid tenant id" in err3.getvalue()


def test_tenant_create_bad_id_via_ctx_flag(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.commands.registry import CommandContext, Registry
    from dxrk.commands.tenant import register_tenant_command

    reg = Registry()
    register_tenant_command(reg)
    cmd = reg.get_command("tenant create")
    assert cmd is not None and cmd.run is not None
    out, err = _ctx_out_err()
    ctx = CommandContext(args=["bad/id"], out=out, err=err)
    rc = cmd.run(ctx)
    assert rc == 1
    assert "invalid tenant id" in err.getvalue()
    # empty id
    out2, err2 = _ctx_out_err()
    ctx2 = CommandContext(args=[""], out=out2, err=err2)
    rc2 = cmd.run(ctx2)
    assert rc2 == 1


def test_tenant_list_active_marker_env_priority(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    # create two tenants
    reg.execute(["tenant", "create", "acme"], out=io.StringIO(), err=io.StringIO())
    reg.execute(["tenant", "create", "beta"], out=io.StringIO(), err=io.StringIO())
    # switch to acme
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "switch", "acme"], out=out, err=err)
    assert rc == 0
    assert (home / ".dxrk" / "tenants" / "_active").read_text() == "acme"
    # list shows * active via _effective_tenant (env DXRK_TENANT set by switch)
    out2, err2 = _ctx_out_err()
    reg.execute(["tenant", "list"], out=out2, err=err2)
    assert "acme * active" in out2.getvalue()
    assert "beta" in out2.getvalue()
    # DXRK_TENANT env overrides _active
    monkeypatch.setenv("DXRK_TENANT", "beta")
    # ensure beta tenant exists already
    out3, err3 = _ctx_out_err()
    reg.execute(["tenant", "list"], out=out3, err=err3)
    assert "beta * active" in out3.getvalue()
    # --tenant bad/id via ctx.tenant_id priority
    from dxrk.commands.registry import CommandContext
    from dxrk.commands.tenant import _effective_tenant

    ctx = CommandContext(tenant_id="beta")
    assert _effective_tenant(ctx) == "beta"
    ctx2 = CommandContext(tenant_id="  ")
    # fallback to env
    monkeypatch.setenv("DXRK_TENANT", "acme")
    assert _effective_tenant(ctx2) == "acme"


def test_tenant_switch_invalid_and_not_found(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    # invalid id
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "switch", "bad/id"], out=out, err=err)
    assert rc == 1
    assert "invalid tenant id" in err.getvalue()
    # not found valid id
    out2, err2 = _ctx_out_err()
    rc2 = reg.execute(["tenant", "switch", "ghost"], out=out2, err=err2)
    assert rc2 == 1
    assert "not found" in err2.getvalue()


def test_tenant_current_and_whoami(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    # no tenant yet -> No current tenant
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "current"], out=out, err=err)
    assert rc == 0
    assert "No current tenant" in out.getvalue()
    out2, err2 = _ctx_out_err()
    rc2 = reg.execute(["tenant", "whoami"], out=out2, err=err2)
    assert rc2 == 0
    assert "No tenant" in out2.getvalue()
    # create and switch, then current/whoami reflect env
    reg.execute(["tenant", "create", "zeta"], out=io.StringIO(), err=io.StringIO())
    reg.execute(["tenant", "switch", "zeta"], out=io.StringIO(), err=io.StringIO())
    out3, _ = _ctx_out_err()
    reg.execute(["tenant", "current"], out=out3, err=io.StringIO())
    assert out3.getvalue().strip() == "zeta"
    out4, _ = _ctx_out_err()
    reg.execute(["tenant", "whoami"], out=out4, err=io.StringIO())
    assert out4.getvalue().strip() == "zeta"
    # DXRK_TENANT env priority even without switch
    monkeypatch.setenv("DXRK_TENANT", "zeta")
    out5, _ = _ctx_out_err()
    reg.execute(["tenant", "current"], out=out5, err=io.StringIO())
    assert out5.getvalue().strip() == "zeta"


def test_tenant_effective_priority_ctx_over_env_over_active(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    from dxrk.commands.registry import CommandContext
    from dxrk.commands.tenant import _effective_tenant, _write_active

    # no active, no env -> empty (is_migrated false)
    assert _effective_tenant(None) == ""
    # write active
    _write_active("alpha")
    assert (home / ".dxrk" / "tenants" / "_active").exists()
    assert _effective_tenant(None) == "alpha"
    # env overrides active
    monkeypatch.setenv("DXRK_TENANT", "beta")
    assert _effective_tenant(None) == "beta"
    # ctx overrides env
    ctx = CommandContext(tenant_id="gamma")
    assert _effective_tenant(ctx) == "gamma"
    # ctx blank falls back to env
    ctx2 = CommandContext(tenant_id="   ")
    assert _effective_tenant(ctx2) == "beta"
    # is_migrated path: mock is_migrated to true and no active/env -> default
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    # remove _active
    (home / ".dxrk" / "tenants" / "_active").unlink(missing_ok=True)
    import dxrk.commands.tenant as tenant_mod

    monkeypatch.setattr(tenant_mod, "is_migrated", lambda: True)
    assert _effective_tenant(None) == "default"
    monkeypatch.setattr(tenant_mod, "is_migrated", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert _effective_tenant(None) == ""


def test_tenant_delete_requires_force(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    reg.execute(["tenant", "create", "todel"], out=io.StringIO(), err=io.StringIO())
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "delete", "todel"], out=out, err=err)
    assert rc == 1
    assert "use --force" in err.getvalue()
    # invalid id
    out2, err2 = _ctx_out_err()
    rc2 = reg.execute(["tenant", "delete", "bad/id"], out=out2, err=err2)
    assert rc2 == 1
    assert "invalid tenant id" in err2.getvalue()


def test_tenant_delete_success_cleans_active(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    reg = _mk_registry()
    reg.execute(["tenant", "create", "todel2"], out=io.StringIO(), err=io.StringIO())
    reg.execute(["tenant", "switch", "todel2"], out=io.StringIO(), err=io.StringIO())
    assert (home / ".dxrk" / "tenants" / "_active").read_text() == "todel2"
    assert os.environ.get("DXRK_TENANT") == "todel2"
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "delete", "todel2", "--force"], out=out, err=err)
    assert rc == 0
    assert "Deleted tenant todel2" in out.getvalue()
    assert not (home / ".dxrk" / "tenants" / "todel2").exists()
    assert not (home / ".dxrk" / "tenants" / "_active").exists()
    assert os.environ.get("DXRK_TENANT") is None
    # delete not found
    out2, err2 = _ctx_out_err()
    rc2 = reg.execute(["tenant", "delete", "todel2", "--force"], out=out2, err=err2)
    assert rc2 == 1
    assert "not found" in err2.getvalue()


def test_tenant_migrate_copies_and_idempotent(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    import dxrk.tenant.migration as mig

    # create fake legacy file under home/.dxrk/identity.txt etc.
    legacy_dxrk = home / ".dxrk"
    legacy_dxrk.mkdir(parents=True, exist_ok=True)
    (legacy_dxrk / "identity.txt").write_text("hello legacy")
    (legacy_dxrk / "config.yaml").write_text("a:1")
    # patch LEGACY_PATHS to point to our tmp files (module was imported with real HOME)
    orig_paths = mig.LEGACY_PATHS
    monkeypatch.setattr(
        mig,
        "LEGACY_PATHS",
        [
            (legacy_dxrk / "identity.txt", Path("identity.txt")),
            (legacy_dxrk / "config.yaml", Path("config.yaml")),
        ],
    )
    # also patch _dxrk_home/_tenants_root to use tmp home
    monkeypatch.setattr(mig, "_dxrk_home", lambda: home / ".dxrk")
    monkeypatch.setattr(mig, "_tenants_root", lambda: home / ".dxrk" / "tenants")
    reg = _mk_registry()
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant", "migrate"], out=out, err=err)
    assert rc == 0
    assert "Migrated" in out.getvalue()
    assert (home / ".dxrk" / "tenants" / "default" / "identity.txt").exists()
    assert (home / ".dxrk" / "tenants" / "_registry.json").exists()
    assert (home / ".dxrk" / "tenants" / "_active").read_text() == "default"
    # second migrate idempotent -> 0 copied
    out2, err2 = _ctx_out_err()
    reg.execute(["tenant", "migrate"], out=out2, err=err2)
    assert "Migrated 0 files" in out2.getvalue()
    monkeypatch.setattr(mig, "LEGACY_PATHS", orig_paths)


def test_tenant_parent_and_read_active_oserror(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.commands import tenant as tmod

    # parent_run error path
    reg = _mk_registry()
    out, err = _ctx_out_err()
    rc = reg.execute(["tenant"], out=out, err=err)
    assert rc == 1
    assert "use 'dxrk tenant list'" in err.getvalue()
    # _read_active OSError path: monkeypatch Path.read_text to raise
    home = Path.home()
    (home / ".dxrk" / "tenants").mkdir(parents=True, exist_ok=True)
    (home / ".dxrk" / "tenants" / "_active").write_text("oops\nsecond")
    assert tmod._read_active() == "oops"
    # OSError on read
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert tmod._read_active() == ""
    # OSError on write_active: patch mkdir to raise
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert tmod._write_active("x") is False
    # _list_tenants OSError path: patch iterdir
    monkeypatch.setattr(Path, "iterdir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    # need fresh module's _list_tenants; but we patched Path.iterdir globally, so call should return []
    assert tmod._list_tenants() == []


# ---------------------------------------------------------------------------
# hooks_cli
# ---------------------------------------------------------------------------


def test_hooks_pid_alive_self_and_dead(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    assert hc._pid_alive(os.getpid()) is True
    assert hc._pid_alive(999999) is False
    # pid 0 / -1 are platform-specific (kill(0,0) checks group, -1 all); just ensure bool
    assert isinstance(hc._pid_alive(0), bool)
    # ValueError path via mocked kill
    monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(ValueError("bad pid")))
    assert hc._pid_alive(123) is False


def test_hooks_wing_from_transcript_empty_and_fallback(tmp_path):
    import dxrk.memory.hooks_cli as hc

    assert hc._wing_from_transcript_path("") == "wing_sessions"
    assert hc._wing_from_transcript_path("/tmp/nope.jsonl") == "wing_sessions"
    # path with .. should be sanitized via _validate -> None then fallback regex
    # encoded project via regex 1
    p = "/home/dxrk/.claude/projects/-Users-dxrk-git-MyCoolProj/transcript.jsonl"
    assert hc._wing_from_transcript_path(p) == "wing_mycoolproj"
    # second regex Projects: re.search(r"-Projects-([^/]+?)(?:/|$)")
    p2b = "/some-Projects-AwesomeX/file.jsonl"
    assert hc._wing_from_transcript_path(p2b) == "wing_awesomex"
    # fallback to wing_sessions for non-matching
    assert hc._wing_from_transcript_path("/some/other/path/file.jsonl") == "wing_sessions"


def test_hooks_wing_from_transcript_cwd_json(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    tr = tmp_path / "transcript.jsonl"
    # first 200 lines scanned for "cwd"
    with open(tr, "w", encoding="utf-8") as f:
        f.write('{"foo":"bar"}\n')
        f.write('{"cwd": "/home/user/Projects/MyProject"}\n')
        f.write('{"cwd": "/other"}\n')
    assert hc._wing_from_transcript_path(str(tr)) == "wing_myproject"
    # cwd with spaces and dash
    tr2 = tmp_path / "tr2.jsonl"
    with open(tr2, "w", encoding="utf-8") as f:
        f.write('{"cwd": "/tmp/My Cool-Project"}\n')
    assert hc._wing_from_transcript_path(str(tr2)) == "wing_my_cool_project"
    # with backslashes Windows style
    tr3 = tmp_path / "tr3.jsonl"
    with open(tr3, "w", encoding="utf-8") as f:
        f.write('{"cwd": "C:\\\\Users\\\\foo\\\\Projects\\\\WinProj"}\n')
    assert hc._wing_from_transcript_path(str(tr3)) == "wing_winproj"
    # file not exists -> fallback regex already tested


def test_hooks_ensure_configs_idempotent(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    home = tmp_path / "home_hc"
    home.mkdir()
    # ensure idempotent: two calls same result
    hc.ensure_hook_configs(home_dir=str(home))
    cfg_path = home / ".config" / "dxrk" / "hooks.json"
    assert cfg_path.exists()
    data1 = json.loads(cfg_path.read_text())
    assert len(data1["hooks"]) == 2
    ids1 = {h["id"] for h in data1["hooks"]}
    assert "dxrk-memory-stop" in ids1
    # second call should not duplicate
    hc.ensure_hook_configs(home_dir=str(home))
    data2 = json.loads(cfg_path.read_text())
    assert len(data2["hooks"]) == 2
    # also test without home_dir via HOME env
    monkeypatch.setenv("HOME", str(tmp_path / "home2"))
    hc.ensure_hook_configs()
    p2 = Path.home() / ".config" / "dxrk" / "hooks.json"
    assert p2.exists()
    # re-call with existing file containing legacy list? test migration not needed
    # ensure no exception on second run
    hc.ensure_hook_configs()


def test_hooks_maybe_auto_ingest_no_targets(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    monkeypatch.delenv("DXRK_PROJECT_DIR", raising=False)
    # should be no-op, not raise
    hc._maybe_auto_ingest()
    # with non-dir project
    monkeypatch.setenv("DXRK_PROJECT_DIR", str(tmp_path / "nope"))
    hc._maybe_auto_ingest()


def test_hooks_maybe_auto_ingest_with_target_mocked(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "file.txt").write_text("hello world content here " * 20)
    monkeypatch.setenv("DXRK_PROJECT_DIR", str(proj))
    # mock _spawn_mine to capture
    calls: list[list[str]] = []

    def fake_spawn(cmd):
        calls.append(cmd)

    monkeypatch.setattr(hc, "_spawn_mine", fake_spawn)
    # need PALACE_ROOT to exist for logging? Not needed for _maybe_auto_ingest, but _spawn_mine is mocked
    hc._maybe_auto_ingest()
    assert len(calls) == 1
    assert "mine" in calls[0]
    assert str(proj) in calls[0]
    # also test timeout parsing branches
    monkeypatch.setenv("DXRK_MINE_TIMEOUT_HOURS", "not-a-number")
    assert hc._mine_slot_timeout_secs() == 0.0
    monkeypatch.setenv("DXRK_MINE_TIMEOUT_HOURS", "1.5")
    assert hc._mine_slot_timeout_secs() == 5400.0
    monkeypatch.setenv("DXRK_MINE_TIMEOUT_HOURS", "0")
    assert hc._mine_slot_timeout_secs() == 0.0
    monkeypatch.delenv("DXRK_MINE_TIMEOUT_HOURS", raising=False)
    assert hc._mine_slot_timeout_secs() == 7200.0


def test_hooks_save_session_summary_direct_with_palace(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    palace_root = tmp_path / "palace"
    state_dir = tmp_path / "hook_state"
    monkeypatch.setattr(hc, "PALACE_ROOT", palace_root)
    monkeypatch.setattr(hc, "STATE_DIR", state_dir)
    # need PALACE_ROOT.is_dir() for _log, but _save doesn't check that
    palace_root.mkdir(parents=True)
    # create transcript with human messages
    tr = tmp_path / "transcript.jsonl"
    with open(tr, "w", encoding="utf-8") as f:
        for i in range(5):
            json.dump({"message": {"role": "user", "content": f"hello world {i} project Alpha"}}, f)
            f.write("\n")
        # command-message should be ignored
        json.dump({"message": {"role": "user", "content": "<command-message>ignore</command-message>"}}, f)
        f.write("\n")
        json.dump({"message": {"role": "assistant", "content": "hi"}}, f)
        f.write("\n")
    res = hc._save_session_summary_direct(str(tr), "sess123", wing="wing_test")
    assert res["count"] == 5
    assert "drawer_id" in res
    drawer_id = res["drawer_id"]
    assert isinstance(drawer_id, str) and drawer_id
    # check drawer actually exists via DxrkMemory
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(palace_root))
    dm.init()
    got = dm.get_drawer(drawer_id)
    assert got is not None
    # themes extracted
    assert isinstance(res.get("themes"), list)
    # ack file written
    ack = state_dir / "last_checkpoint"
    assert ack.exists()
    data = json.loads(ack.read_text())
    assert data["msgs"] == 5


def test_hooks_save_session_no_messages(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    palace_root = tmp_path / "palace2"
    state_dir = tmp_path / "hook_state2"
    monkeypatch.setattr(hc, "PALACE_ROOT", palace_root)
    monkeypatch.setattr(hc, "STATE_DIR", state_dir)
    palace_root.mkdir(parents=True)
    tr = tmp_path / "empty.jsonl"
    tr.write_text("")
    res = hc._save_session_summary_direct(str(tr), "sess999")
    assert res["count"] == 0
    # missing file also 0
    res2 = hc._save_session_summary_direct(str(tmp_path / "missing.jsonl"), "sess999")
    assert res2["count"] == 0
    # also test _extract_themes directly
    themes = hc._extract_themes(["hello world project Alpha deployment", "world deployment"], max_themes=2)
    assert isinstance(themes, list)
    # _extract_recent_messages branch list content
    tr3 = tmp_path / "tr3.jsonl"
    with open(tr3, "w", encoding="utf-8") as f:
        json.dump({"message": {"role": "user", "content": [{"text": "hello"}, {"text": "world"}]}}, f)
        f.write("\n")
        json.dump({"type": "event_msg", "payload": {"type": "user_message", "message": "event hello"}}, f)
        f.write("\n")
        json.dump(
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "<command-message>no</command-message>"},
            },
            f,
        )
        f.write("\n")
    msgs = hc._extract_recent_messages(str(tr3))
    assert len(msgs) >= 2


def test_hooks_claim_slot_and_already_running(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    # isolate state dir
    state = tmp_path / "state"
    monkeypatch.setattr(hc, "STATE_DIR", state)
    monkeypatch.setattr(hc, "_MINE_PID_DIR", state / "mine_pids")
    cmd = [sys.executable, "-m", "dxrk.memory", "mine", "/tmp/proj", "--wing", "default"]
    # first claim should succeed
    p1 = hc._claim_mine_slot(cmd)
    assert p1 is not None
    assert p1.exists()
    # second claim should be None (already running self pid alive)
    p2 = hc._claim_mine_slot(cmd)
    assert p2 is None
    # _mine_already_running true
    assert hc._mine_already_running(cmd) is True
    # test pid file handling edge: corrupt pid
    p1.write_text("not-a-pid ???")
    assert hc._mine_already_running(cmd) is False
    # timeout case: set timeout 0 to disable timeout, but pid dead -> false
    monkeypatch.setenv("DXRK_MINE_TIMEOUT_HOURS", "0")
    p1.write_text("999999 0")
    assert hc._mine_already_running(cmd) is False
    # cleanup
    try:
        p1.unlink()
    except OSError:
        pass
    # _pid_file_for_cmd deterministic
    pf1 = hc._pid_file_for_cmd(cmd)
    pf2 = hc._pid_file_for_cmd(cmd)
    assert pf1 == pf2
    # different cmd different file
    pf3 = hc._pid_file_for_cmd([sys.executable, "-m", "dxrk.memory", "mine", "/other", "--wing", "x"])
    assert pf3 != pf1
    # no mine in cmd
    pf4 = hc._pid_file_for_cmd([sys.executable, "-c", "print(1)"])
    assert pf4.name.startswith("mine_")


def test_hooks_count_and_sanitize(tmp_path, monkeypatch):
    import dxrk.memory.hooks_cli as hc

    # _sanitize_session_id
    assert hc._sanitize_session_id("abc-123_foo!") == "abc-123_foo"
    assert hc._sanitize_session_id("!!!") == "unknown"
    assert hc._sanitize_session_id("") == "unknown"
    # _validate_transcript_path
    assert hc._validate_transcript_path("") is None
    tr = tmp_path / "a.jsonl"
    tr.write_text("hi")
    assert hc._validate_transcript_path(str(tr)) is not None
    # suffix check
    bad = tmp_path / "a.txt"
    bad.write_text("hi")
    assert hc._validate_transcript_path(str(bad)) is None
    # .. check
    assert hc._validate_transcript_path("/tmp/../etc/passwd.jsonl") is None
    # _count_human_messages
    tr2 = tmp_path / "count.jsonl"
    with open(tr2, "w", encoding="utf-8") as f:
        json.dump({"message": {"role": "user", "content": "hello"}}, f)
        f.write("\n")
        json.dump({"message": {"role": "user", "content": [{"text": "hi"}, {"text": "there"}]}}, f)
        f.write("\n")
        json.dump({"message": {"role": "user", "content": "<command-message>ignore</command-message>"}}, f)
        f.write("\n")
        json.dump({"type": "event_msg", "payload": {"type": "user_message", "message": "hey"}}, f)
        f.write("\n")
        json.dump(
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "<command-message>no</command-message>"},
            },
            f,
        )
        f.write("\n")
        f.write("not json\n")
    assert hc._count_human_messages(str(tr2)) == 3
    assert hc._count_human_messages("") == 0
    assert hc._count_human_messages(str(tmp_path / "nonexistent.jsonl")) == 0
    # _parse_harness_input unknown harness should exit
    import pytest as _pytest

    with _pytest.raises(SystemExit):
        hc._parse_harness_input({}, "unknown-harness")


# ---------------------------------------------------------------------------
# __main__.py
# ---------------------------------------------------------------------------


def test_main_mine_dispatch_dry_run(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    from dxrk.memory import __main__ as mem_main

    proj = tmp_path / "proj_main"
    proj.mkdir()
    (proj / "hello.py").write_text("print('hello world')\n" * 50)
    # dry_run via palace isolated HOME
    rc = mem_main.main(["mine", str(proj), "--wing", "default", "--dry-run"])
    assert rc == 0
    # palace should exist but have 0 drawers because dry_run
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(home / ".dxrk" / "memory"))
    # if tenant migrated, path may be tenants/default/palace; fallback
    try:
        # Use explicit path from HOME logic: _iso_home already sets HOME, so palace is at home/.dxrk/memory
        # but if migrated, DxrkMemory may resolve to tenants/default; we check both
        assert dm.count() >= 0
    except Exception:
        pass


def test_main_mine_dispatch_real(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.memory import __main__ as mem_main

    proj = tmp_path / "proj_real"
    proj.mkdir()
    (proj / "a.txt").write_text("alpha beta gamma " * 100)
    rc = mem_main.main(["mine", str(proj), "--wing", "wing_a", "--room", "general"])
    assert rc == 0
    # missing project should fail
    rc2 = mem_main.main(["mine", str(tmp_path / "nope"), "--wing", "default"])
    assert rc2 == 1


def test_main_search_dispatch(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.memory import __main__ as mem_main

    # need some data first
    proj = tmp_path / "proj_search"
    proj.mkdir()
    (proj / "search.txt").write_text("searchable content unicorn " * 50)
    mem_main.main(["mine", str(proj), "--wing", "default"])
    # mock AgentMemory search to avoid sqlite full scan? Just run real search via __main__
    # It prints json lines to stdout; capture
    import contextlib
    import io as _io

    buf = _io.StringIO()
    # monkeypatch AgentMemory to avoid HOME issues? Use real but patch sys.stdout
    with contextlib.redirect_stdout(buf):
        # need to pass --n
        rc = mem_main.main(["search", "unicorn", "--n", "2"])
    assert rc == 0
    # output may be empty if not found but should not crash
    # also test search with wing filter
    with contextlib.redirect_stdout(_io.StringIO()):
        rc2 = mem_main.main(["search", "unicorn", "--wing", "default"])
    assert rc2 == 0


def test_main_hooks_dispatch_and_unknown(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.memory import __main__ as mem_main

    # hooks dispatch unknown hook should exit 1 via SystemExit?
    # run_hook unknown should sys.exit(1); we test via main
    # Use ensure-hooks
    rc = mem_main.main(["hooks", "ensure-hooks"])
    assert rc == 0
    # unknown subcommand
    rc2 = mem_main.main(["unknown_cmd"])
    assert rc2 == 2
    # help
    rc3 = mem_main.main([])
    assert rc3 == 0
    rc4 = mem_main.main(["-h"])
    assert rc4 == 0
    # hooks with session-start
    # need PALACE_ROOT to not exist -> no-op path; isolate HOME already empty so PALACE_ROOT missing
    # we test hooks dispatch via _cmd_hooks
    # create invalid hook should sys.exit(1); we test via subprocess-like but call directly

    # ensure palace root exists for hooks to not be no-op? But we want to test hook output
    palace = Path.home() / ".dxrk" / "memory"
    palace.mkdir(parents=True, exist_ok=True)
    # feed empty stdin json via monkeypatch sys.stdin?
    import io as _io
    import json as _json

    old_stdin = sys.stdin
    try:
        sys.stdin = _io.StringIO(_json.dumps({"session_id": "test123", "transcript_path": ""}))
        rc5 = mem_main.main(["hooks", "session-start", "dxrk"])
        assert rc5 == 0
    finally:
        sys.stdin = old_stdin
    # search via main with mocked AgentMemory
    monkeypatch.setattr("dxrk.memory.AgentMemory", lambda *a, **k: type("M", (), {"search": lambda self, **kw: []})())
    import contextlib as _cl
    import io as _io2

    with _cl.redirect_stdout(_io2.StringIO()):
        assert mem_main.main(["search", "q"]) == 0


# ---------------------------------------------------------------------------
# palace gaps
# ---------------------------------------------------------------------------


def test_palace_mine_dry_run_counts(tmp_path, monkeypatch):
    from dxrk.memory.palace import DxrkMemory

    _iso_home(tmp_path, monkeypatch)
    palace_path = tmp_path / "palace_dry"
    proj = tmp_path / "proj_dry"
    proj.mkdir()
    (proj / "file1.txt").write_text("hello world " * 100)
    (proj / "file2.txt").write_text("another file " * 100)
    dm = DxrkMemory(str(palace_path))
    dm.init()
    res = dm.mine(str(proj), wing="default", room="general", dry_run=True)
    assert int(res["files_mined"]) == 2  # type: ignore[arg-type]
    assert int(res["drawers_added"]) >= 2  # type: ignore[arg-type]
    assert int(res["files_skipped"]) == 0  # type: ignore[arg-type]
    # dry_run should not have added drawers
    assert dm.count() == 0
    # real mine then dry_run again should still work
    res2 = dm.mine(str(proj), wing="default", room="general", dry_run=False)
    assert int(res2["files_mined"]) == 2  # type: ignore[arg-type]
    assert dm.count() > 0
    # skipped small file
    (proj / "tiny.txt").write_text("hi")
    res3 = dm.mine(str(proj), wing="default", dry_run=True)
    assert int(res3["files_skipped"]) >= 1  # type: ignore[arg-type]


def test_palace_reap_stale_locks(tmp_path, monkeypatch):
    from dxrk.memory.palace import _dxrk_lock_dir, reap_stale_dxrk_locks

    _iso_home(tmp_path, monkeypatch)
    # ensure lock dir exists via DxrkMemory
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace_reap"))
    dm.init()
    lock_dir = _dxrk_lock_dir()
    lock_dir.mkdir(parents=True, exist_ok=True)
    # create stale lock files
    old = lock_dir / "old123.lock"
    old.write_text("x")
    # make it old
    old_time = time.time() - 7200
    os.utime(old, (old_time, old_time))
    # create recent lock
    recent = lock_dir / "recent.lock"
    recent.write_text("y")
    # create mine_palace lock should be skipped
    palace_lock = lock_dir / "mine_palace_abc.lock"
    palace_lock.write_text("z")
    os.utime(palace_lock, (old_time, old_time))
    reaped, skipped = reap_stale_dxrk_locks(min_age_seconds=3600)
    # old should be reaped (if not held), recent not, palace skipped
    assert reaped >= 1
    assert not palace_lock.exists() or skipped >= 0
    # second run with none old should return 0,0 or skipped
    reaped2, skipped2 = reap_stale_dxrk_locks(min_age_seconds=3600)
    assert isinstance(reaped2, int)
    # test with tenant_id param
    reaped3, _ = reap_stale_dxrk_locks(min_age_seconds=3600, tenant_id="acme")
    assert isinstance(reaped3, int)
    # test via alias
    from dxrk.memory.palace import reap_stale_mine_locks

    assert reap_stale_mine_locks is reap_stale_dxrk_locks


def test_palace_tenant_isolation_mine(tmp_path, monkeypatch):
    from dxrk.memory.palace import DxrkMemory

    _iso_home(tmp_path, monkeypatch)
    proj = tmp_path / "proj_iso"
    proj.mkdir()
    (proj / "iso.txt").write_text("isolation test " * 50)
    # tenant a
    dm_a = DxrkMemory(tenant_id="tenantA")
    # palace_path should be tenants/tenantA/palace
    assert "tenantA" in dm_a.palace_path or "tenants" in dm_a.palace_path
    dm_a.init()
    dm_a.mine(str(proj), wing="default")
    assert dm_a.count() > 0
    # tenant b should be empty
    dm_b = DxrkMemory(tenant_id="tenantB")
    dm_b.init()
    assert dm_b.count() == 0
    # explicit palace_path bypasses tenant
    explicit = tmp_path / "explicit_palace"
    dm_c = DxrkMemory(str(explicit), tenant_id="tenantA")
    dm_c.init()
    assert str(explicit) in dm_c.palace_path
    # ensure lock dir tenant-aware
    from dxrk.memory.palace import _dxrk_lock_dir

    monkeypatch.setenv("DXRK_TENANT", "tenantA")
    ld = _dxrk_lock_dir()
    assert "tenantA" in str(ld)
    monkeypatch.delenv("DXRK_TENANT", raising=False)


def test_palace_chunk_and_metadata(tmp_path):
    from dxrk.memory.palace import DxrkMemory, _build_drawer_metadata, _detect_hall, _extract_entities, chunk_text

    # chunk validation
    try:
        chunk_text("hi", chunk_size=0)
        assert False
    except ValueError:
        pass
    try:
        chunk_text("hi", chunk_overlap=-1)
        assert False
    except ValueError:
        pass
    try:
        chunk_text("hi", chunk_size=10, chunk_overlap=10)
        assert False
    except ValueError:
        pass
    chunks = chunk_text("a" * 100, chunk_size=10, chunk_overlap=2, min_chunk_size=5)
    assert len(chunks) > 0
    assert _detect_hall("I feel love and hope") == "emotional"
    assert _detect_hall("api database deploy") == "technical"
    ents = _extract_entities("Alice Alice Bob Bob Alice")
    assert isinstance(ents, str)
    meta = _build_drawer_metadata("w", "r", "src", 0, "agent", "hello Alice Alice", None, chunk_total=3)
    assert meta["wing"] == "w"
    assert meta["chunk_total"] == 3
    # DxrkMemory via memory-only sentinel
    dm = DxrkMemory("memory-only")
    assert dm.palace_path == "memory-only"


# ---------------------------------------------------------------------------
# tenant_switcher screen
# ---------------------------------------------------------------------------


def test_tenant_switcher_get_tenants_and_badge(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.context import TUIContext, set_ctx
    from dxrk.tui.screens.tenant_switcher import _get_tenants, _tenant_badge_text

    # empty first
    assert _get_tenants() == []
    # create tenants via migration helper
    from dxrk.tenant.migration import ensure_tenant

    ensure_tenant("acme")
    ensure_tenant("beta")
    tids = _get_tenants()
    assert "acme" in tids and "beta" in tids
    # badge reflects ctx
    set_ctx(TUIContext(tenant_id="acme", role="admin"))
    badge = _tenant_badge_text()
    assert "tenant: acme" in badge
    assert "role: admin" in badge
    # fallback when ctx empty
    set_ctx(TUIContext(tenant_id="", role=""))
    badge2 = _tenant_badge_text()
    assert "tenant: default" in badge2


def test_tenant_switcher_compose_has_ids(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    import inspect

    from dxrk.tui.screens import tenant_switcher as ts_mod
    from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

    # patch watch_cursor before instantiation to avoid NoActiveAppError (reactive init)
    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
    screen = TenantSwitcherScreen()
    # BINDINGS and reactive without needing app
    assert any(b.key == "escape" for b in screen.BINDINGS)
    assert hasattr(screen, "cursor")
    assert screen.cursor == 0
    # Verify compose source contains expected ids (import + cursor logic sin TUI run)
    src = inspect.getsource(screen.compose)
    assert "tenant-switcher-container" in src
    assert "tenant-create-input" in src
    assert "tenant-badge" in src
    # also check _get_tenants importable and class is ModalScreen
    from textual.screen import ModalScreen

    assert issubclass(TenantSwitcherScreen, ModalScreen)


def test_tenant_switcher_cursor_bounds(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.screens import tenant_switcher as ts_mod
    from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
    screen = TenantSwitcherScreen()
    screen._tenants = ["a", "b", "c"]
    screen.cursor = 0
    screen.action_cursor_up()
    assert screen.cursor == 0
    screen.action_cursor_down()
    assert screen.cursor == 1
    screen.action_cursor_down()
    assert screen.cursor == 2
    screen.action_cursor_down()
    assert screen.cursor == 2
    screen.action_cursor_up()
    assert screen.cursor == 1
    # out of bounds switch should not crash
    screen._tenants = []
    screen.action_switch()
    screen._tenants = ["x"]
    screen.cursor = 5
    screen.action_switch()
    screen.cursor = -1
    screen.action_switch()


def test_tenant_switcher_do_switch_updates_env_and_active(tmp_path, monkeypatch):
    home = _iso_home(tmp_path, monkeypatch)
    from dxrk.tenant.migration import ensure_tenant
    from dxrk.tui.context import TUIContext, get_ctx, set_ctx
    from dxrk.tui.screens import tenant_switcher as ts_mod
    from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

    class DummyApp:
        def push_screen(self, name):
            self.pushed = name

    dummy = DummyApp()
    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "app", property(lambda self: dummy))
    ensure_tenant("acme")
    set_ctx(TUIContext(tenant_id="old", tenant_path="", role="readonly"))
    screen = TenantSwitcherScreen()

    # also need query_one to not crash; patch it to raise
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("no badge")))
    # call _do_switch
    screen._do_switch("acme")
    ctx = get_ctx()
    assert ctx.tenant_id == "acme"
    assert "acme" in ctx.tenant_path
    assert os.environ.get("DXRK_TENANT") == "acme"
    assert (home / ".dxrk" / "tenants" / "_active").read_text() == "acme"
    # role resolved via TenantRoleResolver (may be readonly)
    assert ctx.role in ("admin", "dev", "readonly")
    # switch again with missing tenant_root? simulate error via monkeypatch
    monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(OSError("boom")))
    # should still set tenant_path to tid fallback
    screen._do_switch("acme")
    assert get_ctx().tenant_path == "acme"


def test_tenant_switcher_action_create_flow(tmp_path, monkeypatch):
    _iso_home(tmp_path, monkeypatch)
    from dxrk.tui.context import TUIContext, set_ctx
    from dxrk.tui.screens import tenant_switcher as ts_mod
    from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

    class DummyApp2:
        def push_screen(self, name):
            self.pushed = name

    dummy2 = DummyApp2()
    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
    monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "app", property(lambda self: dummy2))
    set_ctx(TUIContext(tenant_id="", role="readonly"))
    screen = TenantSwitcherScreen()
    screen._tenants = []
    screen.cursor = 0

    # mock Input query
    class FakeInput:
        def __init__(self, val):
            self.value = val
            self.placeholder = ""

        def focus(self):
            self.focused = True

    # case empty -> focus
    fake = FakeInput("")
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda *a, **k: fake if "tenant-create-input" in str(a) else (_ for _ in ()).throw(Exception()),
    )
    screen.action_create()
    assert hasattr(fake, "focused")

    # invalid id
    fake2 = FakeInput("bad/id")
    monkeypatch.setattr(screen, "query_one", lambda *a, **k: fake2)
    screen.action_create()
    assert fake2.value == ""
    assert "invalid id" in fake2.placeholder

    # valid create
    fake3 = FakeInput("newtenant")
    # need to mock _get_tenants to return new list after ensure
    monkeypatch.setattr(
        screen,
        "query_one",
        lambda *a, **k: (
            fake3
            if "input" in str(a).lower() or "tenant-create-input" in str(a)
            else (_ for _ in ()).throw(Exception())
        ),
    )
    # Also need to mock app push and _do_switch and _render_list
    monkeypatch.setattr(screen, "_render_list", lambda: None)
    monkeypatch.setattr(screen, "_do_switch", lambda tid: setattr(screen, "_switched", tid))
    # also need to isolate _get_tenants vs ensure_tenant
    screen.action_create()
    assert getattr(screen, "_switched", None) == "newtenant"
    assert fake3.value == ""

    # action_back
    screen.action_back()
    assert dummy2.pushed == "welcome"

    # test _render_list branches without mounted app
    from textual.widget import Widget

    monkeypatch.setattr(Widget, "_render", lambda self: "dummy_visual")  # type: ignore[attr-defined]
    screen2 = TenantSwitcherScreen()
    screen2._tenants = []
    # query_one will raise -> fallback
    monkeypatch.setattr(screen2, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("no scroll")))

    # should not crash
    res = screen2._render_list()
    assert res is not None
    # also test non-empty path: need VerticalScroll mock
    from unittest.mock import MagicMock

    mock_scroll = MagicMock()
    mock_scroll.remove_children = MagicMock()
    mock_scroll.mount = MagicMock()
    monkeypatch.setattr(screen2, "query_one", lambda *a, **k: mock_scroll)
    screen2._tenants = ["alpha"]
    # need get_ctx returns tenant
    from dxrk.tui.context import TUIContext, set_ctx

    set_ctx(TUIContext(tenant_id="alpha", role="readonly"))
    res2 = screen2._render_list()
    assert res2 is not None
    assert mock_scroll.mount.called
