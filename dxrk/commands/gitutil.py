# SPDX-License-Identifier: MIT
"""Shared git helpers for command modules."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass


@dataclass
class GitResult:
    """Result of a raw git invocation."""

    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def run_git(wd: str, *args: str) -> GitResult:
    """Runs `git` with the given arguments in wd, capturing output."""
    env = dict(os.environ)
    env.setdefault("GIT_CONFIG_GLOBAL", os.devnull)
    env.setdefault("GIT_CONFIG_SYSTEM", os.devnull)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=wd,
            capture_output=True,
            text=True,
            env=env,
        )
    except OSError as exc:
        return GitResult(1, "", str(exc))
    return GitResult(result.returncode, result.stdout, result.stderr)


def git_dir(wd: str) -> GitResult:
    """Resolves the git directory; fails if wd is not inside a repository."""
    return run_git(wd, "rev-parse", "--git-dir")


def git_status_porcelain(wd: str) -> GitResult:
    """Returns `git status --porcelain` output."""
    return run_git(wd, "status", "--porcelain")


def git_diff(wd: str, since: str | None = None, until: str | None = None) -> GitResult:
    """Runs `git diff` (optionally between two refs)."""
    if since is not None:
        ref = since if until is None else f"{since}..{until}"
        return run_git(wd, "diff", ref, "HEAD")
    return run_git(wd, "diff")


def git_diff_cached(wd: str) -> GitResult:
    """Runs `git diff --cached`."""
    return run_git(wd, "diff", "--cached")


def git_current_branch(wd: str) -> str | None:
    """Returns the current branch name, or None when detached."""
    result = run_git(wd, "symbolic-ref", "--short", "HEAD")
    if not result.ok:
        return None
    return result.out.strip()


def git_default_branch(wd: str) -> str:
    """Resolves the repository's default branch (origin/HEAD -> main fallback)."""
    result = run_git(wd, "symbolic-ref", "refs/remotes/origin/HEAD")
    if result.ok:
        ref = result.out.strip()
        name = ref.rsplit("/", 1)[-1]
        if name:
            return name
    return "main"


def git_diff_stats(diff: str) -> tuple[int, int, int]:
    """Counts files changed, insertions and deletions from a diff."""
    files = 0
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m:
            files += 1
            continue
        m = re.match(r"^\+([^+].*)$", line)
        if m:
            additions += 1
            continue
        m = re.match(r"^-([^-].*)$", line)
        if m:
            deletions += 1
            continue
    return files, additions, deletions


_CONVENTIONAL_TYPES = (
    "feat",
    "fix",
    "chore",
    "docs",
    "refactor",
    "test",
    "style",
    "perf",
    "ci",
)

_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "feat": ("add", "create", "implement", "support", "feature", "new"),
    "fix": ("fix", "bug", "repair", "correct", "resolve"),
    "docs": ("doc", "readme", "comment", "document"),
    "test": ("test", "spec"),
    "perf": ("perf", "optimize", "speed", "fast", "benchmark"),
    "style": ("style", "format", "lint"),
    "refactor": ("refactor", "rename", "move", "extract", "clean"),
    "ci": ("ci", "pipeline", "action", "workflow"),
    "chore": ("update", "bump", "upgrade", "downgrade", "pin", "config", "dep", "version"),
}


def generate_commit_message(diff: str, staged: bool = False) -> str:
    """Generates a conventional commit message from a diff."""
    files: list[str] = []
    for line in diff.splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m and m.group(1) != "/dev/null":
            files.append(m.group(1))

    lower = diff.lower()
    commit_type = "chore"
    for typ in _CONVENTIONAL_TYPES:
        if any(kw in lower for kw in _TYPE_KEYWORDS.get(typ, ())):
            commit_type = typ
            break
    if not files:
        return f"{commit_type}: update"

    scope = os.path.basename(os.path.dirname(files[0])) or "app"
    if len(files) == 1:
        subject = f"{commit_type}({scope}): update {os.path.basename(files[0])}"
    else:
        subject = f"{commit_type}({scope}): update {len(files)} files"

    return subject


def run_gh(wd: str, *args: str) -> GitResult:
    """Runs `gh` with the given arguments, capturing output."""
    try:
        result = subprocess.run(
            ["gh", *args],
            cwd=wd,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return GitResult(1, "", str(exc))
    return GitResult(result.returncode, result.stdout, result.stderr)


def detect_gh() -> bool:
    """Returns True when the GitHub CLI is available."""
    try:
        subprocess.run(["gh", "--version"], capture_output=True, text=True, check=False)
        return True
    except OSError:
        return False
