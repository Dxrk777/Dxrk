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
            ctx.err.write("Error: el nombre de la etiqueta no puede estar vacío\n")
            return 1

        try:
            sessions = list_session_files()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        s = _find_session(sessions, session_id)
        if s is None:
            ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
            return 1

        for t in s.tags:
            if t == tag_name:
                out.write(f"La etiqueta {go_quote(tag_name)} ya existe en la sesión {s.id[:8]}\n")
                return 0

        s.tags.append(tag_name)
        if not save_session(s):
            ctx.err.write("Error: al guardar la sesión etiquetada\n")
            return 1
        out.write(f"Etiqueta {go_quote(tag_name)} agregada a la sesión {s.id[:8]} — {s.title}\n")
        return 0

    return Command(name="tag add", short="Agregar una etiqueta a una sesión", min_args=2, max_args=2, run=run)


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
            ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
            return 1

        filtered: list[str] = []
        found = False
        for t in s.tags:
            if t == tag_name:
                found = True
                continue
            filtered.append(t)

        if not found:
            ctx.err.write(f"Error: etiqueta {go_quote(tag_name)} no encontrada en la sesión {s.id[:8]}\n")
            return 1

        s.tags = filtered
        if not save_session(s):
            ctx.err.write("Error: al guardar la sesión\n")
            return 1
        out.write(f"Etiqueta {go_quote(tag_name)} eliminada de la sesión {s.id[:8]}\n")
        return 0

    return Command(name="tag remove", short="Eliminar una etiqueta de una sesión", min_args=2, max_args=2, run=run)


def tag_list_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        try:
            s = load_session(ctx.args[0])
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        if not s.tags:
            out.write(f"La sesión {s.id[:8]} no tiene etiquetas.\n")
            return 0

        out.write(f"Etiquetas de la sesión {s.id[:8]} ({s.title}):\n")
        for t in s.tags:
            out.write(f"  - {t}\n")
        return 0

    return Command(name="tag list", short="Listar las etiquetas de una sesión", min_args=1, max_args=1, run=run)


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
            out.write(f"No se encontraron sesiones con la etiqueta {go_quote(tag_name)}\n")
            return 0

        out.write(f"Sesiones con la etiqueta {go_quote(tag_name)} ({len(matches)}):\n\n")
        for s in matches:
            title = s.title
            if len(title) > 40:
                title = title[:37] + "..."
            out.write(f"  {s.id[:8]}  {title:<40}  {_fmt_ts_short(s.updated_at)}\n")
        return 0

    return Command(
        name="tag search", short="Buscar sesiones con una etiqueta específica", min_args=1, max_args=1, run=run
    )


def tag_parent_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        ctx.err.write("Error: usa 'dxrk tag add', 'remove', 'list' o 'search'\n")
        return 1

    return Command(
        name="tag",
        short="Gestionar las etiquetas de sesión",
        long="Agregar, eliminar o listar etiquetas en sesiones de conversación para organizarlas.",
        run=run,
    )


def register_tag_command(reg: Registry) -> None:
    """Registers the `dxrk tag` command and its subcommands."""
    reg.add_command(tag_parent_cmd())
    reg.add_command(tag_add_cmd())
    reg.add_command(tag_remove_cmd())
    reg.add_command(tag_list_cmd())
    reg.add_command(tag_search_cmd())
