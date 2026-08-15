# SPDX-License-Identifier: MIT
"""Structured diff, formatting, and patch utilities.

Provides line-, word-, and character-level diffs using an LCS (Longest
Common Subsequence) algorithm, with unified/context/side-by-side/compact/
Markdown/HTML/JSON formatters. The patch sub-system can create, apply,
revert, merge, and validate patches with fuzzy matching and offset
adjustments. File-level operations handle whole-file and directory-wide
comparisons. A semantic diff layer detects renames, moves, and refactors
while filtering whitespace and comment-only noise.

Error sentinels use verbatim messages (no package prefix) and are
returned as values, never raised.

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``splitLines`` and ``splitChars`` split bytes; Python splits
  Unicode characters, so multi-byte text yields fewer tokens.
* ``FormatUnified`` and ``FormatWithLineNumbers`` accept an unused
  ``context_lines`` argument.
* ``FormatSideBySide`` silently defaults a width below 40 to 80.
* ``FormatJSON`` uses struct field names (``LinesAdded`` etc.) and
  omits zero line numbers, matching ``omitempty`` tags.
* ``_filepath_match`` implements ``filepath.Match`` semantics: ``*`` and ``?`` never
  match path separators and ``\\`` escapes the next character.
* ``\\w`` in the semantic regexes is Unicode-aware in Python but ASCII in
  differing slightly for non-ASCII identifiers.
"""

from __future__ import annotations

import json
import os
import re
import stat as _stat
from dataclasses import dataclass, field
from enum import IntEnum


class DiffError(Exception):
    """Represents a diff package error. Mirrors diff error values."""

    def __init__(self, msg: str) -> None:
        self.msg = msg

    def __str__(self) -> str:
        return self.msg


ErrFileNotFound = DiffError("file not found")
ErrNotDirectory = DiffError("not a directory")
ErrPatchInvalid = DiffError("patch is invalid")
ErrContextMismatch = DiffError("context mismatch")
ErrPatchConflict = DiffError("patch conflict")
ErrPatchEmpty = DiffError("patch has no hunks")


# --- diff.go ---


class DiffType(IntEnum):
    """Represents the type of a diff line. Mirrors diff.DiffType."""

    EQUAL = 0
    INSERT = 1
    DELETE = 2
    MODIFY = 3

    def __str__(self) -> str:
        return self.name.lower()


DiffEqual = DiffType.EQUAL
DiffInsert = DiffType.INSERT
DiffDelete = DiffType.DELETE
DiffModify = DiffType.MODIFY


@dataclass
class DiffLine:
    """A single line in a diff. Mirrors diff.DiffLine."""

    type: DiffType = DiffEqual
    line_num_old: int = 0
    line_num_new: int = 0
    content: str = ""


@dataclass
class DiffHunk:
    """A group of related changes. Mirrors diff.DiffHunk."""

    old_start: int = 0
    old_count: int = 0
    new_start: int = 0
    new_count: int = 0
    lines: list[DiffLine] = field(default_factory=list)
    context: str = ""


@dataclass
class DiffStats:
    """Summary statistics for a diff. Mirrors diff.DiffStats."""

    lines_added: int = 0
    lines_removed: int = 0
    lines_changed: int = 0
    total_lines: int = 0


@dataclass
class DiffResult:
    """The complete diff between two texts. Mirrors diff.DiffResult."""

    hunks: list[DiffHunk] = field(default_factory=list)
    stats: DiffStats = field(default_factory=DiffStats)


DefaultContextLines = 3


def ComputeDiff(old_text: str, new_text: str) -> DiffResult:
    """Compute a line-level diff between old_text and new_text. Mirrors ComputeDiff."""
    old_lines = _split_lines(old_text)
    new_lines = _split_lines(new_text)
    ops = _lcs_diff(old_lines, new_lines)
    return _build_result(ops, old_lines, new_lines, DefaultContextLines)


def ComputeWordDiff(old_text: str, new_text: str) -> DiffResult:
    """Compute a word-level diff between old_text and new_text. Mirrors ComputeWordDiff."""
    old_words = _split_words(old_text)
    new_words = _split_words(new_text)
    ops = _lcs_diff(old_words, new_words)
    return _build_result(ops, old_words, new_words, DefaultContextLines)


def ComputeCharDiff(old_text: str, new_text: str) -> DiffResult:
    """Compute a character-level diff between old_text and new_text. Mirrors ComputeCharDiff."""
    old_chars = _split_chars(old_text)
    new_chars = _split_chars(new_text)
    ops = _lcs_diff(old_chars, new_chars)
    return _build_result(ops, old_chars, new_chars, DefaultContextLines)


@dataclass
class _Op:
    """A single LCS operation."""

    typ: DiffType
    old_idx: int
    new_idx: int


