# SPDX-License-Identifier: MIT
"""Coverage 100% lote final 4 — uninstall (Service/componentes/helpers) + update (ejecutor/estrategias)."""

from __future__ import annotations

import io
import json
import os
import subprocess
import tarfile
import time
from types import SimpleNamespace
from unittest import mock

from dxrk.components import uninstall as U
from dxrk.models import AgentID, ComponentID, DxrkMemoryUninstallScope, MCPStrategy


class FlexAdapter:
    def __init__(self, home: str = "", **kw) -> None:
        self.agent = kw.get("agent", AgentID.OPENCODE)
        self.supports_system_prompt = kw.get("supports_system_prompt", True)
        self.supports_output_styles = kw.get("supports_output_styles", False)
        self.supports_skills = kw.get("supports_skills", True)
        self.supports_slash_commands = kw.get("supports_slash_commands", True)
        self.mcp_strategy = kw.get("mcp_strategy", MCPStrategy.MERGE_INTO_SETTINGS)
        self._home = home
        self._settings = kw.get("settings_path", os.path.join(home, "settings.json"))
        self._skills = kw.get("skills_dir", os.path.join(home, "skills"))
        self._commands = kw.get("commands_dir", os.path.join(home, "commands"))
        self._prompt = kw.get("prompt_file", os.path.join(home, "AGENTS.md"))
        self._mcp = kw.get("mcp_path", os.path.join(home, "mcp.json"))
        self._perms = kw.get("permissions_file", "")
        self._legacy = kw.get("legacy", "raise")
        self._outdir = kw.get("output_dir", os.path.join(home, "styles"))

    def system_prompt_file(self, home_dir: str = "") -> str:
        return self._prompt or os.path.join(home_dir, "AGENTS.md")

    def output_style_dir(self, home_dir: str = "") -> str:
        return self._outdir

    def settings_path(self, home_dir: str = "") -> str | None:
        return self._settings

    def skills_dir(self, home_dir: str = "") -> str:
        return self._skills

    def commands_dir(self, home_dir: str = "") -> str:
        return self._commands

    def mcp_config_path(self, home_dir: str = "", server_name: str = "") -> str:
        return self._mcp or os.path.join(home_dir, "mcp.json")

    def permissions_file(self, home_dir: str = "") -> str:
        if self._perms == "raise":
            raise AttributeError("no perms")
        return self._perms

    def legacy_system_prompt_files(self, home_dir: str = "") -> list[str]:
        if self._legacy == "raise":
            raise AttributeError("no legacy")
        return list(self._legacy)


def _svc(home: str, **kw) -> U.Service:
    s = U.Service(home_dir=home, **kw)
    return s


class TestBuildPlanMergeExpand:
    def test_merge_rewrite_same_path(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        fa = FlexAdapter(home)
        monkeypatch.setattr(U.Service, "_get_adapter", lambda self, aid: fa)
        monkeypatch.setattr(
            U.Service,
            "_component_operations",
            lambda self, ad, cid: (
                [U._rewrite_json_file(os.path.join(home, "s.json"), ["a"])],
                [os.path.join(home, "s.json")],
            ),
        )
        svc = _svc(home)
        (tmp_path / "s.json").write_text('{"a": 1, "b": 2}')
        targets, ops = svc._build_plan([AgentID.OPENCODE, AgentID.CURSOR], [ComponentID.THEME])
        assert len(ops) == 1
        assert str(tmp_path / "s.json") in targets

    def test_build_plan_overwrites_non_rewrite(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        fa = FlexAdapter(home)
        monkeypatch.setattr(U.Service, "_get_adapter", lambda self, aid: fa)
        p = os.path.join(home, "f.txt")
        (tmp_path / "f.txt").write_text("x")
        monkeypatch.setattr(U.Service, "_component_operations", lambda self, ad, cid: ([U._remove_file(p)], [p]))
        svc = _svc(home)
        targets, ops = svc._build_plan([AgentID.OPENCODE], [ComponentID.THEME])
        assert ops and p in targets

    def test_build_plan_gga_and_state_targets(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        fa = FlexAdapter(home)
        monkeypatch.setattr(U.Service, "_get_adapter", lambda self, aid: fa)
        monkeypatch.setattr(U.Service, "_component_operations", lambda self, ad, cid: ([], []))
        svc = _svc(home)
        targets, ops = svc._build_plan([AgentID.OPENCODE], [ComponentID.THEME])
        assert any("state.json" in t for t in targets)
        assert any("DXRK_GUARDIAN" in t or "gentle" in t.lower() or "config" in t for t in targets)


class TestExecutePlanBranches:
    def test_backup_copy_and_rewrite_changed(self, tmp_path):
        home = str(tmp_path)
        f = tmp_path / "s.json"
        f.write_text('{"a": 1, "b": 2}')
        op = U._rewrite_json_file(str(f), ["a"])
        svc = _svc(home, app_version="9.9")
        res = svc._execute_plan(([str(f)], [op]), [])
        assert str(f) in res.ChangedFiles
        assert res.Manifest["source"] == "uninstall"
        assert res.BackupPath.startswith(svc.backup_root)

    def test_error_raises(self, tmp_path):
        svc = _svc(str(tmp_path))
        bad = U.Operation(U.OpType.REWRITE_FILE, "/x", lambda p: (False, False, "boom"))
        try:
            svc._execute_plan(([], [bad]), [])
            raised = False
        except RuntimeError as e:
            raised = "boom" in str(e)
        assert raised is True

    def test_remove_if_empty_with_note(self, tmp_path):
        d = tmp_path / "nonempty"
        d.mkdir()
        (d / "keep.txt").write_text("x")
        op = U._remove_dir_if_empty(str(d))
        svc = _svc(str(tmp_path))
        res = svc._execute_plan(([], [op]), [])
        assert any(str(d) in m for m in res.ManualActions)

    def test_remove_if_empty_removed_dir(self, tmp_path):
        d = tmp_path / "empty2"
        d.mkdir()
        op = U._remove_dir_if_empty(str(d))
        svc = _svc(str(tmp_path))
        res = svc._execute_plan(([], [op]), [])
        assert str(d) in res.RemovedDirectories

    def test_unchanged_op_skipped(self, tmp_path):
        f = tmp_path / "keep.md"
        f.write_text("plain")
        op = U._rewrite_markdown_file(str(f), lambda c: (c, False))
        svc = _svc(str(tmp_path))
        res = svc._execute_plan(([], [op]), [])
        assert res.ChangedFiles == [] and res.RemovedFiles == []

    def test_remove_file_and_tree_recorded(self, tmp_path):
        f = tmp_path / "del.txt"
        f.write_text("x")
        d = tmp_path / "treedel"
        d.mkdir()
        (d / "a").write_text("x")
        svc = _svc(str(tmp_path))
        res = svc._execute_plan(([], [U._remove_file(str(f)), U._remove_tree(str(d))]), [])
        assert str(f) in res.RemovedFiles
        assert str(d) in res.RemovedDirectories


class TestComponentPersona:
    def test_full_persona_opencode(self, tmp_path):
        home = str(tmp_path)
        prompt = tmp_path / "AGENTS.md"
        prompt.write_text("hello")
        settings = tmp_path / "settings.json"
        settings.write_text('{"outputStyle": "x", "agent": {"dxrk": 1}}')
        legacy = tmp_path / "legacy.md"
        legacy.write_text("<!-- dxrk:persona --> Gentle AI Persona Senior Architect")
        fa = FlexAdapter(
            home,
            agent=AgentID.OPENCODE,
            supports_system_prompt=True,
            supports_output_styles=True,
            settings_path=str(settings),
            prompt_file=str(prompt),
            legacy=[str(legacy)],
        )
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.PERSONA)
        assert ops and targets
        assert any("dxrk.md" in o.path for o in ops)
        res = svc._execute_plan((targets, ops), [])
        assert isinstance(res, U.Result)

    def test_persona_minimal_no_settings(self, tmp_path):
        home = str(tmp_path)
        fa = FlexAdapter(
            home, supports_system_prompt=False, supports_output_styles=False, settings_path=None, legacy="raise"
        )
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.PERSONA)
        assert ops == [] and targets == []

    def test_persona_other_agent_settings(self, tmp_path):
        home = str(tmp_path)
        settings = tmp_path / "s.json"
        settings.write_text('{"outputStyle": 1}')
        fa = FlexAdapter(
            home,
            agent=AgentID.CURSOR,
            supports_system_prompt=False,
            supports_output_styles=False,
            settings_path=str(settings),
            legacy=[],
        )
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.PERSONA)
        assert len(ops) == 1


