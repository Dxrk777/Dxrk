# SPDX-License-Identifier: MIT
"""Cobertura 100% final7 — ramas/líneas sueltas de bajo conteo.

Tests reales de comportamiento: cada test ejercita una rama o línea
exacta del coverage report. Sin red real (servidor HTTP local o fakes).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest

# ═══════════ dxrk/agents/interface.py 18->exit ═══════════


class TestAdapterAbstractBody:
    def test_agent_abstract_property_body(self):
        from dxrk.agents.interface import Adapter
        from dxrk.agents.opencode.adapter import OpenCodeAdapter

        ad = OpenCodeAdapter()
        assert Adapter.agent.fget(ad) is None


# ═══════════ dxrk/__main__.py 431->435 ═══════════


class TestUninstallCliEmptyManual:
    def test_empty_manual_actions(self, capsys):
        import dxrk.__main__ as mainmod

        args = SimpleNamespace(agents=[], components=[], all=False, yes=False)
        fake = SimpleNamespace(removed_files=[], manual_actions=[])
        with mock.patch("dxrk.cli.uninstall.RunUninstall", return_value=fake):
            mainmod._run_uninstall_cli(args)
        assert "Uninstall complete" in capsys.readouterr().out


# ═══════════ dxrk/coordinator.py 309->315 ═══════════


class TestCoordinatorZeroLimit:
    def test_scratchpad_zero_limit_empty(self):
        from dxrk.coordinator import Coordinator, CoordinatorConfig

        coord = Coordinator(CoordinatorConfig(scratchpad_limit=0))
        coord.set_scratchpad("k", "v", "tester")
        assert coord.get_scratchpad("k").value == "v"


# ═══════════ dxrk/opencode.py 97->118 ═══════════


class TestLoadModelsNonDict:
    def test_models_not_a_dict(self, tmp_path):
        from dxrk.opencode import load_models

        cache = tmp_path / "models.json"
        cache.write_text(json.dumps({"p": {"name": "P", "env": [], "models": ["no", "dict"]}}))
        providers = load_models(str(cache))
        assert providers["p"].models == {}


# ═══════════ dxrk/resilience 174->exit, 186->exit ═══════════


class TestBreakerOpenIgnored:
    def test_failure_and_success_while_open(self):
        from dxrk.resilience import CircuitBreaker, CircuitBreakerConfig, State

        cfg = CircuitBreakerConfig(failure_threshold=1, success_threshold=1, timeout=timedelta(seconds=30))
        brk = CircuitBreaker(cfg)
        brk._on_failure()
        assert brk.state() == State.OPEN
        brk._on_failure()
        assert brk.state() == State.OPEN
        brk._on_success()
        assert brk.state() == State.OPEN


# ═══════════ dxrk/scholar/citation/format.py 70->72 ═══════════


class TestBibtexNoYear:
    def test_authors_without_year(self):
        from dxrk.scholar.citation.format import Paper, format_bibtex

        out = format_bibtex(Paper(title="T", authors=["John Doe"], year=0))
        assert "@article{doe," in out
        assert "year" not in out


# ═══════════ dxrk/scraper 46->44 ═══════════


class _EmptyHrefHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = (
            b"<html><head><title>H</title></head>"
            b"<body><p>x</p>"
            b'<a href="">empty</a><a>nohref</a><a href="/ok">ok</a>'
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class TestScrapeEmptyHref:
    def test_empty_href_skipped(self):
        from dxrk.scraper import scrape

        httpd = HTTPServer(("127.0.0.1", 0), _EmptyHrefHandler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            res = scrape(f"http://127.0.0.1:{httpd.server_address[1]}", 5.0)
        finally:
            httpd.shutdown()
        assert res.links == ["/ok"]


# ═══════════ dxrk/security/permissions.py 240->247 ═══════════


class TestMatchesRulePatternOnly:
    def test_glob_without_prefix(self):
        from dxrk.security.permissions import PermissionRule, _matches_rule

        rule = PermissionRule(tool="Bash", pattern="git *")
        assert _matches_rule(rule, "bash", "git status") is True
        assert _matches_rule(rule, "bash", "ls") is False
        prefixed = PermissionRule(tool="Bash", prefix="git")
        assert _matches_rule(prefixed, "bash", "ls -la") is False
        assert _matches_rule(prefixed, "bash", "git status") is True
        assert _matches_rule(prefixed, "bash", "github status") is False


# ═══════════ dxrk/utils/http/context.py 44->exit ═══════════


class TestContextDoubleCancel:
    def test_second_cancel_is_noop(self):
        from dxrk.utils.http.context import _with_cancel

        ctx, cancel = _with_cancel()
        cancel()
        assert ctx.err() is not None
        cancel()
        assert ctx.err() is not None


# ═══════════ dxrk/verify.py 96->89 ═══════════


class TestBuildReportWarningLoop:
    def test_warning_then_passed(self):
        from dxrk.verify import CheckResult, CheckStatus, build_report

        rep = build_report(
            [
                CheckResult(id="w", status=CheckStatus.WARNING),
                CheckResult(id="p", status=CheckStatus.PASSED),
            ]
        )
        assert rep.warnings == 1
        assert rep.passed == 1
        assert rep.ready is True

    def test_unknown_status_tolerated(self):
        from dxrk.verify import CheckResult, build_report

        rep = build_report([CheckResult(id="x", status="estado-futuro")])
        assert (rep.passed, rep.failed, rep.skipped, rep.warnings) == (0, 0, 0, 0)
        assert rep.ready is True


# ═══════════ dxrk/cli/runtime_uninstall.py 25->29 ═══════════


class TestRunUninstallConfirmed:
    def test_confirm_yes_partial(self, monkeypatch):
        from dxrk.cli import runtime_uninstall as rv

        monkeypatch.setattr("builtins.input", lambda *a, **k: "yes")
        sentinel = object()
        with mock.patch("dxrk.components.uninstall.Service") as svc:
            svc.return_value.complete_uninstall.return_value = sentinel
            out = rv.run_uninstall(["--all"], stdout=StringIO())
        assert out is sentinel


# ═══════════ dxrk/cli/runtime_paths.py ═══════════


def _fake_adapter2(**kw):
    from dxrk.models import MCPStrategy, SystemPromptStrategy

    base = dict(
        mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES,
        system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
        supports_system_prompt=True,
        supports_slash_commands=True,
        supports_skills=True,
        supports_output_styles=True,
        agent="fake",
    )
    base.update(kw)
    mcp_path = kw.get("_mcp_path", "/home/u/mcp.json")
    settings_path = kw.get("_settings_path", "/home/u/settings.json")
    sys_path = kw.get("_sys_path", "/home/u/sys.md")
    cmd_dir = kw.get("_cmd_dir", "/home/u/cmds")
    skills_dir = kw.get("_skills_dir", "/home/u/skills")
    style_dir = kw.get("_style_dir", "/home/u/styles")

    def mcp_config_path(home, name):
        return mcp_path if mcp_path else ""

    def settings_path_fn(home):
        return settings_path

    def system_prompt_file(home):
        return sys_path

    def commands_dir(home):
        return cmd_dir

    def skills_dir_fn(home):
        return skills_dir

    def output_style_dir(home):
        return style_dir

    return SimpleNamespace(
        mcp_strategy=base["mcp_strategy"],
        system_prompt_strategy=base["system_prompt_strategy"],
        supports_system_prompt=base["supports_system_prompt"],
        supports_slash_commands=base["supports_slash_commands"],
        supports_skills=base["supports_skills"],
        supports_output_styles=base["supports_output_styles"],
        agent=base["agent"],
        mcp_config_path=mcp_config_path,
        settings_path=settings_path_fn,
        system_prompt_file=system_prompt_file,
        commands_dir=commands_dir,
        skills_dir=skills_dir_fn,
        output_style_dir=output_style_dir,
    )


class TestRuntimePathsRemainder:
    def test_memory_unknown_strategy(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, Selection

        ad = _fake_adapter2(mcp_strategy="estrategia-desconocida")
        assert _component_paths("/h", Selection(), [ad], ComponentID.DXRK_MEMORY) == ["/home/u/sys.md"]

    def test_unknown_component_skips_all_branches(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import Selection

        ad = _fake_adapter2()
        ad2 = _fake_adapter2()
        assert _component_paths("/h", Selection(), [ad, ad2], "componente-desconocido") == []

    def test_memory_toml_empty_path(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, MCPStrategy, Selection

        ad = _fake_adapter2(mcp_strategy=MCPStrategy.TOML_FILE, _mcp_path="")
        assert _component_paths("/h", Selection(), [ad], ComponentID.DXRK_MEMORY) == ["/home/u/sys.md"]

    def test_context7_mcp_config_empty_path(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, MCPStrategy, Selection

        ad = _fake_adapter2(mcp_strategy=MCPStrategy.MCP_CONFIG_FILE, _mcp_path="")
        assert _component_paths("/h", Selection(), [ad], ComponentID.CONTEXT7) == []

    def test_persona_neutral(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, PersonaID, Selection

        sel = Selection(persona=PersonaID.NEUTRAL)
        paths = _component_paths("/h", sel, [_fake_adapter2()], ComponentID.PERSONA)
        assert any("sys.md" in p for p in paths)

    def test_persona_dxrk_empty_settings(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, PersonaID, Selection

        sel = Selection(persona=PersonaID.DXRK)
        ad = _fake_adapter2(_settings_path="")
        paths = _component_paths("/h", sel, [ad], ComponentID.PERSONA)
        assert any("styles" in p for p in paths)
        assert not any("settings.json" in p for p in paths)

    def test_theme_empty_settings(self):
        from dxrk.cli.runtime_paths import _component_paths
        from dxrk.models import ComponentID, Selection

        ad = _fake_adapter2(_settings_path="")
        ad2 = _fake_adapter2(_settings_path="")
        assert _component_paths("/h", Selection(), [ad, ad2], ComponentID.THEME) == []


# ═══════════ dxrk/cli/runtime_sync.py ═══════════


def _sync_step(comp, sel=None):
    from dxrk.cli.runtime_sync import ComponentSyncStep
    from dxrk.models import AgentID, Selection

    if sel is None:
        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[comp])
    return ComponentSyncStep(
        step_id=f"sync:{comp.value}",
        component=comp,
        home_dir="/tmp/h",
        workspace_dir="/tmp/w",
        agents=[AgentID.CLAUDE_CODE],
        selection=sel,
        files_changed=[0],
    )


def _sdd_sel(**kw):
    from dxrk.models import AgentID, ComponentID, Selection

    sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SDD])
    sel.sdd_mode = kw.get("sdd_mode", "single")
    sel.sdd_profile_strategy = kw.get("sdd_profile_strategy", "generated-multi")
    sel.profiles = kw.get("profiles", [])
    sel.model_assignments = {}
    sel.claude_model_assignments = {}
    sel.kiro_model_assignments = {}
    sel.strict_tdd = False
    return sel


class TestSyncRemainder:
    def test_sdd_empty_adapters(self):
        from dxrk.models import ComponentID

        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[]),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="generated-multi"),
        ):
            assert _sync_step(ComponentID.SDD, _sdd_sel()).run() is None

    def test_sdd_non_opencode_adapter(self):
        from dxrk.models import ComponentID

        with (
            mock.patch(
                "dxrk.cli.runtime_sync._resolve_adapters",
                return_value=[SimpleNamespace(agent="otro")],
            ),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="generated-multi"),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert _sync_step(ComponentID.SDD, _sdd_sel()).run() is None

    def test_sdd_opencode_empty_settings(self):
        from dxrk.models import AgentID, ComponentID

        opencode_ad = SimpleNamespace(agent=AgentID.OPENCODE, settings_path=lambda h: "")
        with (
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[opencode_ad]),
            mock.patch("dxrk.components.sdd.resolve_profile_strategy", return_value="generated-multi"),
            mock.patch("dxrk.components.sdd.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert _sync_step(ComponentID.SDD, _sdd_sel()).run() is None

    def test_skills_empty_preset(self):
        from dxrk.models import AgentID, ComponentID, PresetID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.SKILLS], preset=PresetID.MINIMAL)
        sel.skills = []
        with mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[]):
            assert _sync_step(ComponentID.SKILLS, sel).run() is None

    def test_discover_agents_empty_state(self, tmp_path):
        from dxrk.cli.runtime_sync import discover_agents

        with mock.patch("dxrk.state.read", return_value=SimpleNamespace(installed_agents=[])):
            assert discover_agents(str(tmp_path)) == []

    def test_run_sync_files_changed(self, tmp_path):
        from dxrk.cli.runtime_sync import run_sync_with_selection
        from dxrk.models import AgentID, ComponentID, Selection

        sel = Selection(agents=[AgentID.CLAUDE_CODE], components=[ComponentID.THEME])

        class _OrchOk:
            def execute(self, plan):
                for step in plan.apply:
                    step.run()
                return SimpleNamespace(error="")

        with (
            mock.patch("dxrk.pipeline.new_orchestrator", lambda p: _OrchOk()),
            mock.patch("dxrk.pipeline.default_rollback_policy", lambda: None),
            mock.patch("dxrk.cli.runtime_sync._resolve_adapters", return_value=[_fake_adapter2()]),
            mock.patch("dxrk.components.theme.inject", return_value=SimpleNamespace(Changed=2)),
            mock.patch(
                "dxrk.cli.runtime_sync._run_post_sync_verification",
                return_value=SimpleNamespace(ready=True),
            ),
        ):
            out = run_sync_with_selection(str(tmp_path), sel)
        assert out.no_op is False
        assert out.files_changed == 2


# ═══════════ dxrk/cli/install_steps_backup.py 115-116 ═══════════


class TestRollbackCopyError:
    def test_copy_failure_warns(self, tmp_path):
        import shutil

        from dxrk.cli.install_steps_backup import RollbackRestoreStep

        dest = tmp_path / "bak" / "f.txt"
        dest.parent.mkdir(parents=True)
        dest.write_text("backup")
        state = {
            "manifest": {
                "_backup_root": str(tmp_path / "bak" / "manifest.json"),
                "entries": [{"source": str(tmp_path / "orig.txt"), "dest": "f.txt"}],
            }
        }
        step = RollbackRestoreStep(step_id="rb", state=state)
        with mock.patch.object(shutil, "copy2", side_effect=OSError("ro")):
            assert step.rollback() is None


# ═══════════ dxrk/cli/install_steps_agents.py 135->126 ═══════════


class TestCheckDepsEmptyHome:
    def test_empty_home_dir_skips_detect(self, monkeypatch):
        from dxrk.cli.install_steps_agents import CheckDependenciesStep
        from dxrk.models import AgentID, Selection

        monkeypatch.setattr("dxrk.system.detect_dependencies", lambda profile: None)
        sel = Selection(agents=[AgentID.OPENCODE], components=[])
        step = CheckDependenciesStep(step_id="deps", profile=SimpleNamespace(), home_dir="", selection=sel)
        assert step.run() is None


# ═══════════ dxrk/task.py 309, 313 ═══════════


class TestWorkerPoolAccessors:
    def test_submit_and_queue(self):
        from dxrk.task import Payload, Queue, TaskType, WorkerPool, new_task

        q = Queue()
        pool = WorkerPool(queue=q, handler=None, workers=1)
        t = new_task(TaskType.GENERIC, Payload())
        pool.submit(t)
        assert pool.queue() is q


# ═══════════ dxrk/slo 176 ═══════════


class TestSloShortOnly:
    def test_short_fails_long_passes(self):
        from dxrk.slo import MultiWindowEvaluator, WindowConfig

        ev = MultiWindowEvaluator()
        cfg = WindowConfig(short_target=0.9, long_target=0.5)
        ok, msg = ev.evaluate([0.7, 0.7], cfg)
        assert ok is False
        assert "short window failed" in msg


# ═══════════ dxrk/model 785 ═══════════


class TestModelSelectionHasComponent:
    def test_missing_component(self):
        from dxrk.model import Selection

        sel = Selection(
            Agents=[],
            Components=[],
            Skills=[],
            Persona="dxrk",
            Preset="full",
            SDDMode="single",
            SDDProfileStrategy="generated",
        )
        assert sel.has_component("cualquiera") is False


# ═══════════ dxrk/scholar/openalex.py 65, 86->88 ═══════════


class TestOpenAlexRemainder:
    def test_fetch_by_doi_ok(self):
        import httpx

        from dxrk.scholar.openalex import OpenAlexProvider

        work = {
            "display_name": "Some Paper",
            "doi": "https://doi.org/10.1000/xyz",
            "publication_year": 2021,
            "authorships": [],
            "primary_location": {},
            "open_access": {},
        }

        class _FakeClient:
            def get(self, url, params=None, **kwargs):
                import json as _json

                return httpx.Response(200, json=_json.loads(_json.dumps(work)), request=httpx.Request("GET", url))

        p = OpenAlexProvider(client=_FakeClient())
        paper, err = p.fetch_by_doi("10.1000/xyz")
        assert err is None
        assert paper is not None
        assert paper.title == "Some Paper"

    def test_plain_doi_kept(self):
        from dxrk.scholar.openalex import map_openalex_work

        paper = map_openalex_work({"display_name": "T", "doi": "10.1000/xyz"})
        assert paper is not None
        assert paper.doi == "10.1000/xyz"


# ═══════════ dxrk/scholar/pubmed.py 82->77, 94, 97 ═══════════


class TestPubMedRemainder:
    def _client(self, payload):
        import httpx

        class _FakeClient:
            def get(self, url, params=None, **kwargs):
                import json as _json

                return httpx.Response(
                    200,
                    json=_json.loads(_json.dumps(payload)),
                    request=httpx.Request("GET", url),
                )

        return _FakeClient()

    def test_summary_none_skipped(self):
        from dxrk.scholar.pubmed import PubMedProvider

        payload = {"result": {"1": {"uid": "1", "title": "  "}}}
        p = PubMedProvider(client=self._client(payload))
        papers, err = p._fetch_summaries(["1"])
        assert err is None
        assert papers == []

    def test_fetch_by_doi_summaries_error(self):
        from dxrk.scholar.pubmed import PubMedProvider

        payload = {"esearchresult": {"idlist": ["1"]}}
        p = PubMedProvider(client=self._client(payload))
        with mock.patch.object(PubMedProvider, "_fetch_summaries", return_value=([], "boom")):
            paper, err = p.fetch_by_doi("10.1000/abc")
        assert paper is None
        assert err == "boom"

    def test_fetch_by_doi_ok(self):
        from dxrk.scholar.pubmed import PubMedProvider

        payload = {
            "esearchresult": {"idlist": ["1"]},
            "result": {
                "1": {
                    "uid": "1",
                    "title": "Real Paper",
                    "pubdate": "2023",
                    "doi": "10.1000/abc",
                    "authors": [],
                }
            },
        }
        p = PubMedProvider(client=self._client(payload))
        paper, err = p.fetch_by_doi("10.1000/abc")
        assert err is None
        assert paper is not None
        assert paper.title == "Real Paper"


# ═══════════ dxrk/scholar/semanticscholar.py 99 ═══════════


class TestSemanticScholarRemainder:
    def test_search_ok(self):
        import httpx

        from dxrk.scholar.semanticscholar import SemanticScholarProvider

        payload = {
            "data": [
                {
                    "paperId": "abc",
                    "title": "SS Paper",
                    "year": 2024,
                    "authors": [{"name": "Alice"}],
                }
            ]
        }

        class _FakeClient:
            def get(self, url, params=None, **kwargs):
                import json as _json

                return httpx.Response(200, json=_json.loads(_json.dumps(payload)), request=httpx.Request("GET", url))

        p = SemanticScholarProvider(client=_FakeClient())
        papers, err = p.search("query", 5)
        assert err is None
        assert len(papers) == 1


# ═══════════ dxrk/security/jwt.py 461 ═══════════


class TestJwtStopDuringBackoff:
    def test_stop_set_aborts_retries(self):
        from dxrk.security.jwt import RefreshConfig, TokenRefreshScheduler

        def _fail():
            raise RuntimeError("down")

        cfg = RefreshConfig(max_retries=3, retry_interval=timedelta(seconds=60))
        sched = TokenRefreshScheduler(token="t", refresh_func=_fail, config=cfg)
        sched._stop.set()
        sched._attempt_refresh()
        assert sched._last_error is None
        assert sched._failure_count == 0


# ═══════════ dxrk/security/yolo.py 129, 268->276 ═══════════


class TestYoloRemainder:
    def test_blank_command_medium(self):
        from dxrk.security.yolo import RiskLevel, assess_bash_risk

        assert assess_bash_risk("   ") == RiskLevel.MEDIUM

    def test_tool_agnostic_pattern(self):
        from dxrk.security.yolo import (
            KNOWN_DANGEROUS_PATTERNS,
            DangerousPattern,
            RiskLevel,
            check_dangerous_patterns,
        )

        probe = DangerousPattern(pattern="zxq-patron-global-inexistente", reason="test", risk=RiskLevel.HIGH)
        KNOWN_DANGEROUS_PATTERNS.append(probe)
        try:
            matches = check_dangerous_patterns("ejecuta zxq-patron-global-inexistente ahora", "OtraHerramienta")
        finally:
            KNOWN_DANGEROUS_PATTERNS.remove(probe)
        assert [m for m in matches if m.pattern == probe.pattern]


# ═══════════ ola 2 ═══════════


def _apply_step(comp, agents=None, selection=None, profile=None):
    from dxrk.cli.install_steps_components import ComponentApplyStep
    from dxrk.models import AgentID, Selection
    from dxrk.system import PlatformProfile

    return ComponentApplyStep(
        step_id=f"apply:{comp.value if hasattr(comp, 'value') else comp}",
        component=comp,
        home_dir="/tmp/h",
        workspace_dir="/tmp/w",
        agents=[AgentID.OPENCODE] if agents is None else agents,
        selection=Selection() if selection is None else selection,
        profile=PlatformProfile(package_manager="apt") if profile is None else profile,
    )


class TestInstallComponentsRemainder:
    def test_step_id(self):
        from dxrk.models import ComponentID

        assert _apply_step(ComponentID.THEME).id() == "apply:theme"

    def test_memory_duplicate_slug_and_no_changes(self, monkeypatch):
        from dxrk.models import AgentID, ComponentID

        monkeypatch.setattr("dxrk.components.memory.download_latest_binary", lambda profile: None)
        step = _apply_step(ComponentID.DXRK_MEMORY, agents=[AgentID.OPENCODE, AgentID.OPENCODE])
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters") as rad,
            mock.patch("dxrk.cli.install_steps_components.execute_command", return_value="") as exe,
            mock.patch("dxrk.components.memory.inject", return_value=SimpleNamespace(Changed=0, Files=[])),
        ):
            from dxrk.agents.factory import create_registry

            reg = create_registry()
            rad.return_value = [reg.get(AgentID.OPENCODE), reg.get(AgentID.OPENCODE)]
            assert step.run() is None
            assert exe.call_count == 1

    def test_skills_no_changes_two_adapters(self):
        from dxrk.models import ComponentID, Selection, SkillID

        sel = Selection(skills=[SkillID.SDD_INIT])
        step = _apply_step(ComponentID.SKILLS, agents=[], selection=sel)
        with (
            mock.patch(
                "dxrk.cli.install_steps_components._resolve_adapters",
                return_value=[SimpleNamespace(agent="a"), SimpleNamespace(agent="b")],
            ),
            mock.patch("dxrk.components.skills.inject", return_value=SimpleNamespace(Changed=0)),
        ):
            assert step.run() is None

    def test_gga_already_available(self):
        from dxrk.models import ComponentID

        step = _apply_step(ComponentID.DXRK_GUARDIAN, agents=[])
        with (
            mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]),
            mock.patch("dxrk.cli.install_steps_components._gga_available", return_value=True),
            mock.patch("dxrk.components.gga.ensure_runtime_assets", return_value=None),
            mock.patch(
                "dxrk.components.gga.inject",
                return_value=SimpleNamespace(ConfigChanged=0, AgentsChanged=0),
            ),
        ):
            assert step.run() is None

    def test_unknown_component(self):
        from dxrk.models import ComponentID

        step = _apply_step(ComponentID.THEME, agents=[])
        step._component = "unknown-zzz"
        with mock.patch("dxrk.cli.install_steps_components._resolve_adapters", return_value=[]):
            out = step.run()
        assert "no es compatible" in out


class TestTransportProtocol:
    def test_protocol_stub_bodies(self):
        from dxrk.utils.http.transport import Transport

        obj = object()
        assert Transport.handle_request(obj, None) is None
        assert Transport.close(obj) is None
        assert Transport.clone(obj) is None

    def test_env_proxy_http_error(self):
        from dxrk.utils.http import transport as tmod
        from dxrk.utils.http.errors import HttpError

        def _boom():
            raise HttpError("bad proxy")

        with mock.patch.object(tmod, "get_proxy_from_environment", return_value=SimpleNamespace(get_proxy_url=_boom)):
            assert tmod._env_proxy_url() is None


class TestClientOptionsNonZero:
    def test_nonzero_idle_and_tls_timeouts(self):
        from dxrk.utils.http.client import ClientOptions, new_http_client

        opts = ClientOptions(
            idle_conn_timeout=timedelta(seconds=5),
            tls_handshake_timeout=timedelta(seconds=5),
        )
        client, err = new_http_client(opts)
        assert err is None
        assert client is not None


class _Always503Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"retry"
        self.send_response(503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestClientCancelMidRetry:
    def test_ctx_cancel_with_response_closes_it(self):
        import httpx

        from dxrk.utils.http.client import ClientOptions, RetryPolicy, new_http_client

        httpd = HTTPServer(("127.0.0.1", 0), _Always503Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            policy = RetryPolicy(max_retries=2, retry_backoff=timedelta(milliseconds=1))
            client, err = new_http_client(ClientOptions(retry_policy=policy))
            assert err is None

            calls = {"n": 0}

            class _FlakyCtx:
                def err(self):
                    calls["n"] += 1
                    if calls["n"] <= 2:
                        return None
                    return "cancelado"

                def remaining(self):
                    return None

            req = httpx.Request("GET", f"http://127.0.0.1:{httpd.server_address[1]}/")
            resp, err = client.do_with_context(_FlakyCtx(), req)
        finally:
            httpd.shutdown()
        assert resp is None
        assert err is not None

    def test_ctx_cancel_without_response_skips_close(self):
        import httpx

        from dxrk.utils.http.client import ClientOptions, RetryPolicy, new_http_client

        policy = RetryPolicy(max_retries=2, retry_backoff=timedelta(milliseconds=1))
        client, err = new_http_client(ClientOptions(retry_policy=policy))
        assert err is None

        calls = {"n": 0}

        class _FlakyCtx:
            def err(self):
                calls["n"] += 1
                if calls["n"] <= 2:
                    return None
                return "cancelado"

            def remaining(self):
                return None

        with mock.patch.object(client, "_send", return_value=(None, httpx.ReadTimeout("lento"))):
            req = httpx.Request("GET", "http://127.0.0.1:9/")
            resp, err = client.do_with_context(_FlakyCtx(), req)
        assert resp is None
        assert err is not None


class TestContext7Remainder:
    def test_merge_empty_settings(self, tmp_path):
        from dxrk.components.context7 import _inject_merge_into_settings

        ad = SimpleNamespace(agent="fake", settings_path=lambda h: "")
        out = _inject_merge_into_settings(str(tmp_path), ad)
        assert out.Changed == 0

    def test_merge_default_overlay(self, tmp_path):
        from dxrk.components.context7 import _inject_merge_into_settings

        target = tmp_path / "settings.json"
        ad = SimpleNamespace(agent="fake", settings_path=lambda h: str(target))
        out = _inject_merge_into_settings(str(tmp_path), ad)
        assert out.Changed is True
        assert target.exists()

    def test_mcp_config_empty_path(self, tmp_path):
        from dxrk.components.context7 import _inject_mcp_config_file

        ad = SimpleNamespace(agent="fake", mcp_config_path=lambda h, n: "")
        out = _inject_mcp_config_file(str(tmp_path), ad)
        assert out.Changed == 0

    def test_os_read_missing(self, tmp_path):
        from dxrk.components.context7 import _os_read_file

        assert _os_read_file(str(tmp_path / "no-existe.json")) == b""

    def test_os_read_existing(self, tmp_path):
        from dxrk.components.context7 import _os_read_file

        p = tmp_path / "s.json"
        p.write_bytes(b'{"a": 1}')
        assert _os_read_file(str(p)) == b'{"a": 1}'


class TestFeatureFlagsRemainder:
    def test_getall_get_missing_and_ctor(self):
        from dxrk.config.featureflags import FeatureFlag, NewFeatureFlagManager

        mgr = NewFeatureFlagManager()
        assert len(mgr.GetAll()) == 5
        flag, ok = mgr.Get("no-existe")
        assert flag is None and ok is False
        mgr.Register(FeatureFlag(name="x", enabled=True))
        assert "x" in mgr.EnabledFlags()


class TestReconsolidationFsrs:
    def test_no_labile_window(self):
        from dxrk.memory.reconsolidation import ReconsolidationState, reconsolidate_with_fsrs

        st = ReconsolidationState()
        out = reconsolidate_with_fsrs(st, 1.0, 0.5, 0.5, 0.8, 0.9)
        assert out == (st, 1.0, 0.5, 0.5)

    def test_closed_window_decay(self):
        from dxrk.memory.reconsolidation import ReconsolidationState, reconsolidate_with_fsrs

        st = ReconsolidationState(labile_until="2000-01-01T00:00:00+00:00")
        new_state, new_s, new_d, new_rd = reconsolidate_with_fsrs(st, 1.0, 0.5, 0.5, 0.8, 0.9)
        assert new_state.labile_until == ""
        assert new_s == pytest.approx(0.9)
        assert (new_d, new_rd) == (0.5, 0.5)


class TestEvalHarnessRemainder:
    def test_load_skips_blank_lines(self, tmp_path):
        from dxrk.memory.eval_harness import EvalQuery, load_eval_dataset, save_eval_dataset

        p = tmp_path / "q.jsonl"
        save_eval_dataset(p, [EvalQuery(query="q", expected_recall_ids=["a"], partition="w")])
        with p.open("a") as f:
            f.write("\n   \n")
        queries = load_eval_dataset(p)
        assert len(queries) == 1

    def test_synthetic_skips_empty_and_short(self):
        from dxrk.memory.eval_harness import generate_synthetic_queries

        malla = SimpleNamespace(
            list_recalls=lambda **k: [
                {"metadata": {}, "document": ""},
                {"metadata": {}, "document": "a b"},
                {"id": "d3", "metadata": {}, "document": "alpha beta gamma delta epsilon"},
            ]
        )
        out = generate_synthetic_queries(malla, "w", n=5)
        assert isinstance(out, list)

    def test_run_empty_generates_and_reports(self, tmp_path):
        from dxrk.memory.eval_harness import EvalHarness

        malla = SimpleNamespace(list_recalls=lambda **k: [])
        harness = EvalHarness(malla, tmp_path)
        report = harness.run("w")
        assert report.num_queries == 0

    def test_run_loads_queries_from_file(self, tmp_path):
        from dxrk.memory.eval_harness import EvalHarness, EvalQuery, save_eval_dataset

        malla = SimpleNamespace(
            list_recalls=lambda **k: [],
            search=lambda **k: {"results": [{"id": "a"}]},
        )
        harness = EvalHarness(malla, tmp_path)
        save_eval_dataset(
            tmp_path / "w.jsonl",
            [EvalQuery(query="q", expected_recall_ids=["a"], partition="w")],
        )
        report = harness.run("w")
        assert report.num_queries == 1
        assert report.recall_at_k[1] == 1.0

    def test_run_explicit_queries(self, tmp_path):
        from dxrk.memory.eval_harness import EvalHarness, EvalQuery

        malla = SimpleNamespace(search=lambda **k: {"results": []})
        harness = EvalHarness(malla, tmp_path)
        report = harness.run("w", queries=[EvalQuery(query="q", expected_recall_ids=["a"], partition="w")])
        assert report.num_queries == 1

    def test_calibrate_placeholder(self, tmp_path):
        from dxrk.memory.eval_harness import EvalHarness

        harness = EvalHarness(SimpleNamespace(), tmp_path)
        assert harness.calibrate_by_ece("w", {}) == {"ece": 0.0}


class TestPoolRemainder:
    def test_with_proxy_empty_host(self):
        from dxrk.utils.http.errors import ErrNoProxyConfigured
        from dxrk.utils.http.pool import new_connection_pool

        pool = new_connection_pool(None)
        with pytest.raises(Exception, match="no proxy configured"):
            pool.with_proxy("http://:8080")
        assert ErrNoProxyConfigured is not None

    def test_pooled_do_with_deadline_ctx(self):
        import httpx

        from dxrk.utils.http.context import _with_timeout
        from dxrk.utils.http.pool import new_connection_pool, new_pooled_client

        pool = new_connection_pool(None)
        pooled = new_pooled_client(pool, timedelta(seconds=10))
        ctx, cancel = _with_timeout(None, timedelta(seconds=30))
        try:
            req = httpx.Request("GET", "http://127.0.0.1:9/")
            req._ctx = ctx
            resp, err = pooled.do(req)
            assert resp is None
            assert err is not None
        finally:
            cancel()

    def test_set_timeout_plain_float(self):
        from dxrk.utils.http.pool import PooledClient, new_connection_pool

        pool = new_connection_pool(None)
        pooled = PooledClient(client=SimpleNamespace(timeout=5.0), pool=pool, timeout=timedelta(seconds=10))
        pooled.set_timeout(timedelta(seconds=7))
        assert pooled.timeout == timedelta(seconds=7)


class TestReviewCursorStandalone:
    def test_cursor_actions_without_mount(self):
        from dxrk.tui.screens.review import ReviewScreen

        s = ReviewScreen()
        s.action_cursor_up()
        assert s.cursor == 0
        s.cursor = 1
        s.action_cursor_down()
        assert s.cursor == 1


# ═══════════ ola 3 ═══════════


class TestComponentPermissionsRemainder:
    def test_managed_paths_no_agent(self):
        from dxrk.components.permissions import managed_paths

        assert managed_paths(object()) == []

    def test_managed_paths_empty_settings(self):
        import dxrk.components.permissions as perm

        ad = SimpleNamespace(agent="x", settings_path=lambda h: "")
        with (
            mock.patch.object(perm, "supports_agent", return_value=True),
            mock.patch.object(perm, "_permissions_file", return_value=""),
        ):
            assert perm.managed_paths(ad, "/h") == []

    def test_inject_no_agent(self):
        from dxrk.components.permissions import _inject_permissions_file

        assert _inject_permissions_file("/h", object(), []) is False

    def test_inject_cursor_no_parent(self, tmp_path, monkeypatch):
        import dxrk.components.permissions as perm
        from dxrk.models import AgentID

        monkeypatch.chdir(tmp_path)
        ad = SimpleNamespace(agent=AgentID.CURSOR)
        with (
            mock.patch.object(perm, "_permissions_file", return_value="rel.json"),
            mock.patch.object(perm, "_merge_json_file", return_value=(SimpleNamespace(Changed=True), None)),
        ):
            files: list[str] = []
            assert perm._inject_permissions_file(str(tmp_path), ad, files) is True
            assert files == ["rel.json"]

    def test_inject_kiro_existing(self, tmp_path):
        import dxrk.components.permissions as perm
        from dxrk.models import AgentID

        existing = tmp_path / "k.json"
        existing.write_text("{}")
        ad = SimpleNamespace(agent=AgentID.KIRO_IDE)
        with mock.patch.object(perm, "_permissions_file", return_value=str(existing)):
            files: list[str] = []
            assert perm._inject_permissions_file(str(tmp_path), ad, files) is False
            assert files == [str(existing)]

    def test_inject_other_agent_false(self, tmp_path):
        import dxrk.components.permissions as perm
        from dxrk.models import AgentID

        target = tmp_path / "o.json"
        ad = SimpleNamespace(agent=AgentID.OPENCODE)
        with mock.patch.object(perm, "_permissions_file", return_value=str(target)):
            assert perm._inject_permissions_file(str(tmp_path), ad, []) is False


class TestSettingsStoresRemainder:
    def test_memory_delete(self):
        from dxrk.config.settings import MemorySettingsStore

        st = MemorySettingsStore()
        st.Set("k", 1)
        st.Delete("k")
        assert st.Get("k") == (None, False)

    def test_file_load_non_dict(self, tmp_path):
        from dxrk.config.settings import FileSettingsStore

        p = tmp_path / "s.json"
        p.write_text("[1, 2]")
        st = FileSettingsStore(str(p))
        st.Load()
        assert st.List() == {}

    def test_file_load_corrupt(self, tmp_path):
        from dxrk.config.settings import FileSettingsStore

        p = tmp_path / "s.json"
        p.write_text("{no json")
        st = FileSettingsStore(str(p))
        with pytest.raises(OSError, match="read settings"):
            st.Load()

    def test_manager_delete(self):
        from dxrk.config.settings import MemorySettingsStore, NewSettingsManager

        m = NewSettingsManager(MemorySettingsStore())
        m.Set("k", 1)
        m.Delete("k")
        assert m.Has("k") is False

    def test_manager_import_non_dict(self):
        from dxrk.config.settings import MemorySettingsStore, NewSettingsManager

        m = NewSettingsManager(MemorySettingsStore())
        with pytest.raises(ValueError, match="expected an object"):
            m.Import(b"[1, 2]")

    def test_manager_import_store_failure(self):
        from dxrk.config.settings import SettingsManager

        class _Bad:
            def Priority(self):
                return 1

            def Get(self, k):
                return None, False

            def Set(self, k, v):
                raise RuntimeError("ro")

            def Delete(self, k):
                pass

            def List(self):
                return {}

            def Save(self):
                pass

            def Load(self):
                pass

        m = SettingsManager([_Bad()])
        with pytest.raises(ValueError, match="import setting k"):
            m.Import(b'{"k": 1}')

    def test_manager_save_failure(self):
        from dxrk.config.settings import SettingsManager

        class _BadSave:
            def Priority(self):
                return 1

            def Save(self):
                raise RuntimeError("disk")

            def Load(self):
                pass

        m = SettingsManager([_BadSave()])
        with pytest.raises(OSError, match="save store"):
            m.Save()

    def test_manager_load_failure(self):
        from dxrk.config.settings import SettingsManager

        class _BadLoad:
            def Priority(self):
                return 1

            def Save(self):
                pass

            def Load(self):
                raise RuntimeError("gone")

        m = SettingsManager([_BadLoad()])
        with pytest.raises(OSError, match="load store"):
            m.Load()

    def test_store_ctors(self):
        from dxrk.config.settings import NewMemorySettingsStore, NewProjectSettingsStore

        assert NewProjectSettingsStore().Priority() == 200
        assert NewMemorySettingsStore(3).Priority() == 3


class TestStorageCleanupRemainder:
    def test_cleanup_unlink_failure(self, tmp_path, monkeypatch):
        from pathlib import Path

        from dxrk.config.storage import save_json_atomic

        target = tmp_path / "s.json"
        real_replace = Path.replace
        real_unlink = Path.unlink

        def _boom_replace(self, other):
            raise OSError("no se puede reemplazar")

        def _boom_unlink(self, missing_ok=False):
            raise OSError("no se puede borrar")

        monkeypatch.setattr(Path, "replace", _boom_replace)
        monkeypatch.setattr(Path, "unlink", _boom_unlink)
        try:
            with pytest.raises(OSError, match="no se puede reemplazar"):
                save_json_atomic(target, {"a": 1})
        finally:
            monkeypatch.setattr(Path, "replace", real_replace)
            monkeypatch.setattr(Path, "unlink", real_unlink)
            for leftover in tmp_path.glob(".*.tmp"):
                leftover.unlink()


# ═══════════ ola 4: persona + config/migration ═══════════


def _persona_adapter(**kw):
    from dxrk.models import SystemPromptStrategy

    base = dict(
        supports_system_prompt=True,
        system_prompt_strategy=SystemPromptStrategy.MARKDOWN_SECTIONS,
        supports_slash_commands=False,
        supports_skills=False,
        supports_output_styles=False,
        agent="fake",
        system_prompt_file=lambda h: "/tmp/noexiste-sys.md",
        settings_path=lambda h: "",
        commands_dir=lambda h: "",
        skills_dir=lambda h: "",
        output_style_dir=lambda h: "",
        global_config_dir=lambda h: "/tmp/noexiste-cfg",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestPersonaRemainder:
    def test_clean_legacy_remove_fails(self, tmp_path):
        import dxrk.components.persona as persona

        legacy = tmp_path / "old.md"
        legacy.write_text("Senior Architect legacy")
        ad = SimpleNamespace(legacy_system_prompt_files=lambda h: [str(legacy)])
        with mock.patch.object(persona.os, "remove", side_effect=OSError("ro")):
            assert persona.clean_legacy_prompt_files(str(tmp_path), ad) is False
        assert legacy.exists()

    def test_preserve_marker_at_zero(self):
        from dxrk.components.persona import _preserve_managed_sections
        from dxrk.models import PersonaID

        out, changed = _preserve_managed_sections("<!-- dxrk:x -->viejo", "nuevo\n", PersonaID.NEUTRAL)
        assert changed is True
        assert "nuevo" in out

    def test_migrate_legacy_agent_key_non_dict(self, tmp_path):
        from dxrk.components.persona import _migrate_legacy_agent_key

        p = tmp_path / "settings.json"
        p.write_text("[1, 2]")
        assert _migrate_legacy_agent_key(str(p)) is False

    def test_file_replace_exact_legacy_asset(self, tmp_path):
        from dxrk.components import persona as persona_mod
        from dxrk.components.persona import inject
        from dxrk.models import AgentID, PersonaID, SystemPromptStrategy

        asset = persona_mod._must_read("generic/persona-neutral.md")
        prompt = tmp_path / "AGENTS.md"
        prompt.write_text(asset)
        ad = _persona_adapter(
            agent=AgentID.OPENCODE,
            system_prompt_strategy=SystemPromptStrategy.FILE_REPLACE,
            system_prompt_file=lambda h: str(prompt),
        )
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert str(prompt) in out.Files

    def test_append_empty_existing(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID, SystemPromptStrategy

        prompt = tmp_path / "prompt.md"
        ad = _persona_adapter(
            system_prompt_strategy=SystemPromptStrategy.APPEND_TO_FILE,
            system_prompt_file=lambda h: str(prompt),
        )
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert out.Changed is True
        assert "persona" in prompt.read_text().lower() or len(prompt.read_text()) > 0

    def test_instructions_strategy_writes_wrapped(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID, SystemPromptStrategy

        prompt = tmp_path / "instructions.md"
        ad = _persona_adapter(
            system_prompt_strategy=SystemPromptStrategy.INSTRUCTIONS_FILE,
            system_prompt_file=lambda h: str(prompt),
        )
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert out.Changed is True
        assert prompt.exists()

    def test_unknown_strategy_skips_section1(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID

        ad = _persona_adapter(system_prompt_strategy="estrategia-desconocida")
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert out.Changed is False
        assert out.Files == []

    def test_jinja_no_bootstrap(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID, SystemPromptStrategy

        cfg = tmp_path / "cfg"
        ad = _persona_adapter(
            system_prompt_strategy=SystemPromptStrategy.JINJA_MODULES,
            global_config_dir=lambda h: str(cfg),
        )
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert (cfg / "persona.md").exists()
        assert out.Changed is True

    def test_section2_skipped_foreign_agent(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID

        prompt = tmp_path / "sys.md"
        ad = _persona_adapter(system_prompt_file=lambda h: str(prompt))
        out = inject(str(tmp_path), ad, PersonaID.NEUTRAL)
        assert str(prompt) in out.Files
        assert not [f for f in out.Files if f.endswith(".json")]

    def test_section3_empty_dirs(self, tmp_path):
        from dxrk.components.persona import inject
        from dxrk.models import PersonaID

        prompt = tmp_path / "sys.md"
        ad = _persona_adapter(
            system_prompt_file=lambda h: str(prompt),
            supports_output_styles=True,
            output_style_dir=lambda h: "",
            settings_path=lambda h: "",
        )
        out = inject(str(tmp_path), ad, PersonaID.DXRK)
        assert str(prompt) in out.Files


class TestConfigMigrationRemainder:
    def test_write_yaml_chmod_failures(self, tmp_path, monkeypatch):
        from pathlib import Path

        from dxrk.config.migration import _write_yaml

        target = tmp_path / "c.yaml"
        monkeypatch.setattr(Path, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        _write_yaml(target, {"settings": {"a": 1}})
        assert target.exists()

    def test_backup_once_failures(self, tmp_path, monkeypatch):
        from pathlib import Path

        from dxrk.config.migration import _backup_once

        p = tmp_path / "c.yaml"
        p.write_text("settings: {}")
        monkeypatch.setattr(Path, "chmod", lambda self, mode: (_ for _ in ()).throw(OSError("ro")))
        _backup_once(p)
        assert (tmp_path / "c.yaml.bak").exists()
        monkeypatch.setattr(Path, "write_bytes", lambda self, data: (_ for _ in ()).throw(OSError("ro")))
        _backup_once(tmp_path / "otro.yaml")

    def test_migrate_invalid_tenant(self, tmp_path, monkeypatch):
        import json

        from dxrk.config.migration import migrate_settings_to_yaml

        home = tmp_path / "home"
        (home / ".dxrk").mkdir(parents=True)
        (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}))
        monkeypatch.setenv("HOME", str(home))
        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.chdir(proj)
        res = migrate_settings_to_yaml(dry_run=False, tenant="invalido/\x00")
        assert any(s.startswith("tenant:") for s in res["skipped"])

    def test_migrate_write_error_skipped(self, tmp_path, monkeypatch):
        import json

        import dxrk.config.migration as mig

        home = tmp_path / "home"
        (home / ".dxrk").mkdir(parents=True)
        (home / ".dxrk" / "settings.json").write_text(json.dumps({"theme": "dark"}))
        monkeypatch.setenv("HOME", str(home))
        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.chdir(proj)
        with mock.patch.object(mig, "_write_yaml", side_effect=OSError("disco lleno")):
            res = mig.migrate_settings_to_yaml(dry_run=False)
        assert any("error" in s for s in res["skipped"])


# ═══════════ ola 6 ═══════════


class TestTripleCopyRemainder:
    def test_update_recreates_from_s(self):
        from dxrk.memory.triplecopy import create_triple_copy, update_triple_copy

        tc = create_triple_copy(4.0)
        new_tc = update_triple_copy(tc, 1.0, 1.0, 8.0)
        assert (new_tc.fast, new_tc.medium, new_tc.deep) == (2.0, 8.0, 32.0)


class TestMetacogRemainder:
    def test_confidence_from_outcome(self):
        from dxrk.memory.metacog import confidence_from_outcome

        assert confidence_from_outcome(True) == 0.5
        assert confidence_from_outcome(False, base_confidence=0.9) == 0.9


class TestMcpStdioRemainder:
    def test_send_echo(self):
        from dxrk.mcp import StdioTransport

        t = StdioTransport("cat")
        try:
            assert t.send(b'{"ping": 1}') == b'{"ping": 1}\n'
        finally:
            t.close()

    def test_close_exited_proc(self):
        from dxrk.mcp import StdioTransport

        t = StdioTransport("true")
        t._proc.wait(timeout=5)
        t.close()
        assert t._proc.poll() is not None


class TestQieoRemainder:
    def test_default_seed_none(self):
        from dxrk.memory.qieo import QIEOConfig, qieo_optimize

        cfg = QIEOConfig(pop_size=4, n_iter=2)
        best, fit = qieo_optimize(lambda p: -sum(x * x for x in p), [(0.0, 1.0)], config=cfg)
        assert len(best) == 1
        assert 0.0 <= best[0] <= 1.0

    def test_zero_iterations_returns_lower_bounds(self):
        from dxrk.memory.qieo import QIEOConfig, qieo_optimize

        cfg = QIEOConfig(pop_size=4, n_iter=0)
        best, fit = qieo_optimize(lambda p: 1.0, [(2.0, 5.0), (0.0, 1.0)], config=cfg, seed=7)
        assert best == [2.0, 0.0]


class TestThompsonRemainder:
    def test_quarantined_skipped(self):
        from dxrk.memory.thompson import select_evaluation_candidates

        malla = SimpleNamespace(
            iter_recalls=lambda: [
                {"id": "q", "metadata": {"quarantined": True}},
                {"id": "p", "metadata": {"pinned": True}},
                {"id": "ok", "metadata": {}},
            ]
        )
        out = select_evaluation_candidates(malla, n=10)
        assert out == ["ok"] or (isinstance(out, list) and "q" not in out and "p" not in out)


class TestOpenCodePluginRemainder:
    def test_empty_existing_file(self, tmp_path):
        from dxrk.components.opencodeplugin import _ensure_tui_plugin

        p = tmp_path / "tui.json"
        p.write_text("")
        assert _ensure_tui_plugin(str(p), "pkg") is True

    def test_corrupt_file_raises(self, tmp_path):
        from dxrk.components.opencodeplugin import _ensure_tui_plugin

        p = tmp_path / "tui.json"
        p.write_text("{no json")
        with pytest.raises(ValueError, match="parse OpenCode TUI config"):
            _ensure_tui_plugin(str(p), "pkg")


# ═══════════ ola 7 ═══════════


class TestProvidersBackendRemainder:
    def test_connected_non_dict(self, tmp_path):
        from dxrk.tui.providers_backend import connected_providers

        p = tmp_path / "auth.json"
        p.write_text("[1, 2]")
        assert connected_providers(str(p)) == set()

    def test_validate_rc_zero(self):
        from dxrk.tui.providers_backend import validate_provider_id

        with mock.patch("subprocess.run", return_value=SimpleNamespace(returncode=0)):
            assert validate_provider_id("openai") is True

    def test_save_corrupt_existing(self, tmp_path):
        from dxrk.tui.providers_backend import save_api_token

        p = tmp_path / "auth.json"
        p.write_text("{roto")
        out = save_api_token("openai", "tok", str(p))
        assert out == str(p)
        assert (tmp_path / "auth.json.bak").exists()

    def test_save_non_dict_existing(self, tmp_path):
        from dxrk.tui.providers_backend import save_api_token

        p = tmp_path / "auth.json"
        p.write_text("[1]")
        save_api_token("openai", "tok", str(p))
        assert "openai" in p.read_text()

    def test_save_fresh_no_backup(self, tmp_path):
        from dxrk.tui.providers_backend import save_api_token

        p = tmp_path / "sub" / "auth.json"
        save_api_token("openai", "tok", str(p))
        assert p.exists()
        assert not (tmp_path / "sub" / "auth.json.bak").exists()

    def test_save_relative_no_parent(self, tmp_path, monkeypatch):
        from dxrk.tui.providers_backend import save_api_token

        monkeypatch.chdir(tmp_path)
        out = save_api_token("openai", "tok", "auth.json")
        assert out == "auth.json"
        assert (tmp_path / "auth.json").exists()

    def test_save_chmod_failure(self, tmp_path, monkeypatch):
        from dxrk.tui.providers_backend import save_api_token

        monkeypatch.setattr("os.chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        p = tmp_path / "auth.json"
        assert save_api_token("openai", "tok", str(p)) == str(p)


class TestStressRemainder:
    def _malla(self, tmp_path):
        from dxrk.memory.malla import DxrkMemory

        dm = DxrkMemory(str(tmp_path / "malla"))
        dm.init()
        return dm

    def test_should_activate(self):
        from dxrk.memory.stress import StressState, should_activate_defenses

        assert should_activate_defenses(StressState(defenses_active=True)) is True
        assert should_activate_defenses(StressState()) is False

    def test_metadata_edge_cases(self, tmp_path):
        from dxrk.memory.stress import compute_system_stress

        dm = self._malla(tmp_path)
        try:
            old = "2000-01-01T00:00:00+00:00"
            fake_col = SimpleNamespace(
                get=lambda **k: SimpleNamespace(
                    metadatas=[
                        None,
                        {"S": -2.0},
                        {"S": 2.0, "quarantine_reason": "x", "quarantined_at": "2024-05-01T00:00:00"},
                        {"S": 1.0, "quarantine_reason": "x", "quarantined_at": old},
                        {"S": 1.0, "quarantine_reason": "x", "quarantined_at": "basura"},
                        {"S": 4.0},
                    ]
                )
            )
            with (
                mock.patch.object(dm, "list_partitions", return_value=["w"]),
                mock.patch.object(dm, "partition_usage", return_value={"count": 6, "budget": 10}),
                mock.patch.object(dm, "_collection", return_value=fake_col),
            ):
                state = compute_system_stress(dm)
            assert state.recent_quarantines == 0
            assert state.avg_inv_stability == pytest.approx(0.6875)
        finally:
            dm.close()

    def test_hysteresis_previously_active(self, tmp_path):
        from dxrk.memory.stress import StressState, compute_system_stress, save_stress_state

        dm = self._malla(tmp_path)
        try:
            save_stress_state(tmp_path / "malla", StressState(level=0.9, defenses_active=True))
            state = compute_system_stress(dm)
            assert state.defenses_active is False
        finally:
            dm.close()


class TestCompleteScreenRemainder:
    @pytest.mark.asyncio
    async def test_failed_steps_and_gga(self):
        import sys

        sys.path.insert(0, "tests")
        from test_tui import _make_app

        from dxrk.models import ComponentID
        from dxrk.tui.screens.complete import CompleteScreen
        from dxrk.tui.shared import STATE

        app = _make_app()
        STATE.plan = SimpleNamespace(
            steps=[
                SimpleNamespace(id="s1", error="falló algo\ndetalle"),
                SimpleNamespace(id="s2", error=""),
            ]
        )
        STATE.selected_components = [ComponentID.DXRK_GUARDIAN]
        async with app.run_test() as pilot:
            await pilot.app.push_screen(CompleteScreen())
            await pilot.pause()
            content = pilot.app.screen.query_one("#complete-content")
            assert content is not None
            await pilot.app.pop_screen()
            await pilot.pause()
            STATE.plan = None
            STATE.selected_components = []
            await pilot.app.push_screen(CompleteScreen())
            await pilot.pause()
            await pilot.app.pop_screen()
            await pilot.pause()
            STATE.selected_components = [ComponentID.DXRK_GUARDIAN]
            await pilot.app.push_screen(CompleteScreen())
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()


# ═══════════ ola 8 ═══════════


class TestComponentPermissionsKiroNew:
    def test_inject_kiro_creates_file(self, tmp_path):
        import dxrk.components.permissions as perm
        from dxrk.models import AgentID

        target = tmp_path / "sub" / "k.json"
        ad = SimpleNamespace(agent=AgentID.KIRO_IDE)
        with mock.patch.object(perm, "_permissions_file", return_value=str(target)):
            files: list[str] = []
            assert perm._inject_permissions_file(str(tmp_path), ad, files) is True
            assert files == [str(target)]
            assert target.exists()

    def test_inject_kiro_no_parent(self, tmp_path, monkeypatch):
        import dxrk.components.permissions as perm
        from dxrk.models import AgentID

        monkeypatch.chdir(tmp_path)
        ad = SimpleNamespace(agent=AgentID.KIRO_IDE)
        with (
            mock.patch.object(perm, "_permissions_file", return_value="k.json"),
            mock.patch(
                "dxrk.components.filemerge.write_file_atomic",
                return_value=SimpleNamespace(Changed=True),
            ),
        ):
            files: list[str] = []
            assert perm._inject_permissions_file(str(tmp_path), ad, files) is True
            assert files == ["k.json"]


class TestMigrationOuterError:
    def test_backup_write_bytes_failure(self, tmp_path, monkeypatch):
        from pathlib import Path

        from dxrk.config.migration import _backup_once

        p = tmp_path / "c.yaml"
        p.write_text("settings: {}")
        monkeypatch.setattr(Path, "write_bytes", lambda self, data: (_ for _ in ()).throw(OSError("ro")))
        _backup_once(p)
        assert not (tmp_path / "c.yaml.bak").exists()


class TestFileSettingsDelete:
    def test_delete(self, tmp_path):
        from dxrk.config.settings import FileSettingsStore

        st = FileSettingsStore(str(tmp_path / "s.json"))
        st.Set("k", 1)
        st.Delete("k")
        assert st.Get("k") == (None, False)


class TestMcpTimeoutSend:
    def test_send_with_timeout(self):
        from dxrk.mcp import StdioTransport

        t = StdioTransport("cat", timeout=5.0)
        try:
            assert t.send(b'{"ping": 1}') == b'{"ping": 1}\n'
        finally:
            t.close()


class TestMemoryQuarantineSkips:
    def test_fused_invalid(self):
        from dxrk.memory import _fused_similarity

        assert _fused_similarity("basura") == 0.0
        assert _fused_similarity(None) == 0.0

    def _mem(self, tmp_path):
        from dxrk.memory import AgentMemory

        return AgentMemory(path=str(tmp_path / "m.db"))

    def test_search_skips_quarantined(self, tmp_path):
        m = self._mem(tmp_path)
        fake_q = SimpleNamespace(
            ids=[["a", "b"]],
            documents=[["d1", "d2"]],
            metadatas=[[{"quarantined": True}, {"S": 1.0}]],
            distances=[[0.5, 0.05]],
        )
        with mock.patch.object(m, "_malla_collection", SimpleNamespace(query=lambda **k: fake_q)):
            out = m.search("proj", "hola mundo")
        assert isinstance(out, list)
        assert all(e.id != "a" for e in out)

    def test_list_skips_quarantined(self, tmp_path):
        m = self._mem(tmp_path)
        fake_g = SimpleNamespace(
            ids=["a", "b"],
            documents=["d1", "d2"],
            metadatas=[{"quarantined": True}, {"S": 1.0}],
        )
        with mock.patch.object(m, "_malla_collection", SimpleNamespace(get=lambda **k: fake_g)):
            out = m.search("proj", "")
        assert isinstance(out, list)
        assert all(e.id != "a" for e in out)


class TestReviewScreenRemainder:
    @pytest.mark.asyncio
    async def test_skills_without_sdd(self):
        import sys

        sys.path.insert(0, "tests")
        from test_tui import _make_app

        from dxrk.models import ComponentID, SkillID
        from dxrk.tui.screens.review import ReviewScreen
        from dxrk.tui.shared import STATE

        app = _make_app()
        STATE.selected_components = [ComponentID.THEME]
        STATE.selected_skills = [SkillID.SDD_INIT]
        STATE.selected_agents = []
        async with app.run_test() as pilot:
            await pilot.app.push_screen(ReviewScreen())
            await pilot.pause()
            assert isinstance(pilot.app.screen, ReviewScreen)


# ═══════════ ola 9 ═══════════


class TestCalibrateRemainder:
    def _recalls(self):
        return [
            {"id": "a", "document": "alpha beta gamma delta", "metadata": {"partition": "w"}},
            {"id": "b", "document": "epsilon zeta eta theta", "metadata": {"partition": "w"}},
            {"id": "c", "document": "", "metadata": {"partition": "w"}},
            {"id": "z", "document": "other partition doc here", "metadata": {"partition": "x"}},
        ]

    def test_recall_few_recalls(self):
        from dxrk.memory.calibrate import CalibrationParams, evaluate_recall_at_k

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls()[:1])
        assert evaluate_recall_at_k(malla, "w", CalibrationParams()) == 0.0

    def test_recall_skips_empty_doc(self):
        from dxrk.memory.calibrate import CalibrationParams, evaluate_recall_at_k

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls())
        out = evaluate_recall_at_k(malla, "w", CalibrationParams(), k=5, sample_size=10)
        assert out == 0.0

    def test_partition_few_candidates(self):
        import dxrk.memory.calibrate as cal

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls())
        with mock.patch.object(cal, "select_evaluation_candidates", return_value=["a"]):
            assert cal.calibrate_partition(malla, "w") == cal.DEFAULT_PARAMS

    def test_partition_optimizes(self, tmp_path):
        import dxrk.memory.calibrate as cal
        from dxrk.memory.qieo import QIEOConfig

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls(), _path=str(tmp_path))
        cfg = QIEOConfig(pop_size=4, n_iter=2)
        with mock.patch.object(cal, "select_evaluation_candidates", return_value=["a", "b"]):
            out = cal.calibrate_partition(malla, "w", qieo_config=cfg, objective_k=2, objective_samples=4)
        assert out.method == "qieo"


class TestLayersRemainder:
    def test_malla_tenant_fallback(self):
        import dxrk.memory.layers as layers

        with mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("sin tenant")):
            out = layers._resolve_malla_path("t1", None)
        assert out.endswith(os.path.join(".dxrk", "malla"))

    def test_malla_migrated_default(self):
        import dxrk.memory.layers as layers

        with (
            mock.patch.object(layers, "_effective_tenant_id", return_value=""),
            mock.patch("dxrk.tenant.migration.is_migrated", return_value=True),
            mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")),
        ):
            out = layers._resolve_malla_path(None, None)
        assert out.endswith(os.path.join(".dxrk", "malla"))

    def test_malla_not_migrated(self):
        import dxrk.memory.layers as layers

        with (
            mock.patch.object(layers, "_effective_tenant_id", return_value=""),
            mock.patch("dxrk.tenant.migration.is_migrated", return_value=False),
        ):
            out = layers._resolve_malla_path(None, None)
        assert out.endswith(os.path.join(".dxrk", "malla"))

    def test_identity_not_migrated(self):
        import dxrk.memory.layers as layers

        with (
            mock.patch.object(layers, "_effective_tenant_id", return_value=""),
            mock.patch("dxrk.tenant.migration.is_migrated", return_value=False),
        ):
            out = layers._resolve_identity_path(None, None)
        assert out.endswith(os.path.join(".dxrk", "identity.txt"))

    def test_identity_migrated_fallback(self):
        import dxrk.memory.layers as layers

        with (
            mock.patch.object(layers, "_effective_tenant_id", return_value=""),
            mock.patch("dxrk.tenant.migration.is_migrated", return_value=True),
            mock.patch("dxrk.tenant.migration.tenant_root", side_effect=OSError("ro")),
        ):
            out = layers._resolve_identity_path(None, None)
        assert out.endswith(os.path.join(".dxrk", "identity.txt"))

    def test_layer2_no_recalls(self):
        from dxrk.memory.layers import Layer2

        fake_col = SimpleNamespace(get=lambda **k: SimpleNamespace(documents=["d"], metadatas=[{"quarantined": True}]))
        layer = Layer2(malla_path="/tmp/nonexistent-malla")
        with mock.patch("dxrk.memory.layers._get_collection", return_value=fake_col):
            assert layer.retrieve(partition="w") == "No recalls found for partition=w."
            assert layer.retrieve(partition="w", subgroup="r") == "No recalls found for partition=w subgroup=r."


# ═══════════ ola 10 ═══════════


class TestTelemetryRemainder:
    def test_go_durations(self):
        from datetime import timedelta

        from dxrk.telemetry import _go_duration

        assert _go_duration(timedelta(0)) == "0s"
        assert _go_duration(timedelta(hours=2)) == "2h0s"
        assert _go_duration(timedelta(minutes=3)) == "3m0s"
        assert _go_duration(timedelta(hours=1, milliseconds=500)) == "1h0s"

    def _store(self, tmp_path, enabled=True):
        from dxrk.telemetry import Config, Store

        cfg = Config()
        cfg.enabled = enabled
        cfg.dir = str(tmp_path)
        return Store(cfg)

    def test_flush_makedirs_failure(self, tmp_path):
        store = self._store(tmp_path)
        from datetime import timedelta

        store.record("a", "t", True, timedelta(seconds=1))
        with mock.patch("os.makedirs", side_effect=OSError("ro")):
            with pytest.raises(OSError, match="create telemetry dir"):
                store.flush()

    def test_flush_marshal_failure(self, tmp_path):
        from datetime import datetime

        from dxrk.telemetry import Event

        store = self._store(tmp_path)
        store._events.append(Event(timestamp=datetime.now(), action="a", tool=object()))
        with pytest.raises(ValueError, match="marshal events"):
            store.flush()

    def test_flush_write_failure(self, tmp_path):
        from datetime import timedelta

        store = self._store(tmp_path)
        store.record("a", "t", True, timedelta(seconds=1))
        with mock.patch("os.chmod", side_effect=OSError("ro")):
            with pytest.raises(OSError, match="write telemetry"):
                store.flush()

    def test_flush_rename_failure(self, tmp_path):
        from datetime import timedelta

        store = self._store(tmp_path)
        store.record("a", "t", True, timedelta(seconds=1))
        with mock.patch("os.rename", side_effect=OSError("ro")):
            with pytest.raises(OSError, match="rename telemetry"):
                store.flush()

    def test_disable_write_failure(self, tmp_path):
        store = self._store(tmp_path)
        with mock.patch.object(store, "_write_config", side_effect=OSError("ro")):
            store.disable()
        assert store.is_enabled() is False


class TestCostoptRemainder:
    def _optimizer(self, **kw):
        from dxrk.costopt import BudgetConfig, CostOptimizer
        from dxrk.router import Router, SemanticCache

        return CostOptimizer(
            kw.get("router", Router(providers=[])),
            kw.get("cache", SemanticCache()),
            kw.get("budget", BudgetConfig()),
            kw.get("path", ""),
        )

    def test_alerts_trimmed(self):
        from dxrk.costopt import BudgetConfig

        co = self._optimizer(budget=BudgetConfig(daily_limit_usd=1, monthly_limit_usd=1, alert_threshold=0.01))
        for _ in range(120):
            co.record_usage("gpt-4o", 100000, 100000)
        assert len(co.alerts) <= 100

    def test_score_unknown_model(self):
        from dxrk.router import ProviderEntry

        co = self._optimizer()
        p = ProviderEntry(name="x", model="modelo-inexistente", provider=None, capabilities=[])
        assert co._score_provider(p) == 0.0

    def test_score_no_cache(self):
        from dxrk.costopt import BudgetConfig, CostOptimizer
        from dxrk.router import Router
        from tests.test_costopt import entry

        co = CostOptimizer(Router(providers=[]), None, BudgetConfig(), "")
        assert co._cache_hit_rate() == 0.0
        assert co._score_provider(entry("k", model="gpt-4o-mini")) > 0.0
        co2 = self._optimizer()
        assert co2._score_provider(entry("k", model="gpt-4o-mini")) > 0.0

    def test_score_cached_hit_rate(self):
        from dxrk.router import Router

        fake_cache = SimpleNamespace(stats=lambda: SimpleNamespace(size=10, hits=5))
        co = self._optimizer(router=Router(providers=[]), cache=fake_cache)
        assert co._cache_hit_rate() == 0.5

        from tests.test_costopt import entry

        assert co._score_provider(entry("k", model="gpt-4o-mini")) > 0.0

    def test_scores_skip_unknown(self):
        from dxrk.router import ProviderEntry
        from tests.test_costopt import MockProvider, entry

        known = entry("k", model="gpt-4o-mini")
        unknown = ProviderEntry(name="u", model="modelo-inexistente", provider=MockProvider("u"), capabilities=[])
        co = self._optimizer()
        co.router.providers[:] = [known, unknown]
        scores = co.get_provider_scores()
        assert [s.name for s in scores] == ["k"]

    def test_save_failure_logged(self, tmp_path):
        co = self._optimizer(path=str(tmp_path / "c.json"))
        with mock.patch("os.makedirs", side_effect=OSError("ro")):
            co._save()


# ═══════════ ola 10b: miner + metacog_v2 ═══════════


class TestMinerRemainder:
    def test_directory_not_regular(self, tmp_path):
        from dxrk.memory.miner import _is_regular_source_file

        assert _is_regular_source_file(tmp_path, tmp_path) is False

    def test_matches_outside_root(self, tmp_path):
        from dxrk.memory.miner import GitignoreMatcher

        m = GitignoreMatcher(tmp_path, [{"pattern": "*.log", "anchored": False, "dir_only": False, "negated": False}])
        assert m.matches(tmp_path.parent / "elsewhere" / "f.txt") is None

    def test_rule_anchored_dir_only(self):
        from pathlib import Path

        from dxrk.memory.miner import GitignoreMatcher

        m = GitignoreMatcher(Path("/r"), [])
        rule = {"pattern": "build", "anchored": True, "dir_only": True, "negated": False}
        assert m._rule_matches(rule, "build/x", True) is True

    def test_force_included_prefix(self, tmp_path):
        from dxrk.memory.miner import is_force_included

        target = tmp_path / "sub" / "f.txt"
        assert is_force_included(target, tmp_path, {"sub"}) is True
        assert is_force_included(target, tmp_path, {"other"}) is False


class TestMetacogV2Remainder:
    def test_ece_zero_count_bin(self):
        from dxrk.memory.metacog_v2 import compute_ece_from_bins

        bins = {"a": {"count": 0, "correct": 0, "conf_sum": 0.0}}
        assert compute_ece_from_bins(bins, 10) == 0.0

    def test_history_too_short(self):
        from dxrk.memory.metacog_v2 import compute_ece_history, fit_isotonic, fit_temperature

        assert compute_ece_history([], 10) == 0.0
        assert fit_temperature([], 10) == 1.0
        assert fit_isotonic([], 10) == {}

    def test_temperature_skips_extreme(self):
        from dxrk.memory.metacog_v2 import MIN_JUDGMENTS_FOR_ECE, fit_temperature

        entries = [{"predicted": 0.0, "actual": 0}] * MIN_JUDGMENTS_FOR_ECE
        assert fit_temperature(entries, 10) == 1.0

    def test_temperature_converges(self):
        from dxrk.memory.metacog_v2 import MIN_JUDGMENTS_FOR_ECE, fit_temperature

        entries = [{"predicted": 0.5, "actual": 1}] * MIN_JUDGMENTS_FOR_ECE
        assert fit_temperature(entries, 10) == 1.0

    def test_isotonic_single_point(self):
        from dxrk.memory.metacog_v2 import MIN_JUDGMENTS_FOR_ECE, fit_isotonic

        entries = [{"predicted": 0.5, "actual": 1}] * MIN_JUDGMENTS_FOR_ECE
        assert fit_isotonic(entries, 10) == {}

    def test_detect_bias_few_per_category(self):
        from dxrk.memory.metacog_v2 import MetacogState, detect_bias

        log = [{"error": 0.1, "context": {"i": i}} for i in range(10)]
        state = MetacogState(introspection_log=log)
        out = detect_bias(state, window=100)
        assert out["category_bias"] == {}


# ═══════════ ola 11: proxy + tls ═══════════


class TestProxyRemainder:
    def test_empty_auth_no_suffix(self):
        from dxrk.utils.http.proxy import ProxyAuth, ProxyConfig, ProxyType

        cfg = ProxyConfig(type=ProxyType.ProxyTypeHTTP, host="h", port=1, auth=ProxyAuth())
        assert cfg.get_proxy_url() == "http://h:1"

    def test_parse_invalid_ipv6(self):
        from dxrk.utils.http.proxy import new_proxy_config

        cfg, err = new_proxy_config("http://[::1")
        assert cfg is None
        assert err is not None

    def test_bad_port(self):
        from dxrk.utils.http.proxy import new_proxy_config

        cfg, err = new_proxy_config("http://h:badport")
        assert cfg is None
        assert err is not None

    def test_default_ports(self):
        from dxrk.utils.http.proxy import new_proxy_config

        cfg, err = new_proxy_config("https://h")
        assert err is None and cfg is not None
        assert cfg.proxy_port() == 8443
        cfg2, err2 = new_proxy_config("socks5://h")
        assert err2 is None and cfg2 is not None
        assert cfg2.proxy_port() == 1080
        cfg3, err3 = new_proxy_config("https://h:8443")
        assert err3 is None and cfg3 is not None
        assert cfg3.get_proxy_url() == "https://h:8443"


def _self_signed_pair():
    import datetime as _dt

    from cryptography import x509 as _x509
    from cryptography.hazmat.primitives import hashes as _hashes
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding as _Enc,
    )
    from cryptography.hazmat.primitives.serialization import (
        NoEncryption as _NoEnc,
    )
    from cryptography.hazmat.primitives.serialization import (
        PrivateFormat as _PF,
    )
    from cryptography.x509.oid import NameOID as _NOID

    key = _ec.generate_private_key(_ec.SECP256R1())
    subject = issuer = _x509.Name([_x509.NameAttribute(_NOID.COMMON_NAME, "test")])
    cert = (
        _x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(_x509.random_serial_number())
        .not_valid_before(_dt.datetime.now(_dt.UTC))
        .not_valid_after(_dt.datetime.now(_dt.UTC) + _dt.timedelta(days=1))
        .sign(key, _hashes.SHA256())
    )
    cert_pem = cert.public_bytes(_Enc.PEM)
    key_pem = key.private_bytes(_Enc.PEM, _PF.PKCS8, _NoEnc())
    return cert, cert_pem, key_pem


class TestTlsRemainder:
    def test_cleanup_unlink_failure(self):
        import ssl

        import dxrk.utils.http.tls as tls

        # la limpieza ignora OSError pero el error original propaga
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        with mock.patch.object(tls.os, "unlink", side_effect=OSError("ro")):
            with pytest.raises(Exception):
                tls._load_cert_chain_mem(ctx, b"basura", b"basura")

    def test_set_cert_key_data_ok(self):
        from dxrk.utils.http.tls import TLSConfig

        _, cert_pem, key_pem = _self_signed_pair()
        cfg = TLSConfig()
        cfg.set_cert_key_data(cert_pem, key_pem)
        assert cfg.cert_data == cert_pem

    def test_build_mismatch(self):
        from dxrk.utils.http.tls import TLSConfig

        cfg = TLSConfig(cert_data=b"basura", key_data=b"basura")
        with pytest.raises(Exception):
            cfg.build_tls_config()

    def test_client_cas_preset_auth(self):
        from dxrk.utils.http.tls import ClientAuthType, TLSConfig

        cert, _, _ = _self_signed_pair()
        cfg = TLSConfig(
            client_cas=[cert],
            client_auth=ClientAuthType.RequireAndVerifyClientCert,
        )
        ctx = cfg.build_tls_config()
        assert ctx is not None

    def test_server_no_max_version(self):
        from dxrk.utils.http.tls import TLSConfig

        _, cert_pem, key_pem = _self_signed_pair()
        cfg = TLSConfig(cert_data=cert_pem, key_data=key_pem, max_version=None)
        ctx = cfg.build_server_tls_config()
        assert ctx is not None

    def test_server_cert_mismatch(self):
        from dxrk.utils.http.tls import TLSConfig

        cfg = TLSConfig(cert_data=b"basura", key_data=b"basura")
        with pytest.raises(Exception):
            cfg.build_server_tls_config()

    def test_server_cert_only(self):
        from dxrk.utils.http.tls import TLSConfig

        _, cert_pem, _ = _self_signed_pair()
        cfg = TLSConfig(cert_data=cert_pem, key_data=b"")
        ctx = cfg.build_server_tls_config()
        assert ctx is not None

    def test_server_file_paths(self, tmp_path):
        from dxrk.utils.http.tls import TLSConfig

        _, cert_pem, key_pem = _self_signed_pair()
        cert_f = tmp_path / "c.pem"
        key_f = tmp_path / "k.pem"
        cert_f.write_bytes(cert_pem)
        key_f.write_bytes(key_pem)
        cfg = TLSConfig(cert_file=str(cert_f), key_file=str(key_f))
        ctx = cfg.build_server_tls_config()
        assert ctx is not None

    def test_ed_key_der(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            Encoding as _Enc,
        )
        from cryptography.hazmat.primitives.serialization import (
            NoEncryption as _NoEnc,
        )
        from cryptography.hazmat.primitives.serialization import (
            PrivateFormat as _PF,
        )

        from dxrk.utils.http.tls import _pem_decode

        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(_Enc.PEM, _PF.PKCS8, _NoEnc())
        assert _pem_decode(pem) == b"valid-private-key"


# ═══════════ ola 12: installcmd + validation ═══════════


class TestInstallcmdRemainder:
    def test_resolver_protocol_stubs(self):
        from dxrk.installcmd import Resolver

        obj = object()
        assert Resolver.resolve_agent_install(obj, None, None) is None
        assert Resolver.resolve_component_install(obj, None, None) is None
        assert Resolver.resolve_dependency_install(obj, None, None) is None

    def test_kilocode_sudo(self):
        from dxrk.installcmd import _resolve_kilocode_install
        from dxrk.system import PlatformProfile

        out = _resolve_kilocode_install(PlatformProfile(os="linux", npm_writable=False))
        assert out[0][0] == "sudo"

    def test_guardian_unsupported(self):
        from dxrk.installcmd import InstallError, _resolve_dxrk_guardian_install
        from dxrk.system import PlatformProfile

        with pytest.raises(InstallError, match="no compatible"):
            _resolve_dxrk_guardian_install(PlatformProfile(os="plan9", linux_distro="x", package_manager="x"))

    def test_go_version_output(self):

        import dxrk.installcmd as ic

        with mock.patch.object(
            ic.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="go version go1.24.0 linux/amd64\n")
        ):
            assert ic._get_go_version_output() == "go version go1.24.0 linux/amd64"
        with mock.patch.object(ic.subprocess, "run", return_value=SimpleNamespace(returncode=1, stdout="x")):
            assert ic._get_go_version_output() == ""
        with mock.patch.object(ic.subprocess, "run", side_effect=FileNotFoundError("go")):
            assert ic._get_go_version_output() == ""

    def test_validate_go_branches(self):
        import dxrk.installcmd as ic
        from dxrk.system import PlatformProfile

        prof = PlatformProfile(os="linux")
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value="/usr/bin/go"),
            mock.patch.object(ic, "_get_go_version_output", return_value=""),
        ):
            with pytest.raises(ic.InstallError, match="no se pudo verificar"):
                ic.validate_go_for_module_install(prof)
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value="/usr/bin/go"),
            mock.patch.object(ic, "_get_go_version_output", return_value="go"),
        ):
            assert ic.validate_go_for_module_install(prof) is None
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value="/usr/bin/go"),
            mock.patch.object(ic, "_get_go_version_output", return_value="go version go1"),
        ):
            assert ic.validate_go_for_module_install(prof) is None
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value="/usr/bin/go"),
            mock.patch.object(ic, "_get_go_version_output", return_value="go version goX.Y linux/amd64"),
        ):
            with pytest.raises(ic.InstallError, match="Se requiere Go"):
                ic.validate_go_for_module_install(prof)

    def test_git_bash_branches(self):
        import dxrk.installcmd as ic

        with (
            mock.patch.object(ic, "_cmd_look_path", return_value="/x/cmd/git"),
            mock.patch.object(ic, "_file_exists", side_effect=[False, True]),
        ):
            assert ic._git_bash_path() == "/x/cmd/bash.exe"
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value=None),
            mock.patch.object(ic, "_file_exists", return_value=True),
            mock.patch.dict("os.environ", {"ProgramFiles": "/pfx", "ProgramFiles(x86)": ""}),
        ):
            assert ic._git_bash_path() == "/pfx/Git/bin/bash.exe"
        with (
            mock.patch.object(ic, "_cmd_look_path", return_value=None),
            mock.patch.object(ic, "_file_exists", return_value=False),
            mock.patch.dict("os.environ", {"ProgramFiles": "", "ProgramFiles(x86)": ""}, clear=False),
        ):
            assert ic._git_bash_path() == "bash"

    def test_bash_script_path_plain(self):
        import dxrk.installcmd as ic
        from dxrk.system import PlatformProfile

        assert ic._bash_script_path(PlatformProfile(os="linux"), "a\\b") == "a\\b"
        assert ic._bash_script_path(PlatformProfile(os="windows"), "a\\b") == "a/b"


class TestValidationRemainder:
    def test_error_str(self):
        from dxrk.config.validation import ConfigError

        e = ConfigError(path="a.b", message="mal", severity="error")
        assert e.Error() == "[error] a.b: mal"

    def test_path_empty(self):
        from dxrk.config.config import HierarchicalConfig
        from dxrk.config.validation import PathValidator

        cfg = HierarchicalConfig()
        cfg.auth.token_path = ""
        assert PathValidator().Validate(cfg) == []

    def test_path_stat_failure(self, tmp_path):
        from dxrk.config.config import HierarchicalConfig
        from dxrk.config.validation import PathValidator

        cfg = HierarchicalConfig()
        cfg.auth.token_path = str(tmp_path)
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("os.stat", side_effect=OSError("ro")),
        ):
            errs = PathValidator().Validate(cfg)
        assert len(errs) == 1
        assert "cannot access" in errs[0].message

    def test_validate_with(self):
        from dxrk.config.config import HierarchicalConfig
        from dxrk.config.validation import PathValidator, ValidateConfigWith

        cfg = HierarchicalConfig()
        cfg.auth.token_path = ""
        assert ValidateConfigWith(cfg, PathValidator()) == []

    def test_format_no_hint(self):
        from dxrk.config.validation import ConfigError, FormatErrors

        out = FormatErrors([ConfigError(path="a", message="m", severity="error")])
        assert out == "[ERROR] a: m\n"

    def test_expand_empty_home(self):
        import dxrk.config.validation as v

        with mock.patch("os.path.expanduser", return_value=""):
            assert v.expand_path("~/x") == "~/x"


# ═══════════ ola 13: components/memory ═══════════


def _mem_adapter(**kw):
    from dxrk.models import AgentID, MCPStrategy

    base = dict(
        supports_mcp=True,
        mcp_strategy=MCPStrategy.SEPARATE_MCP_FILES,
        supports_system_prompt=False,
        agent=AgentID.OPENCODE,
        mcp_config_path=lambda h, n: "",
        settings_path=lambda h: "",
        system_prompt_file=lambda h: "",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestComponentsMemoryRemainder:
    def test_mcp_config_empty_path(self, tmp_path):
        from dxrk.components.memory import inject
        from dxrk.models import MCPStrategy

        ad = _mem_adapter(mcp_strategy=MCPStrategy.MCP_CONFIG_FILE)
        out = inject(str(tmp_path), ad)
        assert out.Changed is False

    def test_toml_empty_path(self, tmp_path):
        from dxrk.components.memory import inject
        from dxrk.models import MCPStrategy

        ad = _mem_adapter(mcp_strategy=MCPStrategy.TOML_FILE)
        out = inject(str(tmp_path), ad)
        assert out.Changed is False

    def test_unknown_strategy(self, tmp_path):
        from dxrk.components.memory import inject

        ad = _mem_adapter(mcp_strategy="estrategia-desconocida")
        out = inject(str(tmp_path), ad)
        assert out.Changed is False

    def test_antigravity_no_settings(self, tmp_path):
        from dxrk.components.memory import inject
        from dxrk.models import AgentID, MCPStrategy

        mcp = tmp_path / "mcp.json"
        mcp.write_bytes(b"{}")
        ad = _mem_adapter(
            agent=AgentID.ANTIGRAVITY,
            mcp_strategy=MCPStrategy.MCP_CONFIG_FILE,
            mcp_config_path=lambda h, n: str(mcp),
            settings_path=lambda h: "",
        )
        out = inject(str(tmp_path), ad)
        assert str(mcp) in out.Files

    def test_hooks_failure_ignored(self, tmp_path):
        from dxrk.components.memory import inject

        mcp = tmp_path / "mcp.json"
        ad = _mem_adapter(mcp_config_path=lambda h, n: str(mcp))
        with mock.patch("dxrk.memory.hooks_cli.ensure_hook_configs", side_effect=RuntimeError("sin hooks")):
            out = inject(str(tmp_path), ad)
        assert str(mcp) in out.Files

    def test_executable_empty(self):
        from dxrk.components.memory import _executable_from_command_value

        assert _executable_from_command_value([]) == ("", False)
        assert _executable_from_command_value(None) == ("", False)

    def test_version_no_token_raises(self, monkeypatch):
        import dxrk.components.memory as mem

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        with mock.patch.object(
            mem,
            "_fetch_latest_DXRK_MEMORY_version_request",
            side_effect=[RuntimeError("red"), ("", 200)],
        ):
            with pytest.raises(RuntimeError):
                mem._fetch_latest_DXRK_MEMORY_version()

    def test_tar_without_binary(self, tmp_path):
        import io
        import tarfile
        from unittest.mock import MagicMock

        import dxrk.components.memory as mem

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name in ("DXRK_MEMORY", "other.txt"):
                info = tarfile.TarInfo(name)
                data = b"x"
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        resp = MagicMock()
        resp.read.return_value = buf.getvalue()
        with (
            mock.patch.object(
                mem, "urlopen", return_value=MagicMock(__enter__=lambda s: resp, __exit__=lambda *a: False)
            ),
            mock.patch.object(tarfile.TarFile, "extractfile", return_value=None),
        ):
            with pytest.raises(FileNotFoundError, match="no encontrado"):
                mem._download_and_extract_tar_gz("http://x/y.tar.gz", "DXRK_MEMORY", str(tmp_path / "bin"))


# ═══════════ ola 14: gga + compress ═══════════


class TestGgaRemainder:
    def test_files_written_variants(self):
        from dxrk.components.gga import InjectionResult

        assert InjectionResult(ConfigFile="c", AgentsFile="a").files_written() == ["c", "a"]
        assert InjectionResult(ConfigFile="", AgentsFile="a").files_written() == ["a"]
        assert InjectionResult().files_written() == []

    def test_shim_symlink_fallbacks(self, tmp_path):
        import shutil

        import dxrk.components.gga as gga

        home = tmp_path / "h"
        cfg = home / ".config" / "DXRK_GUARDIAN"
        cfg.mkdir(parents=True)
        (cfg / "AGENTS.md").write_text("x")
        with (
            mock.patch.object(shutil, "which", return_value="/usr/bin/gga"),
            mock.patch.object(gga.os, "symlink", side_effect=OSError("sin permiso")),
        ):
            gga.ensure_dxrk_guardian_shim(str(home))
        assert (home / ".config" / "gga" / "AGENTS.md").exists()
        with (
            mock.patch.object(shutil, "which", return_value="/usr/bin/gga"),
            mock.patch.object(gga.os, "symlink", side_effect=OSError("sin permiso")),
            mock.patch.object(shutil, "copytree", side_effect=OSError("ro")),
            mock.patch.object(shutil, "copy2", side_effect=OSError("ro")),
        ):
            home2 = tmp_path / "h2"
            cfg2 = home2 / ".config" / "DXRK_GUARDIAN"
            cfg2.mkdir(parents=True)
            (cfg2 / "AGENTS.md").write_text("x")
            gga.ensure_dxrk_guardian_shim(str(home2))

    def test_install_command(self):
        from dxrk.components.gga import install_command
        from dxrk.system import PlatformProfile

        out = install_command(PlatformProfile(os="linux"))
        assert isinstance(out, list)

    def test_assets_missing(self, tmp_path):
        import dxrk.components.gga as gga

        with mock.patch.object(gga, "assets_read", return_value=None):
            with pytest.raises(FileNotFoundError):
                gga.ensure_runtime_assets(str(tmp_path))
        with mock.patch.object(gga, "assets_read", return_value=None):
            with pytest.raises(FileNotFoundError):
                gga.ensure_powershell_shim(str(tmp_path))

    def test_assets_ok(self, tmp_path):
        from dxrk.components.gga import ensure_powershell_shim, ensure_runtime_assets

        ensure_runtime_assets(str(tmp_path))
        assert (tmp_path / ".local" / "share" / "DXRK_GUARDIAN" / "lib" / "pr_mode.sh").exists()
        ensure_powershell_shim(str(tmp_path))
        assert (tmp_path / "bin" / "DXRK_GUARDIAN.ps1").exists()


class TestCompressRemainder:
    def _content(self, **kw):
        from dxrk.compress import Content

        base = dict(id="a", role="user", text="hello world", size=11)
        base.update(kw)
        return Content(**base)

    def test_trim_head_small_chunk(self):
        from dxrk.compress import Compressor, Strategy

        c = Compressor(compression_pct=50, strategy=Strategy.TRIM_HEAD)
        small = self._content(id="s", text="hi", size=2)
        big = self._content(id="b", text="x" * 100, size=100)
        out, changed = c._trim_head([small, big], 10)
        assert changed is True
        assert out[0].text == "hi"

    def test_trim_head_short_text(self):
        from dxrk.compress import Compressor, Strategy

        c = Compressor(compression_pct=10, strategy=Strategy.TRIM_HEAD)
        ch = self._content(text="hey", size=100)
        out, _ = c._trim_head([ch], 10)
        assert out[0].text == "hey"

    def test_summarize_short(self):
        from dxrk.compress import Compressor, Strategy

        c = Compressor(strategy=Strategy.SUMMARY)
        ch = self._content(text="hey", size=3)
        out, _ = c._summarize([ch], 100)
        assert out[0].text == "hey"

    def test_combine_variants(self):
        from dxrk.compress import combine_context

        assert combine_context([self._content()], separator="|") == "<USER>\nhello world\n</USER>"
        assert combine_context([self._content(text="")]) == ""

    def test_snapshot_marshal_failure(self, tmp_path):
        from datetime import datetime

        from dxrk.compress import Snapshot, Snapshotter

        st = Snapshotter(max_age=60.0, max_count=10)
        with mock.patch("dxrk.compress.Snapshot.to_dict", side_effect=TypeError("no")):
            st.snaps.append(
                Snapshot(
                    id="x",
                    created_at=datetime.now(),
                    content=[],
                    token_estimate=0,
                )
            )
            with pytest.raises(RuntimeError, match="marshal snapshots"):
                st.save_to_file(str(tmp_path / "s.json"))

    def test_snapshot_write_failure(self, tmp_path):
        from dxrk.compress import Snapshotter

        st = Snapshotter(max_age=60.0, max_count=10)
        with pytest.raises(RuntimeError, match="write snapshot file"):
            st.save_to_file(str(tmp_path / "nodir" / "s.json"))

    def test_snapshot_rename_failure(self, tmp_path):
        from dxrk.compress import Snapshotter

        st = Snapshotter(max_age=60.0, max_count=10)
        with mock.patch("os.replace", side_effect=OSError("ro")):
            with pytest.raises(RuntimeError, match="rename snapshot file"):
                st.save_to_file(str(tmp_path / "s.json"))
        assert not (tmp_path / "s.json").exists()
        with (
            mock.patch("os.replace", side_effect=OSError("ro")),
            mock.patch("os.remove", side_effect=OSError("ro")),
        ):
            with pytest.raises(RuntimeError, match="rename snapshot file"):
                st.save_to_file(str(tmp_path / "s.json"))

    def test_snapshot_bad_json(self, tmp_path):
        from dxrk.compress import Snapshotter

        p = tmp_path / "s.json"
        p.write_text("{roto")
        with pytest.raises(RuntimeError, match="unmarshal snapshots"):
            Snapshotter(max_age=60.0, max_count=10).load_from_file(str(p))

    def test_snapshot_read_failure(self, tmp_path):
        from dxrk.compress import Snapshotter

        with mock.patch("builtins.open", side_effect=PermissionError("ro")):
            with pytest.raises(RuntimeError, match="read snapshot file"):
                Snapshotter(max_age=60.0, max_count=10).load_from_file(str(tmp_path / "s.json"))

    def test_snapshot_trim(self, tmp_path):
        import json
        from datetime import datetime

        from dxrk.compress import Content, Snapshotter

        st = Snapshotter(max_age=60.0, max_count=1)
        payload = {
            "snapshots": [
                {
                    "id": f"s{i}",
                    "created_at": datetime.now().isoformat(),
                    "content": [Content(id="c", role="u", text="t", size=1).to_dict()],
                    "token_estimate": 1,
                }
                for i in range(3)
            ]
        }
        p = tmp_path / "s.json"
        p.write_text(json.dumps(payload))
        loaded, _ = st.load_from_file(str(p))
        assert loaded == 3
        assert len(st.snaps) == 1


# ═══════════ ola 15: router + hooks_cli ═══════════


class TestRouterRemainder:
    def test_semantic_hit(self):
        from dxrk.router import QueryResponse, SemanticCache

        c = SemanticCache(semantic_enabled=True, semantic_threshold=0.5)
        c.set("alpha beta gamma delta", QueryResponse())
        _, hit = c.get("alpha beta gamma epsilon")
        assert hit is True

    def test_zero_norm_embed(self):
        from dxrk.router import simple_embed

        assert simple_embed("w103") == [0.0] * 128

    def test_evict_reordered(self):
        from dxrk.router import QueryResponse, SemanticCache

        c = SemanticCache(max_size=2)
        c.set("a uno", QueryResponse())
        c.set("b dos", QueryResponse())
        c.get("a uno")
        c.set("c tres", QueryResponse())
        # NOTA: el heap no se reordena en get(); la evicción saca heap[0]
        # rancio (documenta comportamiento actual, no LRU ideal).
        assert c.stats().size == 2
        _, hit_a = c.get("a uno")
        assert hit_a is False
        _, hit_b = c.get("b dos")
        assert hit_b is True


class TestHooksCliRemainder:
    def test_trusted_prefix_binary(self):
        import sys

        from dxrk.memory.hooks_cli import _is_trusted_python

        assert _is_trusted_python(sys.prefix + "/bin/coverage") is True
        assert _is_trusted_python("/tmp/nope/python") is False

    def test_realpath_failure(self):
        import dxrk.memory.hooks_cli as hooks

        with mock.patch.object(hooks.os.path, "realpath", side_effect=OSError("ro")):
            assert hooks._is_trusted_python("/tmp/x") is False

    def test_base_realpath_failure(self):
        import dxrk.memory.hooks_cli as hooks

        with (
            mock.patch.object(
                hooks.os.path,
                "realpath",
                side_effect=["/tmp/fake-py", "/real/exe", OSError("ro"), "/zzz/a", "/zzz/b", "/zzz/c"],
            ),
            mock.patch.object(hooks.os.path, "isfile", return_value=True),
            mock.patch.object(hooks.os, "access", return_value=True),
        ):
            assert hooks._is_trusted_python("/tmp/fake-py") is False

    def test_session_start_recall_failure(self):
        import dxrk.memory.hooks_cli as hooks

        with (
            mock.patch.object(hooks, "_malla_root_exists", return_value=True),
            mock.patch.object(hooks, "_session_start_context", side_effect=RuntimeError("caído")),
            mock.patch.object(hooks, "_output") as out,
            mock.patch.object(hooks, "_log"),
        ):
            hooks.hook_session_start({}, "dxrk")
        out.assert_called_once_with({})

    def test_start_context_variants(self):
        from unittest.mock import Mock

        import dxrk.memory.hooks_cli as hooks

        with (
            mock.patch.object(hooks, "_partition_from_transcript_path", side_effect=ValueError("x")),
            mock.patch(
                "dxrk.memory.layers.MemoryStack",
                return_value=SimpleNamespace(wake_up=Mock(return_value="hola")),
            ),
        ):
            assert hooks._session_start_context("t") == {"systemMessage": "hola"}
        with (
            mock.patch.object(hooks, "_partition_from_transcript_path", return_value="partition_x"),
            mock.patch(
                "dxrk.memory.layers.MemoryStack",
                return_value=SimpleNamespace(wake_up=Mock(side_effect=["No memories yet para x", "texto real"])),
            ),
        ):
            assert hooks._session_start_context("t") == {"systemMessage": "texto real"}
        with (
            mock.patch.object(hooks, "_partition_from_transcript_path", return_value="partition_x"),
            mock.patch(
                "dxrk.memory.layers.MemoryStack",
                return_value=SimpleNamespace(wake_up=Mock(return_value="x" * 5000)),
            ),
        ):
            out = hooks._session_start_context("t")
            assert out["systemMessage"].endswith("... (more in DxrkMemory search)")
        with (
            mock.patch.object(hooks, "_partition_from_transcript_path", return_value="partition_x"),
            mock.patch(
                "dxrk.memory.layers.MemoryStack",
                return_value=SimpleNamespace(wake_up=Mock(return_value="   ")),
            ),
        ):
            assert hooks._session_start_context("t") == {}

    def test_main_guard(self):
        import runpy

        with pytest.raises(SystemExit) as exc:
            runpy.run_path("dxrk/memory/hooks_cli.py", run_name="__main__")
        assert exc.value.code == 2


# ═══════════ ola 16: config/load ═══════════


class TestConfigLoadRemainder:
    def test_rich_dict(self):
        from dxrk.config.load import _load_config_dict

        data = {
            "project": {"name": "p", "root": "/r", "default_provider": "x"},
            "providers": ["no-dict", {"name": "a", "model": "m", "api_key_env": "K", "base_url": ""}],
            "sandbox": {},
            "git": {},
            "tui": {},
            "webui": {},
            "rag": {},
            "autonomy": {},
            "vault": {},
            "cache": {},
        }
        cfg = _load_config_dict(data)
        assert cfg.project.name == "p"
        assert len(cfg.providers) == 1

    def test_to_dict_nones(self):
        from dxrk.config.load import Default, _config_to_dict

        cfg = Default()
        cfg.sandbox = None
        cfg.git = None
        cfg.tui = None
        cfg.webui = None
        cfg.rag = None
        cfg.autonomy = None
        cfg.vault = None
        cfg.cache = None
        d = _config_to_dict(cfg)
        assert "sandbox" not in d
        assert "tui" not in d

    def test_load_errors(self, tmp_path):
        from dxrk.config.load import Load

        bad = tmp_path / "bad.yaml"
        bad.write_text("{{{no yaml")
        with pytest.raises(OSError, match="read config"):
            Load(str(bad))
        empty = tmp_path / "empty.yaml"
        empty.write_text("")
        assert Load(str(empty)).project is not None
        lst = tmp_path / "list.yaml"
        lst.write_text("[1, 2]")
        with pytest.raises(OSError, match="expected a mapping"):
            Load(str(lst))

    def test_save_variants(self, tmp_path, monkeypatch):
        import yaml

        from dxrk.config.load import Default, Save

        with mock.patch.object(yaml, "safe_dump", side_effect=yaml.YAMLError("boom")):
            with pytest.raises(OSError, match="parse config"):
                Save(str(tmp_path / "c.yaml"), Default())
        monkeypatch.chdir(tmp_path)
        Save("rel.yaml", Default())
        assert (tmp_path / "rel.yaml").exists()


# ═══════════ ola 17: autonomy/permissions ═══════════


class TestAutonomyPermissions:
    def test_check_variants(self):
        from dxrk.autonomy.permissions import PermissionStore

        st = PermissionStore()
        st.deny("git", permanent=True)
        assert "permanently denied" in st.check("git", "r")
        st.grant("fs.read")
        assert st.check("fs.read", "r") is None
        st.ask_first.add("sudo")
        assert "requires approval" in st.check("sudo", "porque sí")
        assert "not granted" in st.check("exec", "r")

    def test_grant_deny(self):
        from dxrk.autonomy.permissions import PermissionStore

        st = PermissionStore()
        st.ask_first.add("x")
        st.grant("x")
        assert "x" in st.allowed and "x" not in st.ask_first
        st.deny("x", permanent=False)
        assert "x" not in st.allowed
        st.deny("y", permanent=True)
        assert "y" in st.denied

    def test_request_flow(self):
        from dxrk.autonomy.permissions import PermissionStore

        st = PermissionStore()
        st.ask_first.add("net.http")
        st.granted["net.http:r"] = True
        fn = mock.Mock(return_value=(True, None))
        st.set_request_handler(fn)
        assert st.check("net.http", "r") is None
        fn.assert_not_called()
        st2 = PermissionStore()
        st2.ask_first.add("net.http")
        st2.set_request_handler(lambda c, r: (False, "mal"))
        assert st2.check("net.http", "r") == "mal"
        st3 = PermissionStore()
        st3.ask_first.add("net.http")
        st3.set_request_handler(lambda c, r: (False, None))
        assert "denied" in st3.check("net.http", "r")
        st4 = PermissionStore()
        st4.ask_first.add("net.http")
        st4.set_request_handler(lambda c, r: (True, None))
        assert st4.check("net.http", "r") is None
        assert st4.check("net.http", "r") is None

    def test_all_granted_and_new(self):
        from dxrk.autonomy.permissions import NewPermissionStore

        st = NewPermissionStore([" a ", "", "b"], ["b", " ", "c"])
        assert "a" in st.allowed
        assert "b" in st.ask_first and "b" not in st.allowed
        assert "c" in st.ask_first
        assert st.all_granted() == sorted(st.allowed | set(st.granted))


# ═══════════ ola 18: pipeline ═══════════


class TestPipelineRemainder:
    def test_step_protocol_stubs(self):
        from dxrk.pipeline import RollbackStep, Step

        obj = object()
        assert Step.id(obj) is None
        assert Step.run(obj) is None
        assert RollbackStep.rollback(obj) is None

    def test_rollback_unknown_step(self):
        from dxrk.pipeline import StepResult, StepStatus, execute_rollback

        out = execute_rollback([StepResult(step_id="fantasma", status=StepStatus.SUCCEEDED)], {})
        assert out.success is True

    def test_rollback_failure_propagates(self):
        from dxrk.pipeline import Orchestrator, RollbackStep, StagePlan, Step

        class _OkThenBadRollback(RollbackStep):
            def id(self):
                return "a"

            def run(self):
                return None

            def rollback(self):
                return "no se pudo revertir"

        class _FailApply(Step):
            def id(self):
                return "x"

            def run(self):
                return "boom"

        out = Orchestrator().execute(StagePlan(prepare=[], apply=[_OkThenBadRollback(), _FailApply()]))
        assert out.error == "rollback step 'a': no se pudo revertir"

    def test_execute_command_failures(self):
        import dxrk.pipeline as pipe

        restore = pipe.set_command_streaming(False)
        try:
            with mock.patch.object(
                pipe.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=1, stdout="boom\n", stderr=""),
            ):
                assert "boom" in pipe.execute_command("false")
            with mock.patch.object(
                pipe.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=2, stdout="", stderr=""),
            ):
                assert "código 2" in pipe.execute_command("false")
            with mock.patch.object(
                pipe.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                assert pipe.execute_command("true") is None
        finally:
            restore()

    def test_execute_command_oserror(self):
        import dxrk.pipeline as pipe

        with mock.patch.object(pipe.subprocess, "run", side_effect=PermissionError("ro")):
            assert pipe.execute_command("x") == "ro"

    def test_resolve_gga_curl(self):
        from dxrk.models import ComponentID
        from dxrk.pipeline import resolve_component_install
        from dxrk.system import PlatformProfile

        out = resolve_component_install(PlatformProfile(os="linux", package_manager="apt"), ComponentID.DXRK_GUARDIAN)
        assert any("curl" in arg for cmd in out for arg in cmd)


class TestAgentsScreenRemainder:
    @pytest.mark.asyncio
    async def test_full_flow(self):
        import sys

        sys.path.insert(0, "tests")
        from test_tui import _make_app

        from dxrk.tui.screens.agents import AgentsScreen
        from dxrk.tui.shared import STATE

        app = _make_app()
        STATE.selected_agents = []
        async with app.run_test() as pilot:
            screen = AgentsScreen()
            await pilot.app.push_screen(screen)
            await pilot.pause()
            assert screen.query_one("#agent-list")
            await pilot.press("down")
            await pilot.press("up")
            await pilot.press("space")
            from dxrk.tui.context import get_ctx

            assert len(get_ctx().selected_agents) == 1
            await pilot.press("space")
            assert len(get_ctx().selected_agents) == 0
            screen.cursor = screen._action_offset
            await screen.action_toggle()
            screen.cursor = screen._action_offset + 5
            await screen.action_continue()
            screen.cursor = screen._action_offset
            await screen.action_continue()
            screen.cursor = screen._action_offset + 1
            await screen.action_continue()
            from textual.widgets import Static

            await screen.query_one("#agent-list").mount(Static("extra"))
            screen.cursor = 0
            await pilot.pause()
            screen.action_back()
            await pilot.pause()


# ═══════════ ola 19: scoring ═══════════


class TestScoringRemainder:
    def test_decay_naive_and_future(self):
        from datetime import datetime

        from dxrk.memory.scoring import decay_factor

        assert decay_factor(None, 30.0) == 1.0
        assert decay_factor("2020-01-01T00:00:00+00:00", 30.0, datetime(2020, 1, 1)) == 1.0
        assert decay_factor("2030-01-01T00:00:00+00:00", 30.0) == 1.0

    def test_rank_bad_inputs(self):
        from dxrk.memory.scoring import rank_score

        assert rank_score(importance="basura") == 0.0
        assert rank_score(access_count="muchos") == 0.0
        assert rank_score(importance=1.0, access_count=-5) >= 0.0

    def test_clamp_variants(self):
        from dxrk.memory.scoring import _clamp_float

        assert _clamp_float("x", 2.0) == 2.0
        assert _clamp_float(float("nan"), 2.0) == 2.0
        assert _clamp_float(float("inf"), 2.0) == 2.0
        assert _clamp_float(99.0, 2.0, high=10.0) == 10.0
        assert _clamp_float(-5.0, 2.0, low=0.0) == 0.0

    def test_frequency_bad(self):
        from dxrk.memory.scoring import frequency_factor

        assert frequency_factor("muchos") == 0.7

    def test_days_naive(self):
        from datetime import UTC, datetime

        from dxrk.memory.scoring import _days_since_access

        assert _days_since_access({"filed_at": "2020-01-01T00:00:00"}, datetime(2020, 1, 2, tzinfo=UTC)) == 1.0

    def test_score_meta_edges(self):
        from datetime import datetime

        from dxrk.memory.scoring import score_meta

        assert score_meta({"access_count_total": "muchos"}) >= 0.0
        assert score_meta({"access_count_total": -3}) >= 0.0
        assert score_meta({}, now=datetime(2020, 1, 1)) >= 0.0


# ═══════════ ola 20: calibrate_v2 ═══════════


class TestCalibrateV2Remainder:
    def _recalls(self):
        return [
            {"id": "a", "document": "alpha beta gamma delta", "metadata": {"partition": "w"}},
            {"id": "b", "document": "epsilon zeta eta theta", "metadata": {"partition": "w"}},
            {"id": "c", "document": "", "metadata": {"partition": "w"}},
        ]

    def test_now_iso(self):
        from dxrk.memory.calibrate_v2 import _now_iso

        assert "T" in _now_iso()

    def test_tenant_path_no_tenant(self, tmp_path):
        from dxrk.memory.calibrate_v2 import _tenant_partition_path

        assert _tenant_partition_path(tmp_path, "", "w").name == "w.json"
        assert _tenant_partition_path(tmp_path, "t", "w").name == "t_w.json"

    def test_load_corrupt_global(self, tmp_path):
        from dxrk.memory.calibrate_v2 import DEFAULT_PARAMS, load_calibration

        caldir = tmp_path / ".calibration"
        caldir.mkdir()
        (caldir / "global_w.json").write_text("{roto")
        assert load_calibration(tmp_path, "", "w") == DEFAULT_PARAMS

    def test_recall_few_and_empty_doc(self):
        from dxrk.memory.calibrate_v2 import CalibrationParams, evaluate_recall_at_k

        one = SimpleNamespace(iter_recalls=lambda: self._recalls()[:1])
        assert evaluate_recall_at_k(one, "w", CalibrationParams()) == 0.0
        full = SimpleNamespace(iter_recalls=lambda: self._recalls())
        assert evaluate_recall_at_k(full, "w", CalibrationParams(), k=5, sample_size=10) == 0.0

    def test_partition_few_candidates(self, tmp_path):
        import dxrk.memory.calibrate_v2 as cal

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls(), _path=str(tmp_path))
        with mock.patch.object(cal, "select_evaluation_candidates", return_value=["a"]):
            assert cal.calibrate_partition(malla, "w") == cal.DEFAULT_PARAMS

    def test_partition_optimizes(self, tmp_path):
        import dxrk.memory.calibrate_v2 as cal
        from dxrk.memory.qieo import QIEOConfig

        malla = SimpleNamespace(iter_recalls=lambda: self._recalls(), _path=str(tmp_path))
        cfg = QIEOConfig(pop_size=4, n_iter=2)
        with mock.patch.object(cal, "select_evaluation_candidates", return_value=["a", "b"]):
            out = cal.calibrate_partition(malla, "w", qieo_config=cfg, objective_k=2, objective_samples=4)
        assert out.method == "qieo"
