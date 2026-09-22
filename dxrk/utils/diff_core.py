# SPDX-License-Identifier: MIT

"""Diff core: line/word/char diffs over an LCS algorithm."""

from __future__ import annotations

from dxrk.utils.diff_model import DefaultContextLines as DefaultContextLines
from dxrk.utils.diff_model import DiffDelete as DiffDelete
from dxrk.utils.diff_model import DiffEqual as DiffEqual
from dxrk.utils.diff_model import DiffHunk as DiffHunk
from dxrk.utils.diff_model import DiffInsert as DiffInsert
from dxrk.utils.diff_model import DiffLine as DiffLine
from dxrk.utils.diff_model import DiffModify as DiffModify
from dxrk.utils.diff_model import DiffResult as DiffResult
from dxrk.utils.diff_model import DiffStats as DiffStats
from dxrk.utils.diff_model import DiffType as DiffType
from dxrk.utils.diff_model import _Op as _Op


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
