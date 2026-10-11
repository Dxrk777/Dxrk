# SPDX-License-Identifier: MIT
"""Coverage for low-coverage red modules (part B): runtimes, memory cmd, sdd component."""

from __future__ import annotations

import io
import json
import os
from types import SimpleNamespace

import pytest

from dxrk.cli import runtime_restore as restore
from dxrk.cli import runtime_sync as syncmod
from dxrk.cli import runtime_uninstall as uninstall
from dxrk.cli import runtime_verify as verify
from dxrk.commands import memory as memcmd
from dxrk.commands.registry import CommandContext, Registry
from dxrk.components import sdd


def _ctx(**kw):
    kw.setdefault("out", io.StringIO())
    kw.setdefault("err", io.StringIO())
    return CommandContext(**kw)


def _deny(monkeypatch):
    def _raise(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("dxrk.security.enforcement.require_op", _raise)
    monkeypatch.setattr(memcmd, "require_op", _raise)


# ─── runtime_restore ─────────────────────────────────────────────────────────


def _make_home(tmp_path, snap_id="snap1", with_file=True):
    home = tmp_path / "home"
    snap = home / ".gentle-ai" / "backups" / snap_id
    snap.mkdir(parents=True)
    dest = tmp_path / "restored.txt"
    dest.write_text("old", encoding="utf-8")
    manifest = {"source": "test", "description": "d", "entries": []}
    if with_file:
        (snap / "rel").mkdir(parents=True)
        (snap / "rel" / "file.txt").write_text("content-1", encoding="utf-8")
        manifest["entries"].append({"source": str(dest), "dest": "rel/file.txt"})
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return home, dest


def test_restore_usage_and_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "home"))
    out = io.StringIO()
    assert restore.run_restore([], stdout=out) == "uso: dxrk-py restore [--list | latest | <id>] [--yes]"
    with pytest.raises(ValueError):
        restore.run_restore(["--bogus"], stdout=io.StringIO())


def test_restore_list(tmp_path, monkeypatch):
    home, _ = _make_home(tmp_path)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    out = io.StringIO()
    assert restore.run_restore(["--list"], stdout=out) is None
    assert "Copias disponibles (1)" in out.getvalue()
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "empty"))
    out = io.StringIO()
    restore.run_restore(["--list"], stdout=out)
    assert "no se encontraron" in out.getvalue()


def test_restore_latest_yes(tmp_path, monkeypatch):
    home, dest = _make_home(tmp_path)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    dest.write_text("new", encoding="utf-8")
    out = io.StringIO()
    restore.run_restore(["latest", "--yes"], stdout=out)
    assert dest.read_text(encoding="utf-8") == "content-1"
    assert "restauración completa" in out.getvalue()


def test_restore_by_id_and_errors(tmp_path, monkeypatch):
    home, _ = _make_home(tmp_path)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    with pytest.raises(ValueError):
        restore.run_restore(["nope", "--yes"], stdout=io.StringIO())
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "empty"))
    with pytest.raises(ValueError):
        restore.run_restore(["latest", "--yes"], stdout=io.StringIO())
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    out = io.StringIO()
    restore.run_restore(["snap1", "--yes"], stdout=out)
    assert "restauración completa" in out.getvalue()


def test_restore_confirm_flow(tmp_path, monkeypatch):
    home, _ = _make_home(tmp_path)
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    monkeypatch.setattr("builtins.input", lambda: "yes")
    out = io.StringIO()
    restore.run_restore(["latest"], stdout=out)
    assert "restauración completa" in out.getvalue()
    monkeypatch.setattr("builtins.input", lambda: "no")
    out = io.StringIO()
    assert restore.run_restore(["latest"], stdout=out) is None
    assert "cancelada" in out.getvalue()

    def _eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    out = io.StringIO()
    assert restore.run_restore(["latest"], stdout=out) is None
    assert "cancelada" in out.getvalue()


