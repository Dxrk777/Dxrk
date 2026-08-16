# SPDX-License-Identifier: MIT
from __future__ import annotations

from dxrk.pipeline import (
    ExecutionResult,
    FailurePolicy,
    ProgressEvent,
    RollbackPolicy,
    RollbackStep,
    Runner,
    Stage,
    StagePlan,
    StageResult,
    Step,
    StepResult,
    StepStatus,
    default_rollback_policy,
    execute_command,
    execute_rollback,
    new_orchestrator,
    resolve_component_install,
    run_command_sequence,
    set_command_streaming,
    with_failure_policy,
    with_progress_func,
)


class FakeStep(Step):
    def __init__(self, step_id: str, error: str | None = None):
        self._id = step_id
        self._error = error
        self.called = False

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        self.called = True
        return self._error


class FakeRollbackStep(RollbackStep):
    def __init__(
        self,
        step_id: str,
        run_error: str | None = None,
        rollback_error: str | None = None,
    ):
        self._id = step_id
        self._run_error = run_error
        self._rollback_error = rollback_error
        self.run_called = False
        self.rollback_called = False

    def id(self) -> str:
        return self._id

    def run(self) -> str | None:
        self.run_called = True
        return self._run_error

    def rollback(self) -> str | None:
        self.rollback_called = True
        return self._rollback_error


class TestStage:
    def test_values(self):
        assert Stage.PREPARE == "prepare"
        assert Stage.APPLY == "apply"
        assert Stage.ROLLBACK == "rollback"


class TestStepStatus:
    def test_values(self):
        assert StepStatus.PENDING == "pending"
        assert StepStatus.RUNNING == "running"
        assert StepStatus.SUCCEEDED == "succeeded"
        assert StepStatus.FAILED == "failed"
        assert StepStatus.ROLLED_BACK == "rolled-back"
        assert StepStatus.SKIPPED == "skipped"


class TestFailurePolicy:
    def test_values(self):
        assert FailurePolicy.STOP_ON_ERROR == 0
        assert FailurePolicy.CONTINUE_ON_ERROR == 1


class TestRollbackPolicy:
    def test_default_should_not_rollback_prepare(self):
        policy = RollbackPolicy()
        assert policy.should_rollback(Stage.PREPARE, "error") is False

    def test_should_rollback_apply_on_error(self):
        policy = RollbackPolicy()
        assert policy.should_rollback(Stage.APPLY, "error") is True

    def test_no_rollback_when_no_error(self):
        policy = RollbackPolicy()
        assert policy.should_rollback(Stage.APPLY, None) is False

    def test_disabled_rollback(self):
        policy = RollbackPolicy(on_apply_failure=False)
        assert policy.should_rollback(Stage.APPLY, "error") is False


class TestDefaultRollbackPolicy:
    def test_returns_policy_with_rollback_enabled(self):
        policy = default_rollback_policy()
        assert policy.on_apply_failure is True


class TestRunner:
    def test_all_succeed(self):
        runner = Runner()
        steps = [FakeStep("s1"), FakeStep("s2")]
        result = runner.run(Stage.APPLY, steps)
        assert result.success is True
        assert len(result.steps) == 2
        assert all(s.status == StepStatus.SUCCEEDED for s in result.steps)
        assert all(s.called for s in steps)

    def test_stop_on_first_error(self):
        runner = Runner(failure_policy=FailurePolicy.STOP_ON_ERROR)
        steps = [FakeStep("s1", "fail"), FakeStep("s2")]
        result = runner.run(Stage.APPLY, steps)
        assert result.success is False
        assert len(result.steps) == 1
        assert result.steps[0].status == StepStatus.FAILED
        assert steps[0].called is True
        assert steps[1].called is False

    def test_continue_on_error(self):
        runner = Runner(failure_policy=FailurePolicy.CONTINUE_ON_ERROR)
        steps = [FakeStep("s1", "fail"), FakeStep("s2")]
        result = runner.run(Stage.APPLY, steps)
        assert result.success is False
        assert len(result.steps) == 2
        assert result.steps[0].status == StepStatus.FAILED
        assert result.steps[1].status == StepStatus.SUCCEEDED
        assert steps[1].called is True

    def test_emits_progress(self):
        events: list[ProgressEvent] = []
        runner = Runner(on_progress=events.append)
        steps = [FakeStep("s1")]
        runner.run(Stage.PREPARE, steps)
        assert len(events) == 2
        assert events[0].status == StepStatus.RUNNING
        assert events[1].status == StepStatus.SUCCEEDED

    def test_emits_failure_event(self):
        events: list[ProgressEvent] = []
        runner = Runner(
            failure_policy=FailurePolicy.STOP_ON_ERROR, on_progress=events.append
        )
        steps = [FakeStep("s1", "fail")]
        runner.run(Stage.PREPARE, steps)
        assert len(events) == 2
        assert events[1].status == StepStatus.FAILED
        assert events[1].error == "fail"


