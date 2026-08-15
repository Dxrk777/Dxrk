# SPDX-License-Identifier: MIT
from __future__ import annotations

import queue

import pytest

from dxrk.a2a import (
    A2AError,
    Capability,
    ConsensusState,
    HandoffParams,
    HandoffResult,
    Message,
    MessageHandler,
    MethodConsensusReq,
    MethodQuery,
    QueryParams,
    QueryResult,
    Version1,
    WireStruct,
    handle_consensus_request,
    new_agent_node,
    new_consensus_state,
)


def _handoff_handler(msg: Message) -> tuple[WireStruct | None, Exception | None]:
    params = HandoffParams.from_json(msg.params)
    if params.task == "delegate":
        return HandoffResult(accepted=True, session_id="sess-1"), None
    return HandoffResult(accepted=False, message="unknown task"), None


def test_agent_handoff() -> None:
    a1 = new_agent_node("agent-a", [], _handoff_handler)
    a2 = new_agent_node("agent-b", [], _handoff_handler)
    try:
        a1.add_peer(a2)
        a2.add_peer(a1)

        result = a1.handoff("agent-b", "delegate")
        assert result.accepted
        assert result.session_id == "sess-1"
    finally:
        a1.stop()
        a2.stop()


def test_agent_handoff_rejected() -> None:
    def handler(msg: Message) -> tuple[WireStruct | None, Exception | None]:
        return HandoffResult(accepted=False, message="busy"), None

    a1 = new_agent_node("agent-a", [], handler)
    a2 = new_agent_node("agent-b", [], handler)
    try:
        a1.add_peer(a2)
        a2.add_peer(a1)

        result = a1.handoff("agent-b", "task")
        assert not result.accepted
        assert result.message == "busy"
    finally:
        a1.stop()
        a2.stop()


def test_agent_query() -> None:
    def handler(msg: Message) -> tuple[WireStruct | None, Exception | None]:
        params = QueryParams.from_json(msg.params)
        return QueryResult(answer=f"answer: {params.query}"), None

    a1 = new_agent_node("agent-a", [], handler)
    a2 = new_agent_node("agent-b", [], handler)
    try:
        a1.add_peer(a2)
        a2.add_peer(a1)

        result = a1.query("agent-b", "what is 2+2?")
        assert result.answer == "answer: what is 2+2?"
    finally:
        a1.stop()
        a2.stop()


def _consensus_handler_factory(state: ConsensusState, agent: str) -> MessageHandler:
    def handler(msg: Message) -> tuple[WireStruct | None, Exception | None]:
        if msg.method == MethodConsensusReq:
            return handle_consensus_request(msg, state, agent)
        return None, None

    return handler


def test_agent_consensus() -> None:
    state = new_consensus_state()
    a1 = new_agent_node("agent-a", [], _consensus_handler_factory(state, "agent-a"))
    a2 = new_agent_node("agent-b", [], _consensus_handler_factory(state, "agent-b"))
    a3 = new_agent_node("agent-c", [], _consensus_handler_factory(state, "agent-c"))
    try:
        a1.add_peer(a2)
        a1.add_peer(a3)
        a2.add_peer(a1)
        a3.add_peer(a1)

        result = a1.propose_consensus(
            ["agent-b", "agent-c"],
            "prop-1",
            "Which model to use?",
            ["gpt-4o", "claude-sonnet-4"],
        )
        assert result.decided
        assert result.outcome == "gpt-4o"
        assert len(result.votes) == 2
        assert result.proposal_id == "prop-1"
    finally:
        a1.stop()
        a2.stop()
        a3.stop()


def test_agent_broadcast() -> None:
    received: queue.Queue[str] = queue.Queue()

    a1 = new_agent_node("agent-a", [], lambda msg: (received.put("a1"), None))
    a2 = new_agent_node("agent-b", [], lambda msg: (received.put("a2"), None))
    try:
        a1.add_peer(a2)
        a2.add_peer(a1)

        errs = a1.broadcast("announcement", "hello everyone")
        assert errs == []
        assert received.get(timeout=5) == "a2"
    finally:
        a1.stop()
        a2.stop()


def test_agent_share_context() -> None:
    received: queue.Queue[str] = queue.Queue()

    a1 = new_agent_node("agent-a", [], lambda msg: (None, None))
    a2 = new_agent_node("agent-b", [], lambda msg: (received.put("shared"), None))
    try:
        a1.add_peer(a2)
        a2.add_peer(a1)

        a1.share_context(["agent-b"], {"key": "value"})
        assert received.get(timeout=5) == "shared"
    finally:
        a1.stop()
        a2.stop()


def test_agent_capabilities() -> None:
    caps = [
        Capability(name="coding", description="write code", tools=["sandbox_run_code"]),
        Capability(name="research", description="search web", tools=["web_search"]),
    ]
    a = new_agent_node("agent-a", caps)
    try:
        assert len(a.capabilities) == 2
        assert a.capabilities[0].name == "coding"
    finally:
        a.stop()


def test_send_peer_not_found() -> None:
    a1 = new_agent_node("agent-a", [], lambda msg: (None, None))
    try:
        with pytest.raises(A2AError, match='peer "agent-b" not found'):
            a1.send("agent-b", Message(jsonrpc=Version1, id="m-1", method=MethodQuery))
    finally:
        a1.stop()
