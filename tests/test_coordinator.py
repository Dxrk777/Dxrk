# SPDX-License-Identifier: MIT
from __future__ import annotations

import time
from datetime import timedelta

import pytest

from dxrk.coordinator import (
    AgentNotFoundError,
    AgentResult,
    AgentStatus,
    Coordinator,
    CoordinatorConfig,
    CoordinatorMode,
    CoordinatorError,
    ScratchpadKeyError,
    Team,
    TeamNotFoundError,
    Worker,
    default_coordinator_config,
    new_coordinator,
    new_team,
    new_worker,
)


class TestModesAndStatus:
    def test_coordinator_mode_strings(self):
        assert CoordinatorMode.ModeSingleAgent.String() == "single_agent"
        assert CoordinatorMode.ModeCoordinator.String() == "coordinator"
        assert CoordinatorMode.ModeWorker.String() == "worker"
        assert CoordinatorMode.ModeUnknown.String() == "unknown"
        assert str(CoordinatorMode.ModeWorker) == "worker"

    def test_agent_status_strings(self):
        assert AgentStatus.AgentIdle.String() == "idle"
        assert AgentStatus.AgentBusy.String() == "busy"
        assert AgentStatus.AgentFailed.String() == "failed"
        assert AgentStatus.AgentDone.String() == "done"
        assert AgentStatus.AgentUnknown.String() == "unknown"
        assert str(AgentStatus.AgentDone) == "done"

    def test_default_coordinator_config(self):
        config = default_coordinator_config()
        assert config.mode == CoordinatorMode.ModeSingleAgent
        assert config.max_workers == 8
        assert config.scratchpad_limit == 100
        assert config.agent_timeout == timedelta(minutes=30)
        assert config.context_window == 128000


class TestWorker:
    def test_new_worker_defaults(self):
        worker = new_worker("agent-1")
        assert worker.id == "agent-1"
        assert worker.status == AgentStatus.AgentIdle
        assert worker.task == ""
        assert worker.result is None
        assert worker.created_at is not None
        assert worker.started_at is None
        assert worker.done_at is None
        assert worker.is_idle()
        assert worker.get_status() == AgentStatus.AgentIdle
        assert worker.get_result() is None

    def test_assign_task(self):
        worker = new_worker("agent-1")
        worker.assign_task("build feature")
        assert worker.status == AgentStatus.AgentBusy
        assert worker.task == "build feature"
        assert worker.started_at is not None
        assert not worker.is_idle()

    def test_complete(self):
        worker = new_worker("agent-1")
        worker.assign_task("build feature")
        worker.complete("done output")
        assert worker.status == AgentStatus.AgentDone
        assert worker.done_at is not None
        result = worker.get_result()
        assert isinstance(result, AgentResult)
        assert result.agent_id == "agent-1"
        assert result.output == "done output"
        assert result.error == ""
        assert result.duration >= timedelta(0)

    def test_complete_before_assign_raises(self):
        worker = new_worker("agent-1")
        with pytest.raises(ValueError, match="no started task"):
            worker.complete("output")

    def test_fail(self):
        worker = new_worker("agent-1")
        worker.assign_task("risky task")
        worker.fail("model error")
        assert worker.status == AgentStatus.AgentFailed
        assert worker.done_at is not None
        result = worker.get_result()
        assert isinstance(result, AgentResult)
        assert result.agent_id == "agent-1"
        assert result.output == ""
        assert result.error == "model error"

    def test_reset(self):
        worker = new_worker("agent-1")
        worker.assign_task("task")
        worker.complete("output")
        worker.reset()
        assert worker.status == AgentStatus.AgentIdle
        assert worker.task == ""
        assert worker.result is None
        assert worker.started_at is None
        assert worker.done_at is None
        assert worker.is_idle()

    def test_stop_busy_marks_failed(self):
        worker = new_worker("agent-1")
        worker.assign_task("task")
        worker.stop()
        assert worker.status == AgentStatus.AgentFailed
        result = worker.get_result()
        assert result is not None
        assert result.error == "stopped by coordinator"

    def test_stop_idle_leaves_idle(self):
        worker = new_worker("agent-1")
        worker.stop()
        assert worker.status == AgentStatus.AgentIdle


