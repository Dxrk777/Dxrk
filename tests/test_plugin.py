# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from datetime import datetime

from dxrk.plugin import (
    AuditEntry,
    HookAfterToolExec,
    HookBeforeLoad,
    HookEvent,
    Manager,
    MarketplaceEvent,
    Plugin,
    PluginApprovalConfig,
    PluginComponents,
    PluginHook,
    PluginMCP,
    PluginMetadata,
    PluginSettings,
    PluginSkill,
    PluginStatus,
    PluginTimeoutPolicy,
    PluginTool,
    PolicyLevel,
    new_hook_manager,
    new_manager,
    new_marketplace,
    new_policy_manager,
)
from dxrk.strconst import StrEnabled, StrUnknown
from dxrk.tools import Registry, ToolDef, ToolError, build


def _noop_register(registry: Registry) -> str | None:
    return None


def _register_plugin_tool(registry: Registry) -> str | None:
    tool = build(
        ToolDef(
            name="plugin_tool",
            execute=lambda ctx, input_: ("plugin result", None),
        )
    )
    try:
        registry.register(tool)
    except ToolError as exc:
        return str(exc)
    return None


class TestManager:
    def test_new_manager(self):
        m = new_manager(Registry(), "/tmp/plugins")
        assert isinstance(m, Manager)

    def test_load_all_empty(self):
        m = new_manager(Registry(), "/tmp/plugins")
        count, err = m.load_all()
        assert err is None
        assert count == 0

    def test_register_and_load_all(self):
        reg = Registry()
        m = new_manager(reg, "/tmp/plugins")
        err = m.register(Plugin(name="test-plugin", register=_register_plugin_tool))
        assert err is None

        count, load_err = m.load_all()
        assert load_err is None
        assert count == 1

        tool = reg.get("plugin_tool")
        assert tool is not None
        assert tool.name() == "plugin_tool"

    def test_register_empty_name(self):
        m = new_manager(Registry(), "/tmp/plugins")
        err = m.register(Plugin(register=_noop_register))
        assert err is not None
        assert "name is required" in err

    def test_register_nil_register(self):
        m = new_manager(Registry(), "/tmp/plugins")
        err = m.register(Plugin(name="noop"))
        assert err is not None
        assert 'plugin "noop": Register function is required' == err

    def test_plugins_list(self):
        m = new_manager(Registry(), "/tmp/plugins")
        assert m.register(Plugin(name="p1", register=_noop_register)) is None
        assert m.register(Plugin(name="p2", register=_noop_register)) is None
        assert len(m.plugins()) == 2

    def test_load_all_stops_on_first_error(self):
        def failing(registry: Registry) -> str | None:
            return "boom"

        m = new_manager(Registry(), "/tmp/plugins")
        assert m.register(Plugin(name="ok", register=_noop_register)) is None
        assert m.register(Plugin(name="bad", register=failing)) is None
        count, err = m.load_all()
        assert count == 1
        assert err == 'load plugin "bad": boom'

    def test_discover_nonexistent_dir(self, tmp_path):
        m = new_manager(Registry(), tmp_path / "nonexistent-plugins-dir")
        manifests, err = m.discover()
        assert err is None
        assert manifests == []

    def test_discover_empty_dir(self, tmp_path):
        m = new_manager(Registry(), tmp_path)
        manifests, err = m.discover()
        assert err is None
        assert manifests == []


class TestHookManager:
    def test_register_returns_id(self):
        hm = new_hook_manager()
        hook_id = hm.register(HookBeforeLoad, 0, lambda event: None)
        assert hook_id == "hook-1"
        assert hm.hook_count(HookBeforeLoad) == 1
        assert hm.total_hooks() == 1

    def test_priority_order_lower_runs_first(self):
        hm = new_hook_manager()
        order: list[int] = []
        hm.register(HookBeforeLoad, 10, lambda event: order.append(1) or None)
        hm.register(HookBeforeLoad, 5, lambda event: order.append(2) or None)
        hm.register(HookBeforeLoad, 0, lambda event: order.append(3) or None)
        err = hm.execute(HookBeforeLoad, "plugin-a", {})
        assert err is None
        assert order == [3, 2, 1]

    def test_execute_error_aborts_remaining(self):
        called: list[str] = []

        def first(event: HookEvent) -> str | None:
            called.append("first")
            return "boom"

        def second(event: HookEvent) -> str | None:
            called.append("second")
            return None

        hm = new_hook_manager()
        hm.register(HookBeforeLoad, 1, first)
        hm.register(HookBeforeLoad, 2, second)
        err = hm.execute(HookBeforeLoad, "plugin-a", None)
        assert err == "hook before_load (hook-1) failed: boom"
        assert called == ["first"]

    def test_event_fields(self):
        captured: list[HookEvent] = []

        def capture(event: HookEvent) -> str | None:
            captured.append(event)
            return None

        hm = new_hook_manager()
        hm.register(HookAfterToolExec, 0, capture)
        err = hm.execute(HookAfterToolExec, "plugin-a", {"status": "ok"})
        assert err is None
        assert captured[0].point == HookAfterToolExec
        assert captured[0].plugin_id == "plugin-a"
        assert captured[0].data == {"status": "ok"}
        assert captured[0].time is not None

    def test_remove(self):
        hm = new_hook_manager()
        first = hm.register(HookBeforeLoad, 0, lambda event: None)
        hm.register(HookBeforeLoad, 0, lambda event: None)
        hm.remove(first)
        assert hm.hook_count(HookBeforeLoad) == 1
        assert hm.total_hooks() == 1

    def test_clear(self):
        hm = new_hook_manager()
        hm.register(HookBeforeLoad, 0, lambda event: None)
        hm.clear()
        assert hm.total_hooks() == 0


