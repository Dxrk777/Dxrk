# SPDX-License-Identifier: MIT
"""File merging, markdown section injection, TOML upserts and atomic writes.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

REPLACE_SENTINEL = "__replace__"

MARKER_PREFIX = "<!-- dxrk:"
MARKER_SUFFIX = " -->"
CLOSE_PREFIX = "<!-- /dxrk:"

ATL_BEGIN_MARKER = "<!-- BEGIN:agent-teams-lite -->"
ATL_END_MARKER = "<!-- END:agent-teams-lite -->"

LEGACY_PERSONA_FINGERPRINTS = ["## Personality", "Senior Architect", "## Rules"]

MAX_ATOMIC_FILE_SIZE = 16 << 20


def strip_json_comments(raw: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    in_line_comment = False
    in_block_comment = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and i + 1 < n and raw[i + 1] == "/":
                in_block_comment = False
                i += 1
            i += 1
            continue

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n:
            nxt = raw[i + 1]
            if nxt == "/":
                in_line_comment = True
                i += 2
                continue
            if nxt == "*":
                in_block_comment = True
                i += 2
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def strip_trailing_commas(raw: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]

        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
                i += 1
                continue
            if ch == "\\":
                escaped = True
                i += 1
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n:
                nxt = raw[j]
                if nxt in " \t\n\r":
                    j += 1
                    continue
                if nxt in "}]":
                    ch = ""
                break

        if ch != "":
            out.append(ch)
        i += 1

    return "".join(out)


def normalize_json(raw: str) -> str:
    return strip_trailing_commas(strip_json_comments(raw))


def unmarshal_json_object(raw: str | bytes) -> dict[str, Any]:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    if text.strip() == "":
        return {}
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        try:
            obj = json.loads(normalize_json(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"unmarshal json: {exc}") from exc
    if not isinstance(obj, dict):
        raise TypeError("unmarshal json: not an object")
    return obj


def as_sentinel(v: Any) -> tuple[Any, bool]:
    if not isinstance(v, dict):
        return None, False
    if REPLACE_SENTINEL in v and len(v) == 1:
        return v[REPLACE_SENTINEL], True
    return None, False


def merge_objects(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)

    for key, overlay_value in overlay.items():
        # If the overlay value is a map with exactly one key "__replace__",
        # use the sentinel's value verbatim — regardless of whether the key
        # exists in base. This allows callers to force atomic replacement of a
        # nested object instead of deep-merging.
        replacement, is_sentinel = as_sentinel(overlay_value)
        if is_sentinel:
            result[key] = replacement
            continue

        if key not in result:
            # Even when there is no base value, recurse into overlay maps so
            # that any nested __replace__ sentinels are unwrapped before they
            # reach the output.
            if isinstance(overlay_value, dict):
                result[key] = merge_objects({}, overlay_value)
            else:
                result[key] = overlay_value
            continue

        base_value = result[key]
        if isinstance(base_value, dict) and isinstance(overlay_value, dict):
            result[key] = merge_objects(base_value, overlay_value)
            continue

        result[key] = overlay_value

    return result


def merge_json_objects(base_json: str | bytes, overlay_json: str | bytes) -> str:
    try:
        base = unmarshal_json_object(base_json)
    except (TypeError, ValueError):
        # Real user machines may have a malformed or non-JSON mcp.json. The
        # installer backup step already snapshots the existing file before
        # apply, so proceeding with an empty base is safe and far preferable
        # to aborting the whole install.
        base = {}

    try:
        overlay = unmarshal_json_object(overlay_json)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unmarshal overlay json: {exc}") from exc

    merged = merge_objects(base, overlay)

    try:
        encoded = json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"marshal merged json: {exc}") from exc

    # json.MarshalIndent-style output HTML-escapes <, > and & inside strings.
    encoded = (
        encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    )
    return encoded + "\n"


def open_marker(section_id: str) -> str:
    return MARKER_PREFIX + section_id + MARKER_SUFFIX


def close_marker(section_id: str) -> str:
    return CLOSE_PREFIX + section_id + MARKER_SUFFIX


def strip_legacy_persona_block(content: str) -> str:
    # Quick check: all fingerprints must be present somewhere in the file.
    for fp in LEGACY_PERSONA_FINGERPRINTS:
        if fp not in content:
            return content

    # Find the position of the first marker — everything before it is the
    # potential legacy zone. If there are no markers, the whole file is the
    # legacy zone.
    first_marker_idx = content.find(MARKER_PREFIX)

    zone = content if first_marker_idx < 0 else content[:first_marker_idx]

    # Verify that ALL fingerprints live in the pre-marker zone. Requiring every
    # fingerprint to appear inside the zone prevents a false positive where,
    # for example, "## Rules" is a legitimate user section header before the
    # first marker while the other two fingerprints exist only inside a marker
    # block.
    for fp in LEGACY_PERSONA_FINGERPRINTS:
        if fp not in zone:
            return content

    if first_marker_idx < 0:
        # No markers at all — the entire file is legacy persona content.
        # Return empty string so the caller can write a fresh section.
        return ""

    # Keep everything from the first marker onwards, trimming any leading
    # blank lines between the stripped block and the first marker.
    return content[first_marker_idx:].lstrip("\r\n")


def find_line_start(s: str, needle: str) -> int:
    offset = 0
    while True:
        idx = s.find(needle, offset)
        if idx < 0:
            return -1
        if idx == 0 or s[idx - 1] == "\n":
            return idx
        # Not at line start — continue searching after this occurrence.
        offset = idx + 1
        if offset >= len(s):
            return -1


def remove_line_start_markers(content: str, marker: str) -> str:
    while True:
        idx = find_line_start(content, marker)
        if idx < 0:
            return content
        end = idx + len(marker)
        # Also consume a trailing line ending (\r\n or \n) if present.
        if end < len(content) and content[end] == "\r":
            end += 1
        if end < len(content) and content[end] == "\n":
            end += 1
        content = content[:idx] + content[end:]


def strip_legacy_atl_block(content: str) -> str:
    while True:
        begin_idx = find_line_start(content, ATL_BEGIN_MARKER)
        if begin_idx < 0:
            # No (more) BEGIN marker — exit the loop and do post-loop cleanup.
            break

        # Search for the END marker starting from after the BEGIN marker so
        # that a stray END marker appearing before BEGIN does not prevent the
        # valid pair from being found.
        search_from = begin_idx + len(ATL_BEGIN_MARKER)
        rel_end_idx = find_line_start(content[search_from:], ATL_END_MARKER)
        if rel_end_idx < 0:
            # Open marker found but no matching close marker — break so that
            # post-loop cleanup still runs (e.g. orphan END markers are removed).
            break
        end_idx = search_from + rel_end_idx

        # Cut out the entire block including both markers.
        before = content[:begin_idx]
        after = content[end_idx + len(ATL_END_MARKER) :]

        # Trim trailing blank lines from the before segment and leading blank
        # lines from the after segment.
        before = before.rstrip("\r\n")
        after = after.lstrip("\r\n")

        if before == "" and after == "":
            content = ""
            continue

        parts: list[str] = []
        if before != "":
            parts.append(before)
            parts.append("\n")
        if after != "":
            if before != "":
                parts.append("\n")
            parts.append(after)
        content = "".join(parts)

    # Remove any orphan markers left behind. A stray END can appear before a
    # valid BEGIN...END pair; a stray BEGIN can appear without a matching END
    # (e.g. a partial manual edit). The loop only strips complete pairs, so
    # leftover markers must be cleaned up here.
    content = remove_line_start_markers(content, ATL_END_MARKER)
    content = remove_line_start_markers(content, ATL_BEGIN_MARKER)

    # Collapse any triple+ newlines into double newlines (done once here,
    # outside the loop, to avoid O(N × content_length) work for N blocks).
    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")

    return content


def inject_markdown_section(existing: str, section_id: str, content: str) -> str:
    open_mark = open_marker(section_id)
    close_mark = close_marker(section_id)

    open_idx = existing.find(open_mark)
    close_idx = existing.find(close_mark)

    # If both markers are found and in the correct order, replace the section.
    if open_idx >= 0 and close_idx >= 0 and close_idx > open_idx:
        # If content is empty, remove the entire section including markers.
        if content == "":
            before = existing[:open_idx]
            after = existing[close_idx + len(close_mark) :]

            # Clean up trailing newline after close marker.
            if len(after) > 0 and after[0] == "\n":
                after = after[1:]
            # Clean up trailing newline before open marker.
            result = before.rstrip("\n")
            if after != "":
                if result != "":
                    result += "\n"
                result += after
            elif result != "":
                result += "\n"
            return result

        before = existing[:open_idx]
        after = existing[close_idx + len(close_mark) :]

        parts = [before, open_mark, "\n", content]
        if not content.endswith("\n"):
            parts.append("\n")
        parts.append(close_mark)
        parts.append(after)
        return "".join(parts)

    # If content is empty and section doesn't exist, return existing unchanged.
    if content == "":
        return existing

    # Section not found — append at end.
    parts = [existing]
    if existing != "" and not existing.endswith("\n"):
        parts.append("\n")
    if existing != "":
        parts.append("\n")
    parts.append(open_mark)
    parts.append("\n")
    parts.append(content)
    if not content.endswith("\n"):
        parts.append("\n")
    parts.append(close_mark)
    parts.append("\n")
    return "".join(parts)


def go_quote(value: str) -> str:
    # Mirrors strconv.Quote / fmt %q: double-quoted with escaped
    # backslashes, quotes and control characters.
    return json.dumps(value, ensure_ascii=True)


def upsert_codex_mcp_server_block(
    content: str, server_name: str, cmd: str, args: list[str]
) -> str:
    if server_name == "":
        server_name = "dxrk-memory"
    if cmd == "":
        cmd = "dxrk-memory"

    args_literal = "[]"
    if len(args) > 0:
        quoted = [go_quote(a) for a in args]
        args_literal = "[" + ", ".join(quoted) + "]"

    section = "[mcp_servers." + server_name + "]"
    block = section + "\ncommand = " + go_quote(cmd) + "\nargs = " + args_literal

    content = content.replace("\r\n", "\n")
    lines = content.split("\n")

    kept: list[str] = []
    i = 0
    while i < len(lines):
        trimmed = lines[i].strip()
        if trimmed == section:
            # Skip the old block header and all its key-value lines.
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
    if base == "":
        return block + "\n"

    return base + "\n\n" + block + "\n"


def upsert_codex_dxrk_memory_block(content: str, dxrk_memory_cmd: str = "") -> str:
    return upsert_codex_mcp_server_block(
        content, "dxrk-memory", dxrk_memory_cmd, ["mcp", "--tools=agent"]
    )


def upsert_top_level_toml_string(content: str, key: str, value: str) -> str:
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")
    line_value = key + " = " + go_quote(value)

    # Remove all existing occurrences of the key.
    cleaned: list[str] = []
    for line in lines:
        trimmed = line.strip()
        if trimmed.startswith((key + " ", key + "=")):
            continue
        cleaned.append(line)

    # Find insertion point: before the first [section] header.
    insert_at = len(cleaned)
    for i, line in enumerate(cleaned):
        trimmed = line.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            insert_at = i
            break

    out = cleaned[:insert_at]
    out.append(line_value)
    out.extend(cleaned[insert_at:])

    return "\n".join(out).strip() + "\n"


@dataclass(frozen=True)
class WriteResult:
    Changed: bool
    Created: bool


def _default_sync_dir(dir: str) -> None:
    try:
        fd = os.open(dir, os.O_RDONLY)
    except OSError as exc:
        raise OSError(f"open parent directory {dir!r}: {exc}") from exc
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# Module-level vars so tests can override them without spawning a real
# Windows process (runtimeGOOS / syncDirFn overrides).
_runtime_goos: str = sys.platform
_sync_dir_fn = _default_sync_dir


def read_comparable_file(path: str) -> bytes:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing to read symlink {path!r}")
    if info.st_size > MAX_ATOMIC_FILE_SIZE:
        raise OSError(
            f"file {path!r} exceeds max atomic compare size {MAX_ATOMIC_FILE_SIZE} bytes"
        )

    with open(path, "rb") as file:
        data = file.read(MAX_ATOMIC_FILE_SIZE + 1)
    if len(data) > MAX_ATOMIC_FILE_SIZE:
        raise OSError(
            f"file {path!r} exceeds max atomic compare size {MAX_ATOMIC_FILE_SIZE} bytes"
        )
    return data


def ensure_atomic_parent_dir(dir: str, path: str) -> None:
    try:
        info = os.lstat(dir)
    except FileNotFoundError:
        try:
            os.makedirs(dir, 0o700)
        except OSError as exc:
            raise OSError(f"create parent directories for {path!r}: {exc}") from exc
        info = os.lstat(dir)
    except OSError as exc:
        raise OSError(f"stat parent directory for {path!r}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode):
        raise OSError(f"refusing symlink parent directory {dir!r} for {path!r}")
    if not stat.S_ISDIR(info.st_mode):
        raise OSError(f"parent path {dir!r} for {path!r} is not a directory")
    if info.st_mode & 0o200 == 0:
        try:
            os.chmod(dir, 0o750)
        except OSError as exc:
            raise OSError(
                f"relax parent directory permissions for {path!r}: {exc}"
            ) from exc


def write_file_atomic(path: str, content: bytes, perm: int = 0o600) -> WriteResult:
    if perm == 0:
        perm = 0o600

    created = False
    try:
        existing = read_comparable_file(path)
    except FileNotFoundError:
        created = True
    except OSError as exc:
        raise OSError(f"read existing file {path!r}: {exc}") from exc
    else:
        if existing == content:
            return WriteResult(Changed=False, Created=False)

    dir = os.path.dirname(path)
    ensure_atomic_parent_dir(dir, path)

    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".dxrk-", suffix=".tmp", dir=dir)
    except OSError as exc:
        raise OSError(f"create temp file for {path!r}: {exc}") from exc

    cleanup = True
    try:
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(content)
                tmp.flush()
                os.fchmod(tmp.fileno(), perm)
                os.fsync(tmp.fileno())
        except OSError as exc:
            raise OSError(f"write temp file for {path!r}: {exc}") from exc

        try:
            os.rename(tmp_path, path)
        except OSError as exc:
            raise OSError(f"replace {path!r} atomically: {exc}") from exc

        # Sync the parent directory to flush the new directory entry to disk.
        # On Windows, NTFS returns ErrPermission when syncing a directory fd —
        # tolerate that specific error only. Any other error is still fatal.
        try:
            _sync_dir_fn(dir)
        except PermissionError as exc:
            if _runtime_goos != "win32":
                raise OSError(f"sync parent directory for {path!r}: {exc}") from exc
        except OSError as exc:
            raise OSError(f"sync parent directory for {path!r}: {exc}") from exc

        cleanup = False
        return WriteResult(Changed=True, Created=created)
    finally:
        if cleanup:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# Aliases
MergeJSONObjects = merge_json_objects
StripLegacyATLBlock = strip_legacy_atl_block
StripLegacyPersonaBlock = strip_legacy_persona_block
InjectMarkdownSection = inject_markdown_section
UpsertCodexMCPServerBlock = upsert_codex_mcp_server_block
UpsertCodexDxrkMemoryBlock = upsert_codex_dxrk_memory_block
UpsertTopLevelTOMLString = upsert_top_level_toml_string
WriteFileAtomic = write_file_atomic
