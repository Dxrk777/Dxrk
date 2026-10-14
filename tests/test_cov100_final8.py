# SPDX-License-Identifier: MIT
"""Cobertura 100% final8 — plugin/tools/query/system/skillregistry/pipeline/observe/log/router/slo/planner/git/vault.

Tests reales de comportamiento: cada test ejercita líneas/ramas exactas del
coverage report. Sin red real (respuestas parseadas directo o fakes locales),
sin pragma, sin relleno. Incluye 5 simplificaciones ya aplicadas en código:
slo.calculate_burn_rate (guard imposible), git.parse_status (if imposible),
vault tenant (condición siempre-true), skillregistry.regenerate (elif imposible)
y skillregistry._extract_rules_from_headings (chequeo _next_h2 inalcanzable:
load_skill lee en modo texto y universal-newlines elimina todo \\r).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import urllib.error
from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest


class _F8StaticProvider:
    """Provider fake que devuelve un texto fijo sin red."""

    def __init__(self, text: str = "hi") -> None:
        self._text = text

    def generate(self, messages, tools):
        from dxrk.query import Response

        return Response(text=self._text), None


class _F8ErrPersist:
    """Persistence fake cuyo save_turn siempre falla."""

    def save_turn(self, session_id, user_msg, assistant_msg):
        return "boom"


class _F8RuntimeOk:
    """InstallRuntime fake con una etapa que tiene éxito."""

    def __init__(self, *args) -> None:
        pass

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        ok = SimpleNamespace(id=lambda: "s-ok", run=lambda: None)
        return StagePlan(prepare=[], apply=[ok])


class _F8RuntimeFail:
    """InstallRuntime fake con una etapa que falla."""

    def __init__(self, *args) -> None:
        pass

    def stage_plan(self):
        from dxrk.pipeline import StagePlan

        bad = SimpleNamespace(id=lambda: "s-bad", run=lambda: "boom")
        return StagePlan(prepare=[], apply=[bad])


class _F8RuntimeBoom:
    """InstallRuntime fake que explota al construir."""

    def __init__(self, *args) -> None:
        raise RuntimeError("no runtime")


def _f8_selection():
    from dxrk.models import AgentID, ComponentID, Selection

    return Selection(agents=[AgentID.OPENCODE], components=[ComponentID.SDD])


# ═══════════ dxrk/log/__init__.py 16, 23 ═══════════


class TestLogLevelStr:
    def test_all_levels(self):
        from dxrk.log import Level

        assert str(Level.DEBUG) == "DEBUG"
        assert str(Level.INFO) == "INFO"
        assert str(Level.WARN) == "WARN"
        assert str(Level.ERROR) == "ERROR"

    def test_unknown_fallback_default_arm(self):
        from dxrk.log import Level

        # Rama defensiva (default del switch en Go): valores fuera de rango
        # devuelven UNKNOWN en vez de romper el contrato -> str.
        assert Level.__str__(99) == "UNKNOWN"


# ═══════════ dxrk/router/__init__.py 336->333, 337->336 ═══════════


class TestRouterEvictionBranches:
    def test_evict_scans_past_newer_dict_entry(self):
        from unittest.mock import patch

        from dxrk.router import QueryResponse, SemanticCache

        cache = SemanticCache(max_size=2, ttl=300.0)
        # Reloj sesgado: "b" se registra más vieja que "a" aunque llegó después.
        with patch("dxrk.router.time.time", side_effect=[10.0, 5.0, 6.0, 7.0, 8.0]):
            cache.set("a", QueryResponse(text="A"))
            cache.set("b", QueryResponse(text="B"))
            cache.set("c", QueryResponse(text="C"))  # desaloja a "b", primera en el dict es "a"
            _, ok = cache.get("b")
            assert not ok
            got, ok = cache.get("a")
            assert ok and got.text == "A"

    def test_evict_tolerates_stale_heap_entry(self):
        from unittest.mock import patch

        from dxrk.router import QueryResponse, SemanticCache

        cache = SemanticCache(max_size=10, ttl=300.0)
        with patch("dxrk.router.time.time", side_effect=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]):
            cache.set("a", QueryResponse(text="A"))
            cache.set("b", QueryResponse(text="B"))
            cache.set("c", QueryResponse(text="C"))
            # invalidate() reordena el heap sin refrescar .index: el segundo
            # invalidate deja una entrada obsoleta dentro del heap.
            cache.invalidate("a")
            cache.invalidate("c")
            cache._max_size = 1
            cache.set("d", QueryResponse(text="D"))  # el pop obsoleto no borra entradas vivas
            got, ok = cache.get("b")
            assert ok and got.text == "B"
            _, ok = cache.get("c")
            assert not ok
            got, ok = cache.get("d")
            assert ok and got.text == "D"
            assert cache.stats().size == 2


# ═══════════ dxrk/planner.py: soft-ordering inicializado en import ═══════════


class TestPlannerSoftPairs:
    def test_pairs_initialized(self):
        import dxrk.planner as planner_mod

        assert len(planner_mod.SOFT_ORDERING_PAIRS) == 2
        assert len(planner_mod.soft_ordering_constraints()) == 2


# ═══════════ dxrk/pipeline.py 409-411, 417->420, 434->437, 445-448, ═══════════
# ═══════════ 462->exit, 471->474, 478->481, 482-484, 486->488 ═══════════


def _f8_patch_install(monkeypatch, runtime_cls):
    from dxrk.system import PlatformProfile

    profile = PlatformProfile(os="linux", linux_distro="ubuntu", package_manager="apt", supported=True)
    sel = _f8_selection()
    detection = SimpleNamespace(system=SimpleNamespace(supported=True))
    monkeypatch.setattr("dxrk.system.detect", lambda: detection)
    monkeypatch.setattr("dxrk.cli.install.resolve_install_profile", lambda det: profile)
    monkeypatch.setattr("dxrk.cli.install.normalize_install_flags", lambda flags, det: SimpleNamespace(selection=sel))
    monkeypatch.setattr("dxrk.cli.install.build_stage_plan", lambda selection, resolved: SimpleNamespace())
    monkeypatch.setattr("dxrk.cli.install.InstallRuntime", runtime_cls)
    return sel


class TestRunInstallPipeline:
    async def test_unsupported_reports_progress(self):
        from dxrk.pipeline import run_install_pipeline

        calls = []

        async def on_progress(msg, pct):
            calls.append((msg, pct))

        with mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=False))):
            assert await run_install_pipeline(_f8_selection(), on_progress=on_progress) is False
        assert calls == [("Sistema no compatible", 0)]

    async def test_unsupported_without_progress(self):
        from dxrk.pipeline import run_install_pipeline

        with mock.patch("dxrk.system.detect", return_value=SimpleNamespace(system=SimpleNamespace(supported=False))):
            assert await run_install_pipeline(_f8_selection(), on_progress=None) is False

    async def test_success_full_progress(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeOk)
        calls = []

        async def on_progress(msg, pct):
            calls.append((msg, pct))

        assert await run_install_pipeline(sel, on_progress=on_progress) is True
        await asyncio.sleep(0.05)
        assert calls[0] == ("Generando el plan de etapas...", 5)
        assert ("¡Instalación completa!", 100) in calls
        assert any("Instalando 1 agente(s)..." in m for m, _ in calls)

    async def test_apply_error_without_progress(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeFail)
        assert await run_install_pipeline(sel, on_progress=None) is False

    async def test_runtime_init_error(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeBoom)
        calls = []

        async def on_progress(msg, pct):
            calls.append((msg, pct))

        assert await run_install_pipeline(sel, on_progress=on_progress) is False
        assert any("Error de ejecución" in m for m, _ in calls)

    async def test_runtime_init_error_without_progress(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeBoom)
        assert await run_install_pipeline(sel, on_progress=None) is False

    async def test_apply_error_with_progress(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeFail)
        calls = []

        async def on_progress(msg, pct):
            calls.append((msg, pct))

        assert await run_install_pipeline(sel, on_progress=on_progress) is False
        await asyncio.sleep(0.05)
        assert any("Falló" in m for m, _ in calls)

    async def test_success_without_progress(self, monkeypatch):
        from dxrk.pipeline import run_install_pipeline

        sel = _f8_patch_install(monkeypatch, _F8RuntimeOk)
        assert await run_install_pipeline(sel, on_progress=None) is True


# ═══════════ dxrk/plugin.py ═══════════


class TestPluginHookRemove:
    def test_remove_from_empty_is_noop(self):
        from dxrk.plugin import new_hook_manager

        new_hook_manager().remove("hook-9")

    def test_remove_unknown_id_keeps_hooks(self):
        from dxrk.plugin import new_hook_manager

        hm = new_hook_manager()
        seen = []
        hm.register("before_load", 0, lambda ev: seen.append(ev.point))
        hm.remove("hook-999")
        assert hm.execute("before_load", "p") is None
        assert seen == ["before_load"]

    def test_remove_second_of_two(self):
        from dxrk.plugin import new_hook_manager

        hm = new_hook_manager()
        ran = []
        hm.register("before_load", 0, lambda ev: ran.append("first") or "err-first")
        hm.register("before_load", 1, lambda ev: ran.append("second"))
        second_id = "hook-2"
        hm.remove(second_id)
        assert hm.execute("before_load", "p") == "hook before_load (hook-1) failed: err-first"
        assert ran == ["first"]

    def test_remove_sole_hook_deletes_point(self):
        from dxrk.plugin import new_hook_manager

        hm = new_hook_manager()
        hid = hm.register("before_load", 0, lambda ev: None)
        assert hm.hook_count("before_load") == 1
        hm.remove(hid)
        assert hm.hook_count("before_load") == 0

    def test_execute_skips_none_hook(self):
        from dxrk.plugin import new_hook_manager

        hm = new_hook_manager()
        ran = []
        hm.register("before_load", 0, None)
        hm.register("before_load", 1, lambda ev: ran.append(True))
        assert hm.execute("before_load", "p") is None
        assert ran == [True]


class TestPluginManagerDiscover:
    def test_load_all_with_nil_register(self):
        from dxrk.plugin import Plugin, new_manager
        from dxrk.tools import Registry

        mgr = new_manager(Registry(), "/tmp/dxrk-f8-nope")
        mgr._plugins.append(Plugin(name="ghost"))
        loaded, err = mgr.load_all()
        assert loaded == 0
        assert err is not None and "ghost" in err

    def test_discover_os_error(self, tmp_path):
        from dxrk.plugin import new_manager
        from dxrk.tools import Registry

        probe = tmp_path / "file.txt"
        probe.write_text("x")
        mgr = new_manager(Registry(), str(probe))
        manifests, err = mgr.discover()
        assert manifests == []
        assert err is not None and "read plugins dir" in err

    def test_discover_skips_file_and_manifestless_dir(self, tmp_path):
        from dxrk.plugin import new_manager
        from dxrk.tools import Registry

        (tmp_path / "stray.txt").write_text("x")
        (tmp_path / "empty").mkdir()
        full = tmp_path / "full"
        full.mkdir()
        (full / "plugin.json").write_text("{}")
        mgr = new_manager(Registry(), str(tmp_path))
        manifests, err = mgr.discover()
        assert (manifests, err) == ([], None)


class TestPluginMarketplaceScan:
    def test_scan_os_error(self, tmp_path):
        from dxrk.plugin import new_marketplace

        probe = tmp_path / "file.txt"
        probe.write_text("x")
        mp = new_marketplace(str(probe))
        err = mp.scan()
        assert err is not None and err.startswith("read plugins dir")

    def test_scan_skips_unreadable_and_invalid(self, tmp_path):
        from dxrk.plugin import PluginMetadata, new_marketplace

        plugdir = tmp_path / "plugins"
        plugdir.mkdir()
        (plugdir / "top.txt").write_text("x")
        (plugdir / "nomanifest").mkdir()
        bad = plugdir / "bad"
        bad.mkdir()
        (bad / "plugin.json").write_text("{not json")
        good = plugdir / "good"
        good.mkdir()
        (good / "plugin.json").write_text(PluginMetadata(id="p1", name="P", version="1.0").to_json())
        mp = new_marketplace(str(plugdir))
        assert mp.scan() is None
        assert mp.get("p1") is not None and mp.get("p1").name == "P"


class TestPluginStatusUnknown:
    def test_status_unknown_arm(self):
        from dxrk.plugin import PluginStatus, PolicyLevel

        assert PluginStatus.__str__(255) == "unknown"
        assert PolicyLevel.__str__("nope") == "unknown"


class TestPluginPolicyChecks:
    def _manager(self, **policy_kw):
        from dxrk.plugin import EnterprisePolicy, new_policy_manager

        pm = new_policy_manager()
        pm._policy = EnterprisePolicy(**policy_kw)
        return pm

    def test_blocked_second_entry_matches(self):
        from dxrk.plugin import PluginMetadata

        pm = self._manager(blocked_plugins=["a", "b"])
        allowed, reason = pm.check_install(PluginMetadata(id="b"))
        assert (allowed, reason) == (False, "plugin is in the blocked list")

    def test_allowed_author_passes(self):
        from dxrk.plugin import PluginMetadata

        pm = self._manager(allowed_authors=["alice"])
        allowed, reason = pm.check_install(PluginMetadata(id="p", author="alice"))
        assert (allowed, reason) == (True, "")

    def test_blocked_tags_no_match_iterates(self):
        from dxrk.plugin import PluginMetadata

        pm = self._manager(blocked_tags=["t1", "t2"])
        allowed, reason = pm.check_install(PluginMetadata(id="p", tags=["other"]))
        assert (allowed, reason) == (True, "")

    def test_max_plugins_audit(self):
        from dxrk.plugin import PluginMetadata

        pm = self._manager(max_plugins=3, audit_log=True)
        allowed, reason = pm.check_install(PluginMetadata(id="p"))
        assert (allowed, reason) == (True, "")
        assert any(e.reason == "within plugin limit" for e in pm.get_audit_log())

    def test_audit_log_capped_at_zero(self):
        from dxrk.plugin import PluginMetadata

        pm = self._manager(blocked_plugins=["p"], audit_log=True)
        pm._max_audit = 0
        allowed, _ = pm.check_install(PluginMetadata(id="p"))
        assert allowed is False
        assert pm.get_audit_log() == []

    def test_save_policy_os_error(self, tmp_path):
        from dxrk.plugin import new_policy_manager

        pm = new_policy_manager()
        blocker = tmp_path / "file"
        blocker.write_text("x")
        err = pm.save_policy(str(blocker / "policy.json"))
        assert err


class TestPluginJsonStrict:
    def test_metadata_roundtrip_without_dates(self):
        from dxrk.plugin import PluginMetadata

        meta = PluginMetadata(id="p", name="P", version="1.0")
        text = meta.to_json()
        back = PluginMetadata.from_json(text)
        assert back.id == "p" and back.installed_at is None and back.updated_at is None

    def test_non_object_rejected(self):
        from dxrk.plugin import PluginMetadata

        with pytest.raises(TypeError):
            PluginMetadata.from_json("[1, 2]")

    def test_get_str_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"id": null}').id == ""
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"id": 5}')

    def test_get_int_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"status": null}').status == 0
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"status": true}')

    def test_get_float_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"settings": {"timeout": null}}').settings.timeout == 0.0
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"settings": {"timeout": true}}')

    def test_get_bool_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"enabled": null}').enabled is False
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"enabled": "yes"}')

    def test_get_str_list_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"tags": null}').tags == []
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"tags": [1]}')

    def test_get_str_map_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"settings": {"env": null}}').settings.env == {}
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"settings": {"env": {"k": 1}}}')

    def test_get_obj_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"settings": null}').settings.max_instances == 0
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"settings": 5}')

    def test_get_obj_list_defaults_and_rejects(self):
        from dxrk.plugin import PluginMetadata

        assert PluginMetadata.from_json('{"components": {"skills": null}}').components.skills == []
        with pytest.raises(TypeError):
            PluginMetadata.from_json('{"components": {"skills": [1]}}')


# ═══════════ dxrk/tools/__init__.py ═══════════


class TestToolsRegistry:
    def test_disabled_tool_execute(self):
        from dxrk.tools import ToolDef, build

        tool = build(
            ToolDef(name="t", description="d", input_schema={}, execute=lambda c, i: (1, None), is_enabled=False)
        )
        assert tool.execute(None, {}) == (None, 'tool "t" is not enabled')

    def test_build_rejects(self):
        from dxrk.tools import ToolDef, build

        with pytest.raises(ValueError, match="tool name is required"):
            build(ToolDef())
        with pytest.raises(ValueError, match="execute function is required"):
            build(ToolDef(name="x"))

    def test_duplicate_and_missing(self):
        from dxrk.tools import Registry, ToolDef, ToolError, build

        reg = Registry()
        tool = build(ToolDef(name="t", description="d", input_schema={}, execute=lambda c, i: (1, None)))
        reg.register(tool)
        with pytest.raises(ToolError, match="already registered"):
            reg.register(tool)
        with pytest.raises(ToolError, match="not found"):
            reg.remove("nope")
        reg.remove("t")
        assert len(reg) == 0

    def test_condition_abstract_bodies(self):
        from dxrk.tools import Condition

        assert Condition.match(object(), None) is None
        assert Condition.description(object()) is None

    def test_match_path_brackets_and_escapes(self):
        from dxrk.tools import _match_path

        assert _match_path("a[b", "a[b")
        assert _match_path("[!abc]", "d")
        assert not _match_path("[!abc]", "a")
        assert _match_path("[]a]", "]")
        assert _match_path("a\\*b", "a*b")
        assert not _match_path("a\\*b", "axxb")
        assert _match_path("ab\\", "ab\\")

    def test_extract_paths(self):
        from dxrk.tools import _extract_paths

        assert _extract_paths(None) == []
        assert _extract_paths({"path": "a", "paths": ["b", "c"], "files": "d"}) == ["a", "b", "c", "d"]

    def test_conditional_tool_passthrough(self):
        from dxrk.tools import AlwaysCondition, ConditionalTool, ToolDef, build

        tool = build(
            ToolDef(
                name="t",
                description="d",
                input_schema={"k": "v"},
                execute=lambda c, i: ({"ok": 1}, None),
                is_enabled=True,
                is_read_only=True,
                is_concurrent_safe=True,
            )
        )
        cond = ConditionalTool(tool, AlwaysCondition())
        assert cond.is_active(None) is True
        assert cond.name() == "t"
        assert cond.is_enabled() is True
        assert cond.is_read_only() is True
        assert cond.is_concurrent_safe() is True
        assert cond.input_schema() == {"k": "v"}
        assert cond.validate(None) is None
        assert cond.execute(None, None) == ({"ok": 1}, None)


# ═══════════ dxrk/tools/dxrk.py ═══════════


class TestDxrkDetectTools:
    def test_detect_agents_with_installed(self):
        from dxrk.agents.discovery import InstalledAgent
        from dxrk.models import AgentID
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_detect_agents

        reg = Registry()
        register_detect_agents(reg, object())
        installed = [InstalledAgent(id=AgentID.OPENCODE, config_dir="/tmp/x")]
        with mock.patch("dxrk.tools.dxrk.discover_installed", return_value=installed):
            res, err = reg.get("detect_agents").execute(None, {"home_dir": "/tmp"})
        assert err is None
        assert res == {"agents": [{"id": "opencode", "config_dir": "/tmp/x"}], "count": 1}

    def test_detect_agent_success_and_failure(self):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_detect_agent

        reg = Registry()
        register_detect_agent(reg, None)
        tool = reg.get("detect_agent")
        good = SimpleNamespace(
            detect=lambda home: SimpleNamespace(installed=True, binary_path="/b", config_path="/c", config_found=True),
            tier=SimpleNamespace(value="core"),
        )
        with mock.patch("dxrk.tools.dxrk._get_adapter", return_value=good):
            res, err = tool.execute(None, {"agent": "opencode"})
        assert err is None
        assert res["installed"] is True and res["tier"] == "core"
        bad = SimpleNamespace(detect=lambda home: (_ for _ in ()).throw(RuntimeError("down")), tier="plain")
        with mock.patch("dxrk.tools.dxrk._get_adapter", return_value=bad):
            res, err = tool.execute(None, {"agent": "opencode"})
        assert res is None and err == 'detect "opencode": down'

    def test_adapter_helpers(self):
        from dxrk.models import AgentID
        from dxrk.tools.dxrk import _adapter_registry, _get_adapter, agent_id_value, check_rg_available, tier_value

        assert _get_adapter("definitely-not-an-agent") is None
        assert _get_adapter("opencode") is not None
        assert agent_id_value(AgentID.OPENCODE) == "opencode"
        assert agent_id_value("plain") == "plain"
        assert tier_value(SimpleNamespace()) == ""
        assert tier_value(SimpleNamespace(tier="x")) == "x"
        assert tier_value(SimpleNamespace(tier=SimpleNamespace(value="v"))) == "v"
        import dxrk.tools.dxrk as dxrk_tools

        saved = dxrk_tools._ADAPTER_REGISTRY
        dxrk_tools._ADAPTER_REGISTRY = None
        try:
            first = _adapter_registry()
            assert _adapter_registry() is first
        finally:
            dxrk_tools._ADAPTER_REGISTRY = saved
        with mock.patch.object(shutil, "which", return_value=None):
            assert check_rg_available() is not None and "ripgrep" in check_rg_available()

    def test_system_info_and_diagnostic_errors(self):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_run_diagnostic, register_system_info

        reg = Registry()
        register_system_info(reg, None)
        register_run_diagnostic(reg, None)
        with mock.patch("dxrk.tools.dxrk.system.detect", side_effect=OSError("down")):
            res, err = reg.get("system_info").execute(None, {})
            assert res is None and err == "system detect: down"
            res, err = reg.get("run_diagnostic").execute(None, {})
            assert res is None and err == "down"

    def test_home_and_project_dir_defaults(self):
        from dxrk.tools.dxrk import get_home_dir, get_project_dir

        assert get_home_dir(None) == os.path.expanduser("~")
        assert get_home_dir({}) == os.path.expanduser("~")
        assert get_home_dir({"home_dir": "/x"}) == "/x"
        assert get_project_dir(None) == os.getcwd()
        assert get_project_dir({}) == os.getcwd()
        assert get_project_dir({"project_dir": "/y"}) == "/y"


class TestDxrkListSkills:
    def test_lists_skips_and_dedupes(self, tmp_path, monkeypatch):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_list_skills

        proj = tmp_path / "proj"
        (proj / "skills" / "alpha").mkdir(parents=True)
        (proj / "skills" / "alpha" / "SKILL.md").write_text("# a")
        (proj / "skills" / "beta").mkdir()
        (proj / "skills" / "stray.txt").write_text("x")
        (proj / "skills" / "dup").mkdir()
        (proj / "skills" / "dup" / "SKILL.md").write_text("# dup-p")
        (proj / ".opencode" / "skills" / "dup").mkdir(parents=True)
        (proj / ".opencode" / "skills" / "dup" / "SKILL.md").write_text("# dup-second")
        home = tmp_path / "home"
        (home / ".agents" / "skills" / "dup").mkdir(parents=True)
        (home / ".agents" / "skills" / "dup" / "SKILL.md").write_text("# dup-u")
        (home / ".agents" / "skills" / "extra").mkdir()
        (home / ".agents" / "skills" / "extra" / "SKILL.md").write_text("# e")
        monkeypatch.setenv("HOME", str(home))
        reg = Registry()
        register_list_skills(reg, None)
        orig = os.scandir
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("denied")
            return orig(path)

        with mock.patch.object(os, "scandir", flaky):
            res, err = reg.get("list_skills").execute(None, {"project_dir": str(proj)})
        assert err is None
        names = [s["name"] for s in res["skills"]]
        assert names == ["alpha", "dup"]
        assert res["count"] == 2


class TestDxrkReadFile:
    def test_stat_error(self, tmp_path):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_read_file

        reg = Registry()
        register_read_file(reg, None)
        res, err = reg.get("read_file").execute(None, {"path": str(tmp_path / "nope.txt")})
        assert res is None and err.startswith("stat")

    def test_read_error(self, tmp_path):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_read_file

        probe = tmp_path / "f.txt"
        probe.write_text("data")
        reg = Registry()
        register_read_file(reg, None)
        with mock.patch("builtins.open", side_effect=OSError("denied")):
            res, err = reg.get("read_file").execute(None, {"path": str(probe)})
        assert res is None and "denied" in err


class TestDxrkGrepSearch:
    def _tool(self, name):
        from dxrk.tools import Registry
        from dxrk.tools.dxrk import register_glob_search, register_grep_search

        reg = Registry()
        register_grep_search(reg, None)
        register_glob_search(reg, None)
        return reg.get(name)

    def _seed(self, root, n=3):
        for i in range(n):
            (root / f"f{i}.txt").write_text(f"hello world {i}\n")

    def test_grep_success_with_include_and_path(self, tmp_path):
        tool = self._tool("grep_search")
        self._seed(tmp_path)
        (tmp_path / "skip.log").write_text("hello log\n")
        res, err = tool.execute(None, {"pattern": "hello", "path": str(tmp_path), "include": "*.txt"})
        assert err is None and res["count"] == 3

    def test_grep_uses_project_dir(self, tmp_path):
        tool = self._tool("grep_search")
        self._seed(tmp_path)
        res, err = tool.execute(None, {"pattern": "hello", "project_dir": str(tmp_path)})
        assert err is None and res["count"] == 3

    def test_grep_truncates(self, tmp_path):
        tool = self._tool("grep_search")
        self._seed(tmp_path, n=60)
        res, err = tool.execute(None, {"pattern": "hello", "path": str(tmp_path), "max_results": 5})
        assert err is None and res["count"] == 5 and len(res["results"]) == 5

    def test_grep_no_match_reports_exit_status(self, tmp_path):
        tool = self._tool("grep_search")
        self._seed(tmp_path)
        res, err = tool.execute(None, {"pattern": "zzz-no-match-zzz", "path": str(tmp_path)})
        assert err is None
        assert res == {"results": [], "count": 0, "error": "exit status 1"}

    def test_grep_bad_regex_reports_stderr(self, tmp_path):
        tool = self._tool("grep_search")
        res, err = tool.execute(None, {"pattern": "(", "path": str(tmp_path)})
        assert res is None and err.startswith("rg: ")

    def test_grep_rg_missing(self, tmp_path):
        tool = self._tool("grep_search")
        with mock.patch.object(shutil, "which", return_value=None):
            res, err = tool.execute(None, {"pattern": "x", "path": str(tmp_path)})
        assert err is None and "ripgrep" in res["error"] and res["results"] == []

    def test_glob_success_with_path_and_limit(self, tmp_path):
        tool = self._tool("glob_search")
        sub = tmp_path / "sub"
        sub.mkdir()
        for i in range(30):
            (sub / f"g{i}.txt").write_text("x")
        res, err = tool.execute(None, {"pattern": "*.txt", "path": str(sub), "max_results": 10})
        assert err is None and res["count"] == 10 and len(res["files"]) == 10

    def test_glob_uses_project_dir(self, tmp_path):
        tool = self._tool("glob_search")
        self._seed(tmp_path)
        res, err = tool.execute(None, {"pattern": "*.txt", "project_dir": str(tmp_path)})
        assert err is None and res["count"] == 3

    def test_glob_bad_path_reports_stderr(self, tmp_path):
        tool = self._tool("glob_search")
        res, err = tool.execute(None, {"pattern": "*.txt", "path": str(tmp_path / "nope")})
        assert res is None and err.startswith("rg --files: ")

    def test_glob_silent_failure(self, tmp_path):
        tool = self._tool("glob_search")
        fake = SimpleNamespace(returncode=1, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            res, err = tool.execute(None, {"pattern": "*.txt", "path": str(tmp_path)})
        assert err is None
        assert res == {"files": [], "count": 0, "error": "exit status 1"}

    def test_glob_rg_missing(self, tmp_path):
        tool = self._tool("glob_search")
        with mock.patch.object(shutil, "which", return_value=None):
            res, err = tool.execute(None, {"pattern": "*.txt", "path": str(tmp_path)})
        assert err is None and "ripgrep" in res["error"] and res["files"] == []


# ═══════════ dxrk/query/__init__.py ═══════════


class TestQueryAbstracts:
    def test_provider_and_persistence_bodies(self):
        from dxrk.query import Persistence, Provider

        assert Provider.generate(None, [], []) is None
        assert Persistence.save_turn(None, "", "", "") is None
        assert Persistence.get_project_context(None, "") is None
        assert Persistence.search(None, "", "") is None
        assert Persistence.close(None) is None


class TestQueryOrchestrator:
    def test_execute_one_unknown_tool(self):
        from dxrk.query import Orchestrator, ToolResultBlock, ToolUseBlock
        from dxrk.tools import Registry

        orch = Orchestrator(Registry())
        res = orch._execute_one(ToolUseBlock(id="1", name="nope", input={}), None)
        assert isinstance(res, ToolResultBlock) and res.is_error and "unknown tool" in res.content


class TestQueryLoop:
    def test_interrupted_result_has_no_final_text(self):
        from dxrk.query import Loop, Message
        from dxrk.tools import Registry

        loop = Loop(_F8StaticProvider("x"), Registry(), interrupt=lambda: True)
        result, err = loop.run([Message(role="user", content="q")])
        assert err is None
        assert result.stop_reason == "interrupted" and result.final_text == ""

    def test_persist_error_is_logged(self, caplog):
        from dxrk.query import Loop, Message, Response, ToolUseBlock
        from dxrk.tools import Registry, ToolDef, build

        reg = Registry()
        reg.register(build(ToolDef(name="t", description="d", input_schema={}, execute=lambda c, i: ("ok", None))))

        class _Prov:
            def generate(self, messages, tools):
                if any(m.role == "tool" for m in messages):
                    return Response(text="done"), None
                return Response(text="hi", tool_uses=[ToolUseBlock(id="1", name="t", input={})]), None

        loop = Loop(_Prov(), reg, persistence=_F8ErrPersist())
        with caplog.at_level(logging.ERROR, logger="dxrk.query"):
            result, err = loop.run([Message(role="user", content="q")])
        assert err is None and result.stop_reason == "success"
        assert any("failed to save turn: boom" in r.getMessage() for r in caplog.records)


class TestQueryProviders:
    def _schema_with_unserializable(self):
        from dxrk.query import ToolSchema

        return [ToolSchema(name="t", description="d", input_schema={"x": object()})]

    def test_marshal_errors(self):
        from dxrk.query import (
            AnthropicProvider,
            GeminiProvider,
            Message,
            OllamaProvider,
            OpenAIProvider,
        )

        msgs = [Message(role="user", content="hi")]
        for cls in (AnthropicProvider, OpenAIProvider, GeminiProvider):
            _, err = cls("k", "m").generate(msgs, self._schema_with_unserializable())
            assert err is not None and err.startswith("marshal request"), cls
        _, err = OllamaProvider("m").generate(msgs, self._schema_with_unserializable())
        assert err is not None and err.startswith("marshal request")

    def test_openai_os_error(self):
        from dxrk.query import Message, OpenAIProvider

        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            _, err = OpenAIProvider("k", "m").generate([Message(role="user", content="hi")], [])
        assert err == "http request: down"

    def test_gemini_http_errors(self):
        from dxrk.query import GeminiProvider, Message

        def http_error(*a, **k):
            raise urllib.error.HTTPError("http://x", 500, "boom", {}, io.BytesIO(b"detail"))

        with mock.patch("urllib.request.urlopen", http_error):
            _, err = GeminiProvider("k", "m").generate([Message(role="user", content="hi")], [])
        assert err == "API error (status 500): detail"
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            _, err = GeminiProvider("k", "m").generate([Message(role="user", content="hi")], [])
        assert err == "http request: down"

    def test_ollama_http_errors(self):
        from dxrk.query import Message, OllamaProvider

        def http_error(*a, **k):
            raise urllib.error.HTTPError("http://x", 500, "boom", {}, io.BytesIO(b"detail"))

        with mock.patch("urllib.request.urlopen", http_error):
            _, err = OllamaProvider("m").generate([Message(role="user", content="hi")], [])
        assert err == "API error (status 500): detail"
        with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
            _, err = OllamaProvider("m").generate([Message(role="user", content="hi")], [])
        assert err == "http request: down"

    def test_parse_response_invalid_json(self):
        from dxrk.query import AnthropicProvider, GeminiProvider, OllamaProvider, OpenAIProvider

        for prov in (AnthropicProvider("k", "m"), OpenAIProvider("k", "m"), GeminiProvider("k", "m")):
            _, err = prov._parse_response(b"nope{")
            assert err is not None and err.startswith("parse response"), prov
        _, err = OllamaProvider("m")._parse_response(b"nope{")
        assert err is not None and err.startswith("parse response")


class TestQueryAnthropicParsing:
    def test_unknown_block_skipped(self):
        from dxrk.query import AnthropicProvider

        body = json.dumps({"content": [{"type": "text", "text": "hi"}, {"type": "mystery", "x": 1}]}).encode()
        resp, err = AnthropicProvider("k", "m")._parse_response(body)
        assert err is None and resp.text == "hi" and resp.tool_uses == []

    def test_tool_use_non_object_input(self):
        from dxrk.query import AnthropicProvider

        body = json.dumps({"content": [{"type": "tool_use", "id": "1", "name": "t", "input": "[1]"}]}).encode()
        _, err = AnthropicProvider("k", "m")._parse_response(body)
        assert err == "parse tool_use input: expected object"

    def test_two_text_blocks_joined(self):
        from dxrk.query import AnthropicProvider

        body = json.dumps({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}).encode()
        resp, err = AnthropicProvider("k", "m")._parse_response(body)
        assert err is None and resp.text == "a\nb"


class TestQueryOpenAIParsing:
    def test_empty_choices(self):
        from dxrk.query import OpenAIProvider

        resp, err = OpenAIProvider("k", "m")._parse_response(json.dumps({"usage": {}}).encode())
        assert err is None and resp.text == "" and resp.tool_uses == []

    def test_response_without_tool_calls(self):
        from dxrk.query import OpenAIProvider

        body = json.dumps({"choices": [{"message": {"content": "hi"}}], "usage": {}}).encode()
        resp, err = OpenAIProvider("k", "m")._parse_response(body)
        assert err is None and resp.text == "hi" and resp.tool_uses == []

    def test_non_dict_tool_call_skipped(self):
        from dxrk.query import OpenAIProvider

        body = json.dumps({"choices": [{"message": {"content": "", "tool_calls": [7]}}]}).encode()
        resp, err = OpenAIProvider("k", "m")._parse_response(body)
        assert err is None and resp.tool_uses == []

    def test_tool_call_non_object_arguments(self):
        from dxrk.query import OpenAIProvider

        tc = {"id": "1", "function": {"name": "t", "arguments": "[1]"}}
        body = json.dumps({"choices": [{"message": {"content": "", "tool_calls": [tc]}}]}).encode()
        _, err = OpenAIProvider("k", "m")._parse_response(body)
        assert err == "parse tool_use arguments: expected object"


class TestQueryGeminiParsing:
    def test_empty_candidates(self):
        from dxrk.query import GeminiProvider

        resp, err = GeminiProvider("k", "m")._parse_response(json.dumps({"candidates": []}).encode())
        assert err is None and resp.text == "" and resp.tool_uses == []

    def test_non_dict_content_skipped(self):
        from dxrk.query import GeminiProvider

        body = json.dumps({"candidates": [{"content": 7}]}).encode()
        resp, err = GeminiProvider("k", "m")._parse_response(body)
        assert err is None and resp.tool_uses == []

    def test_non_dict_part_skipped_and_texts_joined(self):
        from dxrk.query import GeminiProvider

        body = json.dumps({"candidates": [{"content": {"parts": [7, {"text": "a"}, {"text": "b"}]}}]}).encode()
        resp, err = GeminiProvider("k", "m")._parse_response(body)
        assert err is None and resp.text == "a\nb"

    def test_function_call_non_object_args(self):
        from dxrk.query import GeminiProvider

        part = {"functionCall": {"name": "f", "args": "[1]"}}
        body = json.dumps({"candidates": [{"content": {"parts": [part]}}]}).encode()
        _, err = GeminiProvider("k", "m")._parse_response(body)
        assert err == "parse functionCall args: expected object"


class TestQueryOllamaParsing:
    def test_tool_role_build_request(self):
        from dxrk.query import Message, OllamaProvider

        req = OllamaProvider("m")._build_request([Message(role="tool", content="x", tool_call_id="1")], [])
        assert req["messages"] == [{"role": "tool", "content": "x"}]

    def test_non_dict_message(self):
        from dxrk.query import OllamaProvider

        resp, err = OllamaProvider("m")._parse_response(json.dumps({"message": 7}).encode())
        assert err is None and resp.text == ""

    def test_non_dict_tool_call_skipped(self):
        from dxrk.query import OllamaProvider

        body = json.dumps({"message": {"content": "", "tool_calls": [7]}}).encode()
        resp, err = OllamaProvider("m")._parse_response(body)
        assert err is None and resp.tool_uses == []

    def test_tool_call_non_object_arguments(self):
        from dxrk.query import OllamaProvider

        tc = {"function": {"name": "t", "arguments": "[1]"}}
        body = json.dumps({"message": {"content": "", "tool_calls": [tc]}}).encode()
        _, err = OllamaProvider("m")._parse_response(body)
        assert err == "parse tool_calls arguments: expected object"


class TestQueryParseTextContent:
    def test_non_dict_items_skipped(self):
        from dxrk.query import parse_text_content

        assert parse_text_content({"content": [42]}) == ""


# ═══════════ dxrk/system/__init__.py ═══════════


class TestSystemHints:
    def test_hint_matrix_pacman_dnf(self):
        from dxrk.system import (
            PlatformProfile,
            _install_hint_curl,
            _install_hint_git,
            _install_hint_go,
        )

        for pm, tool in (("pacman", "pacman"), ("dnf", "dnf")):
            profile = PlatformProfile(os="linux", package_manager=pm)
            assert tool in _install_hint_git(profile)
            assert tool in _install_hint_curl(profile)
        assert (
            _install_hint_go(PlatformProfile(os="linux", package_manager="pacman")) == "sudo pacman -S --noconfirm go"
        )
        assert _install_hint_go(PlatformProfile(os="linux", package_manager="dnf")) == "sudo dnf install -y golang"
        assert (
            _install_hint_go(PlatformProfile(os="linux", package_manager="nix")) == "install go from https://go.dev/dl/"
        )

    def test_install_commands_matrix(self):
        from dxrk.system import (
            OS_WINDOWS,
            PlatformProfile,
            _install_commands_curl,
            _install_commands_git,
            _install_commands_go,
            _install_commands_node,
        )

        unknown = PlatformProfile(os="linux", package_manager="nix")
        assert _install_commands_git(unknown) is None
        assert _install_commands_curl(unknown) is None
        assert _install_commands_node(unknown) is None
        assert _install_commands_go(unknown) is None
        win = PlatformProfile(os=OS_WINDOWS)
        cmds = _install_commands_go(win)
        assert cmds == [
            [
                "winget",
                "install",
                "--id",
                "GoLang.Go",
                "-e",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ]
        ]


class TestSystemDetectDeps:
    def test_parse_version_go_fallback(self):
        from dxrk.system import _parse_version

        assert _parse_version("go", "golang toolchain 1.2.3") == "1.2.3"

    def test_detect_single_dep_os_error(self):
        from dxrk.system import Dependency, _detect_single_dep

        dep = Dependency(name="git", detect_cmd=["git", "--version"])
        with mock.patch("shutil.which", return_value="/bin/git"):
            with mock.patch("subprocess.run", side_effect=OSError("down")):
                out = _detect_single_dep(dep)
        assert out.installed is True and out.version == ""

    def test_detect_single_dep_bad_exit(self):
        from dxrk.system import Dependency, _detect_single_dep

        dep = Dependency(name="git", detect_cmd=["git", "--version"])
        fake = SimpleNamespace(returncode=1, stdout="", stderr="")
        with mock.patch("shutil.which", return_value="/bin/git"):
            with mock.patch("subprocess.run", return_value=fake):
                out = _detect_single_dep(dep)
        assert out.installed is True and out.version == ""

    def test_npm_writable_errors(self):
        from dxrk.system import _detect_npm_writable

        with mock.patch("subprocess.run", side_effect=OSError("down")):
            assert _detect_npm_writable("/home/u") is False
        fake = SimpleNamespace(returncode=1, stdout="", stderr="")
        with mock.patch("subprocess.run", return_value=fake):
            assert _detect_npm_writable("/home/u") is False

    def test_detect_windows(self):
        from dxrk.system import detect

        with mock.patch("platform.system", return_value="Windows"):
            res = detect()
        assert res.system.os == "windows"
        assert res.system.profile.npm_writable is True

    def test_detect_linux_os_release_unreadable(self):
        from dxrk.system import detect

        real_open = open

        def guarded_open(path, *args, **kwargs):
            if str(path) == "/etc/os-release":
                raise OSError("denied")
            return real_open(path, *args, **kwargs)

        with mock.patch("platform.system", return_value="Linux"):
            with mock.patch("builtins.open", guarded_open):
                res = detect()
        assert res.system.profile.linux_distro == "unknown"


class TestSystemPath:
    def test_add_to_process_path_empty(self, monkeypatch):
        from dxrk.system import _add_to_process_path

        monkeypatch.setenv("PATH", "")
        _add_to_process_path("/x/bin")
        assert os.environ["PATH"] == "/x/bin"

    def test_path_contains_posix(self, monkeypatch):
        from dxrk.system import _path_contains

        monkeypatch.setenv("PATH", "/a:/b")
        assert _path_contains("/b") is True
        assert _path_contains("/c") is False

    def test_add_to_user_path_windows(self, monkeypatch):
        from dxrk.system import add_to_user_path

        calls = []
        monkeypatch.setattr("platform.system", lambda: "Windows")
        monkeypatch.setattr("subprocess.run", lambda *a, **k: calls.append(a))
        monkeypatch.setenv("PATH", "C:\\Win")
        add_to_user_path("C:\\Tools")
        assert os.environ["PATH"].startswith("C:\\Tools")
        assert calls and calls[0][0][0] == "powershell"
        before = len(calls)
        with mock.patch("dxrk.system._path_contains", return_value=True):
            add_to_user_path("C:\\Tools")
        assert len(calls) == before


# ═══════════ dxrk/skillregistry.py ═══════════

_F8_SKILL_MD = """---
name: myskill
description: does things
---