class TestMarketplace:
    def _meta(
        self, plugin_id: str = "plug-a", name: str = "Plug A", version: str = "1.0.0"
    ) -> PluginMetadata:
        return PluginMetadata(
            id=plugin_id,
            name=name,
            version=version,
            author="alice",
            tags=["tag1"],
            status=PluginStatus.StatusInstalled,
        )

    def test_scan_missing_dir(self, tmp_path):
        mp = new_marketplace(tmp_path / "no-such-dir")
        assert mp.scan() is None
        assert mp.list_plugins() == []

    def test_scan_parses_manifests(self, tmp_path):
        plug_dir = tmp_path / "alpha"
        plug_dir.mkdir()
        (plug_dir / "plugin.json").write_text(
            json.dumps({"id": "alpha", "name": "Alpha", "version": "1.0.0"})
        )
        mp = new_marketplace(tmp_path)
        assert mp.scan() is None
        meta = mp.get("alpha")
        assert meta is not None
        assert meta.name == "Alpha"
        assert meta.status == PluginStatus.StatusInstalled

    def test_scan_skips_invalid_manifests(self, tmp_path):
        plug_dir = tmp_path / "bad"
        plug_dir.mkdir()
        (plug_dir / "plugin.json").write_text("{not json")
        mp = new_marketplace(tmp_path)
        assert mp.scan() is None
        assert mp.list_plugins() == []

    def test_scan_skips_plain_files(self, tmp_path):
        (tmp_path / "plugin.json").write_text('{"id": "root"}')
        mp = new_marketplace(tmp_path)
        assert mp.scan() is None
        assert mp.list_plugins() == []

    def test_install_and_get(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta()) is None
        stored = mp.get("plug-a")
        assert stored is not None
        assert stored.status == PluginStatus.StatusEnabled
        assert stored.enabled is True
        assert stored.installed_at is not None

    def test_install_duplicate(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta()) is None
        err = mp.install(self._meta())
        assert err == "plugin plug-a already installed"

    def test_install_stores_a_copy(self):
        mp = new_marketplace("/tmp/plugins")
        meta = self._meta()
        assert mp.install(meta) is None
        meta.name = "Mutated"
        stored = mp.get("plug-a")
        assert stored is not None
        assert stored.name == "Plug A"

    def test_uninstall(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta()) is None
        assert mp.uninstall("plug-a") is None
        assert mp.get("plug-a") is None
        assert mp.uninstall("plug-a") == "plugin plug-a not found"

    def test_enable_disable(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta()) is None

        assert mp.disable("plug-a") is None
        meta = mp.get("plug-a")
        assert meta is not None
        assert meta.enabled is False
        assert meta.status == PluginStatus.StatusDisabled

        assert mp.enable("plug-a") is None
        meta = mp.get("plug-a")
        assert meta is not None
        assert meta.enabled is True
        assert meta.status == PluginStatus.StatusEnabled

        assert mp.enable("nope") == "plugin nope not found"
        assert mp.disable("nope") == "plugin nope not found"

    def test_list_sorted_by_name(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta("p2", "Beta")) is None
        assert mp.install(self._meta("p1", "Alpha")) is None
        assert [m.name for m in mp.list_plugins()] == ["Alpha", "Beta"]

    def test_enabled_plugins(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta("p1", "Alpha")) is None
        assert mp.install(self._meta("p2", "Beta")) is None
        assert mp.disable("p2") is None
        assert [m.id for m in mp.enabled_plugins()] == ["p1"]

    def test_update_available(self):
        mp = new_marketplace("/tmp/plugins")
        assert mp.install(self._meta(version="1.0.0")) is None
        assert mp.update_available("plug-a", "1.1.0") is True
        assert mp.update_available("plug-a", "1.0.0") is False
        assert mp.update_available("nope", "1.0.0") is False

    def test_on_change_events(self):
        events: list[MarketplaceEvent] = []
        mp = new_marketplace("/tmp/plugins")
        mp.set_on_change(events.append)
        assert mp.install(self._meta()) is None
        assert mp.disable("plug-a") is None
        assert mp.enable("plug-a") is None
        assert mp.uninstall("plug-a") is None
        assert [(e.type, e.plugin_id) for e in events] == [
            ("installed", "plug-a"),
            ("disabled", "plug-a"),
            (StrEnabled, "plug-a"),
            ("removed", "plug-a"),
        ]

    def test_metadata_json_roundtrip(self):
        meta = PluginMetadata(
            id="m1",
            name="M1",
            version="2.0.0",
            description="desc",
            author="bob",
            license="MIT",
            tags=["ai", "tools"],
            homepage="https://example.com",
            repository="https://repo",
            components=PluginComponents(
                skills=[PluginSkill(name="s1", path="skills/s1", description="skill")],
                hooks=[PluginHook(name="h1", point=HookBeforeLoad, priority=5)],
                mcps=[
                    PluginMCP(
                        name="mcp1",
                        command="npx",
                        args=["-y", "pkg"],
                        env={"K": "V"},
                    )
                ],
                tools=[PluginTool(name="t1", description="tool")],
            ),
            settings=PluginSettings(
                requires_approval=True,
                max_instances=3,
                timeout=5.0,
                env={"A": "b"},
            ),
            status=PluginStatus.StatusEnabled,
            installed_at=datetime(2026, 1, 1, 12, 0, 0),
            updated_at=datetime(2026, 1, 2, 12, 0, 0),
            enabled=True,
        )
        assert PluginMetadata.from_json(meta.to_json()) == meta