class TestComponentContext7:
    def test_separate_files(self, tmp_path):
        home = str(tmp_path)
        fa = FlexAdapter(home, mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES)
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.CONTEXT7)
        # NOTE: _context7_targets compares mcp_strategy against plain strings,
        # so real enum adapters yield no backup targets (only operations).
        assert len(ops) == 2 and targets == []

    def test_merge_opencode_and_other(self, tmp_path):
        home = str(tmp_path)
        fa1 = FlexAdapter(home, mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, agent=AgentID.OPENCODE)
        fa2 = FlexAdapter(home, mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, agent=AgentID.CURSOR)
        svc = _svc(home)
        o1, _ = svc._component_operations(fa1, ComponentID.CONTEXT7)
        o2, _ = svc._component_operations(fa2, ComponentID.CONTEXT7)
        assert len(o1) == 1 and len(o2) == 1

    def test_mcp_config_vscode_and_other(self, tmp_path):
        home = str(tmp_path)
        fa1 = FlexAdapter(home, mcp_strategy=MCPStrategy.MCP_CONFIG_FILE, agent=AgentID.VSCODE_COPILOT)
        fa2 = FlexAdapter(home, mcp_strategy=MCPStrategy.MCP_CONFIG_FILE, agent=AgentID.CURSOR)
        svc = _svc(home)
        o1, _ = svc._component_operations(fa1, ComponentID.CONTEXT7)
        o2, _ = svc._component_operations(fa2, ComponentID.CONTEXT7)
        assert len(o1) == 1 and len(o2) == 1

    def test_context7_string_strategy_targets(self, tmp_path):
        home = str(tmp_path)

        def _str_adapter(strategy: str):
            return SimpleNamespace(
                mcp_strategy=strategy,
                mcp_config_path=lambda h, s="": os.path.join(h, "mcp.json"),
            )

        assert U._context7_targets(_str_adapter("separate-files"), home) != []
        assert U._context7_targets(_str_adapter("mcp-config-file"), home) != []
        fa3 = FlexAdapter(home, mcp_strategy=MCPStrategy.TOML_FILE)
        assert U._context7_targets(fa3, home) == []
        assert U._context7_operations(fa3, home) == []


class TestComponentMemory:
    def test_project_scope_with_workspace(self, tmp_path):
        home = str(tmp_path)
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / ".memory").mkdir()
        svc = _svc(home, workspace_dir=str(ws))
        svc.set_DXRK_MEMORY_uninstall_scope(DxrkMemoryUninstallScope.PROJECT)
        fa = FlexAdapter(home)
        ops, targets = svc._component_operations(fa, ComponentID.DXRK_MEMORY)
        assert len(ops) == 1 and targets == [os.path.join(str(ws), ".memory")]

    def test_project_scope_empty_workspace(self, tmp_path):
        svc = _svc(str(tmp_path), workspace_dir="   ")
        svc.set_DXRK_MEMORY_uninstall_scope(DxrkMemoryUninstallScope.PROJECT)
        ops, targets = svc._component_operations(FlexAdapter(str(tmp_path)), ComponentID.DXRK_MEMORY)
        assert ops == [] and targets == []

    def test_global_separate_and_prompt(self, tmp_path):
        home = str(tmp_path)
        prompt = tmp_path / "AGENTS.md"
        prompt.write_text("<!-- dxrk:memory-protocol -->\nx\n<!-- /dxrk:memory-protocol -->\nrest")
        fa = FlexAdapter(
            home, mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES, supports_system_prompt=True, prompt_file=str(prompt)
        )
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.DXRK_MEMORY)
        assert len(ops) == 3

    def test_global_merge_opencode_and_other(self, tmp_path):
        home = str(tmp_path)
        svc = _svc(home)
        fa1 = FlexAdapter(
            home, mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, agent=AgentID.OPENCODE, supports_system_prompt=False
        )
        fa2 = FlexAdapter(
            home, mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS, agent=AgentID.CURSOR, supports_system_prompt=False
        )
        assert len(svc._component_operations(fa1, ComponentID.DXRK_MEMORY)[0]) == 1
        assert len(svc._component_operations(fa2, ComponentID.DXRK_MEMORY)[0]) == 1

    def test_global_mcp_config_vscode_and_other(self, tmp_path):
        home = str(tmp_path)
        svc = _svc(home)
        fa1 = FlexAdapter(
            home, mcp_strategy=MCPStrategy.MCP_CONFIG_FILE, agent=AgentID.VSCODE_COPILOT, supports_system_prompt=False
        )
        fa2 = FlexAdapter(
            home, mcp_strategy=MCPStrategy.MCP_CONFIG_FILE, agent=AgentID.CURSOR, supports_system_prompt=False
        )
        assert len(svc._component_operations(fa1, ComponentID.DXRK_MEMORY)[0]) == 1
        assert len(svc._component_operations(fa2, ComponentID.DXRK_MEMORY)[0]) == 1

    def test_global_toml(self, tmp_path):
        home = str(tmp_path)
        cfg = tmp_path / "codex.toml"
        cfg.write_text('[mcp_servers.memory]\nurl = "x"\n')
        fa = FlexAdapter(home, mcp_strategy=MCPStrategy.TOML_FILE, mcp_path=str(cfg), supports_system_prompt=False)
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.DXRK_MEMORY)
        assert len(ops) == 4 and len(targets) == 3
        res = svc._execute_plan((targets, ops), [])
        assert isinstance(res, U.Result)

    def test_memory_targets_toml_and_merge(self, tmp_path):
        home = str(tmp_path)
        fa_toml = FlexAdapter(home, mcp_strategy=MCPStrategy.TOML_FILE)
        assert len(U._memory_targets(fa_toml, home)) == 3
        fa_merge = FlexAdapter(home, mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS)
        assert len(U._memory_targets(fa_merge, home)) == 1
        fa_sep = FlexAdapter(home, mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES)
        assert len(U._memory_targets(fa_sep, home)) == 1
        fa_cfg = FlexAdapter(home, mcp_strategy=MCPStrategy.MCP_CONFIG_FILE)
        assert len(U._memory_targets(fa_cfg, home)) == 1


