# SPDX-License-Identifier: MIT
"""Miner pipeline — chunk_text + scan_project with GitignoreMatcher, stdlib only."""

from __future__ import annotations

import errno
import fnmatch
import os
import re
import stat
import sys
from pathlib import Path

from .palace import CHUNK_OVERLAP, CHUNK_SIZE, MIN_CHUNK_SIZE
from .palace import chunk_text as _chunk_text

READABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".html",
        ".css",
        ".java",
        ".go",
        ".rs",
        ".rb",
        ".sh",
        ".csv",
        ".sql",
        ".toml",
    }
)

SKIP_FILENAMES: frozenset[str] = frozenset(
    {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", ".gitignore", "dxrk.yaml", "dxrk.yml"}
)

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
        ".dxrk",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".cache",
        ".tox",
        ".nox",
        ".idea",
        ".vscode",
        ".ipynb_checkpoints",
        ".eggs",
        "htmlcov",
        "target",
    }
)

MAX_FILE_SIZE = 500 * 1024 * 1024

# ---------------------------------------------------------------------------
# Non-regular file guards (port of db29959)
# ---------------------------------------------------------------------------


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _is_regular_source_file(filepath: Path, root: Path) -> bool:
    """Return True only for regular files — never block on FIFO/socket."""
    if not _path_within_root(filepath, root):
        return False
    # O_NONBLOCK makes the S_ISREG check reachable: opening a FIFO for reading
    # normally blocks until a writer appears. With O_NONBLOCK the open returns
    # immediately and the file type decides (FIFO guarded, non-blocking open).
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = -1
    try:
        try:
            fd = os.open(filepath, flags)
        except OSError as exc:
            if exc.errno != errno.EAGAIN or not stat.S_ISREG(os.lstat(filepath).st_mode):
                return False
            fd = os.open(filepath, flags & ~getattr(os, "O_NONBLOCK", 0))
        st = os.fstat(fd)
        return stat.S_ISREG(st.st_mode) and st.st_size <= MAX_FILE_SIZE
    except OSError:
        return False
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass


def _read_text_no_follow(filepath: Path, root: Path) -> tuple[str, float] | None:
    """Safe read returning (content, mtime) or None for non-regular/too-large."""
    if not _path_within_root(filepath, root):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = -1
    try:
        try:
            fd = os.open(filepath, flags)
        except OSError as exc:
            if exc.errno != errno.EAGAIN or not stat.S_ISREG(os.lstat(filepath).st_mode):
                return None
            fd = os.open(filepath, flags & ~getattr(os, "O_NONBLOCK", 0))
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_SIZE:
            return None
        mtime = st.st_mtime
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as f:
            fd = -1
            return f.read(), mtime
    except OSError:
        return None
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass


def _is_regular_file(path: Path) -> bool:
    """Lightweight S_ISREG check without opening (for discovery walks)."""
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except OSError:
        return False


def chunk_text(
    content: str,
    source_file: str = "",
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    min_chunk_size: int = MIN_CHUNK_SIZE,
) -> list[dict[str, object]]:
    return _chunk_text(content, source_file, chunk_size, chunk_overlap, min_chunk_size)


# ---------------------------------------------------------------------------
# Gitignore matcher (port of miner.py 156-276)
# ---------------------------------------------------------------------------


class GitignoreMatcher:
    """Lightweight matcher for one directory's .gitignore."""

    def __init__(self, base_dir: Path, rules: list[dict[str, object]]) -> None:
        self.base_dir = base_dir
        self.rules = rules

    @classmethod
    def from_dir(cls, dir_path: Path) -> GitignoreMatcher | None:
        gip = dir_path / ".gitignore"
        if not gip.is_file():
            return None
        try:
            lines = gip.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None
        rules: list[dict[str, object]] = []
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("\\#") or line.startswith("\\!"):
                line = line[1:]
            elif line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")
            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")
            if not line:
                continue
            rules.append({"pattern": line, "anchored": anchored, "dir_only": dir_only, "negated": negated})
        if not rules:
            return None
        return cls(dir_path, rules)

    def matches(self, path: Path, is_dir: bool | None = None) -> bool | None:
        try:
            relative = path.relative_to(self.base_dir).as_posix().strip("/")
        except ValueError:
            return None
        if not relative:
            return None
        if is_dir is None:
            is_dir = path.is_dir()
        ignored: bool | None = None
        for rule in self.rules:
            if self._rule_matches(rule, relative, bool(is_dir)):
                ignored = not bool(rule["negated"])
        return ignored

    def _rule_matches(self, rule: dict[str, object], relative: str, is_dir: bool) -> bool:
        pattern = str(rule["pattern"])
        parts = relative.split("/")
        pattern_parts = pattern.split("/")
        if bool(rule["dir_only"]):
            target = parts if is_dir else parts[:-1]
            if not target:
                return False
            if bool(rule["anchored"]) or len(pattern_parts) > 1:
                return self._match_from_root(target, pattern_parts)
            return any(fnmatch.fnmatch(p, pattern) for p in target)
        if bool(rule["anchored"]) or len(pattern_parts) > 1:
            return self._match_from_root(parts, pattern_parts)
        return any(fnmatch.fnmatch(p, pattern) for p in parts)

    def _match_from_root(self, target_parts: list[str], pattern_parts: list[str]) -> bool:
        def match(pi: int, ti: int) -> bool:
            if ti == len(pattern_parts):
                return True
            if pi == len(target_parts):
                return all(p == "**" for p in pattern_parts[ti:])
            pat = pattern_parts[ti]
            if pat == "**":
                return match(pi, ti + 1) or match(pi + 1, ti)
            if not fnmatch.fnmatch(target_parts[pi], pat):
                return False
            return match(pi + 1, ti + 1)

        return match(0, 0)


