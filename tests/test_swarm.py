# SPDX-License-Identifier: MIT
"""Tests for Swarm Multi-Agent Orchestrator."""

from dxrk.autonomy import (
    AgentRole,
    NewSwarmOrchestrator,
    SwarmOrchestrator,
    SwarmResult,
    SwarmTask,
)


def test_swarm_registration_and_execution():
    orchestrator = NewSwarmOrchestrator(max_workers=2)

    def coder_handler(task: SwarmTask) -> SwarmResult:
        return SwarmResult(
            task_id=task.task_id,
            role=task.role,
            success=True,
            output=f"Executed code generation for {task.description}",
        )

    orchestrator.register_agent(AgentRole.CODER, coder_handler)

    task = SwarmTask(
        task_id="t1",
        description="Implement user auth module",
        role=AgentRole.CODER,
    )

    result = orchestrator.execute_task(task)
    assert result.success is True
    assert result.task_id == "t1"
    assert "user auth module" in result.output


def test_swarm_unregistered_agent():
    orchestrator = SwarmOrchestrator()
    task = SwarmTask(
        task_id="t2",
        description="Run security audit",
        role=AgentRole.SECURITY_AUDITOR,
    )
    result = orchestrator.execute_task(task)
    assert result.success is False
    assert len(result.errors) > 0
    assert "No agent registered" in result.errors[0]


def test_swarm_empty_task_list():
    orchestrator = NewSwarmOrchestrator()
    results = orchestrator.execute_swarm([])
    assert results == []

    passed, ratio, summary = orchestrator.consensus_check([])
    assert passed is True
    assert ratio == 1.0
    assert "No results" in summary


def test_swarm_agent_exception_handled():
    orchestrator = NewSwarmOrchestrator()

    def failing_handler(task: SwarmTask) -> SwarmResult:
        raise RuntimeError("boom")

    orchestrator.register_agent(AgentRole.CODER, failing_handler)
    result = orchestrator.execute_task(SwarmTask("t5", "Explode", AgentRole.CODER))
    assert result.success is False
    assert "Agent execution error" in result.errors[0]
    assert "boom" in result.errors[0]


def test_parallel_swarm_execution_and_consensus():
    orchestrator = NewSwarmOrchestrator(max_workers=4)

    def general_handler(task: SwarmTask) -> SwarmResult:
        is_success = task.inputs.get("pass", True)
        return SwarmResult(
            task_id=task.task_id,
            role=task.role,
            success=is_success,
            output=f"Output for {task.task_id}",
        )

    for role in AgentRole:
        orchestrator.register_agent(role, general_handler)

    tasks = [
        SwarmTask("t1", "Task 1", AgentRole.ARCHITECT, inputs={"pass": True}),
        SwarmTask("t2", "Task 2", AgentRole.CODER, inputs={"pass": True}),
        SwarmTask("t3", "Task 3", AgentRole.TESTER, inputs={"pass": True}),
        SwarmTask("t4", "Task 4", AgentRole.REVIEWER, inputs={"pass": False}),
    ]

    results = orchestrator.execute_swarm(tasks)
    assert len(results) == 4

    passed, ratio, summary = orchestrator.consensus_check(results)
    assert passed is True
    assert ratio == 0.75
    assert "3/4 passed" in summary


def test_consensus_below_threshold_fails():
    orchestrator = NewSwarmOrchestrator()

    def flaky_handler(task: SwarmTask) -> SwarmResult:
        return SwarmResult(
            task_id=task.task_id,
            role=task.role,
            success=False,
            output="",
            errors=["failed"],
        )

    orchestrator.register_agent(AgentRole.CODER, flaky_handler)
    results = orchestrator.execute_swarm([SwarmTask("t1", "A", AgentRole.CODER) for _ in range(4)])
    passed, ratio, summary = orchestrator.consensus_check(results)
    assert passed is False
    assert ratio == 0.0
