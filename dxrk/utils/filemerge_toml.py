# SPDX-License-Identifier: MIT
"""TOML upserts and string-quoting helpers for Codex config blocks."""

from __future__ import annotations

import json


def toml_quote(value: str) -> str:
    # Double-quoted with escaped backslashes, quotes and control
    # characters (TOML basic-string compatible for these inputs).
    return json.dumps(value, ensure_ascii=True)


# Backwards-compatible alias (Go-style name, pre-rename).
go_quote = toml_quote


def upsert_codex_mcp_server_block(content: str, server_name: str, cmd: str, args: list[str]) -> str:
    if server_name == "":
        server_name = "dxrk-memory"
    if cmd == "":
        cmd = "dxrk-memory"

    args_literal = "[]"
    if len(args) > 0:
        quoted = [toml_quote(a) for a in args]
        args_literal = "[" + ", ".join(quoted) + "]"

    section = "[mcp_servers." + server_name + "]"
    block = section + "\ncommand = " + toml_quote(cmd) + "\nargs = " + args_literal

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
    return upsert_codex_mcp_server_block(content, "dxrk-memory", dxrk_memory_cmd, ["mcp", "--tools=agent"])


def upsert_top_level_toml_string(content: str, key: str, value: str) -> str:
    content = content.replace("\r\n", "\n")
    lines = content.split("\n")
    line_value = key + " = " + toml_quote(value)

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