class TestExecuteRollback:
    def test_rolls_back_in_reverse_order(self):
        s1 = FakeRollbackStep("s1")
        s2 = FakeRollbackStep("s2")
        results = [
            StepResult(step_id="s1", status=StepStatus.SUCCEEDED),
            StepResult(step_id="s2", status=StepStatus.SUCCEEDED),
        ]
        index = {"s1": s1, "s2": s2}
        result = execute_rollback(results, index)
        assert result.success is True
        assert s2.rollback_called is True
        assert s1.rollback_called is True
        assert result.steps[0].step_id == "s2"

    def test_skips_non_rollback_steps(self):
        s1 = FakeStep("s1")
        s2 = FakeRollbackStep("s2")
        results = [
            StepResult(step_id="s1", status=StepStatus.SUCCEEDED),
            StepResult(step_id="s2", status=StepStatus.SUCCEEDED),
        ]
        index = {"s1": s1, "s2": s2}
        result = execute_rollback(results, index)
        assert result.success is True
        assert s2.rollback_called is True

    def test_skips_failed_steps(self):
        s1 = FakeRollbackStep("s1")
        s2 = FakeRollbackStep("s2")
        results = [
            StepResult(step_id="s1", status=StepStatus.FAILED),
            StepResult(step_id="s2", status=StepStatus.SUCCEEDED),
        ]
        index = {"s1": s1, "s2": s2}
        result = execute_rollback(results, index)
        assert result.success is True
        assert s1.rollback_called is False
        assert s2.rollback_called is True

    def test_stops_on_rollback_error(self):
        s1 = FakeRollbackStep("s1")
        s2 = FakeRollbackStep("s2", rollback_error="rollback fail")
        results = [
            StepResult(step_id="s1", status=StepStatus.SUCCEEDED),
            StepResult(step_id="s2", status=StepStatus.SUCCEEDED),
        ]
        index = {"s1": s1, "s2": s2}
        result = execute_rollback(results, index)
        assert result.success is False
        assert s2.rollback_called is True
        assert s1.rollback_called is False  # stops after s2 fails

    def test_empty_steps(self):
        result = execute_rollback([], {})
        assert result.success is True


class TestOrchestrator:
    def test_full_success(self):
        orch = new_orchestrator()
        plan = StagePlan(
            prepare=[FakeStep("p1")],
            apply=[FakeStep("a1")],
        )
        result = orch.execute(plan)
        assert result.error == ""
        assert result.prepare.success is True
        assert result.apply.success is True
        assert result.rollback.success is True

    def test_prepare_failure_stops(self):
        orch = new_orchestrator()
        plan = StagePlan(
            prepare=[FakeStep("p1", "fail")],
            apply=[FakeStep("a1")],
        )
        result = orch.execute(plan)
        assert result.error == "fail"
        assert result.prepare.success is False

    def test_apply_failure_triggers_rollback(self):
        rb1 = FakeRollbackStep("a1")  # succeeds
        rb2 = FakeRollbackStep("a2", run_error="apply fail")  # fails
        plan = StagePlan(
            prepare=[FakeStep("p1")],
            apply=[rb1, rb2],
        )
        orch = new_orchestrator()
        result = orch.execute(plan)
        assert result.apply.success is False
        assert rb1.rollback_called is True  # succeeded step gets rolled back
        assert rb2.rollback_called is False  # failed step is not rolled back
        assert result.rollback.success is True

    def test_apply_failure_no_rollback_when_disabled(self):
        rb = FakeRollbackStep("a1", run_error="apply fail")
        plan = StagePlan(
            prepare=[FakeStep("p1")],
            apply=[rb],
        )
        policy = RollbackPolicy(on_apply_failure=False)
        orch = new_orchestrator(policy=policy)
        result = orch.execute(plan)
        assert result.apply.success is False
        assert rb.rollback_called is False
        assert result.error == "apply fail"


