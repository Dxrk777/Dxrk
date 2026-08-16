# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.hooks (mirrors internal/hooks port)."""

from __future__ import annotations

import io
import json
import time
from datetime import datetime, timedelta

from dxrk.utils import hooks

_BG = hooks._background()


class TestHookType:
    def test_int_values(self):
        assert [int(t) for t in hooks.HookType] == [0, 1, 2, 3, 4, 5]

    def test_string(self):
        values = [
            hooks.PreToolUse.string(),
            hooks.PostToolUse.string(),
            hooks.UserPromptSubmit.string(),
            hooks.Notification.string(),
            hooks.Stop.string(),
            hooks.SubagentStop.string(),
        ]
        assert values == [
            "pre_tool_use",
            "post_tool_use",
            "user_prompt_submit",
            "notification",
            "stop",
            "subagent_stop",
        ]

    def test_unknown_name(self):
        assert hooks._hook_type_name(99) == "unknown"

    def test_parse_roundtrip(self):
        for value in hooks.HookType:
            assert hooks.ParseHookType(value.string()) == (value, True)

    def test_parse_bogus(self):
        assert hooks.ParseHookType("bogus") == (hooks.PreToolUse, False)


class TestConfig:
    def test_default_config(self):
        cfg = hooks.DefaultConfig()
        assert cfg.version == "1.0"
        assert cfg.hooks == []

    def test_load_missing_returns_default(self, tmp_path):
        cfg, err = hooks.LoadConfig(str(tmp_path / "missing.json"))
        assert err is None
        assert cfg.version == "1.0"
        assert cfg.hooks == []

    def test_load_parse_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ not json", encoding="utf-8")
        cfg, err = hooks.LoadConfig(str(path))
        assert cfg is None
        assert err == hooks.ErrConfigParse

    def test_save_load_roundtrip(self, tmp_path):
        cfg = hooks.DefaultConfig()
        cfg.hooks.append(
            hooks.HookConfig(
                id="echo-hook",
                type=hooks.PostToolUse,
                match=hooks.HookMatch(tool_names=["bash"]),
                command="printf",
                args=["hello"],
                timeout=timedelta(seconds=5),
                max_retries=2,
                retry_delay=timedelta(milliseconds=250),
                enabled=True,
            )
        )
        path = tmp_path / "hooks.json"
        assert hooks.SaveConfig(str(path), cfg) is None

        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["version"] == "1.0"
        assert raw["hooks"][0]["id"] == "echo-hook"
        assert raw["hooks"][0]["timeout"] == 5_000_000_000
        assert raw["hooks"][0]["retry_delay"] == 250_000_000
        assert raw["hooks"][0]["match"] == {"tool_names": ["bash"]}

        loaded, err = hooks.LoadConfig(str(path))
        assert err is None
        assert loaded.version == "1.0"
        hook = loaded.hooks[0]
        assert hook.id == "echo-hook"
        assert hook.type == hooks.PostToolUse
        assert hook.timeout == timedelta(seconds=5)
        assert hook.max_retries == 2
        assert hook.retry_delay == timedelta(milliseconds=250)
        assert hook.args == ["hello"]
        assert hook.match.tool_names == ["bash"]
        assert hook.enabled is True

    def test_load_applies_defaults(self, tmp_path):
        path = tmp_path / "hooks.json"
        path.write_text(
            '{"version": "", "hooks": [{"id": "n", "command": "printf"}]}',
            encoding="utf-8",
        )
        cfg, err = hooks.LoadConfig(str(path))
        assert err is None
        assert cfg.version == "1.0"
        hook = cfg.hooks[0]
        assert hook.timeout == timedelta(seconds=30)
        assert hook.retry_delay == timedelta(seconds=1)
        assert hook.type == hooks.PreToolUse

    def test_validate(self):
        assert hooks.ValidateConfig(hooks.DefaultConfig()) is None
        assert hooks.ValidateConfig(None) == hooks.ErrConfigParse
        assert hooks.ValidateConfig(hooks.HookConfigFile()) is None
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(hooks=[hooks.HookConfig(id="", command="x")])
            )
            == hooks.ErrConfigParse
        )
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(
                    hooks=[
                        hooks.HookConfig(id="a", command="x"),
                        hooks.HookConfig(id="a", command="y"),
                    ]
                )
            )
            == hooks.ErrInvalidConfig
        )
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(hooks=[hooks.HookConfig(id="a", command="")])
            )
            == hooks.ErrConfigParse
        )
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(
                    hooks=[hooks.HookConfig(id="a", type=99, command="x")]
                )
            )
            == hooks.ErrConfigParse
        )
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(
                    hooks=[hooks.HookConfig(id="a", command="x", max_retries=-1)]
                )
            )
            == hooks.ErrConfigParse
        )
        assert (
            hooks.ValidateConfig(
                hooks.HookConfigFile(
                    hooks=[
                        hooks.HookConfig(
                            id="a", command="x", timeout=timedelta(seconds=-1)
                        )
                    ]
                )
            )
            == hooks.ErrConfigParse
        )

    def test_merge_first_wins(self):
        merged = hooks.MergeConfigs(
            hooks.HookConfigFile(hooks=[hooks.HookConfig(id="a", command="1")]),
            hooks.HookConfigFile(
                hooks=[
                    hooks.HookConfig(id="a", command="2"),
                    hooks.HookConfig(id="b", command="3"),
                ]
            ),
        )
        assert [x.id for x in merged.hooks] == ["a", "b"]
        assert hooks.MergeConfigs(None, None).hooks == []

    def test_filters(self):
        cfg = hooks.HookConfigFile(
            hooks=[
                hooks.HookConfig(id="a", type=hooks.PreToolUse, enabled=True),
                hooks.HookConfig(id="b", type=hooks.PostToolUse, enabled=False),
            ]
        )
        assert [x.id for x in hooks.FilterByType(cfg, hooks.PreToolUse)] == ["a"]
        assert [x.id for x in hooks.FilterEnabled(cfg)] == ["a"]

    def test_defaults_apply(self):
        hd = hooks.HookDefaults(
            timeout=timedelta(seconds=7),
            max_retries=2,
            retry_delay=timedelta(seconds=3),
        )
        c = hooks.HookConfig(id="z", command="x")
        hd.ApplyDefaults(c)
        assert c.timeout == timedelta(seconds=7)
        assert c.max_retries == 0
        assert c.retry_delay == timedelta(seconds=3)

        c2 = hooks.HookConfig(
            id="z",
            command="x",
            timeout=timedelta(seconds=1),
            retry_delay=timedelta(seconds=9),
            max_retries=-4,
        )
        hd.ApplyDefaults(c2)
        assert c2.timeout == timedelta(seconds=1)
        assert c2.retry_delay == timedelta(seconds=9)
        assert c2.max_retries == 2

    def test_default_hook_defaults(self):
        dh = hooks.DefaultHookDefaults()
        assert dh.timeout == timedelta(seconds=30)
        assert dh.max_retries == 3
        assert dh.retry_delay == timedelta(seconds=1)