def test_restore_list_edge_cases(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root = home / ".gentle-ai" / "backups"
    root.mkdir(parents=True)
    (root / "stray.txt").write_text("x", encoding="utf-8")
    nodir = root / "nodir"
    nodir.mkdir()
    bad = root / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text("{nope", encoding="utf-8")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    assert restore._list_backups(str(home)) == []
    out = io.StringIO()
    restore._render_restore_list([], out)
    assert "no se encontraron" in out.getvalue()
    m = {"_id": "s1", "source": "x", "entries": [{}, {}], "created_by_version": "2"}
    out = io.StringIO()
    restore._render_restore_list([m], out)
    assert "[v2]" in out.getvalue()


def test_restore_missing_src_skipped(tmp_path, monkeypatch):
    home, _ = _make_home(tmp_path, with_file=False)
    snap = home / ".gentle-ai" / "backups" / "snap1"
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    manifest["entries"].append({"source": str(tmp_path / "d2.txt"), "dest": "rel/gone.txt"})
    manifest["entries"].append({"source": "", "dest": "rel/gone2.txt"})
    (snap / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(home))
    out = io.StringIO()
    restore.run_restore(["latest", "--yes"], stdout=out)
    assert "restauración completa" in out.getvalue()


# ─── runtime_uninstall ───────────────────────────────────────────────────────


def test_uninstall_confirm_branches(monkeypatch):
    from dxrk.cli.install_flags import UninstallFlags

    flags = UninstallFlags(all=True, agents=[], components=["sdd"])
    out = io.StringIO()
    monkeypatch.setattr("builtins.input", lambda: "yes")
    assert uninstall._prompt_uninstall_confirm(flags, out) is True
    assert "todos los agentes" in out.getvalue()
    flags = UninstallFlags(all=False, agents=["opencode"], components=[])
    out = io.StringIO()
    monkeypatch.setattr("builtins.input", lambda: "no")
    assert uninstall._prompt_uninstall_confirm(flags, out) is False
    assert "opencode" in out.getvalue()

    def _eof():
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)
    assert uninstall._prompt_uninstall_confirm(flags, io.StringIO()) is False


def test_uninstall_cancelled(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda: "no")
    out = io.StringIO()
    assert uninstall.run_uninstall(["--all"], stdout=out) is None
    assert "cancelada" in out.getvalue()


def test_uninstall_service_calls(monkeypatch):
    import dxrk.components.uninstall as cu

    calls = []

    class FakeService:
        def __init__(self, home_dir="", workspace_dir=""):
            pass

        def complete_uninstall(self):
            calls.append("complete")
            return "done-complete"

        def partial_uninstall(self, agents, components):
            calls.append(("partial", list(agents), list(components)))
            return "done-partial"

    monkeypatch.setattr(cu, "Service", FakeService)
    assert uninstall.run_uninstall(["--yes", "--all"], stdout=io.StringIO()) == "done-complete"
    assert uninstall.run_uninstall(["--yes", "--agent", "opencode"], stdout=io.StringIO()) == "done-partial"
    kind, agents, _ = calls[1]
    assert kind == "partial" and len(agents) == 1 and agents[0].value == "opencode"


# ─── runtime_verify ──────────────────────────────────────────────────────────


def test_verify_helpers():
    from dxrk.models import AgentID, ComponentID, ModelAssignment

    assert verify._has_component([ComponentID.SDD], ComponentID.SDD) is True
    assert verify._has_component([], ComponentID.SDD) is False
    assert verify._contains_agent([AgentID.OPENCODE], AgentID.OPENCODE) is True
    assert verify._contains_agent([], AgentID.OPENCODE) is False
    assert verify._antigravity_collision_check([]) == []
    assert verify._antigravity_collision_check([AgentID.ANTIGRAVITY]) == []
    assert verify._antigravity_collision_check([AgentID.GEMINI_CLI]) == []
    both = verify._antigravity_collision_check([AgentID.ANTIGRAVITY, AgentID.GEMINI_CLI])
    assert len(both) == 1 and both[0].soft is True
    assert verify._model_assignments_to_state(None) is None
    st = verify._model_assignments_to_state({"a": ModelAssignment(provider_id="p", model_id="m")})
    assert st["a"].provider_id == "p"
    assert verify._claude_aliases_to_strings(None) is None
    assert verify._claude_aliases_to_strings({"x": 1}) == {"x": "1"}


