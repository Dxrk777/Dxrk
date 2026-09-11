# SPDX-License-Identifier: MIT
"""Session rename command"""

from __future__ import annotations

from datetime import UTC, datetime

from .registry import Command, CommandContext, Registry, go_quote
from .session import list_session_files, save_session


def register_rename_command(reg: Registry) -> None:
    """Registers the `dxrk rename` command for renaming a session."""

    def run(ctx: CommandContext) -> int:
        session_id = ctx.args[0]
        new_name = ctx.args[1].strip()
        if new_name == "":
            ctx.err.write("Error: el nuevo nombre no puede estar vacío\n")
            return 1

        sessions = list_session_files()
        if sessions is None:
            ctx.err.write("Error: no se pudieron listar las sesiones\n")
            return 1

        for s in sessions:
            if s.id == session_id or s.id.startswith(session_id):
                old_title = s.title
                s.title = new_name
                s.updated_at = datetime.now(UTC)

                if not save_session(s):
                    ctx.err.write("Error: al guardar la sesión renombrada\n")
                    return 1

                ctx.out.write(f"Sesión {s.id[:8]} renombrada: {go_quote(old_title)} -> {go_quote(new_name)}\n")
                return 0

        ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
        return 1

    cmd = Command(
        name="rename",
        short="Renombrar una sesión",
        min_args=2,
        max_args=2,
        run=run,
    )
    reg.add_command(cmd)