class TestMatcher:
    def test_tool_name(self):
        m = hooks.HookMatcher()
        assert m.MatchToolName(hooks.HookMatch(tool_name="bash"), "bash") is True
        assert m.MatchToolName(hooks.HookMatch(tool_name="bash"), "python") is False
        assert m.MatchToolName(hooks.HookMatch(tool_names=["bash", "sh"]), "sh") is True
        assert m.MatchToolName(hooks.HookMatch(tool_names=["bash"]), "sh") is False

    def test_path_glob(self):
        m = hooks.HookMatcher()
        assert m.MatchPath(hooks.HookMatch(glob="*.go"), "test.go") is True
        assert m.MatchPath(hooks.HookMatch(glob="*.go"), "test.py") is False
        assert m.MatchPath(hooks.HookMatch(glob="bash*"), "bash123") is True

    def test_path_paths_and_regex(self):
        m = hooks.HookMatcher()
        assert m.MatchPath(hooks.HookMatch(paths=["a", "b"]), "b") is True
        assert m.MatchPath(hooks.HookMatch(regex="^a+b$"), "ab") is True
        assert m.MatchPath(hooks.HookMatch(regex="^a+b$"), "abb") is False
        assert m.MatchPath(hooks.HookMatch(regex="("), "x") is False

    def test_command(self):
        m = hooks.HookMatcher()
        assert m.MatchCommand(hooks.HookMatch(command="git"), "git") is True

    def test_event_quirks(self):
        m = hooks.HookMatcher()
        assert (
            m.MatchEvent(
                hooks.HookMatch(tool_name="bash", glob="bash*"),
                hooks.HookEvent(tool_name="bash123"),
            )
            is False
        )
        assert (
            m.MatchEvent(
                hooks.HookMatch(glob="bash*"), hooks.HookEvent(tool_name="bash123")
            )
            is True
        )
        assert (
            m.MatchEvent(
                hooks.HookMatch(command="bash123"), hooks.HookEvent(tool_name="bash123")
            )
            is True
        )
        assert (
            m.MatchEvent(
                hooks.HookMatch(glob="*.go"), hooks.HookEvent(tool_name="bash")
            )
            is False
        )