def test_verify_post_sync_empty(tmp_path):
    from dxrk.models import Selection

    rep = verify._run_post_sync_verification(str(tmp_path), Selection(agents=[], components=[]))
    assert rep.ready is True and rep.checks == []


def test_verify_post_apply_empty(tmp_path):
    from dxrk.models import Selection

    resolved = SimpleNamespace(ordered_components=[], agents=[])
    rep = verify._run_post_apply_verification(str(tmp_path), Selection(agents=[], components=[]), resolved)
    assert rep.ready is True


# ─── runtime_sync ────────────────────────────────────────────────────────────


def test_sync_ids_and_selection():
    from dxrk.cli.install_flags import SyncFlags
    from dxrk.models import AgentID, ComponentID, SDDModeID

    assert syncmod._to_agent_ids(["opencode"]) == [AgentID.OPENCODE]
    sel = syncmod.build_sync_selection(SyncFlags(), [AgentID.OPENCODE])
    assert sel.agents == [AgentID.OPENCODE]
    assert len(sel.components) == 5 and sel.sdd_mode == SDDModeID.SINGLE
    assert ComponentID.SDD in sel.components
    sel2 = syncmod.build_sync_selection(
        SyncFlags(include_permissions=True, include_theme=True, sdd_mode="multi"), [AgentID.OPENCODE]
    )
    assert len(sel2.components) == 7 and sel2.sdd_mode == SDDModeID.MULTI


def test_sync_discover_agents(monkeypatch):
    import dxrk.state as st

    monkeypatch.setattr(st, "read", lambda h: SimpleNamespace(installed_agents=["opencode"]))
    from dxrk.models import AgentID

    assert syncmod.discover_agents("/tmp") == [AgentID.OPENCODE]

    def _boom(h):
        raise OSError("no state")

    monkeypatch.setattr(st, "read", _boom)
    monkeypatch.setattr("dxrk.agents.discovery.discover_installed", lambda reg, h: [])
    assert syncmod.discover_agents("/tmp") == []


def test_sync_noop_and_stage(tmp_path):
    from dxrk.models import Selection

    r = syncmod.run_sync_with_selection(str(tmp_path), Selection(agents=[]))
    assert r.no_op is True and r.files_changed == 0
    rt = syncmod.SyncRuntime(str(tmp_path), str(tmp_path), Selection(agents=[], components=[]))
    plan = rt.stage_plan()
    assert len(plan.prepare) == 1 and len(plan.apply) == 1
    assert rt.files_changed == [0]


def test_sync_count_changed():
    from dxrk.models import ComponentID, Selection

    fc = [0]
    step = syncmod.ComponentSyncStep("s", ComponentID.SDD, "/tmp", "/tmp", [], Selection(agents=[]), fc)
    assert step.id() == "s"
    step._count_changed(0)
    assert fc == [0]
    step._count_changed(3)
    assert fc == [3]
    step2 = syncmod.ComponentSyncStep("s", ComponentID.SDD, "/tmp", "/tmp", [], Selection(agents=[]), [])
    step2._count_changed(5)


def test_sync_run_dry(monkeypatch, tmp_path):
    from dxrk.models import AgentID

    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    monkeypatch.setattr(syncmod, "discover_agents", lambda h: [])
    r = syncmod.run_sync(["--dry-run"])
    assert r.dry_run is True and r.no_op is True
    monkeypatch.setattr(syncmod, "discover_agents", lambda h: [AgentID.OPENCODE])
    r = syncmod.run_sync(["--dry-run"])
    assert r.dry_run is True and r.plan is not None
    seen = {}
    monkeypatch.setattr(
        syncmod, "run_sync_with_selection", lambda h, s: seen.setdefault("sel", s) or syncmod.SyncResult()
    )
    syncmod.run_sync(["--agent", "opencode"])
    assert seen["sel"].agents == [AgentID.OPENCODE]


# ─── commands/memory ─────────────────────────────────────────────────────────


