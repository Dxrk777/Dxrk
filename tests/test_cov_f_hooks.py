# SPDX-License-Identifier: MIT
"""Coverage F — gaps for dxrk/utils/hooks.py, dxrk/memory/hooks_cli.py, dxrk/memory/__init__.py."""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import dxrk.memory.hooks_cli as hc
from dxrk.memory import AgentMemory, MemoryEntry, MemoryType, top_by_importance
from dxrk.utils import hooks

_BG = hooks._background()


@pytest.fixture(autouse=True)
def _reset_hc_flag():
    hc._state_dir_initialized = False
    yield
    hc._state_dir_initialized = False


def _iso_hc(monkeypatch, tmp_path, *, palace=True):
    palace_root = tmp_path / "palace"
    state_dir = tmp_path / "hstate"
    if palace:
        palace_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hc, "PALACE_ROOT", palace_root)
    monkeypatch.setattr(hc, "STATE_DIR", state_dir)
    monkeypatch.setattr(hc, "_MINE_PID_DIR", state_dir / "mine_pids")
    hc._state_dir_initialized = False
    return palace_root, state_dir


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — type names / levels
# ═══════════════════════════════════════════════════════════════════════════


class TestHookTypeExtra:
    def test_hook_type_string_out_of_range(self):
        assert hooks.HookType.string(99) == "unknown"

    def test_hook_type_name_variants(self):
        assert hooks._hook_type_name(hooks.PreToolUse) == "pre_tool_use"
        assert hooks._hook_type_name(2) == "user_prompt_submit"
        assert hooks._hook_type_name(5) == "subagent_stop"
        assert hooks._hook_type_name(99) == "unknown"
        assert hooks._hook_type_name(-1) == "unknown"

    def test_log_level_string_out_of_range(self):
        assert hooks.LogLevel.string(99) == "unknown"
        assert hooks.LogLevelDebug.string() == "debug"
        assert hooks.LogLevelError.string() == "error"

    def test_hook_error_str(self):
        assert str(hooks.HookError("boom")) == "boom"


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — time / json helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeJsonHelpers:
    def test_go_time_fmt_naive_no_micro(self):
        assert hooks._go_time_fmt(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05Z"

    def test_go_time_fmt_micro(self):
        assert hooks._go_time_fmt(datetime(2026, 1, 2, 3, 4, 5, 123456)) == "2026-01-02T03:04:05.123456Z"
        assert hooks._go_time_fmt(datetime(2026, 1, 2, 3, 4, 5, 123000)) == "2026-01-02T03:04:05.123Z"

    def test_go_time_fmt_aware(self):
        aware = datetime(2026, 1, 2, 5, 4, 5, tzinfo=UTC)
        assert hooks._go_time_fmt(aware) == "2026-01-02T05:04:05Z"

    def test_go_time_parse(self):
        assert hooks._go_time_parse("2026-01-02T03:04:05Z") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert hooks._go_time_parse("2026-01-02T03:04:05+00:00") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    def test_td_ns_roundtrip(self):
        assert hooks._td_ns(timedelta(seconds=1)) == 1_000_000_000
        assert hooks._ns_td(1500) == timedelta(microseconds=1)
        assert hooks._ns_td(0) == timedelta(0)

    def test_raw_dump_load(self):
        assert hooks._raw_dump(b"hi") == "hi"
        assert hooks._raw_dump("s") == "s"
        assert hooks._raw_dump(None) is None
        assert hooks._raw_dump({"a": 1}) == {"a": 1}
        assert hooks._raw_load({"a": 1}) == {"a": 1}

    def test_odict(self):
        assert hooks._odict(True, "k", 1) == {"k": 1}
        assert hooks._odict(False, "k", 1) is None


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — dump / load
# ═══════════════════════════════════════════════════════════════════════════


class TestDumpLoad:
    def test_evt_dump_full(self):
        e = hooks.HookEvent(
            type=hooks.PostToolUse,
            tool_name="bash",
            tool_input=b"in",
            tool_output={"k": "v"},
            prompt="p",
            message="m",
            metadata={"a": "b"},
            timestamp=datetime(2026, 1, 2, 3, 4, 5),
            session_id="s1",
        )
        d = hooks._evt_dump(e)
        assert d["type"] == 1
        assert d["tool_name"] == "bash"
        assert d["tool_input"] == "in"
        assert d["tool_output"] == {"k": "v"}
        assert d["prompt"] == "p"
        assert d["message"] == "m"
        assert d["metadata"] == {"a": "b"}
        assert d["timestamp"] == "2026-01-02T03:04:05Z"
        assert d["session_id"] == "s1"

    def test_evt_dump_minimal(self):
        d = hooks._evt_dump(hooks.HookEvent())
        assert d == {"type": 0, "timestamp": d["timestamp"]}
        assert "tool_name" not in d

    def test_evt_load_full(self):
        e = hooks._evt_load(
            {
                "type": 2,
                "tool_name": "x",
                "tool_input": {"a": 1},
                "tool_output": [1],
                "prompt": "p",
                "message": "m",
                "metadata": {"k": "v"},
                "timestamp": "2026-01-02T03:04:05Z",
                "session_id": "s",
            }
        )
        assert e.type == hooks.UserPromptSubmit
        assert e.tool_name == "x"
        assert e.tool_input == {"a": 1}
        assert e.tool_output == [1]
        assert e.prompt == "p"
        assert e.message == "m"
        assert e.metadata == {"k": "v"}
        assert e.session_id == "s"

    def test_evt_load_minimal(self):
        e = hooks._evt_load({})
        assert e.type == hooks.PreToolUse
        assert isinstance(e.timestamp, datetime)

    def test_result_dump_full(self):
        r = hooks.HookResult(
            success=True,
            exit_code=2,
            stdout="o",
            stderr="e",
            error="err",
            duration=timedelta(seconds=2),
            modified_input=b"mi",
            skip_tool=True,
            abort_reason="ab",
            metadata={"k": "v"},
        )
        d = hooks._result_dump(r)
        assert d["success"] is True
        assert d["exit_code"] == 2
        assert d["stdout"] == "o"
        assert d["stderr"] == "e"
        assert d["error"] == "err"
        assert d["duration"] == 2_000_000_000
        assert d["modified_input"] == "mi"
        assert d["skip_tool"] is True
        assert d["abort_reason"] == "ab"
        assert d["metadata"] == {"k": "v"}

    def test_result_dump_minimal(self):
        d = hooks._result_dump(hooks.HookResult())
        assert d == {"success": False, "duration": 0}

    def test_result_load_full(self):
        r = hooks._result_load(
            {
                "success": True,
                "exit_code": 3,
                "stdout": "o",
                "stderr": "e",
                "error": "x",
                "duration": 1_000_000_000,
                "modified_input": {"a": 1},
                "skip_tool": True,
                "abort_reason": "no",
                "metadata": {"k": "v"},
            }
        )
        assert r.success is True
        assert r.exit_code == 3
        assert r.duration == timedelta(seconds=1)
        assert r.modified_input == {"a": 1}
        assert r.skip_tool is True
        assert r.abort_reason == "no"

    def test_result_load_minimal(self):
        r = hooks._result_load({})
        assert r.success is False
        assert r.duration == timedelta(0)

    def test_match_dump_load(self):
        m = hooks.HookMatch(
            tool_name="t",
            tool_names=["a"],
            path="p",
            paths=["x"],
            glob="g*",
            regex="r+",
            command="c",
            commands=["d"],
        )
        d = hooks._match_dump(m)
        assert d == {
            "tool_name": "t",
            "tool_names": ["a"],
            "path": "p",
            "paths": ["x"],
            "glob": "g*",
            "regex": "r+",
            "command": "c",
            "commands": ["d"],
        }
        assert hooks._match_dump(hooks.HookMatch()) == {}
        m2 = hooks._match_load(d)
        assert m2 == m
        assert hooks._match_load({}) == hooks.HookMatch()

    def test_cfg_dump_load(self):
        c = hooks.HookConfig(
            id="i",
            type=hooks.PostToolUse,
            match=hooks.HookMatch(tool_name="t"),
            command="cmd",
            args=["a"],
            env=["K=V"],
            timeout=timedelta(seconds=5),
            max_retries=2,
            retry_delay=timedelta(seconds=1),
            enabled=True,
            description="d",
            priority=3,
        )
        d = hooks._cfg_dump(c)
        assert d["timeout"] == 5_000_000_000
        assert d["retry_delay"] == 1_000_000_000
        assert d["args"] == ["a"]
        assert d["priority"] == 3
        c2 = hooks._cfg_load(d)
        assert c2 == c
        minimal = hooks._cfg_load({"id": "x", "command": "y"})
        assert minimal.args == [] and minimal.enabled is False
        assert hooks._cfg_dump(hooks.HookConfig(id="x", command="y"))["match"] == {}

    def test_file_dump_load_errors(self):
        cfg = hooks.HookConfigFile(version="1.0", hooks=[hooks.HookConfig(id="a", command="x")])
        assert hooks._file_load(hooks._file_dump(cfg)).hooks[0].id == "a"
        with pytest.raises(ValueError, match="JSON object"):
            hooks._file_load([])
        with pytest.raises(ValueError, match="JSON array"):
            hooks._file_load({"hooks": {}})
        with pytest.raises(ValueError, match="JSON object"):
            hooks._file_load({"hooks": [42]})
        assert hooks._file_load({"version": "2", "hooks": []}).version == "2"


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — Load/Save/Validate
# ═══════════════════════════════════════════════════════════════════════════


class TestLoadSaveExtra:
    def test_load_oserror(self, tmp_path, monkeypatch):
        target = tmp_path / "hooks_oserr.json"
        target.write_text("{}", encoding="utf-8")
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("hooks_oserr.json"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        cfg, err = hooks.LoadConfig(str(target))
        assert cfg is None
        assert err == hooks.ErrConfigNotFound

    def test_load_clamps_negative_retries(self, tmp_path):
        p = tmp_path / "h.json"
        p.write_text('{"version": "1.0", "hooks": [{"id": "n", "command": "x", "max_retries": -5}]}', encoding="utf-8")
        cfg, err = hooks.LoadConfig(str(p))
        assert err is None
        assert cfg.hooks[0].max_retries == 0
        assert cfg.hooks[0].timeout == timedelta(seconds=30)

    def test_load_bad_shapes(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("[1, 2]", encoding="utf-8")
        cfg, err = hooks.LoadConfig(str(p))
        assert cfg is None and err == hooks.ErrConfigParse
        p.write_text('{"version": "1"}', encoding="utf-8")
        cfg, err = hooks.LoadConfig(str(p))
        assert cfg is None and err == hooks.ErrConfigParse

    def test_save_dumps_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("nope")))
        cfg = hooks.HookConfigFile(version="1.0", hooks=[])
        assert hooks.SaveConfig(str(tmp_path / "x.json"), cfg) == hooks.ErrConfigParse

    def test_save_makedirs_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        cfg = hooks.HookConfigFile(version="1.0", hooks=[])
        err = hooks.SaveConfig(str(tmp_path / "x.json"), cfg)
        assert isinstance(err, hooks.HookError)

    def test_save_open_error(self, tmp_path, monkeypatch):
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("hooks_fail.json"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        cfg = hooks.HookConfigFile(version="1.0", hooks=[])
        err = hooks.SaveConfig(str(tmp_path / "hooks_fail.json"), cfg)
        assert isinstance(err, hooks.HookError)

    def test_save_creates_parents(self, tmp_path):
        p = tmp_path / "sub" / "deep" / "hooks.json"
        assert hooks.SaveConfig(str(p), hooks.DefaultConfig()) is None
        assert p.is_file()

    def test_validate_retry_delay_negative(self):
        cfg = hooks.HookConfigFile(hooks=[hooks.HookConfig(id="a", command="x", retry_delay=timedelta(seconds=-1))])
        assert hooks.ValidateConfig(cfg) == hooks.ErrConfigParse

    def test_merge_and_filters_empty(self):
        assert hooks.MergeConfigs(None).hooks == []
        cfg = hooks.HookConfigFile(hooks=[])
        assert hooks.FilterByType(cfg, hooks.Stop) == []
        assert hooks.FilterEnabled(cfg) == []


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — matcher / glob / filepath
# ═══════════════════════════════════════════════════════════════════════════


class TestMatcherExtra:
    def test_match_path_exact_and_paths(self):
        m = hooks.HookMatcher()
        assert m.MatchPath(hooks.HookMatch(path="a"), "b") is False
        assert m.MatchPath(hooks.HookMatch(path="a"), "a") is True
        assert m.MatchPath(hooks.HookMatch(paths=["a"]), "b") is False
        assert m.MatchPath(hooks.HookMatch(paths=["a"]), "a") is True

    def test_match_path_glob_regex_branches(self):
        m = hooks.HookMatcher()
        assert m.MatchPath(hooks.HookMatch(glob="*.go"), "x.py") is False
        assert m.MatchPath(hooks.HookMatch(regex="^a+$"), "b") is False
        assert m.MatchPath(hooks.HookMatch(regex="^a+$"), "aa") is True
        assert m.MatchPath(hooks.HookMatch(), "anything") is True

    def test_match_command_branches(self):
        m = hooks.HookMatcher()
        assert m.MatchCommand(hooks.HookMatch(command="a"), "b") is False
        assert m.MatchCommand(hooks.HookMatch(command="a"), "a") is True
        assert m.MatchCommand(hooks.HookMatch(commands=["a"]), "b") is False
        assert m.MatchCommand(hooks.HookMatch(commands=["a"]), "a") is True

    def test_match_glob_cached_and_bad(self):
        m = hooks.HookMatcher()
        assert m._match_glob("*.go", "a.go")[0] is True
        assert m._match_glob("*.go", "a.go")[0] is True  # cache hit
        ok, err = m._match_glob("[", "x")
        assert ok is False and isinstance(err, hooks.HookError)

    def test_match_regex_cached_and_bad(self):
        m = hooks.HookMatcher()
        assert m._match_regex("^a+$", "aa")[0] is True
        assert m._match_regex("^a+$", "aa")[0] is True  # cache hit
        ok, err = m._match_regex("(", "x")
        assert ok is False and isinstance(err, hooks.HookError)

    def test_clear_cache(self):
        m = hooks.HookMatcher()
        m._match_glob("*.go", "a.go")
        m._match_regex("^a$", "a")
        m.ClearCache()
        assert m._glob_cache == {} and m._regex_cache == {}


class TestGlobToRegex:
    @pytest.mark.parametrize(
        ("pat", "expected"),
        [
            ("*.go", "^.*\\.go$"),
            ("a?b", "^a.b$"),
            ("[ab]", "^[ab]$"),
            ("[a*]", "^[a*]$"),
            ("[a?]", "^[a?]$"),
            ("a+b", "^a\\+b$"),
            ("a.b", "^a\\.b$"),
            ("a(b)", "^a\\(b\\)$"),
            ("a^b$c", "^a\\^b\\$c$"),
            ("a{b}c", "^a\\{b\\}c$"),
            ("a|b", "^a\\|b$"),
            ("a\\*b", "^a\\*b$"),
            ("plain", "^plain$"),
        ],
    )
    def test_conversions(self, pat, expected):
        assert hooks._glob_to_regex(pat) == expected

    def test_trailing_backslash(self):
        assert hooks._glob_to_regex("a\\") == "^a\\$"

    def test_close_bracket_outside_class(self):
        assert hooks._glob_to_regex("a]b") == "^a]b$"


class TestFilepathMatch:
    @pytest.mark.parametrize(
        ("pat", "name", "expected"),
        [
            ("abc", "abc", True),
            ("abc", "abd", False),
            ("", "", True),
            ("", "x", False),
            ("*", "anything", True),
            ("*", "a/b", False),
            ("a*b", "axxb", True),
            ("a*b", "a/b", False),
            ("a*b", "ab", True),
            ("?", "x", True),
            ("?", "/", False),
            ("?", "", False),
            ("a?c", "abc", True),
            ("a?c", "a/c", False),
            ("\\a", "a", True),
            ("\\a", "b", False),
            ("\\", "x", False),
            ("\\/", "/", False),
            ("[abc]", "b", True),
            ("[abc]", "d", False),
            ("[abc]", "/", False),
            ("[^abc]", "d", True),
            ("[^abc]", "a", False),
            ("[a-c]", "b", True),
            ("[a-c]", "z", False),
            ("[", "x", False),
            ("a", "", False),
        ],
    )
    def test_cases(self, pat, name, expected):
        assert hooks._filepath_match(pat, name) is expected


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — registry / matches_hook / watcher
# ═══════════════════════════════════════════════════════════════════════════


class TestRegistryExtra:
    def test_register_applies_defaults(self):
        r = hooks.HookRegistry()
        assert r.Register(hooks.HookConfig(id="n", command="x", max_retries=-2)) is None
        cfg, ok = r.Get("n")
        assert ok and cfg.timeout == timedelta(seconds=30)
        assert cfg.max_retries == 0
        assert cfg.retry_delay == timedelta(seconds=1)

    def test_register_keeps_explicit_values(self):
        r = hooks.HookRegistry()
        cfg = hooks.HookConfig(
            id="full",
            command="x",
            timeout=timedelta(seconds=1),
            max_retries=0,
            retry_delay=timedelta(seconds=2),
            enabled=True,
        )
        assert r.Register(cfg) is None
        got, ok = r.Get("full")
        assert ok and got.timeout == timedelta(seconds=1)
        assert got.retry_delay == timedelta(seconds=2)

    def test_get_by_type_empty(self):
        assert hooks.HookRegistry().GetByType(hooks.Stop) == []

    def test_match_closed(self):
        r = hooks.HookRegistry()
        r.Register(hooks.HookConfig(id="a", command="x", enabled=True))
        r.Close()
        assert r.Match(hooks.HookEvent(tool_name="x")) == []

    def test_match_open_paths(self):
        r = hooks.HookRegistry()
        r.Register(hooks.HookConfig(id="yes", command="x", match=hooks.HookMatch(tool_name="bash"), enabled=True))
        r.Register(hooks.HookConfig(id="no", command="x", match=hooks.HookMatch(tool_name="sh"), enabled=True))
        r.Register(hooks.HookConfig(id="off", command="x", match=hooks.HookMatch(tool_name="bash"), enabled=False))
        r.Register(hooks.HookConfig(id="orphan", command="x", enabled=True))
        del r._hooks["orphan"]
        got = r.Match(hooks.HookEvent(tool_name="bash"))
        assert [c.id for c in got] == ["yes"]

    def test_watch_cleanup_on_cancel(self):
        r = hooks.HookRegistry()
        ctx, cancel = hooks._with_cancel(_BG)
        w = r.Watch(ctx)
        cancel()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with r._mu:
                gone = w not in r._watchers
            if gone and w._closed:
                break
            time.sleep(0.05)
        assert w._closed is True
        with r._mu:
            assert w not in r._watchers

    def test_watch_cleanup_skips_others(self):
        r = hooks.HookRegistry()
        w1 = r.Watch(_BG)
        ctx, cancel = hooks._with_cancel(_BG)
        w2 = r.Watch(ctx)
        cancel()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with r._mu:
                gone = w2 not in r._watchers
            if gone and w2._closed:
                break
            time.sleep(0.05)
        assert w2._closed is True
        with r._mu:
            assert w1 in r._watchers and w2 not in r._watchers
        r.Close()

    def test_watch_cleanup_missing_watcher(self):
        r = hooks.HookRegistry()
        ctx, cancel = hooks._with_cancel(_BG)
        w = r.Watch(ctx)
        with r._mu:
            r._watchers.remove(w)
        cancel()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if w._closed:
                break
            time.sleep(0.05)
        assert w._closed is True
        r.Close()

    def test_close_no_watchers(self):
        r = hooks.HookRegistry()
        r.Close()
        r.Close()
        assert r.Match(hooks.HookEvent()) == []

    def test_remove_from_index_missing(self):
        r = hooks.HookRegistry()
        r._remove_from_type_index(hooks.PreToolUse, "ghost")
        r._notify_watchers()

    def test_unregister_removes_type_index(self):
        r = hooks.HookRegistry()
        r.Register(hooks.HookConfig(id="a", command="x", type=hooks.Stop))
        assert r.GetByType(hooks.Stop) == ["a"]
        assert r.Unregister("a") is True
        assert r.GetByType(hooks.Stop) == []

    def test_watcher_notify_after_close(self):
        w = hooks._Watcher()
        w._close()
        w._notify()
        assert w.recv(timeout=0.05) is False

    def test_watcher_recv_notified(self):
        w = hooks._Watcher()
        w._notify()
        assert w.recv(timeout=0.5) is True


class TestMatchesHookExtra:
    def _cfg(self, **kw):
        base = dict(id="c", command="cmd")
        base.update(kw)
        return hooks.HookConfig(**base)

    def test_each_mismatch(self):
        ev = hooks.HookEvent(tool_name="bash")
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(tool_name="sh")), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(tool_names=["sh"])), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(glob="*.zzz")), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(regex="^z+$")), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(regex="(")), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(command="sh")), ev) is False
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch(commands=["sh"])), ev) is False

    def test_empty_and_full_match(self):
        ev = hooks.HookEvent(tool_name="bash")
        assert hooks._matches_hook(self._cfg(match=hooks.HookMatch()), ev) is True
        full = hooks.HookMatch(
            tool_name="bash", tool_names=["bash"], glob="bash*", regex="^b", command="bash", commands=["bash"]
        )
        assert hooks._matches_hook(self._cfg(match=full), ev) is True


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — circuit breaker / context
# ═══════════════════════════════════════════════════════════════════════════