class TestWithFailurePolicy:
    def test_applies_policy(self):
        policy = FailurePolicy.CONTINUE_ON_ERROR
        orch = new_orchestrator(opts=[with_failure_policy(policy)])
        assert orch.runner.failure_policy == FailurePolicy.CONTINUE_ON_ERROR


class TestWithProgressFunc:
    def test_registers_callback(self):
        events: list = []
        orch = new_orchestrator(opts=[with_progress_func(events.append)])
        assert orch.runner.on_progress is not None
        orch.runner.on_progress(ProgressEvent(step_id="test"))
        assert len(events) == 1


class TestExecuteCommand:
    def test_not_found(self):
        err = execute_command("nonexistent-command-12345")
        assert err is not None
        assert "not found" in err

    def test_failure_exit_code(self):
        err = execute_command("python3", "-c", "exit(1)")
        assert err is not None
        assert "exited with code" in err

    def test_captured_output_on_failure(self):
        prev = set_command_streaming(False)
        try:
            err = execute_command("python3", "-c", "import sys; sys.exit(1)")
            assert err is not None
        finally:
            prev()

    def test_success(self):
        err = execute_command("python3", "-c", "")
        assert err is None


class TestRunCommandSequence:
    def test_all_succeed(self):
        err = run_command_sequence(
            [
                ["python3", "-c", "pass"],
                ["python3", "-c", "x=1"],
            ]
        )
        assert err is None

    def test_first_fails(self):
        err = run_command_sequence(
            [
                ["python3", "-c", "exit(1)"],
                ["python3", "-c", "pass"],
            ]
        )
        assert err is not None
        assert "exited with code" in err

    def test_empty_sequence(self):
        err = run_command_sequence([])
        assert err == "empty command sequence"

    def test_empty_command(self):
        err = run_command_sequence([[]])
        assert err == "empty command in sequence"


class TestResolveComponentInstall:
    def test_engram_brew(self):
        class BrewProfile:
            package_manager = "brew"

        cmds = resolve_component_install(BrewProfile(), "DXRK_MEMORY")
        assert len(cmds) == 2
        assert cmds[0] == ["brew", "tap", "Dxrk777/homebrew-tap"]
        assert cmds[1] == ["brew", "install", "DXRK_MEMORY"]

    def test_engram_go(self):
        class LinuxProfile:
            package_manager = "apt"
            os = "linux"

        cmds = resolve_component_install(LinuxProfile(), "DXRK_MEMORY")
        assert len(cmds) == 1
        assert "go" in cmds[0][0]

    def test_gga_brew(self):
        class BrewProfile:
            package_manager = "brew"

        cmds = resolve_component_install(BrewProfile(), "DXRK_GUARDIAN")
        assert len(cmds) == 1
        assert cmds[0] == ["brew", "install", "DXRK_GUARDIAN"]

    def test_unknown_component(self):
        class AnyProfile:
            package_manager = "brew"

        from dxrk.models import ComponentID

        cmds = resolve_component_install(AnyProfile(), ComponentID.SKILLS)
        assert cmds == []

    def test_uses_component_id_enum(self):
        from dxrk.models import ComponentID

        class BrewProfile:
            package_manager = "brew"

        cmds = resolve_component_install(BrewProfile(), ComponentID.DXRK_MEMORY)
        assert len(cmds) == 2


class TestStageResult:
    def test_defaults(self):
        r = StageResult()
        assert r.stage == Stage.PREPARE
        assert r.steps == []
        assert r.success is True
        assert r.error == ""


class TestExecutionResult:
    def test_defaults(self):
        r = ExecutionResult()
        assert r.error == ""


class TestSetCommandStreaming:
    def test_toggles_and_restores(self):
        restore = set_command_streaming(False)
        restore()  # restores to True
        restore = set_command_streaming(True)
        # No crash, streaming restored correctly
