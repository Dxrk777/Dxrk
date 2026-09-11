# SPDX-License-Identifier: MIT
"""Rewind session command"""

from __future__ import annotations

from .registry import Command, CommandContext, Registry, go_quote
from .session import (
    SessionError,
    _find_session,
    list_session_files,
    save_session,
)


def register_rewind_command(reg: Registry) -> None:
    """Registers the `dxrk rewind` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        session_id = ctx.args[0]

        try:
            count = int(ctx.args[1])
        except ValueError:
            ctx.err.write(f"Error: cantidad de mensajes inválida {go_quote(ctx.args[1])}\n")
            return 1
        if count < 1:
            ctx.err.write("Error: la cantidad de mensajes debe ser >= 1\n")
            return 1

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1
        if not sessions:
            ctx.err.write("Error: no se encontraron sesiones\n")
            return 1

        s = _find_session(sessions, session_id)
        if s is None:
            ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
            return 1

        messages = s.messages
        if not messages:
            ctx.err.write("Error: la sesión no tiene mensajes para retroceder\n")
            return 1

        removed = messages[-count:]
        remaining = messages[:-count]
        s.messages = remaining
        s.message_count = len(remaining)

        if not save_session(s):
            ctx.err.write("Error: al guardar la sesión retrocedida\n")
            return 1

        out.write(f"Sesión {s.id[:8]} retrocedida en {len(removed)} mensaje(s) ({len(remaining)} restantes)\n")
        if removed:
            out.write("\nMensajes eliminados:\n")
            for m in removed:
                content = m.content
                if len(content) > 80:
                    content = content[:77] + "..."
                out.write(f"  [{m.role}] {content}\n")
        return 0

    cmd = Command(
        name="rewind",
        short="Eliminar mensajes de una sesión",
        long="Eliminar los últimos N mensajes de una sesión para retroceder su estado.",
        min_args=2,
        max_args=2,
        run=run,
    )
    reg.add_command(cmd)