class TestRegistry:
    def test_register_get_list(self):
        r = hooks.HookRegistry()
        cfg = hooks.HookConfig(
            id="test-hook",
            command="printf",
            args=["hello"],
            match=hooks.HookMatch(tool_names=["bash"]),
            enabled=True,
        )
        assert r.Register(cfg) is None
        hook, ok = r.Get("test-hook")
        assert ok is True
        assert hook.timeout == timedelta(seconds=30)
        assert hook.retry_delay == timedelta(seconds=1)
        assert [x.id for x in r.List()] == ["test-hook"]
        assert r.Get("nope") == (None, False)

    def test_register_errors(self):
        r = hooks.HookRegistry()
        cfg = hooks.HookConfig(id="dup", command="x")
        assert r.Register(cfg) is None
        assert r.Register(cfg) == hooks.ErrDuplicateHookID
        assert (
            r.Register(hooks.HookConfig(id="", command="x")) == hooks.ErrInvalidConfig
        )
        assert (
            r.Register(hooks.HookConfig(id="x", command="")) == hooks.ErrInvalidConfig
        )

    def test_get_by_type_and_match(self):
        r = hooks.HookRegistry()
        r.Register(
            hooks.HookConfig(
                id="glob-hook",
                command="printf",
                match=hooks.HookMatch(glob="*"),
                enabled=True,
            )
        )
        r.Register(
            hooks.HookConfig(
                id="off-hook",
                command="printf",
                match=hooks.HookMatch(glob="*"),
                enabled=False,
            )
        )
        r.Register(
            hooks.HookConfig(
                id="post-hook", type=hooks.PostToolUse, command="printf", enabled=True
            )
        )
        assert r.GetByType(hooks.PreToolUse) == ["glob-hook", "off-hook"]
        assert [c.id for c in r.Match(hooks.HookEvent(tool_name="bash"))] == [
            "glob-hook"
        ]
        assert [
            c.id
            for c in r.Match(hooks.HookEvent(type=hooks.PostToolUse, tool_name="bash"))
        ] == ["post-hook"]

    def test_unregister(self):
        r = hooks.HookRegistry()
        r.Register(hooks.HookConfig(id="a", command="x"))
        assert r.Unregister("a") is True
        assert r.Unregister("a") is False
        assert r.GetByType(hooks.PreToolUse) == []

    def test_watch_fires(self):
        r = hooks.HookRegistry()
        w = r.Watch(_BG)
        r.Register(hooks.HookConfig(id="a", command="x"))
        assert w.recv(timeout=1.0) is True

    def test_close(self):
        r = hooks.HookRegistry()
        r.Register(hooks.HookConfig(id="a", command="x"))
        w = r.Watch(_BG)
        r.Close()
        assert (
            r.Register(hooks.HookConfig(id="b", command="x")) == hooks.ErrRegistryClosed
        )
        assert r.Match(hooks.HookEvent()) == []
        assert r.Unregister("a") is False
        assert w.recv(timeout=0.2) is False


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        cb = hooks.NewCircuitBreaker(3, 2, timedelta(milliseconds=150))
        assert cb.State() == hooks.CircuitClosed

        calls = []

        def fail_fn(_ctx):
            calls.append(1)
            return hooks.ErrHookAborted

        for _ in range(3):
            assert cb.Execute(_BG, fail_fn) == hooks.ErrHookAborted
        assert cb.State() == hooks.CircuitOpen
        assert len(calls) == 3

        def ok_fn(_ctx):
            calls.append(1)
            return None

        assert cb.Execute(_BG, ok_fn) == hooks.ErrCircuitOpen
        assert len(calls) == 3

    def test_half_open_recovers(self):
        cb = hooks.NewCircuitBreaker(3, 2, timedelta(milliseconds=150))
        for _ in range(3):
            cb.Execute(_BG, lambda _ctx: hooks.ErrHookAborted)
        assert cb.State() == hooks.CircuitOpen

        import time

        time.sleep(0.2)
        assert cb.Execute(_BG, lambda _ctx: None) is None
        assert cb.State() == hooks.CircuitHalfOpen
        cb.Execute(_BG, lambda _ctx: None)
        assert cb.State() == hooks.CircuitClosed

    def test_reset(self):
        cb = hooks.NewCircuitBreaker(1, 1, timedelta(seconds=10))
        cb.Execute(_BG, lambda _ctx: hooks.ErrHookAborted)
        assert cb.State() == hooks.CircuitOpen
        cb.Reset()
        assert cb.State() == hooks.CircuitClosed


