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
        raise SessionError(f"formato no compatible: {fmt}")
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
            ctx.err.write("Error: se requiere el archivo de salida (usa --output o pasa una ruta)\n")
            return 1

        if not session_id:
            ctx.err.write("Error: se requiere el id de la sesión\n")
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
            ctx.err.write(f"Error: al escribir el archivo compartido: {exc}\n")
            return 1
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        out.write(f"Sesión {s.id[:8]} compartida en {output_path} ({used})\n")
        return 0

    cmd = Command(
        name="share",
        short="Compartir una sesión como archivo",
        long="Exportar una sesión a un archivo compartible (markdown, html, json o xml).",
        min_args=0,
        max_args=2,
        flags={
            "output": Flag("output", default="", shorthand="o", help="Ruta del archivo de salida"),
            "format": Flag("format", default="", help="Formato de salida (md, html, json, xml)"),
        },
        run=run,
    )
    reg.add_command(cmd)
