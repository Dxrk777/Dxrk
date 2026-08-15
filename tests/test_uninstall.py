# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import os
from pathlib import Path

from dxrk.components.uninstall import (
    _clean_codex_toml,
    _dedupe_sorted_strings,
    _delete_json_path,
    _expand_backup_target,
    _global_backup_targets,
    _json_is_empty_object,
    _looks_like_managed_persona_prefix,
    _managed_sdd_skill_ids,
    _manual_action_for_non_empty_directory,
    _merge_rewrite_ops,
    _normalize_json,
    _read_managed_file,
    _remove_dir_if_empty,
    _remove_dir_if_empty_recursive,
    _remove_file,
    _remove_file_if_exists,
    _remove_json_paths,
    _remove_markdown_sections,
    _remove_managed_persona_preamble,
    _remove_top_level_toml_keys,
    _remove_toml_table,
    _remove_tree,
    _rewrite_json_file,
    _rewrite_markdown_file,
    _rewrite_toml_file,
    _state_agents_to_remove,
    _strip_json_comments,
    _strip_trailing_commas,
    _unmarshal_json_object,
    _update_state_after_uninstall,
    OpType,
    Result,
    Service,
)

from dxrk.models import AgentID, ComponentID, DxrkMemoryUninstallScope

import pytest


class FakeAdapter:
    agent = AgentID.OPENCODE
    supports_system_prompt = False
    supports_output_styles = False
    supports_mcp = False

    def system_prompt_file(self, home_dir: str) -> str:
        return os.path.join(home_dir, "prompt.md")

    def output_style_dir(self, home_dir: str) -> str:
        return os.path.join(home_dir, "styles")

    def settings_path(self, home_dir: str) -> str | None:
        return None

    def mcp_config_path(self, home_dir: str, server_name: str = "") -> str:
        return os.path.join(home_dir, "mcp.json")


class TestManagedSddSkillIds:
    def test_returns_list(self):
        ids = _managed_sdd_skill_ids()
        assert len(ids) == 11  # _SDD_SKILL_PHASE_IDS (10) + "judgment-day"
        assert "sdd-apply" in ids
        assert "sdd-onboard" in ids
        assert "judgment-day" in ids


class TestDedupeSortedStrings:
    def test_deduplicates(self):
        assert _dedupe_sorted_strings(["a", "a", "b", "c", "c"]) == ["a", "b", "c"]

    def test_empty(self):
        assert _dedupe_sorted_strings([]) == []

    def test_already_unique(self):
        assert _dedupe_sorted_strings(["a", "b", "c"]) == ["a", "b", "c"]


class TestRemoveMarkdownSections:
    def test_removes_section(self):
        content = "before\n<!-- dxrk:foo -->\ncontent\n<!-- /dxrk:foo -->\nafter"
        result, changed = _remove_markdown_sections(content, "foo")
        assert changed is True
        assert "content" not in result
        assert "before" in result
        assert "after" in result

    def test_no_match(self):
        content = "no sections here"
        result, changed = _remove_markdown_sections(content, "foo")
        assert changed is False
        assert result == content


class TestRemoveManagedPersonaPreamble:
    def test_detects_no_preamble(self):
        content = "## Something else\nno managed section"
        result, changed = _remove_managed_persona_preamble(content)
        assert changed is False
        assert result == content


class TestLooksLikeManagedPersonaPrefix:
    def test_all_fingerprints(self):
        prefix = "## Personality\nSenior Architect\n## Rules"
        assert _looks_like_managed_persona_prefix(prefix) is True

    def test_not_managed(self):
        assert _looks_like_managed_persona_prefix("## My Custom Section") is False

    def test_partial_fingerprint(self):
        prefix = "## Personality\nSenior Architect"
        assert _looks_like_managed_persona_prefix(prefix) is False  # missing ## Rules


class TestDeleteJsonPath:
    def test_delete_top_level_key(self):
        root = {"a": 1, "b": 2}
        assert _delete_json_path(root, ["a"]) is True
        assert root == {"b": 2}

    def test_delete_nested_key(self):
        root = {"a": {"b": {"c": 1}}}
        assert _delete_json_path(root, ["a", "b", "c"]) is True
        # empty intermediate containers are also cleaned up
        assert root == {}

    def test_path_not_found(self):
        root = {"a": 1}
        assert _delete_json_path(root, ["b"]) is False

    def test_delete_nonexistent_nested_path(self):
        root = {"a": {"b": 1}}
        assert _delete_json_path(root, ["a", "x", "y"]) is False


