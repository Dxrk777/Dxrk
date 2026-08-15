# SPDX-License-Identifier: MIT
"""Share session command"""

from __future__ import annotations

import os

from dxrk.utils.session import (
    Session,
    export_html,
    export_json,
    export_markdown,
    export_xml,
)

from .registry import Command, CommandContext, Flag, Registry
from .session import SessionError, load_session

_SHARE_FORMATS = ("md", "markdown", "html", "json", "xml")


def _share_body(s: Session, fmt: str) -> str:
    if fmt == "json":
        return export_json(s)
    if fmt == "html":
        return export_html(s)
    if fmt == "xml":
        return export_xml(s)
    return export_markdown(s)


def share_session(s: Session, output_path: str, fmt: str) -> str:
    """Writes a session to a share file; returns the format used."""
    if fmt not in _SHARE_FORMATS:
        raise SessionError(f"unsupported format: {fmt}")
    body = _share_body(s, fmt)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(body)
    os.chmod(output_path, 0o600)
    return fmt


def register_share_command(reg: Registry) -> None:
    """Registers the `dxrk share` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0] if ctx.args else ""
        output_path = ctx.flag_str("output")
        if not output_path:
            output_path = ctx.args[1] if len(ctx.args) > 1 else ""
        if not output_path:
            ctx.err.write("Error: output file required (use --output or pass a path)\n")
            return 1

        if not session_id:
            ctx.err.write("Error: session id required\n")
            return 1

        try:
            s = load_session(session_id)
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        fmt = ctx.flag_str("format")
        if not fmt:
            ext = os.path.splitext(output_path)[1].lstrip(".").lower()
            fmt = ext if ext else "md"

        try:
            used = share_session(s, output_path, fmt)
        except OSError as exc:
            ctx.err.write(f"Error: write share file: {exc}\n")
            return 1
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        out.write(f"Shared session {s.id[:8]} to {output_path} ({used})\n")
        return 0

    cmd = Command(
        name="share",
        short="Share a session as a file",
        long="Export a session to a shareable file (markdown, html, json, or xml).",
        min_args=0,
        max_args=2,
        flags={
            "output": Flag("output", default="", shorthand="o", help="Output file path"),
            "format": Flag("format", default="", help="Output format (md, html, json, xml)"),
        },
        run=run,
    )
    reg.add_command(cmd)
