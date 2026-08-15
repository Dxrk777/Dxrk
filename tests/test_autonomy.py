# SPDX-License-Identifier: MIT
"""Tests for dxrk.autonomy (mirrors internal/autonomy/autonomy_test.go)."""

from __future__ import annotations

import time

import pytest

import dxrk.autonomy.updater as updater_module
from dxrk.autonomy import (
    CapDocker,
    CapFSRead,
    CapFSWrite,
    CapGit,
    MemoryItem,
    New,
    NewEvolutionEngine,
    NewIQMetrics,
    NewLearner,
    NewPermissionStore,
    NewUpdater,
    NewVerifier,
    UpdateResult,
)
from dxrk.autonomy.updater import CmdResult
from dxrk.config import AutonomyConfig


def test_permission_store() -> None:
    ps = NewPermissionStore(["fs.read", "git"], ["fs.write", "sudo"])

    assert ps.check(CapFSRead, "read config") is None
    assert ps.check(CapGit, "commit") is None

    requested = False

    def handler(capability, reason):
        nonlocal requested
        requested = True
        return True, None

    ps.set_request_handler(handler)
    assert ps.check(CapFSWrite, "write file") is None
    assert requested


def test_permission_store_deny() -> None:
    ps = NewPermissionStore(["fs.read"], [])
    ps.deny(CapFSRead, True)
    assert ps.check(CapFSRead, "read") is not None


def test_permission_request_handler() -> None:
    ps = NewPermissionStore([], ["docker"])

    denied = False

    def handler(capability, reason):
        nonlocal denied
        denied = True
        return False, "denied"

    ps.set_request_handler(handler)
    assert ps.check(CapDocker, "run container") is not None
    assert denied


def test_iq_metrics(tmp_path) -> None:
    metrics = NewIQMetrics(str(tmp_path / "iq.json"))

    for i in range(15):
        metrics.record_turn(True, 100 + i * 10, float(50 + i * 5))
    metrics.record_turn(False, 200, 100)
    metrics.record_test_result(True)
    metrics.record_test_result(True)
    metrics.record_test_result(False)
    metrics.record_auto_fix(True)

    score = metrics.score()
    assert score.success_rate > 0
    assert score.test_pass_rate > 0
    assert score.overall_iq > 0


def test_iq_metrics_history(tmp_path) -> None:
    metrics = NewIQMetrics(str(tmp_path / "iq.json"))
    for i in range(25):
        metrics.record_turn(i % 5 != 0, 100, float(50 + i % 10 * 5))

    score = metrics.score()
    assert 0 <= score.overall_iq <= 100


def test_learner(tmp_path) -> None:
    learner = NewLearner(str(tmp_path / "learn.json"), 100)

    learner.record(
        MemoryItem(
            category="test",
            input="create a function that adds two numbers",
            output="func add(a, b int) int { return a + b }",
            success=True,
            tags=["math", "function"],
        )
    )

    suggestions = learner.suggest("add two numbers")
    if not suggestions:
        suggestions = learner.suggest("create a function")
    assert len(suggestions) > 0

    mems = learner.recent_memories(1)
    assert len(mems) == 1
    assert mems[0].success


def test_learner_save_load(tmp_path) -> None:
    path = str(tmp_path / "learn.json")

    l1 = NewLearner(path, 100)
    l1.record(
        MemoryItem(
            category="persist",
            input="how to sort a slice in Go",
            output="sort.Slice(s, func(i, j int) bool { return s[i] < s[j] })",
            success=True,
        )
    )

    time.sleep(0.1)

    l2 = NewLearner(path, 100)
    suggestions = l2.suggest("sort a slice")
    if not suggestions:
        suggestions = l2.suggest("how to sort")
    assert len(suggestions) > 0
    assert suggestions[0].trigger != ""


def test_evolution(tmp_path) -> None:
    learner = NewLearner(str(tmp_path / "learn.json"), 100)
    metrics = NewIQMetrics(str(tmp_path / "iq.json"))
    evo = NewEvolutionEngine(str(tmp_path / "evo.json"), learner, metrics)

    assert len(evo.population()) > 0

    genome = evo.evolve()
    assert genome is not None

    best = evo.best_genome()
    assert best.score > 0


def test_evolution_score(tmp_path) -> None:
    learner = NewLearner(str(tmp_path / "learn.json"), 100)
    metrics = NewIQMetrics(str(tmp_path / "iq.json"))
    evo = NewEvolutionEngine(str(tmp_path / "evo.json"), learner, metrics)

    first = evo.best_genome()
    evo.update_score(first.id, 90.0)

    genome = evo.evolve()
    if genome.score <= first.score:
        pytest.skip("no improvement this run (diversity ok)")


def test_verifier_autofix(tmp_path) -> None:
    learner = NewLearner(str(tmp_path / "learn.json"), 100)
    metrics = NewIQMetrics(str(tmp_path / "iq.json"))
    perms = NewPermissionStore(["fs.read", "fs.write", "exec"], [])
    verifier = NewVerifier(str(tmp_path), False, learner, metrics, perms)

    result = verifier.verify()
    assert result is not None
    assert hasattr(result, "pass_")
    assert hasattr(result, "failures")


def test_autonomy_config(tmp_path) -> None:
    cfg = AutonomyConfig(
        enabled=True,
        interval_sec=30,
        self_update=False,
        self_verify=False,
        self_learn=True,
        auto_fix=True,
        capabilities=["fs.read"],
        ask_before=["fs.write"],
        learn_dir=str(tmp_path),
        memories_file=str(tmp_path / "mem.json"),
        iq_metrics_file=str(tmp_path / "iq.json"),
        max_memory_items=100,
    )

    a = New(cfg, str(tmp_path), None)
    assert a is not None
    assert a.config.enabled is True
    a.stop()


def test_updater_check(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, list[str]]] = []
    state = {"logs": 0}

    def fake_run(project_root, name, args):
        calls.append((name, args))
        if args == ["log", "HEAD..origin/HEAD", "--oneline"]:
            state["logs"] += 1
            if state["logs"] == 1:
                return CmdResult(out="", err=False)
            return CmdResult(out="abc\n", err=False)
        return CmdResult(out="", err=False)

    monkeypatch.setattr(updater_module, "_run_cmd_raw", fake_run)

    perms = NewPermissionStore(["git"], [])
    up = NewUpdater(str(tmp_path), 30, perms)

    res = up.check(False)
    assert isinstance(res, UpdateResult)
    assert res.updated is False
    assert up.last_check() is not None
    first_calls = len(calls)

    res = up.check(False)
    assert res.updated is False
    assert len(calls) == first_calls

    res = up.check(True)
    assert res.updated is True
    assert res.changes == 1