class TestCircuitBreakerExtra:
    def test_default_thresholds(self):
        cb = hooks.NewCircuitBreaker(0, 0, timedelta(0))
        assert cb._failure_threshold == 5
        assert cb._success_threshold == 2
        assert cb._timeout == timedelta(seconds=30)

    def test_half_open_failure_reopens(self):
        cb = hooks.NewCircuitBreaker(1, 2, timedelta(milliseconds=50))
        assert cb.Execute(_BG, lambda c: "boom") == "boom"
        assert cb.State() == hooks.CircuitOpen
        time.sleep(0.08)
        assert cb.Execute(_BG, lambda c: "again") == "again"
        assert cb.State() == hooks.CircuitOpen

    def test_closed_success_counts(self):
        cb = hooks.NewCircuitBreaker(5, 2, timedelta(seconds=30))
        assert cb.Execute(_BG, lambda c: None) is None
        assert cb.State() == hooks.CircuitClosed
        assert cb._successes == 1

    def test_open_rejects_immediately(self):
        cb = hooks.NewCircuitBreaker(1, 1, timedelta(seconds=30))
        assert cb.Execute(_BG, lambda c: "boom") == "boom"
        assert cb.State() == hooks.CircuitOpen
        assert cb.Execute(_BG, lambda c: None) == hooks.ErrCircuitOpen
        assert cb.State() == hooks.CircuitOpen

    def test_reset_clears_counts(self):
        cb = hooks.NewCircuitBreaker(1, 1, timedelta(seconds=30))
        cb.Execute(_BG, lambda c: "boom")
        assert cb.State() == hooks.CircuitOpen
        cb.Reset()
        assert cb.State() == hooks.CircuitClosed
        assert cb.Execute(_BG, lambda c: None) is None
        cb.Reset()
        assert cb.State() == hooks.CircuitClosed

    def test_half_open_allows_and_recovers(self):
        cb = hooks.NewCircuitBreaker(1, 1, timedelta(milliseconds=50))
        cb.Execute(_BG, lambda c: "x")
        time.sleep(0.08)
        assert cb.Execute(_BG, lambda c: None) is None
        assert cb.State() == hooks.CircuitClosed
        assert cb._failures == 0