class TestComponentPermissions:
    def test_no_settings(self, tmp_path):
        svc = _svc(str(tmp_path))
        fa = FlexAdapter(str(tmp_path), settings_path=None, permissions_file="raise")
        ops, targets = svc._component_operations(fa, ComponentID.PERMISSIONS)
        assert ops == []

    def test_each_agent_branch(self, tmp_path):
        home = str(tmp_path)
        svc = _svc(home)
        for agent in (
            AgentID.CLAUDE_CODE,
            AgentID.OPENCODE,
            AgentID.GEMINI_CLI,
            AgentID.VSCODE_COPILOT,
        ):
            sp = tmp_path / f"s-{agent}.json"
            sp.write_text(
                '{"permissions": 1, "permission": 1, "general": {"defaultApprovalMode": 1}, "chat": {"tools": {"autoApprove": 1}}}'
            )
            fa = FlexAdapter(home, agent=agent, settings_path=str(sp), permissions_file="raise")
            ops, _ = svc._component_operations(fa, ComponentID.PERMISSIONS)
            assert len(ops) == 1
        sp0 = tmp_path / "s-cursor.json"
        sp0.write_text('{"a": 1}')
        ops0, _ = svc._component_operations(
            FlexAdapter(home, agent=AgentID.CURSOR, settings_path=str(sp0), permissions_file="raise"),
            ComponentID.PERMISSIONS,
        )
        assert ops0 == []

    def test_cursor_perms_file(self, tmp_path):
        home = str(tmp_path)
        sp = tmp_path / "s.json"
        sp.write_text('{"a": 1}')
        pf = tmp_path / "perms.json"
        pf.write_text('{"terminalAllowlist": [], "mcpAllowlist": []}')
        fa = FlexAdapter(home, agent=AgentID.CURSOR, settings_path=str(sp), permissions_file=str(pf))
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.PERMISSIONS)
        assert len(ops) == 1

    def test_kiro_perms_file_match_and_nomatch(self, tmp_path):
        from dxrk.components import permissions as P

        home = str(tmp_path)
        sp = tmp_path / "s.json"
        sp.write_text('{"a": 1}')
        pf = tmp_path / "kiro.json"
        pf.write_text(P._KIRO_PERMISSIONS_YAML)
        fa = FlexAdapter(home, agent=AgentID.KIRO_IDE, settings_path=str(sp), permissions_file=str(pf))
        svc = _svc(home)
        ops, _ = svc._component_operations(fa, ComponentID.PERMISSIONS)
        assert len(ops) == 1
        res = svc._execute_plan(([str(pf)], [ops[0]]), [])
        assert str(pf) in res.RemovedFiles
        pf.write_text("different content")
        ok, changed, err = U._remove_file_if_matches(str(pf), P._KIRO_PERMISSIONS_YAML.encode()).apply(str(pf))
        assert (ok, changed) == (False, False) and err is None

    def test_perms_other_agent_ignored(self, tmp_path):
        home = str(tmp_path)
        sp = tmp_path / "s.json"
        sp.write_text('{"a": 1}')
        fa = FlexAdapter(home, agent=AgentID.CURSOR, settings_path=str(sp), permissions_file="")
        svc = _svc(home)
        ops, _ = svc._component_operations(fa, ComponentID.PERMISSIONS)
        assert len(ops) == 0


class TestComponentThemeSkills:
    def test_theme_with_and_without_settings(self, tmp_path):
        home = str(tmp_path)
        sp = tmp_path / "s.json"
        sp.write_text('{"theme": "dark", "keep": 1}')
        svc = _svc(home)
        ops, _ = svc._component_operations(FlexAdapter(home, settings_path=str(sp)), ComponentID.THEME)
        assert len(ops) == 1
        ops2, _ = svc._component_operations(FlexAdapter(home, settings_path=None), ComponentID.THEME)
        assert ops2 == []

    def test_skills_not_supported_and_no_dir(self, tmp_path):
        home = str(tmp_path)
        svc = _svc(home)
        ops, _ = svc._component_operations(FlexAdapter(home, supports_skills=False), ComponentID.SKILLS)
        assert ops == []
        ops2, _ = svc._component_operations(FlexAdapter(home, skills_dir=""), ComponentID.SKILLS)
        assert ops2 == []

    def test_skills_removes_managed_dirs(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "branch-pr").mkdir()
        (skill_dir / "branch-pr" / "SKILL.md").write_text("x")
        (skill_dir / "sdd-apply").mkdir()
        (skill_dir / "_shared").mkdir()
        (skill_dir / "afile.txt").write_text("x")
        svc = _svc(home)
        fa = FlexAdapter(home, skills_dir=str(skill_dir))
        ops, targets = svc._component_operations(fa, ComponentID.SKILLS)
        assert any("branch-pr" in t for t in targets)
        assert not any("sdd-apply" in t for t in targets)
        assert svc._execute_plan((targets, ops), []).RemovedDirectories != []
        assert not (skill_dir / "branch-pr").exists()

    def test_skills_root_missing(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        svc = _svc(home)
        ops, _ = svc._component_operations(FlexAdapter(home, skills_dir=str(skill_dir)), ComponentID.SKILLS)
        assert ops == []


class TestComponentSDD:
    def test_sdd_full_opencode_scoped(self, tmp_path):
        home = str(tmp_path)
        prompt = tmp_path / "AGENTS.md"
        prompt.write_text("<!-- dxrk:sdd-orchestrator -->\nx\n<!-- /dxrk:sdd-orchestrator -->\nkeep")
        sp = tmp_path / "settings.json"
        sp.write_text('{"agent": {"sdd-orchestrator": {}, "sdd-init": {}}}')
        legacy = tmp_path / "leg.md"
        legacy.write_text("plain user file")
        cmds = tmp_path / "commands"
        cmds.mkdir()
        skills = tmp_path / "skills"
        (skills / "_shared").mkdir(parents=True)
        (skills / "sdd-apply").mkdir(parents=True)
        fa = FlexAdapter(
            home,
            agent=AgentID.OPENCODE,
            supports_system_prompt=True,
            prompt_file=str(prompt),
            legacy=[str(legacy)],
            settings_path=str(sp),
            commands_dir=str(cmds),
            skills_dir=str(skills),
        )
        svc = _svc(home)
        svc.set_profile_names_to_remove(["p1"])
        ops, targets = svc._component_operations(fa, ComponentID.SDD)
        assert len(ops) > 5
        res = svc._execute_plan((targets, ops), [])
        assert isinstance(res, U.Result)

    def test_sdd_unscoped_profiles_detected(self, tmp_path):
        home = str(tmp_path)
        sp = tmp_path / "settings.json"
        sp.write_text('{"agent": {"sdd-orchestrator-x": {}, "sdd-init-x": {}}}')
        fa = FlexAdapter(
            home,
            agent=AgentID.OPENCODE,
            supports_system_prompt=False,
            legacy="raise",
            supports_slash_commands=False,
            settings_path=str(sp),
            supports_skills=False,
        )
        svc = _svc(home)
        ops, _ = svc._component_operations(fa, ComponentID.SDD)
        assert any(o.type_id == U.OpType.REWRITE_FILE for o in ops)

    def test_sdd_non_opencode_settings(self, tmp_path):
        home = str(tmp_path)
        sp = tmp_path / "s.json"
        sp.write_text('{"a": 1}')
        fa = FlexAdapter(
            home,
            agent=AgentID.CURSOR,
            supports_system_prompt=False,
            legacy=[],
            supports_slash_commands=False,
            settings_path=str(sp),
            supports_skills=False,
        )
        svc = _svc(home)
        ops, _ = svc._component_operations(fa, ComponentID.SDD)
        assert ops == []

    def test_sdd_no_settings_no_skills(self, tmp_path):
        home = str(tmp_path)
        fa = FlexAdapter(
            home,
            supports_system_prompt=False,
            legacy="raise",
            supports_slash_commands=False,
            settings_path=None,
            supports_skills=False,
        )
        svc = _svc(home)
        ops, targets = svc._component_operations(fa, ComponentID.SDD)
        assert ops == [] and targets == []

    def test_sdd_gga_component(self, tmp_path):
        home = str(tmp_path)
        from dxrk.components import gga as G

        cfg = G.config_path(home)
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, "w") as f:
            f.write("x")
        svc = _svc(home)
        ops, targets = svc._component_operations(FlexAdapter(home), ComponentID.DXRK_GUARDIAN)
        assert len(ops) == 3
        res = svc._execute_plan((targets, ops), [])
        assert cfg in res.RemovedFiles


