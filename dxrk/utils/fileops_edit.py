# SPDX-License-Identifier: MIT
"""Search-and-replace file editing with indent preservation and regex support."""

from __future__ import annotations

import re as _re
from dataclasses import dataclass

from dxrk.utils.fileops_errors import FileopsError, ValidatePath
from dxrk.utils.fileops_write import WriteAtomic


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


def ApplyRegexEdits(content: str, edits: list[RegexEditOp]) -> tuple[str, int, FileopsError | None]:
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
