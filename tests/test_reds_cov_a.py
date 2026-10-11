# SPDX-License-Identifier: MIT
"""Coverage for low-coverage red modules (part A): small commands, backup steps, reports."""

from __future__ import annotations

import io
import json
import os

from dxrk.cli import install_steps_backup as bk
from dxrk.cli import runtime_reports as reports
from dxrk.cli import runtime_run as runmod
from dxrk.cli.install_verify import _VerifyReport
from dxrk.commands import agents as agents_mod
from dxrk.commands import model as model_mod
from dxrk.commands import plugin as plugin_mod
from dxrk.commands import pr_comments as prc
from dxrk.commands import security_review as secrev
from dxrk.commands import stats as stats_mod
from dxrk.commands import tasks as tasks_mod
from dxrk.commands.gitutil import GitResult
from dxrk.commands.registry import CommandContext, Registry


def _ctx(**kw):
    kw.setdefault("out", io.StringIO())
    kw.setdefault("err", io.StringIO())
    return CommandContext(**kw)


# ─── stats ───────────────────────────────────────────────────────────────────


def test_stats_records_no_session():
    stats_mod.current_session = None
    stats_mod.record_message()
    stats_mod.record_tool_call()
    stats_mod.record_tokens(5)
    stats_mod.set_model("x")


def test_stats_records_with_session():
    stats_mod.current_session = stats_mod.SessionStats()
    stats_mod.record_message()
    stats_mod.record_tool_call()
    stats_mod.record_tokens(7)
    stats_mod.set_model("m")
    s = stats_mod.current_session
    assert (s.messages, s.tool_calls, s.tokens_used, s.model) == (1, 1, 7, "m")
    stats_mod.current_session = None


def test_stats_model_or_none_and_tokens():
    assert stats_mod.model_or_none("") == "(ninguno)"
    assert stats_mod.model_or_none("m") == "m"
    assert stats_mod.format_tokens(999) == "999"
    assert stats_mod.format_tokens(1500) == "1.5K"
    assert stats_mod.format_tokens(2_500_000) == "2.5M"


def test_stats_run_and_register():
    s = stats_mod.SessionStats(messages=2, tool_calls=3, tokens_used=1500, model="")
    ctx = _ctx()
    assert stats_mod.run_stats(ctx, s) == 0
    assert "Estadísticas" in ctx.err.getvalue()
    reg = Registry()
    stats_mod.register_stats_command(reg)
    cmd = reg.get_command("stats")
    assert cmd is not None
    out, err = io.StringIO(), io.StringIO()
    assert cmd.run(_ctx(out=out, err=err)) == 0


# ─── agents ────────────────────────────────────────────────────────────────


