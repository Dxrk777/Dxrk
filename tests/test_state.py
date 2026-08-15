import json

import pytest

from dxrk.state import (
    STATE_DIR,
    InstallState,
    ModelAssignmentState,
    path,
    read,
    write,
)


def test_write_and_read(tmp_path):
    agents = ["claude-code", "opencode"]
    write(str(tmp_path), InstallState(installed_agents=agents))
    s = read(str(tmp_path))
    assert s.installed_agents == agents


def test_persona_round_trip(tmp_path):
    for persona in ["dxrk", "neutral", "custom"]:
        home = tmp_path / persona
        home.mkdir()
        write(
            str(home),
            InstallState(installed_agents=["claude-code"], persona=persona),
        )
        s = read(str(home))
        assert s.persona == persona


def test_persona_backward_compat(tmp_path):
    write(str(tmp_path), InstallState(installed_agents=["claude-code"]))
    s = read(str(tmp_path))
    assert s.persona == ""


def test_write_creates_state_dir(tmp_path):
    write(str(tmp_path), InstallState(installed_agents=["opencode"]))
    assert (tmp_path / STATE_DIR).is_dir()


def test_write_state_file_path(tmp_path):
    got = path(str(tmp_path))
    want = str(tmp_path / ".dxrk" / "state.json")
    assert got == want


def test_read_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read(str(tmp_path))


def test_read_corrupt(tmp_path):
    (tmp_path / STATE_DIR).mkdir()
    (tmp_path / ".dxrk" / "state.json").write_text("not valid json {{{{")
    with pytest.raises(json.JSONDecodeError):
        read(str(tmp_path))


def test_write_overwrite(tmp_path):
    write(str(tmp_path), InstallState(installed_agents=["claude-code"]))
    write(str(tmp_path), InstallState(installed_agents=["opencode", "gemini-cli"]))
    s = read(str(tmp_path))
    assert s.installed_agents == ["opencode", "gemini-cli"]


def test_write_empty_agents(tmp_path):
    write(str(tmp_path), InstallState(installed_agents=[]))
    s = read(str(tmp_path))
    assert len(s.installed_agents) == 0


def test_model_assignments_round_trip(tmp_path):
    want = InstallState(
        installed_agents=["claude-code"],
        claude_model_assignments={
            "orchestrator": "opus",
            "sdd-explore": "sonnet",
            "sdd-archive": "haiku",
        },
        kiro_model_assignments={
            "sdd-design": "opus",
            "sdd-archive": "haiku",
            "default": "sonnet",
        },
        model_assignments={
            "sdd-init": ModelAssignmentState(
                provider_id="anthropic", model_id="claude-sonnet-4"
            )
        },
    )
    write(str(tmp_path), want)
    got = read(str(tmp_path))
    assert got.claude_model_assignments == want.claude_model_assignments
    assert got.kiro_model_assignments == want.kiro_model_assignments
    assert got.model_assignments == want.model_assignments


def test_model_assignment_state_effort_round_trip(tmp_path):
    want = InstallState(
        model_assignments={
            "sdd-apply": ModelAssignmentState(
                provider_id="anthropic", model_id="claude-opus-4", effort="high"
            )
        }
    )
    write(str(tmp_path), want)
    got = read(str(tmp_path))
    assert got.model_assignments is not None
    assert got.model_assignments["sdd-apply"].effort == "high"


def test_model_assignment_state_effort_legacy_missing(tmp_path):
    (tmp_path / STATE_DIR).mkdir()
    legacy = (
        '{"installed_agents":["opencode"],"model_assignments":'
        '{"sdd-apply":{"provider_id":"anthropic","model_id":"claude-opus-4"}}}'
        "\n"
    )
    (tmp_path / ".dxrk" / "state.json").write_text(legacy)
    s = read(str(tmp_path))
    assert s.model_assignments is not None
    assert s.model_assignments["sdd-apply"].effort == ""


def test_backward_compat_no_assignments(tmp_path):
    (tmp_path / STATE_DIR).mkdir()
    legacy = '{"installed_agents":["claude-code"]}\n'
    (tmp_path / ".dxrk" / "state.json").write_text(legacy)
    s = read(str(tmp_path))
    assert s.installed_agents == ["claude-code"]
    assert s.claude_model_assignments is None
    assert s.model_assignments is None
