# SPDX-License-Identifier: MIT
"""Session commands and storage helpers.

Canonical persistence is :class:`dxrk.utils.session_storage.FileStorage`
(single writer, single reader, single error type). ``~/.dxrk/sessions``
files written by the legacy flat-file layout remain readable: every read
goes through the store (which migrates registry versions lazily) and every
write produces the canonical layout.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from dxrk.utils.session import (
    Session,
    SessionOpts,
    SessionStatus,
    import_json,
    new_session,
    now,
)
from dxrk.utils.session_model import SessionError
from dxrk.utils.session_storage import FileStorage, _atomic_write_text

from .registry import Command, CommandContext, Flag, Registry, go_duration, go_quote

SESSION_DIR_NAME = "sessions"
QUARANTINE_DIR_NAME = ".quarantine"

# Session ids are generated internally (hex/uuid); only these characters may
# appear in a file name. The store layer enforces this
# (``FileStorage._validate_session_id`` rejects path traversal); the pattern
# is kept here to document the charset.
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9_-]+")

_STATUS_NAMES: dict[int, str] = {
    SessionStatus.Active: "active",
    SessionStatus.Paused: "paused",
    SessionStatus.Completed: "completed",
    SessionStatus.Archived: "archived",
    SessionStatus.Expired: "expired",
}


def session_dir() -> str:
    """Returns the sessions directory, creating it if needed."""
    home = os.path.expanduser("~")
    if not home:
        raise SessionError("no se pudo resolver el directorio inicio")
    dir_path = os.path.join(home, ".dxrk", SESSION_DIR_NAME)
    try:
        os.makedirs(dir_path, mode=0o750, exist_ok=True)
    except OSError as exc:
        raise SessionError(f"al crear el directorio de sesiones: {exc}") from exc
    return dir_path


def _store() -> FileStorage:
    """Returns the canonical store bound to the sessions directory."""
    return FileStorage(session_dir())


def _sort_key(s: Session) -> datetime:
    return s.updated_at if s.updated_at is not None else datetime.min.replace(tzinfo=UTC)


def _quarantine_file(dir_path: str, name: str) -> bool:
    """Move an unparseable session file into ``.quarantine/``.

    Returns True when the file was moved. Never raises: a listing must not
    fail because quarantine itself is unavailable (the file is then skipped
    as before).
    """
    try:
        os.makedirs(os.path.join(dir_path, QUARANTINE_DIR_NAME), mode=0o700, exist_ok=True)
    except OSError:
        return False
    src = os.path.join(dir_path, name)
    dst = os.path.join(dir_path, QUARANTINE_DIR_NAME, name)
    if os.path.exists(dst):
        base, ext = os.path.splitext(name)
        i = 1
        while True:
            cand = os.path.join(dir_path, QUARANTINE_DIR_NAME, f"{base}-{i}{ext}")
            if not os.path.exists(cand):
                dst = cand
                break
            i += 1
    try:
        os.replace(src, dst)
    except OSError:
        return False
    return True


def list_session_files_with_quarantine() -> tuple[list[Session], int]:
    """Lists all sessions newest-first, quarantining unparseable ``.json`` files.

    Every session is read through the canonical store (single reader:
    migration registry and ``.gz`` fallback apply). Returns ``(sessions,
    quarantined)`` where ``quarantined`` is the number of corrupt files
    moved to ``.quarantine/``. Non-session names (``.index.json``, tmp
    files, non-``.json`` names), directories (including ``.quarantine/``
    itself) and transiently unreadable files are still skipped silently.
    """
    dir_path = session_dir()
    store = FileStorage(dir_path)
    try:
        entries = os.listdir(dir_path)
    except OSError as exc:
        raise SessionError(f"al leer el directorio de sesiones: {exc}") from exc
    sessions: list[Session] = []
    quarantined = 0
    seen: set[str] = set()
    for name in entries:
        full = os.path.join(dir_path, name)
        if os.path.isdir(full):
            continue
        if name in (".index.json",) or name.endswith(".tmp"):
            continue
        if name.endswith(".json.gz"):
            sid = name[: -len(".json.gz")]
            if os.path.exists(os.path.join(dir_path, sid + ".json")):
                continue  # the plain file wins; the store reads it first
        elif name.endswith(".json"):
            sid = name[: -len(".json")]
        else:
            continue
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            sessions.append(store.load(sid))
        except SessionError:
            # The store already tried ``.json`` then ``.gz``: nothing
            # readable remains. Quarantine only a readable-but-corrupt
            # plain file (legacy semantics); unreadable files are skipped
            # silently as before.
            plain = sid + ".json"
            try:
                with open(os.path.join(dir_path, plain), encoding="utf-8") as f:
                    content = f.read()
            except OSError:
                continue
            try:
                import_json(content)
            except Exception:
                if _quarantine_file(dir_path, plain):
                    quarantined += 1
            continue
    sessions.sort(key=_sort_key, reverse=True)
    return sessions, quarantined


def list_session_files() -> list[Session]:
    """Lists all sessions, newest first."""
    sessions, _ = list_session_files_with_quarantine()
    return sessions


def _write_private_file(path: str, data: str) -> None:
    """Write text to ``path`` with owner-only permissions, atomically.

    Tmp file in the same directory + fsync + ``os.replace`` + best-effort
    dir fsync (see ``dxrk.utils.session_storage._atomic_write_text``), so a
    crash can never leave a torn file behind. The tmp file inherits
    mode 0o600 at creation (no world-readable window under a permissive
    umask); the follow-up chmod covers pre-existing files. Raises OSError.
    """
    _atomic_write_text(path, data)


def load_session(session_id: str) -> Session:
    """Loads a single session by id or unique prefix."""
    try:
        return _store().load(session_id)
    except SessionError:
        pass
    found = _find_session(list_session_files(), session_id)
    if found is not None:
        return found
    raise SessionError(f"sesión {go_quote(session_id)} no encontrada")


def save_session_strict(s: Session) -> None:
    """Saves a session through the canonical store. Raises SessionError."""
    _store().save(s)


def save_session(s: Session) -> bool:
    """Saves a session as JSON with 0600 permissions.

    Legacy bool shim at the CLI boundary: True on success, False when the
    store raises. New code should use :func:`save_session_strict`.
    """
    try:
        save_session_strict(s)
    except SessionError:
        return False
    return True


def delete_session_strict(s: Session) -> None:
    """Removes a session from the canonical store. Raises SessionError."""
    store = _store()
    if not store.exists(s.id):
        raise SessionError(f"al eliminar la sesión {go_quote(s.id)}: no existe")
    store.delete(s.id)
    if store.exists(s.id):
        raise SessionError(f"al eliminar la sesión {go_quote(s.id)}")


def delete_session_file(s: Session) -> bool:
    """Removes a session file from disk.

    Legacy bool shim at the CLI boundary. New code should use
    :func:`delete_session_strict`.
    """
    try:
        delete_session_strict(s)
    except SessionError:
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
                ctx.err.write(f"Error: límite inválido: {raw_limit}\n")
                return 1
        status_filter = ctx.flag_str("status")
        tag_filter = ctx.flag_str("tag")

        try:
            sessions, quarantined = list_session_files_with_quarantine()
        except SessionError as exc:
            ctx.err.write(f"Error: {exc}\n")
            return 1

        if quarantined:
            out.write(f"Advertencia: {quarantined} archivo(s) de sesión corrupto(s) movido(s) a cuarentena.\n")
        if not sessions:
            out.write("No se encontraron sesiones.\n")
            return 0

        header = "ID\tTÍTULO\tMODELO\tMENSAJES\tESTADO\tACTUALIZADA"
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
        short="Listar sesiones",
        flags={
            "limit": Flag("limit", default="", help="Número máximo de sesiones a mostrar"),
            "status": Flag("status", default="", help="Filtrar por estado"),
            "tag": Flag("tag", default="", help="Filtrar por etiqueta"),
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
                title=title if title else "Sin título",
                working_dir=ctx.cwd,
            )
        )
        try:
            save_session_strict(s)
        except SessionError:
            ctx.err.write("Error: al guardar la sesión\n")
            return 1
        out.write(f"Sesión {s.id[:8]} creada — {s.title}\n")
        return 0

    cmd = Command(
        name="session create",
        short="Crear una nueva sesión",
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
            ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
            return 1
        found.updated_at = now()
        try:
            save_session_strict(found)
        except SessionError:
            ctx.err.write("Error: al guardar la sesión\n")
            return 1
        out.write(f"Sesión {found.id[:8]} activada — {found.title}\n")
        return 0

    cmd = Command(
        name="session switch",
        short="Cambiar a una sesión",
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
            ctx.err.write(f"Error: sesión {go_quote(session_id)} no encontrada\n")
            return 1
        try:
            delete_session_strict(found)
        except SessionError:
            ctx.err.write("Error: al eliminar la sesión\n")
            return 1
        out.write(f"Sesión {found.id[:8]} eliminada — {found.title}\n")
        return 0

    cmd = Command(
        name="session delete",
        short="Eliminar una sesión",
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

        out.write(f"ID:                 {s.id}\n")
        out.write(f"Título:             {s.title}\n")
        out.write(f"Modelo:             {s.model}\n")
        out.write(f"Estado:             {_status_name(s)}\n")
        out.write(f"Dir. de trabajo:   {s.working_dir}\n")
        out.write(f"Creada:             {_fmt_ts(s.created_at)}\n")
        out.write(f"Actualizada:        {_fmt_ts(s.updated_at)}\n")
        out.write(f"Mensajes:           {s.message_count}\n")
        out.write(f"Tokens:             {s.token_count}\n")
        out.write(f"Duración:           {go_duration(duration_secs)}\n")
        if s.tags:
            out.write(f"Etiquetas:          {', '.join(s.tags)}\n")
        if s.summary:
            out.write(f"Resumen:            {s.summary}\n")
        return 0

    cmd = Command(
        name="session info",
        short="Mostrar los detalles de la sesión",
        min_args=1,
        max_args=1,
        run=run,
    )
    return cmd


def session_parent_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        ctx.err.write("Error: usa 'dxrk session list', 'create', 'switch', 'delete' o 'info'\n")
        return 1

    return Command(name="session", short="Gestionar sesiones", run=run)


def register_session_command(reg: Registry) -> None:
    """Registers the `dxrk session` command and its subcommands."""
    reg.add_command(session_parent_cmd())
    reg.add_command(session_list_cmd())
    reg.add_command(session_create_cmd())
    reg.add_command(session_switch_cmd())
    reg.add_command(session_delete_cmd())
    reg.add_command(session_info_cmd())
