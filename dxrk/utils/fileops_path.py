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


def ResolvePath(path: str, working_dir: str) -> tuple[str, FileopsError | None]:
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


def IsWithinDir(path: str, dir: str) -> tuple[bool, FileopsError | None]:
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


def SafeJoin(*elems: str) -> str:
    """Join path elements and reject any result that escapes the first element. Mirrors SafeJoin."""
    joined = os.path.normpath(os.path.join(*elems))
    if len(elems) > 0:
        base = os.path.normpath(elems[0])
        try:
            rel = os.path.relpath(joined, base)
        except ValueError:
            return joined
        if rel.startswith(".."):
            return base
    return joined


def RelativePath(path: str, base: str) -> tuple[str, FileopsError | None]:
    """Return the relative path from base to path. Mirrors fileops.RelativePath."""
    try:
        abs_path = os.path.abspath(path)
        abs_base = os.path.abspath(base)
        return os.path.relpath(abs_path, abs_base), None
    except (OSError, ValueError) as e:
        return "", FileopsError(str(e))


def ExpandHome(path: str) -> tuple[str, FileopsError | None]:
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


def IsHidden(path: str) -> bool:
    """Return True if the file or directory name starts with a dot. Mirrors IsHidden."""
    return os.path.basename(path).startswith(".")


def IsSymlink(path: str) -> tuple[bool, FileopsError | None]:
    """Report whether path is a symbolic link. Mirrors fileops.IsSymlink."""
    try:
        return os.path.islink(path), None
    except OSError as e:
        return False, FileopsError(str(e))


def RealPath(path: str) -> tuple[str, FileopsError | None]:
    """Resolve all symlinks and return the canonical path. Mirrors fileops.RealPath."""
    try:
        return os.path.realpath(path), None
    except OSError as e:
        return "", FileopsError(str(e))


def Glob(pattern: str, root_dir: str) -> tuple[list[str], None]:
    """Perform a recursive glob starting at root_dir matching pattern. Mirrors Glob."""
    if root_dir == "":
        root_dir = "."
    full_pattern = os.path.join(root_dir, pattern)
    return _glob.glob(full_pattern), None


class _SkipDir(Exception):
    """SkipDir sentinel."""


def WalkDir(
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


def GetExtension(path: str) -> str:
    """Return the file extension including the leading dot. Mirrors GetExtension."""
    return os.path.splitext(path)[1]


def GetBaseName(path: str) -> str:
    """Return the file name without extension. Mirrors fileops.GetBaseName."""
    base = os.path.basename(path)
    ext = os.path.splitext(base)[1]
    if ext == "":
        return base
    return base[: len(base) - len(ext)]


def ChangeExtension(path: str, ext: str) -> str:
    """Replace the file extension. Mirrors fileops.ChangeExtension."""
    if not ext.startswith("."):
        ext = "." + ext
    dirname = os.path.dirname(path)
    base = GetBaseName(path)
    return os.path.join(dirname, base + ext)


def TmpDir() -> str:
    """Return the OS temporary directory. Mirrors fileops.TmpDir."""
    return tempfile.gettempdir()


def TmpFile(ext: str) -> tuple[str, Callable[[], None], FileopsError | None]:
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


def MkdirTemp(pattern: str) -> tuple[str, Callable[[], None], FileopsError | None]:
    """Create a temporary directory and return its path and cleanup. Mirrors MkdirTemp."""
    try:
        dirname = tempfile.mkdtemp(prefix=pattern)
    except OSError as e:
        return "", lambda: None, FileopsError(str(e))
    return dirname, lambda: shutil.rmtree(dirname, ignore_errors=True), None


def NormalizePath(path: str) -> tuple[str, FileopsError | None]:
    """Clean and resolve a path, returning the absolute canonical form. Mirrors NormalizePath."""
    path = os.path.normpath(path)
    if not os.path.isabs(path):
        try:
            wd = os.getcwd()
        except OSError as e:
            return "", FileopsError(str(e))
        path = os.path.join(wd, path)
    return os.path.abspath(path), None


def SplitPath(path: str) -> tuple[str, str]:
    """Split path into directory and file components. Mirrors fileops.SplitPath."""
    dirname, filename = os.path.split(path)
    if dirname and not dirname.endswith(os.sep):
        dirname += os.sep
    return dirname, filename


def DirExists(dir: str) -> tuple[bool, FileopsError | None]:
    """Report whether dir exists and is a directory. Mirrors fileops.DirExists."""
    try:
        os.stat(dir)
    except FileNotFoundError:
        return False, None
    except OSError as e:
        return False, FileopsError(str(e))
    return os.path.isdir(dir), None


def FileExists(path: str) -> tuple[bool, FileopsError | None]:
    """Report whether path exists and is a regular file. Mirrors fileops.FileExists."""
    try:
        info = os.stat(path)
    except FileNotFoundError:
        return False, None
    except OSError as e:
        return False, FileopsError(str(e))
    return _STAT_IFMT(info.st_mode) == _STAT_IFREG, None


def IsDir(path: str) -> bool:
    """Report whether path is a directory. Mirrors fileops.IsDir."""
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def IsFile(path: str) -> bool:
    """Report whether path is a regular file. Mirrors fileops.IsFile."""
    try:
        return os.path.isfile(path)
    except OSError:
        return False


def ExecutableDir() -> tuple[str, FileopsError | None]:
    """Return the directory of the currently running executable. Mirrors ExecutableDir."""
    if sys.executable is None or sys.executable == "":
        return "", FileopsError("executable file not found in $PATH")
    return os.path.dirname(sys.executable), None


def HomeDir() -> tuple[str, FileopsError | None]:
    """Return the user's home directory. Mirrors fileops.HomeDir."""
    home = os.environ.get("HOME")
    if not home:
        return "", FileopsError("fileops: cannot determine home dir")
    return home, None


def UserCacheDir() -> tuple[str, FileopsError | None]:
    """Return the per-user cache directory for the current platform. Mirrors UserCacheDir."""
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return base, None
    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".cache"), None
    return "", FileopsError("neither $XDG_CACHE_HOME nor $HOME are defined")


def UserConfigDir() -> tuple[str, FileopsError | None]:
    """Return the per-user configuration directory. Mirrors UserConfigDir."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return base, None
    home = os.environ.get("HOME")
    if home:
        return os.path.join(home, ".config"), None
    return "", FileopsError("neither $XDG_CONFIG_HOME nor $HOME are defined")


def Platform() -> str:
    """Return the runtime platform value. Mirrors fileops.Platform (runtime.GOOS)."""
    return {"win32": "windows", "cygwin": "windows"}.get(sys.platform, sys.platform)


def CleanPath(path: str) -> str:
    """Clean a path, handling edge cases like empty strings. Mirrors CleanPath."""
    if path == "":
        return "."
    return os.path.normpath(path)


def AbsPath(path: str) -> tuple[str, FileopsError | None]:
    """Return an absolute version of path. Mirrors fileops.AbsPath."""
    try:
        return os.path.abspath(path), None
    except OSError as e:
        return "", FileopsError(str(e))


def EnsureTrailingSep(path: str) -> str:
    """Ensure the path ends with the OS path separator. Mirrors EnsureTrailingSep."""
    if not path.endswith(os.sep):
        return path + os.sep
    return path