class TestExecutor:
    def test_success(self):
        ex = hooks.NewHookExecutor(hooks.WithExecutorRetries(0))
        res = ex.Execute(
            _BG,
            hooks.HookConfig(command="printf", args=["hook-output"]),
            hooks.HookEvent(),
        )
        assert res.success is True
        assert res.stdout == "hook-output"
        assert res.exit_code == 0
        assert res.duration >= timedelta(0)

    def test_failure_with_retry(self):
        ex = hooks.NewHookExecutor(
            hooks.WithExecutorRetries(1),
            hooks.WithExecutorRetryDelay(timedelta(milliseconds=50)),
        )
        res = ex.Execute(
            _BG,
            hooks.HookConfig(command="sh", args=["-c", "exit 1"]),
            hooks.HookEvent(),
        )
        assert res.success is False
        assert res.error == "exit status 1"
        assert res.exit_code == 1

    def test_timeout(self):
        ex = hooks.NewHookExecutor(
            hooks.WithExecutorRetries(0),
            hooks.WithExecutorTimeout(timedelta(milliseconds=300)),
        )
        res = ex.Execute(
            _BG, hooks.HookConfig(command="sleep", args=["2"]), hooks.HookEvent()
        )
        assert res.success is False
        assert res.error == "hooks: execution timeout"
        assert res.exit_code == -1
        assert res.duration < timedelta(seconds=1)

    def test_command_not_found(self):
        ex = hooks.NewHookExecutor(hooks.WithExecutorRetries(0))
        res = ex.Execute(
            _BG,
            hooks.HookConfig(command="definitely-not-a-command-xyz"),
            hooks.HookEvent(),
        )
        assert res.success is False
        assert res.error == (
            'exec: "definitely-not-a-command-xyz": executable file not found in $PATH'
        )

    def test_circuit_breaker_integration(self):
        ex = hooks.NewHookExecutor(
            hooks.WithExecutorRetries(0),
            hooks.WithCircuitBreaker(
                hooks.NewCircuitBreaker(1, 1, timedelta(seconds=10))
            ),
        )
        res = ex.Execute(
            _BG,
            hooks.HookConfig(command="sh", args=["-c", "exit 2"]),
            hooks.HookEvent(),
        )
        assert res.error == "exit status 2"
        res = ex.Execute(
            _BG, hooks.HookConfig(command="printf", args=["ok"]), hooks.HookEvent()
        )
        assert res.error == "hooks: circuit breaker open"
        assert res.success is False


