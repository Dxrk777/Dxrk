# SPDX-License-Identifier: MIT
"""Session commands and storage helpers"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from dxrk.utils.session import (
    Session,
    SessionOpts,
    SessionStatus,
    export_json,
    import_json,
    new_session,
    now,
)

from .registry import Command, CommandContext, Flag, Registry, go_duration, go_quote

SESSION_DIR_NAME = "sessions"

_STATUS_NAMES: dict[int, str] = {
    SessionStatus.Active: "active",
    SessionStatus.Paused: "paused",
    SessionStatus.Completed: "completed",
    SessionStatus.Archived: "archived",
    SessionStatus.Expired: "expired",
}


class SessionError(Exception):
    """Session storage error."""


def session_dir() -> str:
    """Returns the sessions directory, creating it if needed."""
    home = os.path.expanduser("~")
    if not home:
        raise SessionError("resolve home directory")
    dir_path = os.path.join(home, ".dxrk", SESSION_DIR_NAME)
    try:
        os.makedirs(dir_path, mode=0o750, exist_ok=True)
    except OSError as exc:
        raise SessionError(f"create sessions directory: {exc}") from exc
    return dir_path


def _sort_key(s: Session) -> datetime:
    return s.updated_at if s.updated_at is not None else datetime.min.replace(tzinfo=UTC)


def list_session_files() -> list[Session]:
    """Lists all sessions, newest first."""
    dir_path = session_dir()
    try:
        entries = os.listdir(dir_path)
    except OSError as exc:
        raise SessionError(f"read sessions directory: {exc}") from exc
    sessions: list[Session] = []
    for name in entries:
        full = os.path.join(dir_path, name)
        if os.path.isdir(full) or not name.endswith(".json"):
            continue
        try:
            with open(full, encoding="utf-8") as f:
                data = f.read()
        except OSError:
            continue
        try:
            sessions.append(import_json(data))
        except Exception:
            continue
    sessions.sort(key=_sort_key, reverse=True)
    return sessions


def load_session(session_id: str) -> Session:
    """Loads a single session by id or unique prefix."""
    path = os.path.join(session_dir(), session_id + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            data = f.read()
        try:
            return import_json(data)
        except Exception as exc:
            raise SessionError(f"decode session: {exc}") from exc
    except OSError:
        pass
    found = _find_session(list_session_files(), session_id)
    if found is not None:
        return found
    raise SessionError(f"session {go_quote(session_id)} not found")


def save_session(s: Session) -> bool:
    """Saves a session as JSON with 0600 permissions."""
    try:
        data = export_json(s)
    except Exception:
        return False
    path = os.path.join(session_dir(), s.id + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(data)
        os.chmod(path, 0o600)
    except OSError:
        return False
    return True


def delete_session_file(s: Session) -> bool:
    """Removes a session file from disk."""
    path = os.path.join(session_dir(), s.id + ".json")
    try:
        os.remove(path)
    except OSError:
        return False
    return True


def _find_session(sessions: list[Session], session_id: str) -> Session | None:
    for s in sessions:
        if s.id == session_id or s.id.startswith(session_id):
            return s
    return None


def _fmt_ts(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _fmt_ts_short(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def _status_name(s: Session) -> str:
    return _STATUS_NAMES.get(int(s.status), str(int(s.status)))


def session_list_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        raw_limit = ctx.flag_str("limit", "")
        limit = 0
        if raw_limit:
            try:
                limit = max(0, int(raw_limit))
            except ValueError:
                ctx.err.write(f"Error: invalid limit: {raw_limit}\n")
                return 1
        status_filter = ctx.flag_str("status")
        tag_filter = ctx.flag_str("tag")

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        if not sessions:
            out.write("No sessions found.\n")
            return 0

        header = "ID\tTITLE\tMODEL\tMSGS\tSTATUS\tUPDATED"
        out.write(header + "\n")
        shown = 0
        for s in sessions:
            if status_filter and _status_name(s) != status_filter:
                continue
            if tag_filter and tag_filter not in s.tags:
                continue
            if limit and shown >= limit:
                break
            out.write(
                f"{s.id[:8]}\t{s.title}\t{s.model}\t{s.message_count}\t"
                f"{_status_name(s)}\t{_fmt_ts_short(s.updated_at)}\n"
            )
            shown += 1
        return 0

    cmd = Command(
        name="session list",
        short="List sessions",
        flags={
            "limit": Flag("limit", default="", help="Maximum number of sessions to show"),
            "status": Flag("status", default="", help="Filter by status"),
            "tag": Flag("tag", default="", help="Filter by tag"),
        },
        run=run,
    )
    return cmd


def session_create_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        title = ctx.args[0] if ctx.args else ""
        s = new_session(
            SessionOpts(
                title=title if title else "Untitled",
                working_dir=ctx.cwd,
            )
        )
        if not save_session(s):
            ctx.err.write("Error: save session\n")
            return 1
        out.write(f"Created session {s.id[:8]} — {s.title}\n")
        return 0

    cmd = Command(
        name="session create",
        short="Create a new session",
        max_args=1,
        run=run,
    )
    return cmd


def session_switch_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]
        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        found = _find_session(sessions, session_id)
        if found is None:
            ctx.err.write(f"Error: session {go_quote(session_id)} not found\n")
            return 1
        found.updated_at = now()
        if not save_session(found):
            ctx.err.write("Error: save session\n")
            return 1
        out.write(f"Switched to session {found.id[:8]} — {found.title}\n")
        return 0

    cmd = Command(
        name="session switch",
        short="Switch to a session",
        min_args=1,
        max_args=1,
        run=run,
    )
    return cmd


def session_delete_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]
        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        found = _find_session(sessions, session_id)
        if found is None:
            ctx.err.write(f"Error: session {go_quote(session_id)} not found\n")
            return 1
        if not delete_session_file(found):
            ctx.err.write("Error: delete session\n")
            return 1
        out.write(f"Deleted session {found.id[:8]} — {found.title}\n")
        return 0

    cmd = Command(
        name="session delete",
        short="Delete a session",
        min_args=1,
        max_args=1,
        run=run,
    )
    return cmd


def session_info_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]
        try:
            s = load_session(session_id)
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        duration_secs = 0.0
        if s.created_at is not None and s.updated_at is not None:
            duration_secs = (s.updated_at - s.created_at).total_seconds()

        out.write(f"ID:          {s.id}\n")
        out.write(f"Title:       {s.title}\n")
        out.write(f"Model:       {s.model}\n")
        out.write(f"Status:      {_status_name(s)}\n")
        out.write(f"Working Dir: {s.working_dir}\n")
        out.write(f"Created:     {_fmt_ts(s.created_at)}\n")
        out.write(f"Updated:     {_fmt_ts(s.updated_at)}\n")
        out.write(f"Messages:    {s.message_count}\n")
        out.write(f"Tokens:      {s.token_count}\n")
        out.write(f"Duration:    {go_duration(duration_secs)}\n")
        if s.tags:
            out.write(f"Tags:        {', '.join(s.tags)}\n")
        if s.summary:
            out.write(f"Summary:     {s.summary}\n")
        return 0

    cmd = Command(
        name="session info",
        short="Show session details",
        min_args=1,
        max_args=1,
        run=run,
    )
    return cmd


def session_parent_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        ctx.err.write("Error: use 'dxrk session list', 'create', 'switch', 'delete', or 'info'\n")
        return 1

    return Command(name="session", short="Manage sessions", run=run)


def register_session_command(reg: Registry) -> None:
    """Registers the `dxrk session` command and its subcommands."""
    reg.add_command(session_parent_cmd())
    reg.add_command(session_list_cmd())
    reg.add_command(session_create_cmd())
    reg.add_command(session_switch_cmd())
    reg.add_command(session_delete_cmd())
    reg.add_command(session_info_cmd())