class TestRewriteRemoveErrors:
    def test_markdown_oserror_and_missing(self, tmp_path, monkeypatch):
        f = tmp_path / "m.md"
        f.write_text("hi")
        op = U._rewrite_markdown_file(str(f), lambda c: (c + "x", True))
        monkeypatch.setattr(U, "_read_managed_file", lambda p: (_ for _ in ()).throw(OSError("ro")))
        assert op.apply(str(f))[2] == "ro"
        monkeypatch.setattr(U, "_read_managed_file", lambda p: (_ for _ in ()).throw(FileNotFoundError()))
        assert op.apply(str(f)) == (False, False, None)

    def test_markdown_crlf_and_empty_removal(self, tmp_path):
        f = tmp_path / "c.md"
        f.write_text("<!-- dxrk:persona -->\r\nx\r\n<!-- /dxrk:persona -->\r\n", newline="")
        op = U._rewrite_markdown_file(str(f), lambda c: U._remove_markdown_sections(c, "persona"))
        ok, removed, err = op.apply(str(f))
        assert ok is True and err is None
        f2 = tmp_path / "e.md"
        f2.write_text("only<!-- dxrk:persona -->\nx\n<!-- /dxrk:persona -->")
        op2 = U._rewrite_markdown_file(str(f2), lambda c: ("   \n", True))
        ok2, rem2, _ = op2.apply(str(f2))
        assert ok2 is True and rem2 is True and not f2.exists()

    def test_json_oserror_missing_empty_and_crlf(self, tmp_path, monkeypatch):
        assert U._rewrite_json_file(str(tmp_path / "nope"), ["a"]).apply(str(tmp_path / "nope")) == (False, False, None)
        f = tmp_path / "j.json"
        f.write_text('{"a": 1}')
        op = U._rewrite_json_file(str(f), ["a"])
        monkeypatch.setattr(U, "_read_managed_file", lambda p: (_ for _ in ()).throw(OSError("ro")))
        assert op.apply(str(f))[2] == "ro"
        monkeypatch.undo()
        f2 = tmp_path / "only.json"
        f2.write_text('{"a": 1}')
        ok, rem, _ = U._rewrite_json_file(str(f2), ["a"]).apply(str(f2))
        assert (ok, rem) == (True, True) and not f2.exists()
        f3 = tmp_path / "crlf.json"
        f3.write_bytes(b'{"a": 1, "b": 2}\r\n')
        ok3, _, _ = U._rewrite_json_file(str(f3), ["a"]).apply(str(f3))
        assert ok3 is True and json.loads(f3.read_bytes()) == {"b": 2}

    def test_toml_oserror_missing_empty_crlf(self, tmp_path, monkeypatch):
        assert U._rewrite_toml_file(str(tmp_path / "nope"), lambda c: (c, True)).apply("x") == (False, False, None)
        f = tmp_path / "t.toml"
        f.write_text("[a]\nx = 1\n")
        op = U._rewrite_toml_file(str(f), lambda c: (c + "y", True))
        monkeypatch.setattr(U, "_read_managed_file", lambda p: (_ for _ in ()).throw(OSError("ro")))
        assert op.apply(str(f))[2] == "ro"
        monkeypatch.undo()
        f2 = tmp_path / "e.toml"
        f2.write_text("k = 1\r\n")
        ok, rem, _ = U._rewrite_toml_file(str(f2), lambda c: ("  \n", True)).apply(str(f2))
        assert (ok, rem) == (True, True)
        f3 = tmp_path / "c.toml"
        f3.write_text("k = 1\r\n")
        U._rewrite_toml_file(str(f3), lambda c: ("k = 1\nk2 = 2\n", True)).apply(str(f3))
        assert "k2 = 2" in f3.read_text()

    def test_remove_if_matches_branches(self, tmp_path, monkeypatch):
        f = tmp_path / "m.bin"
        f.write_text("exact")
        op = U._remove_file_if_matches(str(f), b"exact")
        assert op.apply(str(f)) == (True, True, None)
        assert U._remove_file_if_matches(str(tmp_path / "no"), b"x").apply("y") == (False, False, None)
        f2 = tmp_path / "m2.bin"
        f2.write_text("x")
        with mock.patch("builtins.open", side_effect=OSError("ro")):
            assert U._remove_file_if_matches(str(f2), b"x").apply(str(f2))[2] == "ro"
        f3 = tmp_path / "m3.bin"
        f3.write_text("n")
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_file_if_matches(str(f3), b"n").apply(str(f3))[2] == "deny"

    def test_remove_file_oserror_and_tree_oserror(self, tmp_path, monkeypatch):
        f = tmp_path / "r.txt"
        f.write_text("x")
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_file(str(f)).apply(str(f))[2] == "deny"
        d = tmp_path / "td"
        d.mkdir()
        assert U._remove_tree(str(tmp_path / "missing-dir-xyz")).apply("x") == (False, False, None)
        import shutil as _sh

        monkeypatch.setattr(_sh, "rmtree", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_tree(str(d)).apply(str(d))[2] == "deny"

    def test_legacy_oserror_unmanaged_remove_error(self, tmp_path, monkeypatch):
        f = tmp_path / "leg.md"
        f.write_text("plain")
        assert U._remove_managed_legacy_file(str(f)).apply(str(f)) == (False, False, None)
        assert U._remove_managed_legacy_file(str(tmp_path / "no")).apply("x") == (False, False, None)
        with mock.patch("builtins.open", side_effect=OSError("ro")):
            assert U._remove_managed_legacy_file(str(f)).apply(str(f))[2] == "ro"
        f2 = tmp_path / "leg2.md"
        f2.write_text("<!-- dxrk:persona --> Gentle AI Persona")
        monkeypatch.setattr(os, "remove", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_managed_legacy_file(str(f2)).apply(str(f2))[2] == "deny"

    def test_dir_if_empty_empty_path_and_oserrors(self, tmp_path, monkeypatch):
        assert U._remove_dir_if_empty("").apply("") == (False, False, None)
        assert U._remove_dir_if_empty_recursive(str(tmp_path / "nope-xyz")) is False
        monkeypatch.setattr(os, "listdir", lambda p: (_ for _ in ()).throw(OSError("ro")))
        assert U._remove_dir_if_empty_recursive(str(tmp_path)) is False
        d = tmp_path / "full"
        d.mkdir()
        (d / "k").write_text("x")
        assert U._remove_dir_if_empty_recursive(str(d)) is False
        d2 = tmp_path / "e2"
        d2.mkdir()
        monkeypatch.setattr(os, "rmdir", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_dir_if_empty_recursive(str(d2)) is False

    def test_read_symlink_and_expand_and_merge(self, tmp_path, monkeypatch):
        target = tmp_path / "t.txt"
        target.write_text("x")
        link = tmp_path / "l.txt"
        link.symlink_to(target)
        try:
            U._read_managed_file(str(link))
            raised = False
        except PermissionError:
            raised = True
        assert raised is True
        assert U._expand_backup_target("") == []
        assert U._expand_backup_target(str(tmp_path / "nope")) == [str(tmp_path / "nope")]
        a = U._rewrite_markdown_file("p", lambda c: (c, True))
        b = U._rewrite_markdown_file("p", lambda c: (c, True))
        with mock.patch.object(a, "apply", return_value=(True, False, "e1")):
            assert U._merge_rewrite_ops(a, b).apply("p")[2] == "e1"
        with mock.patch.object(a, "apply", return_value=(True, True, None)):
            assert U._merge_rewrite_ops(a, b).apply("p") == (True, True, None)

    def test_manual_action_oserror_and_empty(self, tmp_path, monkeypatch):
        assert U._manual_action_for_non_empty_directory("") is None
        monkeypatch.setattr(os, "listdir", lambda p: (_ for _ in ()).throw(OSError("x")))
        assert U._manual_action_for_non_empty_directory(str(tmp_path)) is None


class TestStateHelpers:
    def test_agents_to_remove_full_and_partial(self):
        full = [
            U.ComponentID.PERSONA,
            U.ComponentID.DXRK_MEMORY,
            U.ComponentID.CONTEXT7,
            U.ComponentID.PERMISSIONS,
            U.ComponentID.SDD,
            U.ComponentID.SKILLS,
            U.ComponentID.THEME,
        ]
        out = U._state_agents_to_remove([AgentID.OPENCODE], full)
        assert out == [AgentID.OPENCODE]
        assert U._state_agents_to_remove([AgentID.OPENCODE], [ComponentID.THEME]) == []

    def test_update_state_flows(self, tmp_path):
        from dxrk.state import InstallState
        from dxrk.state import write as swrite

        home = str(tmp_path)
        assert U._update_state_after_uninstall(home, [AgentID.OPENCODE]) == []
        swrite(home, InstallState(installed_agents=["opencode", "cursor"]))
        removed = U._update_state_after_uninstall(home, [AgentID.OPENCODE])
        assert removed == [AgentID.OPENCODE]
        removed2 = U._update_state_after_uninstall(home, [AgentID.OPENCODE])
        assert removed2 == []

    def test_partial_default_components(self, tmp_path, monkeypatch):
        svc = _svc(str(tmp_path))
        seen = {}

        def fake_build(self_svc, agents, comps):
            seen["n"] = len(comps)
            return ([], [])

        monkeypatch.setattr(U.Service, "_build_plan", fake_build)
        monkeypatch.setattr(U.Service, "_execute_plan", lambda s, p, r: U.Result())
        svc.partial_uninstall([AgentID.OPENCODE], [])
        assert seen["n"] == len(U._ALL_MANAGED_COMPONENTS)


class TestCleanersEdge:
    def test_remove_markdown_multi(self):
        c = "a\n<!-- dxrk:x -->\n1\n<!-- /dxrk:x -->\nb\n<!-- dxrk:y -->\n2\n<!-- /dxrk:y -->\nc"
        out, changed = U._remove_markdown_sections(c, "x", "y")
        assert changed is True and "1" not in out and "c" in out

    def test_preamble_managed_and_variants(self):
        managed = "## Personality\nSenior Architect\n## Rules\n<!-- dxrk:persona -->\nbody\n"
        out, ch = U._remove_managed_persona_preamble(managed)
        assert ch is True and out == "<!-- dxrk:persona -->\nbody\n"
        named = "name: Gentle AI Persona\ndescription: Teaching-oriented persona\n<!-- dxrk:z -->\nrest"
        out2, ch2 = U._remove_managed_persona_preamble(named)
        assert ch2 is True
        assert U._remove_managed_persona_preamble("   \n<!-- dxrk:z -->\nbody") == ("   \n<!-- dxrk:z -->\nbody", False)
        assert U._remove_managed_persona_preamble("## Personality\nSenior Architect\n## Rules") == (
            "## Personality\nSenior Architect\n## Rules",
            False,
        )

    def test_looks_like_name_desc(self):
        assert (
            U._looks_like_managed_persona_prefix("name: Gentle AI Persona\ndescription: Teaching-oriented persona")
            is True
        )

    def test_json_paths_edge(self):
        assert U._remove_json_paths(b"not json {{", [["a"]]) == (b"not json {{", False)
        out, ch = U._remove_json_paths(b'{"a": 1}\r\n', [["a"]])
        assert ch is True and b"\r\n" in out
        assert U._remove_json_paths(b'{"a": 1}', [["z"]]) == (b'{"a": 1}', False)
        assert U._delete_json_path({"a": 1}, []) is False
        assert U._delete_json_path({"a": [1]}, ["a", "b"]) is False
        assert U._json_is_empty_object(b"nope {{") is False
        assert U._unmarshal_json_object(b"   ") == {}
        assert U._unmarshal_json_object(b'{"a": 1, // c\n}') == {"a": 1}
        assert U._unmarshal_json_object(b"{{{{") is None

    def test_codex_toml_empty_result(self):
        out, ch = U._clean_codex_toml('[mcp_servers.memory]\nurl = "x"\nmodel_instructions_file = "a"\n')
        assert ch is True and out == ""
        content = "[other]\nmodel_instructions_file = 1\n[mcp_servers.memory]\nurl = 1\n[after]\nk = 1\n"
        out2, _ = U._clean_codex_toml(content)
        assert "[mcp_servers.memory]" not in out2 and "[after]" in out2

    def test_toml_table_crlf_and_keys_variants(self):
        assert U._remove_toml_table("[t]\r\na = 1\r\n[b]\r\nkeep = 2", "t") == "[b]\nkeep = 2"
        assert U._remove_toml_table("[t]\na = 1", "t") == ""
        content = "key1 = 1\nkey1extra = 2\nkey2 = 3\n[sec]\nkey1 = 9\n"
        out = U._remove_top_level_toml_keys(content, "key1")
        assert "key1extra" in out and "[sec]" in out

    def test_strip_comments_strings_escapes(self):
        raw = b'{"a": "// not comment", "b": "/* no */", "c": "esc \\" // x"} // real\n{"d": 1} /* block */ {"e": 2}'
        out = U._strip_json_comments(raw)
        assert b"not comment" in out and b"real" not in out and b"block" not in out
        raw2 = b'{"a": "a\\"b"} /* unterminated'
        assert b"a" in U._strip_json_comments(raw2)
        raw3 = b'{"a": 1} // trailing-no-newline'
        assert b"trailing" not in U._strip_json_comments(raw3)

    def test_strip_commas_strings_escapes(self):
        assert U._strip_trailing_commas(b'{"a": "x,}", "b": 1,}') == b'{"a": "x,}", "b": 1}'
        assert U._strip_trailing_commas(b'{"a": "e\\" ,"}') == b'{"a": "e\\" ,"}'
        assert U._strip_trailing_commas(b"[1, 2, ]") == b"[1, 2 ]"
        assert U._strip_trailing_commas(b'{"a": 1, "b": 2}') == b'{"a": 1, "b": 2}'


class _Upd:
    pass


def _profile(os_name: str = "linux", pm: str = "apt"):
    from dxrk.system import PlatformProfile

    p = PlatformProfile()
    p.os = os_name
    p.package_manager = pm
    return p


def _uresult(name: str = "t", status=None, **kw):
    import dxrk.update as UP

    r = UP.UpdateResult(tool=UP.ToolInfo(name=name))
    if status is not None:
        r.status = status
    for k, v in kw.items():
        setattr(r, k, v)
    return r


class TestGithubTokenBranches:
    def test_gh_nonzero_returns_empty(self):
        import dxrk.update as UP

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(UP, "_look_path", return_value="/usr/bin/gh"),
            mock.patch.object(UP.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="")),
        ):
            assert UP._resolve_github_token() == ""

    def test_gh_empty_token_returns_empty(self):
        import dxrk.update as UP

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(UP, "_look_path", return_value="/usr/bin/gh"),
            mock.patch.object(UP.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="  \n")),
        ):
            assert UP._resolve_github_token() == ""

    def test_gh_timeout_returns_empty(self):
        import dxrk.update as UP

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(UP, "_look_path", return_value="/usr/bin/gh"),
            mock.patch.object(UP.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 5)),
        ):
            assert UP._resolve_github_token() == ""

    def test_gh_missing_binary_returns_empty(self):
        import dxrk.update as UP

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(UP.subprocess, "run", side_effect=FileNotFoundError()),
            mock.patch.object(UP, "_look_path", return_value="/usr/bin/gh"),
        ):
            assert UP._resolve_github_token() == ""


