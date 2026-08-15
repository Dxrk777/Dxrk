# SPDX-License-Identifier: MIT
"""File operation utilities.

Provides safe, cached, atomic file operations with encoding detection:
path validation and utilities, safe reading with encoding detection,
binary detection, atomic writes, search-and-replace editing with
indentation preservation and regex support, and a thread-safe LRU
file-content cache with TTL and modification-time auto-invalidation.

Concurrency mapping:

* ``sync.RWMutex`` -> ``threading.RLock`` / ``threading.Lock``
* ``time.Time`` -> ``datetime`` (wall clock)
* ``time.Duration`` -> ``datetime.timedelta``
* goroutines -> daemon threads
* ``errors.New`` sentinels -> :class:`FileopsError` instances returned
  as values (never raised)

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``ValidatePath`` splits on the OS separator and rejects any ``..``
  component.
* ``DetectEncoding`` returns the same labels (UTF-8, UTF-8-BOM,
  UTF-16LE, UTF-16BE, ASCII, Latin-1, Unknown).
* ``ReadFile`` never uses mmap; the original read is a plain
  ``io.ReadAll`` fallback, so both languages read the whole file.
* ``InvalidatePattern`` matches globs against the base name with
  ``fnmatch``, ``fnmatch``-style matching for names without
  path separators.
* ``splitChars``-style byte splitting does not apply here; Python
  strings are Unicode, so content is decoded with replacement.
* ``EditError`` mirrors the original struct plus its ``Error()`` formatting.
* ``ReadImage`` requires Pillow the original decodes
  image headers via the standard library.
"""

from __future__ import annotations

import base64
import fnmatch
import glob as _glob
import io
import os
import re as _re
import shutil
import stat as _stat
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

try:  # pragma: no cover - exercised only when Pillow is absent
    from PIL import Image as _PILImage  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _PILImage = None

_PILLOW_REQUIRED = (
    "fileops: Pillow (PIL) is required for this operation "
    "(install 'pillow' in the project environment)"
)

_MAX_TEXT_SIZE = 10 * 1024 * 1024
_READ_LIMIT_DEFAULT = 50 * 1024 * 1024
_BINARY_CHECK_SIZE = 8192
_WATCH_INTERVAL = 5.0

_STAT_IFMT = _stat.S_IFMT
_STAT_IFREG = _stat.S_IFREG