class TestPluginStatusStrings:
    def test_status_strings(self):
        assert str(PluginStatus.StatusInstalled) == "installed"
        assert str(PluginStatus.StatusEnabled) == "enabled"
        assert str(PluginStatus.StatusDisabled) == "disabled"
        assert str(PluginStatus.StatusUpdating) == "updating"
        assert str(PluginStatus.StatusError) == "error"

    def test_level_strings(self):
        assert str(PolicyLevel.PolicyAdvisory) == "advisory"
        assert str(PolicyLevel.PolicyEnforce) == "enforce"


class TestPolicyManager:
    def _meta(self, plugin_id: str = "plug-a", author: str = "alice") -> PluginMetadata:
        return PluginMetadata(
            id=plugin_id,
            name="Plug A",
            version="2.0.0",
            author=author,
            tags=["tag1"],
        )

    def test_defaults(self):
        pm = new_policy_manager()
        policy = pm.get_policy()
        assert policy.level == PolicyLevel.PolicyAdvisory
        assert policy.max_plugins == 0
        assert policy.audit_log is False
        assert policy.allowed_plugins == []
        assert policy.blocked_plugins == []
        assert policy.allowed_authors == []
        assert policy.max_plugin_version == ""
        assert policy.required_tags == []
        assert policy.blocked_tags == []
        assert policy.restricted_hooks == []
        assert policy.approval_required == PluginApprovalConfig()
        assert policy.timeout_policy == PluginTimeoutPolicy(
            max_load_time=10.0, max_hook_time=30.0, max_mcp_start_time=15.0
        )

    def test_check_install_blocked(self):
        pm = new_policy_manager()
        pm._policy.blocked_plugins = ["plug-a"]
        allowed, reason = pm.check_install(self._meta())
        assert allowed is False
        assert reason == "plugin is in the blocked list"

    def test_check_install_allowlist(self):
        pm = new_policy_manager()
        pm._policy.allowed_plugins = ["plug-a", "plug-b"]

        allowed, reason = pm.check_install(self._meta("plug-c"))
        assert allowed is False
        assert reason == "plugin is not in the allowed list"

        allowed, reason = pm.check_install(self._meta("plug-a"))
        assert allowed is True
        assert reason == ""

    def test_check_install_author(self):
        pm = new_policy_manager()
        pm._policy.allowed_authors = ["alice"]
        allowed, reason = pm.check_install(self._meta(author="bob"))
        assert allowed is False
        assert reason == "plugin author is not in the allowed authors list"

    def test_check_install_blocked_tag(self):
        pm = new_policy_manager()
        pm._policy.blocked_tags = ["blocked"]
        meta = self._meta()
        meta.tags = ["tag1", "blocked"]
        allowed, reason = pm.check_install(meta)
        assert allowed is False
        assert reason == "plugin has blocked tag: blocked"

    def test_check_install_passes(self):
        pm = new_policy_manager()
        allowed, reason = pm.check_install(self._meta())
        assert allowed is True
        assert reason == ""

    def test_check_hook_exec(self):
        pm = new_policy_manager()
        pm._policy.restricted_hooks = [HookBeforeLoad]
        allowed, reason = pm.check_hook_exec("plug-a", HookBeforeLoad)
        assert allowed is False
        assert reason == "hook before_load requires approval"

        allowed, reason = pm.check_hook_exec("plug-a", HookAfterToolExec)
        assert allowed is True
        assert reason == ""

    def test_is_plugin_allowed(self):
        pm = new_policy_manager()
        assert pm.is_plugin_allowed("plug-a") is True

        pm._policy.blocked_plugins = ["plug-a"]
        assert pm.is_plugin_allowed("plug-a") is False
        assert pm.is_plugin_allowed("plug-b") is True

        pm._policy.blocked_plugins = []
        pm._policy.allowed_plugins = ["plug-a"]
        assert pm.is_plugin_allowed("plug-a") is True
        assert pm.is_plugin_allowed("plug-b") is False

    def test_audit_log_disabled_by_default(self):
        pm = new_policy_manager()
        pm.check_install(self._meta())
        assert pm.get_audit_log() == []

    def test_audit_log_records_entries(self):
        pm = new_policy_manager()
        pm._policy.audit_log = True
        pm.check_install(self._meta())
        pm.check_install(self._meta("plug-b"))
        entries = pm.get_audit_log()
        assert len(entries) == 2
        assert entries[0].action == "install"
        assert entries[0].plugin_id == "plug-a"
        assert entries[0].allowed is True
        assert entries[1].plugin_id == "plug-b"

    def test_audit_log_keeps_failed_checks(self):
        pm = new_policy_manager()
        pm._policy.audit_log = True
        pm._policy.blocked_plugins = ["plug-a"]
        pm.check_install(self._meta())
        entries = pm.get_audit_log()
        assert len(entries) == 1
        assert entries[0].allowed is False
        assert entries[0].reason == "plugin is blocked"

    def test_audit_log_trims_to_max(self):
        pm = new_policy_manager()
        pm._policy.audit_log = True
        pm._max_audit = 3
        for index in range(6):
            pm.check_install(self._meta(f"p{index}"))
        entries = pm.get_audit_log()
        assert len(entries) == 3
        assert [e.plugin_id for e in entries] == ["p3", "p4", "p5"]

    def test_save_load_policy_roundtrip(self, tmp_path):
        pm = new_policy_manager()
        pm._policy.level = PolicyLevel.PolicyEnforce
        pm._policy.blocked_plugins = ["plug-a"]
        pm._policy.restricted_hooks = [HookBeforeLoad]
        pm._policy.timeout_policy.max_load_time = 20.0

        path = tmp_path / "policies" / "policy.json"
        assert pm.save_policy(path) is None
        assert path.exists()

        pm2 = new_policy_manager()
        assert pm2.load_policy(path) is None
        policy = pm2.get_policy()
        assert policy.level == PolicyLevel.PolicyEnforce
        assert policy.blocked_plugins == ["plug-a"]
        assert policy.restricted_hooks == [HookBeforeLoad]
        assert policy.timeout_policy.max_load_time == 20.0

    def test_save_policy_creates_dirs(self, tmp_path):
        pm = new_policy_manager()
        assert pm.save_policy(tmp_path / "a" / "b" / "policy.json") is None
        assert (tmp_path / "a" / "b" / "policy.json").exists()

    def test_load_policy_missing_file(self, tmp_path):
        pm = new_policy_manager()
        err = pm.load_policy(tmp_path / "nope.json")
        assert err is not None
        assert err.startswith("read policy file:")

    def test_load_policy_invalid_json(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text("{not json")
        pm = new_policy_manager()
        err = pm.load_policy(path)
        assert err is not None
        assert err.startswith("parse policy:")

    def test_audit_entry_defaults(self):
        entry = AuditEntry()
        assert entry.action == ""
        assert entry.plugin_id == ""
        assert entry.allowed is False
        assert entry.details == {}

    def test_policy_json_unknown_constants(self):
        assert StrUnknown == "unknown"
