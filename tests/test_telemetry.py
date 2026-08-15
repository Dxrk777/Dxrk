import json
import os
from datetime import timedelta

import pytest

from dxrk.telemetry import (
    Config,
    Store,
    ToolCallCounter,
    default_config,
    new_store,
    new_tool_call_counter,
)


def test_new_store_disabled(tmp_path):
    s = new_store(Config(enabled=False, dir=str(tmp_path)))
    s.record("tool_call", "test_tool", True, timedelta(seconds=1))
    assert s.flush() is None


def test_store_record_and_flush(tmp_path):
    s = new_store(Config(enabled=True, dir=str(tmp_path)))
    s.record("tool_call", "greet", True, timedelta(milliseconds=100))
    s.record("tool_call", "search", False, timedelta(milliseconds=500))
    assert s.flush() is None

    entries = os.listdir(tmp_path)
    assert len(entries) > 0
    assert any(e.startswith("events_") for e in entries)


def test_store_enable_disable(tmp_path):
    s = new_store(default_config(str(tmp_path)))
    assert not s.is_enabled()

    s.enable()
    assert s.is_enabled()

    s.disable()
    assert not s.is_enabled()


def test_store_flush_empty(tmp_path):
    s = new_store(Config(enabled=True, dir=str(tmp_path)))
    assert s.flush() is None


def test_tool_call_counter(tmp_path):
    store = new_store(Config(enabled=True, dir=str(tmp_path)))
    counter = new_tool_call_counter(store)

    counter.record_call("test_tool", True, timedelta(milliseconds=50))
    counter.record_call("slow_tool", False, timedelta(seconds=2))

    assert counter.flush() is None

    entries = os.listdir(tmp_path)
    assert len(entries) >= 1


def test_flush_writes_event_contents(tmp_path):
    s = new_store(Config(enabled=True, dir=str(tmp_path)))
    s.record("tool_call", "greet", True, timedelta(milliseconds=100))
    s.flush()

    events_files = [f for f in os.listdir(tmp_path) if f.startswith("events_")]
    assert len(events_files) == 1

    with open(os.path.join(tmp_path, events_files[0])) as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]["action"] == "tool_call"
    assert data[0]["tool"] == "greet"
    assert data[0]["success"] is True
    assert data[0]["duration"] == "100ms"
    assert data[0]["timestamp"]


def test_flush_clears_buffer(tmp_path):
    s = new_store(Config(enabled=True, dir=str(tmp_path)))
    s.record("tool_call", "greet", True, timedelta(milliseconds=100))
    s.flush()
    s.flush()

    events_files = [f for f in os.listdir(tmp_path) if f.startswith("events_")]
    assert len(events_files) == 1


def test_flush_disabled_is_noop(tmp_path):
    s = new_store(Config(enabled=False, dir=str(tmp_path)))
    s.record("tool_call", "greet", True, timedelta(milliseconds=100))
    s.flush()

    assert os.listdir(tmp_path) == []


def test_disable_writes_config(tmp_path):
    s = new_store(Config(enabled=True, dir=str(tmp_path)))
    s.disable()

    with open(os.path.join(tmp_path, "config.json")) as f:
        data = json.load(f)
    assert data["enabled"] is False


def test_enable_writes_config(tmp_path):
    s = new_store(Config(enabled=False, dir=str(tmp_path)))
    s.enable()

    with open(os.path.join(tmp_path, "config.json")) as f:
        data = json.load(f)
    assert data["enabled"] is True
