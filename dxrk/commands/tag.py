# SPDX-License-Identifier: MIT
"""Tag management commands"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry, go_quote
from .session import (
    SessionError,
    _find_session,
    _fmt_ts_short,
    list_session_files,
    load_session,
    save_session,
)


def tag_add_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]
        tag_name = ctx.args[1].strip()
        if tag_name == "":
            ctx.err.write("Error: tag name cannot be empty\n")
            return 1

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        s = _find_session(sessions, session_id)
        if s is None:
            ctx.err.write(f"Error: session {go_quote(session_id)} not found\n")
            return 1

        for t in s.tags:
            if t == tag_name:
                out.write(f"Tag {go_quote(tag_name)} already exists on session {s.id[:8]}\n")
                return 0

        s.tags.append(tag_name)
        if not save_session(s):
            ctx.err.write("Error: save tagged session\n")
            return 1
        out.write(f"Added tag {go_quote(tag_name)} to session {s.id[:8]} — {s.title}\n")
        return 0

    return Command(name="tag add", short="Add a tag to a session", min_args=2, max_args=2, run=run)


def tag_remove_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]
        tag_name = ctx.args[1]

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        s = _find_session(sessions, session_id)
        if s is None:
            ctx.err.write(f"Error: session {go_quote(session_id)} not found\n")
            return 1

        filtered: list[str] = []
        found = False
        for t in s.tags:
            if t == tag_name:
                found = True
                continue
            filtered.append(t)

        if not found:
            ctx.err.write(
                f"Error: tag {go_quote(tag_name)} not found on session {s.id[:8]}\n"
            )
            return 1

        s.tags = filtered
        if not save_session(s):
            ctx.err.write("Error: save session\n")
            return 1
        out.write(f"Removed tag {go_quote(tag_name)} from session {s.id[:8]}\n")
        return 0

    return Command(name="tag remove", short="Remove a tag from a session", min_args=2, max_args=2, run=run)


def tag_list_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        try:
            s = load_session(ctx.args[0])
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        if not s.tags:
            out.write(f"Session {s.id[:8]} has no tags.\n")
            return 0

        out.write(f"Tags for session {s.id[:8]} ({s.title}):\n")
        for t in s.tags:
            out.write(f"  - {t}\n")
        return 0

    return Command(name="tag list", short="List tags on a session", min_args=1, max_args=1, run=run)


def tag_search_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        tag_name = ctx.args[0]

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        matches = [s for s in sessions if tag_name in s.tags]

        if not matches:
            out.write(f"No sessions found with tag {go_quote(tag_name)}\n")
            return 0

        out.write(f"Sessions with tag {go_quote(tag_name)} ({len(matches)}):\n\n")
        for s in matches:
            title = s.title
            if len(title) > 40:
                title = title[:37] + "..."
            out.write(f"  {s.id[:8]}  {title:<40}  {_fmt_ts_short(s.updated_at)}\n")
        return 0

    return Command(name="tag search", short="Find sessions with a specific tag", min_args=1, max_args=1, run=run)


def tag_parent_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        ctx.err.write("Error: use 'dxrk tag add', 'remove', 'list', or 'search'\n")
        return 1

    return Command(
        name="tag",
        short="Manage session tags",
        long="Add, remove, or list tags on conversation sessions for organization.",
        run=run,
    )


def register_tag_command(reg: Registry) -> None:
    """Registers the `dxrk tag` command and its subcommands."""
    reg.add_command(tag_parent_cmd())
    reg.add_command(tag_add_cmd())
    reg.add_command(tag_remove_cmd())
    reg.add_command(tag_list_cmd())
    reg.add_command(tag_search_cmd())
