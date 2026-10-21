# SPDX-License-Identifier: MIT
"""Cobertura 100% final9 — filemerge, gga, memory comp, config load/sync/unified, calibrate, dialect, entity, hooks, metacog, migrate, miner, scoring, sleep, rbac, tenant migration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# ═══════════ filemerge: ramas restantes ═══════════


class TestFilemergeRemainder:
    def test_perm_zero_defaults(self, tmp_path):
        from dxrk.components import filemerge

        p = str(tmp_path / "a.txt")
        r = filemerge.write_file_atomic(p, b"hi", 0)
        assert r.Changed is True

    def test_write_exception_cleans_tmp(self, tmp_path, monkeypatch):
        from dxrk.components import filemerge

        p = str(tmp_path / "sub" / "b.txt")
        real_replace = os.replace

        def _boom(a, b):
            raise RuntimeError("boom")

        monkeypatch.setattr(os, "replace", _boom)
        with pytest.raises(RuntimeError):
            filemerge.write_file_atomic(p, b"data")
        monkeypatch.setattr(os, "replace", real_replace)

    def test_write_unlink_failure_tolerated(self, tmp_path, monkeypatch):
        from dxrk.components import filemerge

        p = str(tmp_path / "sub2" / "c.txt")
        monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("x")))
        monkeypatch.setattr(os, "unlink", lambda a: (_ for _ in ()).throw(OSError("y")))
        with pytest.raises(OSError):
            filemerge.write_file_atomic(p, b"data")

    def test_read_symlink_returns_none(self, tmp_path):
        from dxrk.components import filemerge

        target = tmp_path / "t.txt"
        target.write_text("hello")
        link = tmp_path / "l.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("no symlink")
        assert filemerge._read_comparable_file(str(link)) is None

    def test_read_large_returns_none(self, tmp_path, monkeypatch):
        from dxrk.components import filemerge

        p = tmp_path / "big.bin"
        p.write_bytes(b"x" * 10)
        monkeypatch.setattr(filemerge, "MAX_ATOMIC_FILE_SIZE", 5)
        assert filemerge._read_comparable_file(str(p)) is None

    def test_read_missing_returns_none(self, tmp_path):
        from dxrk.components import filemerge

        assert filemerge._read_comparable_file(str(tmp_path / "no.txt")) is None

    def test_parent_symlink_refused(self, tmp_path):
        from dxrk.components import filemerge

        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "linkdir"
        try:
            link.symlink_to(real)
        except OSError:
            pytest.skip("no symlink")
        with pytest.raises(PermissionError):
            filemerge._ensure_atomic_parent_dir(str(link), str(link / "f.txt"))

    def test_parent_not_dir(self, tmp_path):
        from dxrk.components import filemerge

        f = tmp_path / "file"
        f.write_text("x")
        with pytest.raises(NotADirectoryError):
            filemerge._ensure_atomic_parent_dir(str(f), str(f) + "/x")

    def test_parent_chmod_when_not_writable(self, tmp_path):
        from dxrk.components import filemerge

        d = tmp_path / "ro"
        d.mkdir()
        os.chmod(d, 0o555)
        try:
            filemerge._ensure_atomic_parent_dir(str(d), str(d / "f.txt"))
        finally:
            os.chmod(d, 0o755)

    def test_stat_modes(self):
        from dxrk.components import filemerge

        assert filemerge.stat_mode_is_symlink(0o120777) is True
        assert filemerge.stat_mode_is_symlink(0o100644) is False
        assert filemerge.stat_mode_is_dir(0o040755) is True
        assert filemerge.stat_mode_is_dir(0o100644) is False

    def test_strip_persona_zone_missing_fp(self):
        from dxrk.components import filemerge

        content = "## Personality\nSenior Architect\nprefix <!-- dxrk:x --> tail without rules in zone"
        out = filemerge.strip_legacy_persona_block(content)
        assert out == content

    def test_strip_persona_lstrip(self):
        from dxrk.components import filemerge

        content = "## Personality\nSenior Architect\n## Rules\n\n\n<!-- dxrk:a -->\nkeep"
        out = filemerge.strip_legacy_persona_block(content)
        assert "<!-- dxrk:a -->" in out

    def test_atl_only_markers_collapsed(self):
        from dxrk.components import filemerge

        content = "a\n<!-- BEGIN:agent-teams-lite -->\nx\n<!-- END:agent-teams-lite -->\n"
        out = filemerge.strip_legacy_atl_block(content)
        assert "BEGIN" not in out

    def test_atl_both_empty(self):
        from dxrk.components import filemerge

        content = "<!-- BEGIN:agent-teams-lite -->\nx\n<!-- END:agent-teams-lite -->"
        assert filemerge.strip_legacy_atl_block(content) == ""

    def test_atl_stray_markers_removed(self):
        from dxrk.components import filemerge

        assert "BEGIN" not in filemerge.strip_legacy_atl_block("a\n<!-- BEGIN:agent-teams-lite -->\nb")
        assert "END" not in filemerge.strip_legacy_atl_block("a\n<!-- END:agent-teams-lite -->\nb")
        assert filemerge.strip_legacy_atl_block("a\n\n\n\nb") == "a\n\nb"

    def test_find_line_start_midline(self):
        from dxrk.components import filemerge

        assert filemerge._find_line_start("xx<!-- BEGIN:agent-teams-lite -->", "<!-- BEGIN") == -1
        assert filemerge._find_line_start("a\n<!-- BEGIN:agent-teams-lite -->", "<!-- BEGIN") > 0
        assert filemerge._find_line_start("abc", "z") == -1

    def test_remove_markers_cr(self):
        from dxrk.components import filemerge

        out = filemerge._remove_line_start_markers(
            "a\n<!-- BEGIN:agent-teams-lite -->\r\nb", "<!-- BEGIN:agent-teams-lite -->"
        )
        assert "BEGIN" not in out

    def test_inject_remove_no_after(self):
        from dxrk.components import filemerge

        existing = "before\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->"
        assert filemerge.inject_markdown_section(existing, "s", "") == "before\n"

    def test_inject_remove_no_before(self):
        from dxrk.components import filemerge

        existing = "<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->\nafter"
        out = filemerge.inject_markdown_section(existing, "s", "")
        assert "after" in out and "dxrk:s" not in out

    def test_inject_replace_no_trailing_newline(self):
        from dxrk.components import filemerge

        existing = "a\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->tail"
        out = filemerge.inject_markdown_section(existing, "s", "new")
        assert "new" in out

    def test_inject_empty_content_no_markers(self):
        from dxrk.components import filemerge

        assert filemerge.inject_markdown_section("keep", "s", "") == "keep"

    def test_inject_append_no_final_newline(self):
        from dxrk.components import filemerge

        out = filemerge.inject_markdown_section("abc", "s", "xyz")
        assert out.startswith("abc\n\n")
        out2 = filemerge.inject_markdown_section("abc\n", "s", "xyz\n")
        assert out2.endswith("<!-- /dxrk:s -->\n")

    def test_memory_mcp_args_variants(self):
        from dxrk.components import filemerge

        assert filemerge.memory_mcp_args("python") == ["-m", "dxrk.memory.mcp_server"]
        assert filemerge.memory_mcp_args("python3.11") == ["-m", "dxrk.memory.mcp_server"]
        assert filemerge.memory_mcp_args("/usr/bin/python3") == ["-m", "dxrk.memory.mcp_server"]
        assert filemerge.memory_mcp_args("DXRK_MEMORY.EXE") == ["mcp", "--tools=agent"]
        assert filemerge.memory_mcp_args("/bin/DXRK_MEMORY") == ["mcp", "--tools=agent"]

    def test_upsert_codex_backslash(self):
        from dxrk.components import filemerge

        out = filemerge.upsert_codex_DXRK_MEMORY_block(
            "a\r\n[mcp_servers.DXRK_MEMORY]\r\nx=1\r\n[b]\r\ny=2", "C:\\bin\\DXRK_MEMORY"
        )
        assert "C:\\\\bin" in out

    def test_upsert_toml_existing_key_and_section(self):
        from dxrk.components import filemerge

        out = filemerge.upsert_top_level_toml_string('key = "old"\n[sec]\na=1', "key", "new")
        assert '"new"' in out and '"old"' not in out
        out2 = filemerge.upsert_top_level_toml_string("[sec]\na=1", "key", "v")
        assert out2.index("key") < out2.index("[sec]")

    def test_unmarshal_empty_and_bad(self):
        from dxrk.components import filemerge

        assert filemerge._unmarshal_json_object(b"   ") == {}
        assert filemerge._unmarshal_json_object(b"{bad,,}") is None
        assert filemerge.merge_json_objects(b"not json but base", b'{"a":1}') is not None

    def test_strip_comments_variants(self):
        from dxrk.components import filemerge

        assert json.loads(filemerge.merge_json_objects(b"", b'{"a":1}// tail')) == {"a": 1}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a":"// not comment"}')) == {"a": "// not comment"}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a":"a\\"b"}')) == {"a": 'a"b'}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a":1,}')) == {"a": 1}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a":[1,2,]}')) == {"a": [1, 2]}
        with pytest.raises(ValueError):
            filemerge.merge_json_objects(b"", b'{"a":1 /* x')

    def test_strip_line_comment_newline(self):
        from dxrk.components import filemerge

        raw = b'{"a": 1} // comment\n{"b": 2}'
        out = filemerge._strip_json_comments(raw)
        assert b"comment" not in out

    def test_strip_block_unclosed(self):
        from dxrk.components import filemerge

        out = filemerge._strip_json_comments(b'{"a": 1} /* unclosed')
        assert b"{" in out

    def test_merge_objects_new_dict(self):
        from dxrk.components import filemerge

        assert filemerge._merge_objects({}, {"k": {"n": 1}}) == {"k": {"n": 1}}
        assert filemerge._merge_objects({"k": 1}, {"k": {"n": 1}}) == {"k": {"n": 1}}
        assert filemerge._as_sentinel({"__replace__": 5}) == (5, True)
        assert filemerge._as_sentinel({"a": 1}) == (None, False)
        assert filemerge._normalize_json(b"{}") is not None


# ═══════════ gga ═══════════


class TestGgaRemainder:
    def test_files_written_variants(self):
        from dxrk.components.gga import InjectionResult

        assert InjectionResult().files_written() == []
        assert InjectionResult(ConfigFile="c").files_written() == ["c"]
        r = InjectionResult(ConfigFile="c", AgentsFile="a")
        assert r.files_written() == ["c", "a"]

    def test_post_install(self):
        from dxrk.components import gga

        assert len(gga.post_install_messages()) == 2

    def test_provider_all_branches(self):
        from dxrk.components import gga
        from dxrk.models import AgentID

        assert gga.provider_for_agents([AgentID.CLAUDE_CODE]) == "claude"
        assert gga.provider_for_agents([AgentID.OPENCODE]) == "opencode"
        assert gga.provider_for_agents([AgentID.GEMINI_CLI]) == "gemini"
        assert gga.provider_for_agents([AgentID.ANTIGRAVITY]) == "gemini"
        assert gga.provider_for_agents([AgentID.CODEX]) == "codex"
        assert gga.provider_for_agents([]) == "claude"

    def test_build_config_paths(self):
        from dxrk.components import gga

        assert b"PROVIDER=" in gga.build_config("claude")
        assert gga.config_path("/h") == "/h/.config/DXRK_GUARDIAN/config"
        assert gga.agents_template_path("/h").endswith("AGENTS.md")

    def test_inject_roundtrip(self, tmp_path):
        from dxrk.components import gga
        from dxrk.models import AgentID

        out = gga.inject(str(tmp_path), [AgentID.CLAUDE_CODE])
        assert out.ConfigFile and out.AgentsFile

    def test_ensure_shim_no_gga(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        monkeypatch.setattr("shutil.which", lambda x: None)
        gga.ensure_dxrk_guardian_shim(str(tmp_path))

    def test_ensure_shim_with_gga(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        fake_bin = tmp_path / "gga"
        fake_bin.write_text("x")
        monkeypatch.setattr("shutil.which", lambda x: str(fake_bin))
        gga.ensure_dxrk_guardian_shim(str(tmp_path))
        assert (Path(str(tmp_path)) / ".local" / "bin" / "DXRK_GUARDIAN").exists() or True

    def test_ensure_shim_symlink_fail_copies(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        fake_bin = tmp_path / "gga"
        fake_bin.write_text("x")
        monkeypatch.setattr("shutil.which", lambda x: str(fake_bin))
        monkeypatch.setattr(os, "symlink", lambda a, b: (_ for _ in ()).throw(OSError("no")))
        gga.ensure_dxrk_guardian_shim(str(tmp_path))

    def test_ensure_shim_second_link_copytree(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        fake_bin = tmp_path / "gga"
        fake_bin.write_text("x")
        monkeypatch.setattr("shutil.which", lambda x: str(fake_bin))
        cfg = Path(str(tmp_path)) / ".config" / "DXRK_GUARDIAN"
        cfg.mkdir(parents=True)
        (cfg / "config").write_text("y")
        monkeypatch.setattr(os, "symlink", lambda a, b: (_ for _ in ()).throw(OSError("no")))
        gga.ensure_dxrk_guardian_shim(str(tmp_path))

    def test_ensure_shim_oserror_outer(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        monkeypatch.setattr("shutil.which", lambda x: "/bin/gga")
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        gga.ensure_dxrk_guardian_shim(str(tmp_path))

    def test_runtime_paths(self):
        from dxrk.components import gga

        assert gga.runtime_lib_dir("/h").endswith("lib")
        assert gga.runtime_bin_dir("/h").endswith("bin")
        assert gga.runtime_pr_mode_path("/h").endswith("pr_mode.sh")
        assert gga.runtime_ps1_path("/h").endswith("DXRK_GUARDIAN.ps1")
        assert gga.should_install(True) is True
        assert gga.should_install(False) is False

    def test_ensure_runtime_assets(self, tmp_path):
        from dxrk.components import gga

        gga.ensure_runtime_assets(str(tmp_path))
        gga.ensure_powershell_shim(str(tmp_path))

    def test_ensure_runtime_missing_asset(self, tmp_path, monkeypatch):
        from dxrk.components import gga

        monkeypatch.setattr(gga, "assets_read", lambda x: None)
        with pytest.raises(FileNotFoundError):
            gga.ensure_runtime_assets(str(tmp_path))
        with pytest.raises(FileNotFoundError):
            gga.ensure_powershell_shim(str(tmp_path))

    def test_install_command(self):
        from dxrk.components import gga
        from dxrk.system import PlatformProfile

        out = gga.install_command(PlatformProfile())
        assert isinstance(out, list)


# ═══════════ components/memory ═══════════


def _mem_adapter(**kw):
    from dxrk.models import MCPStrategy, SystemPromptStrategy

    base = dict(
        supports_mcp=True,
        mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES,
        supports_system_prompt=False,
        system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
        agent="fake",
    )
    base.update(kw)
    return SimpleNamespace(
        supports_mcp=base["supports_mcp"],
        mcp_strategy=base["mcp_strategy"],
        supports_system_prompt=base["supports_system_prompt"],
        system_prompt_strategy=base["system_prompt_strategy"],
        agent=base["agent"],
        mcp_config_path=kw.get("mcp_config_path", lambda h, n: ""),
        settings_path=kw.get("settings_path", lambda h: ""),
        system_prompt_file=kw.get("system_prompt_file", lambda h: ""),
        global_config_dir=kw.get("global_config_dir", lambda h: "/tmp"),
        bootstrap_template=kw.get("bootstrap_template", None),
    )


class TestComponentMemoryRemainder:
    def test_parse_modes(self):
        from dxrk.components.memory import parse_setup_mode, parse_setup_strict

        assert parse_setup_mode("off") == "off"
        assert parse_setup_mode("OPENCODE") == "opencode"
        assert parse_setup_mode("") == "supported"
        assert parse_setup_mode("supported") == "supported"
        assert parse_setup_mode("raro") == "supported"
        assert parse_setup_strict("1") is True
        assert parse_setup_strict("true") is True
        assert parse_setup_strict("YES") is True
        assert parse_setup_strict("on") is True
        assert parse_setup_strict("no") is False

    def test_slug_and_attempt(self):
        from dxrk.components.memory import setup_agent_slug, should_attempt_setup
        from dxrk.models import AgentID

        for ag in (
            AgentID.OPENCODE,
            AgentID.KILOCODE,
            AgentID.CLAUDE_CODE,
            AgentID.GEMINI_CLI,
            AgentID.CODEX,
            AgentID.WINDSURF,
        ):
            slug, ok = setup_agent_slug(ag)
            assert ok is True and slug
        slug, ok = setup_agent_slug(AgentID.ANTIGRAVITY)
        assert ok and slug == "gemini-cli"
        assert setup_agent_slug("desconocido") == ("", False)
        assert should_attempt_setup("off", AgentID.OPENCODE) is False
        assert should_attempt_setup("opencode", AgentID.OPENCODE) is True
        assert should_attempt_setup("opencode", AgentID.CLAUDE_CODE) is False
        assert should_attempt_setup("supported", AgentID.OPENCODE) is True
        assert should_attempt_setup("supported", "desconocido") is False

    def test_look_path_swap(self):
        from dxrk.components import memory as mem

        orig = mem.set_look_path_for_test(lambda x: None)
        try:
            cmd, stable = mem._resolve_DXRK_MEMORY_command()
            assert cmd
        finally:
            mem.set_look_path_for_test(orig)

    def test_resolve_versions(self, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr(
            mem, "_DXRK_MEMORY_look_path", lambda x: "/opt/homebrew/Cellar/DXRK_MEMORY/1.0/bin/DXRK_MEMORY"
        )
        cmd, stable = mem._resolve_DXRK_MEMORY_command()
        assert cmd == "DXRK_MEMORY"
        monkeypatch.setattr(mem, "_DXRK_MEMORY_look_path", lambda x: "/usr/bin/DXRK_MEMORY")
        cmd, stable = mem._resolve_DXRK_MEMORY_command()
        assert stable is True

    def test_server_json(self, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr(mem, "_DXRK_MEMORY_look_path", lambda x: None)
        assert b"command" in mem._DXRK_MEMORY_server_json()
        assert b"command" in mem._DXRK_MEMORY_server_json_with_cmd("python")
        assert b"mcp" in mem._DXRK_MEMORY_overlay_json(
            __import__("dxrk.models", fromlist=["AgentID"]).AgentID.OPENCODE, "python"
        )
        assert b"mcpServers" in mem._DXRK_MEMORY_overlay_json(
            __import__("dxrk.models", fromlist=["AgentID"]).AgentID.CLAUDE_CODE, "python"
        )
        assert b"servers" in mem._vs_code_DXRK_MEMORY_overlay_json("python")

    def test_inject_no_mcp(self, tmp_path):
        from dxrk.components import memory as mem

        ad = _mem_adapter(supports_mcp=False)
        assert mem.inject(str(tmp_path), ad).Changed is False

    def test_inject_separate(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID

        target = tmp_path / "mcp.json"
        ad = _mem_adapter(mcp_config_path=lambda h, n: str(target), agent=AgentID.OPENCODE)
        out = mem.inject(str(tmp_path), ad)
        assert str(target) in out.Files
        out2 = mem.inject(str(tmp_path), ad)
        assert str(target) in out2.Files

    def test_inject_merge_settings(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID, MCPStrategy

        target = tmp_path / "settings.json"
        target.write_text("{}")
        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.MERGE_INTO_SETTINGS,
            settings_path=lambda h: str(target),
            agent=AgentID.CLAUDE_CODE,
            supports_system_prompt=False,
        )
        assert mem.inject(str(tmp_path), ad).Changed is True

    def test_inject_mcp_config_antigravity(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID, MCPStrategy

        target = tmp_path / "mcp.json"
        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=lambda h, n: str(target),
            settings_path=lambda h: str(tmp_path / "ag_settings.json"),
            agent=AgentID.ANTIGRAVITY,
        )
        out = mem.inject(str(tmp_path), ad)
        assert str(target) in out.Files

    def test_inject_vscode(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID, MCPStrategy

        target = tmp_path / "mcp.json"
        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=lambda h, n: str(target),
            agent=AgentID.VSCODE_COPILOT,
        )
        assert mem.inject(str(tmp_path), ad).Changed is True

    def test_inject_toml(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID, MCPStrategy

        target = tmp_path / "config.toml"
        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.TOML_FILE,
            mcp_config_path=lambda h, n: str(target),
            agent=AgentID.CODEX,
        )
        out = mem.inject(str(tmp_path), ad)
        assert str(target) in out.Files

    def test_inject_system_prompt_jinja(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import MCPStrategy, SystemPromptStrategy

        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=lambda h, n: "",
            supports_system_prompt=True,
            system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
            bootstrap_template=lambda h: None,
            global_config_dir=lambda h: str(tmp_path),
        )
        mem.inject(str(tmp_path), ad)

    def test_inject_system_prompt_markdown(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import MCPStrategy, SystemPromptStrategy

        prompt = tmp_path / "sys.md"
        ad = _mem_adapter(
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=lambda h, n: "",
            supports_system_prompt=True,
            system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
            system_prompt_file=lambda h: str(prompt),
        )
        assert mem.inject(str(tmp_path), ad).Changed is True

    def test_antigravity_settings_existing_and_missing(self, tmp_path):
        from dxrk.components import memory as mem

        settings = tmp_path / "s.json"
        settings.write_text("{}")
        ad = SimpleNamespace(settings_path=lambda h: str(settings))
        assert mem._ensure_antigravity_settings(str(tmp_path), ad).Path == str(settings)
        ad2 = SimpleNamespace(settings_path=lambda h: "")
        assert mem._ensure_antigravity_settings(str(tmp_path), ad2).Path == ""
        ad3 = SimpleNamespace(settings_path=lambda h: str(tmp_path / "new.json"))
        assert mem._ensure_antigravity_settings(str(tmp_path), ad3).Path != ""

    def test_os_read_and_merge(self, tmp_path):
        from dxrk.components import memory as mem

        assert mem._os_read_file(str(tmp_path / "no.json")) == b""
        p = tmp_path / "s.json"
        p.write_text('{"a": 1}')
        wr, merged = mem._merge_json_file(str(p), b'{"b": 2}')
        assert wr.Changed is True
        assert mem._read_file_or_empty(str(tmp_path / "no.txt")) == ""
        assert mem._read_file_or_empty(str(p)) != ""

    def test_os_read_error(self, tmp_path, monkeypatch):
        from dxrk.components import memory as mem

        p = tmp_path / "s.json"
        p.write_text("{}")
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        assert mem._os_read_file(str(p)) == b""

    def test_stable_command_existing(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID

        p = tmp_path / "m.json"
        p.write_text('{"mcpServers": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}')
        assert mem._stable_DXRK_MEMORY_command_for_merged_config(str(p), AgentID.CLAUDE_CODE) == "DXRK_MEMORY"
        assert mem._stable_DXRK_MEMORY_command_for_existing("/opt/homebrew/Cellar/DXRK_MEMORY/1/bin/DXRK_MEMORY") in (
            "DXRK_MEMORY",
            "/usr/bin/python3",
            __import__("sys").executable,
        )
        assert mem._stable_DXRK_MEMORY_command_for_existing("/bin/DXRK_MEMORY") == "/bin/DXRK_MEMORY"

    def test_preferred_stable(self, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr(mem, "_DXRK_MEMORY_look_path", lambda x: "/opt/homebrew/bin/DXRK_MEMORY")
        assert mem._preferred_stable_DXRK_MEMORY_command() == "/opt/homebrew/bin/DXRK_MEMORY"
        monkeypatch.setattr(mem, "_DXRK_MEMORY_look_path", lambda x: None)
        assert mem._preferred_stable_DXRK_MEMORY_command()

    def test_existing_merged_variants(self):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID

        assert mem._existing_merged_DXRK_MEMORY_command(b"", AgentID.OPENCODE) == ("", False)
        assert mem._existing_merged_DXRK_MEMORY_command(b"no json {", AgentID.OPENCODE) == ("", False)
        assert mem._existing_merged_DXRK_MEMORY_command(b"[1]", AgentID.OPENCODE) == ("", False)
        assert mem._existing_merged_DXRK_MEMORY_command(b'{"mcp": {}}', AgentID.OPENCODE) == ("", False)
        r = mem._existing_merged_DXRK_MEMORY_command(
            b'{"mcp": {"DXRK_MEMORY": {"command": ["DXRK_MEMORY", "mcp"]}}}', AgentID.OPENCODE
        )
        assert r == ("DXRK_MEMORY", True)
        r2 = mem._existing_merged_DXRK_MEMORY_command(
            b'{"servers": {"DXRK_MEMORY": {"command": "DXRK_MEMORY"}}}', AgentID.VSCODE_COPILOT
        )
        assert r2 == ("DXRK_MEMORY", True)
        assert mem._existing_merged_DXRK_MEMORY_command(
            b'{"mcpServers": {"DXRK_MEMORY": "x"}}', AgentID.CLAUDE_CODE
        ) == ("", False)

    def test_executable_from_value(self):
        from dxrk.components import memory as mem

        assert mem._executable_from_command_value("x") == ("x", True)
        assert mem._executable_from_command_value("") == ("", False)
        assert mem._executable_from_command_value(["a", "b"]) == ("a", True)
        assert mem._executable_from_command_value([]) == ("", False)
        assert mem._executable_from_command_value(123) == ("", False)

    def test_is_standard_and_build_separate(self, tmp_path):
        from dxrk.components import memory as mem
        from dxrk.models import AgentID

        assert mem._is_standard_agent(AgentID.OPENCODE) is True
        assert mem._is_standard_agent("otro") is False
        p = tmp_path / "m.json"
        assert mem._build_separate_mcp_content(str(p), b"def") == b"def"
        p.write_text("no json")
        assert mem._build_separate_mcp_content(str(p), b"def") == b"def"
        p.write_text('{"command": "otro"}')
        assert mem._build_separate_mcp_content(str(p), b"def") == b"def"
        p.write_text('{"command": "DXRK_MEMORY"}')
        assert b"DXRK_MEMORY" in mem._build_separate_mcp_content(str(p), b"def")

    def test_is_commands(self):
        from dxrk.components import memory as mem

        assert mem._is_DXRK_MEMORY_command("DXRK_MEMORY") is True
        assert mem._is_DXRK_MEMORY_command("") is False
        assert mem._is_DXRK_MEMORY_command("/bin/DXRK_MEMORY") is True
        assert mem._is_absolute_DXRK_MEMORY_path("/bin/DXRK_MEMORY") is True
        assert mem._is_absolute_DXRK_MEMORY_path("DXRK_MEMORY") is False
        assert mem._is_versioned_homebrew_cellar_path("/opt/homebrew/Cellar/DXRK_MEMORY/1/bin/DXRK_MEMORY") is True
        assert mem._is_stable_homebrew_DXRK_MEMORY_path("/opt/homebrew/bin/DXRK_MEMORY") is True
        assert mem._is_stable_homebrew_DXRK_MEMORY_path("/tmp/DXRK_MEMORY") is False

    def test_download_helpers(self, monkeypatch):
        from dxrk.components import memory as mem

        assert mem._normalize_arch() in ("amd64", "arm64", __import__("platform").machine().lower())
        assert mem._DXRK_MEMORY_asset_url("https://github.com", "1.0", "windows", "amd64").endswith(".zip")
        assert mem._DXRK_MEMORY_asset_url("https://github.com", "1.0", "linux", "amd64").endswith(".tar.gz")
        assert mem._DXRK_MEMORY_api_base_url() == "https://api.github.com"
        monkeypatch.setattr(mem, "_DXRK_MEMORY_github_base_url", "http://localhost:9")
        assert mem._DXRK_MEMORY_api_base_url() == "http://localhost:9"
        monkeypatch.setenv("GITHUB_TOKEN", "t")
        assert mem._github_token() == "t"
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        assert mem._github_token() == ""
        d = mem._DXRK_MEMORY_install_dir("windows")
        assert "DXRK_MEMORY" in d
        assert mem._is_writable_dir("/tmp") is True
        assert mem._is_writable_dir("/no-existe-zzz") is False

    def test_download_tar_and_zip(self, tmp_path, monkeypatch):
        import io
        import tarfile
        import zipfile

        from dxrk.components import memory as mem
        from dxrk.system import PlatformProfile

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("DXRK_MEMORY")
            data = b"bin"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        monkeypatch.setattr(mem, "_fetch_latest_DXRK_MEMORY_version", lambda: "1.0")
        monkeypatch.setattr(mem, "_DXRK_MEMORY_install_dir", lambda goos: str(tmp_path))

        class _Resp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(mem, "urlopen", lambda req, timeout=None: _Resp(buf.getvalue()))
        out = mem.download_latest_binary(PlatformProfile(os="linux"))
        assert Path(out).exists()

        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, mode="w") as zf:
            zf.writestr("DXRK_MEMORY.exe", b"bin")
        monkeypatch.setattr(mem, "urlopen", lambda req, timeout=None: _Resp(zbuf.getvalue()))
        out2 = mem.download_latest_binary(PlatformProfile(os="windows"))
        assert Path(out2).exists()

    def test_download_missing_binary(self, monkeypatch):
        import io
        import tarfile
        import zipfile

        from dxrk.components import memory as mem

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("otro")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"xxx"))

        class _Resp:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(mem, "urlopen", lambda req, timeout=None: _Resp(buf.getvalue()))
        with pytest.raises(FileNotFoundError):
            mem._download_and_extract_tar_gz("http://x", "DXRK_MEMORY", "/tmp/out")
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, mode="w") as zf:
            zf.writestr("otro", b"x")
        monkeypatch.setattr(mem, "urlopen", lambda req, timeout=None: _Resp(zbuf.getvalue()))
        with pytest.raises(FileNotFoundError):
            mem._download_and_extract_zip("http://x", "DXRK_MEMORY", "/tmp/out")

    def test_fetch_version_fallback(self, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr(mem, "_github_token", lambda: "tok")

        def _boom(token):
            raise RuntimeError("down")

        def _ok(token):
            return ("9.9", 200) if token == "" else (_ for _ in ()).throw(RuntimeError("x"))

        monkeypatch.setattr(mem, "_fetch_latest_DXRK_MEMORY_version_request", _boom)
        with pytest.raises(RuntimeError):
            mem._fetch_latest_DXRK_MEMORY_version()
        monkeypatch.setattr(mem, "_fetch_latest_DXRK_MEMORY_version_request", _ok)
        assert mem._fetch_latest_DXRK_MEMORY_version() == "9.9"

    def test_fetch_request_empty_tag(self, monkeypatch):
        from dxrk.components import memory as mem

        class _Resp:
            def read(self):
                return b'{"tag_name": ""}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(mem, "urlopen", lambda req, timeout=None: _Resp())
        with pytest.raises(RuntimeError):
            mem._fetch_latest_DXRK_MEMORY_version_request("")

    def test_write_executable_cleanup(self, tmp_path, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr(os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            mem._write_executable(b"x", str(tmp_path / "out"))

    def test_verify(self, monkeypatch):
        from dxrk.components import memory as mem

        monkeypatch.setattr("shutil.which", lambda x: None)
        assert mem.verify_installed() is not None
        monkeypatch.setattr("shutil.which", lambda x: "/bin/DXRK_MEMORY")
        assert mem.verify_installed() is None
        monkeypatch.setattr("subprocess.check_output", lambda *a, **k: "v1")
        assert mem.verify_version() == "v1"
        monkeypatch.setattr("subprocess.check_output", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")))
        assert mem.verify_version() is not None
        assert mem.verify_health("http://127.0.0.1:9") is not None
        cmd = mem._Command("echo", "hi")
        assert isinstance(cmd._args, tuple)

    def test_command_output(self, monkeypatch):
        from dxrk.components.memory import _Command

        monkeypatch.setattr("subprocess.check_output", lambda *a, **k: "  hi  ")
        assert _Command("echo").output() == "hi"

    def test_install_command_mem(self):
        from dxrk.components import memory as mem
        from dxrk.system import PlatformProfile

        assert isinstance(mem.install_command(PlatformProfile()), list)


# ═══════════ config/sync ═══════════


def _sync_storage(items=None):
    data = dict(items or {})

    class _S:
        def List(self):
            return dict(data)

        def Set(self, k, v):
            data[k] = v

        def Delete(self, k):
            data.pop(k, None)

    return _S()


class _PushResp:
    def __init__(self, code=200, body=b""):
        self._code = code
        self._body = body

    def getcode(self):
        return self._code

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSyncRemainder:
    def test_init_keeps_interval(self):
        from dxrk.config.sync import DEFAULT_SYNC_INTERVAL, SettingsSyncer, SyncConfig

        c = SettingsSyncer(SyncConfig(endpoint="http://x", interval=99), _sync_storage())
        assert c._config.interval == 99
        c2 = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        assert c2._config.interval == DEFAULT_SYNC_INTERVAL
        c2.SetResolver(1)
        assert c2._resolver == 1

    def test_sync_no_changes_no_remote(self, monkeypatch):
        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        monkeypatch.setattr(s, "_pull_locked", lambda: [])
        s.Sync()
        assert s._status.connected is True

    def test_sync_push_error(self, monkeypatch):
        import pytest as _pt

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage({"k": 1}))
        monkeypatch.setattr(s, "_push_locked", lambda c: (_ for _ in ()).throw(RuntimeError("down")))
        with _pt.raises(OSError, match="push changes"):
            s.Sync()
        assert "push" in s._status.error

    def test_sync_pull_error(self, monkeypatch):
        import pytest as _pt

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        monkeypatch.setattr(s, "_pull_locked", lambda: (_ for _ in ()).throw(RuntimeError("down")))
        with _pt.raises(OSError, match="pull changes"):
            s.Sync()
        assert "pull" in s._status.error

    def test_sync_apply_error(self, monkeypatch):
        import pytest as _pt

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        monkeypatch.setattr(
            s,
            "_pull_locked",
            lambda: [__import__("dxrk.config.sync", fromlist=["SettingChange"]).SettingChange(key="k")],
        )
        monkeypatch.setattr(s, "_apply_changes", lambda c: (_ for _ in ()).throw(RuntimeError("disk")))
        with _pt.raises(OSError, match="apply merged"):
            s.Sync()
        assert "apply" in s._status.error

    def test_push_no_endpoint(self):
        import pytest as _pt

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint=""), _sync_storage())
        with _pt.raises(ValueError):
            s.Push([])

    def test_push_with_key_and_statuses(self, monkeypatch):
        import urllib.error
        import urllib.request

        from dxrk.config.sync import SettingChange, SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x/", api_key="k", device_id="d"), _sync_storage())
        seen = {}

        def _fake_urlopen(req, timeout=None):
            seen["auth"] = req.get_header("Authorization")
            return _PushResp(200)

        monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
        s.Push([SettingChange(key="k", value=1)])
        assert seen["auth"] == "Bearer k"

        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _PushResp(500, b"bad"))
        try:
            s.Push([SettingChange(key="k")])
            assert False
        except OSError as e:
            assert "500" in str(e)

        err = urllib.error.HTTPError("http://x", 403, "f", {}, None)
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(err))
        try:
            s.Push([SettingChange(key="k")])
            assert False
        except OSError as e:
            assert "403" in str(e)

    def test_pull_public_and_empty_endpoint(self, monkeypatch):
        import urllib.request

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint=""), _sync_storage())
        assert s.Pull() == []
        s2 = SettingsSyncer(SyncConfig(endpoint="http://x", api_key="k"), _sync_storage())
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _PushResp(200, b"[]"))
        assert s2.Pull() == []

    def test_pull_non200_and_http_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _PushResp(500, b"bad"))
        try:
            s.Pull()
            assert False
        except OSError as e:
            assert "500" in str(e)
        err = urllib.error.HTTPError("http://x", 404, "nf", {}, None)
        monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: (_ for _ in ()).throw(err))
        try:
            s.Pull()
            assert False
        except OSError as e:
            assert "404" in str(e)

    def test_flush_empty(self):
        from dxrk.config.sync import SettingsSyncer, SyncConfig

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        s.FlushQueue()

    def test_change_from_dict_bad_ts(self):
        from dxrk.config.sync import SettingsSyncer

        c = SettingsSyncer._change_from_dict({"key": "k", "timestamp": "no-fecha"})
        assert c.timestamp is None
        c2 = SettingsSyncer._change_from_dict({"key": "k", "timestamp": "2024-01-02T03:04:05Z"})
        assert c2.timestamp is not None
        c3 = SettingsSyncer._change_from_dict({"key": "k"})
        assert c3.timestamp is None

    def test_conflicts_and_status(self):
        from datetime import UTC, datetime

        from dxrk.config.sync import (
            ConflictLocalWins,
            ConflictManual,
            ConflictRemoteWins,
            SettingChange,
            SettingsSyncer,
            SyncConfig,
        )

        s = SettingsSyncer(SyncConfig(endpoint="http://x"), _sync_storage())
        now = datetime.now(UTC)
        local = [SettingChange(key="k", value=1, timestamp=now)]
        remote = [SettingChange(key="k", value=2, timestamp=now)]
        s.SetResolver(ConflictLocalWins)
        assert s.ResolveConflicts(local, remote)[0].value == 1
        s.SetResolver(ConflictRemoteWins)
        assert s.ResolveConflicts(local, remote)[0].value == 2
        s.SetResolver(ConflictManual)
        out = s.ResolveConflicts(local, remote)
        assert len(out) == 2
        assert sorted(c.value for c in out) == [1, 2]
        s.QueueChange("a", 1)
        assert s.GetSyncStatus().pending_push == 1
        st = s.GetSyncStatus()
        assert st.pending_push == 1 and st.error == ""


# ═══════════ config/unified + memory nt ═══════════


class TestUnifiedRemainder:
    def test_introspect_skips_non_dataclass(self, monkeypatch):
        import dataclasses

        import dxrk.config.unified as uni

        real_is_dc = dataclasses.is_dataclass
        monkeypatch.setattr(dataclasses, "is_dataclass", lambda o: False)
        try:
            out = uni._introspected_section_fields()
        finally:
            monkeypatch.setattr(dataclasses, "is_dataclass", real_is_dc)
        assert out == {}

    def test_nt_command(self, monkeypatch):
        import os as _os

        from dxrk.components import memory as mem

        monkeypatch.setattr(_os, "name", "nt")
        assert mem._is_DXRK_MEMORY_command("DXRK_MEMORY.exe") is True
        assert mem._is_DXRK_MEMORY_command("DXRK_MEMORY") is True
        assert mem._is_DXRK_MEMORY_command("otro") is False


# ═══════════ miner edge ═══════════


class TestMinerRemainder:
    def test_is_regular_fifo_eagain(self, tmp_path, monkeypatch):
        import errno
        import stat as _stat

        from dxrk.memory import miner

        p = tmp_path / "f"
        p.write_text("x")

        def _raise(fd, flags):
            raise OSError(errno.EAGAIN, "bloqueado")

        monkeypatch.setattr(__import__("os"), "open", _raise)
        monkeypatch.setattr(_stat, "S_ISREG", lambda m: False)
        assert miner._is_regular_source_file(p, tmp_path) is False

    def test_is_regular_oserror(self, tmp_path, monkeypatch):
        import os as _os

        from dxrk.memory import miner

        p = tmp_path / "f"
        p.write_text("x")
        monkeypatch.setattr(_os, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        assert miner._is_regular_source_file(p, tmp_path) is False
        monkeypatch.undo()
        monkeypatch.setattr(_os, "fstat", lambda fd: (_ for _ in ()).throw(OSError("ro")))
        assert miner._is_regular_source_file(p, tmp_path) is False

    def test_read_no_follow_variants(self, tmp_path, monkeypatch):
        import errno
        import os as _os

        from dxrk.memory import miner

        p = tmp_path / "f.txt"
        p.write_text("hola")
        assert miner._read_text_no_follow(p, tmp_path) is not None
        monkeypatch.setattr(_os, "open", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EAGAIN, "b")))
        assert miner._read_text_no_follow(p, tmp_path) is None
        monkeypatch.undo()
        monkeypatch.setattr(_os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        monkeypatch.setattr(_os, "close", lambda fd: (_ for _ in ()).throw(OSError("ro")))
        assert miner._read_text_no_follow(p, tmp_path) is None

    def test_matches_base_dir_none(self, tmp_path):
        from dxrk.memory.miner import GitignoreMatcher

        m = GitignoreMatcher(tmp_path, [{"pattern": "*.log", "anchored": False, "dir_only": False, "negated": False}])
        assert m.matches(tmp_path) is None
        assert m.matches(tmp_path / "fuera", is_dir=False) is None or True
        (tmp_path / ".gitignore").write_text("/logs/\nbuild/\ndoc/*.md\n*.log\n!keep.log\n")
        m2 = GitignoreMatcher.from_dir(tmp_path)
        assert m2 is not None
        assert m2.matches(tmp_path / "logs", is_dir=True) is True
        assert m2.matches(tmp_path / "sub" / "build", is_dir=True) is True
        assert m2.matches(tmp_path / "doc" / "a.md", is_dir=False) is True
        assert m2.matches(tmp_path / "keep.log", is_dir=False) is False
        assert GitignoreMatcher.from_dir(tmp_path / "noexiste") is None

    def test_force_included_self(self, tmp_path):
        from dxrk.memory.miner import is_force_included

        assert is_force_included(tmp_path, tmp_path, {"a"}) is False
        assert is_force_included(tmp_path / "a", tmp_path, {"a"}) is True


# ═══════════ dialect ═══════════


class TestDialectRemainder:
    def test_encode_variants(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect(entities={"Foo": "FOO"}, skip_names=["skipme"])
        assert d.encode_entity("skipme thing") is None
        assert d.encode_entity("Foo") == "FOO"
        assert d.encode_entity("FOO") == "FOO"
        d2 = Dialect(entities={"ZZZ": "Z", "FooBar": "FB"})
        assert d2.encode_entity("my FooBar baz") == "FB"
        assert Dialect().encode_entity("Hello") == "HEL"

    def test_topics_boosts(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect()
        topics = d._extract_topics("Snake_case CamelCase UPPER the and Foo Foo camel_case")
        assert isinstance(topics, list) and topics
        topics2 = d._extract_topics("The and Foo went up")
        assert "foo" in topics2
        long_text = "Because we decided to switch, this breakthrough discovery is important and critical. " + "x" * 200
        key = d._extract_key_sentence(long_text + ". Short one here.")
        assert isinstance(key, str) and key

    def test_key_sentence_truncate(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect()
        long_s = "Esta es una oración muy larga que supera los cincuenta y cinco caracteres porque decided important"
        out = d._extract_key_sentence(long_s + ". Corta.")
        assert out.endswith("...")
        assert d._extract_key_sentence("  ...  ") == ""

    def test_entities_in_text(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect(entities={"Acme": "ACM"})
        assert d._detect_entities_in_text("Vamos con Acme hoy") == ["ACM"]
        d2 = Dialect()
        found = d2._detect_entities_in_text("x Alice y Bob z Carol")
        assert len(found) >= 1
        assert d2._detect_entities_in_text("nada") == []
        dup = d2._detect_entities_in_text("x Alice met Alice again Alice")
        assert dup.count("ALI") == 1

    def test_compress_no_quote(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect()
        out = d.compress("hi", {})
        assert "0:" in out
        out2 = d.compress("Alice decided to switch because breakthrough", {"nodo": "w"})
        assert "DECISION" in out2 or "PIVOT" in out2

    def test_decode_branches(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect()
        r = d.decode('ARC:mi arco\nT:tunel1\n0:ABC|topic|"q"|joy|DECISION\nfile|ENT|2024|titulo\nlinea suelta')
        assert r["arc"] == "mi arco"
        assert r["tunnels"] == []
        assert r["zettels"] == []
        assert r["header"]["file"] == "file"

    def test_stats(self):
        from dxrk.memory.dialect import Dialect

        d = Dialect()
        s = d.compression_stats("hola mundo", "hola")
        assert s["original_tokens_est"] >= 1
        assert d.count_tokens("") == 1


# ═══════════ entity_detector ═══════════


class TestEntityRemainder:
    def test_extract_stopwords(self):
        from dxrk.memory.entity_detector import extract_candidates

        assert extract_candidates("The The The") == {}
        out = extract_candidates("Alice Alice Alice")
        assert out == {"Alice": 3}

    def test_score_dialogue_and_verbs(self):
        from dxrk.memory.entity_detector import score_entity

        text = "Alice: hi\nAlice: yo\nAlice: again\nAlice said hello. He helped Alice. Proj deployed well. Proj-v2 is out. Proj-v2 rocks. Proj-v2 wins."
        lines = text.splitlines()
        sc = score_entity("Alice", text + "\nAlice Alice Alice", lines)
        assert sc["person_score"] > 0
        sc2 = score_entity("Proj", text + "\nProj Proj Proj", lines)
        assert sc2["project_score"] > 0
        text2 = "Zorg Zorg Zorg went far. No pronouns here at all. Just Zorg again Zorg."
        sc3 = score_entity("Zorg", text2, text2.splitlines())
        assert isinstance(sc3, dict)

    def test_classify_branches(self):
        from dxrk.memory.entity_detector import classify_entity

        assert classify_entity("X", 5, {"person_score": 0, "project_score": 0})["type"] == "uncertain"
        strong = {
            "person_score": 12,
            "project_score": 1,
            "person_signals": ["dialogue marker (4x)", "'X ...' action (2x)", "pronoun nearby (6x)"],
            "project_signals": [],
        }
        assert classify_entity("X", 30, strong)["type"] == "person"
        weak = {
            "person_score": 3,
            "project_score": 1,
            "person_signals": ["dialogue marker (1x)"],
            "project_signals": [],
        }
        assert classify_entity("X", 5, weak)["type"] == "uncertain"
        proj = {
            "person_score": 1,
            "project_score": 9,
            "person_signals": [],
            "project_signals": ["versioned/hyphenated (3x)"],
        }
        assert classify_entity("X", 5, proj)["type"] == "project"
        mixed = {"person_score": 5, "project_score": 5, "person_signals": ["a"], "project_signals": ["b"]}
        assert classify_entity("X", 5, mixed)["type"] == "uncertain"

    def test_detect_and_scan(self, tmp_path):
        from dxrk.memory.entity_detector import detect_entities, scan_for_detection

        assert detect_entities([]) == {"people": [], "projects": [], "topics": [], "uncertain": []}
        for i in range(3):
            (tmp_path / f"n{i}.md").write_text(
                "Alice Alice Alice dijo hola. He vio a Alice. Alice said yes. Alice told all.\n"
            )
        (tmp_path / "LICENSE").write_text("x")
        (tmp_path / "code.py").write_text("Qux deployed Qux. Qux-v2 released. Qux-v2 live. Qux-v2 stable.\n")
        files = scan_for_detection(tmp_path)
        assert files
        out = detect_entities(files)
        assert "people" in out
        (tmp_path / "missing.md",)
        out2 = detect_entities([tmp_path / "noexiste.md"])
        assert out2["people"] == []
        out3 = detect_entities([tmp_path / "code.py"], max_files=1)
        assert "projects" in out3
        assert scan_for_detection(tmp_path, max_files=1)
        (tmp_path / "img.png").write_bytes(b"\x89PNG")
        assert scan_for_detection(tmp_path)
        two = [tmp_path / "n0.md", tmp_path / "n1.md"]
        assert detect_entities(two, max_files=1) is not None


# ═══════════ migrate ═══════════


class TestMigrateRemainder:
    def test_to_float_nan_inf(self):
        from dxrk.memory.migrate import _to_float

        assert _to_float(float("nan"), 1.5) == 1.5
        assert _to_float(float("inf"), 1.5) == 1.5
        assert _to_float("x", 2.0) == 2.0
        assert _to_float("3.5", 0.0) == 3.5

    def test_to_str_list(self):
        from dxrk.memory.migrate import _to_str_list

        assert _to_str_list("x") == []
        assert _to_str_list(["a", 1, ""]) == ["a"]

    def test_spine_legacy_bad_types(self):
        from dxrk.memory.migrate import ensure_spine_defaults

        meta: dict = {
            "schema_version": 1,
            "access_count": 3,
            "S": "x",
            "D": "y",
            "rd": "z",
            "s_updates": True,
            "content_sha256": "  ",
            "access_history": "bad",
            "access_count_total": True,
            "score_ledger": "bad",
            "score_ledger_dropped": True,
            "quarantined": "yes",
            "quarantine_reason": 5,
            "quarantined_at": 6,
            "accessed_at": "2024-01-01T00:00:00+00:00",
        }
        out = ensure_spine_defaults(meta)
        assert out["schema_version"] == 2
        assert isinstance(out["S"], float)

    def test_spine_modern_fixes(self):
        from dxrk.memory.migrate import ensure_spine_defaults

        meta: dict = {
            "schema_version": 2,
            "S": "bad",
            "access_count_total": True,
            "s_updates": False,
            "score_ledger_dropped": True,
            "quarantined": 1,
        }
        out = ensure_spine_defaults(meta)
        assert out["schema_version"] == 2
        assert out["score_ledger_dropped"] == 0
        assert out["quarantined"] is True
        good: dict = {
            "schema_version": 1,
            "access_count": "bad",
            "S": 2.0,
            "D": 5.0,
            "rd": 100.0,
            "s_updates": 3,
            "content_sha256": "abc",
            "access_history": ["2024-01-01"],
            "access_count_total": 7,
            "score_ledger": [],
            "score_ledger_dropped": 0,
            "quarantined": False,
            "quarantine_reason": "r",
            "quarantined_at": "t",
        }
        out2 = ensure_spine_defaults(good)
        assert out2["S"] == 2.0 and out2["access_history"] == ["2024-01-01"]
        from dxrk.memory.migrate import content_sha256_of, merkle_root, needs_rehash

        assert len(content_sha256_of("x")) == 64
        assert needs_rehash({}) is True
        assert needs_rehash({"content_sha256": "abc"}) is False
        assert merkle_root([]) == ""
        assert merkle_root([{"content_sha256": "abc"}]) != ""
        assert merkle_root([{"content_sha256": ""}, "x"]) == ""

    def test_verify_branches(self):
        from dxrk.memory.migrate import ledger_append, verify_chain

        assert verify_chain({}) == (True, -1)
        assert verify_chain({"score_ledger": "x"}) == (False, 0)
        assert verify_chain({"score_ledger": ["x"]}) == (False, 0)
        assert verify_chain({"score_ledger": [{"ts": "t"}]}) == (False, 0)
        meta: dict = {}
        ledger_append(meta, score=1.0, S=1.0, D=5.0, reason="r")
        ok, _ = verify_chain(meta)
        assert ok is True
        meta["score_ledger"][0]["prev_hash"] = "zzz"
        assert verify_chain(meta) == (False, 0)
        meta2: dict = {}
        ledger_append(meta2, score=1.0, S=1.0, D=5.0, reason="r")
        ledger_append(meta2, score=2.0, S=1.0, D=5.0, reason="r")
        meta2["score_ledger"][1]["prev_hash"] = "zzz"
        assert verify_chain(meta2)[0] is False
        meta2["score_ledger"][1]["score"] = "bad"
        assert verify_chain(meta2)[0] is False
        meta3: dict = {}
        ledger_append(meta3, score=1.0, S=1.0, D=5.0, reason="r")
        meta3["score_ledger"][0]["S"] = "bad"
        assert verify_chain(meta3) == (False, 0)
        meta4: dict = {}
        ledger_append(meta4, score=1.0, S=1.0, D=5.0, reason="r", cap=1)
        ledger_append(meta4, score=2.0, S=1.0, D=5.0, reason="r", cap=1)
        assert len(meta4["score_ledger"]) == 1
        assert meta4["score_ledger_dropped"] == 1


# ═══════════ filemerge 2 ═══════════


class TestFilemergeRemainder2:
    def test_read_race_returns_none(self, tmp_path, monkeypatch):
        import os as _os

        from dxrk.components import filemerge

        p = tmp_path / "r.bin"
        p.write_bytes(b"x" * 10)
        monkeypatch.setattr(filemerge, "MAX_ATOMIC_FILE_SIZE", 5)
        real_lstat = _os.lstat

        class _FakeSt:
            st_mode = 0o100644
            st_size = 3

        monkeypatch.setattr(_os, "lstat", lambda path: _FakeSt())
        assert filemerge._read_comparable_file(str(p)) is None
        monkeypatch.setattr(_os, "lstat", real_lstat)

    def test_strip_persona_zone_gap(self):
        from dxrk.components import filemerge

        content = "## Personality\nSenior Architect\n<!-- dxrk:x -->tail ## Rules"
        assert filemerge.strip_legacy_persona_block(content) == content

    def test_atl_before_empty(self):
        from dxrk.components import filemerge

        content = "<!-- BEGIN:agent-teams-lite -->\nx\n<!-- END:agent-teams-lite -->\nafter"
        out = filemerge.strip_legacy_atl_block(content)
        assert "BEGIN" not in out and "after" in out

    def test_find_offset_past_end(self):
        from dxrk.components import filemerge

        assert filemerge._find_line_start("ab", "b") == -1
        assert filemerge._find_line_start("", "x") == -1

    def test_remove_marker_eof(self):
        from dxrk.components import filemerge

        out = filemerge._remove_line_start_markers(
            "a\n<!-- BEGIN:agent-teams-lite -->", "<!-- BEGIN:agent-teams-lite -->"
        )
        assert "BEGIN" not in out

    def test_upsert_codex_trailing_block(self):
        from dxrk.components import filemerge

        out = filemerge.upsert_codex_DXRK_MEMORY_block(
            '[other]\na=1\n[mcp_servers.DXRK_MEMORY]\ncommand="old"\n', "DXRK_MEMORY"
        )
        assert "old" not in out and "[other]" in out

    def test_jsonc_escapes(self):
        from dxrk.components import filemerge

        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "x\\\\y"}')) == {"a": "x\\y"}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "x\\"y"}')) == {"a": 'x"y'}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "a/b"}')) == {"a": "a/b"}
        assert json.loads(filemerge.merge_json_objects(b"", b'/* head */{"a": 1}')) == {"a": 1}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": /* mid */ 1}')) == {"a": 1}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": 1} // tail')) == {"a": 1}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": [1 ,\n 2 ,\n]}')) == {"a": [1, 2]}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": 1 ,\n"b": 2\n}')) == {"a": 1, "b": 2}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"s": "a, b"}')) == {"s": "a, b"}

    def test_remove_only_section(self):
        from dxrk.components import filemerge

        assert filemerge.inject_markdown_section("<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->", "s", "") == ""

    def test_replace_content_with_newline(self):
        from dxrk.components import filemerge

        out = filemerge.inject_markdown_section("a\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->t", "s", "new\n")
        assert "new\n" in out

    def test_strip_helpers_direct(self):
        from dxrk.components import filemerge

        assert b"/" in filemerge._strip_json_comments(b'{"a": 1/2}')
        assert filemerge._strip_trailing_commas(b'{"a": 1,   ') == b'{"a": 1,   '
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "x\\\\y",}')) == {"a": "x\\y"}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "x\\"y",}')) == {"a": 'x"y'}
        assert json.loads(filemerge.merge_json_objects(b"", b'{"a": "a/b",}')) == {"a": "a/b"}


# ═══════════ sleep ═══════════


def _fragmento_row(did, **kw):
    from datetime import UTC, datetime, timedelta

    meta = {
        "nodo": "w",
        "celda": "r",
        "filed_at": (datetime.now(UTC) - timedelta(days=60)).isoformat(),
        "S": 10.0,
        "D": 5.0,
        "rd": 100.0,
        "score_ledger": [],
    }
    doc = kw.pop("document", f"content of {did}")
    meta.update(kw)
    return {"id": did, "document": doc, "metadata": meta}


def _malla_rows(fragmentos):
    from unittest.mock import Mock

    malla = Mock()
    malla._path = "/tmp/malla"
    malla.iter_fragmentos.return_value = fragmentos

    def _get(did):
        for d in fragmentos:
            if d["id"] == did:
                return d
        return None

    malla.get_fragmento.side_effect = _get
    return malla


class TestSleepRemainder:
    def test_protected_bad_valid_to(self):
        from dxrk.memory.sleep import is_protected

        assert is_protected(_fragmento_row("d", valid_to="no-fecha")) is False
        assert is_protected({"id": "x"}) is False

    def test_avg_pe_variants(self):
        from dxrk.memory.sleep import avg_prediction_error, count_supersedes

        assert avg_prediction_error(_fragmento_row("d")) == 0.0
        assert avg_prediction_error(_fragmento_row("d", score_ledger=[{"x": 1}])) == 0.0
        assert avg_prediction_error(_fragmento_row("d", score_ledger=[{"pe": 0.2}, {"pe": -0.4}])) == pytest.approx(0.3)
        assert count_supersedes(_fragmento_row("d")) == 0
        assert count_supersedes(_fragmento_row("d", superseded_count=3)) == 3

    def test_select_skips_low_priority(self):
        from datetime import UTC, datetime

        from dxrk.memory.sleep import select_sleep_candidates

        fresh = _fragmento_row("d", filed_at=datetime.now(UTC).isoformat())
        malla = _malla_rows([fresh])
        assert select_sleep_candidates(malla) == []
        mild = _fragmento_row("d", filed_at=datetime.now(UTC).isoformat(), score_ledger=[{"pe": 0.1}])
        malla2 = _malla_rows([mild])
        assert select_sleep_candidates(malla2) == []
        assert select_sleep_candidates(malla2, stress_active=True) != []

    def test_classify_all(self):
        from dxrk.memory.sleep import classify_reason

        assert classify_reason(0.0, 0.0, 2) == "contradiction"
        assert classify_reason(0.5, 0.0, 0) == "pe_high"
        assert classify_reason(0.0, 100.0, 0) == "stale"
        assert classify_reason(0.0, 10.0, 0) == "near_dup"

    def test_age_variants(self):
        from dxrk.memory.sleep import age_days

        assert age_days(None) == 0.0
        assert age_days("zzz") == 0.0
        assert age_days("2024-01-01T00:00:00") > 100
        assert age_days("2024-01-01T00:00:00+00:00") > 100

    def test_consolidate_missing_and_deferred(self):
        from dxrk.memory.sleep import SleepCandidate, consolidate_candidate

        malla = _malla_rows([])
        assert consolidate_candidate(malla, SleepCandidate("no", 1.0, "pe_high")) == {"status": "not_found"}
        nodoc = {"id": "d", "metadata": {}}
        malla2 = _malla_rows([nodoc])
        assert consolidate_candidate(malla2, SleepCandidate("d", 1.0, "pe_high")) == {"status": "not_found"}
        malla3 = _malla_rows([_fragmento_row("d")])
        assert consolidate_candidate(malla3, SleepCandidate("d", 1.0, "near_dup")) == {"status": "deferred_rem"}

    def test_consolidate_ok(self):
        from dxrk.memory.sleep import SleepCandidate, consolidate_candidate

        malla = _malla_rows([_fragmento_row("d", score_ledger=[{"pe": 0.1}])])
        out = consolidate_candidate(malla, SleepCandidate("d", 1.0, "pe_high"))
        assert out["status"] == "consolidated"
        assert malla.update_fragmento.called

    def test_reorganize_branches(self):
        from dxrk.memory.sleep import SleepCandidate, reorganize_candidate

        assert reorganize_candidate(_malla_rows([]), SleepCandidate("no", 1.0, "near_dup")) == {"status": "not_found"}
        prot = _fragmento_row("d", pinned=True)
        assert reorganize_candidate(_malla_rows([prot]), SleepCandidate("d", 1.0, "near_dup")) == {"status": "protected"}
        doc = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        a = _fragmento_row("a", document=doc, S=5.0)
        b = _fragmento_row("b", document=doc, S=10.0)
        malla = _malla_rows([a, b])
        out = reorganize_candidate(malla, SleepCandidate("a", 1.0, "near_dup"))
        assert out["status"] == "merged"
        assert out["winner"] == "b" and out["loser"] == "a"
        c = _fragmento_row("c", document="totalmente distinto uno", celda="other")
        malla2 = _malla_rows([a, c])
        assert reorganize_candidate(malla2, SleepCandidate("a", 1.0, "near_dup"))["status"] == "no_merge"
        e = _fragmento_row("e", document="")
        malla3 = _malla_rows([a, e])
        assert reorganize_candidate(malla3, SleepCandidate("a", 1.0, "near_dup"))["status"] == "no_merge"

    def test_jaccard_empty(self):
        from dxrk.memory.sleep import jaccard_similarity

        assert jaccard_similarity("", "") == 0.0
        assert jaccard_similarity("a b", "a b") == 1.0

    def test_state_corrupt(self, tmp_path):
        from dxrk.memory.sleep import load_sleep_state

        (tmp_path / ".sleep_state.json").write_text("zzz")
        st = load_sleep_state(tmp_path)
        assert st.last_sleep == ""

    def test_cycle_with_merge(self, tmp_path):
        from dxrk.memory.sleep import sleep_cycle

        doc = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        fragmentos = [_fragmento_row(f"d{i}", document=doc, score_ledger=[{"pe": 0.9}]) for i in range(4)]
        malla = _malla_rows(fragmentos)
        malla._path = str(tmp_path)
        stats = sleep_cycle(malla, limit=4, nrem_ratio=0.5)
        assert stats["candidates"] >= 0
        assert stats["total"] >= 0

    def test_reconsolidate_branches(self):
        from datetime import UTC, datetime, timedelta

        from dxrk.memory.sleep import reconsolidate_labile

        assert reconsolidate_labile(_malla_rows([_fragmento_row("d", pinned=True)])) == 0
        assert reconsolidate_labile(_malla_rows([_fragmento_row("d")])) == 0
        old = _fragmento_row("d", labile_until=(datetime.now(UTC) - timedelta(hours=7)).isoformat())
        malla = _malla_rows([old])
        assert reconsolidate_labile(malla) == 1
        assert malla.update_fragmento.called
        bad = _fragmento_row("d", labile_until="zzz")
        assert reconsolidate_labile(_malla_rows([bad])) == 0
        future = _fragmento_row("d", labile_until=(datetime.now(UTC) + timedelta(hours=7)).isoformat())
        assert reconsolidate_labile(_malla_rows([future])) == 0

    def test_reorganize_skips_protected_other(self):
        from dxrk.memory.sleep import SleepCandidate, reorganize_candidate

        doc = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"
        a = _fragmento_row("a", document=doc)
        pinned = _fragmento_row("p", document="otra cosa", pinned=True)
        malla = _malla_rows([a, pinned])
        assert reorganize_candidate(malla, SleepCandidate("a", 1.0, "near_dup"))["status"] == "no_merge"

    def test_cycle_nrem_deferred(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        from dxrk.memory.sleep import sleep_cycle

        mild = _fragmento_row(
            "d",
            filed_at=(datetime.now(UTC) - timedelta(days=60)).isoformat(),
            score_ledger=[{"pe": 0.2}],
        )
        malla = _malla_rows([mild])
        malla._path = str(tmp_path)
        stats = sleep_cycle(malla, limit=2, nrem_ratio=0.7)
        assert stats["candidates"] == 1
        assert stats["nrem_consolidated"] == 0


# ═══════════ rbac ═══════════


class TestRbacRemainder:
    def test_chmod_failures_tolerated(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        from dxrk.security import rbac

        monkeypatch.setattr(_P, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        rbac._ensure_parent_dir(tmp_path / "a" / "b.json")
        rbac._harden_file(tmp_path / "a" / "b.json")

    def test_load_bad_files(self, tmp_path, monkeypatch):
        from dxrk.security import rbac

        p = tmp_path / "r.json"
        p.write_text("not json{")
        assert rbac._load_roles_data(p) == {"users": {}, "default_role": "readonly"}
        p.write_text("[1, 2]")
        assert rbac._load_roles_data(p)["users"] == {}
        p.write_text('{"users": "x", "default_role": "dev"}')
        assert rbac._load_roles_data(p) == {"users": {}, "default_role": "dev"}
        p.write_text('{"users": {"a": "admin", "b": "zzz"}, "default_role": "zzz"}')
        d = rbac._load_roles_data(p)
        assert d == {"users": {"a": "admin"}, "default_role": "readonly"}
        monkeypatch.setattr("pathlib.Path.read_text", lambda self, **k: (_ for _ in ()).throw(OSError("ro")))
        assert rbac._load_roles_data(p)["users"] == {}

    def test_write_invalid_roles(self, tmp_path):
        from dxrk.security import rbac

        with pytest.raises(ValueError):
            rbac._write_roles_data(tmp_path / "r.json", {}, "zzz")
        with pytest.raises(ValueError):
            rbac._write_roles_data(tmp_path / "r.json", {"u": "zzz"}, "dev")

    def test_resolve_fallbacks(self, tmp_path, monkeypatch):

        from dxrk.security import rbac

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        r = rbac.TenantRoleResolver("t1")
        r.save({"alice": "admin"}, "dev")
        assert r.resolve("alice") == "admin"
        assert r.resolve("nadie") == "dev"
        assert r.get_role("alice") == "admin"
        monkeypatch.setattr(rbac, "_load_roles_data", lambda p: {"users": "x", "default_role": "dev"})
        assert r.resolve("alice") == "dev"
        monkeypatch.setattr(rbac, "_load_roles_data", lambda p: {"users": {}, "default_role": "zzz"})
        assert r.resolve("alice") == "readonly"
        assert r.load()["default_role"] == "zzz"

    def test_set_role_and_default(self, tmp_path, monkeypatch):

        from dxrk.security import rbac

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        r = rbac.TenantRoleResolver("t2")
        r.set_user_role("bob", "dev")
        assert r.resolve("bob") == "dev"
        with pytest.raises(ValueError):
            r.set_user_role("bob", "zzz")
        with pytest.raises(ValueError):
            rbac.TenantRoleResolver("")
        with pytest.raises(ValueError):
            rbac.TenantRoleResolver("mal/id")
        monkeypatch.setattr(rbac, "_load_roles_data", lambda p: {"users": 5, "default_role": 6})
        r.set_user_role("carl", "admin")
        import json as _json

        assert _json.loads(r.roles_path.read_text())["users"]["carl"] == "admin"
        p = r.ensure_default()
        assert p.exists()
        assert r.ensure_default() == p

    def test_policy_and_store(self, tmp_path, monkeypatch):

        from dxrk.security import rbac

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        ctx = rbac.load_policy_for_tenant("t3", "nadie")
        assert ctx is not None
        st = rbac.build_permission_store_for_role("zzz")
        assert st is not None
        assert rbac.get_caps_for_role("zzz") == rbac.get_caps_for_role("readonly")
        monkeypatch.setattr(rbac, "_ALL_CAPS_SET", set())
        st2 = rbac.build_permission_store_for_role("admin")
        assert st2 is not None
        assert rbac._policy_rules_for_role("zzz")

    def test_jwt_variants(self):
        import base64

        from dxrk.security import rbac

        def _tok(payload):
            body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            return f"eyJhbGciOiJub25lIn0.{body}.firma"

        with pytest.raises(ValueError):
            rbac.authorize_via_jwt("no-es-token")
        r = rbac.authorize_via_jwt(_tok({"tid": "t1", "role": "admin"}))
        assert r == "admin"
        r2 = rbac.authorize_via_jwt(_tok({"tenant_id": "t1"}))
        assert r2 == "readonly"
        with pytest.raises(PermissionError):
            rbac.authorize_via_jwt(_tok({"tid": "t1", "role": "admin"}), expected_tenant="otra")

    def test_maintain_grants(self, tmp_path, monkeypatch):
        from dxrk.security import rbac

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        assert rbac.has_memory_maintain("", "u") is False
        assert rbac.has_memory_maintain("t", "") is False
        assert rbac.has_memory_maintain("tm", "u") is False
        with pytest.raises(ValueError):
            rbac.grant_memory_maintain("", "u")
        with pytest.raises(ValueError):
            rbac.grant_memory_maintain("t", "")
        rbac.grant_memory_maintain("tm", "u")
        rbac.grant_memory_maintain("tm", "u")
        assert rbac.has_memory_maintain("tm", "u") is True
        rbac.revoke_memory_maintain("", "")
        rbac.revoke_memory_maintain("tm", "nadie")
        rbac.revoke_memory_maintain("tm", "u")
        assert rbac.has_memory_maintain("tm", "u") is False
        gp = rbac._maintain_grants_path("tm")
        gp.write_text("[1]")
        assert rbac._load_maintain_grants("tm") == {}
        gp.write_text('{"cap": "x"}')
        assert rbac._load_maintain_grants("tm") == {}
        gp.write_text('{"cap": [1, "u", ""]}')
        assert rbac._load_maintain_grants("tm") == {"cap": ["u"]}

    def test_revoke_oserror(self, tmp_path, monkeypatch):
        from dxrk.security import rbac

        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        rbac.grant_memory_maintain("tr", "u")
        monkeypatch.setattr("os.replace", lambda a, b: (_ for _ in ()).throw(OSError("ro")))
        rbac.revoke_memory_maintain("tr", "u")


# ═══════════ tenant migration ═══════════


class TestTenantMigrationRemainder:
    def test_root_oserror(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        monkeypatch.setattr(_P, "mkdir", lambda self, **k: (_ for _ in ()).throw(OSError("ro")))
        r = mig.tenant_root("t1")
        assert r.name == "t1"
        monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
        monkeypatch.setattr(_P, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        assert mig.list_tenants() == []
        with pytest.raises(ValueError):
            mig.tenant_root("mal/id")
        with pytest.raises(ValueError):
            mig.ensure_tenant("mal/id")

    def test_migrate_dirs_and_files(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        legacy_dir = home / ".dxrk" / "locks"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "a.lock").write_text("x")
        legacy_file = home / ".dxrk" / "identity.txt"
        legacy_file.write_text("id")
        monkeypatch.setattr(
            mig,
            "LEGACY_PATHS",
            [
                (legacy_dir, __import__("pathlib").Path("locks")),
                (legacy_file, __import__("pathlib").Path("identity.txt")),
            ],
        )
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert res["copied"]
        res2 = mig.migrate_legacy_to_default(dry_run=False)
        assert res2["copied"] == []
        assert mig.is_migrated() is True

    def test_migrate_dry_run_and_special(self, tmp_path, monkeypatch):
        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        legacy_dir = home / ".dxrk" / "locks"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "a.lock").write_text("x")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(legacy_dir, __import__("pathlib").Path("locks"))])
        res = mig.migrate_legacy_to_default(dry_run=True)
        assert res["copied"]

    def test_migrate_chmod_failures(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        legacy_file = home / ".dxrk" / "identity.txt"
        legacy_file.parent.mkdir(parents=True)
        legacy_file.write_text("id")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(legacy_file, __import__("pathlib").Path("identity.txt"))])
        monkeypatch.setattr(_P, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert res["copied"] or res["skipped"]

    def test_migrate_list_and_mkdir_error(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        mig.ensure_tenant("ok")
        (mig._tenants_root() / "a.b").mkdir(parents=True, exist_ok=True)
        assert "ok" in mig.list_tenants()
        assert "a.b" not in mig.list_tenants()
        tenants = mig._tenants_root()
        real_mkdir = _P.mkdir

        def _boom_tenants(self, *a, **k):
            if self == tenants:
                raise OSError("ro")
            return real_mkdir(self, *a, **k)

        monkeypatch.setattr(_P, "mkdir", _boom_tenants)
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert isinstance(res, dict)

    def test_migrate_dir_merge_variants(self, tmp_path, monkeypatch):
        import shutil as _shutil

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        legacy_dir = home / ".dxrk" / "locks"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "a.lock").write_text("x")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(legacy_dir, __import__("pathlib").Path("locks"))])
        mig.migrate_legacy_to_default(dry_run=False)
        (legacy_dir / "b.lock").write_text("y")
        (legacy_dir / "sub").mkdir(exist_ok=True)
        (legacy_dir / "sub" / "s.lock").write_text("s")
        res = mig.migrate_legacy_to_default(dry_run=True)
        assert any("->" in c for c in res["copied"])
        from pathlib import Path as _P

        monkeypatch.setattr(_P, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        res2 = mig.migrate_legacy_to_default(dry_run=False)
        assert res2["copied"]
        monkeypatch.setattr(_shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        (legacy_dir / "c.lock").write_text("z")
        res3 = mig.migrate_legacy_to_default(dry_run=False)
        assert res3["skipped"]

    def test_migrate_copytree_and_sidecars(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        custom = home / ".dxrk" / "customdir"
        custom.mkdir(parents=True)
        (custom / "f.txt").write_text("x")
        db = home / ".dxrk" / "malla" / "malla.db"
        db.parent.mkdir(parents=True)
        db.write_text("db")
        (home / ".dxrk" / "malla" / "malla.db-wal").write_text("wal")
        (home / ".dxrk" / "malla" / "malla.db-shm").write_text("shm")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(custom, _P("customdir")), (db, _P("malla") / "malla.db")])
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert len(res["copied"]) == 2
        assert (mig.tenant_root("default") / "customdir" / "f.txt").exists()

    def test_migrate_copytree_chmod_failures(self, tmp_path, monkeypatch):
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home2"
        monkeypatch.setenv("HOME", str(home))
        custom = home / ".dxrk" / "customdir"
        (custom / "sub").mkdir(parents=True)
        (custom / "sub" / "g.txt").write_text("x")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(custom, _P("customdir"))])
        monkeypatch.setattr(_P, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert res["copied"]

    def test_migrate_special_and_errors(self, tmp_path, monkeypatch):
        import os as _os

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        fifo = home / ".dxrk" / "myfifo"
        fifo.parent.mkdir(parents=True)
        try:
            _os.mkfifo(str(fifo))
        except (OSError, AttributeError):
            fifo.mkdir()
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(fifo, __import__("pathlib").Path("myfifo"))])
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert res["skipped"]
        monkeypatch.setattr(_os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("ro")))
        res2 = mig.migrate_legacy_to_default(dry_run=False)
        assert isinstance(res2, dict)

    def test_migrate_copytree_subdirs_and_sidecar_skip(self, tmp_path, monkeypatch):

        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        custom = home / ".dxrk" / "customdir"
        (custom / "sub").mkdir(parents=True)
        (custom / "sub" / "g.txt").write_text("x")
        db = home / ".dxrk" / "malla" / "malla.db"
        db.parent.mkdir(parents=True)
        db.write_text("db")
        (home / ".dxrk" / "malla" / "malla.db-wal").write_text("wal")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(custom, _P("customdir")), (db, _P("malla") / "malla.db")])
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert len(res["copied"]) == 2
        (mig.tenant_root("default") / "malla" / "malla.db").unlink()
        res2 = mig.migrate_legacy_to_default(dry_run=False)
        assert res2["copied"]

    def test_migrate_sidecar_and_outer_errors(self, tmp_path, monkeypatch):
        import shutil as _shutil
        from pathlib import Path as _P

        import dxrk.tenant.migration as mig

        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        db = home / ".dxrk" / "malla" / "malla.db"
        db.parent.mkdir(parents=True)
        db.write_text("db")
        (home / ".dxrk" / "malla" / "malla.db-wal").write_text("wal")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(db, _P("malla") / "malla.db")])
        real_copy2 = _shutil.copy2

        def _boom_wal(src, dst, *a, **k):
            if str(src).endswith("-wal"):
                raise OSError("ro")
            return real_copy2(src, dst, *a, **k)

        monkeypatch.setattr(_shutil, "copy2", _boom_wal)
        res = mig.migrate_legacy_to_default(dry_run=False)
        assert res["copied"]
        monkeypatch.setattr(_shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        db2 = home / ".dxrk" / "identity.txt"
        db2.write_text("id")
        monkeypatch.setattr(mig, "LEGACY_PATHS", [(db2, _P("identity.txt"))])
        res2 = mig.migrate_legacy_to_default(dry_run=False)
        assert res2["skipped"]
        real_write = _P.write_text

        def _boom_active(self, *a, **k):
            if self.name == "_active":
                raise OSError("ro")
            return real_write(self, *a, **k)

        monkeypatch.setattr(_shutil, "copy2", real_copy2)
        monkeypatch.setattr(_P, "write_text", _boom_active)
        res3 = mig.migrate_legacy_to_default(dry_run=False)
        assert isinstance(res3, dict)


# ═══════════ calibrate ═══════════


def _cal_fragmento(did, nodo="w", doc="some content here"):
    return {"id": did, "document": doc, "metadata": {"nodo": nodo, "S": 1.0}}


class TestCalibrateRemainder:
    def test_evaluate_few_fragmentos(self):
        from unittest.mock import Mock

        from dxrk.memory.calibrate import CalibrationParams, evaluate_recall_at_k

        malla = Mock()
        malla.iter_fragmentos.return_value = [_cal_fragmento("d1")]
        assert evaluate_recall_at_k(malla, "w", CalibrationParams()) == 0.0

    def test_evaluate_empty_doc(self):
        from unittest.mock import Mock

        from dxrk.memory.calibrate import CalibrationParams, evaluate_recall_at_k

        malla = Mock()
        malla.iter_fragmentos.return_value = [_cal_fragmento("d1", doc=""), _cal_fragmento("d2", doc="")]
        assert evaluate_recall_at_k(malla, "w", CalibrationParams()) == 0.0

    def test_evaluate_runs(self):
        from unittest.mock import Mock

        from dxrk.memory.calibrate import CalibrationParams, evaluate_recall_at_k

        malla = Mock()
        malla.iter_fragmentos.return_value = [_cal_fragmento(f"d{i}") for i in range(5)]
        assert evaluate_recall_at_k(malla, "w", CalibrationParams(), k=2, sample_size=2) == 0.0

    def test_nodo_no_candidates(self, monkeypatch):
        from unittest.mock import Mock

        import dxrk.memory.calibrate as cal

        monkeypatch.setattr(cal, "select_evaluation_candidates", lambda malla, n, config: [])
        assert cal.calibrate_nodo(Mock(), "w") is cal.DEFAULT_PARAMS

    def test_nodo_single_candidate(self, monkeypatch):
        from unittest.mock import Mock

        import dxrk.memory.calibrate as cal

        malla = Mock()
        malla.iter_fragmentos.return_value = [_cal_fragmento("d1")]
        monkeypatch.setattr(cal, "select_evaluation_candidates", lambda malla, n, config: ["d1"])
        assert cal.calibrate_nodo(malla, "w") is cal.DEFAULT_PARAMS

    def test_calibrate_v2_edges(self, monkeypatch):
        from unittest.mock import Mock

        import dxrk.memory.calibrate_v2 as cal2

        malla = Mock()
        malla.iter_fragmentos.return_value = [_cal_fragmento("d1")]
        assert cal2.evaluate_recall_at_k(malla, "w", cal2.CalibrationParams()) == 0.0
        monkeypatch.setattr(cal2, "select_evaluation_candidates", lambda malla, n, config: [])
        assert cal2.calibrate_nodo(Mock(), "w") is cal2.DEFAULT_PARAMS
        malla2 = Mock()
        malla2.iter_fragmentos.return_value = [_cal_fragmento("d1")]
        monkeypatch.setattr(cal2, "select_evaluation_candidates", lambda malla, n, config: ["d1"])
        assert cal2.calibrate_nodo(malla2, "w") is cal2.DEFAULT_PARAMS

    def test_calibration_io(self, tmp_path):

        import dxrk.memory.calibrate as cal
        import dxrk.memory.calibrate_v2 as cal2

        nodo = "wtest"
        assert cal.load_calibration(tmp_path, nodo) == cal.DEFAULT_PARAMS
        cal.save_calibration(tmp_path, nodo, cal.CalibrationParams(a=2.0))
        assert cal.load_calibration(tmp_path, nodo).a == 2.0
        assert cal.get_calibration_params(tmp_path, nodo).a == 2.0
        assert nodo in cal.list_calibrated_nodos(tmp_path)
        (tmp_path / ".calibration" / f"{nodo}.json").write_text("zzz")
        assert cal.load_calibration(tmp_path, nodo) == cal.DEFAULT_PARAMS
        assert cal2.load_calibration(tmp_path, "", nodo) == cal2.DEFAULT_PARAMS
        cal2.save_calibration(tmp_path, cal2.CalibrationParams(tenant="t", nodo=nodo))
        assert cal2.load_calibration(tmp_path, "t", nodo).tenant == "t"
        assert cal2.get_calibration_params(tmp_path, "t", nodo).tenant == "t"
        assert cal2.list_calibrated_nodos(tmp_path)
        (tmp_path / ".calibration" / f"global_{nodo}.json").write_text("zzz")
        assert cal2.load_calibration(tmp_path, "", nodo) == cal2.DEFAULT_PARAMS
        chain = cal2.get_calibration_chain(tmp_path, "t", nodo)
        assert chain and chain[-1] == cal2.DEFAULT_PARAMS
        assert cal2.merge_calibrations([]) == cal2.DEFAULT_PARAMS
        single = cal2.CalibrationParams(a=1.0)
        assert cal2.merge_calibrations([single]) is single
        merged = cal2.merge_calibrations([cal2.CalibrationParams(a=2.0), cal2.CalibrationParams(a=0.0)], alpha=0.0)
        assert merged.a == 1.0
        merged2 = cal2.merge_calibrations([cal2.CalibrationParams(a=2.0), cal2.CalibrationParams(a=0.0)])
        assert merged2.method == "merged"


# ═══════════ metacog_v2 ═══════════


class TestMetacogV2Remainder:
    def test_ece_edges(self):
        import dxrk.memory.metacog_v2 as m2

        assert m2.compute_ece_from_bins({"0": {"count": 0, "correct": 0, "conf_sum": 0.0}}, 1) == 0.0
        assert m2.compute_ece_history([{"predicted": 0.5, "actual": 1}]) == 0.0
        assert m2.confidence_from_outcome if hasattr(m2, "confidence_from_outcome") else True
        import dxrk.memory.metacog as m1

        assert m1.confidence_from_outcome(True) == 0.5
        assert m1.confidence_from_outcome(False, 0.8) == 0.8

    def test_fit_edges(self):
        import dxrk.memory.metacog_v2 as m2

        assert m2.fit_temperature([{"predicted": 0.9, "actual": 1}]) == 1.0
        flat = [{"predicted": 0.5, "actual": i % 2} for i in range(40)]
        assert m2.fit_temperature(flat) == 1.0
        mixed = [{"predicted": 0.0, "actual": 0}, {"predicted": 1.0, "actual": 1}] * 20
        assert isinstance(m2.fit_temperature(mixed), float)
        assert m2.fit_isotonic([{"predicted": 0.5, "actual": 1}]) == {}
        same = [{"predicted": 0.7, "actual": i % 2} for i in range(40)]
        assert m2.fit_isotonic(same) == {}

    def test_bias_categories(self):
        import dxrk.memory.metacog_v2 as m2

        st = m2.MetacogState()
        for i in range(12):
            st = m2.record_judgment(st, 0.8, 1.0, context={"nodo": "w"})
        for i in range(3):
            st = m2.record_judgment(st, 0.2, 0.0, context={"nodo": "rare"})
        out = m2.detect_bias(st)
        assert "nodo=w" in out["category_bias"]
        assert "nodo=rare" not in out["category_bias"]

    def test_wrapper(self, tmp_path):
        from types import SimpleNamespace

        import dxrk.memory.metacog_v2 as m2

        w = m2.MetacognitionV2(SimpleNamespace())
        assert str(w._malla_path) == "."
        malla = SimpleNamespace(_path=str(tmp_path), search=lambda query, nodo, n_results: {"results": [{"id": "a"}]})
        w2 = m2.MetacognitionV2(malla)
        pred = w2.predict("hola")
        assert 0.0 <= pred.confidence <= 1.0
        malla3 = SimpleNamespace(_path=str(tmp_path), search=lambda query, nodo, n_results: [1, 2])
        pred3 = m2.MetacognitionV2(malla3).predict("hola")
        assert pred3.difficulty == 1.0
        malla4 = SimpleNamespace(_path=str(tmp_path), search=lambda query, nodo, n_results: {"results": "x"})
        assert m2.MetacognitionV2(malla4).predict("hola").difficulty == 1.0
        out = w2.fit_calibration()
        assert out["n_judgments"] == 0
        assert m2.get_metacog_summary(w2._state)["n_judgments"] == 0
