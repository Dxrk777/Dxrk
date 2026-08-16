# SPDX-License-Identifier: MIT
"""Tests for dxrk.tools.dxrk."""

from __future__ import annotations

import shutil

import pytest

from dxrk.agents.factory import create_registry
from dxrk.tools import Registry
from dxrk.tools import dxrk as tools_dxrk


@pytest.fixture
def registry() -> Registry:
    reg = Registry()
    tools_dxrk.register_all(reg, create_registry())
    return reg


def run_tool(
    reg: Registry, name: str, input_: dict | None = None
) -> tuple[object, str | None]:
    tool = reg.get(name)
    assert tool is not None, f"tool {name} not registered"
    return tool.execute({}, input_)


def test_detect_agents_empty_home(
    registry: Registry, temp_dir, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    result, err = run_tool(registry, "detect_agents", {"home_dir": str(temp_dir)})
    assert err is None
    assert result == {"agents": [], "count": 0}


def test_detect_agent_unknown(registry: Registry) -> None:
    result, err = run_tool(registry, "detect_agent", {"agent": "not-a-real-agent"})
    assert result is None
    assert err is not None
    assert "unknown agent" in err


def test_detect_agent_missing_input(registry: Registry) -> None:
    tool = registry.get("detect_agent")
    assert tool is not None
    err = tool.validate({})
    assert err == "agent is required"


def test_system_info_shape(registry: Registry, temp_dir) -> None:
    result, err = run_tool(registry, "system_info")
    assert err is None
    assert isinstance(result, dict)
    for key in ("os", "arch", "shell", "supported", "tools", "configs", "dependencies"):
        assert key in result


def test_list_skills_discovers_project_and_user(
    registry: Registry, temp_dir, monkeypatch
) -> None:
    project = temp_dir / "proj"
    project.mkdir()
    (project / "skills").mkdir()
    (project / "skills" / "demo").mkdir()
    (project / "skills" / "demo" / "SKILL.md").write_text("# Demo\n")
    home = temp_dir / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "skills" / "usertool").mkdir()
    (home / ".claude" / "skills" / "usertool" / "SKILL.md").write_text("# User\n")

    monkeypatch.setenv("HOME", str(home))
    result, err = run_tool(registry, "list_skills", {"project_dir": str(project)})
    assert err is None
    assert isinstance(result, dict)
    names = {s["name"] for s in result["skills"]}
    assert {"demo", "usertool"} <= names
    assert result["count"] == len(result["skills"])


def test_list_skills_ignores_dirs_without_skill_md(
    registry: Registry, temp_dir, monkeypatch
) -> None:
    project = temp_dir / "proj"
    project.mkdir()
    (project / "skills").mkdir()
    (project / "skills" / "nope").mkdir()
    monkeypatch.setenv("HOME", str(temp_dir / "nohome"))
    result, err = run_tool(
        registry,
        "list_skills",
        {"project_dir": str(project)},
    )
    assert err is None
    assert isinstance(result, dict)
    assert result["count"] == 0


def test_run_diagnostic_shape(registry: Registry) -> None:
    result, err = run_tool(registry, "run_diagnostic")
    assert err is None
    assert isinstance(result, dict)
    assert "system" in result and "agents" in result and "tools" in result
    assert result["agent_count"] == len(result["agents"])


def test_run_diagnostic_no_configs(registry: Registry) -> None:
    result, err = run_tool(registry, "run_diagnostic", {"include_configs": False})
    assert err is None
    assert isinstance(result, dict)
    assert "configs" not in result


def test_read_file_ok(registry: Registry, temp_dir) -> None:
    f = temp_dir / "hello.txt"
    f.write_text("hola mundo")
    result, err = run_tool(registry, "read_file", {"path": str(f)})
    assert err is None
    assert isinstance(result, dict)
    assert result["content"] == "hola mundo"
    assert result["size"] == len("hola mundo")


def test_read_file_missing_path(registry: Registry) -> None:
    tool = registry.get("read_file")
    assert tool is not None
    err = tool.validate({})
    assert err == "path is required"


def test_read_file_directory(registry: Registry, temp_dir) -> None:
    result, err = run_tool(registry, "read_file", {"path": str(temp_dir)})
    assert result is None
    assert err is not None
    assert "directory" in err


def test_read_file_max_size(registry: Registry, temp_dir) -> None:
    f = temp_dir / "big.txt"
    f.write_text("x" * 100)
    result, err = run_tool(registry, "read_file", {"path": str(f), "max_size": 10})
    assert result is None
    assert err is not None
    assert "max_size" in err


def test_grep_search_finds(registry: Registry, temp_dir) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not installed")
    f = temp_dir / "code.py"
    f.write_text("def hello():\n    return 42\n")
    result, err = run_tool(
        registry, "grep_search", {"pattern": "hello", "path": str(temp_dir)}
    )
    assert err is None
    assert isinstance(result, dict)
    assert result["count"] >= 1
    assert any("code.py" in r and "hello" in r for r in result["results"])


def test_grep_search_no_match(registry: Registry, temp_dir) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not installed")
    f = temp_dir / "code.py"
    f.write_text("def hello():\n")
    result, err = run_tool(
        registry, "grep_search", {"pattern": "zzzznomatch", "path": str(temp_dir)}
    )
    assert err is None
    assert isinstance(result, dict)
    assert result["count"] == 0


def test_grep_search_missing_pattern(registry: Registry) -> None:
    tool = registry.get("grep_search")
    assert tool is not None
    err = tool.validate({})
    assert err == "pattern is required"


def test_glob_search_finds(registry: Registry, temp_dir) -> None:
    if shutil.which("rg") is None:
        pytest.skip("ripgrep not installed")
    (temp_dir / "a.go").write_text("")
    (temp_dir / "b.py").write_text("")
    result, err = run_tool(
        registry, "glob_search", {"pattern": "*.go", "path": str(temp_dir)}
    )
    assert err is None
    assert isinstance(result, dict)
    assert result["count"] == 1
    assert result["files"][0].endswith("a.go")


def test_glob_search_missing_pattern(registry: Registry) -> None:
    tool = registry.get("glob_search")
    assert tool is not None
    err = tool.validate({})
    assert err == "pattern is required"


import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
