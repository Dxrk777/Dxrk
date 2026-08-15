# SPDX-License-Identifier: MIT
"""File merge utilities — ports internal/components/filemerge/.

Writer, section, TOML, JSON merge helpers.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, cast

# ─── Writer ────────────────────────────────────────────────────────────────

MAX_ATOMIC_FILE_SIZE = 16 << 20  # 16 MiB


@dataclass
class WriteResult:
    Changed: bool = False
    Created: bool = False


def write_file_atomic(path: str, content: bytes, perm: int = 0o644) -> WriteResult:
    if perm == 0:
        perm = 0o644

    created = False
    existing = _read_comparable_file(path)
    if existing is not None:
        if existing == content:
            return WriteResult()
    else:
        created = True

    directory = os.path.dirname(path)
    _ensure_atomic_parent_dir(directory, path)

    fd, tmp_path = tempfile.mkstemp(prefix=".gentle-ai-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())

        os.chmod(tmp_path, perm)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return WriteResult(Changed=True, Created=created)


def _read_comparable_file(path: str) -> bytes | None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None

    if stat_mode_is_symlink(st.st_mode):
        return None
    if st.st_size > MAX_ATOMIC_FILE_SIZE:
        return None

    with open(path, "rb") as f:
        data = f.read(MAX_ATOMIC_FILE_SIZE + 1)
    if len(data) > MAX_ATOMIC_FILE_SIZE:
        return None
    return data


def _ensure_atomic_parent_dir(directory: str, path: str) -> None:
    try:
        st = os.lstat(directory)
    except FileNotFoundError:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        st = os.lstat(directory)

    if stat_mode_is_symlink(st.st_mode):
        raise PermissionError(
            f"refusing symlink parent directory {directory!r} for {path!r}"
        )
    if not stat_mode_is_dir(st.st_mode):
        raise NotADirectoryError(
            f"parent path {directory!r} for {path!r} is not a directory"
        )
    if st.st_mode & 0o200 == 0:
        os.chmod(directory, 0o755)


def stat_mode_is_symlink(mode: int) -> bool:
    return (mode & 0o170000) == 0o120000


def stat_mode_is_dir(mode: int) -> bool:
    return (mode & 0o170000) == 0o040000


# ─── Section (markdown sections) ───────────────────────────────────────────

_MARKER_PREFIX = "<!-- dxrk:"
_MARKER_SUFFIX = " -->"
_CLOSE_PREFIX = "<!-- /dxrk:"

_LEGACY_PERSONA_FINGERPRINTS = [
    "## Personality",
    "Senior Architect",
    "## Rules",
]


def strip_legacy_persona_block(content: str) -> str:
    for fp in _LEGACY_PERSONA_FINGERPRINTS:
        if fp not in content:
            return content

    first_marker_idx = content.find(_MARKER_PREFIX)

    zone = content
    if first_marker_idx >= 0:
        zone = content[:first_marker_idx]

    for fp in _LEGACY_PERSONA_FINGERPRINTS:
        if fp not in zone:
            return content

    if first_marker_idx < 0:
        return ""

    remainder = content[first_marker_idx:]
    remainder = remainder.lstrip("\r\n")
    return remainder


_ATL_BEGIN = "<!-- BEGIN:agent-teams-lite -->"
_ATL_END = "<!-- END:agent-teams-lite -->"


def strip_legacy_atl_block(content: str) -> str:
    while True:
        begin_idx = _find_line_start(content, _ATL_BEGIN)
        if begin_idx < 0:
            break
        search_from = begin_idx + len(_ATL_BEGIN)
        rel_end_idx = _find_line_start(content[search_from:], _ATL_END)
        if rel_end_idx < 0:
            break
        end_idx = search_from + rel_end_idx

        before = content[:begin_idx]
        after = content[end_idx + len(_ATL_END) :]
        before = before.rstrip("\r\n")
        after = after.lstrip("\r\n")

        if not before and not after:
            content = ""
            continue

        parts = []
        if before:
            parts.append(before)
        if after:
            parts.append(after)
        content = "\n\n".join(parts)

    content = _remove_line_start_markers(content, _ATL_END)
    content = _remove_line_start_markers(content, _ATL_BEGIN)

    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")
    return content


def _find_line_start(s: str, needle: str) -> int:
    offset = 0
    while True:
        idx = s.find(needle, offset)
        if idx < 0:
            return -1
        if idx == 0 or s[idx - 1] == "\n":
            return idx
        offset = idx + 1
        if offset >= len(s):
            return -1


def _remove_line_start_markers(content: str, marker: str) -> str:
    while True:
        idx = _find_line_start(content, marker)
        if idx < 0:
            return content
        end = idx + len(marker)
        if end < len(content) and content[end] == "\r":
            end += 1
        if end < len(content) and content[end] == "\n":
            end += 1
        content = content[:idx] + content[end:]


def _open_marker(section_id: str) -> str:
    return _MARKER_PREFIX + section_id + _MARKER_SUFFIX


def _close_marker(section_id: str) -> str:
    return _CLOSE_PREFIX + section_id + _MARKER_SUFFIX


def inject_markdown_section(existing: str, section_id: str, content: str) -> str:
    open_m = _open_marker(section_id)
    close_m = _close_marker(section_id)

    open_idx = existing.find(open_m)
    close_idx = existing.find(close_m)

    if open_idx >= 0 and close_idx >= 0 and close_idx > open_idx:
        if not content:
            before = existing[:open_idx]
            after = existing[close_idx + len(close_m) :]
            if after and after[0] == "\n":
                after = after[1:]
            result = before.rstrip("\n")
            if after:
                if result:
                    result += "\n"
                result += after
            elif result:
                result += "\n"
            return result

        before = existing[:open_idx]
        after = existing[close_idx + len(close_m) :]
        result = before + open_m + "\n" + content
        if not content.endswith("\n"):
            result += "\n"
        result += close_m + after
        return result

    if not content:
        return existing

    result = existing
    if existing and not existing.endswith("\n"):
        result += "\n"
    if existing:
        result += "\n"
    result += open_m + "\n" + content
    if not content.endswith("\n"):
        result += "\n"
    result += close_m + "\n"
    return result


# ─── TOML ──────────────────────────────────────────────────────────────────


def upsert_codex_DXRK_MEMORY_block(content: str, dxrk_cmd: str) -> str:
    if not dxrk_cmd:
        dxrk_cmd = "DXRK_MEMORY"
    escaped_cmd = dxrk_cmd.replace("\\", "\\\\")
    block = f'[mcp_servers.DXRK_MEMORY]\ncommand = "{escaped_cmd}"\nargs = ["mcp", "--tools=agent"]'
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")

    kept: list[str] = []
    i = 0
    while i < len(lines):
        trimmed = lines[i].strip()
        if trimmed == "[mcp_servers.DXRK_MEMORY]":
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if nxt.startswith("[") and nxt.endswith("]"):
                    break
                i += 1
            continue
        kept.append(lines[i])
        i += 1

    base = "\n".join(kept).strip()
    if not base:
        return block + "\n"
    return base + "\n\n" + block + "\n"


def upsert_top_level_toml_string(content: str, key: str, value: str) -> str:
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")
    line_value = f'{key} = "{value}"'

    cleaned: list[str] = []
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith(key + " ") or trimmed.startswith(key + "="):
            continue
        cleaned.append(line)

    insert_at = len(cleaned)
    for i, line in enumerate(cleaned):
        trimmed = line.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            insert_at = i
            break

    out = cleaned[:insert_at] + [line_value] + cleaned[insert_at:]
    return "\n".join(out).strip() + "\n"


# ─── JSON merge ────────────────────────────────────────────────────────────

_REPLACE_SENTINEL = "__replace__"


def merge_json_objects(base_json: bytes, overlay_json: bytes) -> bytes:
    base = _unmarshal_json_object(base_json) or {}
    overlay = _unmarshal_json_object(overlay_json)
    if overlay is None:
        raise ValueError("cannot unmarshal overlay json")

    merged = _merge_objects(base, overlay)
    encoded = json.dumps(merged, indent=2, ensure_ascii=False)
    return (encoded + "\n").encode("utf-8")


def _unmarshal_json_object(raw: bytes) -> dict[str, Any] | None:
    if not raw.strip():
        return {}
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        pass
    normalized = _normalize_json(raw)
    try:
        return cast(dict[str, Any], json.loads(normalized))
    except json.JSONDecodeError:
        return None


def _normalize_json(raw: bytes) -> bytes:
    return _strip_trailing_commas(_strip_json_comments(raw))


def _strip_json_comments(raw: bytes) -> bytes:
    out = bytearray()
    in_string = False
    escaped = False
    in_line = False
    in_block = False

    i = 0
    while i < len(raw):
        ch = raw[i]

        if in_line:
            if ch == ord("\n"):
                in_line = False
                out.append(ch)
            i += 1
            continue

        if in_block:
            if ch == ord("*") and i + 1 < len(raw) and raw[i + 1] == ord("/"):
                in_block = False
                i += 2
                continue
            i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == ord("\\"):
                escaped = True
                i += 1
                continue
            if ch == ord('"'):
                in_string = False
            i += 1
            continue

        if ch == ord('"'):
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ord("/") and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == ord("/"):
                in_line = True
                i += 2
                continue
            if nxt == ord("*"):
                in_block = True
                i += 2
                continue

        out.append(ch)
        i += 1

    return bytes(out)


def _strip_trailing_commas(raw: bytes) -> bytes:
    out = bytearray()
    in_string = False
    escaped = False

    i = 0
    while i < len(raw):
        ch = raw[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == ord("\\"):
                escaped = True
                i += 1
                continue
            if ch == ord('"'):
                in_string = False
            i += 1
            continue

        if ch == ord('"'):
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ord(","):
            j = i + 1
            while j < len(raw):
                nxt = raw[j]
                if nxt in (ord(" "), ord("\t"), ord("\n"), ord("\r")):
                    j += 1
                    continue
                if nxt in (ord("}"), ord("]")):
                    ch = 0
                break

        if ch != 0:
            out.append(ch)
        i += 1

    return bytes(out)


def _as_sentinel(v: Any) -> tuple[Any, bool]:
    if isinstance(v, dict) and _REPLACE_SENTINEL in v and len(v) == 1:
        return v[_REPLACE_SENTINEL], True
    return None, False


def _merge_objects(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, overlay_value in overlay.items():
        replacement, is_sentinel = _as_sentinel(overlay_value)
        if is_sentinel:
            result[key] = replacement
            continue

        if key not in result:
            if isinstance(overlay_value, dict):
                result[key] = _merge_objects({}, overlay_value)
            else:
                result[key] = overlay_value
            continue

        base_value = result[key]
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            result[key] = _merge_objects(base_value, overlay_value)
        else:
            result[key] = overlay_value

    return result
