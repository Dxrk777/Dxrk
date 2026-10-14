# SPDX-License-Identifier: MIT
"""Cobertura 100% final — tenant_switcher + agentbuilder + mcp_server.

Sin pragma, sin relleno: cada test ejercita ramas reales.
"""

from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _iso_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("DXRK_TENANT", raising=False)
    monkeypatch.delenv("DXRK_USER", raising=False)
    monkeypatch.delenv("DXRK_MEMORY_PATH", raising=False)
    monkeypatch.delenv("DXRK_PROJECT_DIR", raising=False)
    return home


CANNED = """# Demo Skill

## Description
Does demo things for testing purposes.

## Trigger
When the user asks to "demo".

## Instructions
1. Do demo.
2. Save via mem_save.

## Rules
- Always demo.

## Examples
User: "demo"
Agent: demos.
"""


# ===========================================================================
# agentbuilder
# ===========================================================================


class TestAgentBuilderCov100:
    def test_registry_find_miss_and_remove(self) -> None:
        from dxrk import agentbuilder as ab

        reg = ab.Registry(Version=1)
        assert reg.find_by_name("nope") is None
        assert reg.remove_by_name("nope") is False
        e = ab.RegistryEntry(Name="a", Title="A", Description="d")
        reg.add(e)
        assert reg.find_by_name("a") is e
        other = ab.RegistryEntry(Name="b", Title="B", Description="db")
        reg.add(other)
        assert reg.remove_by_name("b") is True
        assert reg.find_by_name("b") is None
        assert reg.remove_by_name("a") is True
        assert reg.find_by_name("a") is None
        assert reg.remove_by_name("a") is False

    def test_install_error_carries_results(self) -> None:
        from dxrk import agentbuilder as ab

        r = ab.InstallResult(Success=True)
        err = ab.InstallError("boom", [r])
        assert str(err) == "boom"
        assert err.results == [r]
        assert isinstance(ab.GenerationError("x"), Exception)
        assert isinstance(ab.SDDInjectError("y"), Exception)

    def test_agent_id_str_both(self) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode

        assert ab._agent_id_str(AgentClaudeCode) == AgentClaudeCode.value
        assert ab._agent_id_str("plain") == "plain"  # type: ignore[arg-type]

    def test_compose_prompt_variants(self) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode

        p0 = ab.compose_prompt("hola", None, [])
        assert "hola" in p0 and "Installed Agents" not in p0 and "SDD Integration" not in p0
        p1 = ab.compose_prompt("hola", None, [AgentClaudeCode])
        assert "Installed Agents Context" in p1 and AgentClaudeCode.value in p1
        cfg_s = ab.SDDIntegration(Mode=ab.SDDStandalone)
        p2 = ab.compose_prompt("hola", cfg_s, [])
        assert "SDD Integration" not in p2
        cfg_p = ab.SDDIntegration(Mode=ab.SDDPhaseSupport, TargetPhase="spec")
        p3 = ab.compose_prompt("hola", cfg_p, [])
        assert "sdd-spec" in p3
        cfg_n = ab.SDDIntegration(Mode=ab.SDDNewPhase, PhaseName="review")
        p4 = ab.compose_prompt("hola", cfg_n, [])
        assert "review" in p4
        assert "orchestrator launches you" in p4
        cfg_o = ab.SDDIntegration(Mode="custom-mode")  # type: ignore[arg-type]
        p5 = ab.compose_prompt("hola", cfg_o, [])
        assert "SDD Integration Context" in p5 and "hola" in p5

    def test_parse_errors(self) -> None:
        from dxrk import agentbuilder as ab

        with pytest.raises(ValueError, match="empty content"):
            ab.parse("")
        with pytest.raises(ValueError, match="empty content"):
            ab.parse("```\n```\n")
        with pytest.raises(ValueError, match="missing '# Title'"):
            ab.parse("## Description\nx\n\n## Trigger\ny\n\n## Instructions\nz\n")
        with pytest.raises(ValueError, match="missing '## Description'"):
            ab.parse("# T\n\n## Trigger\ny\n\n## Instructions\nz\n")
        with pytest.raises(ValueError, match="missing '## Trigger'"):
            ab.parse("# T\n\n## Description\nx\n\n## Instructions\nz\n")
        with pytest.raises(ValueError, match="missing '## Instructions'"):
            ab.parse("# T\n\n## Description\nx\n\n## Trigger\ny\n")
        with pytest.raises(ValueError, match="section is empty"):
            ab.parse("# T\n\n## Description\n\n## Trigger\ny\n\n## Instructions\nz\n")
        with pytest.raises(ValueError, match="no valid name"):
            ab.parse("# !!!\n\n## Description\nx\n\n## Trigger\ny\n\n## Instructions\nz\n")
        ag = ab.parse(CANNED)
        assert ag.Name == "demo-skill"

    def test_strip_fences_variants(self) -> None:
        from dxrk import agentbuilder as ab

        assert ab._strip_code_fences(
            "```markdown\n" + CANNED + "\n```\n"
        ) == CANNED.strip() or CANNED in ab._strip_code_fences("```markdown\n" + CANNED + "\n```\n")
        assert "Demo" in ab._strip_code_fences("   \n```\n" + CANNED + "\n```\n")
        assert ab._strip_code_fences(CANNED) == CANNED
        # close con contenido después no se recorta
        raw = CANNED + "\n```\ntrailing text"
        assert "trailing text" in ab._strip_code_fences(raw)
        # open en medio con contenido previo no se recorta; close final sí (solo whitespace después)
        raw2 = "hello\n```python\ncode\n```\n"
        assert ab._strip_code_fences(raw2) == "hello\n```python\ncode\n"
        # sin close
        assert "hello" in ab._strip_code_fences("```\nhello")

    def test_extract_title_and_section_ok(self) -> None:
        from dxrk import agentbuilder as ab

        assert ab._extract_title(CANNED) == "Demo Skill"
        assert "demo things" in ab._extract_section(CANNED, "Description")

    def test_title_to_name_edges(self) -> None:
        from dxrk import agentbuilder as ab

        assert ab._title_to_name("Hello World") == "hello-world"
        assert ab._title_to_name("  Hello---World!! ") == "hello-world"
        assert ab._title_to_name("!!!") == ""
        assert ab._title_to_name("---abc---") == "abc"
        assert ab._title_to_name("a  b   c") == "a-b-c"
        assert ab._title_to_name("CSS A11y Reviewer") == "css-a11y-reviewer"

    def test_new_engine_all(self) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode, AgentCodex, AgentGeminiCLI, AgentOpenCode

        assert isinstance(ab.new_engine(AgentClaudeCode), ab.ClaudeEngine)
        assert isinstance(ab.new_engine(AgentOpenCode), ab.OpenCodeEngine)
        assert isinstance(ab.new_engine(AgentGeminiCLI), ab.GeminiEngine)
        assert isinstance(ab.new_engine(AgentCodex), ab.CodexEngine)
        assert ab.new_engine("unknown-agent") is None  # type: ignore[arg-type]

    def test_base_engine_raises(self) -> None:
        from dxrk import agentbuilder as ab

        base = ab.GenerationEngine()
        with pytest.raises(NotImplementedError):
            base.agent()
        with pytest.raises(NotImplementedError):
            base.generate("x")
        with pytest.raises(NotImplementedError):
            base.available()

    def test_run_cli_branches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk import agentbuilder as ab

        monkeypatch.setattr(
            ab.subprocess,
            "run",
            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("nope")),
        )
        with pytest.raises(ab.GenerationError, match="binary not found"):
            ab._run_cli("nope", [], "p", "demo")
        monkeypatch.setattr(
            ab.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=3, stderr="bad", stdout=""),
        )
        with pytest.raises(ab.GenerationError, match="exit status 3"):
            ab._run_cli("x", [], "p", "demo")
        monkeypatch.setattr(
            ab.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout="out-text"),
        )
        assert ab._run_cli("x", [], "p", "demo") == "out-text"

    def test_engines_available_and_generate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode, AgentCodex, AgentGeminiCLI, AgentOpenCode

        monkeypatch.setattr(ab.shutil, "which", lambda name: "/usr/bin/" + name)
        assert ab.ClaudeEngine().available() is True
        assert ab.OpenCodeEngine().available() is True
        assert ab.GeminiEngine().available() is True
        assert ab.CodexEngine().available() is True
        assert ab.ClaudeEngine().agent() == AgentClaudeCode
        assert ab.OpenCodeEngine().agent() == AgentOpenCode
        assert ab.GeminiEngine().agent() == AgentGeminiCLI
        assert ab.CodexEngine().agent() == AgentCodex
        monkeypatch.setattr(ab.shutil, "which", lambda name: None)
        assert ab.ClaudeEngine().available() is False
        assert ab.OpenCodeEngine().available() is False
        calls: list[tuple[str, list[str], str, str]] = []

        def fake_run(exe: str, args: list[str], prompt: str, name: str) -> str:
            calls.append((exe, args, prompt, name))
            return "gen:" + prompt

        monkeypatch.setattr(ab, "_run_cli", fake_run)
        assert ab.ClaudeEngine().generate("p") == "gen:p"
        assert ab.OpenCodeEngine().generate("p") == "gen:p"
        assert ab.GeminiEngine().generate("p") == "gen:p"
        assert ab.CodexEngine().generate("p") == "gen:p"
        assert calls[0][0] != "" and calls[1][0] == "opencode"

    def test_mock_engine(self) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode

        m = ab.MockEngine(AgentIDVal=AgentClaudeCode, Output="hi", IsAvailable=True)
        assert m.agent() == AgentClaudeCode
        assert m.available() is True
        assert m.generate("p") == "hi"
        m2 = ab.MockEngine(AgentIDVal=AgentClaudeCode, Err=RuntimeError("bad"))
        with pytest.raises(RuntimeError, match="bad"):
            m2.generate("p")
        assert ab.MockEngine(AgentIDVal=AgentClaudeCode).available() is False

    def test_install_none_and_success(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab

        with pytest.raises(ValueError, match="must not be nil"):
            ab.install(None, [])
        ag = ab.parse(CANNED)
        d = tmp_path / "skills"
        d.mkdir()
        res = ab.install(ag, [ab.AdapterInfo(AgentID="a", SkillsDir=str(d))])  # type: ignore[arg-type]
        assert len(res) == 1 and res[0].Success is True
        assert (d / ag.Name / "SKILL.md").exists()
        assert ab.install(ag, []) == []

    def test_install_makedirs_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk import agentbuilder as ab

        ag = ab.parse(CANNED)
        ok_dir = tmp_path / "ok"
        ok_dir.mkdir()
        bad = ab.AdapterInfo(AgentID="bad", SkillsDir=str(tmp_path / "bad"))

        def boom_makedirs(*a: Any, **k: Any) -> None:
            raise OSError("mkdir boom")

        orig_makedirs = os.makedirs
        monkeypatch.setattr(ab.os, "makedirs", boom_makedirs)
        with pytest.raises(ab.InstallError, match="create directory"):
            ab.install(ag, [bad])
        # rollback con éxito parcial: primer adapter ok, segundo falla en write
        monkeypatch.setattr(ab.os, "makedirs", orig_makedirs)
        real_open = open

        def boom_write(path: str, *a: Any, **k: Any) -> Any:
            if str(path).endswith("SKILL.md") and "second" in str(path):
                raise OSError("write boom")
            return real_open(path, *a, **k)

        import builtins

        first = tmp_path / "first"
        second = tmp_path / "second"
        monkeypatch.setattr(builtins, "open", boom_write)
        adapters = [
            ab.AdapterInfo(AgentID="one", SkillsDir=str(first)),  # type: ignore[arg-type]
            ab.AdapterInfo(AgentID="two", SkillsDir=str(second)),  # type: ignore[arg-type]
        ]
        # renombrar second para que el matcher "second" aplique al path
        adapters[1] = ab.AdapterInfo(AgentID="two", SkillsDir=str(tmp_path / "second"))  # type: ignore[arg-type]
        with pytest.raises(ab.InstallError, match="write"):
            ab.install(ag, adapters)
        # el primer archivo se rollbackeó
        assert not (first / ag.Name / "SKILL.md").exists()

    def test_rollback_and_mark_failed(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab

        missing = str(tmp_path / "nope.txt")
        ab._rollback([missing])  # no raise
        f = tmp_path / "f.txt"
        f.write_text("x")
        ab._rollback([str(f)])
        assert not f.exists()
        rs = [ab.InstallResult(Success=True), ab.InstallResult(Success=True)]
        ab._mark_all_failed(rs)
        assert all(r.Success is False for r in rs)
        ab._mark_all_failed([])

    def test_inject_early_and_errors(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab

        p = tmp_path / "sp.md"
        p.write_text("hello")
        ab.inject_sdd_reference(None, str(p))
        assert p.read_text() == "hello"
        ag = ab.parse(CANNED)
        ag.SDDConfig = None
        ab.inject_sdd_reference(ag, str(p))
        assert p.read_text() == "hello"
        ag.SDDConfig = ab.SDDIntegration(Mode=ab.SDDStandalone)
        ab.inject_sdd_reference(ag, str(p))
        assert p.read_text() == "hello"
        with pytest.raises(ab.SDDInjectError, match="read"):
            bad = ab.parse(CANNED)
            bad.SDDConfig = ab.SDDIntegration(Mode=ab.SDDPhaseSupport, TargetPhase="spec")
            ab.inject_sdd_reference(bad, str(tmp_path / "missing.md"))

    def test_inject_append_and_replace(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab

        ag = ab.parse(CANNED)
        ag.SDDConfig = ab.SDDIntegration(Mode=ab.SDDPhaseSupport, TargetPhase="spec")
        p = tmp_path / "sp2.md"
        p.write_text("base")
        ab.inject_sdd_reference(ag, str(p))
        txt = p.read_text()
        assert "<!-- dxrk:custom-agent:demo-skill -->" in txt
        assert "sdd-spec" in txt
        # segunda vez reemplaza, no duplica
        ab.inject_sdd_reference(ag, str(p))
        assert p.read_text().count("<!-- dxrk:custom-agent:demo-skill -->") == 1
        # sin newline final
        p2 = tmp_path / "sp3.md"
        p2.write_text("base sin newline")
        ab.inject_sdd_reference(ag, str(p2))
        assert "demo-skill" in p2.read_text()

    def test_inject_write_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk import agentbuilder as ab

        ag = ab.parse(CANNED)
        ag.SDDConfig = ab.SDDIntegration(Mode=ab.SDDNewPhase, PhaseName="review")
        p = tmp_path / "sp.md"
        p.write_text("base\n")
        real_open = open
        import builtins

        def boom(path: str, *a: Any, **k: Any) -> Any:
            if "w" in (a[0] if a else k.get("mode", "")) or k.get("mode") == "w":
                raise OSError("write boom")
            return real_open(path, *a, **k)

        # parcheo fino: solo falla escritura
        def fake_open(path: Any, *a: Any, **k: Any) -> Any:
            mode = a[0] if a else k.get("mode", "r")
            if "w" in str(mode) and str(path) == str(p):
                raise OSError("write boom")
            return real_open(path, *a, **k)

        monkeypatch.setattr(builtins, "open", fake_open)
        with pytest.raises(ab.SDDInjectError, match="write"):
            ab.inject_sdd_reference(ag, str(p))
        assert p.exists()

    def test_build_sdd_block_variants(self) -> None:
        from dxrk import agentbuilder as ab

        ag = ab.parse(CANNED)
        ag.SDDConfig = ab.SDDIntegration(Mode=ab.SDDPhaseSupport, TargetPhase="spec")
        b1 = ab._build_sdd_block(ag, "<!-- dxrk:custom-agent:demo-skill -->")
        assert "Phase Support" in b1 and "sdd-spec" in b1
        ag2 = ab.parse(CANNED)
        ag2.SDDConfig = ab.SDDIntegration(Mode=ab.SDDNewPhase, PhaseName="review")
        b2 = ab._build_sdd_block(ag2, "<!-- dxrk:custom-agent:demo-skill -->")
        assert "New SDD Phase" in b2 and "review" in b2
        ag3 = ab.parse(CANNED)
        ag3.SDDConfig = ab.SDDIntegration(Mode=ab.SDDNewPhase, PhaseName="")
        b3 = ab._build_sdd_block(ag3, "<!-- dxrk:custom-agent:demo-skill -->")
        assert ag3.Name in b3
        ag4 = ab.parse(CANNED)
        ag4.SDDConfig = ab.SDDIntegration(Mode="other")  # type: ignore[arg-type]
        b4 = ab._build_sdd_block(ag4, "<!-- dxrk:custom-agent:demo-skill -->")
        assert "Custom Agent" in b4
        with pytest.raises(ValueError, match="no SDD config"):
            ag5 = ab.parse(CANNED)
            ag5.SDDConfig = None
            ab._build_sdd_block(ag5, "m")

    def test_replace_block_variants(self) -> None:
        from dxrk import agentbuilder as ab

        marker = "<!-- dxrk:custom-agent:demo -->"
        new = marker + "\nNEW<!-- /dxrk:custom-agent:demo -->"
        assert "NEW" in ab._replace_block("hello", marker, new)
        # end_marker ausente y sin newline tras marker
        content = "aaa " + marker
        out = ab._replace_block(content, marker, new)
        assert "NEW" in out and out.startswith("aaa ")
        content2 = "aaa " + marker + " tail"
        out2 = ab._replace_block(content2, marker, new)
        assert "NEW" in out2
        content_nl = "aaa " + marker + "\n tail sin end-marker"
        out_nl = ab._replace_block(content_nl, marker, new)
        assert "NEW" in out_nl and "sin end-marker" in out_nl
        full = "aaa " + marker + " mid <!-- /dxrk:custom-agent:demo --> bbb"
        out3 = ab._replace_block(full, marker, new)
        assert "NEW" in out3 and "mid" not in out3

    def test_extract_name(self) -> None:
        from dxrk import agentbuilder as ab

        assert ab._extract_name("<!-- dxrk:custom-agent:demo -->") == "demo"
        assert ab._extract_name("garbage") == ""
        assert ab._extract_name("<!-- dxrk:custom-agent: -->") == ""

    def test_builtin_conflict(self) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.catalog import mvp_skills

        names = {s.name for s in mvp_skills()}
        assert isinstance(ab._builtin_skills(), set)
        if names:
            one = sorted(names)[0]
            assert ab.has_conflict_with_builtin(one) is True
        assert ab.has_conflict_with_builtin("definitively-not-a-builtin-xyz") is False

    def test_registry_roundtrip(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab

        missing = tmp_path / "no-reg.json"
        reg = ab.load_registry(str(missing))
        assert reg.Version == 1 and reg.Agents == []
        rp = tmp_path / "reg.json"
        reg2 = ab.Registry(Version=1)
        reg2.add(
            ab.RegistryEntry(
                Name="demo-skill",
                Title="Demo Skill",
                Description="d",
                CreatedAt=datetime.now(UTC),
                GenerationEngine="claude",  # type: ignore[arg-type]
                SDDIntegration=ab.SDDIntegration(Mode=ab.SDDPhaseSupport, TargetPhase="spec"),
                InstalledAgents=["claude"],  # type: ignore[list-item]
            )
        )
        reg2.add(ab.RegistryEntry(Name="plain", Title="P", Description="d2"))
        ab.save_registry(str(rp), reg2)
        loaded = ab.load_registry(str(rp))
        assert loaded.Version == 1
        assert loaded.find_by_name("demo-skill") is not None
        assert loaded.find_by_name("demo-skill").SDDIntegration is not None  # type: ignore[union-attr]
        assert loaded.find_by_name("plain") is not None
        d = ab._registry_to_dict(reg2)
        assert d["version"] == 1 and len(d["agents"]) == 2
        r3 = ab._registry_from_dict({"version": 0})
        assert r3.Version == 0 and r3.Agents == []
        r4 = ab._registry_from_dict({})
        assert r4.Version == 0

    def test_entry_dict_with_without_sdd(self) -> None:
        from dxrk import agentbuilder as ab

        e1 = ab.RegistryEntry(Name="n", Title="t", Description="d")
        d1 = ab._entry_to_dict(e1)
        assert "sdd_integration" not in d1
        e2 = ab.RegistryEntry(
            Name="n",
            Title="t",
            Description="d",
            SDDIntegration=ab.SDDIntegration(Mode=ab.SDDStandalone),
        )
        d2 = ab._entry_to_dict(e2)
        assert "sdd_integration" in d2
        back = ab._entry_from_dict(
            {
                "name": "n",
                "title": "t",
                "description": "d",
                "created_at": datetime.now(UTC).isoformat(),
                "generation_engine": "x",
            }
        )
        assert back.SDDIntegration is None and back.InstalledAgents == []
        cfg = ab._sdd_to_dict(ab.SDDIntegration(Mode=ab.SDDStandalone))
        assert "phase_name" not in cfg
        cfg2 = ab._sdd_to_dict(ab.SDDIntegration(Mode=ab.SDDNewPhase, PhaseName="r"))
        assert cfg2["phase_name"] == "r"
        c3 = ab._sdd_from_dict({})
        assert c3.Mode == ab.SDDStandalone
        c4 = ab._sdd_from_dict({"mode": "x", "target_phase": "t", "phase_name": "p"})
        assert c4.PhaseName == "p"

    def test_generation_tmp_dirs(self, tmp_path: Path) -> None:
        from dxrk import agentbuilder as ab
        from dxrk.models import AgentClaudeCode, AgentOpenCode

        prompt = ab.compose_prompt("build demo", None, [AgentClaudeCode])
        eng = ab.MockEngine(AgentIDVal=AgentClaudeCode, Output=CANNED, IsAvailable=True)
        agent = ab.parse(eng.generate(prompt))
        d1 = tmp_path / "c1"
        d2 = tmp_path / "c2"
        d1.mkdir()
        d2.mkdir()
        res = ab.install(
            agent,
            [
                ab.AdapterInfo(AgentID=AgentClaudeCode, SkillsDir=str(d1)),
                ab.AdapterInfo(AgentID=AgentOpenCode, SkillsDir=str(d2)),
            ],
        )
        assert all(r.Success for r in res)
        assert (d1 / agent.Name / "SKILL.md").read_text().startswith("# Demo")


# ===========================================================================
# mcp_server — handlers directos con palacio temporal
# ===========================================================================


def _mk_palace(tmp_path: Path, name: str = "pal") -> Path:
    from dxrk.memory.palace import DxrkMemory

    pal = tmp_path / name
    dm = DxrkMemory(str(pal))
    dm.init()
    dm.add_drawer("default", "general", "contenido base para busquedas de prueba " * 10, "/base.txt", 0)
    try:
        dm.close()
    except Exception:
        pass
    return pal


class TestMcpServerCov100:
    def test_resolve_palace_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import mcp_server as ms

        _iso_home(tmp_path, monkeypatch)
        monkeypatch.delenv("DXRK_MEMORY_PATH", raising=False)
        monkeypatch.setattr(ms, "DEFAULT_PALACE_PATH", "")
        got = ms._resolve_palace(None)
        assert got.endswith(os.path.join(".dxrk", "memory"))
        explicit = tmp_path / "exp"
        assert ms._resolve_palace(str(explicit)) == str(explicit.resolve())

    def test_project_meta_branches(self) -> None:
        from dxrk.memory.mcp_server import _project_meta_for_mcp

        base = {"wing": "w", "_embedding": [1, 2], "other": 1}
        out = _project_meta_for_mcp(base)
        assert "_embedding" not in out and base["_embedding"] == [1, 2]
        out2 = _project_meta_for_mcp({"access_history": [1, 2, 3], "x": 1})
        assert out2["access_history_len"] == 3 and "access_history" not in out2
        out3 = _project_meta_for_mcp({"x": 1})
        assert out3 == {"x": 1}
        ledger = [{"i": i} for i in range(10)]
        out4 = _project_meta_for_mcp({"score_ledger": ledger})
        assert len(out4["score_ledger"]) == 5 and out4["score_ledger_dropped"] == 5
        out5 = _project_meta_for_mcp({"score_ledger": ledger, "score_ledger_dropped": 3})
        assert out5["score_ledger_dropped"] == 8
        out6 = _project_meta_for_mcp({"score_ledger": ledger, "score_ledger_dropped": True})
        assert out6["score_ledger_dropped"] == 5
        out7 = _project_meta_for_mcp({"score_ledger": ledger, "score_ledger_dropped": -2})
        assert out7["score_ledger_dropped"] == 5
        out8 = _project_meta_for_mcp({"score_ledger": [{"i": 1}]})
        assert out8["score_ledger"] == [{"i": 1}]

    def test_get_kg_no_path(self, tmp_path: Path) -> None:
        from dxrk.memory.mcp_server import _get_kg

        kg = _get_kg()
        kg.close()
        kg2 = _get_kg(str(tmp_path / "k.db"))
        kg2.close()

    def test_status_search_mine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_status")
        st = _handle_tool("dxrk_memory_status", {"palace": str(pal)})
        assert st["count"] >= 1 and "palace_path" in st and "merkle_root" in st
        se = _handle_tool(
            "dxrk_memory_search",
            {"palace": str(pal), "query": "contenido base", "wing": "default", "n_results": 2},
        )
        assert "result" in se
        se2 = _handle_tool(
            "dxrk_memory_search",
            {"palace": str(pal), "query": "contenido", "since": "2000-01-01", "before": "2100-01-01"},
        )
        assert "result" in se2
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "f.txt").write_text("minado mcp contenido " * 30)
        mi = _handle_tool("dxrk_memory_mine", {"palace": str(pal), "project_dir": str(proj), "dry_run": True})
        assert "palace_path" in mi
        mi2 = _handle_tool("dxrk_memory_mine", {"palace": str(pal), "project_dir": str(proj)})
        assert mi2.get("drawers_added", 0) >= 1

    def test_add_drawer_importance(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_add")
        r1 = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "texto con importancia " * 5,
                "source_file": "/a.txt",
                "importance": 0.9,
                "supersedes": "old-id",
            },
        )
        assert "drawer_id" in r1
        r2 = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "sin importancia " * 5,
                "source_file": "/b.txt",
                "importance": "no-numero",
            },
        )
        assert "drawer_id" in r2
        r3 = _handle_tool(
            "dxrk_memory_add_drawer",
            {"palace": str(pal), "wing": "w", "room": "r", "content": "normal " * 5, "source_file": "/c.txt"},
        )
        assert "drawer_id" in r3

    def test_get_drawer_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_get")
        added = _handle_tool(
            "dxrk_memory_add_drawer",
            {"palace": str(pal), "wing": "w", "room": "r", "content": "para get drawer " * 8, "source_file": "/g.txt"},
        )
        did = added["drawer_id"]
        got = _handle_tool("dxrk_memory_get_drawer", {"palace": str(pal), "drawer_id": did})
        assert got["drawer"] is not None and got["drawer"]["metadata"]["wing"] == "w"
        missing = _handle_tool("dxrk_memory_get_drawer", {"palace": str(pal), "drawer_id": "no-existe"})
        assert missing["drawer"] is None

    def test_list_drawers_quarantine_doc(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool
        from dxrk.memory.palace import DxrkMemory

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_list")
        dm = DxrkMemory(str(pal))
        dm.init()
        did = dm.add_drawer("w", "r", "para cuarentena lista " * 6, "/q.txt", 0)
        dm.quarantine_drawer(did, reason="test")
        try:
            dm.close()
        except Exception:
            pass
        out = _handle_tool("dxrk_memory_list_drawers", {"palace": str(pal), "limit": 20})
        assert out["count"] >= 1
        out2 = _handle_tool(
            "dxrk_memory_list_drawers",
            {"palace": str(pal), "wing": "w", "room": "r", "limit": 5, "include_quarantined": True},
        )
        assert out2["count"] >= 1
        assert any(d.get("quarantined") for d in out2["drawers"])
        out3 = _handle_tool("dxrk_memory_list_drawers", {"palace": str(pal), "wing": "", "room": ""})
        assert "drawers" in out3

    def test_update_drawer_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_upd")
        nf = _handle_tool("dxrk_memory_update_drawer", {"palace": str(pal), "drawer_id": "missing"})
        assert "not found" in nf.get("error", "")
        added = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w1",
                "room": "r1",
                "content": "actualizable contenido " * 6,
                "source_file": "/u.txt",
            },
        )
        did = added["drawer_id"]
        # sin cambios (mismo contenido) + cambio de wing/room
        same = _handle_tool("dxrk_memory_update_drawer", {"palace": str(pal), "drawer_id": did, "wing": "w2"})
        assert same.get("updated") is True
        ch = _handle_tool(
            "dxrk_memory_update_drawer",
            {"palace": str(pal), "drawer_id": did, "room": "r2", "content": "actualizable contenido revisado " * 6},
        )
        assert ch.get("updated") is True
        got = _handle_tool("dxrk_memory_get_drawer", {"palace": str(pal), "drawer_id": did})
        assert got["drawer"]["metadata"]["wing"] == "w2"
        assert got["drawer"]["metadata"]["room"] == "r2"
        # enforce_wing_cap que falla no rompe el update
        from dxrk.memory.palace import DxrkMemory

        orig = DxrkMemory.enforce_wing_cap
        monkeypatch.setattr(DxrkMemory, "enforce_wing_cap", lambda self, w: (_ for _ in ()).throw(RuntimeError("cap")))
        ok = _handle_tool("dxrk_memory_update_drawer", {"palace": str(pal), "drawer_id": did, "content": "otro " * 6})
        assert ok.get("updated") is True
        monkeypatch.setattr(DxrkMemory, "enforce_wing_cap", orig)

    def test_delete_and_duplicate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_dup")
        _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "el zorro marron salta sobre el perro " * 4,
                "source_file": "/z.txt",
            },
        )
        bad_thr = _handle_tool(
            "dxrk_memory_check_duplicate",
            {"palace": str(pal), "content": "el zorro marron", "threshold": "mal"},
        )
        assert bad_thr["duplicate"] is True
        empty = _handle_tool("dxrk_memory_check_duplicate", {"palace": str(pal), "content": ""})
        assert empty["duplicate"] is False and empty.get("reason") == "empty query"
        dup = _handle_tool(
            "dxrk_memory_check_duplicate",
            {"palace": str(pal), "content": "el zorro marron salta sobre el perro"},
        )
        assert dup["duplicate"] is True
        fresh = _handle_tool(
            "dxrk_memory_check_duplicate",
            {"palace": str(pal), "content": "vortex cuantico cebra totalmente distinto xyz"},
        )
        assert fresh["duplicate"] is False
        added = _handle_tool(
            "dxrk_memory_add_drawer",
            {"palace": str(pal), "wing": "w", "room": "r", "content": "para borrar " * 5, "source_file": "/d.txt"},
        )
        dl = _handle_tool("dxrk_memory_delete_drawer", {"palace": str(pal), "drawer_id": added["drawer_id"]})
        assert dl["deleted"] == added["drawer_id"]

    def test_duplicate_nonlist_hits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import mcp_server as ms
        from dxrk.memory.palace import DxrkMemory

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_dup2")
        monkeypatch.setattr(DxrkMemory, "search", lambda self, *a, **k: {"results": "no-lista"})
        out = ms._handle_tool("dxrk_memory_check_duplicate", {"palace": str(pal), "content": "algo con contenido"})
        assert out["duplicate"] is False
        monkeypatch.setattr(
            DxrkMemory,
            "search",
            lambda self, *a, **k: {"results": [{"text": 123}, {"text": ""}, "no-dict"]},  # type: ignore[dict-item]
        )
        out2 = ms._handle_tool("dxrk_memory_check_duplicate", {"palace": str(pal), "content": "algo con contenido"})
        assert out2["duplicate"] is False

    def test_wings_rooms_taxonomy_graph(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_tax")
        assert "default" in _handle_tool("dxrk_memory_list_wings", {"palace": str(pal)})["wings"]
        rooms = _handle_tool("dxrk_memory_list_rooms", {"palace": str(pal), "wing": "default"})
        assert "general" in rooms["rooms"]
        rooms2 = _handle_tool("dxrk_memory_list_rooms", {"palace": str(pal)})
        assert isinstance(rooms2["rooms"], list)
        rooms3 = _handle_tool("dxrk_memory_list_rooms", {"palace": str(pal), "wing": 123})
        assert isinstance(rooms3["rooms"], list)
        tax = _handle_tool("dxrk_memory_taxonomy", {"palace": str(pal)})
        assert "default" in tax["taxonomy"]
        gs = _handle_tool("dxrk_memory_graph_stats", {"palace": str(pal)})
        assert gs["total_drawers"] >= 1 and gs["wings"] >= 1

    def test_kg_timeline_none_and_traverse(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        kgp = str(tmp_path / "kgcov.db")
        pal = str(tmp_path / "pal_kg")
        assert _handle_tool(
            "dxrk_memory_kg_add", {"subject": "A", "predicate": "knows", "object": "B", "kg_path": kgp}
        )["triple_id"]
        q = _handle_tool("dxrk_memory_kg_query", {"entity": "A", "kg_path": kgp, "direction": "both", "as_of": None})
        assert len(q["results"]) == 1
        tl_none = _handle_tool("dxrk_memory_kg_timeline", {"kg_path": kgp})
        assert "timeline" in tl_none
        tl_e = _handle_tool("dxrk_memory_kg_timeline", {"kg_path": kgp, "entity": "A"})
        assert "timeline" in tl_e
        assert _handle_tool("dxrk_memory_kg_stats", {"kg_path": kgp})["triples"] == 1
        tr = _handle_tool("dxrk_memory_traverse", {"start": "A", "kg_path": kgp, "depth": 2})
        assert tr["start"] == "A"
        assert (
            _handle_tool(
                "dxrk_memory_kg_invalidate", {"subject": "A", "predicate": "knows", "object": "B", "kg_path": kgp}
            )["invalidated"]
            is True
        )
        # kg sin path explícito (memoria)
        assert _handle_tool("dxrk_memory_kg_add", {"subject": "X", "predicate": "y", "object": "Z"})["triple_id"]
        assert "results" in _handle_tool("dxrk_memory_kg_query", {"entity": "X"})
        assert "invalidated" in _handle_tool(
            "dxrk_memory_kg_invalidate", {"subject": "X", "predicate": "y", "object": "Z"}
        )
        assert "timeline" in _handle_tool("dxrk_memory_kg_timeline", {})
        assert "triples" in _handle_tool("dxrk_memory_kg_stats", {})
        assert "traversed" in _handle_tool("dxrk_memory_traverse", {"start": "X"})
        _ = pal

    def test_consolidate_forget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_cf")
        d1 = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "consolidar uno contenido " * 6,
                "source_file": "/1.txt",
            },
        )["drawer_id"]
        d2 = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "consolidar dos contenido " * 6,
                "source_file": "/2.txt",
            },
        )["drawer_id"]
        co = _handle_tool(
            "dxrk_memory_consolidate", {"palace": str(pal), "drawer_ids": [d1, d2], "wing": "w", "room": "r"}
        )
        assert "palace_path" in co
        co2 = _handle_tool("dxrk_memory_consolidate", {"palace": str(pal), "drawer_ids": "no-lista"})
        assert "palace_path" in co2
        fg = _handle_tool("dxrk_memory_forget", {"palace": str(pal), "drawer_ids": [d1], "hard": False})
        assert "palace_path" in fg
        fg2 = _handle_tool("dxrk_memory_forget", {"palace": str(pal), "wing": "w", "before": "2100-01-01"})
        assert "palace_path" in fg2
        fg3 = _handle_tool("dxrk_memory_forget", {"palace": str(pal)})
        assert "palace_path" in fg3

    def test_pin_timeline_quarantine(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_ptq")
        did = _handle_tool(
            "dxrk_memory_add_drawer",
            {
                "palace": str(pal),
                "wing": "w",
                "room": "r",
                "content": "pineable contenido " * 6,
                "source_file": "/p.txt",
            },
        )["drawer_id"]
        assert _handle_tool("dxrk_memory_pin", {"palace": str(pal)})["error"].startswith("drawer_id")
        assert "not found" in _handle_tool("dxrk_memory_pin", {"palace": str(pal), "drawer_id": "missing"})["error"]
        assert _handle_tool("dxrk_memory_pin", {"palace": str(pal), "drawer_id": did, "pinned": True})["pinned"] is True
        assert (
            _handle_tool("dxrk_memory_pin", {"palace": str(pal), "drawer_id": did, "pinned": False})["pinned"] is False
        )
        ident = _handle_tool("dxrk_memory_pin", {"palace": str(pal), "scope": "identity", "pinned": True})
        assert "palace_path" in ident
        unident = _handle_tool("dxrk_memory_pin", {"palace": str(pal), "scope": "identity", "pinned": False})
        assert "palace_path" in unident
        tl = _handle_tool("dxrk_memory_timeline", {"palace": str(pal), "limit": 10})
        assert tl["count"] >= 0
        tl2 = _handle_tool(
            "dxrk_memory_timeline",
            {"palace": str(pal), "limit": "mal", "since": "2000-01-01", "before": "2100-01-01", "wing": "default"},
        )
        assert "entries" in tl2
        assert _handle_tool("dxrk_memory_quarantine", {"palace": str(pal)})["error"] == "drawer_id required"
        assert (
            "not found" in _handle_tool("dxrk_memory_quarantine", {"palace": str(pal), "drawer_id": "missing"})["error"]
        )
        assert (
            "not found"
            in _handle_tool(
                "dxrk_memory_quarantine", {"palace": str(pal), "drawer_id": "missing", "unquarantine": True}
            )["error"]
        )
        q = _handle_tool("dxrk_memory_quarantine", {"palace": str(pal), "drawer_id": did, "reason": "r"})
        assert q.get("quarantined") is True
        uq = _handle_tool("dxrk_memory_quarantine", {"palace": str(pal), "drawer_id": did, "unquarantine": True})
        assert uq.get("quarantined") is False

    def test_fase2_eval(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = tmp_path / "pal_eval"
        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(str(pal))
        dm.init()
        for i in range(4):
            dm.add_drawer("evalw", "general", f"contenido evaluable numero {i} alpha beta gamma " * 8, f"/e{i}.txt", i)
        try:
            dm.close()
        except Exception:
            pass
        rep = _handle_tool("dxrk_memory_eval_run", {"palace": str(pal), "wing": "evalw", "n_queries": 2})
        assert "report" in rep and rep["report"]["wing"] == "evalw"
        syn = _handle_tool("dxrk_memory_eval_synthetic", {"palace": str(pal), "wing": "evalw", "n": 2})
        assert "queries" in syn and len(syn["queries"]) <= 2

    def test_fase2_metacog_calibrate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_meta")
        pr = _handle_tool(
            "dxrk_memory_metacog_predict", {"palace": str(pal), "query": "contenido base", "wing": "default"}
        )
        assert "confidence" in pr and "difficulty" in pr
        cf = _handle_tool("dxrk_memory_calibrate_fit", {"palace": str(pal), "wing": "default", "method": "temperature"})
        assert cf["method"] == "temperature" and "params" in cf
        cf2 = _handle_tool("dxrk_memory_calibrate_fit", {"palace": str(pal), "wing": "default", "method": "isotonic"})
        assert cf2["method"] == "isotonic"
        ct = _handle_tool(
            "dxrk_memory_calibrate_tenant",
            {
                "palace": str(pal),
                "tenant": "acme",
                "wing": "default",
                "a": 1.0,
                "b": 0.0,
                "c": 1.0,
                "pe_lambda": 0.1,
                "score": 0.7,
            },
        )
        assert ct["saved"] is True and ct["params"]["score"] == 0.7
        ch = _handle_tool("dxrk_memory_calibrate_chain", {"palace": str(pal), "tenant": "acme", "wing": "default"})
        assert "chain" in ch and len(ch["chain"]) >= 1

    def test_fase2_production_judge(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_prod")
        cb = _handle_tool("dxrk_memory_circuit_breaker_status", {"palace": str(pal)})
        assert "breakers" in cb
        slo = _handle_tool("dxrk_memory_slo_check", {"palace": str(pal), "wing": "default"})
        assert "compliant" in slo
        rb = _handle_tool("dxrk_memory_rollback_check", {"palace": str(pal), "wing": "default"})
        assert "should_rollback" in rb
        js = _handle_tool("dxrk_memory_judge_status", {"palace": str(pal)})
        assert "consecutive_passes" in js
        jr = _handle_tool("dxrk_memory_judge_run", {"palace": str(pal)})
        assert "verdict" in jr and "passed" in jr["verdict"]

    def test_duplicate_overlap_loop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory import mcp_server as ms
        from dxrk.memory.palace import DxrkMemory

        _iso_home(tmp_path, monkeypatch)
        pal = _mk_palace(tmp_path, "pal_overlap")
        # dos hits: el primero con bajo overlap sigue el loop, el segundo dispara overlap
        monkeypatch.setattr(
            DxrkMemory,
            "search",
            lambda self, *a, **k: {
                "results": [
                    {"text": "totalmente distinto sin coincidencias qwerty zxcv"},
                    {"text": "contenido base para busquedas de prueba repetido aqui"},
                ]
            },
        )
        out = ms._handle_tool(
            "dxrk_memory_check_duplicate",
            {"palace": str(pal), "content": "contenido base para busquedas de prueba adicional"},
        )
        assert out["duplicate"] is True
        # sin tokens (una letra) + varios hits → loop sin break por overlap
        monkeypatch.setattr(
            DxrkMemory,
            "search",
            lambda self, *a, **k: {"results": [{"text": "zzz"}, {"text": "yyy"}]},
        )
        out2 = ms._handle_tool("dxrk_memory_check_duplicate", {"palace": str(pal), "content": "a b c d e f"})
        assert out2["duplicate"] is False

    def test_main_guard(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import runpy
        import sys as _sys

        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setattr(_sys, "stdin", io.StringIO(""))
        monkeypatch.setattr(_sys, "argv", ["dxrk-memory-mcp"])
        with pytest.raises(SystemExit) as exc:
            runpy.run_module("dxrk.memory.mcp_server", run_name="__main__")
        assert exc.value.code == 0

    def test_handle_unknown_and_exception(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _handle_tool

        _iso_home(tmp_path, monkeypatch)
        pal = tmp_path / "pal_err"
        unk = _handle_tool("no_existe_tool", {"palace": str(pal)})
        assert "unknown tool" in unk["error"]
        # excepción interna (falta project_dir) → error con traceback
        err = _handle_tool("dxrk_memory_mine", {"palace": str(pal)})
        assert "error" in err and "traceback" in err

    def test_dispatch_notifications(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.memory.mcp_server import _dispatch

        _iso_home(tmp_path, monkeypatch)
        assert _dispatch({"method": "initialize", "params": {}}) is None
        assert _dispatch({"method": "ping", "params": {}}) is None
        assert _dispatch({"method": "tools/list", "params": {}}) is None
        assert _dispatch({"method": "tools/call", "params": {"name": "dxrk_memory_status", "arguments": {}}}) is None
        assert _dispatch({"method": "tools/call", "params": {"name": "unknown_tool", "arguments": {}}}) is None
        assert _dispatch({"method": "nope", "params": {}}) is None
        assert _dispatch({"method": "notifications/initialized", "id": 1, "params": {}}) is None
        unk = _dispatch({"method": "nope", "id": 5, "params": {}})
        assert unk["error"]["code"] == -32601
        bad_args = _dispatch(
            {"method": "tools/call", "id": 6, "params": {"name": "dxrk_memory_status", "arguments": [1, 2]}}
        )
        assert bad_args["result"]["isError"] is False
        unk2 = _dispatch({"method": "tools/call", "id": 7, "params": {"name": "unknown_tool", "arguments": {}}})
        assert "error" in unk2

    def test_main_palace_batch(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.memory import mcp_server as ms

        _iso_home(tmp_path, monkeypatch)
        pal = str(tmp_path / "main_pal")
        monkeypatch.delenv("DXRK_MEMORY_PATH", raising=False)
        batch = json.dumps(
            [
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            ]
        )
        single = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        notif_only = json.dumps({"jsonrpc": "2.0", "method": "ping", "params": {}})
        inp = io.StringIO("\n" + batch + "\n" + single + "\n" + notif_only + "\nnot json\n")
        out = io.StringIO()
        monkeypatch.setattr(_sys, "stdin", inp)
        monkeypatch.setattr(_sys, "stdout", out)
        assert ms.main(["--palace", pal]) == 0
        assert os.environ.get("DXRK_MEMORY_PATH") == str(Path(pal).resolve())
        txt = out.getvalue()
        assert '"tools"' in txt and "Parse error" in txt

    def test_main_empty_batch_no_response(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.memory import mcp_server as ms

        _iso_home(tmp_path, monkeypatch)
        only_notif = json.dumps([{"jsonrpc": "2.0", "method": "ping", "params": {}}])
        inp = io.StringIO(only_notif + "\n")
        out = io.StringIO()
        monkeypatch.setattr(_sys, "stdin", inp)
        monkeypatch.setattr(_sys, "stdout", out)
        assert ms.main([]) == 0
        assert out.getvalue() == ""


# ===========================================================================
# tenant_switcher — harness Textual del repo (pilot / sin app montada)
# ===========================================================================


def _mk_screen(monkeypatch: pytest.MonkeyPatch | None = None):  # type: ignore[no-untyped-def]
    from dxrk.tui.screens import tenant_switcher as ts_mod
    from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

    if monkeypatch is not None:
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        monkeypatch.setattr(TenantSwitcherScreen, "_focus_current_card", lambda self: None)
        monkeypatch.setattr(TenantSwitcherScreen, "_update_preview", lambda self: None)
    return TenantSwitcherScreen()


class TestTenantSwitcherCov100:
    def test_get_tenants_import_and_list_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.tui.screens.tenant_switcher import _get_tenants

        _iso_home(tmp_path, monkeypatch)
        assert _get_tenants() == []
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("acme")
        assert "acme" in _get_tenants()
        monkeypatch.setattr("dxrk.tenant.migration.list_tenants", lambda: (_ for _ in ()).throw(OSError("boom")))
        assert _get_tenants() == []
        monkeypatch.setitem(_sys.modules, "dxrk.tenant.migration", None)
        assert _get_tenants() == []

    def test_get_tenant_details_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.tui.context import TUIContext, set_ctx
        from dxrk.tui.screens.tenant_switcher import _get_tenant_details

        home = _iso_home(tmp_path, monkeypatch)
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("acme")
        set_ctx(TUIContext(tenant_id="acme", role="admin"))
        info = _get_tenant_details("acme")
        assert info.id == "acme" and info.is_current is True
        assert info.role in ("admin", "dev", "readonly")
        # resolver devuelve rol válido → rama role = resolved
        import dxrk.security.rbac as rbac

        orig_cls = rbac.TenantRoleResolver

        class FakeResolver:
            def __init__(self, tid: str) -> None:
                pass

            def resolve(self, _u: str) -> str:
                return "admin"

        monkeypatch.setattr(rbac, "TenantRoleResolver", FakeResolver)
        info2 = _get_tenant_details("acme")
        assert info2.role == "admin"

        # resolver que falla → except pass, rol readonly
        class BoomResolver:
            def __init__(self, tid: str) -> None:
                raise OSError("boom")

        monkeypatch.setattr(rbac, "TenantRoleResolver", BoomResolver)
        info3 = _get_tenant_details("acme")
        assert info3.role == "readonly"

        class WeirdResolver:
            def __init__(self, tid: str) -> None:
                pass

            def resolve(self, _u: str) -> str:
                return "superuser"

        monkeypatch.setattr(rbac, "TenantRoleResolver", WeirdResolver)
        assert _get_tenant_details("acme").role == "readonly"
        monkeypatch.setattr(rbac, "TenantRoleResolver", orig_cls)
        # tenant_root que falla → fallback path
        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        info4 = _get_tenant_details("acme")
        assert "acme" in info4.path
        # import de rbac falla
        monkeypatch.setitem(_sys.modules, "dxrk.security.rbac", None)
        info5 = _get_tenant_details("acme")
        assert info5.role == "readonly"
        # import de migration falla (path fallback)
        monkeypatch.setitem(_sys.modules, "dxrk.tenant.migration", None)
        info6 = _get_tenant_details("acme")
        assert "acme" in info6.path
        # DxrkMemory que falla → drawer_count 0
        import dxrk.memory.palace as palace_mod

        monkeypatch.setattr(palace_mod, "DxrkMemory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        info7 = _get_tenant_details("acme")
        assert info7.drawer_count == 0
        _ = home

    def test_cards_compose_pilot(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Las ramas de compose con size_mb/last_accessed/home-strip solo se cubren
        # con app montada (Textual exige active_app en `with Horizontal()`).
        # Se verifican en los pilots de abajo via _render_list + update_preview.
        from dxrk.tui.screens.tenant_switcher import TenantInfo

        _iso_home(tmp_path, monkeypatch)
        info = TenantInfo(
            id="a",
            path=str(Path.home() / ".dxrk" / "tenants" / "a"),
            role="admin",
            is_current=True,
            drawer_count=3,
            size_mb=1.5,
            last_accessed="ayer",
        )
        assert info.size_mb == 1.5 and info.last_accessed == "ayer"
        assert info.is_current is True

    def test_preview_nomount_nomatches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from textual.css.query import NoMatches as _NM

        from dxrk.tui.screens.tenant_switcher import PreviewPane, SearchInput, TenantInfo

        _iso_home(tmp_path, monkeypatch)
        pp = PreviewPane()
        monkeypatch.setattr(pp, "query_one", lambda *a, **k: (_ for _ in ()).throw(_NM("x")))
        pp.update_preview(TenantInfo(id="x", path="/tmp/x", role="dev", is_current=False))
        pp.update_preview(None)
        assert pp.current_info is None
        assert SearchInput() is not None

    def test_on_mount_timer_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tui.screens import tenant_switcher as ts_mod

        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        s = TenantSwitcherScreen()
        monkeypatch.setattr(s, "_load_tenants", lambda: None)
        monkeypatch.setattr(s, "call_later", lambda *a, **k: None)

        def boom_interval(*a: Any, **k: Any) -> Any:
            raise RuntimeError("no timer")

        monkeypatch.setattr(s, "set_interval", boom_interval)
        s.on_mount()
        assert s._refresh_timer is None

    def test_focus_helpers_unmounted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        s._focus_list()
        s._focus_search()
        # query_one que falla con NoMatches explícito
        from textual.css.query import NoMatches

        def boom_q(*a: Any, **k: Any) -> Any:
            raise NoMatches()

        monkeypatch.setattr(s, "query_one", boom_q)
        s._focus_list()
        s._focus_search()
        s.on_unmount()

        # timers con stop que falla
        class BadTimer:
            def stop(self) -> None:
                raise RuntimeError("stop boom")

        s._refresh_timer = None
        s._debounce_timer = BadTimer()  # type: ignore[assignment]
        s.on_unmount()
        assert s._debounce_timer is None

    def test_load_details_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tui.screens import tenant_switcher as ts_mod

        _iso_home(tmp_path, monkeypatch)
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("a1")
        ensure_tenant("a2")
        s = _mk_screen(monkeypatch)
        orig = ts_mod._get_tenant_details

        def boom(tid: str) -> Any:
            if tid == "a2":
                raise OSError("boom")
            return orig(tid)

        monkeypatch.setattr(ts_mod, "_get_tenant_details", boom)
        s._load_tenants()
        assert "a1" in s._tenants and "a2" in s._tenants
        assert "a1" in s._details and "a2" not in s._details
        # _details_for fallback cuando el fetch falla
        monkeypatch.setattr(ts_mod, "_get_tenant_details", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        assert s._details_for("missing-x")["id"] == "missing-x"

        # cache write que falla (dict roto)
        class BadDict(dict):  # type: ignore[type-arg]
            def __setitem__(self, k: Any, v: Any) -> None:
                raise OSError("set boom")

        s._details = BadDict()  # type: ignore[assignment]
        got = s._details_for("a1")
        assert got["id"] == "a1"

    def test_filter_debounce_and_timer_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        s._tenants = ["alpha", "beta"]
        s._details = {}

        # debounce stop que falla → se ignora y sigue
        class BadTimer:
            def stop(self) -> None:
                raise OSError("boom")

        s._debounce_timer = BadTimer()  # type: ignore[assignment]
        applied: list[bool] = []
        monkeypatch.setattr(s, "_apply_filter", lambda: applied.append(True))
        # sin event loop corre directo (rama asyncio.get_running_loop RuntimeError)
        s._filter_tenants()
        assert applied
        assert s._debounce_timer is None

    def test_apply_filter_query_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        rendered: list[int] = []
        monkeypatch.setattr(s, "_render_list", lambda: rendered.append(1) or 0)
        s._tenants = ["alpha", "beta"]
        s._details = {
            "alpha": {"id": "alpha", "path": "/data/alpha_proj", "role": "dev"},
            "beta": {"id": "beta", "path": "/otro", "role": "dev"},
        }
        s.search_query = ""
        s._apply_filter()
        assert s._filtered == ["alpha", "beta"]
        s.search_query = "alpha"
        s._apply_filter()
        assert s._filtered == ["alpha"]
        # match por path, no por id
        s.search_query = "alpha_proj"
        s._apply_filter()
        assert s._filtered == ["alpha"]
        # details_for que falla se ignora
        monkeypatch.setattr(s, "_details_for", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        s.search_query = "zzz"
        s._apply_filter()
        assert s._filtered == []
        assert rendered

    def test_render_empty_and_exceptions(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock

        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        # sin montar → return 0
        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("no scroll")))
        s._filtered = []
        s.search_query = ""
        assert s._render_list() == 0
        s.search_query = "zzz"
        assert s._render_list() == 0
        # empty con update que falla → except pass, return 0
        mock_empty = MagicMock()
        mock_empty.update.side_effect = RuntimeError("boom")
        mock_scroll = MagicMock()
        mock_scroll.remove_children = MagicMock()
        monkeypatch.setattr(s, "query_one", lambda *a, **k: mock_scroll if "tenant-list" in str(a) else mock_empty)
        s._filtered = []
        assert s._render_list() == 0
        # remove_children que falla → se ignora
        mock_scroll.remove_children.side_effect = RuntimeError("boom")
        s._filtered = []
        s.search_query = ""
        assert s._render_list() == 0
        # no vacía con mount que falla + clamp + focus/preview que fallan
        mock_scroll2 = MagicMock()
        mock_scroll2.remove_children = MagicMock()
        mock_scroll2.mount = MagicMock(side_effect=RuntimeError("mount boom"))
        mock_empty_ok = MagicMock()
        mock_empty_ok.update = MagicMock()
        monkeypatch.setattr(s, "query_one", lambda *a, **k: mock_scroll2 if "tenant-list" in str(a) else mock_empty_ok)

        def _boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")

        monkeypatch.setattr(s, "_focus_current_card", _boom)
        monkeypatch.setattr(s, "_update_preview", _boom)
        s._filtered = ["a", "b"]
        s._details = {
            "a": {"id": "a", "path": "/tmp/a", "role": "dev"},
            "b": {"id": "b", "path": "/tmp/b", "role": "dev"},
        }
        s.cursor = 9
        assert s._render_list() == 2
        assert s.cursor == 1

    def test_focus_current_card_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        monkeypatch.setattr(TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        s = TenantSwitcherScreen()
        s._filtered = []
        s._focus_current_card()  # vacío → return
        s._filtered = ["a"]
        s.cursor = 5  # IndexError → pass
        s._focus_current_card()
        s.cursor = 0
        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(TypeError("bad")))
        s._focus_current_card()
        # dict format
        s._filtered = [{"id": "a"}]  # type: ignore[list-item]
        s.cursor = 0
        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(KeyError("k")))
        s._focus_current_card()

    def test_watchers_and_inputs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        s._filtered = ["a"]
        s._tenants = ["a"]
        # watch_cursor llama focus + preview (mockeados en _mk_screen)
        s.watch_cursor(0, 0)
        # watch_search_query dispara filter (sin loop → apply directo)
        monkeypatch.setattr(s, "_render_list", lambda: 0)
        s.watch_search_query("", "a")
        # on_input_changed ambas ramas
        s.on_input_changed(SimpleNamespace(input=SimpleNamespace(id="search-input"), value="x"))  # type: ignore[arg-type]
        assert s.search_query == "x"
        s.on_input_changed(SimpleNamespace(input=SimpleNamespace(id="tenant-create-input"), value="y"))  # type: ignore[arg-type]
        s.on_input_changed(SimpleNamespace(input=SimpleNamespace(id="otro"), value="z"))  # type: ignore[arg-type]
        # on_input_submitted
        called: list[str] = []
        monkeypatch.setattr(s, "action_switch", lambda: called.append("switch"))
        monkeypatch.setattr(s, "action_create", lambda: called.append("create"))
        s.on_input_submitted(SimpleNamespace(input=SimpleNamespace(id="search-input")))  # type: ignore[arg-type]
        s.on_input_submitted(SimpleNamespace(input=SimpleNamespace(id="tenant-create-input")))  # type: ignore[arg-type]
        s.on_input_submitted(SimpleNamespace(input=SimpleNamespace(id="otro")))  # type: ignore[arg-type]
        assert called == ["switch", "create"]
        # on_button_pressed
        s.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="create-btn")))  # type: ignore[arg-type]
        assert called[-1] == "create"
        s.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="otro")))  # type: ignore[arg-type]

    def test_update_preview_branches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from textual.css.query import NoMatches as _NM

        from dxrk.tui.context import TUIContext, set_ctx
        from dxrk.tui.screens import tenant_switcher as ts_mod
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        _iso_home(tmp_path, monkeypatch)
        set_ctx(TUIContext(tenant_id="a", role="dev"))
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        s2 = TenantSwitcherScreen()
        s2._filtered = ["a"]
        s2.cursor = 0
        s2._details = {
            "a": {"id": "a", "path": "/tmp/a", "role": "dev", "is_current": True, "drawer_count": 1, "size_mb": 0.0}
        }

        def boom_nm(*a: Any, **k: Any) -> Any:
            raise _NM("x")

        monkeypatch.setattr(s2, "query_one", boom_nm)
        s2._update_preview()
        # dict format en _filtered
        s2._filtered = [
            {"id": "a", "path": "/tmp/a", "role": "dev", "is_current": False, "drawer_count": 0, "size_mb": 0.0}
        ]  # type: ignore[list-item]
        s2._update_preview()
        # vacío → preview None
        s2._filtered = []
        s2._update_preview()
        # badge sin montar → pass
        s2._update_badge()
        # auto-refresh real ejercita _load_tenants
        s2._auto_refresh_tenants()

    def test_actions_refresh_search_cursor(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock

        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        monkeypatch.setattr(s, "_load_tenants", lambda: None)
        monkeypatch.setattr(s, "notify", lambda *a, **k: None)
        s.action_refresh()
        # action_search con focus ok y con excepción
        mock_inp = MagicMock()
        mock_inp.focus = MagicMock()
        monkeypatch.setattr(s, "query_one", lambda *a, **k: mock_inp)
        s.action_search()
        assert mock_inp.focus.called
        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))
        s.action_search()
        # cursor con panel preview → vuelve a list
        s._filtered = ["a", "b"]
        s.cursor = 1
        s.panel_focus = "preview"  # type: ignore[assignment]
        s.action_cursor_up()
        assert s.panel_focus == "list" and s.cursor == 0
        s.panel_focus = "preview"  # type: ignore[assignment]
        s.action_cursor_down()
        assert s.panel_focus == "list" and s.cursor == 1
        s.panel_focus = "list"  # type: ignore[assignment]
        s.action_cursor_up()
        s.action_cursor_down()
        # toggle panel ambos lados + NoMatches
        mock_prev = MagicMock()
        mock_prev.focus = MagicMock()
        monkeypatch.setattr(s, "query_one", lambda *a, **k: mock_prev)
        s.panel_focus = "list"  # type: ignore[assignment]
        s.action_toggle_panel()
        assert s.panel_focus == "preview"
        s.action_toggle_panel()
        assert s.panel_focus == "list"
        from textual.css.query import NoMatches as _NM2

        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(_NM2("x")))
        s.panel_focus = "list"  # type: ignore[assignment]
        s.action_toggle_panel()
        s.panel_focus = "preview"  # type: ignore[assignment]
        monkeypatch.setattr(s, "_focus_current_card", lambda: None)
        s.action_toggle_panel()

    def test_do_switch_variants(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.tenant.migration import ensure_tenant
        from dxrk.tui.context import TUIContext, get_ctx, set_ctx
        from dxrk.tui.screens import tenant_switcher as ts_mod
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        home = _iso_home(tmp_path, monkeypatch)
        ensure_tenant("acme")
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)

        def mk() -> Any:
            sc = TenantSwitcherScreen()
            monkeypatch.setattr(sc, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("no badge")))
            monkeypatch.setattr(sc, "notify", lambda *a, **k: None)
            return sc

        set_ctx(TUIContext(tenant_id="old", tenant_path="", role="readonly"))
        mk()._do_switch_sync("acme")
        assert get_ctx().tenant_id == "acme"
        assert (home / ".dxrk" / "tenants" / "_active").read_text() == "acme"
        # tenant_root que falla → fallback tid
        monkeypatch.setattr("dxrk.tenant.migration.tenant_root", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        mk()._do_switch_sync("acme")
        assert get_ctx().tenant_path == "acme"
        monkeypatch.undo()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        # import tenant_root falla → _tenant_root None
        monkeypatch.setitem(_sys.modules, "dxrk.tenant.migration", None)
        mk()._do_switch_sync("acme")
        assert get_ctx().tenant_id == "acme"
        monkeypatch.undo()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        # role resolver falla → conserva rol
        import dxrk.security.rbac as rbac

        monkeypatch.setattr(rbac, "TenantRoleResolver", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        set_ctx(TUIContext(tenant_id="x", role="dev"))
        mk()._do_switch_sync("acme")
        assert get_ctx().role == "dev"
        monkeypatch.undo()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        # import rbac falla
        monkeypatch.setitem(_sys.modules, "dxrk.security.rbac", None)
        mk()._do_switch_sync("acme")
        monkeypatch.undo()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        # escritura de _active falla → se ignora
        monkeypatch.setattr(Path, "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        mk()._do_switch_sync("acme")
        assert get_ctx().tenant_id == "acme"
        monkeypatch.undo()

    def test_action_switch_bounds(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)
        s._filtered = []
        s.action_switch()
        s._filtered = ["x"]
        s.cursor = 5
        s.action_switch()
        s.cursor = -1
        s.action_switch()
        # switch válido llama _do_switch_sync
        from dxrk.tenant.migration import ensure_tenant

        ensure_tenant("ok1")
        s._filtered = ["ok1"]
        s.cursor = 0
        monkeypatch.setattr(s, "_do_switch_sync", lambda tid: setattr(s, "_sw", tid))
        s.action_switch()
        assert s._sw == "ok1"  # type: ignore[attr-defined]
        s._filtered = [{"id": "ok1"}]  # type: ignore[list-item]
        s.action_switch()
        assert s._sw == "ok1"  # type: ignore[attr-defined]

    def test_action_create_all(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tui.screens import tenant_switcher as ts_mod

        _iso_home(tmp_path, monkeypatch)
        from dxrk.tui.context import TUIContext, set_ctx

        set_ctx(TUIContext(tenant_id="", role="readonly"))
        s = _mk_screen(monkeypatch)
        # NoMatches → return
        monkeypatch.setattr(s, "query_one", lambda *a, **k: (_ for _ in ()).throw(Exception("no match")))
        # _mk_screen mockea _update_preview/_focus; action_create usa query_one real → restauramos
        from textual.css.query import NoMatches as _NM

        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        s2 = TenantSwitcherScreen()
        monkeypatch.setattr(TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)

        def boom_nm(*a: Any, **k: Any) -> Any:
            raise _NM("x")

        monkeypatch.setattr(s2, "query_one", boom_nm)
        s2.action_create()  # NoMatches → return silencioso

        class FakeInput:
            def __init__(self, val: str) -> None:
                self.value = val
                self.placeholder = ""

            def focus(self) -> None:
                self.focused = True  # type: ignore[attr-defined]

        # vacío → focus
        fake = FakeInput("")
        monkeypatch.setattr(s2, "query_one", lambda *a, **k: fake)
        s2.action_create()
        assert hasattr(fake, "focused")
        # inválido
        fake2 = FakeInput("bad/id")
        monkeypatch.setattr(s2, "query_one", lambda *a, **k: fake2)
        s2.action_create()
        assert fake2.value == "" and "no válido" in fake2.placeholder
        # ensure_tenant falla → notify error y return
        fake3 = FakeInput("goodid")
        monkeypatch.setattr(s2, "query_one", lambda *a, **k: fake3)
        monkeypatch.setattr(s2, "notify", lambda *a, **k: setattr(s2, "_notified", True))
        monkeypatch.setattr("dxrk.tenant.migration.ensure_tenant", lambda tid: (_ for _ in ()).throw(OSError("boom")))
        s2.action_create()
        assert getattr(s2, "_notified", False) is True
        monkeypatch.undo()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        # ensure_default falla → se ignora y sigue
        import dxrk.security.rbac as rbac2

        orig_resolver = rbac2.TenantRoleResolver

        class NoDefault:
            def __init__(self, tid: str) -> None:
                pass

            def resolve(self, _u: str) -> str:
                return "readonly"

            def ensure_default(self) -> None:
                raise OSError("boom")

        monkeypatch.setattr(rbac2, "TenantRoleResolver", NoDefault)
        s3 = TenantSwitcherScreen()
        fake4 = FakeInput("tenantok")
        monkeypatch.setattr(s3, "query_one", lambda *a, **k: fake4)
        monkeypatch.setattr(s3, "notify", lambda *a, **k: None)
        monkeypatch.setattr(s3, "_render_list", lambda: None)
        monkeypatch.setattr(s3, "_do_switch_sync", lambda tid: setattr(s3, "_sw", tid))
        s3.action_create()
        assert getattr(s3, "_sw", None) == "tenantok" and fake4.value == ""
        monkeypatch.setattr(rbac2, "TenantRoleResolver", orig_resolver)

    def test_help_key_focus_back(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from textual.css.query import NoMatches as _NM

        _iso_home(tmp_path, monkeypatch)
        s = _mk_screen(monkeypatch)

        # help toggle con widget ausente → NoMatches → pass
        def boom_nm(*a: Any, **k: Any) -> Any:
            raise _NM("x")

        monkeypatch.setattr(s, "query_one", boom_nm)
        s.show_help = True
        s.action_help_toggle()
        assert s.show_help is False
        s.action_help_toggle()
        assert s.show_help is True
        # on_key
        s.on_key(SimpleNamespace(key="h"))  # type: ignore[arg-type]
        s.on_key(SimpleNamespace(key="question_mark"))  # type: ignore[arg-type]
        s.on_key(SimpleNamespace(key="tab"))  # type: ignore[arg-type]
        s.on_key(SimpleNamespace(key="x"))  # type: ignore[arg-type]
        # on_focus con inputs y con show_help False
        s.show_help = True
        s.on_focus(SimpleNamespace(widget=SimpleNamespace(id="search-input")))  # type: ignore[arg-type]
        assert s.show_help is False
        s.show_help = False
        s.on_focus(SimpleNamespace(widget=SimpleNamespace(id="search-input")))  # type: ignore[arg-type]
        s.show_help = True
        s.on_focus(SimpleNamespace(widget=SimpleNamespace(id="otro")))  # type: ignore[arg-type]
        assert s.show_help is True
        s.on_focus(SimpleNamespace(widget=None))  # type: ignore[arg-type]

        # action_back necesita app
        class DummyApp:
            def __init__(self) -> None:
                self.pushed = ""

            def push_screen(self, name: str) -> None:
                self.pushed = name

        from dxrk.tui.screens import tenant_switcher as ts_mod

        dummy = DummyApp()
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "app", property(lambda self: dummy))
        s.action_back()
        assert dummy.pushed == "welcome"

    async def test_filter_timer_runtime(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tui.screens import tenant_switcher as ts_mod
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        _iso_home(tmp_path, monkeypatch)
        monkeypatch.setattr(ts_mod.TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        s = TenantSwitcherScreen()
        s._tenants = ["a"]
        s._details = {}
        applied: list[bool] = []
        monkeypatch.setattr(s, "_apply_filter", lambda: applied.append(True))

        def boom_timer(*a: Any, **k: Any) -> Any:
            raise RuntimeError("sin timer")

        monkeypatch.setattr(s, "set_timer", boom_timer)
        s._filter_tenants()
        assert applied and s._debounce_timer is None

    async def test_pilot_search_create_help_panel(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import os as _os

        from dxrk.tenant.migration import ensure_tenant
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext, get_ctx
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        home = _iso_home(tmp_path, monkeypatch)
        ensure_tenant("acme")
        ensure_tenant("bob")
        app = DxrkApp(TUIContext(version="test", tenant_id="acme", role="readonly"))
        async with app.run_test() as pilot:
            await pilot.app.push_screen("tenant_switcher")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, TenantSwitcherScreen)
            assert screen._tenants == ["acme", "bob"]
            # filtro en vivo por path/id (debounce 0.1s en pilot con loop)
            screen.search_query = "bob"
            screen._apply_filter()
            await pilot.pause()
            assert screen._filtered == ["bob"]
            screen.search_query = ""
            screen._apply_filter()
            await pilot.pause()
            assert len(screen._filtered) == 2
            # ramas de compose: cards con size_mb + last_accessed + home-strip y no-strip
            screen._details["acme"]["size_mb"] = 2.5
            screen._details["acme"]["last_accessed"] = "ayer"
            screen._details["bob"]["path"] = "/tmp/externo-bob"
            screen._render_list()
            await pilot.pause()
            from dxrk.tui.screens.tenant_switcher import TenantCard, TenantInfo

            cards = list(screen.query(TenantCard))
            assert len(cards) == 2
            lst = screen.query_one("#tenant-list")
            await lst.mount(
                TenantCard(
                    TenantInfo(
                        id="ext",
                        path="/tmp/externo-x",
                        role="readonly",
                        is_current=False,
                        drawer_count=1,
                        size_mb=3.0,
                        last_accessed="hoy",
                    ),
                    index=99,
                )
            )
            await pilot.pause()
            assert len(list(screen.query(TenantCard))) == 3
            # preview montado cubre path-strip + role + estado
            preview = screen.query_one("#preview-pane")
            preview.update_preview(
                TenantInfo(
                    id="acme",
                    path=str(Path.home() / "t" / "acme"),
                    role="admin",
                    is_current=True,
                    drawer_count=2,
                    size_mb=1.5,
                    last_accessed="ayer",
                )
            )
            preview.update_preview(
                TenantInfo(id="e", path="/tmp/externo", role="readonly", is_current=False, drawer_count=0, size_mb=0.0)
            )
            preview.update_preview(None)
            assert preview.current_info is None
            # on_mount/on_focus/on_blur de cards + RoleBadge/ShortcutHelp compose montados
            for c in cards:
                c.on_mount()
                c.on_focus()
                c.on_blur()
            from dxrk.tui.screens.tenant_switcher import RoleBadge, ShortcutHelp

            assert len(list(screen.query(RoleBadge))) >= 2
            assert screen.query_one("#shortcut-help", ShortcutHelp) is not None
            # cursor y preview
            await pilot.press("down")
            await pilot.pause()
            assert screen.cursor == 1
            await pilot.press("up")
            await pilot.pause()
            assert screen.cursor == 0
            # help toggle + panel + search + refresh vía actions reales
            screen.action_help_toggle()
            await pilot.pause()
            screen.action_help_toggle()
            await pilot.pause()
            screen.action_toggle_panel()
            await pilot.pause()
            screen.action_toggle_panel()
            await pilot.pause()
            screen.action_search()
            await pilot.pause()
            screen.action_refresh()
            await pilot.pause()
            # switch con enter cambia al segundo
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert get_ctx().tenant_id == "bob"
            assert _os.environ.get("DXRK_TENANT") == "bob"
            assert (home / ".dxrk" / "tenants" / "_active").read_text() == "bob"

    async def test_pilot_empty_and_create(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tui.app import DxrkApp
        from dxrk.tui.context import TUIContext
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        _iso_home(tmp_path, monkeypatch)
        app = DxrkApp(TUIContext(version="test", tenant_id="", role="readonly"))
        async with app.run_test() as pilot:
            await pilot.app.push_screen("tenant_switcher")
            await pilot.pause()
            screen = pilot.app.screen
            assert isinstance(screen, TenantSwitcherScreen)
            assert screen._filtered == []
            assert screen._render_list() == 0
            # crear vía input real
            create_inp = screen.query_one("#tenant-create-input")
            create_inp.value = "nuevo1"
            screen.action_create()
            await pilot.pause()
            assert "nuevo1" in screen._tenants
            # foco en search sin romper
            screen._focus_search()
            screen._focus_list()
            screen._update_preview()
            screen._update_badge()

    def test_details_for_cache_write_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tenant.migration import ensure_tenant

        _iso_home(tmp_path, monkeypatch)
        ensure_tenant("cachew")
        s = _mk_screen(monkeypatch)

        class BadDict(dict):  # type: ignore[type-arg]
            def __setitem__(self, k: Any, v: Any) -> None:
                raise OSError("set boom")

        # fetch real ok pero el write al cache falla → except → return details
        s._details = BadDict()  # type: ignore[assignment]
        got = s._details_for("cachew")
        assert got["id"] == "cachew"
        assert isinstance(got["path"], str) and got["path"]

    def test_do_switch_besteffort_nomount(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dxrk.tenant.migration import ensure_tenant
        from dxrk.tui.context import TUIContext, get_ctx, set_ctx

        _iso_home(tmp_path, monkeypatch)
        ensure_tenant("besteff")
        set_ctx(TUIContext(tenant_id="old", tenant_path="", role="readonly"))
        s = _mk_screen(monkeypatch)

        def boom_badge() -> None:
            raise RuntimeError("badge boom")

        monkeypatch.setattr(s, "_update_badge", boom_badge)
        # notify real sin app montada → NoActiveAppError → except → pass
        s._do_switch_sync("besteff")
        assert get_ctx().tenant_id == "besteff"
        assert os.environ.get("DXRK_TENANT") == "besteff"

    def test_action_create_jwt_import_fail(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys as _sys

        from dxrk.tui.context import TUIContext, get_ctx, set_ctx
        from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

        _iso_home(tmp_path, monkeypatch)
        set_ctx(TUIContext(tenant_id="", role="readonly"))
        monkeypatch.setattr(TenantSwitcherScreen, "watch_cursor", lambda self, old, new: None)
        s = TenantSwitcherScreen()

        class FakeInput:
            def __init__(self, val: str) -> None:
                self.value = val
                self.placeholder = ""

            def focus(self) -> None:
                self.focused = True  # type: ignore[attr-defined]

        fake = FakeInput("jwtless")
        monkeypatch.setattr(s, "query_one", lambda *a, **k: fake)
        monkeypatch.setattr(s, "_render_list", lambda: None)
        # jwt no importable → _validate_id None → se salta la validación
        monkeypatch.setitem(_sys.modules, "dxrk.security.jwt", None)
        s.action_create()
        assert "jwtless" in s._tenants
        assert get_ctx().tenant_id == "jwtless"
        assert fake.value == ""
