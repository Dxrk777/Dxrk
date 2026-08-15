# SPDX-License-Identifier: MIT
"""Files command"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from .gitutil import run_git
from .registry import Command, CommandContext, Flag, Registry

_IGNORE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".dxrk",
}


def _human_size(size: int) -> str:
    if size >= 1_048_576:
        return f"{size / 1_048_576:.1f}M"
    if size >= 1024:
        return f"{size / 1024:.1f}K"
    return str(size)


def _recent_files(
    wd: str, limit: int, tracked_only: bool
) -> list[tuple[str, float, str, str]]:
    files: list[tuple[str, float, str, str]] = []
    if tracked_only:
        result = run_git(wd, "ls-files")
        if not result.ok:
            return files
        for rel in result.out.splitlines():
            if not rel:
                continue
            full = os.path.join(wd, rel)
            try:
                mtime = os.path.getmtime(full)
                size = os.path.getsize(full)
            except OSError:
                continue
            files.append(("f", mtime, rel, _human_size(size)))
        files.sort(key=lambda item: item[1], reverse=True)
        return files[:limit]

    for root, dirs, names in os.walk(wd):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for name in names:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, wd)
            try:
                mtime = os.path.getmtime(full)
                size = os.path.getsize(full)
            except OSError:
                continue
            files.append(("f", mtime, rel, _human_size(size)))
    files.sort(key=lambda item: item[1], reverse=True)
    return files[:limit]


def register_files_command(reg: Registry) -> None:
    """Registers the `dxrk files` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd
        limit = 20
        raw_limit = ctx.flag_str("limit", "")
        if raw_limit:
            try:
                limit = max(1, int(raw_limit))
            except ValueError:
                ctx.err.write(f"Error: invalid limit: {raw_limit}\n")
                return 1

        tracked_only = ctx.flag_bool("tracked")
        files = _recent_files(wd, limit, tracked_only)

        out.write(f"Recent files in {os.path.abspath(wd)}\n")
        out.write("──────────────────\n")
        if not files:
            out.write("  No files found.\n")
            return 0
        for kind, mtime, rel, size in files:
            when = datetime.fromtimestamp(mtime, tz=UTC).strftime(
                "%Y-%m-%d %H:%M"
            )
            out.write(f"  {kind}{rel:<40}  {size:<8}  {when}\n")
        return 0

    cmd = Command(
        name="files",
        short="List recent files",
        flags={
            "limit": Flag(
                "limit", default="", shorthand="n", help="Maximum number of files"
            ),
            "tracked": Flag(
                "tracked", is_bool=True, default=False, help="Only git-tracked files"
            ),
        },
        run=run,
    )
    reg.add_command(cmd)