class TestRenderBranches:
    def test_update_available_without_hint(self):
        import dxrk.update as UP

        r = _uresult(
            "toolx", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2", update_hint=""
        )
        out = UP.render_cli([r])
        assert "actualización(es) disponible(s)" in out and "toolx" in out

    def test_skipped_plain_omitido(self):
        import dxrk.update as UP

        rep = UP.UpgradeReport(
            dry_run=False, results=[UP.ToolUpgradeResult(tool_name="a", status=UP.ToolUpgradeStatus.SKIPPED)]
        )
        assert "omitido" in UP.render_upgrade_report(rep)

    def test_dry_run_only_succeeded(self):
        import dxrk.update as UP

        rep = UP.UpgradeReport(
            dry_run=True,
            results=[
                UP.ToolUpgradeResult(
                    tool_name="a", status=UP.ToolUpgradeStatus.SUCCEEDED, old_version="1", new_version="2"
                )
            ],
        )
        out = UP.render_upgrade_report(rep)
        assert "No se encontraron actualizaciones aplicables" in out


class TestSpinnerBranches:
    def test_run_and_finish_true(self):
        import dxrk.update as UP

        buf = io.StringIO()
        sp = UP.CLISpinner(buf, "trabajando")
        time.sleep(0.25)
        sp.finish(True)
        assert "trabajando" in buf.getvalue()

    def test_finish_false(self):
        import dxrk.update as UP

        buf = io.StringIO()
        sp = UP.CLISpinner(buf, "otro")
        time.sleep(0.15)
        sp.finish(False)
        assert "otro" in buf.getvalue()

    def test_finish_skipped(self):
        import dxrk.update as UP

        buf = io.StringIO()
        sp = UP.CLISpinner(buf, "salto")
        time.sleep(0.15)
        sp.finish_skipped()
        assert "salto" in buf.getvalue()