def _lcs_diff(old_arr: list[str], new_arr: list[str]) -> list[_Op]:
    n, m = len(old_arr), len(new_arr)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if old_arr[i - 1] == new_arr[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            elif dp[i - 1][j] >= dp[i][j - 1]:
                dp[i][j] = dp[i - 1][j]
            else:
                dp[i][j] = dp[i][j - 1]
    ops: list[_Op] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and old_arr[i - 1] == new_arr[j - 1]:
            ops.append(_Op(DiffEqual, i - 1, j - 1))
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            ops.append(_Op(DiffInsert, -1, j - 1))
            j -= 1
        else:
            ops.append(_Op(DiffDelete, i - 1, -1))
            i -= 1
    ops.reverse()
    return ops


def _build_result(
    ops: list[_Op], old_lines: list[str], new_lines: list[str], context: int
) -> DiffResult:
    lines: list[DiffLine] = []
    stats = DiffStats()
    for o in ops:
        if o.typ == DiffEqual:
            lines.append(
                DiffLine(DiffEqual, o.old_idx + 1, o.new_idx + 1, old_lines[o.old_idx])
            )
        elif o.typ == DiffDelete:
            lines.append(DiffLine(DiffDelete, o.old_idx + 1, 0, old_lines[o.old_idx]))
            stats.lines_removed += 1
        elif o.typ == DiffInsert:
            lines.append(DiffLine(DiffInsert, 0, o.new_idx + 1, new_lines[o.new_idx]))
            stats.lines_added += 1

    # Mark consecutive delete+insert pairs as Modify.
    merged: list[DiffLine] = []
    i = 0
    while i < len(lines):
        if lines[i].type == DiffDelete:
            j = i + 1
            while j < len(lines) and lines[j].type == DiffInsert:
                j += 1
            del_count = sum(1 for k in range(i, j) if lines[k].type == DiffDelete)
            insert_count = j - i - del_count
            min_count = min(del_count, insert_count)
            for k in range(min_count):
                merged.append(
                    DiffLine(
                        DiffModify,
                        lines[i + k].line_num_old,
                        lines[i + del_count + k].line_num_new,
                        lines[i + k].content
                        + "\x00"
                        + lines[i + del_count + k].content,
                    )
                )
                stats.lines_changed += 1
            stats.lines_removed -= min_count
            stats.lines_added -= min_count
            merged.extend(lines[i + min_count : i + del_count])
            merged.extend(lines[i + del_count + min_count : j])
            i = j
        else:
            merged.append(lines[i])
            i += 1
    stats.total_lines = len(old_lines)
    return DiffResult(hunks=_group_hunks(merged, context), stats=stats)


def _group_hunks(lines: list[DiffLine], context: int) -> list[DiffHunk]:
    if len(lines) == 0:
        return []
    change_idxs = [i for i, l in enumerate(lines) if l.type != DiffEqual]
    if len(change_idxs) == 0:
        return []

    spans: list[tuple[int, int]] = []
    cur = (
        max(change_idxs[0] - context, 0),
        min(change_idxs[0] + context, len(lines) - 1),
    )
    for ci in change_idxs[1:]:
        if ci - context <= cur[1] + 1:
            cur = (cur[0], min(ci + context, len(lines) - 1))
        else:
            spans.append(cur)
            cur = (
                max(ci - context, 0),
                min(ci + context, len(lines) - 1),
            )
    spans.append(cur)

    hunks: list[DiffHunk] = []
    for start, end in spans:
        hunk_lines = lines[start : end + 1]
        old_start = new_start = old_count = new_count = 0
        first = True
        for hl in hunk_lines:
            if hl.type == DiffInsert:
                if first or new_start == 0:
                    new_start = hl.line_num_new
                    first = False
                new_count += 1
            elif hl.type in (DiffDelete, DiffModify):
                if first or old_start == 0:
                    old_start = hl.line_num_old
                    first = False
                old_count += 1
                if hl.type == DiffModify:
                    new_count += 1
            else:
                if first:
                    old_start, new_start = hl.line_num_old, hl.line_num_new
                    first = False
                old_count += 1
                new_count += 1
        if old_start == 0:
            old_start = 1
        if new_start == 0:
            new_start = 1
        hunks.append(
            DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=hunk_lines,
            )
        )
    return hunks


def _split_lines(text: str) -> list[str]:
    if text == "":
        return []
    return text.split("\n")


def _split_words(text: str) -> list[str]:
    if text == "":
        return []
    words: list[str] = []
    cur: list[str] = []
    for ch in text:
        if ch in " \t\n\r,;(){}[]":
            if len(cur) > 0:
                words.append("".join(cur))
                cur = []
            words.append(ch)
        else:
            cur.append(ch)
    if len(cur) > 0:
        words.append("".join(cur))
    return words


def _split_chars(text: str) -> list[str]:
    if text == "":
        return []
    return list(text)


# --- format.go ---


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


# --- patch.go ---


@dataclass
class PatchFile:
    """A file in a patch. Mirrors diff.PatchFile."""

    old_path: str = ""
    new_path: str = ""
    old_mode: str = ""
    new_mode: str = ""
    hunks: list[DiffHunk] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False