class FileopsError(Exception):
    """Represents a fileops package error. Mirrors fileops error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrNotAbsolute = FileopsError("fileops: path is not absolute")
ErrOutsideDir = FileopsError("fileops: path is outside allowed directory")
ErrPathTraversal = FileopsError("fileops: path contains traversal components")
ErrNullByte = FileopsError("fileops: path contains null byte")
ErrBinaryFile = FileopsError("fileops: file is binary")
ErrFileTooLarge = FileopsError("fileops: file exceeds read limit")
ErrInvalidImage = FileopsError("fileops: file is not a valid image")


def ValidatePath(path: str) -> FileopsError | None:
    """Check a file path for traversal attacks and null bytes. Mirrors ValidatePath."""
    if "\x00" in path:
        return ErrNullByte
    cleaned = os.path.normpath(path)
    for part in cleaned.split(os.sep):
        if part == "..":
            return ErrPathTraversal
    return None


# --- read.go ---


@dataclass
class FileContent:
    """Holds the result of reading a file. Mirrors fileops.FileContent."""

    path: str = ""
    content: str = ""
    encoding: str = ""
    size: int = 0
    mod_time: datetime = field(default_factory=datetime.now)
    line_count: int = 0


@dataclass
class ImageData:
    """Holds a file read as a base64-encoded image. Mirrors fileops.ImageData."""

    media_type: str = ""
    base64_data: str = ""
    width: int = 0
    height: int = 0


def DetectEncoding(data: bytes) -> str:
    """Inspect a byte slice and return a best-guess encoding label. Mirrors DetectEncoding."""
    if len(data) == 0:
        return "UTF-8"
    if len(data) >= 3 and data[0] == 0xEF and data[1] == 0xBB and data[2] == 0xBF:
        return "UTF-8-BOM"
    if len(data) >= 2:
        if data[0] == 0xFF and data[1] == 0xFE:
            return "UTF-16LE"
        if data[0] == 0xFE and data[1] == 0xFF:
            return "UTF-16BE"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        for ch in text:
            if ord(ch) > 127:
                return "UTF-8"
        return "ASCII"
    latin1 = 0
    for b in data:
        if (0x20 <= b < 0x7F) or b >= 0xA0:
            latin1 += 1
    if latin1 / len(data) > 0.9:
        return "Latin-1"
    return "Unknown"


def IsBinary(path: str) -> tuple[bool, FileopsError | None]:
    """Detect whether a file is likely binary by inspecting the first bytes. Mirrors IsBinary."""
    try:
        with open(path, "rb") as f:
            buf = f.read(_BINARY_CHECK_SIZE)
    except OSError as e:
        return False, FileopsError(str(e))
    if b"\x00" in buf:
        return True, None
    non_text = 0
    for b in buf:
        if b < 0x09 or (b > 0x0D and b < 0x20):
            non_text += 1
    return non_text / max(len(buf), 1) > 0.1, None


def ReadFile(path: str) -> tuple[FileContent | None, FileopsError | None]:
    """Read a file, detect its encoding, and return a FileContent. Mirrors ReadFile."""
    err = ValidatePath(path)
    if err is not None:
        return None, err
    try:
        info = os.stat(path)
    except OSError as e:
        return None, FileopsError(str(e))
    if os.path.isdir(path):
        return None, FileopsError(f"fileops: {path} is a directory")
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, FileopsError(str(e))
    enc = DetectEncoding(data)
    content = data.decode("utf-8", errors="replace")
    lines = content.count("\n")
    if len(content) > 0 and content[-1] != "\n":
        lines += 1
    return (
        FileContent(
            path=path,
            content=content,
            encoding=enc,
            size=info.st_size,
            mod_time=datetime.fromtimestamp(info.st_mtime),
            line_count=lines,
        ),
        None,
    )


def ReadFileLines(
    path: str, offset: int, limit: int
) -> tuple[list[str], int, FileopsError | None]:
    """Read a file and return lines[offset:offset+limit] plus the total count. Mirrors ReadFileLines."""
    fc, err = ReadFile(path)
    if err is not None or fc is None:
        return [], 0, err
    lines = fc.content.split("\n")
    total = len(lines)
    if offset < 0:
        offset = 0
    if offset >= total:
        return [], total, None
    end = offset + limit
    if limit <= 0 or end > total:
        end = total
    return lines[offset:end], total, None


def ReadImage(path: str) -> tuple[ImageData | None, FileopsError | None]:
    """Read an image file and return it as base64 data with dimensions. Mirrors ReadImage."""
    err = ValidatePath(path)
    if err is not None:
        return None, err
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return None, FileopsError(str(e))
    if _PILImage is None:
        raise ImportError(_PILLOW_REQUIRED)
    try:
        with _PILImage.open(io.BytesIO(data)) as img:
            width, height = img.size
    except Exception as e:  # noqa: BLE001 - any decode failure
        return None, FileopsError(f"{ErrInvalidImage}: {e}")
    media_type = "image/png"
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif ext == ".gif":
        media_type = "image/gif"
    return (
        ImageData(
            media_type=media_type,
            base64_data=base64.b64encode(data).decode("ascii"),
            width=width,
            height=height,
        ),
        None,
    )


# --- write.go ---


@dataclass
class WriteOpts:
    """Configures how WriteFile behaves. Mirrors fileops.WriteOpts."""

    create_dirs: bool = False
    mode: int = 0
    backup: bool = False
    overwrite: bool = True
    encoding: str = ""


def DefaultWriteOpts() -> WriteOpts:
    """Return sensible defaults. Mirrors fileops.DefaultWriteOpts."""
    return WriteOpts(create_dirs=True, mode=0o644, overwrite=True)


def WriteFile(path: str, content: str, opts: WriteOpts) -> FileopsError | None:
    """Write content to path atomically. Mirrors fileops.WriteFile."""
    err = ValidatePath(path)
    if err is not None:
        return err
    if opts.mode == 0:
        opts.mode = 0o644
    if opts.create_dirs:
        err = EnsureDir(path)
        if err is not None:
            return err
    if not opts.overwrite:
        if os.path.exists(path):
            return FileopsError(f"fileops: file exists and Overwrite is false: {path}")
    if opts.backup:
        if os.path.exists(path):
            _, err = BackupFile(path)
            if err is not None:
                return FileopsError(f"fileops: backup failed: {err}")
    return WriteAtomic(path, content.encode("utf-8"))


def WriteAtomic(path: str, data: bytes) -> FileopsError | None:
    """Write to a temp file in the same directory, then rename. Mirrors WriteAtomic."""
    err = ValidatePath(path)
    if err is not None:
        return err
    dirname = os.path.dirname(path)
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".fileops-tmp-", dir=dirname)
    except OSError as e:
        return FileopsError(f"fileops: create temp: {e}")
    cleanup = True
    try:
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                try:
                    f.flush()
                    os.fsync(f.fileno())
                except OSError as e:
                    return FileopsError(f"fileops: sync temp: {e}")
        except OSError as e:
            return FileopsError(f"fileops: write temp: {e}")
        try:
            os.replace(tmp_name, path)
        except OSError as e:
            return FileopsError(f"fileops: rename: {e}")
        cleanup = False
        return None
    finally:
        if cleanup:
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def BackupFile(path: str) -> tuple[str, FileopsError | None]:
    """Create a backup of path at path.bak. Mirrors fileops.BackupFile."""
    err = ValidatePath(path)
    if err is not None:
        return "", err
    bak = path + ".bak"
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        return "", FileopsError(f"fileops: read for backup: {e}")
    try:
        info = os.stat(path)
    except OSError as e:
        return "", FileopsError(str(e))
    try:
        with open(bak, "wb") as f:
            f.write(data)
        os.chmod(bak, _stat.S_IMODE(info.st_mode))
    except OSError as e:
        return "", FileopsError(f"fileops: write backup: {e}")
    return bak, None


def WriteLines(path: str, lines: list[str], opts: WriteOpts) -> FileopsError | None:
    """Write each string as a line (joined by newlines) atomically. Mirrors WriteLines."""
    text = "\n".join(lines)
    if len(lines) > 0:
        text += "\n"
    return WriteFile(path, text, opts)


def AppendFile(path: str, content: str) -> FileopsError | None:
    """Append content to the file at path, creating it if necessary. Mirrors AppendFile."""
    err = ValidatePath(path)
    if err is not None:
        return err
    try:
        with open(path, "a") as f:
            f.write(content)
    except OSError as e:
        return FileopsError(str(e))
    return None


def EnsureDir(path: str) -> FileopsError | None:
    """Create parent directories for the given file path. Mirrors fileops.EnsureDir."""
    try:
        os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    except OSError as e:
        return FileopsError(str(e))
    return None


# --- edit.go ---


@dataclass
class EditOp:
    """Describes a single find-and-replace operation. Mirrors fileops.EditOp."""

    old_text: str = ""
    new_text: str = ""
    line: int = 0


@dataclass
class RegexEditOp:
    """Describes a regex-based find-and-replace operation. Mirrors fileops.RegexEditOp."""

    pattern: str = ""
    replacement: str = ""
    flags: str = ""
    line: int = 0


@dataclass
class EditError(Exception):
    """Reports a single failed edit operation. Mirrors fileops.EditError."""

    op_index: int = 0
    message: str = ""
    line: int = 0

    def __str__(self) -> str:
        if self.line > 0:
            return f"edit op {self.op_index} (line {self.line}): {self.message}"
        return f"edit op {self.op_index}: {self.message}"


def EditFile(path: str, edits: list[EditOp]) -> FileopsError | EditError | None:
    """Read the file, apply all edits, and write back atomically. Mirrors EditFile."""
    err = ValidatePath(path)
    if err is not None:
        return err
    try:
        with open(path, "rb") as f:
            content = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return FileopsError(str(e))
    errs = ValidateEdits(content, edits)
    if len(errs) > 0:
        return errs[0]
    result, apply_err = ApplyEdits(content, edits)
    if apply_err is not None:
        return apply_err
    return WriteAtomic(path, result.encode("utf-8"))


def ValidateEdits(content: str, edits: list[EditOp]) -> list[EditError]:
    """Check that every edit's OldText can be found in content. Mirrors ValidateEdits."""
    errs: list[EditError] = []
    for i, op in enumerate(edits):
        if op.old_text not in content:
            errs.append(
                EditError(
                    op_index=i,
                    message=f"old text not found: {op.old_text[:80]}",
                    line=op.line,
                )
            )
    return errs