class TestTeam:
    def test_new_team_members(self):
        team = new_team("team-a", ["alice", "bob"])
        assert team.name == "team-a"
        assert [m.id for m in team.members] == ["alice", "bob"]
        assert all(m.status == AgentStatus.AgentIdle for m in team.members)

    def test_get_member(self):
        team = new_team("team-a", ["alice", "bob"])
        assert team.get_member("bob").id == "bob"

    def test_get_member_unknown_raises(self):
        team = new_team("team-a", ["alice"])
        with pytest.raises(AgentNotFoundError):
            team.get_member("carol")

    def test_member_ids(self):
        team = new_team("team-a", ["alice", "bob"])
        assert team.member_ids() == ["alice", "bob"]

    def test_member_statuses(self):
        team = new_team("team-a", ["alice", "bob"])
        assert team.member_statuses() == {"alice": "idle", "bob": "idle"}
        team.get_member("alice").assign_task("task")
        assert team.member_statuses() == {"alice": "busy", "bob": "idle"}

    def test_route_message(self):
        team = new_team("team-a", ["alice", "bob"])
        team.route_message("alice", "bob", "ping")
        assert team.message_count() == 1
        msg = team.messages[0]
        assert msg.from_ == "alice"
        assert msg.to == "bob"
        assert msg.content == "ping"
        assert msg.timestamp is not None

    def test_route_message_unknown_sender_raises(self):
        team = new_team("team-a", ["alice", "bob"])
        with pytest.raises(AgentNotFoundError):
            team.route_message("carol", "bob", "hi")
        assert team.message_count() == 0

    def test_route_message_unknown_recipient_raises(self):
        team = new_team("team-a", ["alice", "bob"])
        with pytest.raises(AgentNotFoundError):
            team.route_message("alice", "carol", "hi")
        assert team.message_count() == 0

    def test_route_message_to_all(self):
        team = new_team("team-a", ["alice", "bob"])
        team.route_message("alice", "all", "everyone")
        assert team.messages[0].to == "all"

    def test_broadcast(self):
        team = new_team("team-a", ["alice", "bob"])
        team.broadcast("alice", "hello all")
        assert team.message_count() == 1
        assert team.messages[0].to == "all"

    def test_recent_messages_last_n(self):
        team = new_team("team-a", ["alice", "bob"])
        for i in range(3):
            team.route_message("alice", "bob", f"msg-{i}")
        recent = team.recent_messages(2)
        assert [m.content for m in recent] == ["msg-1", "msg-2"]

    def test_recent_messages_more_than_available(self):
        team = new_team("team-a", ["alice", "bob"])
        team.route_message("alice", "bob", "only")
        assert [m.content for m in team.recent_messages(5)] == ["only"]

    def test_recent_messages_empty(self):
        team = new_team("team-a", ["alice"])
        assert team.recent_messages(5) == []
        assert team.recent_messages(0) == []

    def test_message_count(self):
        team = new_team("team-a", ["alice"])
        assert team.message_count() == 0
        team.broadcast("alice", "hi")
        assert team.message_count() == 1


