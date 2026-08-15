# SPDX-License-Identifier: MIT
"""Agent-to-agent protocol.

Provides wire protocol types (message envelopes, method constants, handoff/
query/broadcast/share-context/consensus payloads), an AgentNode with peers,
message queue and handler loop, and consensus proposals with majority
resolution.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NewType, Protocol, runtime_checkable

from dxrk.strconst import StrUnknown

# --- Protocol (protocol.go) ---

ProtocolVersion = NewType("ProtocolVersion", str)

Version1 = ProtocolVersion("2.0")

Method = NewType("Method", str)

# Constant aliases (MethodHandoff, MethodQuery, ...)
MethodHandoff = Method("a2a.handoff")
MethodQuery = Method("a2a.query")
MethodResponse = Method("a2a.response")
MethodBroadcast = Method("a2a.broadcast")
MethodConsensusReq = Method("a2a.consensus.request")
MethodConsensusVote = Method("a2a.consensus.vote")
MethodConsensusRes = Method("a2a.consensus.result")
MethodHeartbeat = Method("a2a.heartbeat")
MethodCapabilities = Method("a2a.capabilities")
MethodShareContext = Method("a2a.share_context")


def _payload_to_json(data: dict[str, object]) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _parse_payload(raw: bytes | None, what: str) -> dict[str, object]:
    if raw is None:
        raise ValueError(f"{what}: missing payload")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{what}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{what}: expected JSON object")
    return data


def _require_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"field {key!r} must be a string")
    return value


def _require_bool(data: dict[str, object], key: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"field {key!r} must be a boolean")
    return value


def _optional_str(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"field {key!r} must be a string")
    return value


def _require_strs(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"field {key!r} must be a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"field {key!r} must be a list of strings")
        result.append(item)
    return result


def _optional_raw(data: dict[str, object], key: str) -> bytes | None:
    value = data.get(key)
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


@runtime_checkable
class WireStruct(Protocol):
    """Protocol for types that serialize to the a2a wire format."""

    def to_json(self) -> bytes: ...


@dataclass
class Error:
    code: int
    message: str

    def to_wire(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message}

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> Error:
        return cls(
            code=_require_int(data, "code"), message=_require_str(data, "message")
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> Error:
        return cls.from_wire(_parse_payload(raw, "error"))


def _require_int(data: dict[str, object], key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError(f"field {key!r} must be an integer")
    return value


@dataclass
class Capability:
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "name": self.name,
            "description": self.description,
        }
        if self.tools:
            data["tools"] = self.tools
        if self.models:
            data["models"] = self.models
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> Capability:
        return cls(
            name=_require_str(data, "name"),
            description=_require_str(data, "description"),
            tools=_require_strs(data, "tools"),
            models=_require_strs(data, "models"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> Capability:
        return cls.from_wire(_parse_payload(raw, "capability"))


@dataclass
class Message:
    jsonrpc: ProtocolVersion
    id: str
    method: Method
    params: bytes | None = None
    result: bytes | None = None
    error: Error | None = None

    def to_json(self) -> bytes:
        data: dict[str, object] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
        }
        if self.params is not None:
            data["params"] = json.loads(self.params.decode("utf-8"))
        if self.result is not None:
            data["result"] = json.loads(self.result.decode("utf-8"))
        if self.error is not None:
            data["error"] = json.loads(self.error.to_json().decode("utf-8"))
        return _payload_to_json(data)

    @classmethod
    def from_json(cls, raw: bytes | None) -> Message:
        data = _parse_payload(raw, "message")
        error: Error | None = None
        if data.get("error") is not None:
            error = Error.from_wire(_require_dict(data, "error"))
        return cls(
            jsonrpc=ProtocolVersion(_require_str(data, "jsonrpc")),
            id=_require_str(data, "id"),
            method=Method(_require_str(data, "method")),
            params=_optional_raw(data, "params"),
            result=_optional_raw(data, "result"),
            error=error,
        )


def _require_dict(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"field {key!r} must be an object")
    return value


@dataclass
class HandoffParams:
    from_agent: str
    to_agent: str
    task: str
    context: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task": self.task,
        }
        if self.context is not None:
            data["context"] = json.loads(self.context.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> HandoffParams:
        return cls(
            from_agent=_require_str(data, "from_agent"),
            to_agent=_require_str(data, "to_agent"),
            task=_require_str(data, "task"),
            context=_optional_raw(data, "context"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> HandoffParams:
        return cls.from_wire(_parse_payload(raw, "handoff params"))


@dataclass
class HandoffResult:
    accepted: bool
    message: str = ""
    session_id: str = ""

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {"accepted": self.accepted}
        if self.message:
            data["message"] = self.message
        if self.session_id:
            data["session_id"] = self.session_id
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> HandoffResult:
        return cls(
            accepted=_require_bool(data, "accepted"),
            message=_optional_str(data, "message"),
            session_id=_optional_str(data, "session_id"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> HandoffResult:
        return cls.from_wire(_parse_payload(raw, "handoff result"))


@dataclass
class QueryParams:
    from_agent: str
    query: str
    context: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_agent": self.from_agent,
            "query": self.query,
        }
        if self.context is not None:
            data["context"] = json.loads(self.context.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> QueryParams:
        return cls(
            from_agent=_require_str(data, "from_agent"),
            query=_require_str(data, "query"),
            context=_optional_raw(data, "context"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> QueryParams:
        return cls.from_wire(_parse_payload(raw, "query params"))


@dataclass
class QueryResult:
    answer: str
    data: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {"answer": self.answer}
        if self.data is not None:
            data["data"] = json.loads(self.data.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> QueryResult:
        return cls(
            answer=_require_str(data, "answer"),
            data=_optional_raw(data, "data"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> QueryResult:
        return cls.from_wire(_parse_payload(raw, "query result"))


@dataclass
class BroadcastParams:
    from_agent: str
    topic: str
    payload: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_agent": self.from_agent,
            "topic": self.topic,
        }
        if self.payload is not None:
            data["payload"] = json.loads(self.payload.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> BroadcastParams:
        return cls(
            from_agent=_require_str(data, "from_agent"),
            topic=_require_str(data, "topic"),
            payload=_optional_raw(data, "payload"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> BroadcastParams:
        return cls.from_wire(_parse_payload(raw, "broadcast params"))


@dataclass
class ShareContextParams:
    from_agent: str
    targets: list[str] = field(default_factory=list)
    context: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_agent": self.from_agent,
            "targets": self.targets,
        }
        if self.context is not None:
            data["context"] = json.loads(self.context.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> ShareContextParams:
        return cls(
            from_agent=_require_str(data, "from_agent"),
            targets=_require_strs(data, "targets"),
            context=_optional_raw(data, "context"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> ShareContextParams:
        return cls.from_wire(_parse_payload(raw, "share context params"))


@dataclass
class ConsensusRequest:
    from_agent: str
    proposal_id: str
    proposal: str
    options: list[str] = field(default_factory=list)
    detail: bytes | None = None

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "from_agent": self.from_agent,
            "proposal_id": self.proposal_id,
            "proposal": self.proposal,
            "options": self.options,
        }
        if self.detail is not None:
            data["detail"] = json.loads(self.detail.decode("utf-8"))
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> ConsensusRequest:
        return cls(
            from_agent=_require_str(data, "from_agent"),
            proposal_id=_require_str(data, "proposal_id"),
            proposal=_require_str(data, "proposal"),
            options=_require_strs(data, "options"),
            detail=_optional_raw(data, "detail"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> ConsensusRequest:
        return cls.from_wire(_parse_payload(raw, "consensus request"))


@dataclass
class ConsensusVote:
    agent_id: str
    proposal_id: str
    vote: str
    reason: str = ""

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "agent_id": self.agent_id,
            "proposal_id": self.proposal_id,
            "vote": self.vote,
        }
        if self.reason:
            data["reason"] = self.reason
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> ConsensusVote:
        return cls(
            agent_id=_require_str(data, "agent_id"),
            proposal_id=_require_str(data, "proposal_id"),
            vote=_require_str(data, "vote"),
            reason=_optional_str(data, "reason"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> ConsensusVote:
        return cls.from_wire(_parse_payload(raw, "consensus vote"))


@dataclass
class ConsensusResult:
    proposal_id: str
    decided: bool
    outcome: str
    votes: list[ConsensusVote] = field(default_factory=list)
    summary: str = ""

    def to_wire(self) -> dict[str, object]:
        data: dict[str, object] = {
            "proposal_id": self.proposal_id,
            "decided": self.decided,
            "outcome": self.outcome,
            "votes": [v.to_wire() for v in self.votes],
        }
        if self.summary:
            data["summary"] = self.summary
        return data

    def to_json(self) -> bytes:
        return _payload_to_json(self.to_wire())

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> ConsensusResult:
        votes_raw = data.get("votes")
        if votes_raw is None:
            votes: list[ConsensusVote] = []
        elif isinstance(votes_raw, list):
            votes = []
            for item in votes_raw:
                if not isinstance(item, dict):
                    raise ValueError("field 'votes' must be a list of objects")
                votes.append(ConsensusVote.from_wire(item))
        else:
            raise ValueError("field 'votes' must be a list of objects")
        return cls(
            proposal_id=_require_str(data, "proposal_id"),
            decided=_require_bool(data, "decided"),
            outcome=_require_str(data, "outcome"),
            votes=votes,
            summary=_optional_str(data, "summary"),
        )

    @classmethod
    def from_json(cls, raw: bytes | None) -> ConsensusResult:
        return cls.from_wire(_parse_payload(raw, "consensus result"))


# --- Agent node (agent.go) ---

MessageHandler = Callable[[Message], tuple[WireStruct | None, Exception | None]]

LoggerFn = Callable[[str], None]

_PENDING_LOCK = threading.Lock()
_PENDING: dict[str, queue.Queue[Message]] = {}


class A2AError(Exception):
    """Protocol-level error raised by send/handoff/query/consensus operations."""


class AgentNode:
    def __init__(
        self,
        name: str,
        capabilities: list[Capability],
        handler: MessageHandler | None = None,
        *opts: AgentOption,
    ) -> None:
        self.name = name
        self.capabilities = capabilities
        self._handler = handler if handler is not None else _noop_handler
        self._peers: dict[str, AgentNode] = {}
        self._lock = threading.Lock()
        self._messages: queue.Queue[Message] = queue.Queue(maxsize=100)
        self._stopped = threading.Event()
        self._logger: LoggerFn = lambda _: None
        for opt in opts:
            opt(self)
        self._thread = threading.Thread(
            target=self._message_loop,
            name=f"a2a-{name}",
            daemon=True,
        )
        self._thread.start()

    def add_peer(self, peer: AgentNode) -> None:
        with self._lock:
            self._peers[peer.name] = peer
        self._log("[a2a] %s added peer %s", self.name, peer.name)

    def remove_peer(self, name: str) -> None:
        with self._lock:
            self._peers.pop(name, None)

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def send(self, target: str, msg: Message, timeout: float = 30.0) -> Message:
        with self._lock:
            peer = self._peers.get(target)
        if peer is None:
            raise A2AError(f'peer "{target}" not found')

        ch: queue.Queue[Message] = queue.Queue(maxsize=1)
        with _PENDING_LOCK:
            _PENDING[msg.id] = ch

        try:
            try:
                peer._messages.put_nowait(msg)
            except queue.Full:
                raise A2AError(f'peer "{target}" message buffer full') from None
            try:
                return ch.get(timeout=timeout)
            except queue.Empty:
                raise A2AError(f"timeout waiting for response to {msg.id}") from None
        finally:
            with _PENDING_LOCK:
                _PENDING.pop(msg.id, None)

    def handoff(
        self,
        target: str,
        task: str,
        context_data: object | None = None,
        timeout: float = 30.0,
    ) -> HandoffResult:
        ctx_raw = _body_message(context_data)
        params = HandoffParams(
            from_agent=self.name,
            to_agent=target,
            task=task,
            context=ctx_raw,
        )
        msg = Message(
            jsonrpc=Version1,
            id=str(uuid.uuid4()),
            method=MethodHandoff,
            params=params.to_json(),
        )

        resp = self.send(target, msg, timeout)
        if resp.error is not None:
            raise A2AError(f"handoff error: {resp.error.message}")
        try:
            return HandoffResult.from_json(resp.result)
        except ValueError as exc:
            raise A2AError(f"parse handoff result: {exc}") from exc

    def query(
        self,
        target: str,
        query: str,
        context_data: object | None = None,
        timeout: float = 30.0,
    ) -> QueryResult:
        ctx_raw = _body_message(context_data)
        params = QueryParams(from_agent=self.name, query=query, context=ctx_raw)
        msg = Message(
            jsonrpc=Version1,
            id=str(uuid.uuid4()),
            method=MethodQuery,
            params=params.to_json(),
        )

        resp = self.send(target, msg, timeout)
        if resp.error is not None:
            raise A2AError(f"query error: {resp.error.message}")
        try:
            return QueryResult.from_json(resp.result)
        except ValueError as exc:
            raise A2AError(f"parse query result: {exc}") from exc

    def broadcast(self, topic: str, payload: object | None) -> list[A2AError]:
        params = BroadcastParams(
            from_agent=self.name,
            topic=topic,
            payload=_body_message(payload),
        )
        msg = Message(
            jsonrpc=Version1,
            id=str(uuid.uuid4()),
            method=MethodBroadcast,
            params=params.to_json(),
        )

        with self._lock:
            peers = list(self._peers.values())

        errs: list[A2AError] = []
        for peer in peers:
            try:
                peer._messages.put_nowait(msg)
            except queue.Full:
                errs.append(A2AError(f'peer "{peer.name}" buffer full'))
        return errs

    def share_context(self, targets: list[str], context_data: object | None) -> None:
        params = ShareContextParams(
            from_agent=self.name,
            targets=targets,
            context=_body_message(context_data),
        )
        msg = Message(
            jsonrpc=Version1,
            id=str(uuid.uuid4()),
            method=MethodShareContext,
            params=params.to_json(),
        )

        with self._lock:
            for target in targets:
                peer = self._peers.get(target)
                if peer is None:
                    continue
                try:
                    peer._messages.put_nowait(msg)
                except queue.Full:
                    raise A2AError(f'peer "{target}" buffer full') from None

    def _message_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                msg = self._messages.get(timeout=0.05)
            except queue.Empty:
                continue
            self._handle_message(msg)

    def _handle_message(self, msg: Message) -> None:
        self._log(
            "[a2a] %s received %s from %s",
            self.name,
            msg.method,
            extract_from_agent(msg),
        )

        if msg.method in (
            MethodHandoff,
            MethodQuery,
            MethodBroadcast,
            MethodShareContext,
            MethodConsensusReq,
        ):
            try:
                result, err = self._handler(msg)
            except Exception as exc:  # handler raised instead of returning an error
                result, err = None, exc
            resp = Message(
                jsonrpc=Version1,
                id=msg.id,
                method=MethodResponse,
            )
            if err is not None:
                resp.error = Error(code=-1, message=str(err))
            elif isinstance(result, WireStruct):
                resp.result = result.to_json()
            self._deliver(msg.id, resp)

        elif msg.method in (MethodResponse, MethodConsensusVote, MethodConsensusRes):
            self._deliver(msg.id, msg)

        else:
            self._log("[a2a] %s unknown method: %s", self.name, msg.method)

    @staticmethod
    def _deliver(msg_id: str, resp: Message) -> None:
        with _PENDING_LOCK:
            ch = _PENDING.get(msg_id)
            if ch is None:
                return
            try:
                ch.put_nowait(resp)
            except queue.Full:
                return  # select-default: drop when the waiter already left

    def _log(self, fmt: str, *args: object) -> None:
        self._logger(fmt % args if args else fmt)

    def propose_consensus(
        self,
        targets: list[str],
        proposal_id: str,
        proposal: str,
        options: list[str],
        detail: object | None = None,
        timeout: float = 30.0,
    ) -> ConsensusResult:
        params = ConsensusRequest(
            from_agent=self.name,
            proposal_id=proposal_id,
            proposal=proposal,
            options=options,
            detail=_body_message(detail),
        )
        params_raw = params.to_json()

        with self._lock:
            peers = [p for t in targets if (p := self._peers.get(t)) is not None]

        if not peers:
            raise A2AError("no target peers found")

        votes: list[ConsensusVote] = []
        for peer in peers:
            # Fresh message ID per peer: each send() waits on its own response
            # channel. The original reused one ID for all peers, which
            # races its pending map (responses land on the last-registered
            # channel and silently overwrite earlier waiters).
            msg = Message(
                jsonrpc=Version1,
                id=str(uuid.uuid4()),
                method=MethodConsensusReq,
                params=params_raw,
            )
            try:
                resp = self.send(peer.name, msg, timeout)
            except A2AError:
                continue
            if resp.error is not None:
                continue
            try:
                votes.append(ConsensusVote.from_json(resp.result))
            except ValueError:
                continue

        outcome = resolve_consensus(options, votes)
        return ConsensusResult(
            proposal_id=proposal_id,
            decided=outcome != "",
            outcome=outcome,
            votes=votes,
            summary=(
                f'Consensus on "{proposal}": {outcome} '
                f"({len(votes)}/{len(peers)} votes)"
            ),
        )


def _noop_handler(msg: Message) -> tuple[None, None]:
    return None, None


AgentOption = Callable[[AgentNode], None]


def new_agent_node(
    name: str,
    capabilities: list[Capability],
    handler: MessageHandler | None = None,
    *opts: AgentOption,
) -> AgentNode:
    return AgentNode(name, capabilities, handler, *opts)


def with_agent_logger(log_fn: LoggerFn) -> AgentOption:
    def apply(node: AgentNode) -> None:
        node._logger = log_fn

    return apply


def _body_message(value: object | None) -> bytes | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def extract_from_agent(msg: Message) -> str:
    try:
        if msg.method == MethodHandoff:
            return HandoffParams.from_json(msg.params).from_agent
        if msg.method == MethodQuery:
            return QueryParams.from_json(msg.params).from_agent
        if msg.method == MethodBroadcast:
            return BroadcastParams.from_json(msg.params).from_agent
        if msg.method == MethodShareContext:
            return ShareContextParams.from_json(msg.params).from_agent
        if msg.method == MethodConsensusReq:
            return ConsensusRequest.from_json(msg.params).from_agent
    except ValueError:
        return ""
    return StrUnknown


# --- Consensus (consensus.go) ---


@dataclass
class ConsensusProposal:
    id: str
    proposal: str
    options: list[str] = field(default_factory=list)
    detail: bytes | None = None
    deadline: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class _ActiveProposal:
    proposal: ConsensusProposal
    votes: list[ConsensusVote] = field(default_factory=list)
    from_agent: str = ""  # field `from` (keyword in Python)
    decided: bool = False


class ConsensusState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proposals: dict[str, _ActiveProposal] = {}

    def get(self, proposal_id: str) -> _ActiveProposal | None:
        with self._lock:
            return self._proposals.get(proposal_id)


def new_consensus_state() -> ConsensusState:
    return ConsensusState()


def resolve_consensus(options: list[str], votes: list[ConsensusVote]) -> str:
    if not votes:
        return ""

    counts: dict[str, int] = {}
    for v in votes:
        counts[v.vote] = counts.get(v.vote, 0) + 1

    majority = len(votes) // 2 + 1
    for opt in options:
        if counts.get(opt, 0) >= majority:
            return opt
    return ""


def handle_consensus_request(
    msg: Message, state: ConsensusState, agent_name: str
) -> tuple[WireStruct | None, Exception | None]:
    try:
        req = ConsensusRequest.from_json(msg.params)
    except ValueError as exc:
        return None, ValueError(f"parse consensus request: {exc}")

    proposal = ConsensusProposal(
        id=req.proposal_id,
        proposal=req.proposal,
        options=req.options,
        detail=req.detail,
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    with state._lock:
        state._proposals[req.proposal_id] = _ActiveProposal(
            proposal=proposal,
            from_agent=req.from_agent,
        )

    vote = ConsensusVote(
        agent_id=agent_name,
        proposal_id=req.proposal_id,
        vote=req.options[0],
        reason="auto-accepted",
    )
    return vote, None
