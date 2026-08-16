# SPDX-License-Identifier: MIT
from __future__ import annotations

import pathlib
import subprocess
from datetime import UTC, datetime

import pytest

from dxrk.git import (
    AuthorInfo,
    LogOptions,
    Runner,
    detect_conflicts,
    extract_hash,
    is_hex,
    parse_branches,
    parse_commits,
    parse_count,
    parse_hunk_stats,
    parse_stashes,
    parse_status,
    parse_worktrees,
)


def _git(repo_dir, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
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
    _git(tmp_path, "init", "--initial-branch=master")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "config", "user.email", "test@example.com")
    return Runner(str(tmp_path))


def test_parse_status_clean():
    result = parse_status("# branch.head main\n# branch.ab +0 -0\n")
    assert result.branch == "main"
    assert result.staged == []
    assert result.unstaged == []
    assert result.untracked == []


def test_parse_status_modified():
    result = parse_status(
        "# branch.head feature\n"
        "# branch.ab +3 -1\n"
        "1 .M N... 100644 100644 00000000000 00000000000 file.go\n"
    )
    assert result.branch == "feature"
    assert result.ahead == 3
    assert result.behind == 1
    assert len(result.unstaged) == 1
    assert result.unstaged[0].path == "file.go"
    assert result.staged == []


def test_parse_status_untracked():
    result = parse_status("# branch.head main\n# branch.ab +0 -0\n? new_file.go\n")
    assert result.untracked == ["new_file.go"]


def test_parse_commits():
    input_text = (
        "abc123def456\n"
        "abc1234\n"
        "John Doe\n"
        "john@example.com\n"
        "1700000000\n"
        "Initial commit\n"
        "---\n"
        "def789abc012\n"
        "def7890\n"
        "Jane Doe\n"
        "jane@example.com\n"
        "1700000001\n"
        "Second commit\n"
        "---\n"
    )
    commits = parse_commits(input_text)
    assert len(commits) == 2
    assert commits[0].hash == "abc123def456"
    assert commits[0].short_hash == "abc1234"
    assert commits[0].author == "John Doe"
    assert commits[0].email == "john@example.com"
    assert commits[0].timestamp == datetime.fromtimestamp(1700000000, tz=UTC)
    assert commits[0].message == "Initial commit"
    assert commits[1].hash == "def789abc012"


def test_parse_branches():
    branches = parse_branches(
        "* main                 abc1234 [origin/main] Latest changes\n"
        "  feature-x            def5678 Some feature\n"
        "  remotes/origin/main  abc1234 Latest changes\n"
    )
    assert len(branches) == 3
    assert branches[0].name == "main"
    assert branches[0].is_current
    assert branches[1].name == "feature-x"
    assert not branches[1].is_current
    assert branches[2].name == "remotes/origin/main"
    assert branches[2].is_remote


def test_parse_stashes():
    stashes = parse_stashes(
        "abc123def456\nstash@{0}\nJohn Doe\n1700000000\nWIP on feature\n---\n"
    )
    assert len(stashes) == 1
    assert stashes[0].hash == "abc123def456"
    assert stashes[0].index == 0
    assert stashes[0].message == "WIP on feature"


def test_parse_worktrees():
    worktrees = parse_worktrees(
        "worktree /home/user/project\n"
        "HEAD abc1234\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /home/user/project-feature\n"
        "HEAD def5678\n"
        "branch refs/heads/feature\n"
        "locked\n"
    )
    assert len(worktrees) == 2
    assert worktrees[0].path == "/home/user/project"
    assert worktrees[0].branch == "main"
    assert worktrees[1].branch == "feature"
    assert worktrees[1].is_locked


@pytest.mark.parametrize(
    ("input_text", "want_added", "want_deleted"),
    [
        ("+1,2 -3,4", 1, 3),
        ("+1 -3", 1, 3),
        ("+0,0 -0,0", 0, 0),
    ],
)
def test_parse_hunk_stats(input_text, want_added, want_deleted):
    added, deleted = parse_hunk_stats(input_text)
    assert added == want_added
    assert deleted == want_deleted


def test_detect_conflicts():
    conflicts = detect_conflicts(
        "Auto-merging file.go\n"
        "CONFLICT (content): Merge conflict in file.go\n"
        "CONFLICT (modify/delete): file2.go deleted in HEAD\n"
    )
    assert len(conflicts) == 2
    assert conflicts[0] == "Merge conflict in file.go"


