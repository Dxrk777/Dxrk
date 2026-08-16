# SPDX-License-Identifier: MIT
"""Tests for dxrk/commands (mirrors internal/commands/*_test.go)."""
from __future__ import annotations

import os
import subprocess

import pytest

from dxrk.commands import register_all


class _Capture:
    def __init__(self):
        self.chunks = []

    def write(self, text):
        self.chunks.append(text)

    def getvalue(self):
        return "".join(self.chunks)


def run_command(cwd, args, env=None, stdin=""):
    """Runs a command synchronously through a fully-registered Registry."""
    reg = register_all()
    out, err = _Capture(), _Capture()
    code = reg.execute(args, out=out, err=err, cwd=str(cwd))
    return code, out.getvalue(), err.getvalue()


def _git(cwd, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "README.md").write_text("# test\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "initial commit")
    return tmp_path


def fake_gh(monkeypatch, tmp_path):
    """Replaces `gh` with a capture script."""
    capture = tmp_path / "gh_capture.txt"
    script = (
        "#!/bin/sh\n"
        f"echo \"$@\" >> {capture}\n"
        'if [ "$1" = "pr" ] && [ "$2" = "list" ]; then echo 4; fi\n'
        'if [ "$1" = "pr" ] && [ "$2" = "view" ]; then echo \'{"number":4,"title":"Test PR","url":"https://github.com/x/y/pull/4","baseRefName":"main"}\'; fi\n'
        'if [ "$1" = "pr" ] && [ "$2" = "diff" ]; then echo "diff --git a/a.txt b/a.txt"; fi\n'
        'if [ "$1" = "pr" ] && [ "$2" = "create" ]; then echo "https://github.com/x/y/pull/4"; fi\n'
        'exit 0\n'
    )
    gh = tmp_path / "gh"
    gh.write_text(script)
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("GH_CAPTURE", str(capture))
    return capture


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)


