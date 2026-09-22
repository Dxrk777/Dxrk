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

from dxrk.utils.diff_core import ComputeCharDiff as ComputeCharDiff
from dxrk.utils.diff_core import ComputeDiff as ComputeDiff
from dxrk.utils.diff_core import ComputeWordDiff as ComputeWordDiff
from dxrk.utils.diff_core import _build_result as _build_result
from dxrk.utils.diff_core import _group_hunks as _group_hunks
from dxrk.utils.diff_core import _lcs_diff as _lcs_diff
from dxrk.utils.diff_core import _split_chars as _split_chars
from dxrk.utils.diff_core import _split_lines as _split_lines
from dxrk.utils.diff_core import _split_words as _split_words
from dxrk.utils.diff_files import CompareDirectories as CompareDirectories
from dxrk.utils.diff_files import CompareFiles as CompareFiles
from dxrk.utils.diff_files import CompareFilesWithOptions as CompareFilesWithOptions
from dxrk.utils.diff_files import DiffStatus as DiffStatus
from dxrk.utils.diff_files import DiffStatusAdded as DiffStatusAdded
from dxrk.utils.diff_files import DiffStatusModified as DiffStatusModified
from dxrk.utils.diff_files import DiffStatusRemoved as DiffStatusRemoved
from dxrk.utils.diff_files import DiffStatusUnchanged as DiffStatusUnchanged
from dxrk.utils.diff_files import FileDiff as FileDiff
from dxrk.utils.diff_files import SummarizeDirectory as SummarizeDirectory
from dxrk.utils.diff_files import _added_tree as _added_tree
from dxrk.utils.diff_files import _compare_dirs_recursive as _compare_dirs_recursive
from dxrk.utils.diff_files import _dir_entries as _dir_entries
from dxrk.utils.diff_files import _file_mode as _file_mode
from dxrk.utils.diff_files import _looks_binary as _looks_binary
from dxrk.utils.diff_files import _removed_tree as _removed_tree
from dxrk.utils.diff_files import _short_hash as _short_hash
from dxrk.utils.diff_files import _strip_whitespace as _strip_whitespace
from dxrk.utils.diff_format import ColorScheme as ColorScheme
from dxrk.utils.diff_format import FormatCompact as FormatCompact
from dxrk.utils.diff_format import FormatContext as FormatContext
from dxrk.utils.diff_format import FormatHTML as FormatHTML
from dxrk.utils.diff_format import FormatJSON as FormatJSON
from dxrk.utils.diff_format import FormatMarkdown as FormatMarkdown
from dxrk.utils.diff_format import FormatSideBySide as FormatSideBySide
from dxrk.utils.diff_format import FormatUnified as FormatUnified
from dxrk.utils.diff_format import FormatWithLineNumbers as FormatWithLineNumbers
from dxrk.utils.diff_format import SetColors as SetColors
from dxrk.utils.diff_format import _c as _c
from dxrk.utils.diff_format import _default_colors as _default_colors
from dxrk.utils.diff_format import _empty_colors as _empty_colors
from dxrk.utils.diff_format import _html_escape as _html_escape
from dxrk.utils.diff_model import DefaultContextLines as DefaultContextLines
from dxrk.utils.diff_model import DiffDelete as DiffDelete
from dxrk.utils.diff_model import DiffEqual as DiffEqual
from dxrk.utils.diff_model import DiffError as DiffError
from dxrk.utils.diff_model import DiffHunk as DiffHunk
from dxrk.utils.diff_model import DiffInsert as DiffInsert
from dxrk.utils.diff_model import DiffLine as DiffLine
from dxrk.utils.diff_model import DiffModify as DiffModify
from dxrk.utils.diff_model import DiffResult as DiffResult
from dxrk.utils.diff_model import DiffStats as DiffStats
from dxrk.utils.diff_model import DiffType as DiffType
from dxrk.utils.diff_model import ErrContextMismatch as ErrContextMismatch
from dxrk.utils.diff_model import ErrFileNotFound as ErrFileNotFound
from dxrk.utils.diff_model import ErrNotDirectory as ErrNotDirectory
from dxrk.utils.diff_model import ErrPatchConflict as ErrPatchConflict
from dxrk.utils.diff_model import ErrPatchEmpty as ErrPatchEmpty
from dxrk.utils.diff_model import ErrPatchInvalid as ErrPatchInvalid
from dxrk.utils.diff_model import _Op as _Op
from dxrk.utils.diff_patch import ApplyPatch as ApplyPatch
from dxrk.utils.diff_patch import ApplyPatchToFile as ApplyPatchToFile
from dxrk.utils.diff_patch import CreatePatch as CreatePatch
from dxrk.utils.diff_patch import FormatPatch as FormatPatch
from dxrk.utils.diff_patch import MergePatches as MergePatches
from dxrk.utils.diff_patch import ParsePatch as ParsePatch
from dxrk.utils.diff_patch import Patch as Patch
from dxrk.utils.diff_patch import PatchFile as PatchFile
from dxrk.utils.diff_patch import PatchLine as PatchLine
from dxrk.utils.diff_patch import PatchOffset as PatchOffset
from dxrk.utils.diff_patch import RevertPatch as RevertPatch
from dxrk.utils.diff_patch import RevertPatchToFile as RevertPatchToFile
from dxrk.utils.diff_patch import ValidatePatch as ValidatePatch
from dxrk.utils.diff_patch import _apply_patch_text as _apply_patch_text
from dxrk.utils.diff_patch import _parse_hunk_header as _parse_hunk_header
from dxrk.utils.diff_patch import _reverse_patch as _reverse_patch
from dxrk.utils.diff_patch import _strip_git_prefix as _strip_git_prefix
from dxrk.utils.diff_semantic import _BLOCK_START as _BLOCK_START
from dxrk.utils.diff_semantic import _COMMENT_RE as _COMMENT_RE
from dxrk.utils.diff_semantic import _FUNC_RE as _FUNC_RE
from dxrk.utils.diff_semantic import DetectSemanticChanges as DetectSemanticChanges
from dxrk.utils.diff_semantic import DetectSemanticDirDiff as DetectSemanticDirDiff
from dxrk.utils.diff_semantic import DetectSemanticFileDiff as DetectSemanticFileDiff
from dxrk.utils.diff_semantic import FormatSemanticChanges as FormatSemanticChanges
from dxrk.utils.diff_semantic import Match as Match
from dxrk.utils.diff_semantic import SemanticChange as SemanticChange
from dxrk.utils.diff_semantic import SemanticChangeAdd as SemanticChangeAdd
from dxrk.utils.diff_semantic import SemanticChangeModify as SemanticChangeModify
from dxrk.utils.diff_semantic import SemanticChangeMove as SemanticChangeMove
from dxrk.utils.diff_semantic import SemanticChangeRefactor as SemanticChangeRefactor
from dxrk.utils.diff_semantic import SemanticChangeRemove as SemanticChangeRemove
from dxrk.utils.diff_semantic import SemanticChangeRename as SemanticChangeRename
from dxrk.utils.diff_semantic import SemanticChangeType as SemanticChangeType
from dxrk.utils.diff_semantic import SemanticChangeUnknown as SemanticChangeUnknown
from dxrk.utils.diff_semantic import SemanticResult as SemanticResult
from dxrk.utils.diff_semantic import _block_symbol as _block_symbol
from dxrk.utils.diff_semantic import _extract_blocks as _extract_blocks
from dxrk.utils.diff_semantic import _extract_symbols as _extract_symbols
from dxrk.utils.diff_semantic import _filepath_match as _filepath_match
from dxrk.utils.diff_semantic import _is_move as _is_move
from dxrk.utils.diff_semantic import _is_noise as _is_noise
from dxrk.utils.diff_semantic import _is_refactor as _is_refactor
from dxrk.utils.diff_semantic import _is_rename as _is_rename
from dxrk.utils.diff_semantic import _match_chunk as _match_chunk
from dxrk.utils.diff_semantic import _name_parts as _name_parts
from dxrk.utils.diff_semantic import _strip_comments as _strip_comments