def test_memory_helpers():
    total, avail = memcmd._meminfo()
    assert total >= 0 and avail >= 0
    assert memcmd._process_rss_kb() >= 0


def test_memory_base_run():
    reg = Registry()
    memcmd.register_memory_command(reg)
    ctx = _ctx()
    assert reg.get_command("memory").run(ctx) == 0
    assert "Uso de memoria" in ctx.out.getvalue()


def test_memory_denied_paths(monkeypatch):
    _deny(monkeypatch)
    reg = Registry()
    memcmd.register_memory_command(reg)
    for name in [
        "memory",
        "memory eval synthetic",
        "memory metacog predict",
        "memory metacog calibrate",
        "memory calibrate tenant",
        "memory calibrate chain",
        "memory production circuit-breaker",
        "memory production slo",
        "memory production rollback",
        "memory judge status",
        "memory judge run",
    ]:
        cmd = reg.get_command(name)
        assert cmd is not None, name
        ctx = _ctx(tenant_id="acme", args=["a", "b"])
        assert cmd.run(ctx) == 1, name
        assert "Error" in ctx.err.getvalue(), name


def test_memory_allowed_readonly(monkeypatch, tmp_path):
    monkeypatch.setenv("DXRK_MEMORY_PATH", str(tmp_path))
    reg = Registry()
    memcmd.register_memory_command(reg)
    ctx = _ctx()
    assert reg.get_command("memory production circuit-breaker").run(ctx) == 0
    assert "Circuit Breakers" in ctx.out.getvalue()
    ctx = _ctx(args=["t1", "w1"])
    assert reg.get_command("memory calibrate chain").run(ctx) == 0
    assert "Cadena de calibración" in ctx.out.getvalue()
    ctx = _ctx()
    assert reg.get_command("memory judge status").run(ctx) == 0
    assert "Judge Continuo" in ctx.out.getvalue()


# ─── components/sdd pure helpers ─────────────────────────────────────────────


def test_sdd_profile_names():
    assert sdd.validate_profile_name("") is not None
    assert sdd.validate_profile_name("default") is not None
    assert sdd.validate_profile_name("Bad_Name") is not None
    assert sdd.validate_profile_name("team-1") is None
    order = sdd.profile_phase_order()
    assert order[0] == "sdd-init" and len(order) == 10
    order.append("x")
    assert len(sdd.profile_phase_order()) == 10
    keys = sdd.profile_agent_keys("team")
    assert keys[0] == "sdd-orchestrator-team" and len(keys) == 11
    assert sdd.shared_prompt_phases() == sdd.profile_phase_order()
    assert sdd.shared_prompt_dir("/h") == "/h/.config/opencode/prompts/sdd"
    cmds = sdd.opencode_commands()
    assert len(cmds) > 5 and all(c.name and c.body for c in cmds)


def test_sdd_strategy_and_external(tmp_path):
    from dxrk.models import SDDProfileStrategyID

    assert sdd.resolve_profile_strategy("/h", SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE) == (
        SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE
    )
    assert sdd.has_external_profile_files("   ") is False
    assert sdd.has_external_profile_files(str(tmp_path)) is False
    prof = tmp_path / ".config" / "opencode" / "profiles"
    prof.mkdir(parents=True)
    (prof / "notes.txt").write_text("x", encoding="utf-8")
    assert sdd.has_external_profile_files(str(tmp_path)) is False
    (prof / "team.json").write_text("{}", encoding="utf-8")
    assert sdd.has_external_profile_files(str(tmp_path)) is True
    assert sdd.resolve_profile_strategy(str(tmp_path), None) == (  # type: ignore[arg-type]
        SDDProfileStrategyID.EXTERNAL_SINGLE_ACTIVE
    )
    assert sdd.resolve_profile_strategy(str(tmp_path / "none"), None) == (  # type: ignore[arg-type]
        SDDProfileStrategyID.GENERATED_MULTI
    )


