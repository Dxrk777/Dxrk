# SPDX-License-Identifier: MIT
"""Export command"""

from __future__ import annotations

import os

from dxrk.utils.session import Session

from .registry import Command, CommandContext, Flag, Registry, go_quote
from .session import SessionError, load_session

_EXPORT_FORMATS = ("md", "markdown", "html", "json", "xml")


def export_session_body(s: Session, fmt: str) -> str:
    """Builds the export body for a session."""
    if fmt == "json":
        from dxrk.utils.session import export_json

        return export_json(s)
    if fmt == "html":
        from dxrk.utils.session import export_html

        return export_html(s)
    if fmt == "xml":
        from dxrk.utils.session import export_xml

        return export_xml(s)

    lines = [f"# {s.title}\n"]
    lines.append(f"- **ID**: {s.id}\n")
    lines.append(f"- **Model**: {s.model}\n")
    lines.append(f"- **Status**: {s.status}\n")
    lines.append(f"- **Created**: {s.created_at.strftime('%Y-%m-%d %H:%M:%S') if s.created_at else ''}\n")
    lines.append(f"- **Updated**: {s.updated_at.strftime('%Y-%m-%d %H:%M:%S') if s.updated_at else ''}\n")
    lines.append(f"- **Messages**: {s.message_count}\n")
    lines.append(f"- **Tokens**: {s.token_count}\n")
    if s.tags:
        lines.append(f"- **Tags**: {', '.join(s.tags)}\n")
    lines.append("\n")
    for m in s.messages:
        lines.append(f"### {m.role}\n\n")
        lines.append(f"{m.content}\n\n")
    return "".join(lines)


def register_export_command(reg: Registry) -> None:
    """Registers the `dxrk export` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]

        try:
            s = load_session(session_id)
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        output_path = ctx.flag_str("output")
        if not output_path:
            output_path = f"{s.id[:8]}.md"

        fmt = ctx.flag_str("format")
        if not fmt:
            ext = os.path.splitext(output_path)[1].lstrip(".").lower()
            fmt = ext if ext else "md"
        if fmt not in _EXPORT_FORMATS:
            ctx.err.write(f"Error: unsupported format {go_quote(fmt)}\n")
            return 1

        body = export_session_body(s, fmt)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(body)
            os.chmod(output_path, 0o600)
        except OSError as exc:
            ctx.err.write(f"Error: write export file: {exc}\n")
            return 1

        out.write(f"Exported session {s.id[:8]} to {output_path} ({fmt})\n")
        return 0

    cmd = Command(
        name="export",
        short="Export a session to a file",
        min_args=1,
        max_args=1,
        flags={
            "output": Flag("output", default="", shorthand="o", help="Output file path"),
            "format": Flag("format", default="", help="Output format (md, html, json, xml)"),
        },
        run=run,
    )
    reg.add_command(cmd)