def test_agents_read_description(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    f = tmp_path / "a.md"
    f.write_text("# Title\n\nfirst real line is here\nsecond\n", encoding="utf-8")
    assert agents_mod._read_description(str(f)) == "first real line is here"
    assert agents_mod._read_description(str(tmp_path / "missing.md")) == ""
    empty = tmp_path / "e.md"
    empty.write_text("# Only\n\n", encoding="utf-8")
    assert agents_mod._read_description(str(empty)) == ""


def test_agents_scan_and_run(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    assert agents_mod._scan_agent_dirs(str(tmp_path)) == []
    home_agents = tmp_path / ".dxrk" / "agents"
    home_agents.mkdir(parents=True)
    (home_agents / "helper.md").write_text("# H\ndesc helper\n", encoding="utf-8")
    (home_agents / "notes.txt").write_text("nope\n", encoding="utf-8")
    sub = home_agents / "mybot.md"
    sub.mkdir()
    (sub / "agent.md").write_text("bot desc\n", encoding="utf-8")
    nodir = home_agents / "emptybot"
    nodir.mkdir()
    found = agents_mod._scan_agent_dirs(str(tmp_path))
    keys = [k for k, _, _ in found]
    assert "helper" in keys and "mybot" in keys
    # dedup: same key in project dir is ignored
    proj = tmp_path / ".dxrk" / "agents"
    assert proj == home_agents  # same wd collapses roots
    reg = Registry()
    agents_mod.register_agents_command(reg)
    ctx = _ctx(cwd=str(tmp_path))
    assert reg.get_command("agents").run(ctx) == 0
    assert "helper" in ctx.out.getvalue()
    ctx2 = _ctx(cwd=str(tmp_path / "nowhere"))
    monkeypatch.setattr(os.path, "expanduser", lambda p: "/definitely/not/here")
    assert reg.get_command("agents").run(ctx2) == 0
    assert "No se encontraron agentes" in ctx2.out.getvalue()


# ─── model ─────────────────────────────────────────────────────────────────


def test_model_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    reg = Registry()
    model_mod.register_model_command(reg)
    ctx = _ctx()
    assert reg.get_command("model list").run(ctx) == 0
    assert "Modelos disponibles" in ctx.out.getvalue() and "*" in ctx.out.getvalue()
    ctx = _ctx()
    assert reg.get_command("model current").run(ctx) == 0
    assert ctx.out.getvalue().strip() != ""
    ctx = _ctx(args=["openai", "gpt-x"])
    assert reg.get_command("model set").run(ctx) == 0
    assert "gpt-x" in ctx.out.getvalue()
    assert (tmp_path / ".dxrk" / "config.yaml").exists()
    ctx = _ctx(args=["nope", "m"])
    assert reg.get_command("model set").run(ctx) == 1
    assert "no encontrado" in ctx.err.getvalue()


# ─── plugin ────────────────────────────────────────────────────────────────


def test_plugin_full_cycle(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    assert plugin_mod.list_plugins() == []
    reg = Registry()
    plugin_mod.register_plugin_command(reg)
    ctx = _ctx()
    assert reg.get_command("plugin list").run(ctx) == 0
    assert "No se encontraron plugins" in ctx.out.getvalue()
    ctx = _ctx(args=["demo"])
    assert reg.get_command("plugin add").run(ctx) == 0
    assert "instalado" in ctx.out.getvalue()
    plugins = plugin_mod.list_plugins()
    assert len(plugins) == 1 and plugins[0][0] == "demo" and plugins[0][1] == "0.1.0"
    ctx = _ctx()
    assert reg.get_command("plugin list").run(ctx) == 0
    assert "demo" in ctx.out.getvalue()
    ctx = _ctx(args=["demo"])
    assert reg.get_command("plugin remove").run(ctx) == 0
    ctx = _ctx(args=["ghost"])
    assert reg.get_command("plugin remove").run(ctx) == 1
    assert "no encontrado" in ctx.err.getvalue()


def test_plugin_list_edge_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    root = tmp_path / ".dxrk" / "plugins"
    root.mkdir(parents=True)
    (root / "file.md").write_text("x", encoding="utf-8")
    nomanifest = root / "noman"
    nomanifest.mkdir()
    bad = root / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text("{nope", encoding="utf-8")
    found = {name: ver for name, ver, _ in plugin_mod.list_plugins()}
    assert found == {"noman": "", "bad": ""}


# ─── tasks ─────────────────────────────────────────────────────────────────


def test_tasks_cycle(monkeypatch):
    import dxrk.task as task_mod

    monkeypatch.setattr(tasks_mod, "_queue", task_mod.new_queue())
    reg = Registry()
    tasks_mod.register_tasks_command(reg)
    assert reg.get_command("tasks").run(_ctx()) == 1
    ctx = _ctx()
    assert reg.get_command("tasks list").run(ctx) == 0
    assert "No hay tareas" in ctx.out.getvalue()
    ctx = _ctx(args=["cosa"], flags={"type": "generic", "priority": "2"})
    assert reg.get_command("tasks add").run(ctx) == 0
    assert "creada" in ctx.out.getvalue()
    ctx = _ctx()
    assert reg.get_command("tasks list").run(ctx) == 0
    assert "generic" in ctx.out.getvalue()
    ctx = _ctx(args=["x"], flags={"type": "nope"})
    assert reg.get_command("tasks add").run(ctx) == 1
    ctx = _ctx(args=["x"], flags={"priority": "zz"})
    assert reg.get_command("tasks add").run(ctx) == 1
    tid = tasks_mod._queue.list()[0].id
    ctx = _ctx(args=[str(tid)])
    assert reg.get_command("tasks delete").run(ctx) == 0
    ctx = _ctx(args=["missing-id"])
    assert reg.get_command("tasks delete").run(ctx) == 1


# ─── pr_comments ───────────────────────────────────────────────────────────


def test_pr_current_number_branches(monkeypatch):
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(1, "", "boom"))
    assert prc._current_pr_number(".") is None
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(0, "{bad", ""))
    assert prc._current_pr_number(".") is None
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(0, '{"other": 1}', ""))
    assert prc._current_pr_number(".") is None
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(0, '{"number": 7}', ""))
    assert prc._current_pr_number(".") == "7"


