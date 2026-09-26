# SPDX-License-Identifier: MIT
"""JSON comment stripping, normalization, and deep-merge helpers."""

from __future__ import annotations

import json
from typing import Any

REPLACE_SENTINEL = "__replace__"


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
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return encoded + "\n"
