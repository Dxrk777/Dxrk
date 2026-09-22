# SPDX-License-Identifier: MIT

"""Semantic diff: renames, moves, refactors, and filepath matching."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import IntEnum

from dxrk.utils.diff_core import ComputeDiff as ComputeDiff
from dxrk.utils.diff_files import FileDiff as FileDiff
from dxrk.utils.diff_model import DiffModify as DiffModify


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
