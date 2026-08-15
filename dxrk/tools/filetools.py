# SPDX-License-Identifier: MIT
"""File manipulation tools: read, write, edit, glob, and grep. Registered via register_all(). Tools follow
the repo contract of returning ``(result, error)`` tuples.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any

from dxrk.tools import Registry, ToolDef, build

MAX_READ_SIZE = 10 * 1024 * 1024
MAX_WRITE_SIZE = 50 * 1024 * 1024
MAX_EDIT_SIZE = 100 * 1024 * 1024
MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 500
MAX_LINE_LENGTH = 1000

_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")

_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}

_SKIP_DIRS = {"node_modules", "vendor", ".git", ".hg", ".svn", "__pycache__"}


def _detect_encoding(data: bytes) -> str:
    if len(data) >= 2 and data[0] == 0xFF and data[1] == 0xFE:
        return "utf16le"
    if len(data) >= 2 and data[0] == 0xFE and data[1] == 0xFF:
        return "utf16be"
    if len(data) >= 3 and data[0] == 0xEF and data[1] == 0xBB and data[2] == 0xBF:
        return "utf8-bom"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"
    return "utf8"


def _read_bytes(path: str, max_size: int) -> tuple[bytes | None, str | None]:
    info = os.stat(path)
    if info.st_size > max_size:
        return None, f"file {path!r} exceeds maximum read size ({max_size} bytes)"
    with open(path, "rb") as f:
        return f.read(), None


def _validate_abs_path(path: Any) -> str | None:
    if not isinstance(path, str) or path == "":
        return "file_path must be a non-empty string"
    if not os.path.isabs(path):
        return "file_path must be an absolute path"
    return None


def _execute_file_read(
    _ctx: Any, input_: dict[str, Any] | None
) -> tuple[Any, str | None]:
    assert input_ is not None
    file_path: str = input_["file_path"]
    try:
        info = os.stat(file_path)
    except FileNotFoundError:
        return None, f"file does not exist: {file_path}"
    except OSError as e:
        return None, f"stat {file_path!r}: {e}"
    if os.path.isdir(file_path):
        return None, f"{file_path!r} is a directory, not a file"
    if info.st_size > MAX_READ_SIZE:
        return (
            None,
            f"file {file_path!r} exceeds maximum read size ({MAX_READ_SIZE} bytes)",
        )

    ext = os.path.splitext(file_path)[1].lower()
    if ext in _IMAGE_EXTENSIONS:
        data, err = _read_bytes(file_path, MAX_READ_SIZE)
        if err is not None:
            return None, f"read image {file_path!r}: {err}"
        assert data is not None
        return {
            "type": "image",
            "path": file_path,
            "base64": base64.b64encode(data).decode("ascii"),
            "media_type": _IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream"),
            "size_bytes": len(data),
        }, None
    if ext == ".pdf":
        data, err = _read_bytes(file_path, MAX_READ_SIZE)
        if err is not None:
            return None, f"read pdf {file_path!r}: {err}"
        assert data is not None
        return {
            "type": "pdf",
            "path": file_path,
            "base64": base64.b64encode(data).decode("ascii"),
            "size_bytes": len(data),
        }, None

    data, err = _read_bytes(file_path, MAX_READ_SIZE)
    if err is not None:
        return None, f"read {file_path!r}: {err}"
    assert data is not None
    encoding = _detect_encoding(data)
    content = data.decode("utf-8", errors="replace")
    lines = content.split("\n")
    total_lines = len(lines)

    offset = input_.get("offset")
    offset = int(offset) if isinstance(offset, (int, float)) else 0
    if offset < 0:
        offset = 0

    limit = input_.get("limit")
    limit = int(limit) if isinstance(limit, (int, float)) else 0

    start_line = offset
    if start_line > total_lines:
        return {
            "path": file_path,
            "content": "",
            "start_line": total_lines + 1,
            "total_lines": total_lines,
            "encoding": encoding,
            "truncated": False,
            "warning": f"offset {offset} exceeds file length ({total_lines} lines)",
        }, None

    if limit > 0:
        end_line = min(start_line + limit, total_lines)
        selected = lines[start_line:end_line]
    else:
        selected = lines[start_line:]

    return {
        "path": file_path,
        "content": "\n".join(selected),
        "start_line": start_line + 1,
        "num_lines": len(selected),
        "total_lines": total_lines,
        "encoding": encoding,
        "truncated": False,
    }, None


def _execute_file_write(
    _ctx: Any, input_: dict[str, Any] | None
) -> tuple[Any, str | None]:
    assert input_ is not None
    file_path: str = input_["file_path"]
    content: str = input_["content"]

    existed = os.path.exists(file_path)
    parent = os.path.dirname(file_path)
    try:
        os.makedirs(parent, exist_ok=True, mode=0o755)
    except OSError as e:
        return None, f"mkdir {parent!r}: {e}"

    lines_before = 0
    if existed:
        try:
            with open(file_path, "rb") as f:
                lines_before = (
                    f.read().decode("utf-8", errors="replace").count("\n") + 1
                )
        except OSError:
            pass

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return None, f"write {file_path!r}: {e}"

    return {
        "type": "update" if existed else "create",
        "path": file_path,
        "size_bytes": len(content.encode("utf-8")),
        "lines": content.count("\n") + 1,
        "lines_before": lines_before,
    }, None


def _execute_file_edit(
    _ctx: Any, input_: dict[str, Any] | None
) -> tuple[Any, str | None]:
    assert input_ is not None
    file_path: str = input_["file_path"]
    old_string: str = input_["old_string"]
    new_string: str = input_["new_string"]
    replace_all = bool(input_.get("replace_all", False))

    try:
        info = os.stat(file_path)
    except FileNotFoundError:
        return None, f"file does not exist: {file_path}"
    except OSError as e:
        return None, f"read {file_path!r}: {e}"
    if info.st_size > MAX_EDIT_SIZE:
        return None, f"file {file_path!r} is too large to edit ({info.st_size} bytes)"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        return None, f"read {file_path!r}: {e}"

    if old_string not in content:
        return None, f"old_string not found in {file_path!r}"

    count = content.count(old_string)
    if count > 1 and not replace_all:
        return None, (
            f"found {count} matches of old_string in {file_path!r}; "
            "set replace_all=true or provide more context to uniquely identify the instance"
        )

    updated = (
        content.replace(old_string, new_string)
        if replace_all
        else content.replace(old_string, new_string, 1)
    )

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(updated)
    except OSError as e:
        return None, f"write {file_path!r}: {e}"

    return {
        "path": file_path,
        "replacements": count,
        "replace_all": replace_all,
        "lines_before": content.count("\n") + 1,
        "lines_after": updated.count("\n") + 1,
    }, None


def _execute_glob(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
    assert input_ is not None
    pattern: str = input_["pattern"]

    search_path = "."
    if isinstance(input_.get("path"), str) and input_["path"] != "":
        search_path = input_["path"]

    from dxrk.tools import _match_path

    files: list[str] = []

    if "**" not in pattern:
        full_pattern = os.path.join(search_path, pattern)
        try:
            import glob as _glob

            matches = sorted(_glob.glob(full_pattern))
        except OSError as e:
            return None, f"glob {pattern!r}: {e}"
        for m in matches:
            try:
                if not os.path.isdir(m):
                    files.append(m)
            except OSError:
                continue
            if len(files) >= MAX_GLOB_RESULTS:
                break
        return {
            "files": files,
            "count": len(files),
            "truncated": len(matches) > MAX_GLOB_RESULTS,
        }, None

    stopped = False
    for root, dirs, names in os.walk(search_path):
        dirs[:] = [
            d
            for d in dirs
            if not (d.startswith(".") and d != ".") and d not in _SKIP_DIRS
        ]
        for name in names:
            full = os.path.join(root, name)
            try:
                if _match_path(pattern, full):
                    files.append(full)
            except Exception:
                return None, f"walk: invalid pattern {pattern!r}"
            if len(files) >= MAX_GLOB_RESULTS:
                stopped = True
                break
        if stopped:
            break

    return {
        "files": files,
        "count": len(files),
        "truncated": stopped,
    }, None


def _execute_grep(_ctx: Any, input_: dict[str, Any] | None) -> tuple[Any, str | None]:
    assert input_ is not None
    pattern: str = input_["pattern"]

    search_path = "."
    if isinstance(input_.get("path"), str) and input_["path"] != "":
        search_path = input_["path"]

    include = input_.get("include", "")
    include = include if isinstance(include, str) else ""

    case_insensitive = bool(input_.get("-i", False))
    max_results = input_.get("max_results")
    max_results = (
        int(max_results) if isinstance(max_results, (int, float)) else MAX_GREP_RESULTS
    )

    flags = "(?i)" if case_insensitive else ""
    try:
        re_pattern = re.compile(flags + pattern)
    except re.error as e:
        return None, f"compile regex: {e}"

    include_re = None
    if include != "":
        include_pattern = include if "*" in include else "*." + include
        try:
            include_re = re.compile(include_pattern)
        except re.error as e:
            return None, f"compile include pattern: {e}"

    try:
        info = os.stat(search_path)
    except OSError as e:
        return None, f"stat {search_path!r}: {e}"

    matches: list[dict[str, Any]] = []
    file_matches: dict[str, bool] = {}

    def search_file(path: str, base_path: str) -> None:
        rel = os.path.relpath(path, base_path)
        if rel == ".":
            rel = path
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line_num, raw in enumerate(f, start=1):
                    if len(matches) >= max_results:
                        break
                    line = raw.rstrip("\n")
                    if len(line) > MAX_LINE_LENGTH:
                        line = line[:MAX_LINE_LENGTH] + "... [truncated]"
                    if re_pattern.search(line):
                        matches.append(
                            {"file": rel, "line": line_num, "text": line.strip()}
                        )
                        file_matches[rel] = True
        except OSError:
            return

    if not os.path.isdir(search_path):
        search_file(search_path, search_path)
    else:
        for root, dirs, names in os.walk(search_path):
            dirs[:] = [
                d
                for d in dirs
                if not (d.startswith(".") and d != ".") and d not in _SKIP_DIRS
            ]
            for name in names:
                if len(matches) >= max_results:
                    break
                if include_re is not None and not include_re.search(name):
                    continue
                search_file(os.path.join(root, name), search_path)
            if len(matches) >= max_results:
                break

    return {
        "matches": matches,
        "num_matches": len(matches),
        "num_files": len(file_matches),
        "files": sorted(file_matches),
        "truncated": len(matches) >= max_results,
    }, None


def _bool(value: bool | None) -> bool | None:
    return value


def _register(
    reg: Registry,
    name: str,
    description: str,
    input_schema: dict[str, Any],
    execute,
    validate,
    read_only: bool,
) -> None:
    reg.register(
        build(
            ToolDef(
                name=name,
                description=description,
                input_schema=input_schema,
                execute=execute,
                validate=validate,
                is_read_only=read_only,
            )
        )
    )


def register_all(reg: Registry) -> None:
    """Register all file tools (mirrors filetools.RegisterAll)."""
    _register(
        reg,
        "file_read",
        "Read the contents of a file from the local filesystem. Supports text files with offset/limit for line-based reading, and binary files (images, PDFs) returned as base64.",
        {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to read",
                },
                "offset": {
                    "type": "integer",
                    "description": "The line number to start reading from (1-indexed). Only provide if the file is too large to read at once",
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "The number of lines to read. Only provide if the file is too large to read at once.",
                    "minimum": 1,
                },
            },
            "required": ["file_path"],
        },
        _execute_file_read,
        _validate_file_read,
        True,
    )
    _register(
        reg,
        "file_write",
        "Write content to a file, creating parent directories as needed. Overwrites existing files.",
        {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to write (must be absolute, not relative)",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        },
        _execute_file_write,
        _validate_file_write,
        False,
    )
    _register(
        reg,
        "file_edit",
        "Edit a file by performing exact string search-and-replace. The old_string must match exactly (including whitespace and indentation). Use replace_all to replace all occurrences.",
        {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace (must match exactly including whitespace)",
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace old_string with",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default: false)",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        _execute_file_edit,
        _validate_file_edit,
        False,
    )
    _register(
        reg,
        "glob",
        "Recursively find files matching a glob pattern. Supports standard glob syntax including **, *, ?, and character classes.",
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The glob pattern to match files against (e.g. **/*.go, src/**/*.ts)",
                },
                "path": {
                    "type": "string",
                    "description": "The directory to search in. Defaults to the current working directory.",
                },
            },
            "required": ["pattern"],
        },
        _execute_glob,
        _validate_glob,
        True,
    )
    _register(
        reg,
        "grep",
        "Search file contents using regular expressions. Returns matching lines with file paths and line numbers.",
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regular expression pattern to search for in file contents",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to search in. Defaults to current working directory.",
                },
                "include": {
                    "type": "string",
                    "description": "Glob pattern to filter files (e.g. *.go, *.{ts,tsx})",
                },
                "-i": {
                    "type": "boolean",
                    "description": "Case insensitive search",
                    "default": False,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching lines to return (default 500)",
                    "minimum": 1,
                },
            },
            "required": ["pattern"],
        },
        _execute_grep,
        _validate_grep,
        True,
    )


def _validate_file_read(input_: dict[str, Any] | None) -> str | None:
    if input_ is None or input_.get("file_path") is None:
        return "file_path is required"
    return _validate_abs_path(input_.get("file_path"))


def _validate_file_write(input_: dict[str, Any] | None) -> str | None:
    if (
        input_ is None
        or input_.get("file_path") is None
        or input_.get("content") is None
    ):
        return "file_path and content are required"
    err = _validate_abs_path(input_.get("file_path"))
    if err is not None:
        return err
    content = input_.get("content")
    if not isinstance(content, str):
        return "content must be a string"
    if len(content) > MAX_WRITE_SIZE:
        return f"content exceeds maximum write size ({len(content)} > {MAX_WRITE_SIZE} bytes)"
    return None


def _validate_file_edit(input_: dict[str, Any] | None) -> str | None:
    if (
        input_ is None
        or input_.get("file_path") is None
        or input_.get("old_string") is None
        or input_.get("new_string") is None
    ):
        return "file_path, old_string, and new_string are required"
    err = _validate_abs_path(input_.get("file_path"))
    if err is not None:
        return err
    old_str = input_.get("old_string")
    new_str = input_.get("new_string")
    if old_str == new_str:
        return "old_string and new_string are identical; no changes to make"
    return None


def _validate_glob(input_: dict[str, Any] | None) -> str | None:
    if input_ is None or input_.get("pattern") is None:
        return "pattern is required"
    pattern = input_.get("pattern")
    if not isinstance(pattern, str) or pattern == "":
        return "pattern must be a non-empty string"
    search_path = input_.get("path")
    if isinstance(search_path, str) and search_path != "":
        if not os.path.isabs(search_path):
            return "path must be an absolute path"
        if not os.path.exists(search_path):
            return f"path does not exist: {search_path}"
        if not os.path.isdir(search_path):
            return f"path is not a directory: {search_path}"
    return None


def _validate_grep(input_: dict[str, Any] | None) -> str | None:
    if input_ is None or input_.get("pattern") is None:
        return "pattern is required"
    pattern = input_.get("pattern")
    if not isinstance(pattern, str) or pattern == "":
        return "pattern must be a non-empty string"
    flags = "(?i)" if input_.get("-i") else ""
    try:
        re.compile(flags + pattern)
    except re.error as e:
        return f"invalid regex pattern: {e}"
    search_path = input_.get("path")
    if isinstance(search_path, str) and search_path != "":
        if not os.path.isabs(search_path):
            return "path must be an absolute path"
        if not os.path.exists(search_path):
            return f"path does not exist: {search_path}"
    return None
