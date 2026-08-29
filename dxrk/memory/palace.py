# SPDX-License-Identifier: MIT
"""DxrkMemory orchestrator — wings / rooms / drawers hierarchy.

Stdlib-only DxrkMemory engine with chunk logic.
Provides DxrkMemory class plus pid-aware locks with re-mine honesty,
orphan lock reap, non-regular file guards, date-window and SIGTERM handling.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import logging
import os
import re
import signal
import stat
import sys
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .backend import PalaceRef, SqliteBackend
from .backend.base import BaseCollection
from .types import DrawerRecord

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 50
NORMALIZE_VERSION = 2
ENTITY_METADATA_LIMIT = 25
ENTITY_EXTRACT_WINDOW = 5000
DRAWER_UPSERT_BATCH_SIZE = 500
MAX_FILE_SIZE = 500 * 1024 * 1024

logger = logging.getLogger("dxrk.memory")

SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        ".next",
        "coverage",
        ".dxrk",
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".cache",
        ".tox",
        ".nox",
        ".idea",
        ".vscode",
        ".ipynb_checkpoints",
        ".eggs",
        "htmlcov",
        "target",
    }
)

_ENTITY_STOPLIST: frozenset[str] = frozenset(
    {
        "The",
        "This",
        "That",
        "These",
        "Those",
        "When",
        "Where",
        "What",
        "Why",
        "Who",
        "Which",
        "How",
        "After",
        "Before",
        "Then",
        "Now",
        "Here",
        "There",
        "And",
        "But",
        "Or",
        "Yet",
        "So",
        "If",
        "Else",
        "Yes",
        "No",
        "Maybe",
        "Okay",
        "User",
        "Assistant",
        "System",
        "Tool",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    }
)

_HALL_KEYWORDS: dict[str, list[str]] = {
    "emotional": ["feel", "love", "fear", "hope", "grief", "joy", "worry", "anxious"],
    "technical": ["api", "database", "deploy", "algorithm", "server", "config", "architecture"],
    "family": ["family", "mother", "father", "daughter", "son", "parent", "child"],
    "work": ["project", "meeting", "deadline", "review", "ship", "release"],
    "general": [],
}

_CANDIDATE_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")

# ---------------------------------------------------------------------------
# Signal handling — SIGTERM/SIGHUP → SystemExit so atexit releases palace lock
# ---------------------------------------------------------------------------


def _install_shutdown_signal_handlers() -> None:
    """Route SIGTERM/SIGHUP through sys.exit so atexit can release locks.

    The palace writer lease is released via flock unlock on close, but a
    brutal SIGTERM would otherwise terminate without unwinding the Python
    stack. Raising SystemExit(0) lets context managers and atexit run.
    Handlers are best-effort — only works from main thread.
    """

    def _shutdown_handler(signum: int, frame: object) -> None:  # noqa: ARG001
        raise SystemExit(0)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _shutdown_handler)  # type: ignore[arg-type]
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# Non-regular file guards helpers (port of db29959)
# ---------------------------------------------------------------------------


def _path_within_root(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except (OSError, ValueError):
        return False


def _read_text_no_follow_palace(filepath: Path, root: Path) -> tuple[str, float] | None:
    """Safe read returning (content, mtime) or None for non-regular/too-large.

    Uses O_NONBLOCK so FIFO never blocks; EAGAIN branch handles write leases.
    Validates via fstat+S_ISREG, returns same-fstat mtime to avoid TOCTOU.
    """
    if not _path_within_root(filepath, root):
        return None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = -1
    try:
        try:
            fd = os.open(filepath, flags)
        except OSError as exc:
            if exc.errno != errno.EAGAIN or not stat.S_ISREG(os.lstat(filepath).st_mode):
                return None
            fd = os.open(filepath, flags & ~getattr(os, "O_NONBLOCK", 0))
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE_SIZE:
            return None
        mtime = st.st_mtime
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as f:
            fd = -1
            return f.read(), mtime
    except OSError:
        return None
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass


def _is_regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.stat().st_mode)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Tenant isolation helpers (R10) — stdlib-only, avoid top-level cycle
# ---------------------------------------------------------------------------


def _effective_tenant_id(tenant_id: str | None = None) -> str:
    """Resolve effective tenant id: explicit > env DXRK_TENANT > default if migrated."""
    tid = (tenant_id if tenant_id is not None else os.environ.get("DXRK_TENANT", "")).strip()
    if tid:
        return tid
    try:
        from dxrk.tenant.migration import is_migrated

        if is_migrated():
            return "default"
        return ""
    except Exception:
        return ""


def _resolve_tenant_path(tenant_id: str | None, palace_path: Path | str | None) -> Path:
    """Resolve palace path with tenant isolation.

    - If palace_path given (non-empty and not sentinel) → Path(palace_path)
    - Sentinel "memory-only" or "" → memory-only sentinel path
    - elif tenant_id or env DXRK_TENANT → tenant_root(effective)/palace
    - elif is_migrated() → tenant_root("default")/palace
    - else → Path.home()/".dxrk"/"palace" (legacy) — task mentions ".dxrk"/"memory" as legacy alias
    """
    if palace_path is not None:
        s = str(palace_path).strip()
        if s == "" or s == "memory-only":
            # preserve sentinel for backward compat
            return Path(s) if s else Path.home() / ".dxrk" / "memory"
        return Path(palace_path).expanduser()
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return tenant_root(tid) / "palace"
        except OSError:
            return Path.home() / ".dxrk" / "palace"
    try:
        from dxrk.tenant.migration import is_migrated, tenant_root

        if is_migrated():
            return tenant_root("default") / "palace"
    except OSError:
        pass
    return Path.home() / ".dxrk" / "palace"


# ---------------------------------------------------------------------------
# Locks (port of palace.mine_lock + mine_palace_lock + 27212e5 reap)
# ---------------------------------------------------------------------------

_palace_lock_holders = threading.local()


def _holder_state() -> set[str]:
    keys: set[str] | None = getattr(_palace_lock_holders, "keys", None)
    pid: int | None = getattr(_palace_lock_holders, "pid", None)
    cur = os.getpid()
    if keys is None or pid != cur:
        keys = set()
        _palace_lock_holders.keys = keys  # type: ignore[attr-defined]
        _palace_lock_holders.pid = cur  # type: ignore[attr-defined]
    return keys


def _held_by_this_thread(key: str) -> bool:
    return key in _holder_state()


def _mark_held(key: str) -> None:
    _holder_state().add(key)


def _mark_released(key: str) -> None:
    _holder_state().discard(key)


def _dxrk_lock_dir(tenant_id: str | None = None) -> Path:
    # Tenant-aware lock directory; legacy fallback if no tenant
    tid = _effective_tenant_id(tenant_id)
    if tid:
        try:
            from dxrk.tenant.migration import tenant_root

            return tenant_root(tid) / "locks"
        except OSError:
            pass
    return Path.home() / ".dxrk" / "locks"


def _mine_lock_path(source_file: str, tenant_id: str | None = None) -> str:
    # tenant-aware lock dir with fallback for monkeypatched zero-arg _dxrk_lock_dir
    try:
        lock_dir = _dxrk_lock_dir(tenant_id)  # type: ignore[call-arg]
    except TypeError:
        lock_dir = _dxrk_lock_dir()  # type: ignore[call-arg]
    lock_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock_dir.chmod(0o750)
    except OSError:
        pass
    return str(lock_dir / (hashlib.sha256(source_file.encode()).hexdigest()[:16] + ".lock"))


def _open_mine_lock_file(lock_path: str, *, create: bool):  # type: ignore[no-untyped-def]
    flags = os.O_RDWR
    if create:
        flags |= os.O_CREAT
    fd = os.open(lock_path, flags, 0o600)
    return os.fdopen(fd, "r+b")


def _lock_mine_lock_file(lock_file, *, blocking: bool) -> bool:  # type: ignore[no-untyped-def]
    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt  # type: ignore[import-not-found]

        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK  # type: ignore[attr-defined]
        try:
            msvcrt.locking(lock_file.fileno(), mode, 1)  # type: ignore[attr-defined]
        except OSError:
            if not blocking:
                return False
            raise
        return True
    import fcntl  # type: ignore[import-not-found]

    flags = fcntl.LOCK_EX  # type: ignore[attr-defined]
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(lock_file, flags)  # type: ignore[attr-defined]
    except BlockingIOError:
        if not blocking:
            return False
        raise
    return True


def _unlock_mine_lock_file(lock_file) -> None:  # type: ignore[no-untyped-def]
    lock_file.seek(0)
    if os.name == "nt":
        import msvcrt  # type: ignore[import-not-found]

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        return
    import fcntl  # type: ignore[import-not-found]

    fcntl.flock(lock_file, fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _mine_lock_file_is_current(lock_file, lock_path: str) -> bool:  # type: ignore[no-untyped-def]
    if os.name == "nt":
        return True
    try:
        path_stat = os.stat(lock_path)
        file_stat = os.fstat(lock_file.fileno())
    except OSError:
        return False
    return (path_stat.st_dev, path_stat.st_ino) == (file_stat.st_dev, file_stat.st_ino)


def _acquire_open_mine_lock_file(lock_file, lock_path: str) -> bool:  # type: ignore[no-untyped-def]
    _lock_mine_lock_file(lock_file, blocking=True)
    if _mine_lock_file_is_current(lock_file, lock_path):
        return True
    try:
        _unlock_mine_lock_file(lock_file)
    except Exception:
        logger.debug("Mine-lock stale-handle release failed", exc_info=True)
    return False


def _acquire_mine_lock_file(lock_path: str):  # type: ignore[no-untyped-def]
    while True:
        lf = _open_mine_lock_file(lock_path, create=True)
        try:
            if _acquire_open_mine_lock_file(lf, lock_path):
                return lf
        except Exception:
            lf.close()
            raise
        lf.close()


def _cleanup_mine_lock_file(lock_path: str) -> None:
    """Best-effort removal preserving flock rendezvous semantics (port of 27212e5)."""
    try:
        lf = _open_mine_lock_file(lock_path, create=False)
    except FileNotFoundError:
        return
    except OSError:
        logger.debug("Mine-lock cleanup open failed for %s", lock_path, exc_info=True)
        return
    acquired = False
    closed = False
    try:
        try:
            acquired = _lock_mine_lock_file(lf, blocking=False)
        except OSError:
            logger.debug("Mine-lock cleanup acquire failed for %s", lock_path, exc_info=True)
            return
        if not acquired:
            return
        if not _mine_lock_file_is_current(lf, lock_path):
            return
        if os.name == "nt":
            try:
                _unlock_mine_lock_file(lf)
            except Exception:
                logger.debug("Mine-lock cleanup release failed", exc_info=True)
                acquired = False
                return
            acquired = False
            lf.close()
            closed = True
            try:
                os.remove(lock_path)
            except OSError:
                pass
            return
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.debug("Mine-lock cleanup remove failed for %s", lock_path, exc_info=True)
    finally:
        if not closed:
            if acquired:
                try:
                    _unlock_mine_lock_file(lf)
                except Exception:
                    logger.debug("Mine-lock cleanup release failed", exc_info=True)
            lf.close()


def _cleanup_dxrk_lock_file(lock_path: str | Path) -> None:
    _cleanup_mine_lock_file(str(lock_path))


def reap_stale_dxrk_locks(
    *, min_age_seconds: int = 3600, tenant_id: str | None = None
) -> tuple[int, int]:
    """Best-effort GC for orphaned per-source-file mine locks (port of 27212e5).

    Reuses _cleanup_mine_lock_file for actual removal — same nonblocking flock
    reacquire safety, so genuinely held locks are never removed regardless of age.
    Skips mine_palace_*.lock (per-palace locks have own lifecycle).
    Returns (reaped, skipped) for logging/testing.
    Tenant-aware via tenant_id or DXRK_TENANT env.
    """
    try:
        lock_dir = _dxrk_lock_dir(tenant_id)  # type: ignore[call-arg]
    except TypeError:
        lock_dir = _dxrk_lock_dir()  # type: ignore[call-arg]
    try:
        entries = os.listdir(lock_dir)
    except OSError:
        return 0, 0
    now = time.time()
    reaped = 0
    skipped = 0
    for name in entries:
        if not name.endswith(".lock") or name.startswith("mine_palace_"):
            continue
        lock_path = lock_dir / name
        try:
            if now - lock_path.stat().st_mtime < min_age_seconds:
                continue
        except OSError:
            continue
        _cleanup_mine_lock_file(str(lock_path))
        if lock_path.exists():
            skipped += 1
        else:
            reaped += 1
    return reaped, skipped


# Alias for upstream name compatibility
reap_stale_mine_locks = reap_stale_dxrk_locks

_LOCK_REAP_INTERVAL_SECONDS = 900  # 15 min


def _maybe_reap_stale_mine_locks(tenant_id: str | None = None) -> None:
    """Throttled opportunistic reap — at most once per 15 min, piggybacks on mine."""
    try:
        lock_dir = _dxrk_lock_dir(tenant_id)  # type: ignore[call-arg]
    except TypeError:
        lock_dir = _dxrk_lock_dir()  # type: ignore[call-arg]
    marker = lock_dir / ".last_reap"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < _LOCK_REAP_INTERVAL_SECONDS:
            return
        lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            lock_dir.chmod(0o750)
        except OSError:
            pass
        marker.touch(exist_ok=True)
        try:
            os.utime(marker, None)
        except OSError:
            pass
        reap_stale_dxrk_locks()
    except Exception:
        logger.debug("Opportunistic mine-lock reap failed", exc_info=True)


def _maybe_reap_stale_dxrk_locks(tenant_id: str | None = None) -> None:
    _maybe_reap_stale_mine_locks(tenant_id=tenant_id)


@contextlib.contextmanager
def mine_lock(source_file: str, tenant_id: str | None = None) -> Generator[None]:
    """Per-file lock to avoid duplicate drawers on concurrent mine.

    Includes opportunistic orphan reap (throttled) and safe cleanup on release.
    Tenant-aware: uses tenant lock dir when tenant_id or DXRK_TENANT present.
    """
    _maybe_reap_stale_mine_locks(tenant_id=tenant_id)
    lock_path = _mine_lock_path(source_file, tenant_id=tenant_id)
    lf = _acquire_mine_lock_file(lock_path)
    try:
        yield
    finally:
        try:
            _unlock_mine_lock_file(lf)
        except Exception:
            logger.debug("Mine-lock release failed", exc_info=True)
        try:
            lf.close()
        except Exception:
            logger.debug("Mine-lock close failed", exc_info=True)
        _cleanup_mine_lock_file(lock_path)


@contextlib.contextmanager
def mine_palace_lock(palace_path: str, tenant_id: str | None = None) -> Generator[None]:
    """Per-palace lock with re-entrant support for same thread. Tenant-aware."""
    try:
        lock_dir = _dxrk_lock_dir(tenant_id)  # type: ignore[call-arg]
    except TypeError:
        lock_dir = _dxrk_lock_dir()  # type: ignore[call-arg]
    lock_dir.mkdir(parents=True, exist_ok=True)
    try:
        lock_dir.chmod(0o750)
    except OSError:
        pass
    resolved = str(Path(palace_path).expanduser().resolve())
    key_source = os.path.normcase(resolved)
    palace_key = hashlib.sha256(key_source.encode()).hexdigest()[:16]
    lock_path = lock_dir / f"mine_palace_{palace_key}.lock"
    if _held_by_this_thread(palace_key):
        yield
        return
    if not lock_path.exists():
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    lf = open(lock_path, "r+b")
    acquired = False
    try:
        lf.seek(0)
        if os.name == "nt":
            import msvcrt  # type: ignore[import-not-found]

            try:
                msvcrt.locking(lf.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
                acquired = True
            except OSError as exc:
                raise RuntimeError(f"palace {resolved} is held by another writer") from exc
        else:
            import fcntl  # type: ignore[import-not-found]

            try:
                fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as exc:
                raise RuntimeError(f"palace {resolved} is held by another writer") from exc
        _mark_held(palace_key)
        try:
            yield
        finally:
            _mark_released(palace_key)
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt  # type: ignore[import-not-found]

                    lf.seek(0)
                    msvcrt.locking(lf.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
                else:
                    import fcntl  # type: ignore[import-not-found]

                    fcntl.flock(lf, fcntl.LOCK_UN)
            except Exception:
                pass
        lf.close()


# alias for backward compat
mine_global_lock = mine_palace_lock

# ---------------------------------------------------------------------------
# Chunking & helpers
# ---------------------------------------------------------------------------


def chunk_text(
    content: str,
    source_file: str = "",
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
    min_chunk_size: int = MIN_CHUNK_SIZE,
) -> list[dict[str, object]]:
    """Split content into drawer-sized chunks (paragraph-aware)."""
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError(f"chunk_size must be positive int, got {chunk_size!r}")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be non-negative int, got {chunk_overlap!r}")
    if chunk_overlap >= chunk_size:
        raise ValueError(f"chunk_overlap {chunk_overlap} must be < chunk_size {chunk_size}")
    if not isinstance(min_chunk_size, int) or min_chunk_size < 0:
        raise ValueError(f"min_chunk_size must be non-negative int, got {min_chunk_size!r}")
    _ = source_file
    content = content.strip()
    if not content:
        return []
    chunks: list[dict[str, object]] = []
    start = 0
    idx = 0
    while start < len(content):
        end = min(start + chunk_size, len(content))
        if end < len(content):
            nl2 = content.rfind("\n\n", start, end)
            if nl2 > start + chunk_size // 2:
                end = nl2
            else:
                nl = content.rfind("\n", start, end)
                if nl > start + chunk_size // 2:
                    end = nl
        chunk = content[start:end].strip()
        if len(chunk) >= min_chunk_size:
            chunks.append({"content": chunk, "chunk_index": idx})
            idx += 1
        start = end - chunk_overlap if end < len(content) else end
    return chunks


def _detect_hall(content: str) -> str:
    low = content[:3000].lower()
    best = "general"
    best_score = 0
    for hall, kws in _HALL_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in low)
        if score > best_score:
            best_score = score
            best = hall
    return best


def _extract_entities(content: str) -> str:
    window = content[:ENTITY_EXTRACT_WINDOW]
    words = _CANDIDATE_RE.findall(window)
    freq: dict[str, int] = {}
    for w in words:
        if w in _ENTITY_STOPLIST:
            continue
        freq[w] = freq.get(w, 0) + 1
    matched = [w for w, c in freq.items() if c >= 2 and len(w) > 2]
    matched.sort()
    return ";".join(matched[:ENTITY_METADATA_LIMIT])


def _build_drawer_metadata(
    wing: str,
    room: str,
    source_file: str,
    chunk_index: int,
    agent: str,
    content: str,
    source_mtime: float | None,
    *,
    chunk_total: int | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "wing": wing,
        "room": room,
        "source_file": source_file,
        "chunk_index": chunk_index,
        "added_by": agent,
        "filed_at": datetime.now(UTC).isoformat(),
        "normalize_version": NORMALIZE_VERSION,
        "hall": _detect_hall(content),
    }
    if source_mtime is not None:
        meta["source_mtime"] = source_mtime
    if chunk_total is not None:
        meta["chunk_total"] = chunk_total
    ents = _extract_entities(content)
    if ents:
        meta["entities"] = ents
    return meta


# ---------------------------------------------------------------------------
# Palace orchestrator
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PalaceConfig:
    palace_path: str
    wing: str = "default"


class DxrkMemory:
    """DxrkMemory — wings / rooms / drawers orchestrator backed by SqliteBackend.

    Canonical name for the fused engine. ``Palace`` remains as alias for
    backward compatibility with earlier DxrkMemory drafts.
    Tenant-aware: palace_path isolated per tenant via ~/.dxrk/tenants/{id}/palace.
    """

    def __init__(
        self,
        palace_path: str | Path | None = None,
        backend: SqliteBackend | None = None,
        tenant_id: str | None = None,
    ) -> None:
        self.tenant_id: str = _effective_tenant_id(tenant_id)
        resolved = _resolve_tenant_path(tenant_id, palace_path)
        # preserve sentinel memory-only handling without resolve
        if str(resolved) in ("", "memory-only"):
            self.palace_path = str(resolved) if str(resolved) else ""
        else:
            try:
                self.palace_path = str(Path(resolved).expanduser().resolve())
            except Exception:
                self.palace_path = str(Path(resolved).expanduser())
        self._backend = backend or SqliteBackend()
        self._ref = PalaceRef(id=self.palace_path, local_path=self.palace_path)

    def _collection(self, name: str = "dxrk_drawers", *, create: bool = True) -> BaseCollection:
        return self._backend.get_collection(palace=self._ref, collection_name=name, create=create)

    def init(self) -> None:
        Path(self.palace_path).mkdir(parents=True, exist_ok=True)
        try:
            Path(self.palace_path).chmod(0o750)
        except OSError:
            pass
        # touch DB by getting collection
        self._collection(create=True)

    def add_drawer(
        self,
        wing: str,
        room: str,
        content: str,
        source_file: str,
        chunk_index: int,
        agent: str = "dxrk",
        *,
        chunk_total: int | None = None,
    ) -> str:
        drawer_id = DrawerRecord.make_id(wing, room, source_file, chunk_index)
        try:
            source_mtime = os.path.getmtime(source_file)
        except OSError:
            source_mtime = 0.0
        meta = _build_drawer_metadata(
            wing, room, source_file, chunk_index, agent, content, source_mtime, chunk_total=chunk_total
        )
        col = self._collection(create=True)
        col.upsert(documents=[content], ids=[drawer_id], metadatas=[meta])  # type: ignore[arg-type]
        return drawer_id

    def mine(
        self,
        project_dir: str | Path,
        wing: str = "default",
        room: str = "general",
        agent: str = "dxrk",
        dry_run: bool = False,
    ) -> dict[str, object]:
        """Mine a project directory into this palace (ported re-mine honesty + chunk_total).

        - Scans project via miner.scan_project (S_ISREG guard + gitignore)
        - For each file, uses mine_lock per file to avoid concurrent duplicate upserts
        - Reads file safely via O_NONBLOCK + S_ISREG (never blocks on FIFO)
        - Stamps chunk_total on every drawer so future file_already_mined can
          distinguish complete vs partial multi-batch mines (759b8f1 + 1654cd2).
        - Wraps multi-batch upsert in try/except that on failure deletes partial
          drawers for that source_file and purges closets before re-raising,
          so next mine retries honestly (1654cd2).
        """
        # Local import to avoid circular
        from .miner import scan_project as _scan_project

        project_path = Path(project_dir).expanduser().resolve()
        if not project_path.is_dir():
            raise ValueError(f"project_dir not found: {project_path}")
        files = _scan_project(project_path)
        col = self._collection(create=True)
        # closets collection optional — if exists, purge on partial failure
        closets_col: BaseCollection | None = None
        try:
            closets_col = self._collection(name="dxrk_closets", create=False)
        except Exception:
            closets_col = None
        total_drawers = 0
        files_mined = 0
        files_skipped = 0
        for fp in files:
            source_file = str(fp)
            # Use O_NONBLOCK safe read that returns same-fstat mtime (db29959 + #22)
            read_result = _read_text_no_follow_palace(fp, project_path)
            if read_result is None:
                files_skipped += 1
                continue
            content, source_mtime = read_result
            content = content.strip()
            if len(content) < MIN_CHUNK_SIZE:
                files_skipped += 1
                continue
            chunks = chunk_text(
                content, source_file, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP, min_chunk_size=MIN_CHUNK_SIZE
            )
            if not chunks:
                files_skipped += 1
                continue
            if dry_run:
                total_drawers += len(chunks)
                files_mined += 1
                continue
            # Per-file lock (tenant-aware)
            with mine_lock(source_file, tenant_id=self.tenant_id or None):
                # Purge stale drawers before re-inserting fresh chunks.
                # If purge fails, abort this file and let next mine retry
                # (leaves old mtime untouched so freshness check stays honest).
                try:
                    col.delete(where={"source_file": source_file})
                except Exception as exc:
                    print(f"  ! [skip] {fp.name} stale-drawer purge failed ({exc!r})", file=sys.stderr)
                    logger.debug("Stale-drawer purge failed for %s", source_file, exc_info=True)
                    files_skipped += 1
                    continue
                chunk_total = len(chunks)
                drawers_added = 0
                try:
                    for batch_start in range(0, len(chunks), DRAWER_UPSERT_BATCH_SIZE):
                        batch_docs: list[str] = []
                        batch_ids: list[str] = []
                        batch_metas: list[dict[str, object]] = []
                        for chunk in chunks[batch_start : batch_start + DRAWER_UPSERT_BATCH_SIZE]:
                            _ci = chunk.get("chunk_index", 0)
                            ci = int(_ci) if isinstance(_ci, int) else int(str(_ci))  # type: ignore[arg-type]
                            drawer_id = DrawerRecord.make_id(wing, room, source_file, ci)
                            batch_docs.append(str(chunk["content"]))
                            batch_ids.append(drawer_id)
                            batch_metas.append(
                                _build_drawer_metadata(
                                    wing,
                                    room,
                                    source_file,
                                    ci,
                                    agent,
                                    str(chunk["content"]),
                                    source_mtime,
                                    chunk_total=chunk_total,
                                )
                            )
                        col.upsert(documents=batch_docs, ids=batch_ids, metadatas=batch_metas)  # type: ignore[arg-type]
                        drawers_added += len(batch_docs)
                except Exception:
                    # Clean partial drawers so next mine retries honestly.
                    # Source lock prevents deleting another miner's work.
                    try:
                        col.delete(where={"source_file": source_file})
                    except Exception:
                        logger.warning(
                            "Failed to clean partial drawers after upsert error for %s", source_file, exc_info=True
                        )
                    if closets_col is not None:
                        try:
                            closets_col.delete(where={"source_file": source_file})
                        except Exception:
                            logger.warning("Failed to clean partial closets for %s", source_file, exc_info=True)
                    raise
                # Closet purge unconditional — old pointers already deleted
                if closets_col is not None:
                    try:
                        closets_col.delete(where={"source_file": source_file})
                    except Exception:
                        pass
                total_drawers += drawers_added
                files_mined += 1
        return {"files_mined": files_mined, "files_skipped": files_skipped, "drawers_added": total_drawers}

    def search(
        self,
        query: str,
        wing: str | None = None,
        room: str | None = None,
        n_results: int = 5,
        since: str | None = None,
        before: str | None = None,
    ) -> dict[str, object]:
        """Search via hybrid_search with optional date window (since/before)."""
        from .search import build_where_filter, hybrid_search

        where = build_where_filter(wing, room)
        col = self._collection(create=False)
        return hybrid_search(col, query, where=where or None, n_results=n_results, since=since, before=before)

    def get_drawer(self, drawer_id: str) -> dict[str, object] | None:
        col = self._collection(create=False)
        res = col.get(ids=[drawer_id], include=["documents", "metadatas"])
        if not res.ids:
            return None
        return {"id": res.ids[0], "document": res.documents[0], "metadata": res.metadatas[0]}

    def list_rooms(self, wing: str | None = None) -> list[str]:
        col = self._collection(create=False)
        got = col.get(include=["metadatas"], limit=2000)
        rooms: set[str] = set()
        for m in got.metadatas:
            if wing is not None and m.get("wing") != wing:
                continue
            r = m.get("room")
            if isinstance(r, str):
                rooms.add(r)
        return sorted(rooms)

    def list_wings(self) -> list[str]:
        col = self._collection(create=False)
        got = col.get(include=["metadatas"], limit=2000)
        wings: set[str] = set()
        for m in got.metadatas:
            w = m.get("wing")
            if isinstance(w, str):
                wings.add(w)
        return sorted(wings)

    def count(self) -> int:
        col = self._collection(create=False)
        return col.count()

    def health(self) -> dict[str, object]:
        st = self._backend.health(self._ref)
        return {"ok": st.ok, "detail": st.detail, "palace_path": self.palace_path}

    def close(self) -> None:
        self._backend.close_palace(self._ref)


# Backward compat aliases — Palace is the pre-branding name, DxrkPalace is legacy
Palace = DxrkMemory
DxrkPalace = DxrkMemory