class TestContextExtra:
    def test_background(self):
        ctx = hooks._background()
        assert ctx.err() is None
        assert ctx.remaining() is None

    def test_cancel(self):
        ctx, cancel = hooks._with_cancel(_BG)
        assert ctx.err() is None
        cancel()
        assert ctx.err() == hooks._CTX_CANCELED

    def test_parent_propagation(self):
        parent, cancel = hooks._with_cancel(_BG)
        child, _ = hooks._with_cancel(parent)
        cancel()
        assert child.err() == hooks._CTX_CANCELED

    def test_deadline_exceeded(self):
        ctx = hooks._Context(deadline=time.monotonic() - 1.0)
        assert ctx.err() == hooks._CTX_DEADLINE
        assert ctx.remaining() == 0.0

    def test_with_timeout_min_parent(self):
        parent, _ = hooks._with_timeout(_BG, timedelta(milliseconds=50))
        child, _ = hooks._with_timeout(parent, timedelta(seconds=10))
        assert child.remaining() is not None and child.remaining() <= 0.06

    def test_with_timeout_child(self):
        child, cancel = hooks._with_timeout(_BG, timedelta(seconds=5))
        assert child.remaining() is not None and 0.0 < child.remaining() <= 5.0
        cancel()
        assert child.err() == hooks._CTX_CANCELED

    def test_set_idempotent_after_deadline(self):
        ctx = hooks._Context(deadline=time.monotonic() + 60)
        ctx._set("x")
        assert ctx.err() == "x"
        ctx._set("y")
        assert ctx.err() == "x"


class TestExecEnv:
    def test_add_and_remove(self, monkeypatch):
        monkeypatch.setenv("COVF_REMOVE_ME", "1")
        cfg = hooks.HookConfig(command="x", env=["COVF_ADD=2", "COVF_REMOVE_ME"])
        env = hooks._exec_env(cfg)
        assert env["COVF_ADD"] == "2"
        assert "COVF_REMOVE_ME" not in env

    def test_value_with_equals(self):
        cfg = hooks.HookConfig(command="x", env=["K=a=b"])
        assert hooks._exec_env(cfg)["K"] == "a=b"

    def test_not_found_msg(self):
        assert "not found" in str(hooks._exec_not_found("zzz"))


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — executor
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutorOptions:
    def test_with_options(self):
        cb = hooks.NewCircuitBreaker(1, 1, timedelta(seconds=5))
        ex = hooks.NewHookExecutor(
            hooks.WithExecutorTimeout(timedelta(seconds=7)),
            hooks.WithExecutorRetries(4),
            hooks.WithExecutorRetryDelay(timedelta(milliseconds=9)),
            hooks.WithCircuitBreaker(cb),
        )
        assert ex._timeout == timedelta(seconds=7)
        assert ex._max_retries == 4
        assert ex._retry_delay == timedelta(milliseconds=9)
        assert ex._circuit_breaker is cb

    def test_defaults(self):
        ex = hooks.NewHookExecutor()
        assert ex._timeout == timedelta(seconds=30)
        assert ex._max_retries == 3


class TestExecuteOnceExtra:
    def test_remaining_caps_timeout(self):
        ex = hooks.NewHookExecutor()
        ctx, _ = hooks._with_timeout(_BG, timedelta(seconds=5))
        res = ex.Execute(ctx, hooks.HookConfig(command="printf", args=["hi"]), hooks.HookEvent())
        assert res.success is True and res.stdout == "hi"

    def test_timeout_expired_without_ctx_err(self, monkeypatch):
        def _boom(cmd, **k):
            raise subprocess.TimeoutExpired(cmd, 1, output=b"o", stderr=b"e")

        monkeypatch.setattr(subprocess, "run", _boom)
        ex = hooks.NewHookExecutor(hooks.WithExecutorRetries(0))
        res = ex.Execute(_BG, hooks.HookConfig(command="x"), hooks.HookEvent())
        assert res.success is False
        assert res.error == hooks._CTX_DEADLINE
        assert res.stdout == "o" and res.stderr == "e" and res.exit_code == -1

    def test_nonzero_with_deadline_ctx(self):
        class _StubCtx:
            def err(self):
                return hooks._CTX_DEADLINE

            def remaining(self):
                return None

        ex = hooks.NewHookExecutor()
        result = hooks.HookResult()
        err = ex._execute_once(
            _StubCtx(), hooks.HookConfig(command="sh", args=["-c", "exit 3"]), hooks.HookEvent(), result, 0
        )
        assert err == hooks.ErrExecutionTimeout
        assert result.exit_code == 3

    def test_precanceled_ctx_with_retries(self):
        ex = hooks.NewHookExecutor(
            hooks.WithExecutorRetries(2), hooks.WithExecutorRetryDelay(timedelta(milliseconds=1))
        )
        ctx, cancel = hooks._with_cancel(_BG)
        cancel()
        res = ex.Execute(ctx, hooks.HookConfig(command="sh", args=["-c", "exit 1"]), hooks.HookEvent())
        assert res.success is False
        assert res.error == hooks._CTX_CANCELED

    def test_breaks_on_execution_timeout(self, monkeypatch):
        calls = []
        real = hooks.HookExecutor._execute_once

        def _spy(self, ctx, cfg, ev, result, attempt):
            calls.append(attempt)
            return hooks.ErrExecutionTimeout

        monkeypatch.setattr(hooks.HookExecutor, "_execute_once", _spy)
        ex = hooks.NewHookExecutor(hooks.WithExecutorRetries(3))
        res = ex.Execute(_BG, hooks.HookConfig(command="x"), hooks.HookEvent())
        assert res.error == "hooks: execution timeout"
        assert calls == [0]
        assert real is not None

    def test_abort_breaks_retry(self, monkeypatch):
        calls = []

        def _spy(self, ctx, cfg, ev, result, attempt):
            calls.append(attempt)
            return hooks.ErrHookAborted

        monkeypatch.setattr(hooks.HookExecutor, "_execute_once", _spy)
        ex = hooks.NewHookExecutor(hooks.WithExecutorRetries(3))
        res = ex.Execute(_BG, hooks.HookConfig(command="x"), hooks.HookEvent())
        assert res.error == "hooks: hook execution aborted"
        assert calls == [0]


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — queue extras
# ═══════════════════════════════════════════════════════════════════════════


class TestQueueExtra:
    def test_start_when_closed(self):
        q = hooks.NewHookQueue()
        q.Stop(_BG)
        q.Start()
        assert q._worker_threads == []

    def test_stop_twice(self):
        q = hooks.NewHookQueue()
        assert q.Stop(_BG) is None
        assert q.Stop(_BG) is None

    def test_stop_deadline_exceeded(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1))
        q.Start()
        try:
            ctx, _ = hooks._with_timeout(_BG, timedelta(0))
            err = q.Stop(ctx)
            assert err == hooks._CTX_DEADLINE
        finally:
            q.Stop(_BG)

    def test_submit_precanceled(self):
        q = hooks.NewHookQueue()
        ctx, cancel = hooks._with_cancel(_BG)
        cancel()
        res, err = q.Submit(ctx, hooks.HookEvent(), hooks.HookConfig(command="printf"))
        assert err == hooks._CTX_CANCELED
        assert res == hooks.HookResult()

    def test_submit_cancel_during_wait(self, monkeypatch):
        q = hooks.NewHookQueue()
        caps = {}
        real_wc = hooks._with_cancel

        def _spy(parent):
            c, cancel = real_wc(parent)
            caps["cancel"] = cancel
            return c, cancel

        monkeypatch.setattr(hooks, "_with_cancel", _spy)
        t = threading.Timer(0.2, lambda: caps["cancel"]())
        t.start()
        try:
            res, err = q.Submit(_BG, hooks.HookEvent(), hooks.HookConfig(command="printf", args=["x"]))
        finally:
            t.join()
        assert err == hooks._CTX_CANCELED
        assert res.success is False

    def test_submit_async_full(self):
        q = hooks.NewHookQueue(hooks.WithQueueBuffer(1))
        q._tasks.put_nowait("filler")
        err = q.SubmitAsync(hooks.HookEvent(), hooks.HookConfig(command="printf"))
        assert err == hooks.ErrQueueFull

    def test_queue_buffer_nonpositive_keeps_default(self):
        q = hooks.NewHookQueue(hooks.WithQueueBuffer(0))
        assert q._tasks.maxsize == 100
        assert q.Stats().queue_cap == 100

    def test_queue_options(self):
        ex = hooks.NewHookExecutor()
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(3), hooks.WithQueueExecutor(ex))
        assert q._workers == 3
        assert q._executor is ex
        assert q.IsRunning() is True

    def test_worker_skips_canceled_task(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1))
        ctx, cancel = hooks._with_cancel(_BG)
        cancel()
        bad = hooks.HookTask(
            event=hooks.HookEvent(),
            config=hooks.HookConfig(command="printf", args=["x"]),
            result=queue.Queue(maxsize=1),
            context=ctx,
            cancel=cancel,
        )
        q._tasks.put_nowait(bad)
        q.Start()
        try:
            res, err = q.Submit(_BG, hooks.HookEvent(), hooks.HookConfig(command="printf", args=["y"]))
            assert err is None and res.success and res.stdout == "y"
        finally:
            q.Stop(_BG)

    def test_worker_result_full_then_cancel(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1))
        q.Start()
        try:
            ctx, cancel = hooks._with_cancel(_BG)
            rch = queue.Queue(maxsize=1)
            rch.put_nowait(hooks.HookResult(success=True))
            task = hooks.HookTask(
                event=hooks.HookEvent(),
                config=hooks.HookConfig(command="printf", args=["z"]),
                result=rch,
                context=ctx,
                cancel=cancel,
            )
            q._tasks.put_nowait(task)
            t = threading.Timer(0.3, cancel)
            t.start()
            t.join()
            time.sleep(0.2)
        finally:
            q.Stop(_BG)

    def test_stats_fields(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1))
        q.Start()
        try:
            res, err = q.Submit(_BG, hooks.HookEvent(), hooks.HookConfig(command="printf", args=["s"]))
            assert err is None and res.success
            st = q.Stats()
            assert st.processed == 1 and st.failed == 0
            assert st.workers == 1 and st.queue_cap == 100
            assert st.uptime >= timedelta(0)
        finally:
            q.Stop(_BG)


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/utils/hooks.py — logger extras
# ═══════════════════════════════════════════════════════════════════════════