def test_sdd_detect_profiles(tmp_path):
    missing = tmp_path / "no.json"
    assert sdd.detect_profiles(str(missing)) == []
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert sdd.detect_profiles(str(bad)) == []
    noagent = tmp_path / "na.json"
    noagent.write_text('{"agent": "x"}', encoding="utf-8")
    assert sdd.detect_profiles(str(noagent)) == []
    empty = tmp_path / "e.json"
    empty.write_text('{"agent": {}}', encoding="utf-8")
    assert sdd.detect_profiles(str(empty)) == []
    good = tmp_path / "g.json"
    good.write_text(
        json.dumps(
            {
                "agent": {
                    "sdd-orchestrator-team": {"model": "anthropic:claude-x"},
                    "sdd-init-team": {"model": "openai/gpt-x"},
                    "sdd-spec-team": {"model": "nonsense"},
                    "other": {"model": "a:b"},
                }
            }
        ),
        encoding="utf-8",
    )
    profiles = sdd.detect_profiles(str(good))
    assert len(profiles) == 1 and profiles[0].name == "team"
    assert profiles[0].orchestrator_model.provider_id == "anthropic"
    assert "sdd-init" in profiles[0].phase_assignments
    assert "sdd-spec" not in profiles[0].phase_assignments
    assert sdd.read_current_profiles(str(good))[0].name == "team"
    assert sdd.read_current_profiles(str(missing)) == []


def test_sdd_extract_model():
    from dxrk.models import ModelAssignment

    assert sdd._extract_model_from_agent("x") == ModelAssignment()
    assert sdd._extract_model_from_agent({}) == ModelAssignment()
    assert sdd._extract_model_from_agent({"model": "nonsense"}) == ModelAssignment()
    assert sdd._extract_model_from_agent({"model": "a:"}) == ModelAssignment()
    m = sdd._extract_model_from_agent({"model": "anthropic:claude"})
    assert (m.provider_id, m.model_id) == ("anthropic", "claude")
    m = sdd._extract_model_from_agent({"model": "openai/gpt"})
    assert (m.provider_id, m.model_id) == ("openai", "gpt")


def test_sdd_overlay_and_prompts():
    from dxrk.models import ModelAssignment, Profile

    with pytest.raises(ValueError):
        sdd.generate_profile_overlay(Profile(name="default"), "/h")
    with pytest.raises(ValueError):
        sdd.generate_profile_overlay(Profile(name=""), "/h")
    prof = Profile(
        name="team",
        orchestrator_model=ModelAssignment(provider_id="anthropic", model_id="c"),
        phase_assignments={"sdd-init": ModelAssignment(provider_id="openai", model_id="g")},
    )
    overlay = json.loads(sdd.generate_profile_overlay(prof, "/h").decode("utf-8"))
    assert "sdd-orchestrator-team" in overlay["agent"]
    assert "sdd-init-team" in overlay["agent"]
    prompt = sdd._build_profile_orchestrator_prompt(prof)
    assert "sdd-orchestrator-team" in prompt
    section = sdd._render_profile_model_assignments_section(prof)
    assert "orchestrator" in section and "anthropic/c" in section
    assert sdd._replace_phase_ref("use sdd-init now", "sdd-init", "sdd-init-team") == "use sdd-init-team now"
    assert sdd._replace_phase_ref("sdd-init-team ok", "sdd-init", "sdd-init-team") == "sdd-init-team ok"
    assert sdd._replace_phase_ref("same", "sdd-init", "sdd-init") == "same"


def test_sdd_remove_profile(tmp_path):
    settings = tmp_path / "s.json"
    with pytest.raises(ValueError):
        sdd.remove_profile_agents(str(settings), "default")
    assert sdd.remove_profile_agents(str(tmp_path / "missing.json"), "team") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert sdd.remove_profile_agents(str(bad), "team") is None
    noagent = tmp_path / "na.json"
    noagent.write_text('{"a": 1}', encoding="utf-8")
    assert sdd.remove_profile_agents(str(noagent), "team") is None
    settings.write_text(
        json.dumps({"agent": {"sdd-orchestrator-team": {}, "sdd-init-team": {}, "keep": {}}}), encoding="utf-8"
    )
    sdd.remove_profile_agents(str(settings), "team")
    remaining = json.loads(settings.read_text(encoding="utf-8"))["agent"]
    assert remaining == {"keep": {}}
    before = settings.read_text(encoding="utf-8")
    sdd.remove_profile_agents(str(settings), "other")
    assert settings.read_text(encoding="utf-8") == before