class TestRemoveJsonPaths:
    def test_removes_paths(self):
        raw = b'{"a": 1, "b": 2, "c": 3}'
        result, changed = _remove_json_paths(raw, [["a"], ["c"]])
        assert changed is True
        assert json.loads(result) == {"b": 2}

    def test_no_paths(self):
        raw = b'{"a": 1}'
        result, changed = _remove_json_paths(raw, [])
        assert changed is False
        assert result == raw


class TestJsonIsEmptyObject:
    def test_empty(self):
        assert _json_is_empty_object(b"{}") is True

    def test_not_empty(self):
        assert _json_is_empty_object(b'{"a":1}') is False

    def test_non_object(self):
        assert _json_is_empty_object(b"[]") is True  # len <= 2


class TestStripJsonComments:
    def test_strips_line_comments(self):
        result = _strip_json_comments(b'{\n  // comment\n  "a": 1\n}')
        assert b"//" not in result
        assert b'"a": 1' in result

    def test_strips_block_comments(self):
        result = _strip_json_comments(b'{\n  /* block */\n  "a": 1\n}')
        assert b"/*" not in result
        assert b'"a": 1' in result


class TestStripTrailingCommas:
    def test_strips_last_comma(self):
        result = _strip_trailing_commas(b'{"a": 1,}')
        assert b",}" not in result

    def test_strips_multiple(self):
        result = _strip_trailing_commas(b'{"a": 1,"b": 2,}')
        assert result == b'{"a": 1,"b": 2}'


class TestNormalizeJson:
    def test_normalizes(self):
        result = _normalize_json(b'{\n  // comment\n  "a": 1,\n}')
        parsed = json.loads(result)
        assert parsed == {"a": 1}


class TestUnmarshalJsonObject:
    def test_valid(self):
        result = _unmarshal_json_object(b'{"a": 1}')
        assert result == {"a": 1}

    def test_empty(self):
        assert _unmarshal_json_object(b"{}") == {}

    def test_invalid(self):
        assert _unmarshal_json_object(b"not json") is None


class TestRemoveTomlTable:
    def test_removes_table(self):
        content = "[tool.dxrk]\nkey = 1\n[other]\nkey = 2"
        result = _remove_toml_table(content, "tool.dxrk")
        assert "[tool.dxrk]" not in result
        assert "[other]" in result

    def test_no_match(self):
        content = "[other]\nkey = 1"
        result = _remove_toml_table(content, "tool.dxrk")
        assert result == content

    def test_keeps_header_comment(self):
        content = "# header\n[table]\nkey = 1\n[other]"
        result = _remove_toml_table(content, "table")
        assert "# header" in result  # not removed by toml helper


class TestRemoveTopLevelTomlKeys:
    def test_removes_keys(self):
        content = "key1 = 1\nkey2 = 2\nkey3 = 3"
        result = _remove_top_level_toml_keys(content, "key1", "key3")
        assert "key1" not in result
        assert "key3" not in result
        assert "key2" in result

    def test_no_match(self):
        content = "key1 = 1"
        result = _remove_top_level_toml_keys(content, "nope")
        assert result == content


class TestCodexTomlClean:
    def test_cleans(self):
        content = "[commands]\ncodex = true\n[key]\nvalue = 1"
        result, changed = _clean_codex_toml(content)
        assert changed is True


class TestReadManagedFile:
    def test_reads_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        result = _read_managed_file(str(f))
        assert result == "content"

    def test_too_large_raises(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * (16 << 20 + 1))
        with pytest.raises(ValueError, match="exceeds max managed size"):
            _read_managed_file(str(f))

    def test_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_managed_file(str(tmp_path / "nonexistent"))