class TestQueue:
    def test_submit_and_stats(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(2))
        assert q.IsRunning() is True
        q.Start()
        res, err = q.Submit(
            _BG, hooks.HookEvent(), hooks.HookConfig(command="printf", args=["q-out"])
        )
        assert err is None
        assert res.success is True
        assert res.stdout == "q-out"
        assert q.Stats().processed == 1

        res, err = q.Submit(
            _BG,
            hooks.HookEvent(),
            hooks.HookConfig(command="sh", args=["-c", "exit 1"]),
        )
        assert err is None
        assert res.success is False
        assert res.error == "exit status 1"
        stats = q.Stats()
        assert stats.processed == 2
        assert stats.failed == 1
        assert stats.workers == 2
        assert stats.queue_cap == 100

        q.Stop(_BG)
        assert q.IsRunning() is False

    def test_full_queue_blocks(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1), hooks.WithQueueBuffer(1))
        q.Start()

        err_a = q.SubmitAsync(
            hooks.HookEvent(), hooks.HookConfig(command="sleep", args=["0.6"])
        )
        assert err_a is None
        time.sleep(0.1)
        err_b = q.SubmitAsync(
            hooks.HookEvent(), hooks.HookConfig(command="printf", args=["b"])
        )
        assert err_b is None

        res_c, err_c = q.Submit(
            _BG, hooks.HookEvent(), hooks.HookConfig(command="printf", args=["c"])
        )
        assert err_c == hooks.ErrQueueFull
        assert res_c.success is False

        time.sleep(0.8)
        stats = q.Stats()
        assert stats.processed == 2
        assert stats.failed == 0

        q.Stop(_BG)

    def test_submit_async(self):
        q = hooks.NewHookQueue(hooks.WithQueueWorkers(1))
        q.Start()
        assert (
            q.SubmitAsync(
                hooks.HookEvent(), hooks.HookConfig(command="printf", args=["x"])
            )
            is None
        )
        import time

        time.sleep(0.2)
        assert q.Stats().processed == 1
        q.Stop(_BG)