def test_pr_comments_error_paths(monkeypatch):
    reg = Registry()
    prc.register_pr_comments_command(reg)
    monkeypatch.setattr(prc, "git_dir", lambda wd: GitResult(1, "", ""))
    assert reg.get_command("pr comments").run(_ctx()) == 1
    assert reg.get_command("pr resolve").run(_ctx()) == 1
    monkeypatch.setattr(prc, "git_dir", lambda wd: GitResult(0, "", ""))
    monkeypatch.setattr(prc, "git_current_branch", lambda wd: None)
    ctx = _ctx()
    assert reg.get_command("pr comments").run(ctx) == 1
    assert "PR" in ctx.err.getvalue()
    monkeypatch.setattr(prc, "git_current_branch", lambda wd: "feat")
    monkeypatch.setattr(prc, "_current_pr_number", lambda wd: None)
    assert reg.get_command("pr comments").run(_ctx()) == 1
    assert reg.get_command("pr resolve").run(_ctx()) == 1


def test_pr_comments_full_flow(monkeypatch):
    reg = Registry()
    prc.register_pr_comments_command(reg)
    monkeypatch.setattr(prc, "git_dir", lambda wd: GitResult(0, "", ""))
    monkeypatch.setattr(prc, "git_current_branch", lambda wd: "feat")
    monkeypatch.setattr(prc, "_current_pr_number", lambda wd: "12")

    def fake_gh(wd, *args):
        if args[:2] == ("pr", "view"):
            return GitResult(0, "", "")
        if "issues/12/comments" in args[-1]:
            return GitResult(0, json.dumps([{"user": {"login": "ana"}, "body": "hola"}]), "")
        return GitResult(0, json.dumps([{"user": {"login": "bob"}, "body": "nit", "path": "a.py", "line": 3}]), "")

    monkeypatch.setattr(prc, "run_gh", fake_gh)
    ctx = _ctx()
    assert reg.get_command("pr comments").run(ctx) == 0
    assert "ana" in ctx.out.getvalue() and "bob" in ctx.out.getvalue()
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(0, "[]", ""))
    ctx = _ctx()
    assert reg.get_command("pr comments").run(ctx) == 0
    assert "No se encontraron comentarios" in ctx.out.getvalue()


def test_pr_resolve_flow(monkeypatch):
    reg = Registry()
    prc.register_pr_comments_command(reg)
    monkeypatch.setattr(prc, "git_dir", lambda wd: GitResult(0, "", ""))
    monkeypatch.setattr(prc, "_current_pr_number", lambda wd: "5")
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(1, "", "down"))
    ctx = _ctx()
    assert reg.get_command("pr resolve").run(ctx) == 0
    assert "No hay hilos" in ctx.out.getvalue()
    monkeypatch.setattr(prc, "run_gh", lambda *a: GitResult(0, "{bad", ""))
    assert reg.get_command("pr resolve").run(ctx) == 0
    monkeypatch.setattr(
        prc, "run_gh", lambda *a: GitResult(0, json.dumps([{"id": "T1"}, {"id": "T2", "in_reply_to_id": "T1"}]), "")
    )
    real = prc.run_gh
    calls = []

    def both(wd, *args):
        if args[:1] == ("graphql",):
            calls.append(args)
            return GitResult(0, "{}", "")
        return real(wd, *args)

    monkeypatch.setattr(prc, "run_gh", both)
    ctx = _ctx()
    assert reg.get_command("pr resolve").run(ctx) == 0
    assert "se resolvieron 1 hilo" in ctx.out.getvalue()


# ─── security_review ───────────────────────────────────────────────────────