def ApplyEdits(content: str, edits: list[EditOp]) -> tuple[str, EditError | None]:
    """Apply all edits sequentially to content. Mirrors fileops.ApplyEdits."""
    for i, op in enumerate(edits):
        idx = content.find(op.old_text)
        if idx < 0:
            return "", EditError(op_index=i, message="old text not found")
        indent = _extract_indent(content, idx)
        new_text = _preserve_indent(op.new_text, indent)
        content = content[:idx] + new_text + content[idx + len(op.old_text) :]
    return content, None


def FindAndReplace(content: str, old: str, new: str) -> tuple[str, int, None]:
    """Replace the first occurrence of old with new in content. Mirrors FindAndReplace."""
    idx = content.find(old)
    if idx < 0:
        return content, 0, None
    result = content[:idx] + new + content[idx + len(old) :]
    return result, 1, None


def FindAndReplaceAll(content: str, old: str, new: str) -> tuple[str, int, None]:
    """Replace every occurrence of old with new in content. Mirrors FindAndReplaceAll."""
    count = content.count(old)
    if count == 0:
        return content, 0, None
    return content.replace(old, new), count, None


def ApplyRegexEdits(
    content: str, edits: list[RegexEditOp]
) -> tuple[str, int, FileopsError | None]:
    """Apply regex-based edits to content. Mirrors fileops.ApplyRegexEdits."""
    total_replaced = 0
    for i, op in enumerate(edits):
        flags = op.flags.replace("g", "")
        pattern = op.pattern
        if flags:
            pattern = "(?" + flags + ")" + pattern
        try:
            re_obj = _re.compile(pattern)
        except _re.error as e:
            return "", 0, FileopsError(f"regex edit op {i}: {e}")
        matches = re_obj.findall(content)
        total_replaced += len(matches)
        content = re_obj.sub(op.replacement, content)
    return content, total_replaced, None


