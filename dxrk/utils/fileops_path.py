# SPDX-License-Identifier: MIT
"""Path resolution, classification, traversal, and temp-dir helpers."""

from __future__ import annotations

import glob as _glob
import os
import shutil
import stat as _stat
import sys
import tempfile
from collections.abc import Callable

from dxrk.utils.fileops_errors import FileopsError, ValidatePath

_STAT_IFMT = _stat.S_IFMT
_STAT_IFREG = _stat.S_IFREG


def resolve_path(path: str, working_dir: str) -> tuple[str, FileopsError | None]:
    """Resolve a potentially relative path against working_dir. Mirrors ResolvePath."""
    err = ValidatePath(path)
    if err is not None:
        return "", err
    if os.path.isabs(path):
        return os.path.normpath(path), None
    if working_dir == "":
        try:
            working_dir = os.getcwd()
        except OSError as e:
            return "", FileopsError(str(e))
    return os.path.join(working_dir, path), None


# Backwards-compatible alias (Go-style name).
ResolvePath = resolve_path


def is_within_dir(path: str, dir: str) -> tuple[bool, FileopsError | None]:
    """Check that path is inside dir (or equals it). Mirrors fileops.IsWithinDir."""
    try:
        abs_path = os.path.abspath(path)
        abs_dir = os.path.abspath(dir)
    except OSError as e:
        return False, FileopsError(str(e))
    try:
        rel = os.path.relpath(abs_path, abs_dir)
    except ValueError as e:
        return False, FileopsError(str(e))
    if rel == ".":
        return True, None
    return not rel.startswith(".."), None


# Backwards-compatible alias (Go-style name).
IsWithinDir = is_within_dir


def safe_join(*elems: str) -> str:
    """Join path elements and reject any result that escapes the first element. Mirrors SafeJoin."""
    joined = os.path.normpath(os.path.join(*elems))
    base = os.path.normpath(elems[0])
    try:
        rel = os.path.relpath(joined, base)
    except ValueError:
        return joined
    if rel.startswith(".."):
        return base
    return joined


# Backwards-compatible alias (Go-style name).
SafeJoin = safe_join


def relative_path(path: str, base: str) -> tuple[str, FileopsError | None]:
    """Return the relative path from base to path. Mirrors fileops.RelativePath."""
    try:
        abs_path = os.path.abspath(path)
        abs_base = os.path.abspath(base)
        return os.path.relpath(abs_path, abs_base), None
    except (OSError, ValueError) as e:
        return "", FileopsError(str(e))


# Backwards-compatible alias (Go-style name).
RelativePath = relative_path


def expand_home(path: str) -> tuple[str, FileopsError | None]:
    """Replace a leading ~ with the user's home directory. Mirrors fileops.ExpandHome."""
    if not path.startswith("~"):
        return path, None
    home = os.environ.get("HOME")
    if not home:
        return "", FileopsError("fileops: cannot determine home dir")
    if path == "~":
        return home, None
    if path.startswith("~/"):
        return os.path.join(home, path[2:]), None
    return path, None


# Backwards-compatible alias (Go-style name).
ExpandHome = expand_home


def is_hidden(path: str) -> bool:
    """Return True if the file or directory name starts with a dot. Mirrors IsHidden."""
    return os.path.basename(path).startswith(".")


# Backwards-compatible alias (Go-style name).
IsHidden = is_hidden


def is_symlink(path: str) -> tuple[bool, FileopsError | None]:
    """Report whether path is a symbolic link. Mirrors fileops.IsSymlink."""
    try:
        return os.path.islink(path), None
    except OSError as e:
        return False, FileopsError(str(e))


# Backwards-compatible alias (Go-style name).
IsSymlink = is_symlink


def real_path(path: str) -> tuple[str, FileopsError | None]:
    """Resolve all symlinks and return the canonical path. Mirrors fileops.RealPath."""
    try:
        return os.path.realpath(path), None
    except OSError as e:
        return "", FileopsError(str(e))


# Backwards-compatible alias (Go-style name).
RealPath = real_path


