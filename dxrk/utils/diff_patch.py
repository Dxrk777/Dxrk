# SPDX-License-Identifier: MIT

"""Patch subsystem: creation, parsing, application, reversion, merge, and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dxrk.utils.diff_core import ComputeDiff as ComputeDiff
from dxrk.utils.diff_model import DefaultContextLines as DefaultContextLines
from dxrk.utils.diff_model import DiffDelete as DiffDelete
from dxrk.utils.diff_model import DiffEqual as DiffEqual
from dxrk.utils.diff_model import DiffError as DiffError
from dxrk.utils.diff_model import DiffHunk as DiffHunk
from dxrk.utils.diff_model import DiffInsert as DiffInsert
from dxrk.utils.diff_model import DiffLine as DiffLine
from dxrk.utils.diff_model import DiffModify as DiffModify
from dxrk.utils.diff_model import ErrContextMismatch as ErrContextMismatch
from dxrk.utils.diff_model import ErrFileNotFound as ErrFileNotFound
from dxrk.utils.diff_model import ErrPatchConflict as ErrPatchConflict
from dxrk.utils.diff_model import ErrPatchEmpty as ErrPatchEmpty
from dxrk.utils.diff_model import ErrPatchInvalid as ErrPatchInvalid


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
