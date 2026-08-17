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

    def __init__(self, max_workers: int = 5) -> None:
        self.max_workers = max_workers
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

    def execute_swarm(self, tasks: list[SwarmTask]) -> list[SwarmResult]:
        """Execute multiple swarm tasks in parallel across worker threads."""
        if not tasks:
            return []

        results: list[SwarmResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_task = {executor.submit(self.execute_task, task): task for task in tasks}
            for future in concurrent.futures.as_completed(future_to_task):
                results.append(future.result())
        return results

    def consensus_check(self, results: list[SwarmResult]) -> tuple[bool, float, str]:
        """Check consensus among swarm task results.

        Returns (pass_status, consensus_ratio, summary).
        """
        if not results:
            return True, 1.0, "No results to evaluate"

        successful = [r for r in results if r.success]
        ratio = len(successful) / len(results)
        passed = ratio >= 0.75

        summary = f"Swarm consensus: {len(successful)}/{len(results)} passed ({ratio * 100:.1f}%)"
        return passed, ratio, summary


def NewSwarmOrchestrator(max_workers: int = 5) -> SwarmOrchestrator:
    """Factory helper to instantiate a new SwarmOrchestrator."""
    return SwarmOrchestrator(max_workers=max_workers)