def test_security_review_paths(monkeypatch):
    reg = Registry()
    secrev.register_security_review_command(reg)
    run = reg.get_command("security review").run
    monkeypatch.setattr(secrev, "git_dir", lambda wd: GitResult(1, "", ""))
    ctx = _ctx()
    assert run(ctx) == 1
    assert "no es un repositorio" in ctx.err.getvalue()
    monkeypatch.setattr(secrev, "git_dir", lambda wd: GitResult(0, ".git", ""))
    monkeypatch.setattr(secrev, "git_current_branch", lambda wd: None)
    monkeypatch.setattr(secrev, "git_default_branch", lambda wd: "main")
    monkeypatch.setattr(secrev, "git_diff", lambda wd, since: GitResult(0, "+++ b/a.py\n+clean line\n", ""))
    ctx = _ctx()
    assert run(ctx) == 0
    assert "No se detectaron problemas" in ctx.out.getvalue()
    assert "(detached)" in ctx.out.getvalue()
    monkeypatch.setattr(secrev, "git_current_branch", lambda wd: "feat")
    monkeypatch.setattr(secrev, "git_diff", lambda wd, since: GitResult(1, "", "offline"))
    ctx = _ctx()
    assert run(ctx) == 1
    diff = (
        "+++ b/a.py\n"
        '+api_key = "AKIAIOSFODNN7EXAMPLEKEY12"\n'
        '+password = "supersecret"\n'
        "+BEGIN RSA PRIVATE KEY\n"
        "+aws_access_key_id = x\n"
        "+token bearer ABCDEFGHIJKLMNOPQRSTUVWX\n"
        "+eval (exec (x))\n"
        '+exec ("rm")\n'
        '+secret = "shhh-secret-value-123456"\n'
    )
    monkeypatch.setattr(secrev, "git_diff", lambda wd, since: GitResult(0, diff, ""))
    ctx = _ctx()
    assert run(ctx) == 0
    assert "Posibles problemas" in ctx.out.getvalue()


# ─── install_steps_backup ──────────────────────────────────────────────────


def test_backup_prepare_and_rollback(tmp_path):
    snap = tmp_path / "snap"
    target = tmp_path / "cfg.md"
    target.write_text("v1", encoding="utf-8")
    state: dict = {}
    step = bk.PrepareBackupStep("bak", str(snap), [str(target)], state, source="s", description="d", app_version="1")
    assert step.id() == "bak"
    assert step.run() is None
    assert len(state["manifest"]["entries"]) == 1
    target.write_text("v2", encoding="utf-8")
    assert step.rollback() is None
    assert target.read_text(encoding="utf-8") == "v1"


def test_backup_empty_and_missing(tmp_path):
    state: dict = {}
    step = bk.PrepareBackupStep("e", str(tmp_path / "s"), [], state)
    assert step.run() is None and step.rollback() is None
    assert bk.RollbackRestoreStep("r", {}).run() is None
    assert bk.RollbackRestoreStep("r", {}).rollback() is None
    step2 = bk.PrepareBackupStep("m", str(tmp_path / "s2"), [str(tmp_path / "nope")], state)
    assert step2.run() is None
    assert state["manifest"]["entries"] == []


def test_backup_rollback_restore_step(tmp_path):
    snap = tmp_path / "snap"
    snap.mkdir()
    rel = "home/user/cfg.md"
    (snap / "home" / "user").mkdir(parents=True)
    (snap / rel).write_text("orig", encoding="utf-8")
    dest = tmp_path / "restored.md"
    dest.write_text("changed", encoding="utf-8")
    state = {"manifest": {"_backup_root": str(snap / "manifest.json"), "entries": [{"source": str(dest), "dest": rel}]}}
    step = bk.RollbackRestoreStep("rr", state)
    assert step.id() == "rr"
    assert step.rollback() is None
    assert dest.read_text(encoding="utf-8") == "orig"


# ─── runtime_reports ───────────────────────────────────────────────────────


def test_reports_joins_and_platform():
    from dxrk.models import AgentID, ComponentID

    assert reports._join_agent_ids([]) == "ninguno"
    assert reports._join_agent_ids([AgentID.OPENCODE]) == "opencode"
    assert reports._join_component_ids([]) == "ninguno"
    assert reports._join_component_ids([ComponentID.SDD]) == "sdd"
    assert "desconocido" in reports._format_platform_decision(None)