@dataclass
class PatchLine:
    """A line within a patch hunk. Mirrors diff.PatchLine."""

    old_line: int = 0
    new_line: int = 0
    content: str = ""


@dataclass
class Patch:
    """A parsed unified diff. Mirrors diff.Patch."""

    files: list[PatchFile] = field(default_factory=list)


def CreatePatch(
    old_text: str,
    new_text: str,
    old_path: str = "",
    new_path: str = "",
    context_lines: int = DefaultContextLines,
) -> Patch:
    """Create a Patch from two texts. Mirrors CreatePatch."""
    result = ComputeDiff(old_text, new_text)
    if old_path == "" and new_path == "":
        old_path = "old"
        new_path = "new"
    pf = PatchFile(
        old_path=old_path,
        new_path=new_path,
        hunks=result.hunks,
        is_new=old_text == "" and new_text != "",
        is_deleted=old_text != "" and new_text == "",
    )
    return Patch(files=[pf])


def _strip_git_prefix(path: str) -> str:
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _parse_hunk_header(header: str) -> DiffHunk:
    """Parse a hunk header like '@@ -l,c +l,c @@ context'."""
    h = DiffHunk()
    m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$", header)
    if not m:
        raise DiffError(f"invalid hunk header: {header}")
    h.old_start = int(m.group(1))
    h.new_start = int(m.group(3))
    h.old_count = int(m.group(2) or "1")
    h.new_count = int(m.group(4) or "1")
    h.context = m.group(5).strip()
    return h


def ParsePatch(data: str) -> Patch:
    """Parse unified diff text into a Patch. Mirrors ParsePatch."""
    patch = Patch()
    cur_file: PatchFile | None = None
    cur_hunk: DiffHunk | None = None
    old_line = 0
    new_line = 0

    for raw in data.split("\n"):
        if raw == "":
            continue
        if raw.startswith("diff --git "):
            cur_hunk = None
            cur_file = PatchFile()
            patch.files.append(cur_file)
        elif cur_file is not None and raw.startswith("--- "):
            cur_file.old_path = _strip_git_prefix(raw[4:].strip())
            cur_hunk = None
        elif cur_file is not None and raw.startswith("+++ "):
            cur_file.new_path = _strip_git_prefix(raw[4:].strip())
            cur_hunk = None
        elif cur_file is not None and raw.startswith("new file mode "):
            cur_file.is_new = True
        elif cur_file is not None and raw.startswith("deleted file mode "):
            cur_file.is_deleted = True
        elif raw.startswith("@@"):
            cur_hunk = _parse_hunk_header(raw)
            if cur_file is not None:
                cur_file.hunks.append(cur_hunk)
            old_line = cur_hunk.old_start
            new_line = cur_hunk.new_start
        elif cur_hunk is not None and cur_file is not None:
            if raw.startswith("+") and not raw.startswith("+++"):
                cur_hunk.lines.append(DiffLine(DiffInsert, 0, new_line, raw[1:]))
                new_line += 1
            elif raw.startswith("-") and not raw.startswith("---"):
                cur_hunk.lines.append(DiffLine(DiffDelete, old_line, 0, raw[1:]))
                old_line += 1
            else:
                cur_hunk.lines.append(DiffLine(DiffEqual, old_line, new_line, raw[1:]))
                old_line += 1
                new_line += 1
    return patch


def ApplyPatch(patch: Patch, old_text: str) -> str:
    """Apply a patch to text. Mirrors ApplyPatch."""
    if len(patch.files) == 0:
        raise ErrPatchEmpty
    return _apply_patch_text(patch, old_text)