## Compact Rules

- rule one
- rule two
"""


class TestSkillRegenerate:
    def _seed(self, cwd, home):
        (cwd / "skills" / "myskill").mkdir(parents=True)
        (cwd / "skills" / "myskill" / "SKILL.md").write_text(_F8_SKILL_MD)

    def test_regenerate_and_cache_hit(self, tmp_path):
        from dxrk.skillregistry import regenerate

        cwd = tmp_path / "proj"
        cwd.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        self._seed(cwd, home)
        first = regenerate(str(cwd), str(home), True)
        assert first.regenerated is True and first.skill_count == 1
        assert first.reason == "forced"
        second = regenerate(str(cwd), str(home), False)
        assert second.regenerated is False and second.reason == "cache-hit"

    def test_regenerate_relpath_value_error(self, tmp_path):
        from dxrk.skillregistry import regenerate

        cwd = tmp_path / "proj"
        cwd.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        self._seed(cwd, home)
        with mock.patch.object(os.path, "relpath", side_effect=ValueError("drv")):
            res = regenerate(str(cwd), str(home), True)
        assert res.regenerated is True and res.skill_count == 1

    def test_regenerate_atl_mkdir_fails(self, tmp_path):
        from dxrk.skillregistry import regenerate

        cwd = tmp_path / "proj"
        cwd.mkdir()
        (cwd / ".atl").write_text("blocker")
        with pytest.raises(OSError, match="create .atl directory"):
            regenerate(str(cwd), str(tmp_path / "home"), True)

    def test_regenerate_write_failures(self, tmp_path):
        from dxrk.skillregistry import regenerate

        cwd = tmp_path / "proj"
        cwd.mkdir()
        home = tmp_path / "home"
        home.mkdir()
        self._seed(cwd, home)
        with mock.patch("dxrk.components.filemerge.write_file_atomic", side_effect=OSError("disk")):
            with pytest.raises(OSError, match="write registry"):
                regenerate(str(cwd), str(home), True)
        with mock.patch("dxrk.components.filemerge.write_file_atomic", side_effect=[None, OSError("disk")]):
            with pytest.raises(OSError, match="write registry cache"):
                regenerate(str(cwd), str(home), True)


class TestSkillEnsureIgnored:
    def test_no_gitignore(self, tmp_path):
        from dxrk.skillregistry import ensure_atl_ignored

        ensure_atl_ignored(str(tmp_path))
        assert (tmp_path / ".gitignore").read_text() == "# Local AI runtime state\n.atl/\n"

    def test_already_ignored(self, tmp_path):
        from dxrk.skillregistry import ensure_atl_ignored

        (tmp_path / ".gitignore").write_text("node_modules\n.atl/\n")
        ensure_atl_ignored(str(tmp_path))
        assert (tmp_path / ".gitignore").read_text() == "node_modules\n.atl/\n"

    def test_missing_trailing_newline(self, tmp_path):
        from dxrk.skillregistry import ensure_atl_ignored

        (tmp_path / ".gitignore").write_text("node_modules")
        ensure_atl_ignored(str(tmp_path))
        assert (tmp_path / ".gitignore").read_text().endswith("\n.atl/\n")

    def test_existing_header_not_duplicated(self, tmp_path):
        from dxrk.skillregistry import ensure_atl_ignored

        (tmp_path / ".gitignore").write_text("# Local Pi runtime state\n")
        ensure_atl_ignored(str(tmp_path))
        text = (tmp_path / ".gitignore").read_text()
        assert text.count("runtime state") == 1 and text.endswith(".atl/\n")


class TestSkillLoadVariants:
    def test_missing_file(self, tmp_path):
        from dxrk.skillregistry import load_skill

        assert load_skill(str(tmp_path / "nope" / "SKILL.md")) is None

    def test_no_frontmatter_uses_dirname(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "cool"
        d.mkdir()
        (d / "SKILL.md").write_text("## Compact Rules\n- r1\n")
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.name == "cool" and entry.rules == ["r1"]

    def test_unclosed_frontmatter(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: x\nno end here\n")
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.name == "s"

    def test_body_without_leading_newline(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: n\n---body\n- r\n")
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.name == "n"

    def test_junk_and_unknown_frontmatter_keys(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "s"
        d.mkdir()
        (d / "SKILL.md").write_text('---\nname: "n"\njust junk\ntitle: x\ndescription: d\n---\nbody\n')
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.name == "n" and entry.description == "d"


class TestSkillFindFiles:
    def test_walk_error_mid_loop_and_names(self):
        from dxrk.skillregistry import _find_all_skill_files

        def walk_mid(root, **kw):
            yield ("/x", [], ["other.txt"])
            kw["onerror"](OSError("denied"))
            yield ("/x/sub", [], ["SKILL.md"])

        with mock.patch.object(os, "walk", walk_mid):
            with pytest.raises(OSError, match="denied"):
                _find_all_skill_files(["/x"])

    def test_walk_error_at_end(self):
        from dxrk.skillregistry import _find_all_skill_files

        def walk_err(root, **kw):
            if kw.get("onerror"):
                kw["onerror"](OSError("denied"))
            return iter([])

        with mock.patch.object(os, "walk", walk_err):
            with pytest.raises(OSError, match="denied"):
                _find_all_skill_files(["/x"])


class TestSkillTableRules:
    def test_table_rows_header_separator_and_short(self, tmp_path):
        from dxrk.skillregistry import load_skill

        body = (
            "---\nname: t\n---\n## Compact Rules\n"
            "| Rule | Requirement |\n| --- | --- |\n| keep | must stay |\n|only|\n|  | empty |\n"
            "| Target | Test Pattern |\n| --- | --- |\n| a | b |\n"
        )
        d = tmp_path / "t"
        d.mkdir()
        (d / "SKILL.md").write_text(body)
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.rules == ["keep: must stay", "a: b"]

    def test_prose_lines_ignored(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "t"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: t\n---\n## Compact Rules\nSome prose here.\n- rule one\n")
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.rules == ["rule one"]

    def test_crlf_file_parses_rules(self, tmp_path):
        from dxrk.skillregistry import load_skill

        d = tmp_path / "t"
        d.mkdir()
        d.joinpath("SKILL.md").write_bytes(b"---\r\nname: t\r\n---\r\n## Compact Rules\r\n- keep\r\n- drop\r\n")
        entry = load_skill(str(d / "SKILL.md"))
        assert entry is not None and entry.rules == ["keep", "drop"]


class TestSkillCacheHelpers:
    def test_fingerprint_missing_file(self, tmp_path):
        from dxrk.skillregistry import _file_exists, fingerprint

        probe = tmp_path / "real.md"
        probe.write_text("x")
        digest = fingerprint([str(tmp_path / "nope.md"), str(probe)])
        assert len(digest) == 40
        assert _file_exists(str(tmp_path / "nope.md")) is False

    def test_cached_fingerprint_bad_json(self, tmp_path):
        from dxrk.skillregistry import _read_cached_fingerprint

        cache = tmp_path / "cache.json"
        cache.write_text("{bad")
        assert _read_cached_fingerprint(str(cache)) == ""
        assert _read_cached_fingerprint(str(tmp_path / "missing.json")) == ""


# ═══════════ dxrk/observe/__init__.py ═══════════


class TestObserveLogger:
    def test_set_level_filters(self):
        from dxrk.log import Level
        from dxrk.observe import Logger

        out = StringIO()
        logger = Logger("t", Level.INFO)
        logger.set_output(out)
        logger.debug("hidden")
        assert out.getvalue() == ""
        logger.set_level(Level.DEBUG)
        logger.debug("shown")
        assert "shown" in out.getvalue()


class TestObserveMetrics:
    def test_named_objects_reused(self):
        from dxrk.observe import new_metrics_registry

        reg = new_metrics_registry()
        assert reg.counter("c") is reg.counter("c")
        assert reg.gauge("g") is reg.gauge("g")
        assert reg.histogram("h") is reg.histogram("h")

    def test_snapshot_str_with_histogram(self):
        from dxrk.observe import new_metrics_registry

        reg = new_metrics_registry()
        reg.counter("c").inc()
        reg.gauge("g").set(1.5)
        reg.histogram("h").observe(1.0)
        reg.histogram("h").observe(6000.0)
        text = str(reg.snapshot())
        assert "counter c: 1" in text
        assert "gauge g: 1.50" in text
        assert "histogram h: total=2" in text

    def test_latency_ms(self):
        from dxrk.observe import latency_ms

        assert latency_ms(timedelta(seconds=2)) == 2000.0


class TestObserveTracing:
    def test_end_without_start_is_noop(self):
        from dxrk.observe import CURRENT_SPAN, Span

        Span("x").end()
        assert CURRENT_SPAN.get() is None

    def test_span_lifecycle(self):
        from datetime import datetime

        from dxrk.observe import (
            CURRENT_SPAN,
            Attribute,
            new_tracer,
            span_add_event,
            span_from_context,
            span_record_duration,
        )

        tracer = new_tracer("t")
        _, span = tracer.start(None, "op", Attribute("k", "v"))
        try:
            assert span_from_context(None) is span
            span.set_attributes(Attribute("k2", 1))
            span.record_error(ValueError("bad"))
            span.set_status("ERROR", "bad")
            span.add_event("note", [Attribute("n", 1)])
            span_add_event(None, "extra", Attribute("e", True))
            span_record_duration(None, "phase", datetime.now())
            names = [name for name, _ in span._events]
            assert names == ["exception", "note", "extra", "phase.done"]
        finally:
            span.end()
        assert CURRENT_SPAN.get() is None
        assert span_from_context(None)._name == ""