def glob(pattern: str, root_dir: str) -> tuple[list[str], None]:
    """Perform a recursive glob starting at root_dir matching pattern. Mirrors Glob."""
    if root_dir == "":
        root_dir = "."
    full_pattern = os.path.join(root_dir, pattern)
    return _glob.glob(full_pattern), None


# Backwards-compatible alias (Go-style name).
Glob = glob


class _SkipDir(Exception):
    """SkipDir sentinel."""


def walk_dir(
    root: str,
    fn: Callable[[str, object, OSError | None], FileopsError | _SkipDir | None],
) -> FileopsError | None:
    """Recursively walk root calling fn for each file or directory. Mirrors WalkDir."""

    def walk(path: str) -> FileopsError | _SkipDir | None:
        try:
            info = os.lstat(path)
        except OSError as e:
            return fn(path, None, e)
        err = fn(path, info, None)
        is_dir = info is not None and not os.path.islink(path) and os.path.isdir(path)
        if err is not None:
            if isinstance(err, _SkipDir) and is_dir:
                return None
            return err
        if is_dir:
            try:
                names = sorted(os.listdir(path))
            except OSError as e:
                return fn(path, info, e)
            for name in names:
                err = walk(os.path.join(path, name))
                if isinstance(err, _SkipDir):
                    break
                if err is not None:
                    return err
        return None

    err = walk(root)
    if isinstance(err, _SkipDir):
        return None
    return err


# Backwards-compatible alias (Go-style name).
WalkDir = walk_dir


def get_extension(path: str) -> str:
    """Return the file extension including the leading dot. Mirrors GetExtension."""
    return os.path.splitext(path)[1]


# Backwards-compatible alias (Go-style name).
GetExtension = get_extension


def get_base_name(path: str) -> str:
    """Return the file name without extension. Mirrors fileops.GetBaseName."""
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1]
    if ext == "":
        return base
    return base[: len(base) - len(ext)]


# Backwards-compatible alias (Go-style name).
GetBaseName = get_base_name


def change_extension(path: str, ext: str) -> str:
    """Replace the file extension. Mirrors fileops.ChangeExtension."""
    if not ext.startswith("."):
        ext = "." + ext
    dirname = os.path.dirname(path)
    base = GetBaseName(path)
    return os.path.join(dirname, base + ext)


# Backwards-compatible alias (Go-style name).
ChangeExtension = change_extension


def tmp_dir() -> str:
    """Return the OS temporary directory. Mirrors fileops.TmpDir."""
    return tempfile.gettempdir()


# Backwards-compatible alias (Go-style name).
TmpDir = tmp_dir


def tmp_file(ext: str) -> tuple[str, Callable[[], None], FileopsError | None]:
    """Create a temporary file with the given extension and return its path. Mirrors TmpFile."""
    if not ext.startswith(".") and ext != "":
        ext = "." + ext
    try:
        with tempfile.NamedTemporaryFile(delete=False, prefix="fileops-", suffix=ext) as f:
            name = f.name
    except OSError as e:
        return "", lambda: None, FileopsError(str(e))

    def cleanup() -> None:
        try:
            os.remove(name)
        except OSError:
            pass

    return name, cleanup, None


# Backwards-compatible alias (Go-style name).
TmpFile = tmp_file


def mkdir_temp(pattern: str) -> tuple[str, Callable[[], None], FileopsError | None]:
    """Create a temporary directory and return its path and cleanup. Mirrors MkdirTemp."""
    try:
        dirname = tempfile.mkdtemp(prefix=pattern)
    except OSError as e:
        return "", lambda: None, FileopsError(str(e))
    return dirname, lambda: shutil.rmtree(dirname, ignore_errors=True), None


# Backwards-compatible alias (Go-style name).
MkdirTemp = mkdir_temp


def normalize_path(path: str) -> tuple[str, FileopsError | None]:
    """Clean and resolve a path, returning the absolute canonical form. Mirrors NormalizePath."""
    path = os.path.normpath(path)
    if not os.path.isabs(path):
        try:
            wd = os.getcwd()
        except OSError as e:
            return "", FileopsError(str(e))
        path = os.path.join(wd, path)
    return os.path.abspath(path), None


# Backwards-compatible alias (Go-style name).
NormalizePath = normalize_path


