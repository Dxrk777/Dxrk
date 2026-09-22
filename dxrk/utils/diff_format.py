# SPDX-License-Identifier: MIT

"""Diff formatters: unified, context, side-by-side, compact, Markdown, HTML, JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass

from dxrk.utils.diff_model import DefaultContextLines as DefaultContextLines
from dxrk.utils.diff_model import DiffDelete as DiffDelete
from dxrk.utils.diff_model import DiffEqual as DiffEqual
from dxrk.utils.diff_model import DiffInsert as DiffInsert
from dxrk.utils.diff_model import DiffModify as DiffModify
from dxrk.utils.diff_model import DiffResult as DiffResult


@dataclass
class ColorScheme:
    """ANSI color codes for diff output. Mirrors diff.ColorScheme."""

    added: str = "\033[32m"
    removed: str = "\033[31m"
    modified: str = "\033[33m"
    context: str = "\033[37m"
    meta: str = "\033[36m"
    reset: str = "\033[0m"
    bold: str = "\033[1m"

    @property
    def enabled(self) -> bool:
        return self.added != ""


_default_colors = ColorScheme()
_empty_colors = ColorScheme("", "", "", "", "", "", "")


def SetColors(colors: ColorScheme) -> None:
    """Configure the global color scheme for formatted output."""
    global _default_colors
    _default_colors = colors


def _c(code: str, text: str) -> str:
    if code == "":
        return text
    return f"{code}{text}{_default_colors.reset}"


def FormatUnified(result: DiffResult, context_lines: int = DefaultContextLines) -> str:
    """Format a diff as unified output with +/- markers. Mirrors FormatUnified."""
    _ = context_lines  # unused parameter (kept for API parity)
    b: list[str] = []
    for h in result.hunks:
        b.append(
            f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@"
            + (f" {h.context}" if h.context else "")
        )
        for line in h.lines:
            prefix = {"insert": "+", "delete": "-", "modify": "!", "equal": " "}[
                str(line.type)
            ]
            content = (
                line.content.split("\x00")[0]
                if line.type == DiffModify
                else line.content
            )
            if _default_colors.enabled:
                code = {
                    "insert": _default_colors.added,
                    "delete": _default_colors.removed,
                    "modify": _default_colors.modified,
                    "equal": _default_colors.context,
                }[str(line.type)]
                b.append(_c(code, prefix + content))
            else:
                b.append(prefix + content)
    return "\n".join(b) + ("\n" if b else "")


def FormatContext(result: DiffResult, context_lines: int = DefaultContextLines) -> str:
    """Format a diff using context notation with ! and - markers. Mirrors FormatContext."""
    _ = context_lines  # unused parameter (kept for API parity)
    b: list[str] = []
    for h in result.hunks:
        b.append(f"*** {h.old_start},{h.old_count} ***")
        b.append(f"--- {h.new_start},{h.new_count} ---")
        for line in h.lines:
            if line.type == DiffInsert:
                prefix = "+"
            elif line.type == DiffDelete:
                prefix = "-"
            elif line.type == DiffModify:
                prefix = "!"
            else:
                prefix = " "
            content = (
                line.content.split("\x00")[0]
                if line.type == DiffModify
                else line.content
            )
            b.append(prefix + content)
    return "\n".join(b) + ("\n" if b else "")


def FormatSideBySide(
    result: DiffResult, width: int = 80, context_lines: int = DefaultContextLines
) -> str:
    """Format a diff in two columns, old on the left, new on the right. Mirrors FormatSideBySide."""
    _ = context_lines  # unused parameter (kept for API parity)
    if width < 40:
        width = 80
    half = width // 2
    b: list[str] = []
    b.append("-" * width)
    for h in result.hunks:
        b.append(f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@")
        for line in h.lines:
            left = ""
            right = ""
            if line.type == DiffModify:
                parts = line.content.split("\x00")
                left = parts[0] if parts else ""
                right = parts[1] if len(parts) > 1 else ""
            else:
                if line.type in (DiffEqual, DiffDelete):
                    left = line.content
                if line.type in (DiffEqual, DiffInsert):
                    right = line.content
            left = left[:half]
            right = right[:half]
            marker = {"insert": "+", "delete": "-", "modify": "!", "equal": " "}[
                str(line.type)
            ]
            if line.type == DiffInsert:
                left = ""
            b.append(f"{marker}{left:<{half}}| {right}")
    b.append("-" * width)
    return "\n".join(b)


def FormatCompact(result: DiffResult) -> str:
    """Format a diff as compact one-line change summaries. Mirrors FormatCompact."""
    b: list[str] = []
    for h in result.hunks:
        added = removed = 0
        for line in h.lines:
            if line.type == DiffInsert:
                added += 1
            elif line.type == DiffDelete:
                removed += 1
            elif line.type == DiffModify:
                added += 1
                removed += 1
        op = "M"
        if added > 0 and removed == 0:
            op = "A"
        elif removed > 0 and added == 0:
            op = "D"
        b.append(f"{op} {h.old_start}..{h.old_start + h.old_count} +{added} -{removed}")
    return "\n".join(b)


def FormatMarkdown(result: DiffResult) -> str:
    """Format a diff as a Markdown code block. Mirrors FormatMarkdown."""
    b: list[str] = ["```diff"]
    for h in result.hunks:
        b.append(f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@")
        for line in h.lines:
            if line.type == DiffInsert:
                b.append("+ " + line.content)
            elif line.type == DiffDelete:
                b.append("- " + line.content)
            elif line.type == DiffModify:
                b.append("~ " + line.content.split("\x00")[0])
            else:
                b.append("  " + line.content)
    b.append("```")
    return "\n".join(b)


def _html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def FormatHTML(result: DiffResult, title: str = "Diff") -> str:
    """Format a diff as a standalone HTML document. Mirrors FormatHTML."""
    b: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{_html_escape(title)}</title>",
        "<style>",
        "body{font-family:monospace;margin:20px;background:#f5f5f5}",
        "pre{background:#fff;border:1px solid #ddd;padding:10px;overflow-x:auto}",
        ".add{background:#e6ffec;color:#1a7f37}",
        ".del{background:#ffebe9;color:#cf222e}",
        ".mod{background:#fff8c5;color:#9a6700}",
        ".hunk{background:#ddf4ff;color:#0969da;font-weight:bold}",
        "</style></head><body>",
        f"<h2>{_html_escape(title)}</h2><pre>",
    ]
    for h in result.hunks:
        b.append(
            f"<span class='hunk'>@@ -{h.old_start},{h.old_count} "
            f"+{h.new_start},{h.new_count} @@</span>"
        )
        for line in h.lines:
            content = _html_escape(line.content.split("\x00")[0])
            if line.type == DiffInsert:
                b.append(f"<span class='add'>+ {content}</span>")
            elif line.type == DiffDelete:
                b.append(f"<span class='del'>- {content}</span>")
            elif line.type == DiffModify:
                b.append(f"<span class='mod'>! {content}</span>")
            else:
                b.append(f"  {content}")
    b.append("</pre></body></html>")
    return "\n".join(b)


def FormatJSON(result: DiffResult) -> str:
    """Serialize a diff to JSON. Mirrors FormatJSON (struct field names)."""
    hunks = []
    for h in result.hunks:
        hunk: dict[str, object] = {
            "OldStart": h.old_start,
            "OldCount": h.old_count,
            "NewStart": h.new_start,
            "NewCount": h.new_count,
        }
        if h.context:
            hunk["Context"] = h.context
        lines = []
        for l in h.lines:
            entry: dict[str, object] = {"Type": str(l.type)}
            if l.line_num_old:
                entry["LineNumOld"] = l.line_num_old
            if l.line_num_new:
                entry["LineNumNew"] = l.line_num_new
            entry["Content"] = l.content
            lines.append(entry)
        hunk["Lines"] = lines
        hunks.append(hunk)
    stats = {
        "LinesAdded": result.stats.lines_added,
        "LinesRemoved": result.stats.lines_removed,
        "LinesChanged": result.stats.lines_changed,
        "TotalLines": result.stats.total_lines,
    }
    return json.dumps({"Hunks": hunks, "Stats": stats})


def FormatWithLineNumbers(
    result: DiffResult, context_lines: int = DefaultContextLines
) -> str:
    """Format a diff with old/new line numbers. Mirrors FormatWithLineNumbers."""
    _ = context_lines  # unused parameter (kept for API parity)
    b: list[str] = []
    for h in result.hunks:
        for line in h.lines:
            old_num = str(line.line_num_old) if line.line_num_old else " "
            new_num = str(line.line_num_new) if line.line_num_new else " "
            prefix = {"insert": "+", "delete": "-", "modify": "!", "equal": " "}[
                str(line.type)
            ]
            content = (
                line.content.split("\x00")[0]
                if line.type == DiffModify
                else line.content
            )
            b.append(f"{old_num:>6} {new_num:>6} {prefix} {content}")
    return "\n".join(b) + ("\n" if b else "")
