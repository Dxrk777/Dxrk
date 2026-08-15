# SPDX-License-Identifier: MIT
"""Resume session command"""

from __future__ import annotations

from .registry import Command, CommandContext, Flag, Registry, go_quote
from .session import SessionError, _fmt_ts_short, list_session_files


def _truncate(s: str, width: int) -> str:
    if len(s) <= width:
        return s
    return s[: width - 3] + "..."


def register_resume_command(reg: Registry) -> None:
    """Registers the `dxrk resume` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        limit = 5
        raw_limit = ctx.flag_str("limit", "")
        if raw_limit:
            try:
                limit = max(1, int(raw_limit))
            except ValueError:
                ctx.err.write(f"Error: invalid limit: {raw_limit}\n")
                return 1

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        if not ctx.args:
            shown = sessions[:limit]
            out.write(f"Recent sessions (showing {len(shown)} of {len(sessions)}):\n\n")
            for s in shown:
                out.write(
                    f"  {s.id[:8]}  {_truncate(s.title, 50):<50}  "
                    f"{_fmt_ts_short(s.updated_at)}  {s.message_count} msgs\n"
                )
            out.write("\nResume with: dxrk resume <id-or-title>\n")
            return 0

        query = ctx.args[0]
        found = None
        for s in sessions:
            if s.id == query or s.id.startswith(query) or query.lower() in s.title.lower():
                found = s
                break

        if found is None:
            ctx.err.write(
                f"Error: no session matching {go_quote(query)} — "
                "use `dxrk resume` to list recent sessions\n"
            )
            return 1

        out.write(f"Resumed session {found.id[:8]} — {found.title}\n")
        out.write(f"Model: {found.model} | Messages: {found.message_count} | Tokens: {found.token_count}\n")
        if found.messages:
            last = found.messages[-1]
            content = _truncate(last.content, 80)
            out.write(f"Last message ({last.role}): {content}\n")
        return 0

    cmd = Command(
        name="resume",
        short="Resume a previous session",
        long="List recent sessions or resume a specific one by ID or title.",
        min_args=0,
        max_args=1,
        flags={
            "limit": Flag("limit", default="", help="Maximum number of sessions to list"),
        },
        run=run,
    )
    reg.add_command(cmd)