def split_path(path: str) -> tuple[str, str]:
    """Split path into directory and file components. Mirrors fileops.SplitPath."""
    dirname, filename = os.path.split(path)
    if dirname and not dirname.endswith(os.sep):
        dirname += os.sep
    return dirname, filename


# Backwards-compatible alias (Go-style name).
SplitPath = split_path


def dir_exists(dir: str) -> tuple[bool, FileopsError | None]:
    """Report whether dir exists and is a directory. Mirrors fileops.DirExists."""
    try:
        os.stat(dir)
    except FileNotFoundError:
        return False, None
    except OSError as e:
        return False, FileopsError(str(e))
    return os.path.isdir(dir), None


# Backwards-compatible alias (Go-style name).
DirExists = dir_exists


def file_exists(path: str) -> tuple[bool, FileopsError | None]:
    """Report whether path exists and is a regular file. Mirrors fileops.FileExists."""
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return False, None
    except OSError as e:
        return False, FileopsError(str(e))
    return _STAT_IFMT(info.st_mode) == _STAT_IFREG, None


# Backwards-compatible alias (Go-style name).
FileExists = file_exists


def is_dir(path: str) -> bool:
    """Report whether path is a directory. Mirrors fileops.IsDir."""
    try:
        return os.path.isdir(path)
    except OSError:
        return False


# Backwards-compatible alias (Go-style name).
IsDir = is_dir


def is_file(path: str) -> bool:
    """Report whether path is a regular file. Mirrors fileops.IsFile."""
    try:
        return os.path.isfile(path)
    except OSError:
        return False


# Backwards-compatible alias (Go-style name).
IsFile = is_file


def executable_dir() -> tuple[str, FileopsError | None]:
    """Return the directory of the currently running executable. Mirrors ExecutableDir."""
    if sys.executable is None or sys.executable == "":
        return "", FileopsError("executable file not found in $PATH")
    return os.path.dirname(sys.executable), None


# Backwards-compatible alias (Go-style name).
ExecutableDir = executable_dir


def home_dir() -> tuple[str, FileopsError | None]:
    """Return the user's home directory. Mirrors fileops.HomeDir."""
    home = os.environ.get("HOME")
    if not home:
        return "", FileopsError("fileops: cannot determine home dir")
    return home, None


# Backwards-compatible alias (Go-style name).
HomeDir = home_dir


def user_cache_dir() -> tuple[str, FileopsError | None]:
    """Return the per-user cache directory for the current platform. Mirrors UserCacheDir."""
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return base, None
    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".cache"), None
    return "", FileopsError("neither $XDG_CACHE_HOME nor $HOME are defined")


# Backwards-compatible alias (Go-style name).
UserCacheDir = user_cache_dir


def user_config_dir() -> tuple[str, FileopsError | None]:
    """Return the per-user configuration directory. Mirrors UserConfigDir."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return base, None
    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".config"), None
    return "", FileopsError("neither $XDG_CONFIG_HOME nor $HOME are defined")


# Backwards-compatible alias (Go-style name).
UserConfigDir = user_config_dir


def platform() -> str:
    """Return the runtime platform value. Mirrors fileops.Platform (runtime.GOOS)."""
    return {"win32": "windows", "cygwin": "windows"}.get(sys.platform, sys.platform)


# Backwards-compatible alias (Go-style name).
Platform = platform


def clean_path(path: str) -> str:
    """Clean a path, handling edge cases like empty strings. Mirrors CleanPath."""
    if path == "":
        return "."
    return os.path.normpath(path)


# Backwards-compatible alias (Go-style name).
CleanPath = clean_path


def abs_path(path: str) -> tuple[str, FileopsError | None]:
    """Return an absolute version of path. Mirrors fileops.AbsPath."""
    try:
        return os.path.abspath(path), None
    except OSError as e:
        return "", FileopsError(str(e))


# Backwards-compatible alias (Go-style name).
AbsPath = abs_path


def ensure_trailing_sep(path: str) -> str:
    """Ensure the path ends with the OS path separator. Mirrors EnsureTrailingSep."""
    if not path.endswith(os.sep):
        return path + os.sep
    return path


# Backwards-compatible alias (Go-style name).
EnsureTrailingSep = ensure_trailing_sep
