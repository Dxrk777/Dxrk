# SPDX-License-Identifier: MIT
"""Agent coordinator"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class CoordinatorError(Exception):
    pass


class TeamNotFoundError(CoordinatorError):
    pass


class AgentNotFoundError(CoordinatorError):
    pass


class ScratchpadKeyError(CoordinatorError, KeyError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- Modes and statuses (coordinator.go) ---


class CoordinatorMode(StrEnum):
    """Operating mode for multi-agent orchestration."""

    ModeSingleAgent = "single_agent"
    ModeCoordinator = "coordinator"
    ModeWorker = "worker"
    ModeUnknown = "unknown"

    def String(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


class AgentStatus(StrEnum):
    """Current state of a worker agent."""

    AgentIdle = "idle"
    AgentBusy = "busy"
    AgentFailed = "failed"
    AgentDone = "done"
    AgentUnknown = "unknown"

    def String(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


# --- Data types (coordinator.go) ---


@dataclass
class ScratchpadEntry:
    """Shared context item between agents."""

    key: str
    value: str
    set_by: str
    created_at: datetime
    updated_at: datetime


@dataclass
class CoordinatorConfig:
    """Configuration for the multi-agent system."""

    mode: CoordinatorMode = CoordinatorMode.ModeSingleAgent
    max_workers: int = 8
    scratchpad_limit: int = 100
    agent_timeout: timedelta = timedelta(minutes=30)
    context_window: int = 128000


def default_coordinator_config() -> CoordinatorConfig:
    return CoordinatorConfig()


@dataclass
class AgentResult:
    """Output from a worker agent."""

    agent_id: str
    output: str = ""
    error: str = ""
    duration: timedelta = timedelta(0)


@dataclass
class Message:
    """Inter-agent message."""

    from_: str
    to: str
    content: str
    timestamp: datetime


# --- Worker (worker.go) ---


@dataclass
class Worker:
    """A single agent worker."""

    id: str
    status: AgentStatus = AgentStatus.AgentIdle
    task: str = ""
    result: AgentResult | None = None
    created_at: datetime = field(default_factory=_utcnow)
    started_at: datetime | None = None
    done_at: datetime | None = None
    cancel: Callable[[], None] | None = None
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    def assign_task(self, task: str) -> None:
        with self._lock:
            self.status = AgentStatus.AgentBusy
            self.task = task
            self.started_at = _utcnow()

    def complete(self, output: str) -> None:
        with self._lock:
            if self.started_at is None:
                raise ValueError(f"worker {self.id!r} has no started task")
            now = _utcnow()
            self.done_at = now
            self.status = AgentStatus.AgentDone
            self.result = AgentResult(
                agent_id=self.id,
                output=output,
                duration=now - self.started_at,
            )

    def fail(self, error: str) -> None:
        with self._lock:
            if self.started_at is None:
                raise ValueError(f"worker {self.id!r} has no started task")
            now = _utcnow()
            self.done_at = now
            self.status = AgentStatus.AgentFailed
            self.result = AgentResult(
                agent_id=self.id,
                error=error,
                duration=now - self.started_at,
            )

    def reset(self) -> None:
        with self._lock:
            self.status = AgentStatus.AgentIdle
            self.task = ""
            self.result = None
            self.started_at = None
            self.done_at = None

    def stop(self) -> None:
        with self._lock:
            if self.cancel is not None:
                self.cancel()
            if self.status == AgentStatus.AgentBusy:
                self.fail("stopped by coordinator")

    def is_idle(self) -> bool:
        with self._lock:
            return self.status == AgentStatus.AgentIdle

    def get_status(self) -> AgentStatus:
        with self._lock:
            return self.status

    def get_result(self) -> AgentResult | None:
        with self._lock:
            return self.result


def new_worker(worker_id: str) -> Worker:
    return Worker(id=worker_id)


# --- Team (team.go) ---


@dataclass
class Team:
    """A group of worker agents."""

    name: str
    members: list[Worker] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, repr=False, compare=False
    )

    def route_message(self, from_: str, to: str, content: str) -> None:
        with self._lock:
            if not self._is_member(from_):
                raise AgentNotFoundError(
                    f"agent {from_!r} is not a member of team {self.name!r}"
                )
            if to != "all" and not self._is_member(to):
                raise AgentNotFoundError(
                    f"agent {to!r} is not a member of team {self.name!r}"
                )
            self.messages.append(
                Message(from_=from_, to=to, content=content, timestamp=_utcnow())
            )

    def broadcast(self, from_: str, content: str) -> None:
        self.route_message(from_, "all", content)

    def get_member(self, worker_id: str) -> Worker:
        with self._lock:
            for member in self.members:
                if member.id == worker_id:
                    return member
        raise AgentNotFoundError(f"agent {worker_id!r} not found in team {self.name!r}")

    def member_ids(self) -> list[str]:
        with self._lock:
            return [member.id for member in self.members]

    def member_statuses(self) -> dict[str, str]:
        with self._lock:
            return {member.id: member.status.String() for member in self.members}

    def recent_messages(self, n: int) -> list[Message]:
        with self._lock:
            if not self.messages or n <= 0:
                return []
            return list(self.messages[-n:])

    def message_count(self) -> int:
        with self._lock:
            return len(self.messages)

    def _is_member(self, worker_id: str) -> bool:
        for member in self.members:
            if member.id == worker_id:
                return True
        return False


def new_team(name: str, member_ids: list[str]) -> Team:
    return Team(name=name, members=[new_worker(mid) for mid in member_ids])


# --- Coordinator (coordinator.go) ---


class Coordinator:
    """Manages multi-agent orchestration."""

    def __init__(self, config: CoordinatorConfig):
        self._config = config
        self._teams: dict[str, Team] = {}
        self._scratchpad: dict[str, ScratchpadEntry] = {}
        self._workers: dict[str, Worker] = {}
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

    def create_team(self, name: str, members: list[str]) -> Team:
        with self._lock:
            if name in self._teams:
                raise ValueError(f"team {name!r} already exists")
            if not members:
                raise ValueError("team must have at least one member")
            team = new_team(name, members)
            self._teams[name] = team
            return team

    def delete_team(self, name: str) -> None:
        with self._lock:
            team = self._teams.get(name)
            if team is None:
                raise TeamNotFoundError(f"team {name!r} not found")
            with team._lock:
                for member in team.members:
                    member.status = AgentStatus.AgentDone
            del self._teams[name]

    def send_message(
        self, team_name: str, from_agent: str, to_agent: str, message_text: str
    ) -> None:
        with self._lock:
            team = self._require_team(team_name)
            team.route_message(from_agent, to_agent, message_text)

    def broadcast_message(
        self, team_name: str, from_agent: str, message_text: str
    ) -> None:
        with self._lock:
            team = self._require_team(team_name)
            team.broadcast(from_agent, message_text)

    def set_scratchpad(self, key: str, value: str, set_by: str) -> None:
        with self._lock:
            if len(self._scratchpad) >= self._config.scratchpad_limit:
                if self._scratchpad:
                    oldest_key = min(
                        self._scratchpad,
                        key=lambda k: self._scratchpad[k].created_at,
                    )
                    del self._scratchpad[oldest_key]
            now = _utcnow()
            entry = self._scratchpad.get(key)
            if entry is not None:
                entry.value = value
                entry.set_by = set_by
                entry.updated_at = now
            else:
                self._scratchpad[key] = ScratchpadEntry(
                    key=key,
                    value=value,
                    set_by=set_by,
                    created_at=now,
                    updated_at=now,
                )

    def get_scratchpad(self, key: str) -> ScratchpadEntry:
        with self._lock:
            entry = self._scratchpad.get(key)
            if entry is None:
                raise ScratchpadKeyError(f"scratchpad key {key!r} not found")
            return entry

    def get_all_scratchpad(self) -> dict[str, ScratchpadEntry]:
        with self._lock:
            return dict(self._scratchpad)

    def delegate_work(self, team_name: str, task: str) -> Worker:
        """Assigns a task to an available worker in a team."""
        with self._lock:
            team = self._require_team(team_name)
            candidate: Worker | None = None
            with team._lock:
                for member in team.members:
                    if member.status == AgentStatus.AgentIdle:
                        candidate = member
                        break
            if candidate is None:
                raise ValueError(f"no idle workers available in team {team_name!r}")
            candidate.assign_task(task)
            return candidate

    def inject_context(self, worker_id: str, team_name: str) -> str:
        """Builds a context string for a worker agent."""
        with self._lock:
            parts: list[str] = []
            if self._scratchpad:
                lines = [
                    f"- **{key}**: {entry.value} (set by {entry.set_by})"
                    for key, entry in sorted(self._scratchpad.items())
                ]
                parts.append("## Shared Scratchpad\n\n" + "\n".join(lines) + "\n")
            team = self._teams.get(team_name)
            if team is not None:
                members_desc = ", ".join(
                    f"{member.id} ({member.status.String()})" for member in team.members
                )
                parts.append(f"## Team: {team_name}\n\nMembers: {members_desc}\n\n")
                with team._lock:
                    for msg in team.messages:
                        if (
                            msg.to == worker_id
                            or msg.from_ == worker_id
                            or msg.to == "all"
                        ):
                            parts.append(f"[{msg.from_} → {msg.to}]: {msg.content}\n")
            return "".join(parts)

    def get_team(self, name: str) -> Team:
        with self._lock:
            team = self._teams.get(name)
            if team is None:
                raise TeamNotFoundError(f"team {name!r} not found")
            return team

    def list_teams(self) -> list[str]:
        with self._lock:
            return list(self._teams)

    def shutdown(self) -> None:
        """Stops all workers and cleans up."""
        self._stop_event.set()
        with self._lock:
            for team in self._teams.values():
                with team._lock:
                    for member in team.members:
                        member.stop()
            for worker in self._workers.values():
                worker.stop()

    def _require_team(self, name: str) -> Team:
        team = self._teams.get(name)
        if team is None:
            raise TeamNotFoundError(f"team {name!r} not found")
        return team


def new_coordinator(config: CoordinatorConfig | None = None) -> Coordinator:
    return Coordinator(config if config is not None else default_coordinator_config())