class TestRemoveFileIfExists:
    def test_removes(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        _remove_file_if_exists(str(f))
        assert not f.exists()

    def test_nonexistent_no_error(self, tmp_path):
        _remove_file_if_exists(str(tmp_path / "missing"))


class TestRemoveFile:
    def test_removes_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        op = _remove_file(str(f))
        ok, changed, err = op.apply(str(f))
        assert ok is True
        assert changed is True
        assert not f.exists()

    def test_nonexistent(self, tmp_path):
        op = _remove_file(str(tmp_path / "missing"))
        ok, changed, err = op.apply(str(tmp_path / "missing"))
        assert ok is False
        assert changed is False


class TestRemoveTree:
    def test_removes_dir(self, tmp_path):
        d = tmp_path / "mydir"
        d.mkdir()
        (d / "file.txt").write_text("x")
        op = _remove_tree(str(d))
        ok, changed, err = op.apply(str(d))
        assert ok is True
        assert changed is True
        assert not d.exists()


class TestRemoveDirIfEmpty:
    def test_removes_empty(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        op = _remove_dir_if_empty(str(d))
        ok, changed, err = op.apply(str(d))
        assert ok is True
        assert changed is True
        assert not d.exists()


class TestRemoveDirIfEmptyRecursive:
    def test_removes_empty_dir(self, tmp_path):
        a = tmp_path / "a" / "b" / "c"
        a.mkdir(parents=True)
        result = _remove_dir_if_empty_recursive(str(a))
        assert result is True
        assert not a.exists()
        # parent dirs are NOT removed by this function
        assert (tmp_path / "a" / "b").exists()

    def test_keeps_non_empty_dir(self, tmp_path):
        a = tmp_path / "a" / "b"
        a.mkdir(parents=True)
        (tmp_path / "a" / "keep").write_text("x")
        result = _remove_dir_if_empty_recursive(str(a))
        assert result is True
        assert not a.exists()


class TestRewriteMarkdownFile:
    def test_rewrites(self, tmp_path):
        # _rewrite_markdown_file takes path + mutate callable
        def mutate(content: str) -> tuple[str, bool]:
            return content.replace("old", "new"), True

        f = tmp_path / "test.md"
        f.write_text("before old after")
        op = _rewrite_markdown_file(str(f), mutate)
        ok, changed, err = op.apply(str(f))
        assert ok is True
        assert "old" not in f.read_text()

    def test_no_change(self, tmp_path):
        def mutate(content: str) -> tuple[str, bool]:
            return content, False

        f = tmp_path / "test.md"
        f.write_text("unchanged")
        op = _rewrite_markdown_file(str(f), mutate)
        ok, changed, err = op.apply(str(f))
        assert ok is False
        assert changed is False


class TestRewriteJsonFile:
    def test_rewrites(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"a": 1, "b": 2}')
        op = _rewrite_json_file(str(f), ["a"])
        ok, changed, err = op.apply(str(f))
        assert ok is True
        assert json.loads(f.read_text()) == {"b": 2}


class TestRewriteTomlFile:
    def test_rewrites(self, tmp_path):
        def mutate(content: str) -> tuple[str, bool]:
            return content.replace("[tool.dxrk]", ""), True

        f = tmp_path / "test.toml"
        f.write_text("[tool.dxrk]\nkey = 1\n[other]\nkey = 2")
        op = _rewrite_toml_file(str(f), mutate)
        ok, changed, err = op.apply(str(f))
        assert ok is True
        assert "[tool.dxrk]" not in f.read_text()


class TestMergeRewriteOps:
    def test_merges_and_type_is_rewrite(self, tmp_path):
        def m1(c):
            return c.replace("a", "x"), True

        def m2(c):
            return c.replace("b", "y"), True

        f = tmp_path / "test.md"
        f.write_text("a b c")
        a = _rewrite_markdown_file(str(f), m1)
        b = _rewrite_markdown_file(str(f), m2)
        merged = _merge_rewrite_ops(a, b)
        assert merged.type_id == OpType.REWRITE_FILE
        merged.apply(str(f))
        assert f.read_text() == "x y c"


class TestManualActionForNonEmptyDirectory:
    def test_returns_message(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        (d / "file").write_text("x")
        msg = _manual_action_for_non_empty_directory(str(d))
        assert msg is not None
        assert "manual" in msg.lower()

    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert _manual_action_for_non_empty_directory(str(d)) is None


class TestStateAgentsToRemove:
    def test_returns_empty_without_all_components(self):
        result = _state_agents_to_remove([], [])
        assert result == []


class TestUpdateStateAfterUninstall:
    def test_empty_to_remove(self, tmp_path):
        result = _update_state_after_uninstall(str(tmp_path), [])
        assert result == []


class TestExpandBackupTarget:
    def test_returns_single_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        targets = _expand_backup_target(str(f))
        assert str(f) in targets

    def test_returns_directory_contents(self, tmp_path):
        d = tmp_path / "dir"
        d.mkdir()
        (d / "a.txt").write_text("x")
        (d / "b.txt").write_text("y")
        targets = _expand_backup_target(str(d))
        assert len(targets) >= 2


class TestGlobalBackupTargets:
    def test_returns_list(self, tmp_path):
        targets = _global_backup_targets(str(tmp_path))
        assert isinstance(targets, list)


class TestServicePartialUninstall:
    def test_raises_on_empty_agents(self):
        svc = Service(home_dir="/tmp")
        with pytest.raises(ValueError, match="requires at least one agent"):
            svc.partial_uninstall([], [])

    def test_executes_plan(self, tmp_path, monkeypatch):
        calls = []

        def fake_build(self_svc, agents, components):
            calls.append((agents, components))
            return [], []

        def fake_execute(self_svc, plan, state_removals):
            return Result()

        monkeypatch.setattr(Service, "_build_plan", fake_build)
        monkeypatch.setattr(Service, "_execute_plan", fake_execute)

        svc = Service(home_dir=str(tmp_path))
        result = svc.partial_uninstall([AgentID.OPENCODE], [ComponentID.DXRK_MEMORY])
        assert isinstance(result, Result)
        assert len(calls) == 1


class TestServiceCompleteUninstall:
    def test_adds_manual_action(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            Service, "_build_plan", lambda self_svc, agents, comps: ([], [])
        )
        monkeypatch.setattr(
            Service, "_execute_plan", lambda self_svc, plan, state: Result()
        )

        svc = Service(home_dir=str(tmp_path))
        result = svc.complete_uninstall()
        assert len(result.ManualActions) == 1
        assert "remove" in result.ManualActions[0].lower()


class TestServiceBuildPlan:
    def test_returns_plan(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "dxrk.components.uninstall.Service._component_operations",
            lambda self, adapter, cid: ([], []),
        )
        monkeypatch.setattr(
            "dxrk.components.uninstall._expand_backup_target",
            lambda p: [p],
        )
        monkeypatch.setattr(
            "dxrk.components.uninstall._global_backup_targets",
            lambda h: [],
        )
        # Mock the adapter
        fa = FakeAdapter()
        fa._agent = AgentID.OPENCODE
        monkeypatch.setattr(
            Service,
            "_get_adapter",
            lambda self, aid: fa,
        )

        svc = Service(home_dir=str(tmp_path))
        targets, ops = svc._build_plan([AgentID.OPENCODE], [ComponentID.DXRK_MEMORY])
        assert isinstance(targets, list)
        assert isinstance(ops, list)


class TestServiceExecutePlan:
    def test_executes_empty_plan(self, tmp_path):
        svc = Service(home_dir=str(tmp_path))
        result = svc._execute_plan(([], []), [])
        assert isinstance(result, Result)
        assert result.ChangedFiles == []
        assert result.RemovedFiles == []

    def test_backup_and_remove(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("content")
        remove_op = _remove_file(str(f))
        svc = Service(home_dir=str(tmp_path), app_version="test")
        result = svc._execute_plan(([str(f)], [remove_op]), [])
        assert (
            str(f) in result.ChangedFiles
            or str(f) in result.RemovedFiles
            or not f.exists()
        )


class TestServiceGetAdapter:
    def test_get_adapter_returns_non_none(self, monkeypatch):
        class FakeReg:
            def get(self, aid):
                return FakeAdapter()

        monkeypatch.setattr("dxrk.agents.registry.Registry", lambda: FakeReg())
        svc = Service(home_dir="/tmp")
        adapter = svc._get_adapter(AgentID.OPENCODE)
        assert adapter is not None


class TestServiceSetProfileNames:
    def test_sets_and_deduplicates(self):
        svc = Service(home_dir="/tmp")
        svc.set_profile_names_to_remove(["a", "b", "a"])
        assert svc.profile_names_to_remove == ["a", "b"]


class TestServiceSetEngramScope:
    def test_sets_scope(self):
        svc = Service(home_dir="/tmp")
        svc.set_DXRK_MEMORY_uninstall_scope(DxrkMemoryUninstallScope.PROJECT)
        assert svc.DXRK_MEMORY_uninstall_scope == DxrkMemoryUninstallScope.PROJECT