class TestEnumerateAndBackupPaths:
    def test_symlink_to_file_kept(self, tmp_path):
        import dxrk.update as UP

        real = tmp_path / "real.txt"
        real.write_text("x")
        link = tmp_path / "link.txt"
        link.symlink_to(real)
        files = UP.enumerate_files_in_dir(str(tmp_path), exclude_names=set())
        assert str(real) in files and str(link) in files

    def test_config_paths_file_and_oserror(self, tmp_path, monkeypatch):
        import dxrk.update as UP

        d = tmp_path / "cfg"
        d.mkdir()
        (d / "a.json").write_text("{}")
        cfg = SimpleNamespace(path=str(d))
        monkeypatch.setattr(
            "dxrk.system.scan_configs", lambda home: [cfg, SimpleNamespace(path=str(tmp_path / "nofile"))]
        )
        paths = UP.config_paths_for_backup(str(tmp_path))
        assert any("a.json" in p for p in paths)
        monkeypatch.setattr(UP, "enumerate_files_in_dir", lambda p: (_ for _ in ()).throw(OSError("ro")))
        assert UP.config_paths_for_backup(str(tmp_path)) == []


class TestExecuteOptionsBranches:
    def test_execute_with_progress_sets_diagnostics(self, monkeypatch):
        import dxrk.update as UP

        seen = {}

        def fake(results, profile, home, dry, options):
            seen["p"] = options.progress
            seen["b"] = options.backup_diagnostics
            return UP.UpgradeReport(dry_run=dry)

        monkeypatch.setattr(UP, "execute_with_options", fake)
        buf = io.StringIO()
        UP.execute([], _profile(), "/tmp", dry_run=True, progress=buf)
        assert seen["p"] is buf and seen["b"] is buf

    def test_early_return_up_to_date(self):
        import dxrk.update as UP

        r = _uresult("a", UP.UpdateStatus.UP_TO_DATE)
        rep = UP.execute_with_options([r], _profile(), "/tmp", False, UP.ExecuteOptions())
        assert rep.results == [] and rep.dry_run is False

    def test_backup_success_with_spinner(self, tmp_path, monkeypatch):
        import dxrk.update as UP

        home = str(tmp_path)
        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        manifest = SimpleNamespace(id="bid-1", source=None, description="", created_by_version="")

        class Snap:
            def create(self, snapshot_dir, paths):
                return manifest

        import dxrk.backup as B

        monkeypatch.setattr(B, "Snapshotter", Snap)
        monkeypatch.setattr(UP, "config_paths_for_backup", lambda h: [])
        monkeypatch.setattr(B, "write_manifest", lambda p, m: None)
        monkeypatch.setattr(
            UP,
            "_execute_one",
            lambda r, p, d: UP.ToolUpgradeResult(
                tool_name=r.tool.name, status=UP.ToolUpgradeStatus.SUCCEEDED, old_version="1", new_version="2"
            ),
        )
        buf = io.StringIO()
        rep = UP.execute_with_options([r], _profile(), home, False, UP.ExecuteOptions(progress=buf))
        assert rep.backup_id == "bid-1" and len(rep.results) == 1

    def test_backup_failure_warning(self, tmp_path, monkeypatch):
        import dxrk.update as UP

        home = str(tmp_path)
        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")

        class Snap:
            def create(self, snapshot_dir, paths):
                raise OSError("sin espacio")

        import dxrk.backup as B

        monkeypatch.setattr(B, "Snapshotter", Snap)
        monkeypatch.setattr(UP, "config_paths_for_backup", lambda h: [])
        monkeypatch.setattr(
            UP,
            "_execute_one",
            lambda r, p, d: UP.ToolUpgradeResult(tool_name=r.tool.name, status=UP.ToolUpgradeStatus.SKIPPED),
        )
        rep = UP.execute_with_options([r], _profile(), home, False, UP.ExecuteOptions())
        assert "sin espacio" in rep.backup_warning

    def test_dev_and_unknown_loops(self, monkeypatch):
        import dxrk.update as UP

        dev = _uresult("devt", UP.UpdateStatus.DEV_BUILD, installed_version="dev", latest_version="2.0.0")
        dev.tool.repo = "repo"
        unk = _uresult("unkt", UP.UpdateStatus.VERSION_UNKNOWN, installed_version="", latest_version="1")
        unk.tool.detect_cmd = ["unkt", "--version"]
        rep = UP.execute_with_options([dev, unk], _profile(), "/tmp", False, UP.ExecuteOptions())
        assert len(rep.results) == 2
        assert all(x.status == UP.ToolUpgradeStatus.SKIPPED for x in rep.results)

    def test_executable_spinner_finishes(self, tmp_path, monkeypatch):
        import dxrk.update as UP

        home = str(tmp_path)
        monkeypatch.setattr(UP, "config_paths_for_backup", lambda h: [])
        import dxrk.backup as B

        class Snap:
            def create(self, snapshot_dir, paths):
                m = SimpleNamespace(id="x", source=None, description="", created_by_version="")
                return m

        monkeypatch.setattr(B, "Snapshotter", Snap)
        monkeypatch.setattr(B, "write_manifest", lambda p, m: None)
        results = [
            _uresult("a", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2"),
            _uresult("b", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2"),
            _uresult("c", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2"),
        ]
        statuses = [UP.ToolUpgradeStatus.SUCCEEDED, UP.ToolUpgradeStatus.SKIPPED, UP.ToolUpgradeStatus.FAILED]
        calls = {"n": 0}

        def fake_one(r, p, d):
            s = statuses[calls["n"]]
            calls["n"] += 1
            return UP.ToolUpgradeResult(
                tool_name=r.tool.name, status=s, err="boom" if s == UP.ToolUpgradeStatus.FAILED else ""
            )

        monkeypatch.setattr(UP, "_execute_one", fake_one)
        buf = io.StringIO()
        rep = UP.execute_with_options(results, _profile(), home, False, UP.ExecuteOptions(progress=buf))
        assert [x.status for x in rep.results] == statuses


class TestRunStrategyBranches:
    def _res(self, name, method, **kw):
        import dxrk.update as UP

        r = UP.UpdateResult(tool=UP.ToolInfo(name=name, install_method=method, owner="o", repo="r"))
        r.installed_version = kw.get("installed_version", "1")
        r.latest_version = kw.get("latest_version", "2")
        return r

    def test_brew(self, monkeypatch):
        import dxrk.update as UP

        seen = {}
        monkeypatch.setattr(UP, "_brew_upgrade", lambda n: seen.setdefault("name", n))
        UP._run_strategy(self._res("t", UP.InstallMethod.BINARY), _profile(pm="brew"))
        assert seen == {"name": "t"}

    def test_go_install(self, monkeypatch):
        import dxrk.update as UP

        seen = {}
        monkeypatch.setattr(UP, "_go_install_upgrade", lambda t, v: seen.setdefault("v", (t.name, v)))
        r = self._res("t", UP.InstallMethod.GO_INSTALL)
        UP._run_strategy(r, _profile())
        assert seen == {"v": ("t", "2")}

    def test_binary(self, monkeypatch):
        import dxrk.update as UP

        seen = {}
        monkeypatch.setattr(UP, "_binary_upgrade", lambda r, p: seen.setdefault("name", r.tool.name))
        UP._run_strategy(self._res("t", UP.InstallMethod.BINARY), _profile())
        assert seen == {"name": "t"}

    def test_script_gga_and_other(self, monkeypatch):
        import dxrk.update as UP

        seen = []
        monkeypatch.setattr(UP, "_gga_script_upgrade", lambda r: seen.append(("gga", r.tool.name)))
        monkeypatch.setattr(UP, "_script_upgrade", lambda r, p: seen.append(("sh", r.tool.name)))
        UP._run_strategy(self._res("gga", UP.InstallMethod.SCRIPT), _profile())
        UP._run_strategy(self._res("other", UP.InstallMethod.SCRIPT), _profile())
        assert seen == [("gga", "gga"), ("sh", "other")]

    def test_opencode_plugin(self, monkeypatch):
        import dxrk.update as UP

        seen = {}
        monkeypatch.setattr(UP, "_opencode_plugin_upgrade", lambda r: seen.setdefault("name", r.tool.name))
        UP._run_strategy(self._res("t", UP.InstallMethod.OPENCODE_PLUGIN), _profile())
        assert seen == {"name": "t"}

    def test_unknown_method_fallback(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        class Weird:
            value = "weird"

        monkeypatch.setattr(UP, "effective_method", lambda t, p: Weird())
        with pytest.raises(UP.ManualFallbackError):
            UP._run_strategy(self._res("t", UP.InstallMethod.BINARY), _profile())

    def test_brew_failure(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        monkeypatch.setattr(UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="nope"))
        with pytest.raises(RuntimeError, match="nope"):
            UP._brew_upgrade("toolx")

    def test_brew_success(self, monkeypatch):
        import dxrk.update as UP

        calls = []
        monkeypatch.setattr(
            UP.subprocess,
            "run",
            lambda *a, **k: calls.append(a[0]) or SimpleNamespace(returncode=0, stderr="", stdout=""),
        )
        UP._brew_upgrade("toolx")
        assert ["brew", "upgrade", "toolx"] in calls

    def test_go_empty_path(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        with pytest.raises(RuntimeError, match="GoImportPath"):
            UP._go_install_upgrade(UP.ToolInfo(name="t"), "1.2.3")

    def test_go_success_and_fail(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        monkeypatch.setattr(UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""))
        UP._go_install_upgrade(UP.ToolInfo(name="t", go_import_path="example.com/m"), "1.2.3")
        monkeypatch.setattr(
            UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad", stdout="")
        )
        with pytest.raises(RuntimeError, match="bad"):
            UP._go_install_upgrade(UP.ToolInfo(name="t", go_import_path="example.com/m"), "1.2.3")
        assert UP._install_script_url("o", "r").endswith("install.sh")


class TestBinaryDownloadBranches:
    def test_binary_windows_fallback(self):
        import pytest

        import dxrk.update as UP

        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2", update_hint="")
        r.tool.repo = "repo"
        with pytest.raises(UP.ManualFallbackError):
            UP._binary_upgrade(r, _profile(os_name="windows"))

    def test_binary_dxrk_dispatch(self, monkeypatch):
        import dxrk.update as UP

        called = {}
        monkeypatch.setattr(UP, "_dxrk_upgrade", lambda: called.setdefault("y", True))
        r = UP.UpdateResult(tool=UP.ToolInfo(name="dxrk"))
        UP._binary_upgrade(r, _profile())
        assert called == {"y": True}

    def test_download_windows_runtime(self):
        import pytest

        import dxrk.update as UP

        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2", update_hint="")
        r.tool.repo = "repo"
        with pytest.raises(RuntimeError, match="Windows"):
            UP._download(r, _profile(os_name="windows"))

    def test_download_no_binary(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        monkeypatch.setattr(UP, "_look_path", lambda n: None)
        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        with pytest.raises(RuntimeError, match="no se encontró"):
            UP._download(r, _profile())

    def test_download_failure_cleans_tmp(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        binary = tmp_path / "mybin"
        binary.write_text("old")
        monkeypatch.setattr(UP, "_look_path", lambda n: str(binary))
        monkeypatch.setattr(UP, "_resolve_asset_url", lambda *a: "http://x/y.tar.gz")
        monkeypatch.setattr(UP, "_download_binary", lambda *a: (_ for _ in ()).throw(RuntimeError("net down")))
        r = _uresult("mybin", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        with pytest.raises(RuntimeError, match="net down"):
            UP._download(r, _profile())
        assert not os.path.exists(str(binary) + ".new")

    def test_download_success_replaces(self, tmp_path, monkeypatch):
        import dxrk.update as UP

        binary = tmp_path / "mybin"
        binary.write_text("old")

        def fake_dl(url, name, out):
            with open(out, "w") as f:
                f.write("new")

        monkeypatch.setattr(UP, "_look_path", lambda n: str(binary))
        monkeypatch.setattr(UP, "_resolve_asset_url", lambda *a: "http://x/y.tar.gz")
        monkeypatch.setattr(UP, "_download_binary", fake_dl)
        r = _uresult("mybin", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        UP._download(r, _profile())
        assert binary.read_text() == "new"
        UP._download_and_replace(r, _profile())
        assert binary.read_text() == "new"

    def test_download_binary_and_extract(self, tmp_path):
        import pytest

        import dxrk.update as UP

        arc = tmp_path / "a.tar.gz"
        with tarfile.open(str(arc), "w:gz") as tar:
            info = tarfile.TarInfo("somedir/mybin")
            data = b"binary-bytes"
            info.size = len(data)
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
            dinfo = tarfile.TarInfo("somedir")
            dinfo.type = tarfile.DIRTYPE
            tar.addfile(dinfo)
        out = tmp_path / "out" / "mybin"
        with open(str(arc), "rb") as fh:
            UP._extract_binary_from_tar_gz(fh, "mybin", str(out))
        assert out.read_bytes() == b"binary-bytes"
        with open(str(arc), "rb") as fh2:
            with pytest.raises(RuntimeError, match="no se encontró"):
                UP._extract_binary_from_tar_gz(fh2, "other", str(tmp_path / "o2"))
        with mock.patch.object(UP.urllib.request, "urlopen") as mu:
            mu.return_value.__enter__.return_value = open(str(arc), "rb")
            UP._download_binary("http://x", "mybin", str(tmp_path / "o3"))
            assert (tmp_path / "o3").exists()
        assert UP._atomic_replace(str(out), str(out)) is None

    def test_script_windows_size_fail_and_fail_run(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2", update_hint="")
        r.tool.owner = "o"
        r.tool.repo = "r"
        with pytest.raises(UP.ManualFallbackError):
            UP._script_upgrade(r, _profile(os_name="windows"))

        class Resp:
            def __init__(self, body):
                self._b = body

            def read(self, n=None):
                return self._b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        big = b"x" * (UP._max_script_size + 5)
        with mock.patch.object(UP.urllib.request, "urlopen", return_value=Resp(big)):
            with pytest.raises(RuntimeError, match="supera el límite"):
                UP._script_upgrade(r, _profile())
        with mock.patch.object(UP.urllib.request, "urlopen", return_value=Resp(b"echo hi")):
            monkeypatch.setattr(
                UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout="")
            )
            UP._script_upgrade(r, _profile())
            monkeypatch.setattr(
                UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad", stdout="")
            )
            with pytest.raises(RuntimeError, match="install.sh falló"):
                UP._script_upgrade(r, _profile())
        assert UP._install_script_url("o", "r").endswith("/main/install.sh")


class TestGgaOpencodeBranches:
    def test_gga_delegates(self, monkeypatch):
        import sys

        import dxrk.update as UP

        seen = {}
        monkeypatch.setattr(UP, "_gga_script_upgrade_for_os", lambda r, o: seen.setdefault("o", o))
        r = _uresult("gga", UP.UpdateStatus.UPDATE_AVAILABLE)
        UP._gga_script_upgrade(r)
        assert seen == {"o": sys.platform}

    def test_gga_win32(self):
        import pytest

        import dxrk.update as UP

        r = _uresult("gga", UP.UpdateStatus.UPDATE_AVAILABLE, update_hint="")
        r.tool.owner = "o"
        r.tool.repo = "r"
        with pytest.raises(UP.ManualFallbackError):
            UP._gga_script_upgrade_for_os(r, "win32")

    def test_gga_clone_and_install(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        r = _uresult("gga", UP.UpdateStatus.UPDATE_AVAILABLE)
        r.tool.owner = "o"
        r.tool.repo = "r"
        calls = {"n": 0}

        def fake_run(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=0, stderr="", stdout="")

        monkeypatch.setattr(UP.subprocess, "run", fake_run)
        UP._gga_script_upgrade_for_os(r, "linux")
        assert calls["n"] == 2

        def fake_fail(*a, **k):
            calls["n"] += 1
            if "clone" in a[0]:
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=3, stderr="fail", stdout="")

        monkeypatch.setattr(UP.subprocess, "run", fake_fail)
        with pytest.raises(RuntimeError, match="install.sh falló"):
            UP._gga_script_upgrade_for_os(r, "linux")

    def test_opencode_no_pkg(self):
        import pytest

        import dxrk.update as UP

        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="  "))
        with pytest.raises(UP.ManualFallbackError):
            UP._opencode_plugin_upgrade(r)

    def test_opencode_no_home(self, monkeypatch):
        import pytest

        import dxrk.update as UP

        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="pkg"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: "~")
        with pytest.raises(UP.ManualFallbackError, match="home"):
            UP._opencode_plugin_upgrade(r)

    def test_opencode_no_dir(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="pkg"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        with pytest.raises(UP.ManualFallbackError, match="No se encontró"):
            UP._opencode_plugin_upgrade(r)

    def test_opencode_not_materialized(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        oc = tmp_path / ".config" / "opencode"
        oc.mkdir(parents=True)
        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="pkg"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        with pytest.raises(UP.ManualFallbackError, match="materialice"):
            UP._opencode_plugin_upgrade(r)

    def test_opencode_no_pm(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        oc = tmp_path / ".config" / "opencode"
        (oc / "node_modules" / "pkg").mkdir(parents=True)
        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="pkg"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(UP, "_select_opencode_package_manager", lambda d: None)
        with pytest.raises(UP.ManualFallbackError, match="gestor de paquetes"):
            UP._opencode_plugin_upgrade(r)

    def test_opencode_bun_npm_success_and_fail(self, tmp_path, monkeypatch):
        import pytest

        import dxrk.update as UP

        oc = tmp_path / ".config" / "opencode"
        (oc / "node_modules" / "pkg").mkdir(parents=True)
        r = UP.UpdateResult(tool=UP.ToolInfo(name="p", npm_package="pkg"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path))
        monkeypatch.setattr(UP, "_select_opencode_package_manager", lambda d: "bun")
        monkeypatch.setattr(UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""))
        UP._opencode_plugin_upgrade(r)
        monkeypatch.setattr(UP, "_select_opencode_package_manager", lambda d: "npm")
        UP._opencode_plugin_upgrade(r)
        monkeypatch.setattr(
            UP.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stderr="bad", stdout="")
        )
        with pytest.raises(RuntimeError, match="upgrade pkg"):
            UP._opencode_plugin_upgrade(r)

    def test_pm_metadata_unknown_and_invalid(self, tmp_path):
        import dxrk.update as UP

        (tmp_path / "package.json").write_text(json.dumps({"packageManager": "yarn@4"}))
        assert UP._opencode_pm_from_metadata(str(tmp_path)) is None
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "package.json").write_text("not json")
        assert UP._opencode_pm_from_metadata(str(bad)) is None


class TestFinalArcsUninstall:
    def test_execute_fallthrough_remove_changed_not_removed(self, tmp_path):
        svc = _svc(str(tmp_path))
        op = U.Operation(U.OpType.REMOVE_FILE, "/x-never", lambda p: (True, False, None))
        res = svc._execute_plan(([], [op]), [])
        assert res.ChangedFiles == [] and res.RemovedFiles == [] and res.RemovedDirectories == []

    def test_sdd_asset_dir_missing(self, tmp_path, monkeypatch):
        home = str(tmp_path)
        cmds = tmp_path / "commands"
        cmds.mkdir()
        monkeypatch.setattr(os.path, "isdir", lambda p: False)
        fa = FlexAdapter(
            home,
            supports_system_prompt=False,
            legacy="raise",
            supports_slash_commands=True,
            commands_dir=str(cmds),
            settings_path=None,
            supports_skills=False,
        )
        ops, _ = _svc(home)._component_operations(fa, ComponentID.SDD)
        assert any(o.type_id == U.OpType.REMOVE_IF_EMPTY for o in ops)

    def test_unknown_component_returns_empty(self, tmp_path):
        ops, targets = _svc(str(tmp_path))._component_operations(FlexAdapter(str(tmp_path)), ComponentID.DXRK)
        assert ops == [] and targets == []

    def test_memory_unknown_strategy(self, tmp_path):
        home = str(tmp_path)
        fake = SimpleNamespace(
            mcp_strategy="bogus",
            supports_system_prompt=False,
            mcp_config_path=lambda h, s="": os.path.join(h, "m.json"),
            settings_path=lambda h: os.path.join(h, "s.json"),
        )
        assert U._memory_targets(fake, home) == []
        assert U._memory_operations(fake, home) == []

    def test_rewrite_unchanged_json_and_toml(self, tmp_path):
        f = tmp_path / "u.json"
        f.write_text('{"b": 2}')
        assert U._rewrite_json_file(str(f), ["a"]).apply(str(f)) == (False, False, None)
        t = tmp_path / "u.toml"
        t.write_text("k = 1\n")
        assert U._rewrite_toml_file(str(t), lambda c: (c, False)).apply(str(t)) == (False, False, None)

    def test_rmdir_failure_returns_false(self, tmp_path, monkeypatch):
        d = tmp_path / "e3"
        d.mkdir()
        monkeypatch.setattr(os, "rmdir", lambda p: (_ for _ in ()).throw(OSError("deny")))
        assert U._remove_dir_if_empty_recursive(str(d)) is False

    def test_slash_without_comment_kept(self):
        out = U._strip_json_comments(b'{"a": 1/2, "b": "x"}')
        assert b"/2" in out

    def test_trailing_comma_at_eof_kept(self):
        assert U._strip_trailing_commas(b'{"a": 1,') == b'{"a": 1,'


class TestFinalArcsUpdate:
    def test_unknown_upgrade_status_falls_through(self):
        import dxrk.update as UP

        rep = UP.UpgradeReport(results=[UP.ToolUpgradeResult(tool_name="z", status="bogus")])
        out = UP.render_upgrade_report(rep)
        assert "z" in out and "omitidas" in out

    def test_backup_success_without_progress(self, tmp_path, monkeypatch):
        import dxrk.backup as B
        import dxrk.update as UP

        home = str(tmp_path)
        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        manifest = SimpleNamespace(id="bid-2", source=None, description="", created_by_version="")

        class Snap:
            def create(self, snapshot_dir, paths):
                return manifest

        monkeypatch.setattr(B, "Snapshotter", Snap)
        monkeypatch.setattr(UP, "config_paths_for_backup", lambda h: [])
        monkeypatch.setattr(B, "write_manifest", lambda p, m: None)
        monkeypatch.setattr(
            UP,
            "_execute_one",
            lambda r, p, d: UP.ToolUpgradeResult(tool_name=r.tool.name, status=UP.ToolUpgradeStatus.SUCCEEDED),
        )
        rep = UP.execute_with_options([r], _profile(), home, False, UP.ExecuteOptions())
        assert rep.backup_id == "bid-2"

    def test_backup_failure_with_progress(self, tmp_path, monkeypatch):
        import dxrk.backup as B
        import dxrk.update as UP

        class Snap:
            def create(self, snapshot_dir, paths):
                raise OSError("ro-disk")

        monkeypatch.setattr(B, "Snapshotter", Snap)
        monkeypatch.setattr(UP, "config_paths_for_backup", lambda h: [])
        monkeypatch.setattr(
            UP,
            "_execute_one",
            lambda r, p, d: UP.ToolUpgradeResult(tool_name=r.tool.name, status=UP.ToolUpgradeStatus.SKIPPED),
        )
        r = _uresult("t", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        buf = io.StringIO()
        rep = UP.execute_with_options([r], _profile(), str(tmp_path), False, UP.ExecuteOptions(progress=buf))
        assert "ro-disk" in rep.backup_warning and "Creando copia" in buf.getvalue()

    def test_binary_upgrade_linux_success(self, monkeypatch):
        import dxrk.update as UP

        called = {}
        monkeypatch.setattr(UP, "_download_and_replace", lambda r, p: called.setdefault("ok", True))
        r = _uresult("mytool", UP.UpdateStatus.UPDATE_AVAILABLE, installed_version="1", latest_version="2")
        UP._binary_upgrade(r, _profile())
        assert called == {"ok": True}