def test_sdd_read_helpers(tmp_path):
    assert sdd._read_opencode_agent_prompt("", "k") is None
    assert sdd._read_opencode_agent_prompt(str(tmp_path / "m.json"), "k") is None
    bad = tmp_path / "b.json"
    bad.write_text("{x", encoding="utf-8")
    assert sdd._read_opencode_agent_prompt(str(bad), "k") is None
    na = tmp_path / "na.json"
    na.write_text('{"agent": 1}', encoding="utf-8")
    assert sdd._read_opencode_agent_prompt(str(na), "k") is None
    good = tmp_path / "g.json"
    good.write_text(json.dumps({"agent": {"k": {"prompt": "hello"}, "n": {}, "s": {"prompt": 1}}}), encoding="utf-8")
    assert sdd._read_opencode_agent_prompt(str(good), "k") == "hello"
    assert sdd._read_opencode_agent_prompt(str(good), "n") is None
    assert sdd._read_opencode_agent_prompt(str(good), "s") is None
    assert sdd._read_opencode_root_model(str(tmp_path / "m.json")) is None
    assert sdd._read_opencode_root_model(str(bad)) is None
    assert sdd._read_opencode_root_model(str(na)) is None
    rm = tmp_path / "rm.json"
    rm.write_text('{"model": "a:b"}', encoding="utf-8")
    assert sdd._read_opencode_root_model(str(rm)) == "a:b"
    assert sdd._read_existing_agent_models(str(tmp_path / "m.json")) == {}
    assert sdd._read_existing_agent_models(str(bad)) == {}
    assert sdd._read_existing_agent_models(str(na)) == {}
    assert sdd._read_existing_agent_models(str(good)) == {"k": True, "n": True, "s": True}
    assert sdd._read_file_or_empty(str(tmp_path / "m.json")) == ""


def test_sdd_model_assignments_inject():
    from dxrk.models import ModelAssignment

    bad = b"{nope"
    assert sdd._inject_model_assignments(bad, {}, None, {}) == bad
    noagent = b'{"other": 1}'
    assert sdd._inject_model_assignments(noagent, {}, None, {}) == noagent
    overlay = json.dumps({"agent": {"sdd-apply": {}, "sdd-verify": {"model": "keep"}, "dxrk": {}}}).encode()
    out = json.loads(
        sdd._inject_model_assignments(
            overlay,
            {"sdd-orchestrator": ModelAssignment(provider_id="anthropic", model_id="c")},
            "root:model",
            {"dxrk": True},
        ).decode()
    )
    assert out["agent"]["sdd-apply"]["model"] == "root:model"
    assert out["agent"]["sdd-verify"]["model"] == "root:model"
    assert out["agent"]["dxrk"]["model"] == "anthropic/c"
    out2 = json.loads(
        sdd._inject_model_assignments(
            overlay,
            {},
            "root:model",
            {"sdd-verify": True},
        ).decode()
    )
    assert out2["agent"]["sdd-verify"]["model"] == "keep"
    assert out2["agent"]["sdd-apply"]["model"] == "root:model"


def test_sdd_claude_assignments():
    alias = sdd._resolve_claude_model_alias({}, "sdd-init")
    assert alias.value in ("opus", "sonnet", "haiku")
    alias = sdd._resolve_claude_model_alias({"sdd-apply": "opus"}, "sdd-apply")
    assert alias.value == "opus"
    alias = sdd._resolve_claude_model_alias({"sdd-apply": "bogus"}, "sdd-apply")
    assert alias.value == "sonnet"
    section = sdd._render_claude_model_assignments_section({"default": "sonnet"})
    assert "Model Assignments" in section
    content = "before <!-- dxrk:sdd-model-assignments -->old<!-- /dxrk:sdd-model-assignments --> after"
    out = sdd._inject_claude_model_assignments(content, {"sdd-apply": "opus", "x": "bogus"})
    assert "opus" in out and "after" in out
    with pytest.raises(ValueError):
        sdd._inject_claude_model_assignments("no markers", {})