def load_gitignore_matcher(dir_path: Path, cache: dict[Path, GitignoreMatcher | None]) -> GitignoreMatcher | None:
    if dir_path not in cache:
        cache[dir_path] = GitignoreMatcher.from_dir(dir_path)
    return cache[dir_path]


def is_gitignored(path: Path, matchers: list[GitignoreMatcher], is_dir: bool = False) -> bool:
    ignored = False
    for m in matchers:
        d = m.matches(path, is_dir=is_dir)
        if d is not None:
            ignored = d
    return ignored


def should_skip_dir(dirname: str) -> bool:
    return dirname in SKIP_DIRS or dirname.endswith(".egg-info")


def normalize_include_paths(include_ignored: list[str] | None) -> set[str]:
    out: set[str] = set()
    for raw in include_ignored or []:
        cand = str(raw).strip().strip("/")
        if cand:
            out.add(Path(cand).as_posix())
    return out


def is_force_included(path: Path, project_path: Path, include_paths: set[str]) -> bool:
    if not include_paths:
        return False
    try:
        rel = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False
    if not rel:
        return False
    for inc in include_paths:
        if rel == inc or rel.startswith(f"{inc}/") or inc.startswith(f"{rel}/"):
            return True
    return False


def is_exact_force_include(path: Path, project_path: Path, include_paths: set[str]) -> bool:
    if not include_paths:
        return False
    try:
        rel = path.relative_to(project_path).as_posix().strip("/")
    except ValueError:
        return False
    return rel in include_paths


def scan_project(
    project_dir: str | Path,
    respect_gitignore: bool = True,
    include_ignored: list[str] | None = None,
) -> list[Path]:
    """Return list of readable file paths under project_dir."""
    project_path = Path(project_dir).expanduser().resolve()
    files: list[Path] = []
    active: list[GitignoreMatcher] = []
    cache: dict[Path, GitignoreMatcher | None] = {}
    include_paths = normalize_include_paths(include_ignored)
    for root, dirs, filenames in os.walk(project_path):
        root_path = Path(root)
        if respect_gitignore:
            active = [m for m in active if root_path == m.base_dir or m.base_dir in root_path.parents]
            cur = load_gitignore_matcher(root_path, cache)
            if cur is not None:
                active.append(cur)
        dirs[:] = [
            d for d in dirs if is_force_included(root_path / d, project_path, include_paths) or not should_skip_dir(d)
        ]
        if respect_gitignore and active:
            dirs[:] = [
                d
                for d in dirs
                if is_force_included(root_path / d, project_path, include_paths)
                or not is_gitignored(root_path / d, active, is_dir=True)
            ]
        for filename in filenames:
            filepath = root_path / filename
            force = is_force_included(filepath, project_path, include_paths)
            exact = is_exact_force_include(filepath, project_path, include_paths)
            if not force and filename in SKIP_FILENAMES:
                continue
            if filepath.suffix.lower() not in READABLE_EXTENSIONS and not exact:
                continue
            if respect_gitignore and active and not force and is_gitignored(filepath, active, is_dir=False):
                continue
            if filepath.is_symlink():
                continue
            try:
                file_stat = filepath.stat()
                # Reject non-regular files before any reader touches them.
                # os.walk lists FIFOs/sockets as plain filenames; opening
                # them would block forever (db29959).
                if not stat.S_ISREG(file_stat.st_mode):
                    print(f"  SKIP: {filepath.name} (not a regular file)", file=sys.stderr)
                    continue
                if file_stat.st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            files.append(filepath)
    return files


def normalize_content(content: str) -> str:
    """Simplified normalize — strip, handle 7 formats loosely."""
    # For now, just strip and normalize whitespace; placeholder for 7-format logic
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    # remove excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def scan_and_chunk(
    project_dir: str | Path,
    wing: str = "default",
    room: str = "general",
) -> list[tuple[Path, list[dict[str, object]]]]:
    """Scan project and chunk each file — helper for Palace ingestion."""
    project_path = Path(project_dir).expanduser().resolve()
    out: list[tuple[Path, list[dict[str, object]]]] = []
    for fp in scan_project(project_dir):
        # Double-guard: scan_project already filtered non-regular files,
        # but a TOCTOU race could replace it with a FIFO before read.
        # _read_text_no_follow uses O_NONBLOCK so it never blocks.
        result = _read_text_no_follow(fp, project_path)
        if result is None:
            continue
        raw, _ = result
        norm = normalize_content(raw)
        chunks = chunk_text(norm, str(fp))
        if chunks:
            _ = wing
            _ = room
            out.append((fp, chunks))
    return out