@pytest.mark.parametrize(
    ("input_text", "want"),
    [("1", 1), ("0", 0), ("", 0), ("5,2", 5), ("abc", 0)],
)
def test_parse_count(input_text, want):
    assert parse_count(input_text) == want


@pytest.mark.parametrize(
    ("input_text", "want"),
    [
        ("abc123", True),
        ("ABC123", True),
        ("deadbeef", True),
        ("", True),
        ("xyz", False),
        ("abc123z", False),
        ("123", True),
        ("abc.123", True),
    ],
)
def test_is_hex(input_text, want):
    assert is_hex(input_text) is want


@pytest.mark.parametrize(
    ("input_text", "want"),
    [
        ("[main abc1234] Initial commit", "abc1234"),
        ("[main abc1234.] Initial commit", "abc1234"),
        ("[feature/x  def5678] Feature", "def5678"),
        ("nothing to commit", ""),
    ],
)
def test_extract_hash(input_text, want):
    assert extract_hash(input_text) == want


def test_runner_current_branch(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")
    assert repo.current_branch() == "master"
    _git(repo.work_dir, "checkout", "-b", "test-branch")
    assert repo.current_branch() == "test-branch"


def test_runner_root(repo):
    root = repo.root()
    assert root.endswith(repo.work_dir)


def test_runner_status(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")

    status = repo.status()
    assert status.branch == "master"
    assert status.unstaged == []
    assert status.staged == []
    assert status.untracked == []

    pathlib.Path(repo.work_dir, "file.txt").write_text("change\n")
    status = repo.status()
    assert len(status.untracked) == 1
    assert status.untracked[0] == "file.txt"

    _git(repo.work_dir, "add", "file.txt")
    status = repo.status()
    assert len(status.staged) == 1


def test_runner_log(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "first")
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "second")
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "third")

    commits = repo.log(LogOptions(limit=2))
    assert len(commits) == 2
    assert commits[0].message == "third"
    assert commits[1].message == "second"
    assert commits[0].hash != ""
    assert commits[0].short_hash != ""
    assert commits[0].author == "Test User"


def test_runner_add_commit(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")


    pathlib.Path(repo.work_dir, "test.txt").write_text("content\n")
    repo.add("test.txt")

    author = AuthorInfo(name="Test User", email="test@example.com")
    info = repo.commit("add test.txt", author)
    assert info.hash != ""
    assert info.short_hash != ""
    assert info.message == "add test.txt"

    commits = repo.log(LogOptions(limit=1))
    assert len(commits) == 1
    assert commits[0].message == "add test.txt"


def test_runner_branch(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")
    _git(repo.work_dir, "checkout", "-b", "feature-a")
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "feature a work")
    _git(repo.work_dir, "checkout", "-b", "feature-b")

    branches = repo.branch()
    assert len(branches) >= 2
    current = [b for b in branches if b.is_current]
    assert len(current) == 1
    assert current[0].name == "feature-b"
    names = [b.name for b in branches]
    assert "feature-a" in names


def test_runner_diff(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")


    pathlib.Path(repo.work_dir, "diff.txt").write_text("line1\n")
    _git(repo.work_dir, "add", "diff.txt")
    _git(repo.work_dir, "commit", "-m", "add diff.txt")
    pathlib.Path(repo.work_dir, "diff.txt").write_text("line1\nline2\n")

    diff = repo.diff(staged=False, path="")
    assert diff.stats.files_changed > 0
    assert diff.stats.additions > 0

    staged = repo.diff(staged=True, path="")
    assert staged.stats.files_changed == 0


def test_runner_stash(repo):
    _git(repo.work_dir, "commit", "--allow-empty", "-m", "init")


    pathlib.Path(repo.work_dir, "stash.txt").write_text("stash-content\n")
    _git(repo.work_dir, "add", "stash.txt")

    repo.stash("test stash")

    stashes = repo.stash_list()
    assert len(stashes) == 1
    assert stashes[0].message == "On master: test stash"
    assert stashes[0].index == 0
    assert stashes[0].hash != ""

    repo.stash_pop(0)
    stashes = repo.stash_list()
    assert len(stashes) == 0

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