def test_sdd_orchestrator_markers():
    assert sdd._has_sdd_orchestrator("## Agent Teams Orchestrator\nx") is True
    assert sdd._has_sdd_orchestrator("plain") is False
    assert sdd._strip_bare_orchestrator_section("plain") == "plain"
    stripped = sdd._strip_bare_orchestrator_section("intro\n## Agent Teams Orchestrator\nbody\n## Next\ntail\n")
    assert "body" not in stripped and "tail" in stripped
    assert sdd._has_legacy_bare_orchestrator("plain") is False
    assert sdd._has_legacy_bare_orchestrator("## Agent Teams Orchestrator\nx") is True
    marked = "a <!-- dxrk:sdd-orchestrator --> b"
    assert sdd._has_legacy_bare_orchestrator(marked) is False
    legacy = "# Agent Teams Lite — Orchestrator Instructions\nold\n<!-- dxrk:sdd-orchestrator -->\nnew\n"
    assert sdd._has_legacy_bare_orchestrator(legacy) is True
    out = sdd._strip_bare_orchestrator_for_file_prompt(legacy)
    assert "old" not in out and "new" in out
    assert sdd._strip_bare_orchestrator_for_file_prompt("plain") == "plain"
    assert sdd._strip_bare_orchestrator_for_file_prompt("## Agent Teams Orchestrator\nonly") == ""
    from dxrk.models import AgentID

    assert sdd._sdd_orchestrator_asset(AgentID.OPENCODE) == "opencode/sdd-orchestrator.md"
    assert sdd._sdd_orchestrator_asset(AgentID.CLAUDE_CODE) == "generic/sdd-orchestrator.md"
    from dxrk.models import SDDModeID

    assert sdd._overlay_asset_path(SDDModeID.MULTI).endswith("multi.json")
    assert sdd._overlay_asset_path(SDDModeID.SINGLE).endswith("single.json")


def test_sdd_find_root_and_merge(tmp_path):
    assert sdd._find_project_root("") is None
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert sdd._find_project_root(str(sub)) == str(tmp_path)
    assert sdd._find_project_root(str(tmp_path)) == str(tmp_path)
    strong = tmp_path / "strong"
    strong.mkdir()
    (strong / "pyproject.toml").write_text("", encoding="utf-8")
    assert sdd._find_project_root(str(strong)) == str(strong)
    target = tmp_path / "settings.json"
    wr, merged = sdd._merge_json_file(str(target), b'{"agent": {"a": 1}}')
    assert merged is not None and target.exists()
    wr2, _ = sdd._merge_json_file(str(target), b'{"agent": {"a": 1}}')
    assert wr2 is not None


def test_sdd_model_assignments_read(tmp_path):
    assert sdd.read_current_model_assignments(str(tmp_path / "m.json")) == {}
    bad = tmp_path / "b.json"
    bad.write_text("{x", encoding="utf-8")
    assert sdd.read_current_model_assignments(str(bad)) == {}
    na = tmp_path / "na.json"
    na.write_text('{"agent": 1}', encoding="utf-8")
    assert sdd.read_current_model_assignments(str(na)) == {}
    good = tmp_path / "g.json"
    good.write_text(
        json.dumps(
            {
                "agent": {
                    "sdd-apply": {"model": "a:b"},
                    "sdd-verify": {"model": "zzz"},
                    "sdd-spec": {"other": 1},
                    "sdd-design": {"model": "a:"},
                    "other": {"model": "a:b"},
                    "sdd-tasks": "x",
                }
            }
        ),
        encoding="utf-8",
    )
    got = sdd.read_current_model_assignments(str(good))
    assert set(got) == {"sdd-apply"}


def test_sdd_write_shared_prompts(tmp_path):
    assert sdd.write_shared_prompt_files(str(tmp_path)) is True
    assert (tmp_path / ".config" / "opencode" / "prompts" / "sdd" / "sdd-init.md").exists()
    assert sdd.write_shared_prompt_files(str(tmp_path)) is False
