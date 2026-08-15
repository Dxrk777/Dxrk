# SPDX-License-Identifier: MIT
"""Git runner"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime

from dxrk.strconst import StrStatus


@dataclass
class Repo:
    path: str = ""
    worktree: str = ""
    remote_url: str = ""
    current_branch: str = ""
    is_worktree: bool = False


@dataclass
class CommitInfo:
    hash: str = ""
    short_hash: str = ""
    author: str = ""
    email: str = ""
    message: str = ""
    timestamp: datetime | None = None
    files: list[str] = field(default_factory=list)


@dataclass
class DiffStats:
    files_changed: int = 0
    additions: int = 0
    deletions: int = 0


@dataclass
class DiffFile:
    path: str = ""
    old_path: str = ""
    status: str = ""
    additions: int = 0
    deletions: int = 0
    is_binary: bool = False
    content: str = ""


@dataclass
class DiffResult:
    files: list[DiffFile] = field(default_factory=list)
    stats: DiffStats = field(default_factory=DiffStats)


@dataclass
class StatusEntry:
    path: str = ""
    index: str = ""
    work: str = ""


@dataclass
class StatusResult:
    branch: str = ""
    ahead: int = 0
    behind: int = 0
    staged: list[StatusEntry] = field(default_factory=list)
    unstaged: list[StatusEntry] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


@dataclass
class LogOptions:
    limit: int = 0
    since: datetime | None = None
    until: datetime | None = None
    author: str = ""
    path: str = ""
    all_branches: bool = False
    oneline: bool = False


@dataclass
class BranchInfo:
    name: str = ""
    hash: str = ""
    is_current: bool = False
    is_remote: bool = False
    upstream: str = ""
    ahead: int = 0
    behind: int = 0
    last_commit: CommitInfo | None = None


@dataclass
class RemoteInfo:
    name: str = ""
    url: str = ""
    fetch: str = ""
    push: str = ""


@dataclass
class TagInfo:
    name: str = ""
    hash: str = ""
    message: str = ""
    tagger: str = ""
    timestamp: datetime | None = None
    is_annotated: bool = False


@dataclass
class StashEntry:
    index: int = 0
    hash: str = ""
    branch: str = ""
    message: str = ""
    timestamp: datetime | None = None


@dataclass
class WorktreeInfo:
    path: str = ""
    branch: str = ""
    hash: str = ""
    is_bare: bool = False
    is_detached: bool = False
    is_locked: bool = False


@dataclass
class PRConfig:
    title: str = ""
    body: str = ""
    base_branch: str = ""
    head_branch: str = ""
    draft: bool = False
    reviewers: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)


@dataclass
class PRInfo:
    number: int = 0
    title: str = ""
    body: str = ""
    state: str = ""
    base_branch: str = ""
    head_branch: str = ""
    url: str = ""
    author: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    merged_at: datetime | None = None
    labels: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    commits: int = 0
    changes: int = 0


@dataclass
class MergeResult:
    success: bool = False
    commit_hash: str = ""
    conflicts: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class RebaseResult:
    success: bool = False
    commit_hash: str = ""
    conflicts: list[str] = field(default_factory=list)
    steps: int = 0
    message: str = ""


@dataclass
class PushResult:
    success: bool = False
    remote_refs: list[str] = field(default_factory=list)
    message: str = ""
    force_pushed: bool = False


@dataclass
class FetchResult:
    success: bool = False
    refs: list[str] = field(default_factory=list)
    pruned: int = 0
    message: str = ""


@dataclass
class PullResult:
    success: bool = False
    merge_commit: str = ""
    fast_forward: bool = False
    conflicts: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class ConfigOptions:
    global_: bool = False
    local: bool = False
    system: bool = False
    file_path: str = ""


@dataclass
class AuthorInfo:
    name: str = ""
    email: str = ""


def _parse_int(s: str) -> int:
    try:
        return int(s)
    except ValueError:
        return 0


def _trim_one(s: str, prefix: str) -> str:
    return s[len(prefix) :] if s.startswith(prefix) else s


def parse_status(s: str) -> StatusResult:
    res = StatusResult()
    for line in s.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("# branch.head "):
            res.branch = line[len("# branch.head ") :]
            continue
        if line.startswith("# branch.ab +"):
            rest = line[len("# branch.ab +") :]
            parts = rest.split(" -", 1)
            if len(parts) == 2:
                res.ahead = _parse_int(parts[0])
                res.behind = _parse_int(parts[1])
            continue
        if line.startswith("1 ") or line.startswith("2 "):
            fields = line.split()
            if len(fields) >= 3:
                xy = fields[1]
                path = fields[-1]
                index = xy[0] if len(xy) >= 2 else xy
                work = xy[1] if len(xy) >= 2 else "."
                entry = StatusEntry(path=path, index=index, work=work)
                if index != "." and index != " ":
                    res.staged.append(entry)
                if work != "." and work != " ":
                    res.unstaged.append(entry)
            continue
        if line.startswith("? "):
            res.untracked.append(line[2:].strip())
            continue
        if line.startswith("u "):
            fields = line.split()
            if len(fields) >= 2:
                res.conflicts.append(fields[-1])
    return res


def parse_count(s: str) -> int:
    if "," in s:
        s = s.split(",", 1)[0]
    return _parse_int(s)


def parse_hunk_stats(s: str) -> tuple[int, int]:
    parts = s.split(" ")
    if len(parts) < 2:
        return 0, 0
    added = parse_count(_trim_one(parts[0], "+"))
    deleted = parse_count(_trim_one(parts[1], "-"))
    return added, deleted


def parse_diff(s: str) -> DiffResult:
    res = DiffResult()
    lines = s.split("\n")
    cur: DiffFile | None = None
    for line in lines:
        if line.startswith("diff --git "):
            if cur is not None:
                res.files.append(cur)
            cur = DiffFile()
            parts = line.split(" ")
            if len(parts) >= 4:
                cur.path = _trim_one(parts[-1], "b/")
            continue
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if line.startswith("@@"):
            if cur is not None:
                parts = line.split(" ")
                if len(parts) >= 3:
                    added, deleted = parse_hunk_stats(parts[2])
                    cur.additions += added
                    cur.deletions += deleted
        if cur is not None:
            cur.content += line + "\n"
            if line.startswith("+") and not line.startswith("+++"):
                cur.additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                cur.deletions += 1
    if cur is not None:
        res.files.append(cur)
    for f in res.files:
        res.stats.files_changed += 1
        res.stats.additions += f.additions
        res.stats.deletions += f.deletions
    return res


def parse_commits(s: str) -> list[CommitInfo]:
    commits: list[CommitInfo] = []
    for block in s.split("---\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n", 6)
        if len(lines) < 6:
            continue
        commits.append(
            CommitInfo(
                hash=lines[0],
                short_hash=lines[1],
                author=lines[2],
                email=lines[3],
                timestamp=datetime.fromtimestamp(_parse_int(lines[4]), tz=UTC),
                message=lines[5],
            )
        )
    return commits


def extract_hash(s: str) -> str:
    for line in s.split("\n"):
        if not line.startswith("["):
            continue
        close_idx = line.find("]")
        if close_idx < 0:
            continue
        inner = line[1:close_idx]
        for part in inner.split():
            if len(part) >= 7 and is_hex(part):
                return part.rstrip(".")
    return ""


def is_hex(s: str) -> bool:
    return all(c in "0123456789abcdefABCDEF." for c in s)


def parse_branches(s: str) -> list[BranchInfo]:
    branches: list[BranchInfo] = []
    for line in s.split("\n"):
        line = line.strip()
        if not line:
            continue
        bi = BranchInfo(is_current=line.startswith("* "))
        rest = line.lstrip("* ")
        parts = rest.split()
        if parts:
            bi.name = parts[0]
        if len(parts) > 1:
            bi.hash = parts[1]
        bi.is_remote = bi.name.startswith("remotes/")
        branches.append(bi)
    return branches


def _stash_index(line: str) -> int:
    prefix = "stash@{"
    if line.startswith(prefix) and line.endswith("}"):
        return _parse_int(line[len(prefix) : -1])
    return 0


def parse_stashes(s: str) -> list[StashEntry]:
    stashes: list[StashEntry] = []
    for block in s.split("---\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n", 5)
        if len(lines) < 5:
            continue
        stashes.append(
            StashEntry(
                index=_stash_index(lines[1]),
                hash=lines[0],
                message=lines[4],
                timestamp=datetime.fromtimestamp(_parse_int(lines[3]), tz=UTC),
            )
        )
    return stashes


def parse_worktrees(s: str) -> list[WorktreeInfo]:
    worktrees: list[WorktreeInfo] = []
    cur: WorktreeInfo | None = None
    for line in s.split("\n"):
        line = line.strip()
        if not line:
            if cur is not None:
                worktrees.append(cur)
                cur = None
            continue
        if line.startswith("worktree "):
            if cur is not None:
                worktrees.append(cur)
            cur = WorktreeInfo(path=line[len("worktree ") :])
            continue
        if cur is None:
            continue
        if line.startswith("HEAD "):
            cur.hash = line[len("HEAD ") :]
            continue
        if line.startswith("branch refs/heads/"):
            cur.branch = line[len("branch refs/heads/") :]
            continue
        if line == "bare":
            cur.is_bare = True
            continue
        if line == "detached":
            cur.is_detached = True
            continue
        if line.startswith("locked"):
            cur.is_locked = True
    if cur is not None:
        worktrees.append(cur)
    return worktrees


def detect_conflicts(s: str) -> list[str]:
    conflicts: list[str] = []
    for line in s.split("\n"):
        if not line.startswith("CONFLICT"):
            continue
        marker = ": "
        if marker in line:
            desc = line[line.index(marker) + len(marker) :]
        else:
            desc = line
        conflicts.append(desc.rstrip("."))
    return conflicts


class Runner:
    def __init__(self, work_dir: str):
        self.work_dir = work_dir

    def _run(
        self,
        args: list[str],
        *,
        binary: str = "git",
        stdin: str | None = None,
    ) -> tuple[str, str, int]:
        proc = subprocess.run(
            [binary, *args],
            cwd=self.work_dir,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode

    def status(self) -> StatusResult:
        stdout, stderr, rc = self._run([StrStatus, "--porcelain=v2", "--branch"])
        if rc != 0:
            raise RuntimeError(f"git status: {stderr}")
        return parse_status(stdout)

    def diff(self, staged: bool, path: str) -> DiffResult:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if path:
            args.extend(["--", path])
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git diff: {stderr}")
        return parse_diff(stdout)

    def log(self, opts: LogOptions) -> list[CommitInfo]:
        args = ["log", "--format=%H%n%h%n%an%n%ae%n%ct%n%s%n---"]
        if opts.limit > 0:
            args.append(f"-{opts.limit}")
        if opts.since is not None:
            args.append("--since=" + _format_rfc3339(opts.since))
        if opts.author:
            args.append("--author=" + opts.author)
        if opts.all_branches:
            args.append("--all")
        if opts.path:
            args.extend(["--", opts.path])
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git log: {stderr}")
        return parse_commits(stdout)

    def add(self, *files: str) -> None:
        args = ["add", *files]
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git add: {stderr}")

    def commit(self, msg: str, author: AuthorInfo | None = None) -> CommitInfo:
        args = ["commit", "-m", msg]
        if author is not None and author.name:
            args.append(f"--author={author.name} <{author.email}>")
        args.append("--allow-empty")
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git commit: {stderr}")
        hash = extract_hash(stdout)
        info = CommitInfo(hash=hash, message=msg, timestamp=datetime.now(UTC))
        if len(hash) >= 7:
            info.short_hash = hash[:7]
        return info

    def branch(self, all_branches: bool = False) -> list[BranchInfo]:
        args = ["branch", "-vv"]
        if all_branches:
            args.append("-a")
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git branch: {stderr}")
        return parse_branches(stdout)

    def checkout(self, branch: str, create: bool = False) -> None:
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch)
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git checkout: {stderr}")

    def push(self, remote: str, branch: str, force: bool = False) -> PushResult:
        args = ["push"]
        if force:
            args.append("--force")
        args.extend([remote, branch])
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git push: {stderr}")
        return PushResult(success=True, message=stdout + "\n" + stderr)

    def pull(
        self, remote: str = "", branch: str = "", rebase: bool = False
    ) -> PullResult:
        args = ["pull"]
        if rebase:
            args.append("--rebase")
        if remote:
            args.append(remote)
        if branch:
            args.append(branch)
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git pull: {stderr}")
        return PullResult(success=True, message=stdout + "\n" + stderr)

    def stash(self, msg: str = "") -> None:
        args = ["stash", "push"]
        if msg:
            args.extend(["-m", msg])
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git stash: {stderr}")

    def stash_pop(self, index: int = -1) -> None:
        args = ["stash", "pop"]
        if index >= 0:
            args.append(f"stash@{{{index}}}")
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git stash pop: {stderr}")

    def stash_list(self) -> list[StashEntry]:
        args = ["stash", "list", "--format=%H%n%gd%n%an%n%ct%n%s%n---"]
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git stash list: {stderr}")
        return parse_stashes(stdout)

    def fetch(self, remote: str = "", prune: bool = False) -> FetchResult:
        args = ["fetch"]
        if prune:
            args.append("--prune")
        if remote:
            args.append(remote)
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git fetch: {stderr}")
        pruned = sum(1 for line in stdout.split("\n") if "[pruned]" in line)
        return FetchResult(success=True, pruned=pruned, message=stdout + "\n" + stderr)

    def merge(self, branch: str, ff_only: bool = False) -> MergeResult:
        args = ["merge"]
        if ff_only:
            args.append("--ff-only")
        args.append(branch)
        stdout, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git merge: {stderr}")
        return MergeResult(success=True, message=stdout + "\n" + stderr)

    def remote(self) -> list[RemoteInfo]:
        stdout, stderr, rc = self._run(["remote", "-v"])
        if rc != 0:
            raise RuntimeError(f"git remote: {stderr}")
        seen: dict[str, RemoteInfo] = {}
        for line in stdout.split("\n"):
            parts = line.split()
            if len(parts) < 3:
                continue
            name, url, ref = parts[0], parts[1], parts[2]
            ri = seen.get(name)
            if ri is None:
                ri = RemoteInfo(name=name, url=url)
                seen[name] = ri
            if ref == "(fetch)":
                ri.fetch = url
            elif ref == "(push)":
                ri.push = url
        return list(seen.values())

    def worktree_list(self) -> list[WorktreeInfo]:
        stdout, stderr, rc = self._run(["worktree", "list", "--porcelain"])
        if rc != 0:
            raise RuntimeError(f"git worktree list: {stderr}")
        return parse_worktrees(stdout)

    def worktree_add(self, path: str, branch: str = "") -> None:
        args = ["worktree", "add", path]
        if branch:
            args.append(branch)
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git worktree add: {stderr}")

    def worktree_remove(self, path: str, force: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(path)
        _, stderr, rc = self._run(args)
        if rc != 0:
            raise RuntimeError(f"git worktree remove: {stderr}")

    def create_pr(self, cfg: PRConfig) -> PRInfo:
        args = ["pr", "create", "--title", cfg.title, "--body", cfg.body]
        if cfg.base_branch:
            args.extend(["--base", cfg.base_branch])
        if cfg.head_branch:
            args.extend(["--head", cfg.head_branch])
        if cfg.draft:
            args.append("--draft")
        for label in cfg.labels:
            args.extend(["--label", label])
        for reviewer in cfg.reviewers:
            args.extend(["--reviewer", reviewer])
        for assignee in cfg.assignees:
            args.extend(["--assignee", assignee])
        stdout, stderr, rc = self._run(args, binary="gh", stdin=cfg.body)
        if rc != 0:
            raise RuntimeError(f"gh pr create: {stderr}")
        return PRInfo(url=stdout.strip(), body=cfg.body)

    def root(self) -> str:
        stdout, stderr, rc = self._run(["rev-parse", "--show-toplevel"])
        if rc != 0:
            raise RuntimeError(f"git rev-parse: {stderr}")
        return stdout

    def current_branch(self) -> str:
        stdout, stderr, rc = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        if rc != 0:
            raise RuntimeError(f"git rev-parse: {stderr}")
        return stdout


def _format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
