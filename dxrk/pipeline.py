# SPDX-License-Identifier: MIT
"""
Install pipeline.

Orchestrator → Runner → Steps with rollback support.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from typing import Any

from dxrk.models import Selection

log = logging.getLogger(__name__)


# ─── Stage ──────────────────────────────────────────────────────────────────


class Stage(StrEnum):
    PREPARE = "prepare"
    APPLY = "apply"
    ROLLBACK = "rollback"


# ─── Step Status ────────────────────────────────────────────────────────────


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled-back"
    SKIPPED = "skipped"


# ─── Failure Policy ─────────────────────────────────────────────────────────


class FailurePolicy(int, Enum):
    STOP_ON_ERROR = 0
    CONTINUE_ON_ERROR = 1


StopOnError = FailurePolicy.STOP_ON_ERROR
ContinueOnError = FailurePolicy.CONTINUE_ON_ERROR


# ─── Step Interfaces ────────────────────────────────────────────────────────


class Step(ABC):
    @abstractmethod
    def id(self) -> str: ...

    @abstractmethod
    def run(self) -> str | None: ...


class RollbackStep(Step):
    @abstractmethod
    def rollback(self) -> str | None: ...


# ─── Progress ───────────────────────────────────────────────────────────────


@dataclass
class ProgressEvent:
    step_id: str = ""
    stage: Stage = Stage.PREPARE
    status: StepStatus = StepStatus.PENDING
    error: str = ""


ProgressFunc = Callable[[ProgressEvent], None]


# ─── Stage Plan ─────────────────────────────────────────────────────────────


@dataclass
class StagePlan:
    prepare: list[Step] = field(default_factory=list)
    apply: list[Step] = field(default_factory=list)


# ─── Results ────────────────────────────────────────────────────────────────


@dataclass
class StepResult:
    step_id: str = ""
    status: StepStatus = StepStatus.PENDING
    started_at: str = ""
    finished_at: str = ""
    error: str = ""


@dataclass
class StageResult:
    stage: Stage = Stage.PREPARE
    steps: list[StepResult] = field(default_factory=list)
    success: bool = True
    error: str = ""


@dataclass
class ExecutionResult:
    prepare: StageResult = field(default_factory=StageResult)
    apply: StageResult = field(default_factory=StageResult)
    rollback: StageResult = field(default_factory=StageResult)
    error: str = ""


# ─── Rollback Policy ───────────────────────────────────────────────────────


@dataclass
class RollbackPolicy:
    on_apply_failure: bool = True

    def should_rollback(self, stage: Stage, error: str | None) -> bool:
        if not error:
            return False
        return stage == Stage.APPLY and self.on_apply_failure


def default_rollback_policy() -> RollbackPolicy:
    return RollbackPolicy(on_apply_failure=True)


def execute_rollback(
    steps: list[StepResult], step_index: dict[str, Step]
) -> StageResult:
    result = StageResult(stage=Stage.ROLLBACK, success=True)

    for i in range(len(steps) - 1, -1, -1):
        step_result = steps[i]
        if step_result.status != StepStatus.SUCCEEDED:
            continue

        step = step_index.get(step_result.step_id)
        if step is None:
            continue

        rollback_step = step if isinstance(step, RollbackStep) else None
        if rollback_step is None:
            continue

        err = rollback_step.rollback()
        item = StepResult(step_id=rollback_step.id(), status=StepStatus.ROLLED_BACK)
        if err:
            item.status = StepStatus.FAILED
            item.error = err
            result.steps.append(item)
            result.success = False
            result.error = f"rollback step {rollback_step.id()!r}: {err}"
            return result

        result.steps.append(item)

    return result


# ─── Runner ─────────────────────────────────────────────────────────────────


class Runner:
    def __init__(
        self,
        failure_policy: FailurePolicy = FailurePolicy.STOP_ON_ERROR,
        on_progress: ProgressFunc | None = None,
    ):
        self.failure_policy = failure_policy
        self.on_progress = on_progress

    def run(self, stage: Stage, steps: list[Step]) -> StageResult:
        result = StageResult(stage=stage, success=True, steps=[])
        errs: list[str] = []

        for step in steps:
            self._emit(
                ProgressEvent(
                    step_id=step.id(),
                    stage=stage,
                    status=StepStatus.RUNNING,
                )
            )

            started = datetime.now(UTC).isoformat()
            err = step.run()
            finished = datetime.now(UTC).isoformat()

            step_result = StepResult(
                step_id=step.id(),
                started_at=started,
                finished_at=finished,
            )

            if err:
                step_result.status = StepStatus.FAILED
                step_result.error = err
                result.steps.append(step_result)
                self._emit(
                    ProgressEvent(
                        step_id=step.id(),
                        stage=stage,
                        status=StepStatus.FAILED,
                        error=err,
                    )
                )
                errs.append(err)
                result.success = False

                if self.failure_policy == FailurePolicy.STOP_ON_ERROR:
                    result.error = err
                    return result
                continue

            step_result.status = StepStatus.SUCCEEDED
            result.steps.append(step_result)
            self._emit(
                ProgressEvent(
                    step_id=step.id(),
                    stage=stage,
                    status=StepStatus.SUCCEEDED,
                )
            )

        if errs:
            result.error = "; ".join(errs)
        return result

    def _emit(self, event: ProgressEvent) -> None:
        if self.on_progress:
            self.on_progress(event)


# ─── Orchestrator ───────────────────────────────────────────────────────────

OrchestratorOption = Callable[["Orchestrator"], None]


def with_failure_policy(policy: FailurePolicy) -> OrchestratorOption:
    def apply(o: Orchestrator) -> None:
        o.runner.failure_policy = policy

    return apply


def with_progress_func(fn: ProgressFunc) -> OrchestratorOption:
    def apply(o: Orchestrator) -> None:
        o.runner.on_progress = fn

    return apply


class Orchestrator:
    def __init__(
        self,
        policy: RollbackPolicy | None = None,
        opts: list[OrchestratorOption] | None = None,
    ):
        self.runner = Runner()
        self.policy = policy or default_rollback_policy()
        self._step_by_id: dict[str, Step] = {}

        if opts:
            for opt in opts:
                opt(self)

    def execute(self, plan: StagePlan) -> ExecutionResult:
        self._index_steps(plan.prepare)
        self._index_steps(plan.apply)

        prepare_result = self.runner.run(Stage.PREPARE, plan.prepare)
        if not prepare_result.success:
            return ExecutionResult(prepare=prepare_result, error=prepare_result.error)

        apply_result = self.runner.run(Stage.APPLY, plan.apply)
        result = ExecutionResult(prepare=prepare_result, apply=apply_result)

        if apply_result.success:
            return result

        result.error = apply_result.error
        if self.policy.should_rollback(Stage.APPLY, apply_result.error):
            result.rollback = execute_rollback(apply_result.steps, self._step_by_id)
            if not result.rollback.success:
                result.error = result.rollback.error

        return result

    def _index_steps(self, steps: list[Step]) -> None:
        for step in steps:
            self._step_by_id[step.id()] = step


def new_orchestrator(
    policy: RollbackPolicy | None = None,
    opts: list[OrchestratorOption] | None = None,
) -> Orchestrator:
    return Orchestrator(policy=policy, opts=opts)


# ─── Execute Command ────────────────────────────────────────────────────────

_stream_command_output = True


def set_command_streaming(enabled: bool) -> Callable[[], None]:
    global _stream_command_output
    prev = _stream_command_output
    _stream_command_output = enabled
    return lambda: setattr(sys.modules[__name__], "_stream_command_output", prev)


def execute_command(name: str, *args: str) -> str | None:
    cmd = [name, *args]
    try:
        if _stream_command_output:
            proc = subprocess.run(cmd, check=False)
            if proc.returncode != 0:
                return f"command {cmd!r} exited with code {proc.returncode}"
            return None
        else:
            captured = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if captured.returncode != 0:
                out = captured.stdout.strip() + captured.stderr.strip()
                if out:
                    return f"command {cmd!r} failed:\n{out}"
                return f"command {cmd!r} exited with code {captured.returncode}"
            return None
    except FileNotFoundError:
        return f"command {name!r} not found in PATH"
    except OSError as e:
        return str(e)


def run_command_sequence(commands: list[list[str]]) -> str | None:
    if not commands:
        return "empty command sequence"

    for command in commands:
        if not command:
            return "empty command in sequence"
        err = execute_command(command[0], *command[1:])
        if err:
            return f"run command {' '.join(command)!r}: {err}"
    return None


# ─── Component Install Resolution ───────────────────────────────────────────
# Used by dxrk.components.engram.install_command()


def resolve_component_install(profile: Any, component_id: Any) -> list[list[str]]:
    from dxrk.models import ComponentID

    cid = (
        ComponentID(component_id)
        if not isinstance(component_id, ComponentID)
        else component_id
    )

    if cid == ComponentID.DXRK_MEMORY:
        if profile.package_manager == "brew":
            return [
                ["brew", "tap", "Dxrk777/homebrew-tap"],
                ["brew", "install", "DXRK_MEMORY"],
            ]
        return [
            [
                "go",
                "install",
                "github.com/Dxrk777/engram/cmd/engram@latest",
            ],
        ]

    if cid == ComponentID.DXRK_GUARDIAN:
        if profile.package_manager == "brew":
            return [["brew", "install", "DXRK_GUARDIAN"]]
        if profile.os == "linux":
            return [
                [
                    "bash",
                    "-c",
                    "$(curl -fsSL https://raw.githubusercontent.com/Dxrk777/gentleman-guardian-angel/main/install.sh)",
                ],
            ]
        return [
            [
                "bash",
                "-c",
                "$(curl -fsSL https://raw.githubusercontent.com/gentleman-programming/gga/main/install.sh)",
            ],
        ]

    return []


# ─── run_install_pipeline (async TUI bridge) ────────────────────────────────


async def run_install_pipeline(
    selection: Selection,
    on_progress=None,
) -> bool:
    from dxrk.cli.install import InstallFlags, InstallRuntime, resolve_install_profile
    from dxrk.planner import new_resolver, platform_decision_from_profile
    from dxrk.system import detect

    detection = detect()
    if not detection.system.supported:
        if on_progress:
            await on_progress("Unsupported system", 0)
        return False

    profile = resolve_install_profile(detection)
    resolved = new_resolver().resolve(selection)
    resolved.platform_decision = platform_decision_from_profile(profile)

    if on_progress:
        await on_progress("Building stage plan...", 5)

    from dxrk.cli.install import build_stage_plan, normalize_install_flags

    input_data = normalize_install_flags(
        InstallFlags(
            dry_run=False,
            agents=[a.value for a in selection.agents],
            components=[c.value for c in selection.components],
            persona=selection.persona.value if selection.persona else "gentleman",
            preset=selection.preset.value if selection.preset else "full-gentleman",
        ),
        detection,
    )
    stage_plan = build_stage_plan(input_data.selection, resolved)

    if on_progress:
        await on_progress(f"Installing {len(selection.agents)} agent(s)...", 10)

    try:
        rt = InstallRuntime(
            os.path.expanduser("~"),
            os.getcwd(),
            input_data.selection,
            resolved,
            profile,
        )
    except Exception as e:
        if on_progress:
            await on_progress(f"Runtime error: {e}", 0)
        return False

    stage_plan = rt.stage_plan()
    total = len(stage_plan.prepare) + len(stage_plan.apply) or 1
    completed = [0]

    def cb(event: ProgressEvent) -> None:
        completed[0] += 1
        if on_progress:
            import asyncio

            asyncio.ensure_future(
                on_progress(event.step_id, 10 + 70 * completed[0] / total)
            )

    from dxrk.pipeline import default_rollback_policy, new_orchestrator

    orch = new_orchestrator(default_rollback_policy())
    orch.runner.on_progress = cb

    if on_progress:
        await on_progress("Starting installation...", 10)

    import asyncio

    execution = await asyncio.to_thread(orch.execute, stage_plan)

    if on_progress:
        await on_progress("Verifying...", 80)

    if execution.error:
        if on_progress:
            await on_progress(f"Failed: {execution.error}", 0)
        return False

    if on_progress:
        await on_progress("Installation complete!", 100)
    return True