def fake_session_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def env(repo, clean_env):
    return {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


class TestBasics:
    def test_unknown_command(self, repo, env):
        code, out, err = run_command(repo, ["nope"], env=env)
        assert code == 1
        assert "unknown command: nope" in err

    def test_fast_sets_effort_fast(self, repo, env):
        code, out, err = run_command(repo, ["fast"], env=env)
        assert code == 0
        assert "fast" in out

    def test_vim_outputs_vim_mode(self, repo, env):
        code, out, err = run_command(repo, ["vim"], env=env)
        assert code == 0
        assert "vim" in out.lower()

    def test_effort_no_value(self, repo, env):
        code, out, err = run_command(repo, ["effort"], env=env)
        assert code == 0

    def test_rename(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, _ = run_command(tmp_path, ["session", "create"], env=env)
        sid = out.split("Created session ")[1].split()[0]
        code, out, err = run_command(tmp_path, ["rename", sid, "new title"], env=env)
        assert code == 0
        assert "Renamed session" in out
        assert "new title" in out

    def test_rename_missing(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, err = run_command(tmp_path, ["rename", "missing", "x"], env=env)
        assert code == 1
        assert "not found" in err


class TestSession:
    def test_session_lifecycle(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["session", "create"], env={"HOME": str(home)})
        assert code == 0
        assert "Created session" in out
        sid = out.split("Created session ")[1].split()[0]

        code, out, err = run_command(tmp_path, ["session", "list"], env={"HOME": str(home)})
        assert code == 0
        assert sid[:8] in out

        code, out, err = run_command(tmp_path, ["session", "info", sid], env={"HOME": str(home)})
        assert code == 0
        assert "ID:" in out

        code, out, err = run_command(tmp_path, ["session", "delete", sid], env={"HOME": str(home)})
        assert code == 0
        assert "Deleted session" in out

    def test_session_list_empty(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["session", "list"], env={"HOME": str(home)})
        assert code == 0
        assert "No sessions found" in out

    def test_session_info_missing(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["session", "info", "doesnotexist"], env={"HOME": str(home)})
        assert code == 1
        assert "not found" in err


class TestTag:
    def test_tag_lifecycle(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, _ = run_command(tmp_path, ["session", "create"], env=env)
        sid = out.split("Created session ")[1].split()[0]

        code, out, err = run_command(tmp_path, ["tag", "add", sid, "important"], env=env)
        assert code == 0
        assert "Added tag" in out

        code, out, err = run_command(tmp_path, ["tag", "add", sid, "important"], env=env)
        assert code == 0
        assert "already exists" in out

        code, out, err = run_command(tmp_path, ["tag", "list", sid], env=env)
        assert code == 0
        assert "important" in out

        code, out, err = run_command(tmp_path, ["tag", "search", "important"], env=env)
        assert code == 0
        assert "important" in out

        code, out, err = run_command(tmp_path, ["tag", "remove", sid, "important"], env=env)
        assert code == 0
        assert "Removed tag" in out


class TestGit:
    def test_commit_nothing(self, repo, env):
        code, out, err = run_command(repo, ["commit", "-m", "noop"], env=env)
        assert code == 1
        assert "nothing to commit" in err

    def test_commit_and_diff(self, repo, env):
        (repo / "a.txt").write_text("hello\n")
        code, out, err = run_command(repo, ["commit", "-m", "feat: add a.txt"], env=env)
        assert code == 0
        assert "feat: add a.txt" in out

        code, out, err = run_command(repo, ["diff"], env=env)
        assert code == 0

    def test_diff_shows_changes(self, repo, env):
        (repo / "a.txt").write_text("hello\n")
        _git(repo, "add", "a.txt")
        code, out, err = run_command(repo, ["diff", "--staged"], env=env)
        assert code == 0
        assert "a.txt" in out

    def test_branch_list(self, repo, env):
        code, out, err = run_command(repo, ["branch"], env=env)
        assert code == 0
        assert "main" in out

    def test_branch_create_switch_delete(self, repo, env):
        code, out, err = run_command(repo, ["branch", "-c", "feature"], env=env)
        assert code == 0
        code, out, err = run_command(repo, ["branch", "-s", "feature"], env=env)
        assert code == 0
        code, out, err = run_command(repo, ["branch", "-d", "feature"], env=env)
        assert code == 1  # cannot delete the checked-out branch

    def test_branch_delete_missing_name(self, repo, env):
        code, out, err = run_command(repo, ["branch", "-d"], env=env)
        assert code == 1
        assert "branch name required for delete" in err

    def test_review_uncommitted(self, repo, env):
        (repo / "a.txt").write_text("hello\n")
        code, out, err = run_command(repo, ["review"], env=env)
        assert code == 0
        assert "REVIEW" in out

    def test_review_pr(self, repo, monkeypatch, env):
        fake_gh(monkeypatch, repo)
        code, out, err = run_command(repo, ["review", "--pr", "4"], env=env)
        assert code == 0

    def test_pr_comments(self, repo, monkeypatch, env):
        fake_gh(monkeypatch, repo)
        code, out, err = run_command(repo, ["pr", "comments", "4"], env=env)
        assert code == 0

    def test_commit_push_pr(self, repo, monkeypatch, env):
        fake_gh(monkeypatch, repo)
        remote = repo / "remote.git"
        _git(repo, "init", "--bare", "--initial-branch=main", str(remote))
        _git(repo, "remote", "add", "origin", str(remote))
        (repo / "a.txt").write_text("hello\n")
        code, out, err = run_command(repo, ["commit-push-pr", "-t", "feat: a"], env=env)
        assert code == 0
        assert "PR created" in out


class TestMisc:
    def test_export_roundtrip(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, _ = run_command(tmp_path, ["session", "create"], env=env)
        sid = out.split("Created session ")[1].split()[0]

        dest = tmp_path / "session.md"
        code, out, err = run_command(tmp_path, ["export", sid, "--output", str(dest)], env=env)
        assert code == 0
        assert dest.exists()
        assert "# " in dest.read_text()

    def test_usage_lists_commands(self, repo, env):
        code, out, err = run_command(repo, ["usage"], env=env)
        assert code == 0
        assert "Commands:" in out
        assert "usage" in out

    def test_init_detects_existing(self, tmp_path, clean_env):
        code, out, err = run_command(tmp_path, ["init"], env=env_with())
        assert code == 0
        assert "Initialized" in out
        code, out, err = run_command(tmp_path, ["init"], env=env_with())
        assert code == 0
        assert "already initialized" in out

    def test_init_creates(self, tmp_path, clean_env):
        code, out, err = run_command(tmp_path, ["init"], env=env_with())
        assert code == 0
        assert "Initialized" in out
        assert (tmp_path / ".dxrk" / "config.json").exists()

    def test_files_lists(self, repo, env):
        (repo / "z.txt").write_text("z")
        code, out, err = run_command(repo, ["files"], env=env)
        assert code == 0
        assert "Recent files" in out

    def test_memory(self, repo, env):
        code, out, err = run_command(repo, ["memory"], env=env)
        assert code == 0

    def test_context(self, repo, env):
        code, out, err = run_command(repo, ["context"], env=env)
        assert code == 0
        assert "Working dir" in out

    def test_config(self, repo, env):
        code, out, err = run_command(repo, ["config"], env=env)
        assert code == 0

    def test_model(self, repo, env):
        code, out, err = run_command(repo, ["model", "list"], env=env)
        assert code == 0

    def test_theme(self, repo, env):
        code, out, err = run_command(repo, ["theme"], env=env)
        assert code == 0
        assert "default" in out

    def test_keybindings(self, repo, env):
        code, out, err = run_command(repo, ["keybindings"], env=env)
        assert code == 0
        assert "ACTION" in out

    def test_hooks_add_remove(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, err = run_command(tmp_path, ["hooks", "add", "myhook", "pre-commit", "echo hi"], env=env)
        assert code == 0
        assert "Added hook" in out
        code, out, err = run_command(tmp_path, ["hooks", "add", "myhook", "pre-commit", "echo hi"], env=env)
        assert code == 1
        assert "already exists" in err
        code, out, err = run_command(tmp_path, ["hooks", "remove", "myhook"], env=env)
        assert code == 0
        assert "Removed hook" in out

    def test_hooks_list_empty(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["hooks", "list"], env={"HOME": str(home)})
        assert code == 0
        assert "No hooks" in out

    def test_permissions_default(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["permissions"], env={"HOME": str(home)})
        assert code == 0
        assert "Sandbox Image" in out

        code, out, err = run_command(tmp_path, ["permissions", "reset"], env={"HOME": str(home)})
        assert code == 0
        assert "reset to defaults" in out

    def test_doctor(self, repo, env):
        code, out, err = run_command(repo, ["doctor"], env=env)
        assert code == 0

    def test_agents_empty(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["agents"], env={"HOME": str(home)})
        assert code == 0
        assert "No agents" in out

    def test_skills_empty(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["skills"], env={"HOME": str(home)})
        assert code == 0

    def test_plugin_list_empty(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["plugin", "list"], env={"HOME": str(home)})
        assert code == 0
        assert "No plugins" in out

    def test_plan_flow(self, tmp_path, clean_env):
        code, out, err = run_command(tmp_path, ["plan", "add", "write docs"], env=env_with())
        assert code == 0
        assert "Added task" in out
        code, out, err = run_command(tmp_path, ["plan", "show"], env=env_with())
        assert code == 0
        assert "- [ ] write docs" in out
        code, out, err = run_command(tmp_path, ["plan", "done", "1"], env=env_with())
        assert code == 0
        assert "done" in out

    def test_mcp_add_list_remove(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        env = {"HOME": str(home)}
        code, out, err = run_command(tmp_path, ["mcp", "add", "myserver", "--command", "npx-foo"], env=env)
        assert code == 0
        assert "Added MCP server" in out
        code, out, err = run_command(tmp_path, ["mcp", "list"], env=env)
        assert code == 0
        assert "myserver" in out
        code, out, err = run_command(tmp_path, ["mcp", "remove", "myserver"], env=env)
        assert code == 0
        assert "Removed MCP server" in out

    def test_cost_missing_session(self, tmp_path, monkeypatch, clean_env):
        home = fake_session_dir(tmp_path, monkeypatch)
        code, out, err = run_command(tmp_path, ["cost", "nonexistent"], env={"HOME": str(home)})
        assert code == 1
        assert "not found" in err


def env_with():
    return {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