class TestCoordinator:
    def test_new_coordinator(self):
        coord = new_coordinator()
        assert coord._config == default_coordinator_config()
        assert coord.list_teams() == []
        assert coord.get_all_scratchpad() == {}

    def test_create_team_and_get(self):
        coord = new_coordinator()
        team = coord.create_team("team-a", ["alice", "bob"])
        assert isinstance(team, Team)
        assert coord.get_team("team-a") is team
        assert coord.list_teams() == ["team-a"]

    def test_create_team_duplicate_raises(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice"])
        with pytest.raises(ValueError, match="already exists"):
            coord.create_team("team-a", ["bob"])

    def test_create_team_empty_members_raises(self):
        coord = new_coordinator()
        with pytest.raises(ValueError, match="at least one member"):
            coord.create_team("team-a", [])

    def test_get_team_unknown_raises(self):
        coord = new_coordinator()
        with pytest.raises(TeamNotFoundError):
            coord.get_team("nope")

    def test_delete_team_marks_members_done(self):
        coord = new_coordinator()
        team = coord.create_team("team-a", ["alice"])
        coord.delete_team("team-a")
        assert team.get_member("alice").status == AgentStatus.AgentDone
        assert coord.list_teams() == []

    def test_delete_team_unknown_raises(self):
        coord = new_coordinator()
        with pytest.raises(TeamNotFoundError):
            coord.delete_team("nope")

    def test_send_message(self):
        coord = new_coordinator()
        team = coord.create_team("team-a", ["alice", "bob"])
        coord.send_message("team-a", "alice", "bob", "hello")
        assert team.message_count() == 1
        assert team.messages[0].content == "hello"

    def test_send_message_unknown_team_raises(self):
        coord = new_coordinator()
        with pytest.raises(TeamNotFoundError):
            coord.send_message("nope", "alice", "bob", "hello")

    def test_broadcast_message(self):
        coord = new_coordinator()
        team = coord.create_team("team-a", ["alice", "bob"])
        coord.broadcast_message("team-a", "alice", "attention")
        assert team.messages[0].to == "all"

    def test_delegate_work(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice", "bob"])
        worker = coord.delegate_work("team-a", "build")
        assert worker.id == "alice"
        assert worker.status == AgentStatus.AgentBusy
        assert worker.task == "build"

    def test_delegate_work_picks_next_idle(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice", "bob"])
        coord.delegate_work("team-a", "one")
        worker = coord.delegate_work("team-a", "two")
        assert worker.id == "bob"

    def test_delegate_work_no_idle_raises(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice"])
        coord.delegate_work("team-a", "one")
        with pytest.raises(ValueError, match="no idle workers"):
            coord.delegate_work("team-a", "two")

    def test_delegate_work_unknown_team_raises(self):
        coord = new_coordinator()
        with pytest.raises(TeamNotFoundError):
            coord.delegate_work("nope", "task")

    def test_delegate_complete_cycle(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice"])
        worker = coord.delegate_work("team-a", "build")
        worker.complete("built")
        assert worker.status == AgentStatus.AgentDone
        result = worker.get_result()
        assert result is not None
        assert result.output == "built"
        worker.reset()
        assert worker.is_idle()


class TestScratchpad:
    def test_set_and_get(self):
        coord = new_coordinator()
        coord.set_scratchpad("goal", "ship", "alice")
        entry = coord.get_scratchpad("goal")
        assert entry.key == "goal"
        assert entry.value == "ship"
        assert entry.set_by == "alice"
        assert entry.created_at is not None
        assert entry.updated_at == entry.created_at

    def test_get_missing_raises(self):
        coord = new_coordinator()
        with pytest.raises(ScratchpadKeyError):
            coord.get_scratchpad("nope")

    def test_update_preserves_created_at(self):
        coord = new_coordinator()
        coord.set_scratchpad("goal", "ship", "alice")
        time.sleep(0.002)
        coord.set_scratchpad("goal", "ship-done", "bob")
        entry = coord.get_scratchpad("goal")
        assert entry.value == "ship-done"
        assert entry.set_by == "bob"
        assert entry.updated_at >= entry.created_at

    def test_get_all_scratchpad(self):
        coord = new_coordinator()
        coord.set_scratchpad("a", "1", "alice")
        coord.set_scratchpad("b", "2", "bob")
        all_entries = coord.get_all_scratchpad()
        assert set(all_entries) == {"a", "b"}
        assert all_entries["b"].value == "2"

    def test_eviction_removes_oldest(self):
        coord = new_coordinator(CoordinatorConfig(scratchpad_limit=2))
        coord.set_scratchpad("a", "1", "alice")
        time.sleep(0.002)
        coord.set_scratchpad("b", "2", "bob")
        time.sleep(0.002)
        coord.set_scratchpad("c", "3", "carol")
        assert set(coord.get_all_scratchpad()) == {"b", "c"}


class TestInjectContext:
    def test_empty(self):
        coord = new_coordinator()
        assert coord.inject_context("alice", "team-a") == ""

    def test_scratchpad_only(self):
        coord = new_coordinator()
        coord.set_scratchpad("goal", "ship", "alice")
        ctx = coord.inject_context("alice", "team-a")
        assert "## Shared Scratchpad" in ctx
        assert "- **goal**: ship (set by alice)" in ctx

    def test_team_members(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice", "bob"])
        coord.delegate_work("team-a", "build")
        ctx = coord.inject_context("alice", "team-a")
        assert "## Team: team-a" in ctx
        assert "Members: alice (busy), bob (idle)" in ctx

    def test_relevant_messages_only(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice", "bob", "carol"])
        coord.send_message("team-a", "bob", "alice", "to-alice")
        coord.send_message("team-a", "alice", "bob", "from-alice")
        coord.send_message("team-a", "carol", "all", "broadcast")
        coord.send_message("team-a", "bob", "carol", "unrelated")
        ctx = coord.inject_context("alice", "team-a")
        assert "[bob → alice]: to-alice" in ctx
        assert "[alice → bob]: from-alice" in ctx
        assert "[carol → all]: broadcast" in ctx
        assert "unrelated" not in ctx

    def test_unknown_team_has_no_team_section(self):
        coord = new_coordinator()
        coord.set_scratchpad("k", "v", "alice")
        ctx = coord.inject_context("alice", "nope")
        assert "## Shared Scratchpad" in ctx
        assert "## Team:" not in ctx


class TestShutdown:
    def test_shutdown_stops_team_members(self):
        coord = new_coordinator()
        team = coord.create_team("team-a", ["alice", "bob"])
        coord.delegate_work("team-a", "task")
        coord.shutdown()
        assert team.get_member("alice").status == AgentStatus.AgentFailed
        result = team.get_member("alice").get_result()
        assert result is not None
        assert result.error == "stopped by coordinator"
        assert team.get_member("bob").status == AgentStatus.AgentIdle

    def test_shutdown_twice_is_safe(self):
        coord = new_coordinator()
        coord.create_team("team-a", ["alice"])
        coord.delegate_work("team-a", "task")
        coord.shutdown()
        coord.shutdown()


def test_error_hierarchy():
    assert issubclass(TeamNotFoundError, CoordinatorError)
    assert issubclass(AgentNotFoundError, CoordinatorError)
    assert issubclass(ScratchpadKeyError, CoordinatorError)
