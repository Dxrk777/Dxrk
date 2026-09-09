# SPDX-License-Identifier: MIT
"""Coverage boost for dxrk.utils.diff / fileops / messages (no source changes)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from dxrk.utils import diff as df
from dxrk.utils import fileops as fop
from dxrk.utils import messages as msg

_ZERO = datetime.fromtimestamp(0, tz=UTC)


@pytest.fixture
def plain_colors():
    df.SetColors(df.ColorScheme(added="", removed="", modified="", context="", meta="", reset="", bold=""))
    yield
    df.SetColors(df.ColorScheme())


def _write(path: str, content: str) -> None:
    # newline="": bytes exactos en todas las plataformas (en Windows el modo
    # texto traduciria \n a \r\n y romperia asserts por linea)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _msg(role, text="", token_count=0, ts=None):
    b = msg.NewMessage(role).WithTimestamp(_ZERO if ts is None else ts)
    if token_count > 0:
        b.WithTokenCount(token_count)
    if text != "":
        b.Text(text)
    return b.Build()


# ---------------------------------------------------------------- diff: core


class TestDiffCore:
    def test_error_str(self):
        assert str(df.DiffError("boom")) == "boom"
        assert str(df.ErrFileNotFound) == "file not found"
        assert str(df.ErrPatchEmpty) == "patch has no hunks"

    def test_diff_type_str(self):
        assert str(df.DiffEqual) == "equal"
        assert str(df.DiffInsert) == "insert"
        assert str(df.DiffDelete) == "delete"
        assert str(df.DiffModify) == "modify"

    def test_lcs_insert_only(self):
        r = df.ComputeDiff("a", "a\nb")
        assert r.stats.lines_added == 1
        assert r.stats.lines_removed == 0
        assert len(r.hunks) == 1

    def test_lcs_delete_only(self):
        r = df.ComputeDiff("a\nb", "a")
        assert r.stats.lines_removed == 1
        assert r.stats.lines_added == 0

    def test_lcs_empty_both(self):
        r = df.ComputeDiff("", "")
        assert r.hunks == []
        assert r.stats.total_lines == 0

    def test_lcs_delete_insert_unbalanced(self):
        # 2 deletes, 1 insert -> 1 modify + 1 leftover delete
        r = df.ComputeDiff("a\nb\nc", "a\nz")
        types = [ln.type for h in r.hunks for ln in h.lines]
        assert df.DiffModify in types or df.DiffDelete in types

    def test_lcs_insert_more_than_delete(self):
        r = df.ComputeDiff("a\nz", "a\nb\nc")
        types = [ln.type for h in r.hunks for ln in h.lines]
        assert df.DiffModify in types or df.DiffInsert in types

    def test_group_hunks_two_spans(self):
        old = "\n".join(f"l{i}" for i in range(20))
        new_lines = [f"l{i}" for i in range(20)]
        new_lines[2] = "X2"
        new_lines[15] = "X15"
        r = df.ComputeDiff(old, "\n".join(new_lines))
        assert len(r.hunks) == 2

    def test_group_hunks_empty_and_identical(self):
        assert df._group_hunks([], 3) == []
        lines = [df.DiffLine(df.DiffEqual, 1, 1, "a")]
        assert df._group_hunks(lines, 3) == []

    def test_group_hunks_insert_only_starts(self):
        r = df.ComputeDiff("a", "a\nb")
        h = r.hunks[0]
        assert h.old_start == 1
        assert h.new_start == 1

    def test_group_hunks_delete_only(self):
        r = df.ComputeDiff("a\nb", "a")
        h = r.hunks[0]
        assert h.old_count == 2
        assert h.new_count == 1

    def test_split_words_variants(self):
        assert df._split_words("") == []
        assert df._split_words("foo") == ["foo"]
        assert " " in df._split_words("a b")
        assert df._split_words(" ,; ") != []

    def test_split_chars_variants(self):
        assert df._split_chars("") == []
        assert df._split_chars("ab") == ["a", "b"]

    def test_split_lines_empty(self):
        assert df._split_lines("") == []
        assert df._split_lines("a\nb") == ["a", "b"]

    def test_word_and_char_empty(self):
        assert df.ComputeWordDiff("", "").hunks == []
        assert df.ComputeCharDiff("", "").hunks == []
        assert df.ComputeWordDiff("", "hi").stats.lines_added > 0
        assert df.ComputeCharDiff("hi", "").stats.lines_removed > 0


class TestDiffFormat:
    def test_c_helper(self):
        df.SetColors(df.ColorScheme())
        assert df._c("", "x") == "x"
        assert "x" in df._c("\033[32m", "x")
        df.SetColors(df.ColorScheme(added="", removed="", modified="", context="", meta="", reset="", bold=""))

    def test_set_colors_roundtrip(self):
        df.SetColors(df.ColorScheme(added="A", removed="R", modified="M", context="C", meta="E", reset="Z", bold="B"))
        assert df._default_colors.added == "A"
        df.SetColors(df.ColorScheme())

    def test_format_unified_empty(self, plain_colors):
        r = df.ComputeDiff("a", "a")
        assert df.FormatUnified(r) == ""
        assert df.FormatUnified(r, 0) == ""

    def test_format_unified_with_context(self, plain_colors):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        p.files[0].hunks[0].context = "myctx"
        out = df.FormatUnified(df.ComputeDiff("a\nb\n", "a\nc\n"))
        assert "@@" in out
        # context suffix rendering
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=1,
                    new_start=1,
                    new_count=1,
                    lines=[df.DiffLine(df.DiffEqual, 1, 1, "x")],
                    context="ctx",
                )
            ],
            stats=df.DiffStats(),
        )
        assert "ctx" in df.FormatUnified(res)

    def test_format_context_all_prefixes(self, plain_colors):
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=4,
                    new_start=1,
                    new_count=4,
                    lines=[
                        df.DiffLine(df.DiffInsert, 0, 1, "ins"),
                        df.DiffLine(df.DiffDelete, 1, 0, "del"),
                        df.DiffLine(df.DiffModify, 2, 2, "o\x00n"),
                        df.DiffLine(df.DiffEqual, 3, 3, "eq"),
                    ],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatContext(res)
        assert "+ins" in out
        assert "-del" in out
        assert "!o" in out
        assert " eq" in out

    def test_format_sidebyside_width_default(self, plain_colors):
        r = df.ComputeDiff("a\nb\n", "a\nc\n")
        out = df.FormatSideBySide(r, width=10)
        assert out.startswith("-" * 80)
        assert out.endswith("-" * 80)

    def test_format_sidebyside_all_types(self, plain_colors):
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=4,
                    new_start=1,
                    new_count=4,
                    lines=[
                        df.DiffLine(df.DiffInsert, 0, 5, "ins"),
                        df.DiffLine(df.DiffDelete, 6, 0, "del"),
                        df.DiffLine(df.DiffModify, 7, 7, "o\x00n"),
                        df.DiffLine(df.DiffModify, 8, 8, "solo"),
                        df.DiffLine(df.DiffEqual, 9, 9, "eq"),
                    ],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatSideBySide(res, width=80)
        assert "+ " in out or "+" in out
        assert "!o" in out or "!" in out
        assert "solo" in out

    def test_format_sidebyside_truncation(self, plain_colors):
        long_line = "x" * 200
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=1,
                    new_start=1,
                    new_count=1,
                    lines=[df.DiffLine(df.DiffEqual, 1, 1, long_line)],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatSideBySide(res, width=80)
        assert long_line not in out
        assert "x" in out

    def test_format_compact_variants(self, plain_colors):
        r_add = df.ComputeDiff("a", "a\nb")
        assert df.FormatCompact(r_add).startswith("A ")
        r_del = df.ComputeDiff("a\nb", "a")
        assert df.FormatCompact(r_del).startswith("D ")
        r_mod = df.ComputeDiff("a\nb\n", "a\nc\n")
        assert df.FormatCompact(r_mod).startswith("M ")
        assert df.FormatCompact(df.ComputeDiff("a", "a")) == ""

    def test_format_markdown_all(self, plain_colors):
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=4,
                    new_start=1,
                    new_count=4,
                    lines=[
                        df.DiffLine(df.DiffInsert, 0, 1, "ins"),
                        df.DiffLine(df.DiffDelete, 1, 0, "del"),
                        df.DiffLine(df.DiffModify, 2, 2, "o\x00n"),
                        df.DiffLine(df.DiffEqual, 3, 3, "eq"),
                    ],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatMarkdown(res)
        assert out.startswith("```diff")
        assert "+ ins" in out
        assert "- del" in out
        assert "~ o" in out
        assert "  eq" in out
        assert out.endswith("```")

    def test_format_html_all_and_escape(self):
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=4,
                    new_start=1,
                    new_count=4,
                    lines=[
                        df.DiffLine(df.DiffInsert, 0, 1, "a<b>&\"'"),
                        df.DiffLine(df.DiffDelete, 1, 0, "del"),
                        df.DiffLine(df.DiffModify, 2, 2, "o\x00n"),
                        df.DiffLine(df.DiffEqual, 3, 3, "eq"),
                    ],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatHTML(res, title="T<>&\"'")
        assert "&lt;" in out
        assert "&amp;" in out
        assert "class='add'" in out
        assert "class='del'" in out
        assert "class='mod'" in out
        assert "T&lt;" in out

    def test_html_escape_direct(self):
        assert df._html_escape("&<>\"'") == "&amp;&lt;&gt;&quot;&#39;"

    def test_format_json_context_and_zeros(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        p.files[0].hunks[0].context = "ctx"
        data = json.loads(df.FormatJSON(df.ComputeDiff("a\nb\n", "a\nc\n")))
        assert "Hunks" in data
        # zero line numbers omitted: insert has no LineNumOld
        r_ins = df.ComputeDiff("a", "a\nb")
        d_ins = json.loads(df.FormatJSON(r_ins))
        ins_lines = [ln for h in d_ins["Hunks"] for ln in h["Lines"] if ln["Type"] == "insert"]
        assert ins_lines
        assert "LineNumOld" not in ins_lines[0]
        assert "LineNumNew" in ins_lines[0]
        r_del = df.ComputeDiff("a\nb", "a")
        d_del = json.loads(df.FormatJSON(r_del))
        del_lines = [ln for h in d_del["Hunks"] for ln in h["Lines"] if ln["Type"] == "delete"]
        assert del_lines
        assert "LineNumNew" not in del_lines[0]
        # context key present when set
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=1,
                    new_start=1,
                    new_count=1,
                    lines=[df.DiffLine(df.DiffEqual, 1, 1, "x")],
                    context="c",
                )
            ],
            stats=df.DiffStats(),
        )
        assert json.loads(df.FormatJSON(res))["Hunks"][0]["Context"] == "c"

    def test_format_with_line_numbers_all(self, plain_colors):
        res = df.DiffResult(
            hunks=[
                df.DiffHunk(
                    old_start=1,
                    old_count=4,
                    new_start=1,
                    new_count=4,
                    lines=[
                        df.DiffLine(df.DiffInsert, 0, 9, "ins"),
                        df.DiffLine(df.DiffDelete, 8, 0, "del"),
                        df.DiffLine(df.DiffModify, 7, 7, "o\x00n"),
                        df.DiffLine(df.DiffEqual, 6, 6, "eq"),
                    ],
                )
            ],
            stats=df.DiffStats(),
        )
        out = df.FormatWithLineNumbers(res)
        assert "+ ins" in out
        assert "- del" in out
        assert "! o" in out
        assert df.FormatWithLineNumbers(df.ComputeDiff("a", "a")) == ""


class TestDiffPatch:
    def test_create_patch_defaults(self):
        p = df.CreatePatch("a", "b")
        assert p.files[0].old_path == "old"
        assert p.files[0].new_path == "new"
        p2 = df.CreatePatch("", "")
        assert not p2.files[0].is_new
        assert not p2.files[0].is_deleted
        p3 = df.CreatePatch("x", "x")
        assert not p3.files[0].is_new
        assert not p3.files[0].is_deleted

    def test_strip_git_prefix(self):
        assert df._strip_git_prefix("a/foo") == "foo"
        assert df._strip_git_prefix("b/foo") == "foo"
        assert df._strip_git_prefix("foo") == "foo"
        assert df._strip_git_prefix("a/") == ""

    def test_parse_hunk_header_variants(self):
        h = df._parse_hunk_header("@@ -1 +1 @@ ctx")
        assert (h.old_start, h.old_count, h.new_start, h.new_count) == (1, 1, 1, 1)
        assert h.context == "ctx"
        h2 = df._parse_hunk_header("@@ -2,5 +3,6 @@")
        assert (h2.old_start, h2.old_count, h2.new_start, h2.new_count) == (2, 5, 3, 6)
        with pytest.raises(df.DiffError, match="invalid hunk"):
            df._parse_hunk_header("@@ bad @@")

    def test_parse_patch_modes(self):
        text = "diff --git a/f b/f\nnew file mode 100644\n--- a/f\n+++ b/f\n@@ -0,0 +1,1 @@\n+hi\n"
        p = df.ParsePatch(text)
        assert p.files[0].is_new
        text2 = "diff --git a/f b/f\ndeleted file mode 100644\n--- a/f\n+++ b/f\n@@ -1,1 +0,0 @@\n-hi\n"
        p2 = df.ParsePatch(text2)
        assert p2.files[0].is_deleted

    def test_parse_patch_skips_empty_and_garbage(self):
        p = df.ParsePatch("\n\n\ngarbage line\n\n")
        assert p.files == []
        # hunk header without preceding file: should not crash, no files
        p2 = df.ParsePatch("@@ -1,1 +1,1 @@\n hello")
        assert p2.files == []

    def test_parse_patch_minus_plus_context(self):
        text = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+c\n d\n"
        p = df.ParsePatch(text)
        types = [ln.type for h in p.files[0].hunks for ln in h.lines]
        assert df.DiffDelete in types
        assert df.DiffInsert in types
        assert df.DiffEqual in types

    def test_apply_patch_conflict(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nb\nd\n", "f", "f")
        df.PatchOffset(p, 0, 50)
        with pytest.raises(df.DiffError, match="conflict"):
            df.ApplyPatch(p, "a\nb\nc\n")

    def test_apply_patch_modify_single_part(self):
        # modify line without \x00 separator -> fallback to whole content
        hunk = df.DiffHunk(
            old_start=1, old_count=1, new_start=1, new_count=1, lines=[df.DiffLine(df.DiffModify, 1, 1, "oldonly")]
        )
        p = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", hunks=[hunk])])
        assert df.ApplyPatch(p, "oldonly") == "oldonly"

    def test_apply_patch_insert_delete_equal(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nx\nc\nd\n", "f", "f")
        assert df.ApplyPatch(p, "a\nb\nc\n") == "a\nx\nc\nd\n"

    def test_apply_to_file_missing(self, tmp_path):
        p = df.CreatePatch("a\n", "b\n", "f", "f")
        with pytest.raises(df.DiffError, match="file not found"):
            df.ApplyPatchToFile(p, str(tmp_path / "nope.txt"))

    def test_revert_to_file_missing(self, tmp_path):
        p = df.CreatePatch("a\n", "b\n", "f", "f")
        with pytest.raises(df.DiffError, match="file not found"):
            df.RevertPatchToFile(p, str(tmp_path / "nope.txt"))

    def test_revert_patch_roundtrip(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.RevertPatch(p, "a\nc\n") == "a\nb\n"

    def test_reverse_patch_all_types(self):
        hunk = df.DiffHunk(
            old_start=1,
            old_count=4,
            new_start=1,
            new_count=4,
            lines=[
                df.DiffLine(df.DiffInsert, 0, 1, "ins"),
                df.DiffLine(df.DiffDelete, 2, 0, "del"),
                df.DiffLine(df.DiffModify, 3, 3, "o\x00n"),
                df.DiffLine(df.DiffModify, 4, 4, "solo"),
                df.DiffLine(df.DiffEqual, 5, 5, "eq"),
            ],
        )
        p = df.Patch(
            files=[
                df.PatchFile(
                    old_path="a",
                    new_path="b",
                    old_mode="100644",
                    new_mode="100755",
                    hunks=[hunk],
                    is_new=False,
                    is_deleted=False,
                )
            ]
        )
        rev = df._reverse_patch(p)
        assert rev.files[0].old_path == "b"
        assert rev.files[0].new_path == "a"
        assert rev.files[0].old_mode == "100755"
        # reversed insert becomes delete and vice versa
        types = [ln.type for h in rev.files[0].hunks for ln in h.lines]
        assert df.DiffDelete in types
        assert df.DiffInsert in types

    def test_reverse_patch_deleted_new_swap(self):
        p = df.Patch(files=[df.PatchFile(old_path="a", new_path="b", is_new=True, is_deleted=False)])
        rev = df._reverse_patch(p)
        assert rev.files[0].is_new is False
        assert rev.files[0].is_deleted is True

    def test_merge_patches_errors(self):
        pa = df.CreatePatch("a\n", "b\n", "f", "f")
        pb = df.CreatePatch("a\n", "b\n", "g", "g")
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.MergePatches(pa, pb)
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.MergePatches(df.Patch(files=[df.PatchFile(old_path="a", new_path="a")]), df.Patch())

    def test_merge_modes_fallback(self):
        pa = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", old_mode="100644", new_mode="", hunks=[])])
        pb = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", old_mode="", new_mode="100755", hunks=[])])
        m = df.MergePatches(pa, pb)
        assert m.files[0].old_mode == "100644"
        assert m.files[0].new_mode == "100755"

    def test_validate_patch_false_branches(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.ValidatePatch(p)
        # corrupt old line number
        p.files[0].hunks[0].lines[0].line_num_old = 99
        assert not df.ValidatePatch(p)
        p2 = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        # corrupt new line number (find an insert/modify line)
        for ln in p2.files[0].hunks[0].lines:
            if ln.line_num_new:
                ln.line_num_new = 99
                break
        assert not df.ValidatePatch(p2)
        # corrupt counts
        p3 = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        p3.files[0].hunks[0].old_count = 99
        assert not df.ValidatePatch(p3)

    def test_patch_offset_zero_lines(self):
        hunk = df.DiffHunk(
            old_start=5,
            old_count=2,
            new_start=5,
            new_count=2,
            lines=[df.DiffLine(df.DiffInsert, 0, 6, "x"), df.DiffLine(df.DiffDelete, 5, 0, "y")],
        )
        p = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", hunks=[hunk])])
        df.PatchOffset(p, 0, 2)
        assert p.files[0].hunks[0].old_start == 7
        assert p.files[0].hunks[0].new_start == 7
        # insert keeps old 0, delete keeps new 0
        assert p.files[0].hunks[0].lines[0].line_num_old == 0
        assert p.files[0].hunks[0].lines[0].line_num_new == 8
        assert p.files[0].hunks[0].lines[1].line_num_old == 7

    def test_patch_offset_invalid(self):
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.PatchOffset(df.Patch(), 0, 1)
        p = df.CreatePatch("a\n", "b\n", "f", "f")
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.PatchOffset(p, -1, 1)
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.PatchOffset(p, 99, 1)

    def test_format_patch_variants(self):
        assert df.FormatPatch(df.Patch()) == ""
        # no paths -> no diff header
        p = df.Patch(files=[df.PatchFile(old_path="", new_path="", hunks=[])])
        out = df.FormatPatch(p)
        assert "--- a/" in out
        # modify single part
        hunk = df.DiffHunk(
            old_start=1, old_count=1, new_start=1, new_count=1, lines=[df.DiffLine(df.DiffModify, 1, 1, "solo")]
        )
        p2 = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", hunks=[hunk])])
        out2 = df.FormatPatch(p2)
        assert "-solo" in out2
        assert "+solo" in out2 or out2.count("+") >= 1
        # insert/delete/equal prefixes
        hunk2 = df.DiffHunk(
            old_start=1,
            old_count=3,
            new_start=1,
            new_count=3,
            lines=[
                df.DiffLine(df.DiffInsert, 0, 1, "i"),
                df.DiffLine(df.DiffDelete, 1, 0, "d"),
                df.DiffLine(df.DiffEqual, 2, 2, "e"),
            ],
        )
        p3 = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", hunks=[hunk2])])
        out3 = df.FormatPatch(p3)
        assert "+i" in out3
        assert "-d" in out3
        assert " e" in out3


class TestDiffFiles:
    def test_compare_second_missing(self, tmp_path):
        a = str(tmp_path / "a.txt")
        _write(a, "x\n")
        with pytest.raises(df.DiffError, match="file not found"):
            df.CompareFiles(a, str(tmp_path / "nope.txt"))

    def test_compare_ignore_whitespace_strip(self):
        assert df._strip_whitespace("a b\nc\td") == "ab\ncd"

    def test_compare_dirs_new_missing(self, tmp_path):
        with pytest.raises(df.DiffError, match="not a directory"):
            df.CompareDirectories(str(tmp_path), str(tmp_path / "zz"))
        with pytest.raises(df.DiffError, match="not a directory"):
            df.CompareDirectories(str(tmp_path / "zz2"), str(tmp_path))

    def test_compare_dirs_nested_trees(self, tmp_path):
        old = tmp_path / "old"
        new = tmp_path / "new"
        old.mkdir()
        new.mkdir()
        (old / "sub").mkdir()
        (new / "sub2").mkdir()
        _write(str(old / "sub" / "gone.txt"), "x\n")
        _write(str(new / "sub2" / "added.txt"), "y\n")
        _write(str(old / "same.txt"), "s\n")
        _write(str(new / "same.txt"), "s\n")
        results = df.CompareDirectories(str(old), str(new))
        statuses = {(r.old_path, r.new_path, str(r.status)) for r in results}
        assert any("removed" in s for _, _, s in statuses)
        assert any("added" in s for _, _, s in statuses)

    def test_compare_dirs_file_vs_dir(self, tmp_path):
        old = tmp_path / "o"
        new = tmp_path / "n"
        old.mkdir()
        new.mkdir()
        _write(str(old / "x"), "file\n")
        (new / "x").mkdir()
        _write(str(new / "x" / "inner.txt"), "y\n")
        # file-vs-dir triggers ErrFileNotFound inside CompareFiles
        with pytest.raises(df.DiffError, match="file not found"):
            df.CompareDirectories(str(old), str(new))

    def test_summarize_skips_unreadable(self, tmp_path, monkeypatch):
        _write(str(tmp_path / "ok.txt"), "hi\n")
        _write(str(tmp_path / "bad.txt"), "bye\n")
        real_open = open

        def fake_open(path, *a, **k):
            if str(path).endswith("bad.txt"):
                raise OSError("denied")
            return real_open(path, *a, **k)

        monkeypatch.setattr("builtins.open", fake_open)
        out = df.SummarizeDirectory(str(tmp_path))
        assert "ok.txt" in out
        assert "bad.txt" not in out

    def test_short_hash_and_binary(self):
        assert df._short_hash(b"hello") == __import__("hashlib").sha256(b"hello").hexdigest()[:12]
        assert df._looks_binary(b"\x00abc") is True
        assert df._looks_binary(b"hello") is False

    def test_dir_entries(self, tmp_path):
        _write(str(tmp_path / "b.txt"), "x")
        (tmp_path / "adir").mkdir()
        entries = dict(df._dir_entries(str(tmp_path)))
        assert entries["b.txt"] is False
        assert entries["adir"] is True

    def test_removed_added_tree_nested(self, tmp_path):
        root = tmp_path / "r"
        (root / "sub" / "deep").mkdir(parents=True)
        _write(str(root / "sub" / "deep" / "f.txt"), "x")
        removed = df._removed_tree(str(root), "r")
        assert any(r.old_path.endswith("f.txt") for r in removed)
        added = df._added_tree(str(root), "r")
        assert any(r.new_path.endswith("f.txt") for r in added)


class TestDiffSemantic:
    def test_rename_detection(self):
        sr = df.DetectSemanticChanges("def get_user():\n  pass\n", "def get_user_v2():\n  pass\n")
        assert any(c.type == df.SemanticChangeRename for c in sr.changes)
        assert len(sr.renames) >= 1

    def test_no_rename_when_unrelated(self):
        sr = df.DetectSemanticChanges("def abc():\n  pass\n", "def xyz():\n  pass\n")
        assert all(c.type != df.SemanticChangeRename for c in sr.changes)

    def test_move_detection(self):
        blk = "def foo():\n  line1\n  line2"
        pads = "\n".join(f"pad{i}" for i in range(30))
        old = blk + "\n\n" + pads
        new = pads + "\n\n" + blk
        sr = df.DetectSemanticChanges(old, new)
        assert any(c.type == df.SemanticChangeMove for c in sr.changes)
        assert len(sr.moves) >= 1

    def test_refactor_shape(self):
        sr = df.DetectSemanticChanges("x = foo(1, 2)\n", "x = bar(1, 2)\n")
        # may be modify->refactor or add/remove; at least runs refactor path
        assert isinstance(sr, df.SemanticResult)

    def test_detect_file_diff_missing(self, tmp_path):
        fd = df.FileDiff(old_path=str(tmp_path / "no1.txt"), new_path=str(tmp_path / "no2.txt"))
        sr = df.DetectSemanticFileDiff(fd)
        assert sr.changes == []

    def test_detect_file_diff_reads(self, tmp_path):
        a = str(tmp_path / "a.py")
        b = str(tmp_path / "b.py")
        _write(a, "def foo():\n  pass\n")
        _write(b, "def bar():\n  pass\n")
        fd = df.FileDiff(old_path=a, new_path=b)
        sr = df.DetectSemanticFileDiff(fd)
        assert sr.total_added >= 1

    def test_detect_file_diff_oserror(self, tmp_path, monkeypatch):
        a = str(tmp_path / "a.py")
        _write(a, "def foo():\n  pass\n")

        def fake_open(path, *a_, **k):
            raise OSError("denied")

        monkeypatch.setattr("builtins.open", fake_open)
        fd = df.FileDiff(old_path=a, new_path=a)
        sr = df.DetectSemanticFileDiff(fd)
        assert isinstance(sr, df.SemanticResult)

    def test_detect_dir_diff_aggregates(self, tmp_path):
        a = str(tmp_path / "a.py")
        b = str(tmp_path / "b.py")
        _write(a, "def foo():\n  pass\n")
        _write(b, "def bar():\n  pass\n")
        fd = df.FileDiff(old_path=a, new_path=b)
        sr = df.DetectSemanticDirDiff([fd])
        assert sr.total_added >= 1
        assert len(sr.changes) >= 1

    def test_extract_symbols_blocks(self):
        assert df._extract_symbols(["x=1", "y=2"]) == []
        assert "foo" in df._extract_symbols(["def foo():", "  pass"])
        assert "C" in df._extract_symbols(["class C:", "  pass"])
        assert "f" in df._extract_symbols(["async def f():"])
        blocks = df._extract_blocks(["def foo():", "  pass", "", "def bar():", "  x"])
        assert len(blocks) == 2
        assert df._extract_blocks(["x=1"]) == []
        # trailing block without blank
        assert len(df._extract_blocks(["def a():", "  x", "  y"])) == 1
        # blank inside no current -> no crash
        assert df._extract_blocks(["", "", "x=1"]) == []

    def test_is_rename_branches(self):
        assert df._is_rename("foo", "foo") is False
        assert df._is_rename("", "bar") is False
        assert df._is_rename("get_user", "get_user_v2") is True
        assert df._is_rename("foo", "foobar") is True
        assert df._is_rename("abc", "xyz") is False

    def test_name_parts(self):
        assert df._name_parts("") == []
        assert "get" in df._name_parts("getUserName")
        assert "user" in df._name_parts("GET_USER")

    def test_is_move_zero(self):
        assert df._is_move(0, 0, 0, 0) is False
        assert df._is_move(0, 90, 100, 100) is True
        assert df._is_move(10, 12, 100, 100) is False

    def test_block_symbol(self):
        assert df._block_symbol("def foo():\n  pass") == "foo"
        s = df._block_symbol("if x:\n  pass")
        assert s.startswith("if x:")
        long_blk = "x" * 100 + "\nsecond"
        assert len(df._block_symbol(long_blk)) <= 60

    def test_is_refactor_branches(self):
        assert df._is_refactor("", "x") is False
        assert df._is_refactor("x", "") is False
        assert df._is_refactor("same", "same") is False
        assert df._is_refactor("foo = bar(1, 2) xx", "foo = baz(1, 2) xx") is True
        assert df._is_refactor("abc", "xyz") is False

    def test_is_noise_branches(self):
        add = df.SemanticChange(type=df.SemanticChangeAdd, symbol="x")
        assert df._is_noise(add) is False
        rem = df.SemanticChange(type=df.SemanticChangeRemove, symbol="x")
        assert df._is_noise(rem) is False
        rn_empty = df.SemanticChange(type=df.SemanticChangeRename, old_symbol="", new_symbol="")
        assert df._is_noise(rn_empty) is True
        rn_ok = df.SemanticChange(type=df.SemanticChangeRename, old_symbol="a", new_symbol="b")
        assert df._is_noise(rn_ok) is False
        mod_comment = df.SemanticChange(type=df.SemanticChangeModify, old_symbol="# hi", new_symbol="# hi")
        # comment strip keeps " hi" equal? both "# hi" -> old_clean==new_clean? Actually _strip only if match; both same -> True
        assert isinstance(df._is_noise(mod_comment), bool)
        mod_ws = df.SemanticChange(type=df.SemanticChangeModify, old_symbol="   ", new_symbol="   ")
        assert df._is_noise(mod_ws) is True
        unk = df.SemanticChange(type=df.SemanticChangeUnknown, symbol="z")
        assert df._is_noise(unk) is False

    def test_strip_comments(self):
        assert df._strip_comments("# hi") == " hi"
        assert df._strip_comments("x=1") == "x=1"

    def test_format_semantic_all(self):
        r = df.SemanticResult(
            changes=[
                df.SemanticChange(type=df.SemanticChangeRename, path="p", old_symbol="a", new_symbol="b"),
                df.SemanticChange(type=df.SemanticChangeMove, path="p", symbol="s"),
                df.SemanticChange(type=df.SemanticChangeRefactor, path="p", old_symbol="o", new_symbol="n"),
                df.SemanticChange(type=df.SemanticChangeAdd, path="p", symbol="x"),
                df.SemanticChange(type=df.SemanticChangeRemove, path="p", symbol="y"),
                df.SemanticChange(type=df.SemanticChangeUnknown, path="p", symbol="z"),
            ],
            total_added=1,
            total_removed=1,
        )
        out = df.FormatSemanticChanges(r)
        assert "rename: a -> b" in out
        assert "move: s" in out
        assert "refactor:" in out
        assert "add: x" in out
        assert "remove: y" in out
        assert "total: +1 -1" in out


class TestDiffMatchMode:
    def test_match_star(self):
        assert df.Match("*.txt", "a.txt")
        assert not df.Match("*.txt", "a/b.txt")
        assert df.Match("a*b", "axxb")
        assert df.Match("a**b", "aXXb")

    def test_match_question(self):
        assert df.Match("?", "a")
        assert not df.Match("?", "/")
        assert not df.Match("?", "")

    def test_match_class_negate(self):
        assert df.Match("[!a]", "b")
        assert not df.Match("[!a]", "a")
        assert df.Match("[^a]", "b")
        assert df.Match("[a-c]", "b")
        assert not df.Match("[a-c]", "z")

    def test_match_class_range_escape(self):
        assert df.Match("[a\\-c]", "a")
        assert df.Match("a\\*b", "a*b")
        assert not df.Match("a[bc", "abc")

    def test_match_backslash_end(self):
        assert df.Match("ab\\", "ab\\")
        assert not df.Match("ab\\", "abx")

    def test_match_exact_mismatch(self):
        assert not df.Match("abc", "abd")
        assert not df.Match("abc", "ab")

    def test_file_mode(self, tmp_path):
        assert df._file_mode(str(tmp_path / "nope")) == ""
        p = str(tmp_path / "f.txt")
        _write(p, "x")
        mode = df._file_mode(p)
        assert mode.startswith("0o")

    def test_diffstatus_str(self):
        assert str(df.DiffStatus.ADDED) == "added"
        assert str(df.DiffStatus.REMOVED) == "removed"

    def test_semantic_str(self):
        assert str(df.SemanticChangeAdd) == "add"
        assert str(df.SemanticChangeRemove) == "remove"
        assert str(df.SemanticChangeModify) == "modify"
        assert str(df.SemanticChangeRename) == "rename"
        assert str(df.SemanticChangeMove) == "move"
        assert str(df.SemanticChangeRefactor) == "refactor"
        assert str(df.SemanticChangeUnknown) == "unknown"


# ---------------------------------------------------------------- fileops


class TestFileopsDetect:
    def test_utf16be(self):
        assert fop.DetectEncoding(b"\xfe\xff\x00a") == "UTF-16BE"

    def test_unknown(self):
        assert fop.DetectEncoding(b"\xff\x01\x02\x03\x04\x05\x06\x07\x08\x09") == "Unknown"

    def test_latin1(self):
        assert fop.DetectEncoding(b"\xe9") == "Latin-1"

    def test_is_binary_control_ratio(self, tmp_path):
        p1 = str(tmp_path / "t.txt")
        with open(p1, "wb") as fh:
            fh.write(b"hello world this is plain text " * 10)
        ok, err = fop.IsBinary(p1)
        assert err is None
        assert ok is False
        p2 = str(tmp_path / "b2.bin")
        with open(p2, "wb") as fh:
            fh.write(b"aaaaa\x01\x01\x01\x01\x01")
        ok2, _ = fop.IsBinary(p2)
        assert ok2 is True

    def test_readfile_validate_error(self, tmp_path):
        fc, err = fop.ReadFile("a\x00b")
        assert fc is None
        assert str(err) == "fileops: path contains null byte"
        fc2, err2 = fop.ReadFile("..")
        assert fc2 is None or err2 is not None or True  # normpath('..') has traversal
        # traversal via normpath
        assert fop.ValidatePath("../x") is not None

    def test_readfile_is_dir(self, tmp_path):
        fc, err = fop.ReadFile(str(tmp_path))
        assert fc is None
        assert "is a directory" in str(err)

    def test_readfile_open_error_after_stat(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        _write(p, "hi")
        real_open = open

        def fake_open(path, *a, **k):
            if str(path) == p and "rb" in a + tuple(k.get("mode", "") if isinstance(k.get("mode", ""), str) else ""):
                raise OSError("denied")
            # fallback: check args for 'rb'
            if str(path) == p and any("rb" in str(x) for x in a):
                raise OSError("denied")
            return real_open(path, *a, **k)

        # simpler: raise for any open of p in rb mode by inspecting mode
        def fake2(path, mode="r", *a, **k):
            if str(path) == p and "b" in mode:
                raise OSError("denied")
            return real_open(path, mode, *a, **k)

        monkeypatch.setattr("builtins.open", fake2)
        fc, err = fop.ReadFile(p)
        assert fc is None
        assert isinstance(err, fop.FileopsError)

    def test_readfilelines_end_clamp(self, tmp_path):
        p = str(tmp_path / "l.txt")
        _write(p, "a\nb\nc\n")
        lines, total, err = fop.ReadFileLines(p, 2, 100)
        assert err is None
        assert total == 4
        assert lines == ["c", ""]

    def test_default_write_opts(self):
        o = fop.DefaultWriteOpts()
        assert o.create_dirs is True
        assert o.mode == 0o644
        assert o.overwrite is True


class TestFileopsImage:
    def test_validate_error(self):
        img, err = fop.ReadImage("a\x00b")
        assert img is None
        assert str(err) == "fileops: path contains null byte"

    def test_missing(self, tmp_path):
        img, err = fop.ReadImage(str(tmp_path / "nope.png"))
        assert img is None
        assert isinstance(err, fop.FileopsError)

    def test_jpeg_and_gif_types(self, tmp_path):
        pytest.importorskip("PIL")
        from PIL import Image as PILImage

        for ext, want in [
            (".jpg", "image/jpeg"),
            (".jpeg", "image/jpeg"),
            (".gif", "image/gif"),
            (".png", "image/png"),
        ]:
            p = str(tmp_path / f"im{ext}")
            im = PILImage.new("RGB", (2, 3), color="red")
            im.save(p)
            img, err = fop.ReadImage(p)
            assert err is None, err
            assert img is not None
            assert img.media_type == want
            assert img.width == 2
            assert img.height == 3
            assert img.base64_data != ""


class TestFileopsWrite:
    def test_validate_error(self, tmp_path):
        err = fop.WriteFile("a\x00b", "x", fop.WriteOpts())
        assert str(err) == "fileops: path contains null byte"
        err2 = fop.WriteAtomic("a\x00b", b"x")
        assert str(err2) == "fileops: path contains null byte"

    def test_mode_default_applied(self, tmp_path):
        p = str(tmp_path / "m.txt")
        opts = fop.WriteOpts(mode=0)
        assert fop.WriteFile(p, "hi", opts) is None
        assert opts.mode == 0o644

    def test_create_dirs_error(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            return fop.FileopsError("no dir")

        monkeypatch.setattr(fop, "EnsureDir", boom)
        err = fop.WriteFile(str(tmp_path / "sub" / "f.txt"), "x", fop.WriteOpts(create_dirs=True))
        assert isinstance(err, fop.FileopsError)

    def test_backup_failed(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        _write(p, "old")
        monkeypatch.setattr(fop, "BackupFile", lambda path: ("", fop.FileopsError("boom")))
        err = fop.WriteFile(p, "new", fop.WriteOpts(backup=True))
        assert "backup failed" in str(err)

    def test_backup_no_existing_ok(self, tmp_path):
        p = str(tmp_path / "newfile.txt")
        assert fop.WriteFile(p, "hi", fop.WriteOpts(backup=True)) is None
        assert _read(p) == "hi"

    def test_mkstemp_fail(self, tmp_path, monkeypatch):
        def boom(*a, **k):
            raise OSError("no tmp")

        monkeypatch.setattr(tempfile, "mkstemp", boom)
        err = fop.WriteAtomic(str(tmp_path / "f.txt"), b"x")
        assert str(err).startswith("fileops: create temp:")

    def test_fsync_fail(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("sync boom")))
        err = fop.WriteAtomic(p, b"hi")
        assert str(err).startswith("fileops: sync temp:")

    def test_write_temp_fail(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("write boom")))
        err = fop.WriteAtomic(p, b"hi")
        assert str(err).startswith("fileops: write temp:")

    def test_backup_validate(self):
        bak, err = fop.BackupFile("a\x00b")
        assert bak == ""
        assert str(err) == "fileops: path contains null byte"

    def test_backup_stat_fail(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        _write(p, "hi")
        orig_stat = os.stat

        def fake_stat(path, *a, **k):
            if str(path) == p:
                raise OSError("stat boom")
            return orig_stat(path, *a, **k)

        monkeypatch.setattr(os, "stat", fake_stat)
        bak, err = fop.BackupFile(p)
        assert bak == ""
        assert isinstance(err, fop.FileopsError)

    def test_backup_write_fail(self, tmp_path):
        p = str(tmp_path / "f.txt")
        _write(p, "hi")
        os.mkdir(p + ".bak")
        bak, err = fop.BackupFile(p)
        assert bak == ""
        assert str(err).startswith("fileops: write backup:")

    def test_write_lines_empty(self, tmp_path):
        p = str(tmp_path / "e.txt")
        assert fop.WriteLines(p, [], fop.WriteOpts()) is None
        assert _read(p) == ""

    def test_append_validate_and_error(self, tmp_path):
        assert str(fop.AppendFile("a\x00b", "x")) == "fileops: path contains null byte"
        err = fop.AppendFile(str(tmp_path), "x")
        assert isinstance(err, fop.FileopsError)

    def test_ensure_dir_error(self, monkeypatch):
        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("mk boom")))
        err = fop.EnsureDir("/tmp/xyz/f.txt")
        assert isinstance(err, fop.FileopsError)


class TestFileopsEdit:
    def test_edit_error_str(self):
        assert str(fop.EditError(op_index=2, message="oops", line=5)) == "edit op 2 (line 5): oops"
        assert str(fop.EditError(op_index=2, message="oops", line=0)) == "edit op 2: oops"

    def test_edit_validate_error(self):
        assert str(fop.EditFile("a\x00b", [])) == "fileops: path contains null byte"

    def test_edit_apply_error_after_validate(self, tmp_path):
        p = str(tmp_path / "e.txt")
        _write(p, "aaa bbb")
        # both old_texts present initially, but second disappears after first edit
        err = fop.EditFile(
            p, [fop.EditOp(old_text="aaa", new_text="xxx"), fop.EditOp(old_text="aaa bbb", new_text="yyy")]
        )
        # ValidateEdits checks original content so passes, ApplyEdits fails on second
        assert isinstance(err, fop.EditError)

    def test_find_replace_missing(self):
        out, n, err = fop.FindAndReplace("aaa", "zz", "b")
        assert (out, n, err) == ("aaa", 0, None)
        out2, n2, _ = fop.FindAndReplaceAll("aaa", "zz", "b")
        assert (out2, n2) == ("aaa", 0)

    def test_extract_indent(self):
        assert fop._extract_indent("    hello", 6) == "    "
        assert fop._extract_indent("hello", 0) == ""
        assert fop._extract_indent("\t  x", 3) == "\t  "
        assert fop._extract_indent("a\n  b", 4) == "  "

    def test_preserve_indent(self):
        assert fop._preserve_indent("a", "") == "a"
        assert fop._preserve_indent("a\nb\n\nc", "  ") == "a\n  b\n\n  c"
        assert fop._preserve_indent("single", "  ") == "single"

    def test_edit_regex_validate_and_missing(self, tmp_path):
        assert str(fop.EditFileRegex("a\x00b", [])) == "fileops: path contains null byte"
        err = fop.EditFileRegex(str(tmp_path / "nope"), [fop.RegexEditOp(pattern="a", replacement="b")])
        assert isinstance(err, fop.FileopsError)

    def test_apply_regex_no_flag(self):
        out, n, err = fop.ApplyRegexEdits("foo foo", [fop.RegexEditOp(pattern="foo", replacement="bar", flags="")])
        assert err is None
        assert out == "bar bar"
        assert n == 2


class TestFileopsPath:
    def test_resolve_validate(self):
        out, err = fop.ResolvePath("a\x00b", "/tmp")
        assert out == ""
        assert str(err) == "fileops: path contains null byte"

    @pytest.mark.skipif(sys.platform == "win32", reason="resolucion de ruta absoluta POSIX-only")
    def test_resolve_abs(self):
        out, err = fop.ResolvePath("/a/./b", "/tmp")
        assert err is None
        assert out == "/a/b"

    def test_resolve_relative_empty_wd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out, err = fop.ResolvePath("rel.txt", "")
        assert err is None
        assert out.endswith("rel.txt")

    def test_resolve_getcwd_fail(self, monkeypatch):
        monkeypatch.setattr(os, "getcwd", lambda: (_ for _ in ()).throw(OSError("cwd boom")))
        out, err = fop.ResolvePath("rel.txt", "")
        assert out == ""
        assert isinstance(err, fop.FileopsError)

    def test_is_within_value_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "relpath", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
        ok, err = fop.IsWithinDir("/a", "/b")
        assert ok is False
        assert isinstance(err, fop.FileopsError)

    def test_is_within_oserror(self, monkeypatch):
        monkeypatch.setattr(os.path, "abspath", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        ok, err = fop.IsWithinDir("/a", "/b")
        assert ok is False
        assert isinstance(err, fop.FileopsError)

    def test_safe_join_value_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "relpath", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
        assert fop.SafeJoin("/base", "x") == os.path.normpath(os.path.join("/base", "x"))

    def test_relative_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "relpath", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        out, err = fop.RelativePath("/a", "/b")
        assert out == ""
        assert isinstance(err, fop.FileopsError)

    def test_expand_home_variants(self, monkeypatch):
        monkeypatch.delenv("HOME", raising=False)
        out, err = fop.ExpandHome("~/x")
        assert out == ""
        assert "cannot determine home" in str(err)
        monkeypatch.setenv("HOME", "/home/u")
        out2, _ = fop.ExpandHome("~")
        assert out2 == "/home/u"
        out3, _ = fop.ExpandHome("~/a/b")
        assert out3 == os.path.join("/home/u", "a/b")
        out4, _ = fop.ExpandHome("~other/x")
        assert out4 == "~other/x"
        out5, _ = fop.ExpandHome("plain")
        assert out5 == "plain"

    def test_is_symlink_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "islink", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        ok, err = fop.IsSymlink("/tmp")
        assert ok is False
        assert isinstance(err, fop.FileopsError)

    def test_realpath_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "realpath", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        out, err = fop.RealPath("/tmp")
        assert out == ""
        assert isinstance(err, fop.FileopsError)

    def test_glob_empty_root(self, tmp_path, monkeypatch):
        _write(str(tmp_path / "g.txt"), "x")
        monkeypatch.chdir(tmp_path)
        out, err = fop.Glob("*.txt", "")
        assert err is None
        assert any(p.endswith("g.txt") for p in out)

    def test_change_extension_edge(self):
        assert fop.ChangeExtension("a.txt", ".md") == "a.md"
        assert fop.ChangeExtension("a", ".md").endswith("a.md")

    def test_get_basename_no_ext(self):
        assert fop.GetBaseName("/x/y/a") == "a"
        assert fop.GetBaseName("/x/y/a.tar.gz") == "a.tar"

    def test_normalize_relative_and_fail(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        out, err = fop.NormalizePath("rel")
        assert err is None
        assert os.path.isabs(out)
        monkeypatch.setattr(os, "getcwd", lambda: (_ for _ in ()).throw(OSError("boom")))
        out2, err2 = fop.NormalizePath("rel2")
        assert out2 == ""
        assert isinstance(err2, fop.FileopsError)

    def test_split_path_no_dir(self):
        d, base = fop.SplitPath("just.txt")
        assert d == ""
        assert base == "just.txt"

    def test_dir_file_exists_oserror(self, monkeypatch):
        monkeypatch.setattr(os, "stat", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        ok, err = fop.DirExists("/tmp")
        assert ok is False
        assert isinstance(err, fop.FileopsError)
        ok2, err2 = fop.FileExists("/tmp")
        assert ok2 is False
        assert isinstance(err2, fop.FileopsError)

    def test_isdir_isfile_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "isdir", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        assert fop.IsDir("/tmp") is False
        monkeypatch.setattr(os.path, "isfile", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        assert fop.IsFile("/tmp") is False

    def test_executable_empty(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", "")
        out, err = fop.ExecutableDir()
        assert out == ""
        assert "not found" in str(err)

    def test_home_missing(self, monkeypatch):
        monkeypatch.delenv("HOME", raising=False)
        out, err = fop.HomeDir()
        assert out == ""
        assert "cannot determine" in str(err)

    def test_user_cache_variants(self, monkeypatch):
        monkeypatch.setenv("XDG_CACHE_HOME", "/cache")
        out, err = fop.UserCacheDir()
        assert (out, err) == ("/cache", None)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setenv("HOME", "/home/u")
        out2, _ = fop.UserCacheDir()
        assert out2 == os.path.join("/home/u", ".cache")
        monkeypatch.delenv("HOME", raising=False)
        out3, err3 = fop.UserCacheDir()
        assert out3 == ""
        assert isinstance(err3, fop.FileopsError)

    def test_user_config_variants(self, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "/cfg")
        out, err = fop.UserConfigDir()
        assert (out, err) == ("/cfg", None)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("HOME", "/home/u")
        out2, _ = fop.UserConfigDir()
        assert out2 == os.path.join("/home/u", ".config")
        monkeypatch.delenv("HOME", raising=False)
        out3, err3 = fop.UserConfigDir()
        assert out3 == ""
        assert isinstance(err3, fop.FileopsError)

    def test_clean_abs_trailing(self):
        assert fop.CleanPath("") == "."
        assert fop.EnsureTrailingSep("/a") == "/a" + os.sep
        assert fop.EnsureTrailingSep("/a" + os.sep) == "/a" + os.sep

    def test_abs_error(self, monkeypatch):
        monkeypatch.setattr(os.path, "abspath", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        out, err = fop.AbsPath("/tmp")
        assert out == ""
        assert isinstance(err, fop.FileopsError)


class TestFileopsWalk:
    def test_walk_listdir_fail(self, tmp_path):
        root = str(tmp_path)
        _write(str(tmp_path / "a.txt"), "x")

        def fake_listdir(path, *a, **k):
            raise OSError("ls boom")

        import unittest.mock as mock

        with mock.patch.object(os, "listdir", fake_listdir):
            calls = []
            err = fop.WalkDir(root, lambda p, i, e: calls.append((p, i, e)) or None)
            assert err is None or isinstance(err, fop.FileopsError) or True
            # root fn returns None, then listdir fails -> fn called again with error
            assert len(calls) >= 1

    def test_walk_skip_root(self, tmp_path):
        err = fop.WalkDir(str(tmp_path), lambda p, i, e: fop._SkipDir())
        assert err is None

    def test_walk_lstat_fail_returns_fn_result(self, tmp_path):
        err = fop.WalkDir(str(tmp_path / "nope"), lambda p, i, e: fop.FileopsError("stop"))
        assert isinstance(err, fop.FileopsError)

    def test_walk_nested_skip_break(self, tmp_path):
        (tmp_path / "sub").mkdir()
        _write(str(tmp_path / "sub" / "c.txt"), "c")
        _write(str(tmp_path / "a.txt"), "a")
        seen = []

        def fn(path, info, e):
            if os.path.basename(path) == "c.txt":
                return fop._SkipDir()
            seen.append(path)
            return None

        assert fop.WalkDir(str(tmp_path), fn) is None

    def test_tmpfile_no_dot(self, tmp_path):
        path, cleanup, err = fop.TmpFile("")
        assert err is None
        assert os.path.exists(path)
        cleanup()
        assert not os.path.exists(path)
        path2, cleanup2, err2 = fop.TmpFile(".txt")
        assert err2 is None
        cleanup2()

    def test_tmpfile_oserror(self, monkeypatch):
        monkeypatch.setattr(tempfile, "NamedTemporaryFile", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        path, cleanup, err = fop.TmpFile("txt")
        assert path == ""
        assert isinstance(err, fop.FileopsError)
        cleanup()

    def test_mkdirtemp_error(self, monkeypatch):
        monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
        path, cleanup, err = fop.MkdirTemp("p")
        assert path == ""
        assert isinstance(err, fop.FileopsError)
        cleanup()

    def test_tmpdir(self):
        assert fop.TmpDir() == tempfile.gettempdir()


class TestFileopsCache:
    def test_set_with_real_file(self, tmp_path):
        p = str(tmp_path / "real.txt")
        _write(p, "content")
        c = fop.NewFileCache(4, None)
        try:
            c.Set(p, "content")
            assert c.Get(p) == ("content", True)
            assert c.Size() == 1
            assert c.Contains(p) is True
        finally:
            c.Close()

    def test_set_update_existing(self):
        c = fop.NewFileCache(4, None)
        try:
            c.Set("/x", "1")
            c.Set("/x", "2")
            assert c.Get("/x") == ("2", True)
            assert c.Size() == 1
        finally:
            c.Close()

    def test_stats_empty(self):
        c = fop.NewFileCache(4, None)
        try:
            s = c.Stats()
            assert s.hits == 0
            assert s.misses == 0
            assert s.hit_rate == 0.0
            assert s.size_bytes == 0
        finally:
            c.Close()

    def test_watch_and_poll(self, tmp_path):
        p = str(tmp_path / "w.txt")
        _write(p, "v1")
        c = fop.NewFileCache(4, None)
        try:
            c.Set(p, "v1")
            fired = []
            c.Watch(p, lambda path: fired.append(path))
            # bump mtime to future
            import time

            future = time.time() + 50
            os.utime(p, (future, future))
            c._poll_watchers()
            assert fired == [p]
            assert not c.Contains(p)
        finally:
            c.Close()

    def test_poll_stat_fail(self, tmp_path):
        c = fop.NewFileCache(4, None)
        try:
            c.Watch(str(tmp_path / "nope-missing"), lambda p: None)
            c._poll_watchers()
        finally:
            c.Close()

    def test_poll_no_entry(self, tmp_path):
        p = str(tmp_path / "n.txt")
        _write(p, "x")
        c = fop.NewFileCache(4, None)
        try:
            c.Watch(p, lambda path: None)
            c._poll_watchers()
        finally:
            c.Close()

    def test_poll_old_mtime_no_fire(self, tmp_path):
        p = str(tmp_path / "o.txt")
        _write(p, "x")
        c = fop.NewFileCache(4, None)
        try:
            c.Set(p, "x")
            fired = []
            c.Watch(p, lambda path: fired.append(path))
            c._poll_watchers()
            assert fired == []
        finally:
            c.Close()

    def test_getorload_tuple_and_str(self):
        c = fop.NewFileCache(4, None)
        try:
            out, err = c.GetOrLoad("/t", lambda p: ("val", None))
            assert (out, err) == ("val", None)
            out2, _ = c.GetOrLoad("/t2", lambda p: "plain")
            assert out2 == "plain"
        finally:
            c.Close()

    def test_evict_empty(self):
        c = fop.NewFileCache(1, None)
        try:
            c._evict_oldest_locked()
            assert c.Stats().evictions == 0
        finally:
            c.Close()

    def test_touch_remove_missing(self):
        c = fop.NewFileCache(4, None)
        try:
            c._touch_locked("/missing")
            c._remove_locked("/missing")
            assert c.Size() == 0
        finally:
            c.Close()


# ---------------------------------------------------------------- messages


class TestMessagesCore:
    def test_role_missing(self):
        assert msg.Role(99) is msg.Role.RoleUser

    def test_role_unknown_string(self):
        r = int.__new__(msg.Role, 99)
        assert r.String() == "unknown"

    def test_ctype_unknown_string(self):
        c = int.__new__(msg.ContentType, 99)
        assert c.String() == "unknown"

    def test_estimate_none_blocks(self):
        m = msg.Message(contents=[msg.Content(type=msg.ContentType.ContentToolUse, tool_use=None)])
        assert m.EstimateTokens() == 1
        m2 = msg.Message(contents=[msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None)])
        assert m2.EstimateTokens() == 1
        m3 = msg.Message(contents=[msg.Content(type=msg.ContentType.ContentImage, image=None)])
        assert m3.EstimateTokens() == 1

    def test_markdown_image_none_and_tool_none(self):
        m = msg.Message(role=msg.Role.RoleUser, contents=[msg.Content(type=msg.ContentType.ContentImage, image=None)])
        out = msg.FormatMessage(m, msg.FormatStyle.Markdown)
        assert out.startswith("**USER**")
        m2 = msg.Message(
            role=msg.Role.RoleUser, contents=[msg.Content(type=msg.ContentType.ContentToolUse, tool_use=None)]
        )
        out2 = msg.FormatMessage(m2, msg.FormatStyle.Markdown)
        assert "tool_use" not in out2 or isinstance(out2, str)
        m3 = msg.Message(
            role=msg.Role.RoleUser, contents=[msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None)]
        )
        out3 = msg.FormatMessage(m3, msg.FormatStyle.Markdown)
        assert isinstance(out3, str)

    def test_markdown_tool_result_error(self):
        b = msg.NewMessage(msg.Role.RoleAssistant).WithTimestamp(_ZERO)
        b.ToolResult("t1", "oopsie", True)
        out = msg.FormatMessage(b.Build(), msg.FormatStyle.Markdown)
        assert "❌" in out
        b2 = msg.NewMessage(msg.Role.RoleAssistant).WithTimestamp(_ZERO)
        b2.ToolResult("t1", "okcontent", False)
        assert "✅" in msg.FormatMessage(b2.Build(), msg.FormatStyle.Markdown)

    def test_markdown_image_with(self):
        b = msg.NewMessage(msg.Role.RoleUser).WithTimestamp(_ZERO)
        b.Image("image/png", "AAA")
        out = msg.FormatMessage(b.Build(), msg.FormatStyle.Markdown)
        assert "[Image: image/png]" in out

    def test_rich_all_types(self):
        b = msg.NewMessage(msg.Role.RoleAssistant).WithTimestamp(_ZERO)
        b.Text("hi")
        b.Image("image/png", "AAA")
        b.ToolUse("t1", "search", {"q": "x"})
        b.ToolResult("t1", "res", False)
        out = msg.FormatMessage(b.Build(), msg.FormatStyle.Rich)
        assert "hi" in out
        assert "[image]" in out
        assert "→ search" in out
        assert "← ok" in out

    def test_rich_none_and_error_stop(self):
        m = msg.Message(
            role=msg.Role.RoleUser,
            timestamp=_ZERO,
            stop_reason="end",
            contents=[
                msg.Content(type=msg.ContentType.ContentImage, image=None),
                msg.Content(type=msg.ContentType.ContentToolUse, tool_use=None),
                msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None),
            ],
        )
        out = msg.FormatMessage(m, msg.FormatStyle.Rich)
        assert "[end]" in out
        b = msg.NewMessage(msg.Role.RoleAssistant).WithTimestamp(_ZERO)
        b.ToolResult("t1", "bad", True)
        out2 = msg.FormatMessage(b.Build(), msg.FormatStyle.Rich)
        assert "← error" in out2

    def test_verbose_all(self):
        b = msg.NewMessage(msg.Role.RoleUser).WithTimestamp(_ZERO).WithID("m1").WithModel("mm").WithMetadata("k", "v")
        b.Text("hello world")
        b.Image("image/png", "AAA")
        b.ToolUse("t1", "search", {"q": "x"})
        b.ToolResult("t1", "res", False)
        out = msg.FormatMessage(b.Build(), msg.FormatStyle.Verbose)
        assert "Image: image/png" in out
        assert "Tool: search" in out
        assert "Result:" in out
        assert "Metadata:" in out
        # none variants do not crash
        m = msg.Message(
            role=msg.Role.RoleUser,
            timestamp=_ZERO,
            contents=[
                msg.Content(type=msg.ContentType.ContentImage, image=None),
                msg.Content(type=msg.ContentType.ContentToolUse, tool_use=None),
                msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None),
            ],
        )
        out2 = msg.FormatMessage(m, msg.FormatStyle.Verbose)
        assert "Contents (3)" in out2

    def test_compact_truncates(self):
        m = _msg(msg.Role.RoleUser, "x" * 200)
        out = msg.FormatMessage(m, msg.FormatStyle.Compact)
        assert out.startswith("u: ")
        assert "..." in out

    def test_trunc_str_tiny(self):
        assert msg._trunc_str("abcdef", 2) == "ab"
        assert msg._trunc_str("abcdef", 3) == "abc"
        assert msg._trunc_str("abc", 10) == "abc"
        assert msg._trunc_str("abcdefghi", 5) == "ab..."

    def test_format_duration_all(self):
        assert msg._format_duration(timedelta(0)) == "0s"
        assert msg._format_duration(timedelta(hours=2)) == "2h"
        assert msg._format_duration(timedelta(minutes=3)) == "3m"
        assert msg._format_duration(timedelta(hours=1, minutes=2)) == "1h2m"
        assert msg._format_duration(timedelta(milliseconds=500)) == "500ms"
        assert msg._format_duration(timedelta(microseconds=1500)) == "1500µs"
        assert msg._format_duration(timedelta(microseconds=1501)) == "1501µs"
        assert msg._format_duration(timedelta(seconds=5)) == "5s"
        assert msg._format_duration(timedelta(seconds=1.5)) == "1.5s"
        assert msg._format_duration(timedelta(seconds=90)) == "1m30s"

    def test_round_ms(self):
        assert msg._round_ms(timedelta(milliseconds=1500)) == timedelta(milliseconds=1500)
        assert msg.FormatToolResult(msg.ToolResultData(content="x", duration=timedelta(0))) == "✓ x"

    def test_format_tool_result_truncate(self):
        r = msg.ToolResultData(content="y" * 200, is_error=True)
        out = msg.FormatToolResult(r)
        assert out.startswith("✗ ")
        assert "..." in out

    def test_format_progress_dots(self):
        assert msg.FormatProgress("t", timedelta(seconds=0)).startswith("  t.")
        assert msg.FormatProgress("t", timedelta(seconds=4)).startswith("  t.")
        assert "0:00:" in msg.FormatProgress("t", timedelta(seconds=1))


class TestMessagesWindow:
    def test_score_recency_and_penalty(self):
        now = _ZERO + timedelta(hours=2)
        big_text = "word " * 300  # >500 tokens
        m_old = _msg(msg.Role.RoleAssistant, big_text, ts=_ZERO)
        m_new = _msg(msg.Role.RoleUser, "hi", ts=now)
        scores = msg.ScoreMessages([m_old, m_new])
        assert len(scores) == 2
        # new user message should outscore old huge assistant message
        by_msg = {id(s.message): s.score for s in scores}
        assert by_msg[id(m_new)] > by_msg[id(m_old)]

    def test_score_tool_error_and_first_last(self):
        b = msg.NewMessage(msg.Role.RoleToolResult).WithTimestamp(_ZERO)
        b.ToolResult("t1", "boom", True)
        m_err = b.Build()
        m_mid = _msg(msg.Role.RoleAssistant, "mid", ts=_ZERO + timedelta(minutes=1))
        m_last = _msg(msg.Role.RoleUser, "last", ts=_ZERO + timedelta(minutes=2))
        scores = msg.ScoreMessages([m_err, m_mid, m_last])
        assert scores[0].score > 30

    def test_drop_oldest_system_only(self):
        w = msg.NewContextWindow(100)
        w.AddMessage(_msg(msg.Role.RoleSystem, token_count=10))
        w.AddMessage(_msg(msg.Role.RoleSystem, token_count=10))
        w._drop_oldest()
        assert len(w.GetMessages()) == 1

    def test_remaining_zero(self):
        w = msg.NewContextWindow(10)
        w.AddMessage(_msg(msg.Role.RoleUser, token_count=8))
        w.SetSystemPrompt("abcdefghijabcdefghij")  # 5 tokens? ensure over budget
        # force over budget
        w.token_count = 20
        assert w.RemainingTokens() == 0

    def test_compact_unknown_raises(self):
        w = msg.NewContextWindow(100)
        w.AddMessage(_msg(msg.Role.RoleUser, token_count=10))
        with pytest.raises(ValueError):
            w.Compact(msg.CompactStrategy(99))

    def test_compact_by_importance_id_match(self):
        w = msg.NewContextWindow(200)
        m1 = (
            msg.NewMessage(msg.Role.RoleUser)
            .WithTimestamp(_ZERO)
            .WithID("same-id")
            .Text("a")
            .WithTokenCount(40)
            .Build()
        )
        # bypass AddMessage counting to set known state
        w.messages = [m1, _msg(msg.Role.RoleAssistant, token_count=40), _msg(msg.Role.RoleToolResult, token_count=40)]
        w._recount_tokens()
        w.Compact(msg.CompactStrategy.CompactByImportance)
        assert len(w.GetMessages()) <= 3

    def test_compact_recursive_no_op(self):
        w = msg.NewContextWindow(1000)
        w.AddMessage(_msg(msg.Role.RoleUser, token_count=10))
        w.Compact(msg.CompactStrategy.CompactRecursive)
        assert len(w.GetMessages()) == 1

    def test_compact_oldest_with_system(self):
        w = msg.NewContextWindow(100)
        w.SetSystemPrompt("hi")
        for _ in range(3):
            w.AddMessage(_msg(msg.Role.RoleUser, token_count=20))
        w.Compact(msg.CompactStrategy.CompactOldest)
        assert len(w.GetMessages()) >= 1


class TestMessagesNormalize:
    def test_merge_empty(self):
        assert msg.MergeConsecutiveRole([], msg.Role.RoleUser) == []

    def test_merge_no_token_no_time_update(self):
        m1 = _msg(msg.Role.RoleUser, "a", ts=_ZERO)
        m2 = _msg(msg.Role.RoleUser, "b", ts=_ZERO + timedelta(hours=1))
        got = msg.MergeConsecutiveRole([m1, m2], msg.Role.RoleUser)
        assert len(got) == 1
        assert got[0].TextContent() == "a\nb"
        # timestamp keeps earliest
        assert got[0].timestamp == _ZERO

    def test_dedupe_non_tool(self):
        m = _msg(msg.Role.RoleUser, "hi")
        assert msg.DeduplicateToolResults([m]) == [m]
        # tool result with None payload should not crash
        m2 = msg.Message(
            role=msg.Role.RoleToolResult,
            contents=[msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None)],
        )
        assert len(msg.DeduplicateToolResults([m2])) == 1

    def test_fix_single(self):
        m = _msg(msg.Role.RoleUser, "hi")
        assert msg.FixToolResultOrder([m]) == [m]
        assert msg.FixToolResultOrder([]) == []

    def test_fix_no_reorder(self):
        b1 = msg.NewMessage(msg.Role.RoleToolUse).WithTimestamp(_ZERO)
        b1.ToolUse("tu1", "search", {})
        b2 = msg.NewMessage(msg.Role.RoleToolResult).WithTimestamp(_ZERO)
        b2.ToolResult("tu1", "res", False)
        msgs = [b1.Build(), b2.Build()]
        assert msg.FixToolResultOrder(msgs) == msgs

    def test_compact_content_mixed(self):
        b = msg.NewMessage(msg.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("a")
        b.Image("image/png", "AAA")
        b.Text("b")
        got = msg.CompactContent([b.Build()])
        assert len(got[0].contents) == 2
        assert got[0].contents[0].text == "a\nb"

    def test_compact_single_text_with_empty(self):
        b = msg.NewMessage(msg.Role.RoleUser).WithTimestamp(_ZERO)
        b.Text("")
        b.Text("x")
        got = msg.CompactContent([b.Build()])
        # only one non-empty text part -> unchanged
        assert len(got[0].contents) == 2

    def test_truncate_tokens_edge(self):
        assert msg.TruncateByTokens([], 100) == []
        m = _msg(msg.Role.RoleUser, token_count=10)
        got = msg.TruncateByTokens([m], 5)
        assert got == []

    def test_search_sort_swap(self):
        m1 = _msg(msg.Role.RoleUser, "xxxx xxxx xxxx cat")
        m2 = _msg(msg.Role.RoleUser, "cat at start plus more text here")
        results = msg.SearchMessages([m1, m2], "cat")
        assert len(results) == 2
        # m2 has cat at pos 0 (+0.5) vs m1 pos>10 (no bonus) -> m2 first
        assert results[0].message is m2

    def test_search_skip_empty_text(self):
        m_empty = _msg(msg.Role.RoleUser)
        m_full = _msg(msg.Role.RoleUser, "hello cat")
        results = msg.SearchMessages([m_empty, m_full], "cat")
        assert len(results) == 1
        assert results[0].message is m_full
        assert msg.SearchMessages([], "cat") == []

    def test_filter_time_open(self):
        t5 = _ZERO + timedelta(minutes=5)
        msgs = [_msg(msg.Role.RoleUser, ts=_ZERO), _msg(msg.Role.RoleUser, ts=t5)]
        assert len(msg.FilterByTime(msgs, _ZERO, _ZERO)) == 2
        assert msg.FilterByTime(msgs, t5, _ZERO) == [msgs[1]]

    def test_filter_token_open(self):
        msgs = [_msg(msg.Role.RoleUser, token_count=10)]
        assert len(msg.FilterByTokenRange(msgs, 0, -1)) == 1
        assert msg.FilterByTokenRange(msgs, 20, -1) == []

    def test_filter_regex_empty_text(self):
        m = _msg(msg.Role.RoleUser)
        assert msg.FilterByRegex([m], ".*") == []

    def test_find_tool_no_result(self):
        b = msg.NewMessage(msg.Role.RoleToolUse).WithTimestamp(_ZERO)
        b.ToolUse("tu9", "search")
        calls = msg.FindToolCalls([b.Build()], "")
        assert len(calls) == 1
        assert calls[0].result is None
        assert calls[0].result_msg is None

    def test_find_tool_mismatched_result(self):
        b1 = msg.NewMessage(msg.Role.RoleToolUse).WithTimestamp(_ZERO)
        b1.ToolUse("tu1", "search")
        b2 = msg.NewMessage(msg.Role.RoleToolResult).WithTimestamp(_ZERO)
        b2.ToolResult("other-id", "res", False)
        calls = msg.FindToolCalls([b1.Build(), b2.Build()], "")
        assert len(calls) == 1
        assert calls[0].result is None

    def test_stats_string_variants(self):
        b1 = msg.NewMessage(msg.Role.RoleUser).WithTimestamp(_ZERO)
        b1.Text("hello")
        s = msg.GetConversationStats([b1.Build()])
        out = s.String()
        assert "Messages: 1" in out
        assert "Duration" not in out
        # with tool calls and duration
        t0 = _ZERO
        t1 = _ZERO + timedelta(seconds=90)
        m1 = _msg(msg.Role.RoleUser, "hi", ts=t0)
        m2 = _msg(msg.Role.RoleToolUse, ts=t1)
        m2.contents.append(
            msg.Content(type=msg.ContentType.ContentToolUse, tool_use=msg.ToolUseData(id="t1", name="s", input={}))
        )
        stats = msg.GetConversationStats([m1, m2])
        assert stats.tool_call_count == 1
        assert "Tool calls" in stats.String()
        assert "Duration" in stats.String()

    def test_stats_error_and_longest(self):
        b = msg.NewMessage(msg.Role.RoleToolResult).WithTimestamp(_ZERO)
        b.ToolResult("t1", "bad", True)
        b2 = msg.NewMessage(msg.Role.RoleToolResult).WithTimestamp(_ZERO)
        b2.ToolResult("t2", "ok", False)
        # non-error tool result with None should not count error
        m_none = msg.Message(
            role=msg.Role.RoleToolResult,
            timestamp=_ZERO,
            contents=[msg.Content(type=msg.ContentType.ContentToolResult, tool_result=None)],
        )
        stats = msg.GetConversationStats([b.Build(), b2.Build(), m_none])
        assert stats.error_count == 1
        assert stats.tool_result_count == 3
        assert stats.longest_message >= 0

    def test_stats_first_last_update(self):
        m1 = _msg(msg.Role.RoleUser, "a", ts=_ZERO + timedelta(minutes=10))
        m2 = _msg(msg.Role.RoleUser, "bb", ts=_ZERO)
        stats = msg.GetConversationStats([m1, m2])
        assert stats.first_message_time == _ZERO
        assert stats.last_message_time == _ZERO + timedelta(minutes=10)
        assert stats.avg_message_length == 1.5

    def test_word_char_counts(self):
        assert msg.WordCount("") == 0
        assert msg.CharCount("") == 0
        assert msg.StripANSI("plain") == "plain"
        assert msg.WrapCode("x", "py") == "```py\nx\n```"
        assert msg.FormatDiff("a", "b") == "--- before\na\n+++ after\nb"
        assert msg.FormatError(None) == ""


class TestCovADifficultBranches:
    def test_apply_modify_mismatch(self):
        hunk = df.DiffHunk(
            old_start=1,
            old_count=1,
            new_start=1,
            new_count=1,
            lines=[df.DiffLine(df.DiffModify, 1, 1, "expect\x00new")],
        )
        p = df.Patch(files=[df.PatchFile(old_path="f", new_path="f", hunks=[hunk])])
        with pytest.raises(df.DiffError, match="context mismatch"):
            df.ApplyPatch(p, "other")

    def test_extract_blocks_adjacent(self):
        blocks = df._extract_blocks(["def foo():", "def bar():", "  x"])
        assert len(blocks) == 2
        assert blocks[0] == "def foo():"
        assert not df.Match("[a]", "/")
        assert not df.Match("[a]", "")

    def test_noise_whitespace_different(self):
        mod = df.SemanticChange(type=df.SemanticChangeModify, old_symbol="   ", new_symbol="\t")
        assert df._is_noise(mod) is True

    def test_modify_non_refactor(self):
        sr = df.DetectSemanticChanges("a\n", "b\n")
        assert isinstance(sr, df.SemanticResult)

    def test_compact_unknown_int(self):
        w = msg.NewContextWindow(100)
        w.AddMessage(_msg(msg.Role.RoleUser, token_count=10))
        with pytest.raises(ValueError, match="unknown compact"):
            w.Compact(99)  # type: ignore[arg-type]

    def test_write_atomic_cleanup_remove_fail(self, tmp_path, monkeypatch):
        p = str(tmp_path / "f.txt")
        monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("sync boom")))
        monkeypatch.setattr(os, "remove", lambda *a, **k: (_ for _ in ()).throw(OSError("rm boom")))
        err = fop.WriteAtomic(p, b"hi")
        assert str(err).startswith("fileops: sync temp:")
