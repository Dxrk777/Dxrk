# SPDX-License-Identifier: MIT
"""Swarm Multi-Agent Orchestrator: parallel delegation and consensus execution."""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentRole(StrEnum):
    """Roles assigned to agents in a multi-agent swarm task."""

    ARCHITECT = "architect"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"
    SECURITY_AUDITOR = "security_auditor"


@dataclass
class SwarmTask:
    """Task delegated to a swarm agent."""

    task_id: str
    description: str
    role: AgentRole
    inputs: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""


@dataclass
class SwarmResult:
    """Result returned by a swarm agent task execution."""

    task_id: str
    role: AgentRole
    success: bool
    output: str
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


AgentHandler = Callable[[SwarmTask], SwarmResult]


class SwarmOrchestrator:
    """Orchestrates parallel multi-agent swarm workflows and consensus evaluation."""

    def __init__(self, max_workers: int = 5, consensus_threshold: float = 0.75) -> None:
        if not 0.0 <= consensus_threshold <= 1.0:
            raise ValueError("consensus_threshold must be in [0.0, 1.0]")
        self.max_workers = max_workers
        self.consensus_threshold = consensus_threshold
        self._agent_handlers: dict[AgentRole, AgentHandler] = {}

    def register_agent(self, role: AgentRole, handler: AgentHandler) -> None:
        """Register a handler for a specific agent role."""
        self._agent_handlers[role] = handler

    def execute_task(self, task: SwarmTask) -> SwarmResult:
        """Execute a single swarm task using the registered role handler."""
        handler = self._agent_handlers.get(task.role)
        if not handler:
            return SwarmResult(
                task_id=task.task_id,
                role=task.role,
                success=False,
                output="",
                errors=[f"No agent registered for role: {task.role}"],
            )
        try:
            return handler(task)
        except Exception as exc:
            return SwarmResult(
                task_id=task.task_id,
                role=task.role,
                success=False,
                output="",
                errors=[f"Agent execution error: {exc}"],
            )

    def execute_swarm(self, tasks: list[SwarmTask], timeout: float | None = None) -> list[SwarmResult]:
        """Execute multiple swarm tasks in parallel across worker threads.

        Results are returned in input order (``results[i]`` corresponds to
        ``tasks[i]``). ``timeout`` is a per-task limit in seconds; a task
        that exceeds it completes as a failure with a ``task timed out``
        error instead of blocking the batch.
        """
        if not tasks:
            return []

        results: list[SwarmResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self.execute_task, task) for task in tasks]
            for task, future in zip(tasks, futures, strict=True):
                try:
                    results.append(future.result(timeout=timeout))
                except concurrent.futures.TimeoutError:
                    results.append(
                        SwarmResult(
                            task_id=task.task_id,
                            role=task.role,
                            success=False,
                            output="",
                            errors=[f"task timed out after {timeout}s"],
                        )
                    )
        return results

    def consensus_check(self, results: list[SwarmResult], threshold: float | None = None) -> tuple[bool, float, str]:
        """Check consensus among swarm task results.

        Returns (pass_status, consensus_ratio, summary). An empty result
        set is an explicit empty verdict — it does NOT pass.
        """
        if not results:
            return False, 0.0, "Swarm consensus: empty — no results to evaluate"

        effective = self.consensus_threshold if threshold is None else threshold
        successful = [r for r in results if r.success]
        ratio = len(successful) / len(results)
        passed = ratio >= effective

        summary = f"Swarm consensus: {len(successful)}/{len(results)} passed ({ratio * 100:.1f}%)"
        return passed, ratio, summary


def NewSwarmOrchestrator(max_workers: int = 5, consensus_threshold: float = 0.75) -> SwarmOrchestrator:
    """Factory helper to instantiate a new SwarmOrchestrator."""
    return SwarmOrchestrator(max_workers=max_workers, consensus_threshold=consensus_threshold)