def test_render_dry_run():
    from dxrk.cli.runtime_install import InstallResult
    from dxrk.models import AgentID, ComponentID
    from dxrk.planner import PlatformDecision, ResolvedPlan

    res = InstallResult(
        resolved=ResolvedPlan(agents=[AgentID.OPENCODE], ordered_components=[ComponentID.SDD]),
        review=None,
        plan=None,
    )
    text = reports.render_dry_run(res)
    assert "simulación" in text and "opencode" in text
    res.review = type("R", (), {"platform_decision": PlatformDecision(os="linux", supported=True)})()
    res.plan = type("P", (), {"prepare": [1], "apply": [1, 2]})()
    text = reports.render_dry_run(res)
    assert "compatible" in text and "Pasos de aplicación: 2" in text


def test_render_sync_report():
    from dxrk.cli.runtime_sync import SyncResult
    from dxrk.models import AgentID

    r = SyncResult(no_op=True, agents=[])
    assert "no se necesitan acciones" in reports.render_sync_report(r)
    r = SyncResult(no_op=True, agents=[AgentID.OPENCODE])
    assert "ya están actualizados" in reports.render_sync_report(r)
    r = SyncResult(dry_run=True, agents=[AgentID.OPENCODE])
    assert "simulación" in reports.render_sync_report(r)
    r.plan = type("P", (), {"prepare": [1], "apply": []})()
    assert "Pasos de preparación: 1" in reports.render_sync_report(r)
    r = SyncResult(agents=[AgentID.OPENCODE], files_changed=3)
    assert "3 archivos" in reports.render_sync_report(r)
    r.verify = _VerifyReport(checks=[], ready=False)
    assert "Verificación" in reports.render_sync_report(r)


def test_render_uninstall_report():
    from types import SimpleNamespace

    from dxrk.models import AgentID

    r = SimpleNamespace(
        Manifest={"entries": [1]},
        BackupPath="/tmp/b",
        ChangedFiles=["a"],
        RemovedFiles=[],
        RemovedDirectories=[],
        AgentsRemovedFromState=[AgentID.OPENCODE],
        ManualActions=["revisar x"],
    )
    text = reports.render_uninstall_report(r)
    assert "Desinstalación" in text and "Ruta de la copia" in text and "revisar x" in text


# ─── runtime_run pure helpers ──────────────────────────────────────────────


def test_run_go_bin_dir_and_path(tmp_path, monkeypatch):
    monkeypatch.setenv("GOBIN", "/gobin")
    assert runmod._go_install_bin_dir() == "/gobin"
    monkeypatch.delenv("GOBIN")
    monkeypatch.setenv("GOPATH", "/gopath")
    assert runmod._go_install_bin_dir() == os.path.join("/gopath", "bin")
    monkeypatch.delenv("GOPATH")
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
    assert runmod._go_install_bin_dir() == os.path.join(str(tmp_path), "go", "bin")
    monkeypatch.setenv("PATH", f"/x{os.pathsep}/y")
    assert runmod._is_in_path("/y") is True
    assert runmod._is_in_path("/nope") is False


def test_run_memory_guidance():
    assert "fish_user_paths" in runmod._memory_path_guidance("/usr/bin/fish")
    assert ".zshrc" in runmod._memory_path_guidance("/bin/zsh")
    assert ".bashrc" in runmod._memory_path_guidance("/bin/bash")
    assert "PATH" in runmod._memory_path_guidance("/bin/sh")


def test_run_post_install_notes(monkeypatch):
    from dxrk.models import ComponentID
    from dxrk.planner import ResolvedPlan
    from dxrk.system import PlatformProfile

    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("SHELL", "/bin/bash")
    rep = _VerifyReport(ready=True, final_note="")
    resolved = ResolvedPlan(ordered_components=[ComponentID.DXRK_GUARDIAN])
    out = runmod._with_post_install_notes(rep, resolved, PlatformProfile(package_manager="brew"))
    assert "DXRK_GUARDIAN" in out.final_note
    out2 = runmod._with_post_install_notes(out, resolved, PlatformProfile(package_manager="brew"))
    assert out2.final_note.count("ya está instalado globalmente") == 1
    rep2 = _VerifyReport(ready=True, final_note="")
    resolved2 = ResolvedPlan(ordered_components=[ComponentID.DXRK_MEMORY])
    out3 = runmod._with_post_install_notes(rep2, resolved2, PlatformProfile(package_manager="apt"))
    assert "PATH" in out3.final_note