def _extract_indent(content: str, offset: int) -> str:
    """Return the leading whitespace of the line containing offset. Mirrors extractIndent."""
    start = offset
    while start > 0 and content[start - 1] != "\n":
        start -= 1
    indent = ""
    for i in range(start, len(content)):
        ch = content[i]
        if ch == " " or ch == "\t":
            indent += ch
        else:
            break
    return indent


def _preserve_indent(text: str, indent: str) -> str:
    """Prepend indent to each line of text except the first. Mirrors preserveIndent."""
    if indent == "":
        return text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i] != "":
            lines[i] = indent + lines[i]
    return "\n".join(lines)


def EditFileRegex(path: str, edits: list[RegexEditOp]) -> FileopsError | None:
    """Read the file, apply regex edits, and write back atomically. Mirrors EditFileRegex."""
    err = ValidatePath(path)
    if err is not None:
        return err
    try:
        with open(path, "rb") as f:
            content = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return FileopsError(str(e))
    result, _, err = ApplyRegexEdits(content, edits)
    if err is not None:
        return err
    return WriteAtomic(path, result.encode("utf-8"))


# --- path.go ---


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
        with tempfile.NamedTemporaryFile(
            delete=False, prefix="fileops-", suffix=ext
        ) as f:
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
        info = os.stat(dir)
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


# --- cache.go ---


@dataclass
class CacheEntry:
    """A single cached file. Mirrors fileops.CacheEntry."""

    path: str = ""
    content: str = ""
    size: int = 0
    mod_time: datetime = field(default_factory=datetime.now)
    expiry: datetime = field(default_factory=datetime.now)