class TestLoggerExtra:
    def test_discard_writer(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(None, hooks.LogLevelDebug)
        logger.Log(hooks.HookLogEntry(level=hooks.LogLevelDebug, hook_id="d", result=hooks.HookResult()))
        assert out.getvalue() == ""
        assert len(logger.RecentEntries(10)) == 1
        assert hooks._DiscardWriter().write("abc") == 3

    def test_entry_dump_with_error_and_meta(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        logger.Log(
            hooks.HookLogEntry(
                level=hooks.LogLevelError,
                hook_id="e",
                result=hooks.HookResult(success=False),
                error="boom",
                metadata={"k": "v"},
            )
        )
        data = json.loads(out.getvalue().strip())
        assert data["error"] == "boom"
        assert data["metadata"] == {"k": "v"}

    def test_max_entries_trim(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        logger._max_entries = 2
        for i in range(3):
            logger.Log(hooks.HookLogEntry(level=hooks.LogLevelDebug, hook_id=f"h{i}", result=hooks.HookResult()))
        assert [e.hook_id for e in logger.RecentEntries(10)] == ["h1", "h2"]

    def test_write_entry_fallback(self, monkeypatch):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        monkeypatch.setattr(json, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("nope")))
        logger.Log(hooks.HookLogEntry(level=hooks.LogLevelDebug, hook_id="f", result=hooks.HookResult()))
        assert out.getvalue().strip() == "{}"

    def test_metrics_same_hook_twice(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        for ok in (True, False):
            logger.Log(
                hooks.HookLogEntry(
                    level=hooks.LogLevelDebug,
                    hook_id="same",
                    hook_type=hooks.PreToolUse,
                    result=hooks.HookResult(success=ok),
                    duration=timedelta(milliseconds=10),
                )
            )
        m = logger.Metrics()
        assert m.by_hook["same"].count == 2
        assert m.by_hook["same"].success == 1
        assert m.by_hook["same"].failure == 1
        assert m.by_type[hooks.PreToolUse].count == 2
        assert m.by_type[hooks.PreToolUse].success == 1

    def test_recent_entries_bounds(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        logger.Log(hooks.HookLogEntry(level=hooks.LogLevelDebug, hook_id="a", result=hooks.HookResult()))
        assert len(logger.RecentEntries(0)) == 1
        assert len(logger.RecentEntries(99)) == 1
        assert logger.RecentEntries(-3) == logger.RecentEntries(1)

    def test_log_hook_execution_error_field(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        logger.LogHookExecution(
            _BG, hooks.HookConfig(id="lh"), hooks.HookEvent(), hooks.HookResult(success=False, error="bad"), 2
        )
        entry = logger.RecentEntries(1)[0]
        assert entry.error == "bad"
        assert entry.attempt == 2


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/memory/hooks_cli.py — small helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestDetachedPopen:
    def test_posix(self, monkeypatch):
        monkeypatch.setattr(os, "name", "posix")
        kw = hc._detached_popen_kwargs()
        assert kw["start_new_session"] is True
        assert kw["stdin"] is subprocess.DEVNULL

    def test_nt_no_flags(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        kw = hc._detached_popen_kwargs()
        assert "start_new_session" not in kw
        assert kw["stdin"] is subprocess.DEVNULL

    def test_nt_with_flags(self, monkeypatch):
        monkeypatch.setattr(os, "name", "nt")
        monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 1, raising=False)
        monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 2, raising=False)
        # en Windows real existe un tercer flag (CREATE_BREAKAWAY_FROM_JOB):
        # fijarlo tambien para un resultado determinista en todas las plataformas
        monkeypatch.setattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 4, raising=False)
        kw = hc._detached_popen_kwargs()
        assert kw["creationflags"] == 7


class TestDxrkPython:
    def test_env_valid(self, tmp_path, monkeypatch):
        exe = tmp_path / "mypython"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        monkeypatch.setenv("DXRK_PYTHON", str(exe))
        assert hc._dxrk_python() == str(exe)

    def test_env_invalid_falls_through(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DXRK_PYTHON", str(tmp_path / "nope"))
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        assert hc._dxrk_python() == sys.executable

    def test_venv_bin(self, monkeypatch):
        monkeypatch.delenv("DXRK_PYTHON", raising=False)
        monkeypatch.setattr(Path, "is_file", lambda self: True)
        assert hc._dxrk_python() == str(Path(hc.__file__).resolve().parents[3] / "bin" / "python")

    def test_project_venv(self, monkeypatch):
        monkeypatch.delenv("DXRK_PYTHON", raising=False)
        # sufijo con separadores de la plataforma (en Windows str(Path) usa \)
        venv_rel = os.path.join("dxrk", "venv", "bin", "python")

        def _fake(self):
            return str(self).endswith(venv_rel)

        monkeypatch.setattr(Path, "is_file", _fake)
        want = Path(hc.__file__).resolve().parents[1] / "venv" / "bin" / "python"
        assert hc._dxrk_python() == str(want)

    def test_fallback(self, monkeypatch):
        monkeypatch.delenv("DXRK_PYTHON", raising=False)
        monkeypatch.setattr(Path, "is_file", lambda self: False)
        assert hc._dxrk_python() == sys.executable


class TestSanitizeValidate:
    def test_sanitize(self):
        assert hc._sanitize_session_id("abc-123_foo!") == "abc-123_foo"
        assert hc._sanitize_session_id("!!!") == "unknown"
        assert hc._sanitize_session_id("") == "unknown"

    def test_validate(self, tmp_path):
        assert hc._validate_transcript_path("") is None
        good = tmp_path / "a.jsonl"
        good.write_text("x")
        assert hc._validate_transcript_path(str(good)) is not None
        bad = tmp_path / "a.txt"
        bad.write_text("x")
        assert hc._validate_transcript_path(str(bad)) is None
        assert hc._validate_transcript_path("/tmp/../x.jsonl") is None

    def test_parse_harness_unknown(self):
        with pytest.raises(SystemExit):
            hc._parse_harness_input({}, "nope")


class TestCountHuman:
    def _write(self, path, lines):
        with open(path, "w", encoding="utf-8") as f:
            for item in lines:
                f.write(item + "\n" if isinstance(item, str) else json.dumps(item) + "\n")

    def test_branches(self, tmp_path):
        tr = tmp_path / "c.jsonl"
        self._write(
            tr,
            [
                {"message": {"role": "user", "content": "hello"}},
                {"message": {"role": "user", "content": [{"text": "hi"}, "oops", 42]}},
                {"message": {"role": "user", "content": 123}},
                {"message": {"role": "user", "content": "<command-message>x</command-message>"}},
                {"message": {"role": "user", "content": [{"text": "<command-message>y</command-message>"}]}},
                {"message": {"role": "assistant", "content": "hi"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "hey"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "<command-message>no"}},
                {"type": "event_msg", "payload": {"type": "other", "message": "hey"}},
                {"type": "event_msg", "payload": "notadict"},
                {"type": "event_msg", "payload": {"type": "user_message", "message": 123}},
                {"unrelated": True},
                "not json",
            ],
        )
        assert hc._count_human_messages(str(tr)) == 4
        assert hc._count_human_messages("") == 0
        assert hc._count_human_messages(str(tmp_path / "missing.jsonl")) == 0

    def test_rejected_logs_warning(self, tmp_path, monkeypatch):
        logs = []
        monkeypatch.setattr(hc, "_log", logs.append)
        assert hc._count_human_messages("/tmp/x.txt") == 0
        assert any("rejected" in m for m in logs)

    def test_open_oserror(self, tmp_path, monkeypatch):
        tr = tmp_path / "o.jsonl"
        tr.write_text("x\n")
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("o.jsonl"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        assert hc._count_human_messages(str(tr)) == 0


class TestHcLog:
    def test_no_palace_noop(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=False)
        hc._log("hello")
        assert not (tmp_path / "hstate").exists()

    def test_write_and_reuse(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        hc._log("first")
        hc._log("second")
        text = (tmp_path / "hstate" / "hook.log").read_text(encoding="utf-8")
        assert "first" in text and "second" in text

    def test_mkdir_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        hc._log("x")

    def test_chmod_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        monkeypatch.setattr(Path, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        hc._log("x")
        assert (tmp_path / "hstate" / "hook.log").exists()

    def test_write_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("hook.log"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        hc._log("x")


class TestHcOutput:
    def test_normal(self):
        assert hc._output({"a": 1}) is None

    def test_interrupted_retry(self, monkeypatch):
        real_write = os.write
        state = {"n": 0}

        def _fake(fd, data):
            if state["n"] == 0:
                state["n"] += 1
                raise InterruptedError("again")
            return real_write(fd, data)

        monkeypatch.setattr(os, "write", _fake)
        hc._output({"ok": True})

    def test_oserror_fallback(self, monkeypatch):
        buf = io.BytesIO()
        monkeypatch.setattr(os, "write", lambda fd, data: (_ for _ in ()).throw(OSError("ro")))
        monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=buf))
        hc._output({"k": "v"})
        assert json.loads(buf.getvalue().decode("utf-8")) == {"k": "v"}


class TestMineTargets:
    def test_empty(self, monkeypatch):
        monkeypatch.delenv("DXRK_PROJECT_DIR", raising=False)
        assert hc._get_mine_targets() == []

    def test_missing_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DXRK_PROJECT_DIR", str(tmp_path / "nope"))
        assert hc._get_mine_targets() == []

    def test_file_not_dir(self, tmp_path, monkeypatch):
        f = tmp_path / "f.txt"
        f.write_text("x")
        monkeypatch.setenv("DXRK_PROJECT_DIR", str(f))
        assert hc._get_mine_targets() == []

    def test_valid(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DXRK_PROJECT_DIR", str(tmp_path))
        assert hc._get_mine_targets() == [(str(tmp_path.resolve()), "default")]


class TestMineTimeout:
    def test_variants(self, monkeypatch):
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "not-a-number")
        assert hc._mine_slot_timeout_secs() == 0.0
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "1.5")
        assert hc._mine_slot_timeout_secs() == 5400.0
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "-2")
        assert hc._mine_slot_timeout_secs() == 0.0
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "0")
        assert hc._mine_slot_timeout_secs() == 0.0
        monkeypatch.delenv(hc._MINE_TIMEOUT_HOURS_ENV, raising=False)
        assert hc._mine_slot_timeout_secs() == 7200.0


class TestPidFile:
    def test_deterministic(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        cmd = [sys.executable, "-m", "dxrk.memory", "mine", "/tmp/p", "--wing", "default"]
        assert hc._pid_file_for_cmd(cmd) == hc._pid_file_for_cmd(cmd)
        other = [sys.executable, "-m", "dxrk.memory", "mine", "/other", "--wing", "x"]
        assert hc._pid_file_for_cmd(other) != hc._pid_file_for_cmd(cmd)
        assert hc._pid_file_for_cmd([sys.executable, "-c", "print(1)"]).name.startswith("mine_")


class TestPidAlive:
    def test_self_and_dead(self):
        assert hc._pid_alive(os.getpid()) is True
        assert hc._pid_alive(999999) is False

    def test_value_error(self, monkeypatch):
        monkeypatch.setattr(os, "kill", lambda pid, sig: (_ for _ in ()).throw(ValueError("bad")))
        assert hc._pid_alive(123) is False

    def test_win32_branches(self, monkeypatch):
        import ctypes as _ct

        kernel = mock.MagicMock()
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(_ct, "windll", SimpleNamespace(kernel32=kernel), raising=False)
        kernel.OpenProcess.return_value = 0
        assert hc._pid_alive(111) is False
        kernel.OpenProcess.return_value = 99
        kernel.GetExitCodeProcess.return_value = False
        assert hc._pid_alive(111) is False

        def _exited(handle, pref):
            pref._obj.value = 1
            return True

        kernel.GetExitCodeProcess.side_effect = _exited
        assert hc._pid_alive(111) is False

        def _active(handle, pref):
            pref._obj.value = 259
            return True

        kernel.GetExitCodeProcess.side_effect = _active
        assert hc._pid_alive(111) is True


class TestMineAlreadyRunning:
    def _cmd(self):
        return [sys.executable, "-m", "dxrk.memory", "mine", "/tmp/proj", "--wing", "default"]

    def test_no_file(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        assert hc._mine_already_running(self._cmd()) is False

    def test_empty_and_corrupt(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is False
        pf.write_text("not-a-pid ???", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is False
        pf.write_text("999999 0", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is False

    def test_alive_no_timeout(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "0")
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is True

    def test_timeout_recent_and_expired(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "2")
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is True
        pf.write_text(f"{os.getpid()} 1", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is False
        pf.write_text(f"{os.getpid()} bogus", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is False

    def test_mtime_fallback(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "2")
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"{os.getpid()}", encoding="utf-8")
        assert hc._mine_already_running(self._cmd()) is True
        old = time.time() - 10000
        os.utime(pf, (old, old))
        assert hc._mine_already_running(self._cmd()) is False

    def test_stat_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        monkeypatch.setenv(hc._MINE_TIMEOUT_HOURS_ENV, "2")
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(f"{os.getpid()}", encoding="utf-8")
        monkeypatch.setattr(Path, "stat", lambda self: (_ for _ in ()).throw(OSError("ro")))
        assert hc._mine_already_running(self._cmd()) is True


class TestCreateMineSlot:
    def test_success(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._MINE_PID_DIR / "mine_x.pid"
        pf.parent.mkdir(parents=True, exist_ok=True)
        out = hc._create_mine_slot_with_placeholder(pf)
        assert out == pf
        assert pf.read_text(encoding="utf-8").split()[0].isdigit()

    def test_fdopen_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._MINE_PID_DIR / "mine_y.pid"
        pf.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            hc._create_mine_slot_with_placeholder(pf)
        assert not pf.exists()

    def test_fdopen_oserror_close_and_unlink_fail(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._MINE_PID_DIR / "mine_z.pid"
        pf.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError("busy")))
        monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            hc._create_mine_slot_with_placeholder(pf)


class TestClaimMineSlot:
    def _cmd(self):
        return [sys.executable, "-m", "dxrk.memory", "mine", "/tmp/cproj", "--wing", "default"]

    def test_fresh_and_busy(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        p1 = hc._claim_mine_slot(self._cmd())
        assert p1 is not None and p1.exists()
        assert hc._claim_mine_slot(self._cmd()) is None
        assert hc._mine_already_running(self._cmd()) is True

    def test_dead_reclaimed(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("999999 0", encoding="utf-8")
        p = hc._claim_mine_slot(self._cmd())
        assert p is not None and p.exists()

    def test_unlink_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("999999 0", encoding="utf-8")
        monkeypatch.setattr(hc, "_mine_already_running", lambda cmd: False)
        monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        assert hc._claim_mine_slot(self._cmd()) is None

    def test_unlink_gone_then_success(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("999999 0", encoding="utf-8")
        monkeypatch.setattr(hc, "_mine_already_running", lambda cmd: False)
        real_unlink = Path.unlink

        def _sneaky(self, *a, **k):
            if self == pf:
                try:
                    real_unlink(self)
                except OSError:
                    pass
                raise FileNotFoundError("gone")
            return real_unlink(self, *a, **k)

        monkeypatch.setattr(Path, "unlink", _sneaky)
        p = hc._claim_mine_slot(self._cmd())
        assert p is not None and p.exists()

    def test_second_create_race(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        pf = hc._pid_file_for_cmd(self._cmd())
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("999999 0", encoding="utf-8")
        monkeypatch.setattr(hc, "_mine_already_running", lambda cmd: False)
        monkeypatch.setattr(
            hc, "_create_mine_slot_with_placeholder", lambda pf: (_ for _ in ()).throw(FileExistsError("race"))
        )
        assert hc._claim_mine_slot(self._cmd()) is None


class TestSpawnMine:
    def _cmd(self, proj):
        return [sys.executable, "-m", "dxrk.memory", "mine", str(proj), "--wing", "default"]

    def test_skip_when_busy(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        logs = []
        monkeypatch.setattr(hc, "_claim_mine_slot", lambda cmd: None)
        monkeypatch.setattr(hc, "_log", logs.append)
        hc._spawn_mine(self._cmd(tmp_path))
        assert any("already running" in m for m in logs)

    def test_success(self, tmp_path, monkeypatch):
        _, state = _iso_hc(monkeypatch, tmp_path, palace=True)
        cmd = self._cmd(tmp_path)
        seen = {}

        def _fake_popen(*a, **k):
            seen.update(k)
            return SimpleNamespace(pid=4242)

        monkeypatch.setattr(hc.subprocess, "Popen", _fake_popen)
        hc._spawn_mine(cmd)
        pf = hc._pid_file_for_cmd(cmd)
        assert pf.read_text(encoding="utf-8").startswith("4242")
        assert seen["env"][hc._MINE_PID_FILE_ENV] == str(pf)

    def test_popen_oserror_cleans(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        cmd = self._cmd(tmp_path)
        pf = hc._pid_file_for_cmd(cmd)
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("111 222", encoding="utf-8")
        monkeypatch.setattr(hc, "_claim_mine_slot", lambda c: pf)
        monkeypatch.setattr(hc.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        with pytest.raises(OSError):
            hc._spawn_mine(cmd)
        assert not pf.exists()

    def test_popen_oserror_unlink_fails(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        cmd = self._cmd(tmp_path)
        pf = hc._pid_file_for_cmd(cmd)
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text("111 222", encoding="utf-8")
        monkeypatch.setattr(hc, "_claim_mine_slot", lambda c: pf)
        monkeypatch.setattr(hc.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
        monkeypatch.setattr(Path, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError):
            hc._spawn_mine(cmd)

    def test_write_oserror_ignored(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        cmd = self._cmd(tmp_path)
        monkeypatch.setattr(hc.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1))
        real_write = Path.write_text

        def _fake_write(self, *a, **k):
            if self.name.endswith(".pid"):
                raise OSError("ro")
            return real_write(self, *a, **k)

        monkeypatch.setattr(Path, "write_text", _fake_write)
        hc._spawn_mine(cmd)


class TestAutoIngestSync:
    def test_auto_no_targets(self, monkeypatch):
        monkeypatch.setattr(hc, "_get_mine_targets", lambda: [])
        hc._maybe_auto_ingest()

    def test_auto_spawn_oserror(self, monkeypatch):
        monkeypatch.setattr(hc, "_get_mine_targets", lambda: [("/tmp/x", "default")])
        monkeypatch.setattr(hc, "_dxrk_python", lambda: "py")
        monkeypatch.setattr(hc, "_spawn_mine", lambda cmd: (_ for _ in ()).throw(OSError("ro")))
        hc._maybe_auto_ingest()

    def test_auto_spawn_ok(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hc, "_get_mine_targets", lambda: [("/tmp/x", "default")])
        monkeypatch.setattr(hc, "_dxrk_python", lambda: "py")
        monkeypatch.setattr(hc, "_spawn_mine", lambda cmd: calls.append(cmd))
        hc._maybe_auto_ingest()
        assert calls[0][:3] == ["py", "-m", "dxrk.memory"]

    def test_sync_no_targets(self, monkeypatch):
        monkeypatch.setattr(hc, "_get_mine_targets", lambda: [])
        hc._mine_sync()

    def test_sync_variants(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        monkeypatch.setattr(hc, "_get_mine_targets", lambda: [("/tmp/x", "default")])
        monkeypatch.setattr(hc, "_dxrk_python", lambda: "py")
        monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
        hc._mine_sync()
        monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        hc._mine_sync()
        monkeypatch.setattr(
            hc.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("c", 60))
        )
        hc._mine_sync()


class TestExtractRecent:
    def _write(self, path, lines):
        with open(path, "w", encoding="utf-8") as f:
            for item in lines:
                f.write(item + "\n" if isinstance(item, str) else json.dumps(item) + "\n")

    def test_missing(self, tmp_path):
        assert hc._extract_recent_messages(str(tmp_path / "no.jsonl")) == []

    def test_branches(self, tmp_path):
        tr = tmp_path / "r.jsonl"
        self._write(
            tr,
            [
                {"message": {"role": "user", "content": "one"}},
                {"event_message": {"role": "user", "content": "two"}},
                {"message": {"role": "user", "content": [{"text": "a"}, {"nope": 1}]}},
                {"message": {"role": "user", "content": 123}},
                {"message": {"role": "user", "content": "   "}},
                {"message": {"role": "user", "content": "<system-reminder>x</system-reminder>"}},
                {"message": {"role": "assistant", "content": "hi"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "three"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": "<command-message>x"}},
                {"type": "event_msg", "payload": {"type": "other", "message": "z"}},
                {"type": "event_msg", "payload": {"type": "user_message", "message": 42}},
                "bad json",
            ],
        )
        assert hc._extract_recent_messages(str(tr)) == ["one", "two", "a", "three"]

    def test_slice_count(self, tmp_path):
        tr = tmp_path / "s.jsonl"
        self._write(tr, [{"message": {"role": "user", "content": f"m{i}"}} for i in range(5)])
        assert hc._extract_recent_messages(str(tr), count=2) == ["m3", "m4"]

    def test_oserror(self, tmp_path, monkeypatch):
        tr = tmp_path / "e.jsonl"
        tr.write_text("x\n")
        real_open = open

        def _fake_open(path, *a, **k):
            if str(path).endswith("e.jsonl"):
                raise OSError("ro")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", _fake_open)
        assert hc._extract_recent_messages(str(tr)) == []


class TestExtractThemes:
    def test_basic(self):
        themes = hc._extract_themes(["hello world project alpha deployment", "world deployment"], max_themes=2)
        assert set(themes) <= {"hello", "world", "project", "alpha", "deployment"}
        assert len(themes) == 2

    def test_noise_ignored(self):
        assert hc._extract_themes(["hi a the 123 !!!"], max_themes=3) == []
        assert hc._extract_themes([], max_themes=3) == []


class TestSaveSummary:
    def test_no_messages(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "empty.jsonl"
        tr.write_text("")
        assert hc._save_session_summary_direct(str(tr), "s1") == {"count": 0}
        assert hc._save_session_summary_direct(str(tmp_path / "missing.jsonl"), "s1") == {"count": 0}

    def test_exception_path(self, tmp_path, monkeypatch):
        import dxrk.memory.palace as pal

        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "t.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            for i in range(3):
                f.write(json.dumps({"message": {"role": "user", "content": f"hello world {i}"}}) + "\n")
        logs = []
        monkeypatch.setattr(hc, "_log", logs.append)
        monkeypatch.setattr(pal, "DxrkMemory", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert hc._save_session_summary_direct(str(tr), "s9") == {"count": 0}
        assert any("error" in m for m in logs)

    def test_ack_oserror_ignored(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "t2.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            for i in range(2):
                f.write(json.dumps({"message": {"role": "user", "content": f"alpha beta gamma {i}"}}) + "\n")
        real_write = Path.write_text

        def _fake_write(self, *a, **k):
            if self.name == "last_checkpoint":
                raise OSError("ro")
            return real_write(self, *a, **k)

        monkeypatch.setattr(Path, "write_text", _fake_write)
        res = hc._save_session_summary_direct(str(tr), "sAck", wing="wing_t")
        assert res["count"] == 2 and "drawer_id" in res

    def test_success(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "t3.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            for i in range(2):
                f.write(json.dumps({"message": {"role": "user", "content": f"project alpha content {i}"}}) + "\n")
        res = hc._save_session_summary_direct(str(tr), "sOk", wing="wing_t")
        assert res["count"] == 2
        assert isinstance(res["themes"], list)


class TestIngestTranscript:
    def test_small_and_missing(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        small = tmp_path / "s.jsonl"
        small.write_text("tiny")
        monkeypatch.setattr(hc, "_spawn_mine", lambda cmd: (_ for _ in ()).throw(AssertionError("no spawn")))
        hc._ingest_transcript(str(small))
        hc._ingest_transcript(str(tmp_path / "missing.jsonl"))

    def test_success(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "big.jsonl"
        tr.write_text("x" * 200)
        calls = []
        monkeypatch.setattr(hc, "_spawn_mine", lambda cmd: calls.append(cmd))
        monkeypatch.setattr(hc, "_dxrk_python", lambda: "py")
        logs = []
        monkeypatch.setattr(hc, "_log", logs.append)
        hc._ingest_transcript(str(tr))
        assert len(calls) == 1 and "mine" in calls[0]
        assert any("ingest started" in m for m in logs)

    def test_spawn_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        tr = tmp_path / "big2.jsonl"
        tr.write_text("y" * 200)
        monkeypatch.setattr(hc, "_spawn_mine", lambda cmd: (_ for _ in ()).throw(OSError("ro")))
        monkeypatch.setattr(hc, "_dxrk_python", lambda: "py")
        hc._ingest_transcript(str(tr))


class TestWingFromTranscript:
    def test_cwd_variants(self, tmp_path):
        tr = tmp_path / "t.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            f.write('{"cwd": }\n')
            f.write('{"cwd": 123}\n')
            f.write('{"cwd": ""}\n')
            f.write('{"cwd": "/"}\n')
            f.write('{"cwd": "/home/user/Projects/MyProject"}\n')
        assert hc._wing_from_transcript_path(str(tr)) == "wing_myproject"

    def test_open_oserror(self, tmp_path, monkeypatch):
        tr = tmp_path / "o.jsonl"
        tr.write_text('{"cwd": "/a/b"}\n')
        monkeypatch.setattr(Path, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        assert hc._wing_from_transcript_path(str(tr)) == "wing_sessions"

    def test_encoded_paths(self):
        assert hc._wing_from_transcript_path("/x/.claude/projects/-Users-bob-git-CoolProj/y.jsonl") == "wing_coolproj"
        assert hc._wing_from_transcript_path("/x/.claude/projects/-plainproj/y.jsonl") == "wing_plainproj"
        assert hc._wing_from_transcript_path("/x/.claude/projects/-Users-bob-dev-Thing/y.jsonl") == "wing_thing"
        assert hc._wing_from_transcript_path("/some-Projects-AwesomeX/file.jsonl") == "wing_awesomex"
        assert hc._wing_from_transcript_path("/nonexistent_xyz/f.jsonl") == "wing_sessions"
        assert hc._wing_from_transcript_path("") == "wing_sessions"

    def test_no_cwd_exhausts(self, tmp_path):
        tr = tmp_path / "nc.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            f.write("\n")
            f.write('{"a": 1}\n')
            f.write('{"cwd": }\n')
        assert hc._wing_from_transcript_path(str(tr)) == "wing_sessions"

    def test_200_line_break(self, tmp_path):
        tr = tmp_path / "big.jsonl"
        with open(tr, "w", encoding="utf-8") as f:
            for _ in range(205):
                f.write('{"a": 1}\n')
        assert hc._wing_from_transcript_path(str(tr)) == "wing_sessions"

    def test_empty_project_after_prefix(self):
        assert hc._wing_from_transcript_path("/x/.claude/projects/-git-/y.jsonl") == "wing_sessions"


class TestHookStop:
    def _base(self):
        return {"session_id": "sess1", "stop_hook_active": False, "transcript_path": ""}

    def test_no_palace(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=False)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        hc.hook_stop(self._base(), "dxrk")
        assert outs == [{}]

    @pytest.mark.parametrize("active", [True, "true", "1", "yes", "YES"])
    def test_stop_active(self, tmp_path, monkeypatch, active):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        data = self._base()
        data["stop_hook_active"] = active
        hc.hook_stop(data, "dxrk")
        assert outs == [{}]

    def test_below_interval(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_count_human_messages", lambda p: 3)
        hc.hook_stop(self._base(), "dxrk")
        assert outs == [{}]

    def test_bad_last_save_and_zero_count(self, tmp_path, monkeypatch):
        _, state = _iso_hc(monkeypatch, tmp_path, palace=True)
        state.mkdir(parents=True, exist_ok=True)
        (state / "sess1_last_save").write_text("garbage")
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_count_human_messages", lambda p: 20)
        monkeypatch.setattr(hc, "_wing_from_transcript_path", lambda p: "wing_x")
        monkeypatch.setattr(hc, "_save_session_summary_direct", lambda *a, **k: {"count": 0})
        monkeypatch.setattr(hc, "_ingest_transcript", lambda p: None)
        monkeypatch.setattr(hc, "_maybe_auto_ingest", lambda: None)
        data = self._base()
        data["transcript_path"] = str(tmp_path / "t.jsonl")
        hc.hook_stop(data, "dxrk")
        assert outs == [{}]

    def test_trigger_save_success(self, tmp_path, monkeypatch):
        _, state = _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        ingested, auto = [], []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_count_human_messages", lambda p: 20)
        monkeypatch.setattr(hc, "_wing_from_transcript_path", lambda p: "wing_x")
        monkeypatch.setattr(hc, "_save_session_summary_direct", lambda *a, **k: {"count": 3, "themes": ["alpha"]})
        monkeypatch.setattr(hc, "_ingest_transcript", lambda p: ingested.append(p))
        monkeypatch.setattr(hc, "_maybe_auto_ingest", lambda: auto.append(1))
        data = self._base()
        data["transcript_path"] = str(tmp_path / "t.jsonl")
        hc.hook_stop(data, "dxrk")
        assert len(outs) == 1 and "3 memories" in outs[0]["systemMessage"]
        assert (state / "sess1_last_save").read_text(encoding="utf-8") == "20"
        assert ingested and auto

    def test_trigger_empty_transcript(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        saved = []
        auto = []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_count_human_messages", lambda p: 20)
        monkeypatch.setattr(hc, "_save_session_summary_direct", lambda *a, **k: saved.append(1) or {"count": 0})
        monkeypatch.setattr(hc, "_maybe_auto_ingest", lambda: auto.append(1))
        hc.hook_stop(self._base(), "dxrk")
        assert outs == [{}] and saved == [] and auto == [1]

    def test_last_save_write_oserror(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_count_human_messages", lambda p: 20)
        monkeypatch.setattr(hc, "_wing_from_transcript_path", lambda p: "wing_x")
        monkeypatch.setattr(hc, "_save_session_summary_direct", lambda *a, **k: {"count": 2, "themes": []})
        monkeypatch.setattr(hc, "_ingest_transcript", lambda p: None)
        monkeypatch.setattr(hc, "_maybe_auto_ingest", lambda: None)
        real_write = Path.write_text

        def _fake_write(self, *a, **k):
            if self.name.endswith("_last_save"):
                raise OSError("ro")
            return real_write(self, *a, **k)

        monkeypatch.setattr(Path, "write_text", _fake_write)
        data = self._base()
        data["transcript_path"] = str(tmp_path / "t.jsonl")
        hc.hook_stop(data, "dxrk")
        assert "2 memories" in outs[0]["systemMessage"]


class TestSessionStartPrecompact:
    def test_session_start_no_palace(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=False)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        hc.hook_session_start({"session_id": "s"}, "dxrk")
        assert outs == [{}]

    def test_session_start_ok(self, tmp_path, monkeypatch):
        _, state = _iso_hc(monkeypatch, tmp_path, palace=True)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        hc.hook_session_start({"session_id": "s"}, "dxrk")
        assert outs == [{}] and state.is_dir()

    def test_precompact_no_palace(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=False)
        outs = []
        monkeypatch.setattr(hc, "_output", outs.append)
        hc.hook_precompact({"session_id": "s", "transcript_path": ""}, "dxrk")
        assert outs == [{}]

    def test_precompact_ok(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs, ingested, synced = [], [], []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_ingest_transcript", lambda p: ingested.append(p))
        monkeypatch.setattr(hc, "_mine_sync", lambda: synced.append(1))
        hc.hook_precompact({"session_id": "s", "transcript_path": str(tmp_path / "t.jsonl")}, "dxrk")
        assert outs == [{}] and len(ingested) == 1 and synced == [1]

    def test_precompact_no_transcript(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        outs, ingested, synced = [], [], []
        monkeypatch.setattr(hc, "_output", outs.append)
        monkeypatch.setattr(hc, "_ingest_transcript", lambda p: ingested.append(p))
        monkeypatch.setattr(hc, "_mine_sync", lambda: synced.append(1))
        hc.hook_precompact({"session_id": "s", "transcript_path": ""}, "dxrk")
        assert outs == [{}] and ingested == [] and synced == [1]


class TestRunHook:
    def test_bad_stdin(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path, palace=True)
        calls = []
        monkeypatch.setattr(hc, "hook_session_start", lambda data, harness: calls.append((data, harness)))
        monkeypatch.setattr(sys, "stdin", io.StringIO("{bad json"))
        hc.run_hook("session-start", "dxrk")
        assert calls == [({}, "dxrk")]

    def test_unknown_hook(self, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
        with pytest.raises(SystemExit):
            hc.run_hook("nope", "dxrk")

    def test_session_end_alias(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(hc, "hook_stop", lambda data, harness: calls.append((data, harness)))
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "a"}'))
        hc.run_hook("session-end", "dxrk")
        assert calls == [({"session_id": "a"}, "dxrk")]

    def test_precompact_dispatch(self, tmp_path, monkeypatch):
        _iso_hc(monkeypatch, tmp_path)
        calls = []
        monkeypatch.setattr(hc, "hook_precompact", lambda data, harness: calls.append(1))
        monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
        hc.run_hook("precompact", "dxrk")
        assert calls == [1]


class TestEnsureHooks:
    def test_fresh_and_idempotent(self, tmp_path, monkeypatch):
        import dxrk.utils.hooks as hu

        home = tmp_path / "h1"
        home.mkdir()
        hc.ensure_hook_configs(home_dir=str(home))
        cfg = json.loads((home / ".config" / "dxrk" / "hooks.json").read_text(encoding="utf-8"))
        assert {h["id"] for h in cfg["hooks"]} == {"dxrk-memory-stop", "dxrk-memory-session-start"}
        calls = []
        orig = hu.SaveConfig
        monkeypatch.setattr(hu, "SaveConfig", lambda *a, **k: (calls.append(1), orig(*a, **k))[1])
        hc.ensure_hook_configs(home_dir=str(home))
        assert calls == []
        cfg2 = json.loads((home / ".config" / "dxrk" / "hooks.json").read_text(encoding="utf-8"))
        assert len(cfg2["hooks"]) == 2

    def test_cfg_none(self, tmp_path, monkeypatch):
        import dxrk.utils.hooks as hu

        home = tmp_path / "h2"
        home.mkdir()
        monkeypatch.setattr(hu, "LoadConfig", lambda p: (None, hu.ErrConfigParse))
        saved = []
        monkeypatch.setattr(hu, "SaveConfig", lambda p, c: saved.append(c) or None)
        hc.ensure_hook_configs(home_dir=str(home))
        assert len(saved) == 1 and len(saved[0].hooks) == 2

    def test_exception_logged(self, tmp_path, monkeypatch):
        import dxrk.utils.hooks as hu

        monkeypatch.setattr(hu, "LoadConfig", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        logs = []
        monkeypatch.setattr(hc, "_log", logs.append)
        hc.ensure_hook_configs(home_dir=str(tmp_path))
        assert any("ensure_hook_configs failed" in m for m in logs)


class TestMainHc:
    def test_ensure_shortcut(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hc, "ensure_hook_configs", lambda *a, **k: calls.append(1))
        assert hc.main(["ensure-hooks"]) == 0
        assert calls == [1]

    def test_hook_dispatch(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hc, "run_hook", lambda name, harness: calls.append((name, harness)))
        assert hc.main(["stop", "dxrk"]) == 0
        assert calls == [("stop", "dxrk")]

    def test_ensure_parsed(self, monkeypatch):
        calls = []
        monkeypatch.setattr(hc, "ensure_hook_configs", lambda *a, **k: calls.append(1))
        monkeypatch.setattr(sys, "argv", ["dxrk-memory-hooks", "ensure-hooks"])
        assert hc.main(None) == 0
        assert calls == [1]


# ═══════════════════════════════════════════════════════════════════════════
# dxrk/memory/__init__.py — helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestMemoryHelpers:
    def test_effective_tenant(self, monkeypatch):
        import dxrk.memory as mem
        import dxrk.tenant.migration as tmig

        assert mem._effective_tenant_id("  t1  ") == "t1"
        monkeypatch.setenv("DXRK_TENANT", " envt ")
        assert mem._effective_tenant_id(None) == "envt"
        monkeypatch.delenv("DXRK_TENANT")
        monkeypatch.setattr(tmig, "is_migrated", lambda: True)
        assert mem._effective_tenant_id(None) == "default"
        monkeypatch.setattr(tmig, "is_migrated", lambda: False)
        assert mem._effective_tenant_id(None) == ""
        monkeypatch.setattr(tmig, "is_migrated", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        assert mem._effective_tenant_id(None) == ""

    def test_resolve_tenant_path(self):
        import dxrk.memory as mem

        assert mem._resolve_memory_tenant_path(None, None) is None
        assert mem._resolve_memory_tenant_path(None, "") == ""
        assert mem._resolve_memory_tenant_path(None, "memory-only") == "memory-only"
        assert mem._resolve_memory_tenant_path("t", "/tmp/x") == "/tmp/x"

    def test_is_sqlite_path(self):
        import dxrk.memory as mem

        assert mem._is_sqlite_path(None) is False
        assert mem._is_sqlite_path("") is False
        assert mem._is_sqlite_path("   ") is False
        assert mem._is_sqlite_path("m.json") is False
        assert mem._is_sqlite_path("M.JSON") is False
        assert mem._is_sqlite_path("/tmp/pal") is True
        assert mem._is_sqlite_path("/tmp/x.db") is True

    def test_parse_dt(self):
        import dxrk.memory as mem

        assert mem._parse_dt("2026-01-02T03:04:05+00:00") == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
        assert mem._parse_dt("zzz") == datetime.fromtimestamp(0, tz=UTC)

    def test_top_by_importance(self):
        entries = [MemoryEntry(importance=0.1), MemoryEntry(importance=0.9)]
        assert top_by_importance(entries, 5) is entries
        assert top_by_importance(entries, 1)[0].importance == 0.9

    def test_memory_type_values(self):
        assert int(MemoryType.SEMANTIC) == 0
        assert int(MemoryType.TECHNICAL) == 3
        assert int(MemoryType.PERSONAL) == 4
        assert MemoryType(1) == MemoryType.EPISODIC


@pytest.fixture
def _iso_tenant(tmp_path, monkeypatch):
    monkeypatch.setenv("DXRK_TENANT", "")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return tmp_path


class TestAgentMemoryJson:
    def test_load_bad_json(self, tmp_path, _iso_tenant):
        p = tmp_path / "bad.json"
        p.write_text("{nope")
        assert AgentMemory(path=str(p)).stats().total_entries == 0

    def test_load_dir(self, tmp_path, _iso_tenant):
        d = tmp_path / "adir.json"
        d.mkdir()
        assert AgentMemory(path=str(d)).stats().total_entries == 0

    def test_load_type_fallback_and_unknown_keys(self, tmp_path, _iso_tenant):
        p = tmp_path / "m.json"
        p.write_text(
            json.dumps(
                [
                    {"id": "a", "type": 99, "content": "hi", "bogus_field": 1},
                    {"id": "b", "type": 1, "content": "yo"},
                ]
            )
        )
        m = AgentMemory(path=str(p))
        assert m.retrieve("a").type == MemoryType.SEMANTIC
        assert m.retrieve("b").type == MemoryType.EPISODIC

    def test_remove_from_index_branches(self, tmp_path, _iso_tenant):
        m = AgentMemory(path=str(tmp_path / "m.json"))
        m.store(MemoryEntry(id="a", content="x", project_id="p1", session_id="s1"))
        m.store(MemoryEntry(id="b", content="y", project_id="p1", session_id="s1"))
        del m._by_project["p1"]
        m.delete("a")
        assert m.retrieve("a") is None
        m._by_session["s1"].remove("b")
        m.delete("b")
        assert m.stats().total_entries == 0

    def test_resolve_missing(self, _iso_tenant):
        m = AgentMemory()
        m._by_project["p"] = ["ghost"]
        assert m.get_by_project("p") == []
        assert m.get_by_session("nosuch") == []
        assert m.get_by_type(MemoryType.SEMANTIC) == []

    def test_search_local_type_int(self, _iso_tenant):
        m = AgentMemory()
        m.store(MemoryEntry(id="a", content="needle", type=MemoryType.EPISODIC))
        assert [e.id for e in m._search_local("", "needle", 1, 10)] == ["a"]
        assert m._search_local("", "needle", 2, 10) == []
        assert m._search_local("", "zzz", 0, 10) == []


class _StubCol:
    def __init__(self, qres=None, getres=None, query_exc=None, get_exc=None, count_val=0):
        self._qres = qres
        self._getres = getres
        self._query_exc = query_exc
        self._get_exc = get_exc
        self._count_val = count_val
        self.deleted = []
        self.upserted = []

    def query(self, **kwargs):
        if self._query_exc is not None:
            raise self._query_exc
        return self._qres

    def get(self, **kwargs):
        if self._get_exc is not None:
            raise self._get_exc
        return self._getres

    def upsert(self, **kwargs):
        self.upserted.append(kwargs)

    def delete(self, **kwargs):
        self.deleted.append(kwargs)

    def count(self):
        if isinstance(self._count_val, Exception):
            raise self._count_val
        return self._count_val


def _sqlite_mem(tmp_path, name="pal"):
    return AgentMemory(path=str(tmp_path / name))


def _qres(ids, docs, metas, dists):
    return SimpleNamespace(ids=[ids], documents=[docs], metadatas=[metas], distances=[dists])


class TestAgentMemorySqliteInit:
    def test_db_file_parent(self, tmp_path, _iso_tenant):
        m = AgentMemory(path=str(tmp_path / "sub" / "x.db"))
        assert m._use_sqlite is True
        assert (tmp_path / "sub").is_dir()

    def test_palace_typeerror_fallback(self, tmp_path, _iso_tenant, monkeypatch):
        import dxrk.memory.palace as pal

        stub_col = _StubCol()

        class _FakePalace:
            def __init__(self, path, *a, **k):
                if "tenant_id" in k:
                    raise TypeError("no tenant kw")
                self.path = path

            def init(self):
                pass

            def _collection(self, create=True):
                return stub_col

        monkeypatch.setattr(pal, "Palace", _FakePalace)
        m = AgentMemory(path=str(tmp_path / "pfb"))
        assert m._use_sqlite is True
        assert m._palace_collection is stub_col

    def test_chmod_oserror_ignored(self, tmp_path, _iso_tenant, monkeypatch):
        monkeypatch.setattr(Path, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        m = _sqlite_mem(tmp_path, "chmodpal")
        assert m._use_sqlite is True

    def test_init_failure_falls_back(self, tmp_path, _iso_tenant, monkeypatch):
        import dxrk.memory.palace as pal

        monkeypatch.setattr(pal.Palace, "init", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        m = _sqlite_mem(tmp_path, "badpal")
        assert m._use_sqlite is False


class TestAgentMemoryStoreSqlite:
    def test_metadata_upsert(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "st1")
        m.store(MemoryEntry(content="hello meta", project_id="p1", session_id="s1", metadata={"custom": "v"}))
        got = m._palace_collection.get(ids=[], include=["documents", "metadatas"])
        assert got is not None
        res = m.retrieve(next(iter(m._entries)))
        assert res is not None

    def test_upsert_error_ignored(self, tmp_path, _iso_tenant, monkeypatch):
        m = _sqlite_mem(tmp_path, "st2")
        monkeypatch.setattr(m._palace_collection, "upsert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        m.store(MemoryEntry(content="hello upsert-fail", project_id="p1"))
        assert len(m._entries) == 1
        assert m.retrieve(next(iter(m._entries))) is not None

    def test_evict_sqlite_delete_error(self, tmp_path, _iso_tenant, monkeypatch):
        m = AgentMemory(path=str(tmp_path / "ev"), max_entries=1)
        m.store(MemoryEntry(id="a", content="first entry here", project_id="p1"))
        monkeypatch.setattr(
            m._palace_collection, "delete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("del boom"))
        )
        m.store(MemoryEntry(id="b", content="second entry here", project_id="p1"))
        assert "a" not in m._entries and "b" in m._entries

    def test_store_rag_variants(self, _iso_tenant):
        m = AgentMemory(rag=SimpleNamespace(is_enabled=lambda: True))
        m.store(MemoryEntry(content="no query attr"))
        assert m.stats().total_entries == 1

        class _Rag:
            def is_enabled(self):
                return True

            def query(self, q, n):
                return [SimpleNamespace(id="x")]

        m2 = AgentMemory(rag=_Rag())
        m2.store(MemoryEntry(content="no embedding attr"))
        assert next(iter(m2._entries.values())).embedding is None


class TestAgentMemoryRetrieveSqlite:
    def test_empty_ids(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "rt0")
        m._palace_collection = _StubCol(getres=SimpleNamespace(ids=[], documents=[], metadatas=[]))
        assert m.retrieve("ghost") is None

    def test_full_meta(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "rt1")
        meta = {
            "project_id": "p1",
            "session_id": "s1",
            "type": 1,
            "importance": 2.5,
            "wing": "w",
            "room": "r",
            "source_file": "f",
            "filed_at": "2024-01-01T00:00:00",
            "custom": "k",
        }
        m._palace_collection = _StubCol(getres=SimpleNamespace(ids=["a"], documents=["doc a"], metadatas=[meta]))
        e = m.retrieve("a")
        assert e is not None and e.content == "doc a"
        assert e.type == MemoryType.EPISODIC and e.importance == 2.5
        assert e.metadata == {"custom": "k"}
        assert e.wing == "w" and e.palace_path == "f"
        e2 = m.retrieve("a")
        assert e2.access_count == 2

    def test_meta_not_dict_and_bad_values(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "rt2")
        m._palace_collection = _StubCol(getres=SimpleNamespace(ids=["b"], documents=[""], metadatas=["bad"]))
        e = m.retrieve("b")
        assert e is not None and e.metadata is None and e.type == MemoryType.SEMANTIC
        m2 = _sqlite_mem(tmp_path, "rt2b")
        m2._palace_collection = _StubCol(
            getres=SimpleNamespace(ids=["c"], documents=["x"], metadatas=[{"type": "bad", "importance": "bad"}])
        )
        e2 = m2.retrieve("c")
        assert e2.type == MemoryType.SEMANTIC and e2.importance == 0.0
        m3 = _sqlite_mem(tmp_path, "rt2c")
        m3._palace_collection = _StubCol(
            getres=SimpleNamespace(ids=["d"], documents=["x"], metadatas=[{"mem_type": 2, "importance": None}])
        )
        assert m3.retrieve("d").type == MemoryType.PROCEDURAL

    def test_get_raises(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "rt3")
        m._palace_collection = _StubCol(get_exc=RuntimeError("boom"))
        assert m.retrieve("ghost") is None

    def test_delete_missing_sqlite(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "del1")
        stub = _StubCol()
        m._palace_collection = stub
        m.delete("ghost")
        assert stub.deleted == [{"ids": ["ghost"]}]
        m._palace_collection = _StubCol()
        monkeypatch_del = mock.MagicMock(side_effect=RuntimeError("boom"))
        m._palace_collection.delete = monkeypatch_del
        m.delete("ghost2")

    def test_delete_missing_json(self, _iso_tenant):
        m = AgentMemory()
        m.delete("ghost")

    def test_delete_present_sqlite_error(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "del2")
        m.store(MemoryEntry(id="a", content="hello", project_id="p1", session_id="s1"))
        m._palace_collection.delete = mock.MagicMock(side_effect=RuntimeError("boom"))
        m.delete("a")
        assert "a" not in m._entries

    def test_evict_json(self, tmp_path, _iso_tenant):
        m = AgentMemory(path=str(tmp_path / "evj.json"), max_entries=1)
        m.store(MemoryEntry(id="a", content="first", project_id="p1"))
        m.store(MemoryEntry(id="b", content="second", project_id="p1"))
        assert "a" not in m._entries and "b" in m._entries


class TestAgentMemorySearchSqlite:
    def _meta(self, **kw):
        base = {
            "project_id": "p1",
            "session_id": "s1",
            "type": 1,
            "importance": 2.0,
            "wing": "w",
            "room": "r",
            "source_file": "f",
            "filed_at": "2024-06-01T00:00:00",
        }
        base.update(kw)
        return base

    def test_basic_query(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq0")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello alpha"], [self._meta(custom="k")], [0.2]))
        out = m.search("p1", "alpha")
        assert [e.id for e in out] == ["a"]
        assert out[0].importance == 2.0
        assert out[0].metadata == {"custom": "k"}

    def test_memtype_only_meta(self, tmp_path, _iso_tenant):
        meta = self._meta()
        del meta["type"]
        meta["mem_type"] = 2
        m = _sqlite_mem(tmp_path, "sq0b")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [meta], [0.1]))
        out = m.search("p1", "hello", MemoryType.PROCEDURAL, 10)
        assert [e.id for e in out] == ["a"]
        assert out[0].type == MemoryType.PROCEDURAL

    def test_bad_type_and_importance_query_path(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq0c")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta(type="bad", importance="bad")], [0.4]))
        out = m.search("p1", "hello", 0, 10)
        assert len(out) == 1
        assert out[0].type == MemoryType.SEMANTIC
        assert out[0].importance == pytest.approx(0.6)

    def test_substring_skip_falls_back(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq1")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["nothing here"], [self._meta()], [0.1]))
        assert m.search("p1", "zzz_no_match") == []

    def test_memtype_filter(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq2a")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta()], [0.1]))
        assert len(m.search("p1", "hello", MemoryType.EPISODIC, 10)) == 1
        m2 = _sqlite_mem(tmp_path, "sq2b")
        m2._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta()], [0.1]))
        assert m2.search("p1", "hello", MemoryType.PROCEDURAL, 10) == []
        m3 = _sqlite_mem(tmp_path, "sq2c")
        m3._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta(type="bad")], [0.1]))
        assert m3.search("p1", "hello", MemoryType.EPISODIC, 10) == []

    def test_date_window(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq3a")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta()], [0.1]))
        assert len(m.search("p1", "hello", 0, 10, since="2024-01-01", before="2025-01-01")) == 1
        m2 = _sqlite_mem(tmp_path, "sq3b")
        m2._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta()], [0.1]))
        assert m2.search("p1", "hello", 0, 10, since="2025-01-01", before="2026-01-01") == []
        m3 = _sqlite_mem(tmp_path, "sq3c")
        m3._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta(filed_at=None)], [0.1]))
        assert m3.search("p1", "hello", 0, 10, since="2024-01-01", before="2025-01-01") == []

    def test_parse_error_raises(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq4")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta()], [0.1]))
        with pytest.raises(ValueError):
            m.search("p1", "hello", 0, 10, since="not-a-date")
        with pytest.raises(ValueError):
            m.search("p1", "", 0, 10, since="not-a-date")

    def test_dist_and_importance(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq5")
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta(importance=0)], [None]))
        out = m.search("p1", "hello")
        assert out[0].importance == 0.0
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], [self._meta(importance=0)], ["bad"]))
        assert m.search("p1", "hello")[0].importance == 0.0
        m._palace_collection = _StubCol(qres=_qres(["a"], ["hello"], ["notadict"], [0.3]))
        out2 = m.search("p1", "hello")
        assert out2[0].importance == pytest.approx(0.7)

    def test_limit_break(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq6")
        metas = [self._meta(), self._meta()]
        m._palace_collection = _StubCol(qres=_qres(["a", "b"], ["hello one", "hello two"], metas, [0.1, 0.2]))
        assert len(m.search("p1", "hello", 0, 1)) == 1

    def test_broken_qres(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq7")
        m._palace_collection = _StubCol(qres=object())
        assert m.search("p1", "hello") == []

    def test_query_raises(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq8")
        m._palace_collection = _StubCol(query_exc=RuntimeError("boom"))
        assert m.search("p1", "hello") == []
        m._palace_collection = _StubCol(query_exc=ValueError("bad window"))
        with pytest.raises(ValueError):
            m.search("p1", "hello")

    def test_empty_query_get_path(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq9")
        getres = SimpleNamespace(
            ids=["a", "b"], documents=["doc a", "doc b"], metadatas=[self._meta(), self._meta(type=2)]
        )
        m._palace_collection = _StubCol(getres=getres)
        assert len(m.search("p1", "")) == 2
        assert len(m.search("p1", "", MemoryType.PROCEDURAL, 10)) == 1
        assert len(m.search("p1", "", 0, 1)) == 1

    def test_empty_query_memtype_only_and_bad(self, tmp_path, _iso_tenant):
        meta = self._meta()
        del meta["type"]
        meta["mem_type"] = 2
        m = _sqlite_mem(tmp_path, "sq9b")
        m._palace_collection = _StubCol(getres=SimpleNamespace(ids=["a"], documents=["doc"], metadatas=[meta]))
        assert len(m.search("p1", "", MemoryType.PROCEDURAL, 10)) == 1
        m2 = _sqlite_mem(tmp_path, "sq9c")
        m2._palace_collection = _StubCol(
            getres=SimpleNamespace(ids=["a"], documents=["doc"], metadatas=[self._meta(type="bad")])
        )
        assert len(m2.search("p1", "", MemoryType.PROCEDURAL, 10)) == 0
        m3 = _sqlite_mem(tmp_path, "sq9d")
        m3._palace_collection = _StubCol(
            getres=SimpleNamespace(ids=["a"], documents=["doc"], metadatas=[self._meta(type="bad")])
        )
        out = m3.search("p1", "", 0, 10)
        assert len(out) == 1 and out[0].type == MemoryType.SEMANTIC

    def test_empty_query_date_and_bad(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq10a")
        getres = SimpleNamespace(
            ids=["a"],
            documents=["doc"],
            metadatas=[self._meta(filed_at="2024-06-01T00:00:00", importance="bad")],
        )
        m._palace_collection = _StubCol(getres=getres)
        assert len(m.search("p1", "", 0, 10, since="2024-01-01", before="2025-01-01")) == 1
        m2 = _sqlite_mem(tmp_path, "sq10b")
        m2._palace_collection = _StubCol(getres=getres)
        assert m2.search("p1", "", 0, 10, since="2026-01-01", before="2027-01-01") == []
        m3 = _sqlite_mem(tmp_path, "sq10c")
        m3._palace_collection = _StubCol(getres=SimpleNamespace(ids=["a"], documents=["d"], metadatas=["bad"]))
        assert len(m3.search("p1", "")) == 1
        m4 = _sqlite_mem(tmp_path, "sq10d")
        m4._palace_collection = _StubCol(getres=getres)
        assert m4.search("p1", "", 0, 0) == []

    def test_empty_query_raises(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "sq11")
        m._palace_collection = _StubCol(get_exc=ValueError("bad"))
        with pytest.raises(ValueError):
            m.search("p1", "")
        m._palace_collection = _StubCol(get_exc=RuntimeError("boom"))
        assert m.search("p1", "") == []


class TestAgentMemoryFilterRag:
    class _Rec:
        def __init__(self, i):
            self.id = i

    class _Rag:
        def __init__(self, res):
            self._res = res

        def is_enabled(self):
            return True

        def query(self, q, n):
            return self._res

    def test_filter_branches(self, _iso_tenant):
        rag = self._Rag([self._Rec("a"), self._Rec("b"), self._Rec("ghost")])
        m = AgentMemory(rag=rag)
        m.store(MemoryEntry(id="a", content="x", project_id="p1", type=MemoryType.SEMANTIC))
        m.store(MemoryEntry(id="b", content="y", project_id="p2", type=MemoryType.SEMANTIC))
        assert m.search("p1", "q", MemoryType.PROCEDURAL, 10) == []
        assert [e.id for e in m.search("p1", "q", MemoryType.SEMANTIC, 10)] == ["a"]
        assert [e.id for e in m.search("", "q", 0, 10)] == ["a", "b"]

    def test_search_rag_empty_and_disabled(self, _iso_tenant):
        empty_rag = self._Rag([])
        m = AgentMemory(rag=empty_rag)
        m.store(MemoryEntry(id="a", content="needle here", project_id="p1"))
        assert [e.id for e in m.search("", "needle", 0, 10)] == ["a"]
        noquery_rag = SimpleNamespace(is_enabled=lambda: True)
        m2 = AgentMemory(rag=noquery_rag)
        m2.store(MemoryEntry(id="b", content="needle here", project_id="p1"))
        assert [e.id for e in m2.search("", "needle", 0, 10)] == ["b"]

    def test_store_rag_empty_results(self, _iso_tenant):
        m = AgentMemory(rag=self._Rag([]))
        m.store(MemoryEntry(content="hello with rag but no results", project_id="p1"))
        assert next(iter(m._entries.values())).embedding is None


class TestAgentMemoryStatsSqlite:
    def test_real_stats(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats1")
        m.store(MemoryEntry(content="alpha one", project_id="p1", session_id="s1", type=MemoryType.SEMANTIC))
        m.store(MemoryEntry(content="beta two", project_id="p1", session_id="s2", type=MemoryType.EPISODIC))
        st = m.stats()
        assert st.total_entries == 2
        assert st.by_type == {MemoryType.SEMANTIC: 1, MemoryType.EPISODIC: 1}
        assert st.by_project == 1
        assert st.by_session == 2

    def test_count_raises_fallback(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats2")
        m.store(MemoryEntry(content="hello", project_id="p1"))
        m._palace_collection = _StubCol(count_val=RuntimeError("boom"))
        st = m.stats()
        assert st.total_entries == 1

    def test_get_raises_palace_count(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats3")
        m.store(MemoryEntry(content="hello", project_id="p1"))
        m._palace_collection = _StubCol(count_val=7, get_exc=RuntimeError("boom"))
        st = m.stats()
        assert st.total_entries == 7

    def test_empty_ids_palace_count(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats4")
        m.store(MemoryEntry(content="hello", project_id="p1"))
        m._palace_collection = _StubCol(count_val=4, getres=SimpleNamespace(ids=[], metadatas=[]))
        assert m.stats().total_entries == 4

    def test_meta_branches(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats5")
        m.store(MemoryEntry(content="hello", project_id="p1"))
        metas = ["notadict", {"type": "bad", "wing": "w1", "room": "r1"}, {"mem_type": 1}, {"wing": 123, "room": 456}]
        m._palace_collection = _StubCol(count_val=9, getres=SimpleNamespace(ids=["a", "b", "c", "d"], metadatas=metas))
        st = m.stats()
        assert st.total_entries == 9
        assert st.by_project == 1 and st.by_session == 1

    def test_no_wings_fallback(self, tmp_path, _iso_tenant):
        m = _sqlite_mem(tmp_path, "stats6")
        m.store(MemoryEntry(content="hello", project_id="p1", session_id="s1"))
        m._palace_collection = _StubCol(count_val=3, getres=SimpleNamespace(ids=["a"], metadatas=[{"type": 0}]))
        st = m.stats()
        assert st.total_entries == 3
        assert st.by_project == 1 and st.by_session == 1


class TestMemoryImportFallback:
    def test_reimport_without_backend(self, monkeypatch):
        import importlib

        import dxrk.memory as mem_mod

        monkeypatch.setitem(sys.modules, "dxrk.memory.backend", None)
        try:
            importlib.reload(mem_mod)
            assert hasattr(mem_mod, "AgentMemory")
        finally:
            monkeypatch.undo()
            importlib.reload(mem_mod)
        assert hasattr(mem_mod, "AgentMemory")