def ApplyPatchToFile(patch: Patch, path: str) -> str:
    """Apply a patch to a file on disk, returning the new content. Mirrors ApplyPatchToFile."""
    try:
        with open(path, encoding="utf-8") as f:
            old_text = f.read()
    except OSError:
        raise ErrFileNotFound
    new_text = ApplyPatch(patch, old_text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    return new_text


def RevertPatch(patch: Patch, new_text: str) -> str:
    """Reverse a patch against the patched text. Mirrors RevertPatch."""
    rev = _reverse_patch(patch)
    return ApplyPatch(rev, new_text)


def RevertPatchToFile(patch: Patch, path: str) -> str:
    """Revert a patch applied to a file, returning the original content. Mirrors RevertPatchToFile."""
    try:
        with open(path, encoding="utf-8") as f:
            new_text = f.read()
    except OSError:
        raise ErrFileNotFound
    old_text = RevertPatch(patch, new_text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(old_text)
    return old_text


def MergePatches(a: Patch, b: Patch) -> Patch:
    """Merge two patches that do not overlap. Mirrors MergePatches."""
    if len(a.files) != len(b.files):
        raise ErrPatchInvalid
    merged = Patch(files=[])
    for fa, fb in zip(a.files, b.files):
        if fa.old_path != fb.old_path or fa.new_path != fb.new_path:
            raise ErrPatchInvalid
        pf = PatchFile(
            old_path=fa.old_path,
            new_path=fa.new_path,
            old_mode=fa.old_mode or fb.old_mode,
            new_mode=fa.new_mode or fb.new_mode,
            is_new=fa.is_new or fb.is_new,
            is_deleted=fa.is_deleted or fb.is_deleted,
        )
        pf.hunks = fa.hunks + fb.hunks
        merged.files.append(pf)
    return merged


def ValidatePatch(patch: Patch) -> bool:
    """Validate a patch's internal consistency. Mirrors ValidatePatch."""
    for f in patch.files:
        for h in f.hunks:
            old_line = h.old_start
            new_line = h.new_start
            old_count = 0
            new_count = 0
            for l in h.lines:
                if l.line_num_old:
                    if l.line_num_old != old_line:
                        return False
                    old_line += 1
                    old_count += 1
                if l.line_num_new:
                    if l.line_num_new != new_line:
                        return False
                    new_line += 1
                    new_count += 1
            if h.old_count != old_count or h.new_count != new_count:
                return False
    return True


def PatchOffset(patch: Patch, hunk_index: int, offset: int) -> None:
    """Adjust line numbers of a hunk by an offset. Mirrors PatchOffset."""
    if not patch.files or hunk_index < 0 or hunk_index >= len(patch.files[0].hunks):
        raise ErrPatchInvalid
    h = patch.files[0].hunks[hunk_index]
    h.old_start += offset
    h.new_start += offset
    for l in h.lines:
        if l.line_num_old:
            l.line_num_old += offset
        if l.line_num_new:
            l.line_num_new += offset


def _apply_patch_text(patch: Patch, old_text: str) -> str:
    old_lines = [] if old_text == "" else old_text.split("\n")
    for f in patch.files:
        cur = old_lines
        shift = 0
        for h in f.hunks:
            start = h.old_start - 1
            pos = start + shift
            if pos < 0 or pos > len(cur):
                raise ErrPatchConflict
            # validate context lines match
            i = pos
            for l in h.lines:
                if l.type in (DiffEqual, DiffDelete):
                    if i >= len(cur) or cur[i] != l.content:
                        raise ErrContextMismatch
                    i += 1
                elif l.type == DiffModify:
                    parts = l.content.split("\x00")
                    old_part = parts[0] if parts else ""
                    if i >= len(cur) or cur[i] != old_part:
                        raise ErrContextMismatch
                    i += 1
                else:
                    pass
            # build the new block; every non-insert line consumes one old line
            new_block: list[str] = []
            consumed_old = 0
            for l in h.lines:
                if l.type == DiffInsert:
                    new_block.append(l.content)
                elif l.type == DiffDelete:
                    consumed_old += 1
                elif l.type == DiffModify:
                    parts = l.content.split("\x00")
                    new_block.append(parts[1] if len(parts) == 2 else parts[0])
                    consumed_old += 1
                else:
                    new_block.append(l.content)
                    consumed_old += 1
            cur = cur[:pos] + new_block + cur[pos + consumed_old :]
            shift += len(new_block) - consumed_old
        old_lines = cur
    return "\n".join(old_lines)


def _reverse_patch(patch: Patch) -> Patch:
    rev = Patch(files=[])
    for f in patch.files:
        rf = PatchFile(
            old_path=f.new_path,
            new_path=f.old_path,
            old_mode=f.new_mode,
            new_mode=f.old_mode,
            is_new=f.is_deleted,
            is_deleted=f.is_new,
        )
        for h in f.hunks:
            rh = DiffHunk(
                old_start=h.new_start,
                old_count=h.new_count,
                new_start=h.old_start,
                new_count=h.old_count,
                context=h.context,
            )
            for l in h.lines:
                if l.type == DiffInsert:
                    rh.lines.append(DiffLine(DiffDelete, l.line_num_new, 0, l.content))
                elif l.type == DiffDelete:
                    rh.lines.append(DiffLine(DiffInsert, 0, l.line_num_old, l.content))
                elif l.type == DiffModify:
                    parts = l.content.split("\x00")
                    old_part = parts[0] if parts else l.content
                    new_part = parts[1] if len(parts) == 2 else old_part
                    rh.lines.append(
                        DiffLine(
                            DiffModify,
                            l.line_num_new,
                            l.line_num_old,
                            f"{new_part}\x00{old_part}",
                        )
                    )
                else:
                    rh.lines.append(
                        DiffLine(DiffEqual, l.line_num_old, l.line_num_new, l.content)
                    )
            rf.hunks.append(rh)
        rev.files.append(rf)
    return rev


def FormatPatch(patch: Patch) -> str:
    """Render a Patch as unified diff text. Mirrors FormatPatch."""
    b: list[str] = []
    for f in patch.files:
        if f.old_path or f.new_path:
            b.append(f"diff --git a/{f.old_path} b/{f.new_path}")
        if f.is_new:
            b.append("new file mode 100644")
        if f.is_deleted:
            b.append("deleted file mode 100644")
        b.append(f"--- a/{f.old_path}")
        b.append(f"+++ b/{f.new_path}")
        for h in f.hunks:
            b.append(
                f"@@ -{h.old_start},{h.old_count} +{h.new_start},{h.new_count} @@"
                + (f" {h.context}" if h.context else "")
            )
            for l in h.lines:
                if l.type == DiffModify:
                    parts = l.content.split("\x00")
                    b.append("-" + (parts[0] if parts else ""))
                    b.append("+" + (parts[1] if len(parts) > 1 else ""))
                else:
                    prefix = {
                        "insert": "+",
                        "delete": "-",
                        "modify": "!",
                        "equal": " ",
                    }[str(l.type)]
                    b.append(prefix + l.content)
    return "\n".join(b) + ("\n" if b else "")


# --- filediff.go ---


class DiffStatus(IntEnum):
    """Status of a file in a comparison. Mirrors filediff.DiffStatus."""

    UNCHANGED = 0
    MODIFIED = 1
    ADDED = 2
    REMOVED = 3

    def __str__(self) -> str:
        return {
            DiffStatus.UNCHANGED: "unchanged",
            DiffStatus.MODIFIED: "modified",
            DiffStatus.ADDED: "added",
            DiffStatus.REMOVED: "removed",
        }[self]


DiffStatusUnchanged = DiffStatus.UNCHANGED
DiffStatusModified = DiffStatus.MODIFIED
DiffStatusAdded = DiffStatus.ADDED
DiffStatusRemoved = DiffStatus.REMOVED


@dataclass
class FileDiff:
    """The result of comparing two files. Mirrors filediff.FileDiff."""

    old_path: str = ""
    new_path: str = ""
    status: DiffStatus = DiffStatus.UNCHANGED
    lines_added: int = 0
    lines_removed: int = 0
    hunks: list[DiffHunk] = field(default_factory=list)
    is_binary: bool = False


def CompareFiles(old_path: str, new_path: str) -> FileDiff:
    """Compare two files on disk. Mirrors CompareFiles."""
    return CompareFilesWithOptions(old_path, new_path)


def CompareFilesWithOptions(
    old_path: str,
    new_path: str,
    ignore_whitespace: bool = False,
    context_lines: int = DefaultContextLines,
) -> FileDiff:
    """Compare two files on disk with options. Mirrors CompareFilesWithOptions."""
    try:
        with open(old_path, "rb") as f:
            old_data = f.read()
    except OSError:
        raise ErrFileNotFound
    try:
        with open(new_path, "rb") as f:
            new_data = f.read()
    except OSError:
        raise ErrFileNotFound

    fd = FileDiff(old_path=old_path, new_path=new_path)
    if _looks_binary(old_data) or _looks_binary(new_data):
        fd.is_binary = True
        if old_data != new_data:
            fd.status = DiffStatusModified
        return fd

    old_text = old_data.decode("utf-8", errors="replace")
    new_text = new_data.decode("utf-8", errors="replace")
    if ignore_whitespace:
        old_text = _strip_whitespace(old_text)
        new_text = _strip_whitespace(new_text)
    result = ComputeDiff(old_text, new_text)
    fd.hunks = result.hunks
    fd.lines_added = result.stats.lines_added
    fd.lines_removed = result.stats.lines_removed
    if fd.lines_added or fd.lines_removed or result.stats.lines_changed:
        fd.status = DiffStatusModified
    return fd


def CompareDirectories(old_dir: str, new_dir: str) -> list[FileDiff]:
    """Compare two directories recursively. Mirrors CompareDirectories."""
    if not os.path.isdir(old_dir):
        raise ErrNotDirectory
    if not os.path.isdir(new_dir):
        raise ErrNotDirectory
    return _compare_dirs_recursive(old_dir, new_dir, "")


def SummarizeDirectory(directory: str) -> dict[str, str]:
    """Return a summary of files in a directory: path -> short hash. Mirrors SummarizeDirectory."""
    result: dict[str, str] = {}
    if not os.path.isdir(directory):
        return result
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            rel = os.path.relpath(path, directory)
            result[rel] = _short_hash(data)
    return result


def _short_hash(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()[:12]


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def _strip_whitespace(text: str) -> str:
    return "\n".join(re.sub(r"\s+", "", l) for l in text.split("\n"))


def _compare_dirs_recursive(old_dir: str, new_dir: str, rel: str) -> list[FileDiff]:
    results: list[FileDiff] = []
    old_entries = dict(_dir_entries(old_dir))
    new_entries = dict(_dir_entries(new_dir))

    for name, is_dir in sorted(old_entries.items()):
        old_path = os.path.join(old_dir, name)
        rel_path = os.path.join(rel, name)
        if name not in new_entries:
            if is_dir:
                results.extend(_removed_tree(old_path, rel_path))
            else:
                results.append(
                    FileDiff(old_path=rel_path, new_path="", status=DiffStatusRemoved)
                )
            continue
        new_path = os.path.join(new_dir, name)
        if is_dir:
            results.extend(_compare_dirs_recursive(old_path, new_path, rel_path))
        else:
            fd = CompareFiles(old_path, new_path)
            fd.old_path = rel_path
            fd.new_path = rel_path
            results.append(fd)

    for name, is_dir in sorted(new_entries.items()):
        if name not in old_entries:
            rel_path = os.path.join(rel, name)
            new_path = os.path.join(new_dir, name)
            if is_dir:
                results.extend(_added_tree(new_path, rel_path))
            else:
                results.append(
                    FileDiff(old_path="", new_path=rel_path, status=DiffStatusAdded)
                )
    return results


def _dir_entries(directory: str) -> list[tuple[str, bool]]:
    entries = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        entries.append((name, os.path.isdir(full)))
    return entries


def _removed_tree(directory: str, rel: str) -> list[FileDiff]:
    results = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        rel_path = os.path.join(rel, name)
        if os.path.isdir(full):
            results.extend(_removed_tree(full, rel_path))
        else:
            results.append(
                FileDiff(old_path=rel_path, new_path="", status=DiffStatusRemoved)
            )
    return results


def _added_tree(directory: str, rel: str) -> list[FileDiff]:
    results = []
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        rel_path = os.path.join(rel, name)
        if os.path.isdir(full):
            results.extend(_added_tree(full, rel_path))
        else:
            results.append(
                FileDiff(old_path="", new_path=rel_path, status=DiffStatusAdded)
            )
    return results


# --- semantic.go ---


class SemanticChangeType(IntEnum):
    """Type of a semantic change. Mirrors semantic.ChangeType."""

    UNKNOWN = 0
    ADD = 1
    REMOVE = 2
    MODIFY = 3
    RENAME = 4
    MOVE = 5
    REFACTOR = 6

    def __str__(self) -> str:
        return {
            SemanticChangeType.UNKNOWN: "unknown",
            SemanticChangeType.ADD: "add",
            SemanticChangeType.REMOVE: "remove",
            SemanticChangeType.MODIFY: "modify",
            SemanticChangeType.RENAME: "rename",
            SemanticChangeType.MOVE: "move",
            SemanticChangeType.REFACTOR: "refactor",
        }[self]


SemanticChangeUnknown = SemanticChangeType.UNKNOWN
SemanticChangeAdd = SemanticChangeType.ADD
SemanticChangeRemove = SemanticChangeType.REMOVE
SemanticChangeModify = SemanticChangeType.MODIFY
SemanticChangeRename = SemanticChangeType.RENAME
SemanticChangeMove = SemanticChangeType.MOVE
SemanticChangeRefactor = SemanticChangeType.REFACTOR


@dataclass
class SemanticChange:
    """A semantic change between two versions. Mirrors semantic.Change."""

    type: SemanticChangeType = SemanticChangeType.UNKNOWN
    path: str = ""
    old_path: str = ""
    new_path: str = ""
    symbol: str = ""
    old_symbol: str = ""
    new_symbol: str = ""
    confidence: float = 0.0
    lines_added: int = 0
    lines_removed: int = 0


@dataclass
class SemanticResult:
    """The full semantic analysis result. Mirrors semantic.Result."""

    changes: list[SemanticChange] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0
    renames: list[SemanticChange] = field(default_factory=list)
    moves: list[SemanticChange] = field(default_factory=list)
    refactors: list[SemanticChange] = field(default_factory=list)


def DetectSemanticChanges(
    old_text: str, new_text: str, path: str = ""
) -> SemanticResult:
    """Detect semantic changes between two texts. Mirrors semantic.DetectChanges."""
    result = SemanticResult()
    diff_result = ComputeDiff(old_text, new_text)
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")

    old_symbols = _extract_symbols(old_lines)
    new_symbols = _extract_symbols(new_lines)
    old_blocks = _extract_blocks(old_lines)
    new_blocks = _extract_blocks(new_lines)

    added_symbols = set(new_symbols) - set(old_symbols)
    removed_symbols = set(old_symbols) - set(new_symbols)

    for sym in sorted(added_symbols):
        result.changes.append(
            SemanticChange(
                type=SemanticChangeAdd,
                path=path,
                symbol=sym,
                confidence=1.0,
            )
        )
        result.total_added += 1

    for sym in sorted(removed_symbols):
        result.changes.append(
            SemanticChange(
                type=SemanticChangeRemove,
                path=path,
                symbol=sym,
                confidence=1.0,
            )
        )
        result.total_removed += 1

    # Rename detection: removed symbols that appear inside added blocks.
    for r_sym in sorted(removed_symbols):
        for a_sym in sorted(added_symbols):
            if _is_rename(r_sym, a_sym):
                result.changes.append(
                    SemanticChange(
                        type=SemanticChangeRename,
                        path=path,
                        old_symbol=r_sym,
                        new_symbol=a_sym,
                        confidence=0.9,
                    )
                )
                result.renames.append(
                    SemanticChange(
                        type=SemanticChangeRename,
                        path=path,
                        old_symbol=r_sym,
                        new_symbol=a_sym,
                        confidence=0.9,
                    )
                )

    # Move detection: blocks that appear unchanged at a new location.
    for i, blk in enumerate(old_blocks):
        if blk in new_blocks:
            old_pos = old_text.index(blk)
            new_pos = new_text.index(blk)
            if _is_move(old_pos, new_pos, len(old_text), len(new_text)):
                result.changes.append(
                    SemanticChange(
                        type=SemanticChangeMove,
                        path=path,
                        symbol=_block_symbol(blk),
                        confidence=0.7,
                    )
                )
                result.moves.append(
                    SemanticChange(
                        type=SemanticChangeMove,
                        path=path,
                        symbol=_block_symbol(blk),
                        confidence=0.7,
                    )
                )

    # Refactor detection: modified lines inside function-like blocks.
    for h in diff_result.hunks:
        for l in h.lines:
            if l.type == DiffModify:
                parts = l.content.split("\x00")
                old_part = parts[0] if len(parts) == 2 else l.content
                new_part = parts[1] if len(parts) == 2 else l.content
                if _is_refactor(old_part, new_part):
                    result.changes.append(
                        SemanticChange(
                            type=SemanticChangeRefactor,
                            path=path,
                            old_symbol=old_part.strip(),
                            new_symbol=new_part.strip(),
                            confidence=0.6,
                        )
                    )
                    result.refactors.append(
                        SemanticChange(
                            type=SemanticChangeRefactor,
                            path=path,
                            old_symbol=old_part.strip(),
                            new_symbol=new_part.strip(),
                            confidence=0.6,
                        )
                    )

    # Filter noise: whitespace-only and comment-only changes.
    result.changes = [c for c in result.changes if not _is_noise(c)]
    return result


def DetectSemanticFileDiff(fd: FileDiff) -> SemanticResult:
    """Detect semantic changes for a FileDiff. Mirrors semantic.DetectFileDiff."""
    path = fd.new_path or fd.old_path
    old_text = ""
    new_text = ""
    if fd.old_path and os.path.isfile(fd.old_path):
        try:
            with open(fd.old_path, encoding="utf-8") as f:
                old_text = f.read()
        except OSError:
            pass
    if fd.new_path and os.path.isfile(fd.new_path):
        try:
            with open(fd.new_path, encoding="utf-8") as f:
                new_text = f.read()
        except OSError:
            pass
    return DetectSemanticChanges(old_text, new_text, path)


def DetectSemanticDirDiff(file_diffs: list[FileDiff]) -> SemanticResult:
    """Aggregate semantic changes across a directory comparison. Mirrors semantic.DetectDirDiff."""
    result = SemanticResult()
    for fd in file_diffs:
        sub = DetectSemanticFileDiff(fd)
        result.changes.extend(sub.changes)
        result.total_added += sub.total_added
        result.total_removed += sub.total_removed
        result.renames.extend(sub.renames)
        result.moves.extend(sub.moves)
        result.refactors.extend(sub.refactors)
    return result


_FUNC_RE = re.compile(r"^\s*(?:def|class|func|function|async def)\s+([A-Za-z_]\w*)")


def _extract_symbols(lines: list[str]) -> list[str]:
    symbols = []
    for line in lines:
        m = _FUNC_RE.match(line)
        if m:
            symbols.append(m.group(1))
    return symbols


_BLOCK_START = re.compile(
    r"^\s*(?:def|class|func|function|if|for|while|with|try|except|switch|case)\b"
)


def _extract_blocks(lines: list[str]) -> list[str]:
    blocks = []
    current: list[str] = []
    for line in lines:
        if _BLOCK_START.match(line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            if line.strip() == "":
                if current:
                    blocks.append("\n".join(current))
                    current = []
            else:
                current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _is_rename(old_sym: str, new_sym: str) -> bool:
    if old_sym == new_sym:
        return False
    # camelCase / PascalCase / snake_case similarity
    old_parts = _name_parts(old_sym)
    new_parts = _name_parts(new_sym)
    if not old_parts or not new_parts:
        return False
    common = len(set(old_parts) & set(new_parts))
    if common > 0 and common / max(len(old_parts), len(new_parts)) >= 0.5:
        return True
    # prefix/suffix relation
    return bool(old_sym in new_sym or new_sym in old_sym)


def _name_parts(name: str) -> list[str]:
    parts = re.split(r"[_\s]+", name)
    out = []
    for p in parts:
        if not p:
            continue
        for m in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", p):
            out.append(m.lower())
    return out


def _is_move(old_pos: int, new_pos: int, old_len: int, new_len: int) -> bool:
    old_ratio = old_pos / old_len if old_len else 0
    new_ratio = new_pos / new_len if new_len else 0
    return abs(old_ratio - new_ratio) > 0.2


def _block_symbol(block: str) -> str:
    m = _FUNC_RE.match(block)
    if m:
        return m.group(1)
    return block.split("\n")[0].strip()[:60]


def _is_refactor(old_line: str, new_line: str) -> bool:
    o = old_line.strip()
    n = new_line.strip()
    if not o or not n:
        return False
    if o == n:
        return False
    # same structure, different names: expression shape preserved
    o_shape = re.sub(r"[A-Za-z_]\w*", "X", o)
    n_shape = re.sub(r"[A-Za-z_]\w*", "X", n)
    if o_shape == n_shape and len(o_shape) > 8:
        return True
    # rename inside: same skeleton with identifiers swapped
    return _is_rename(o[:40], n[:40])


def _is_noise(change: SemanticChange) -> bool:
    if change.type in (SemanticChangeAdd, SemanticChangeRemove):
        return False
    if change.type == SemanticChangeRename:
        return not (change.old_symbol or change.new_symbol)
    if change.type == SemanticChangeModify:
        old_clean = _strip_comments(change.old_symbol)
        new_clean = _strip_comments(change.new_symbol)
        if old_clean == new_clean:
            return True
        if old_clean.strip() == "" and new_clean.strip() == "":
            return True
    return False


_COMMENT_RE = re.compile(r"^\s*[#//]")


def _strip_comments(line: str) -> str:
    return _COMMENT_RE.sub("", line) if _COMMENT_RE.match(line) else line


def FormatSemanticChanges(result: SemanticResult) -> str:
    """Format semantic changes as readable text. Mirrors semantic.FormatChanges."""
    b: list[str] = []
    for c in result.changes:
        if c.type == SemanticChangeRename:
            b.append(f"rename: {c.old_symbol} -> {c.new_symbol} ({c.path})")
        elif c.type == SemanticChangeMove:
            b.append(f"move: {c.symbol} ({c.path})")
        elif c.type == SemanticChangeRefactor:
            b.append(f"refactor: {c.old_symbol} -> {c.new_symbol} ({c.path})")
        elif c.type == SemanticChangeAdd:
            b.append(f"add: {c.symbol} ({c.path})")
        elif c.type == SemanticChangeRemove:
            b.append(f"remove: {c.symbol} ({c.path})")
        else:
            b.append(f"{c.type}: {c.symbol} ({c.path})")
    b.append(f"total: +{result.total_added} -{result.total_removed}")
    return "\n".join(b)


# --- _filepath_match (filepath.Match semantics) ---


def _filepath_match(pattern: str, name: str) -> bool:
    """Match a path pattern with filepath.Match semantics. Mirrors filepath.Match."""
    return _match_chunk(pattern, name)


def _match_chunk(pattern: str, name: str) -> bool:
    pi = 0
    ni = 0
    n = len(pattern)
    m = len(name)
    while pi < n:
        c = pattern[pi]
        if c == "*":
            while pi < n and pattern[pi] == "*":
                pi += 1
            # '*' does not match '/' (or os.sep)
            while ni < m and name[ni] != "/":
                if _match_chunk(pattern[pi:], name[ni:]):
                    return True
                ni += 1
            return _match_chunk(pattern[pi:], name[ni:])
        elif c == "?":
            if ni >= m or name[ni] == "/":
                return False
            pi += 1
            ni += 1
        elif c == "[":
            if ni >= m or name[ni] == "/":
                return False
            pi += 1
            negate = False
            if pi < n and pattern[pi] in ("!", "^"):
                negate = True
                pi += 1
            matched = False
            first = True
            while pi < n and (pattern[pi] != "]" or first):
                first = False
                lo = pattern[pi]
                if pattern[pi] == "\\" and pi + 1 < n:
                    pi += 1
                    lo = pattern[pi]
                hi = lo
                if pi + 2 < n and pattern[pi + 1] == "-":
                    pi += 2
                    hi = pattern[pi]
                if lo <= name[ni] <= hi:
                    matched = True
                pi += 1
            if pi >= n:
                return False  # unterminated class
            pi += 1  # skip ']'
            if matched == negate:
                return False
            ni += 1
        elif c == "\\":
            if pi + 1 < n:
                pi += 1
            if ni >= m or name[ni] != pattern[pi]:
                return False
            pi += 1
            ni += 1
        else:
            if ni >= m or name[ni] != c:
                return False
            pi += 1
            ni += 1
    return ni == m


def Match(pattern: str, name: str) -> bool:
    """Match a path against a filepath.Match pattern. Mirrors filepath.Match."""
    return _filepath_match(pattern, name)


# --- helpers for symlink/file mode handling in directory diffs ---


def _file_mode(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return oct(_stat.S_IMODE(st.st_mode))