@dataclass
class CacheStats:
    """Reports cache performance. Mirrors fileops.CacheStats."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    entries: int = 0
    hit_rate: float = 0.0
    size_bytes: int = 0


class FileCache:
    """A thread-safe LRU file content cache with TTL expiration. Mirrors FileCache."""

    def __init__(self, max_entries: int, ttl: timedelta | None) -> None:
        if max_entries < 1:
            max_entries = 256
        self._mu = threading.RLock()
        self._entries: dict[str, CacheEntry] = {}
        self._order: list[str] = []
        self._max_entries = max_entries
        self._ttl = ttl
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._watchers: dict[str, list[Callable[[str], None]]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def Get(self, path: str) -> tuple[str, bool]:
        """Return cached content for path if present and not expired. Mirrors Get."""
        with self._mu:
            entry = self._entries.get(path)
            if entry is None:
                self._misses += 1
                return "", False
            if datetime.now() > entry.expiry:
                self._remove_locked(path)
                self._misses += 1
                return "", False
            self._touch_locked(path)
            self._hits += 1
            return entry.content, True

    def Set(self, path: str, content: str) -> None:
        """Cache content for path. Mirrors fileops.FileCache.Set."""
        with self._mu:
            info = None
            try:
                info = os.stat(path)
            except OSError:
                pass
            if info is not None:
                mod_time = datetime.fromtimestamp(info.st_mtime)
                size = info.st_size
            else:
                mod_time = datetime.now()
                size = 0
            entry = CacheEntry(
                path=path,
                content=content,
                size=size,
                mod_time=mod_time,
                expiry=(
                    datetime.now() + self._ttl
                    if self._ttl is not None
                    else datetime.max
                ),
            )
            if path in self._entries:
                self._entries[path] = entry
                self._touch_locked(path)
                return
            while len(self._entries) >= self._max_entries:
                self._evict_oldest_locked()
            self._entries[path] = entry
            self._order.append(path)

    def Invalidate(self, path: str) -> None:
        """Remove a single entry from the cache. Mirrors Invalidate."""
        with self._mu:
            self._remove_locked(path)

    def InvalidateAll(self) -> None:
        """Clear the entire cache. Mirrors InvalidateAll."""
        with self._mu:
            self._entries = {}
            self._order = []

    def InvalidatePattern(self, pattern: str) -> None:
        """Remove entries whose path base name matches the glob pattern. Mirrors InvalidatePattern."""
        with self._mu:
            matched = [
                p
                for p in self._entries
                if fnmatch.fnmatchcase(os.path.basename(p), pattern)
            ]
            for p in matched:
                self._remove_locked(p)

    def InvalidatePrefix(self, prefix: str) -> None:
        """Remove all entries whose path starts with prefix. Mirrors InvalidatePrefix."""
        with self._mu:
            matched = [p for p in self._entries if p.startswith(prefix)]
            for p in matched:
                self._remove_locked(p)

    def Watch(self, path: str, callback: Callable[[str], None]) -> None:
        """Register a callback that fires when path is detected as modified. Mirrors Watch."""
        with self._mu:
            self._watchers.setdefault(path, []).append(callback)

    def Stats(self) -> CacheStats:
        """Return current cache statistics. Mirrors fileops.Stats."""
        with self._mu:
            total_size = sum(e.size for e in self._entries.values())
            total = self._hits + self._misses
            rate = 0.0
            if total > 0:
                rate = self._hits / total
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                evictions=self._evictions,
                entries=len(self._entries),
                hit_rate=rate,
                size_bytes=total_size,
            )

    def Close(self) -> None:
        """Stop the background watcher thread. Mirrors fileops.Close."""
        self._stop.set()

    def GetOrLoad(
        self, path: str, loader: Callable[[str], str | tuple[str, FileopsError | None]]
    ) -> tuple[str, FileopsError | None]:
        """Return cached content or load it via loader, caching the result. Mirrors GetOrLoad."""
        content, ok = self.Get(path)
        if ok:
            return content, None
        result = loader(path)
        if isinstance(result, tuple):
            content, err = result
        else:
            content, err = result, None
        if err is not None:
            return "", err
        self.Set(path, content)
        return content, None

    def Paths(self) -> list[str]:
        """Return all currently cached file paths. Mirrors fileops.Paths."""
        with self._mu:
            return list(self._order)

    def Size(self) -> int:
        """Return the number of entries in the cache. Mirrors fileops.Size."""
        with self._mu:
            return len(self._entries)

    def Contains(self, path: str) -> bool:
        """Report whether path is currently cached and not expired. Mirrors Contains."""
        with self._mu:
            entry = self._entries.get(path)
            if entry is None:
                return False
            return datetime.now() <= entry.expiry

    def Keys(self) -> list[str]:
        """Return all cached keys (alias for Paths). Mirrors fileops.Keys."""
        return self.Paths()

    def _touch_locked(self, path: str) -> None:
        for i, p in enumerate(self._order):
            if p == path:
                self._order.pop(i)
                self._order.append(path)
                return

    def _remove_locked(self, path: str) -> None:
        self._entries.pop(path, None)
        for i, p in enumerate(self._order):
            if p == path:
                self._order.pop(i)
                return

    def _evict_oldest_locked(self) -> None:
        if len(self._order) == 0:
            return
        oldest = self._order.pop(0)
        self._entries.pop(oldest, None)
        self._evictions += 1

    def _watch_loop(self) -> None:
        while not self._stop.wait(_WATCH_INTERVAL):
            self._poll_watchers()

    def _poll_watchers(self) -> None:
        with self._mu:
            paths = list(self._watchers)
            cbs = {p: list(fns) for p, fns in self._watchers.items()}
        for p in paths:
            try:
                info = os.stat(p)
            except OSError:
                continue
            with self._mu:
                entry = self._entries.get(p)
            if (
                entry is not None
                and datetime.fromtimestamp(info.st_mtime) > entry.mod_time
            ):
                with self._mu:
                    self._remove_locked(p)
                for cb in cbs.get(p, []):
                    cb(p)


def NewFileCache(max_entries: int, ttl: timedelta | None) -> FileCache:
    """Create a cache holding at most max_entries entries for the given TTL. Mirrors NewFileCache."""
    cache = FileCache(max_entries=max_entries, ttl=ttl)
    cache._thread = threading.Thread(target=cache._watch_loop, daemon=True)
    cache._thread.start()
    return cache