class TestLogger:
    def test_log_line_json(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelInfo)
        logger.Log(
            hooks.HookLogEntry(
                timestamp=datetime(2026, 1, 2, 3, 4, 5),
                level=hooks.LogLevelInfo,
                hook_id="first",
                hook_type=hooks.PostToolUse,
                event=hooks.HookEvent(tool_name="bash"),
                result=hooks.HookResult(
                    success=True, duration=timedelta(milliseconds=100)
                ),
                duration=timedelta(milliseconds=100),
                attempt=1,
            )
        )
        data = json.loads(out.getvalue().strip())
        assert data["timestamp"] == "2026-01-02T03:04:05Z"
        assert data["level"] == 1
        assert data["hook_id"] == "first"
        assert data["hook_type"] == 1
        assert data["result"]["success"] is True
        assert data["duration"] == 100_000_000
        assert data["attempt"] == 1
        assert data["event"]["tool_name"] == "bash"

    def test_level_filtering(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelInfo)
        logger.Log(
            hooks.HookLogEntry(
                level=hooks.LogLevelDebug, hook_id="debug", result=hooks.HookResult()
            )
        )
        assert logger.RecentEntries(10) == []
        logger.Log(
            hooks.HookLogEntry(
                level=hooks.LogLevelError,
                hook_id="failed",
                result=hooks.HookResult(success=False, exit_code=1, error="boom"),
            )
        )
        assert [e.hook_id for e in logger.RecentEntries(10)] == ["failed"]
        logger.SetLevel(hooks.LogLevelError)
        logger.Log(
            hooks.HookLogEntry(
                level=hooks.LogLevelWarn, hook_id="w", result=hooks.HookResult()
            )
        )
        assert [e.hook_id for e in logger.RecentEntries(10)] == ["failed"]

    def test_recent_entries_trim(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelInfo)
        logger.Log(
            hooks.HookLogEntry(
                hook_id="a", level=hooks.LogLevelInfo, result=hooks.HookResult()
            )
        )
        logger.Log(
            hooks.HookLogEntry(
                hook_id="b", level=hooks.LogLevelInfo, result=hooks.HookResult()
            )
        )
        assert [e.hook_id for e in logger.RecentEntries(1)] == ["b"]

    def test_metrics(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelInfo)
        logger.Log(
            hooks.HookLogEntry(
                hook_id="first",
                level=hooks.LogLevelInfo,
                hook_type=hooks.PostToolUse,
                result=hooks.HookResult(
                    success=True, duration=timedelta(milliseconds=100)
                ),
                duration=timedelta(milliseconds=100),
            )
        )
        logger.Log(
            hooks.HookLogEntry(
                hook_id="failed",
                level=hooks.LogLevelInfo,
                result=hooks.HookResult(success=False, exit_code=1, error="boom"),
                duration=timedelta(seconds=1),
            )
        )
        m = logger.Metrics()
        assert m.total_executions == 2
        assert m.success_count == 1
        assert m.failure_count == 1
        assert m.total_duration == timedelta(milliseconds=100) + timedelta(seconds=1)
        assert m.by_type[hooks.PostToolUse].count == 1
        assert m.by_type[hooks.PreToolUse].failure == 1
        assert m.by_hook["first"].count == 1
        assert m.by_hook["failed"].avg_dur == timedelta(seconds=1)

    def test_log_hook_execution_levels(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelInfo)
        logger.LogHookExecution(
            _BG,
            hooks.HookConfig(id="lh"),
            hooks.HookEvent(),
            hooks.HookResult(success=False),
            0,
        )
        assert logger.RecentEntries(1)[0].level == hooks.LogLevelError
        logger.LogHookExecution(
            _BG,
            hooks.HookConfig(id="lh2"),
            hooks.HookEvent(),
            hooks.HookResult(success=True, duration=timedelta(seconds=6)),
            0,
        )
        assert logger.RecentEntries(1)[0].level == hooks.LogLevelWarn
        logger.LogHookExecution(
            _BG,
            hooks.HookConfig(id="lh3"),
            hooks.HookEvent(),
            hooks.HookResult(success=True),
            1,
        )
        assert logger.RecentEntries(1)[0].level == hooks.LogLevelInfo

    def test_add_hook(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelDebug)
        seen = []
        logger.AddHook(lambda entry: seen.append(entry.hook_id))
        logger.Log(hooks.HookLogEntry(hook_id="hooked", result=hooks.HookResult()))
        assert seen == ["hooked"]

    def test_close(self):
        out = io.StringIO()
        logger = hooks.NewHookLogger(out, hooks.LogLevelError)
        logger.Close()
        logger.Log(
            hooks.HookLogEntry(
                level=hooks.LogLevelError, hook_id="x", result=hooks.HookResult()
            )
        )
        assert logger.RecentEntries(10) == []


class TestErrors:
    def test_error_strings(self):
        assert str(hooks.ErrConfigNotFound) == "hooks: config not found"
        assert str(hooks.ErrConfigParse) == "hooks: config parse error"
        assert str(hooks.ErrHookNotFound) == "hooks: hook not found"
        assert str(hooks.ErrHookDisabled) == "hooks: hook is disabled"
        assert str(hooks.ErrInvalidConfig) == "hooks: invalid configuration"
        assert str(hooks.ErrRegistryClosed) == "hooks: registry is closed"
        assert str(hooks.ErrDuplicateHookID) == "hooks: duplicate hook ID"
        assert str(hooks.ErrExecutionTimeout) == "hooks: execution timeout"
        assert str(hooks.ErrMaxRetriesExceeded) == "hooks: max retries exceeded"
        assert str(hooks.ErrCircuitOpen) == "hooks: circuit breaker open"
        assert str(hooks.ErrHookAborted) == "hooks: hook execution aborted"
        assert str(hooks.ErrQueueClosed) == "hooks: queue is closed"
        assert str(hooks.ErrQueueFull) == "hooks: queue is full"
        assert str(hooks.ErrWorkerStopped) == "hooks: worker stopped"
        assert str(hooks.ErrLoggerClosed) == "hooks: logger is closed"
