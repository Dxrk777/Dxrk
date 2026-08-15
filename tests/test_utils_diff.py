# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.diff (mirrors internal/utils/diff port)."""

from __future__ import annotations

import json
import os

import pytest

from dxrk.utils import diff as df

OLD = "a\nb\nc\n"
NEW = "a\nb\nd\n"


@pytest.fixture
def plain_colors():
    """Disables ANSI colors for formatter tests and restores defaults after."""
    df.SetColors(
        df.ColorScheme(
            added="", removed="", modified="", context="", meta="", reset="", bold=""
        )
    )
    yield
    df.SetColors(df.ColorScheme())


def _result(old: str = OLD, new: str = NEW) -> df.DiffResult:
    return df.ComputeDiff(old, new)


def _write(path: str, content: str) -> None:
    with open(path, "w") as fh:
        fh.write(content)


class TestComputeDiff:
    def test_pure_modify(self):
        r = _result()
        assert len(r.hunks) == 1
        h = r.hunks[0]
        assert h.old_start == 1
        assert h.old_count == 4
        assert h.new_start == 1
        assert h.new_count == 4
        assert [
            (ln.type, ln.content, ln.line_num_old, ln.line_num_new) for ln in h.lines
        ] == [
            (df.DiffType.EQUAL, "a", 1, 1),
            (df.DiffType.EQUAL, "b", 2, 2),
            (df.DiffType.MODIFY, "c\x00d", 3, 3),
            (df.DiffType.EQUAL, "", 4, 4),
        ]
        assert r.stats.lines_added == 0
        assert r.stats.lines_removed == 0
        assert r.stats.lines_changed == 1
        assert r.stats.total_lines == 4

    def test_identical(self):
        r = _result(OLD, OLD)
        assert r.hunks == []
        assert r.stats.lines_changed == 0
        assert r.stats.total_lines == 4

    def test_empty_inputs(self):
        r = df.ComputeDiff("", "")
        assert r.hunks == []
        assert r.stats.total_lines == 0

    def test_trailing_newline_added(self):
        r = df.ComputeDiff("a", "a\n")
        h = r.hunks[0]
        assert (h.old_start, h.old_count, h.new_start, h.new_count) == (1, 1, 1, 2)
        assert [(ln.type, ln.content) for ln in h.lines] == [
            (df.DiffType.EQUAL, "a"),
            (df.DiffType.INSERT, ""),
        ]
        assert r.stats.lines_added == 1
        assert r.stats.total_lines == 1

    def test_type_str_names(self):
        assert str(df.DiffType.EQUAL) == "equal"
        assert str(df.DiffType.INSERT) == "insert"
        assert str(df.DiffType.DELETE) == "delete"
        assert str(df.DiffType.MODIFY) == "modify"
        assert str(df.DiffStatus.MODIFIED) == "modified"
        assert str(df.DiffStatus.UNCHANGED) == "unchanged"

    def test_word_diff(self):
        r = df.ComputeWordDiff("foo bar baz", "foo qux baz")
        assert [(ln.type, ln.content) for ln in r.hunks[0].lines] == [
            (df.DiffType.EQUAL, "foo"),
            (df.DiffType.EQUAL, " "),
            (df.DiffType.MODIFY, "bar\x00qux"),
            (df.DiffType.EQUAL, " "),
            (df.DiffType.EQUAL, "baz"),
        ]
        assert r.stats.lines_changed == 1
        assert r.stats.total_lines == 5

    def test_char_diff(self):
        r = df.ComputeCharDiff("ab", "ad")
        assert [(ln.type, ln.content) for ln in r.hunks[0].lines] == [
            (df.DiffType.EQUAL, "a"),
            (df.DiffType.MODIFY, "b\x00d"),
        ]


class TestFormatUnified:
    def test_plain(self, plain_colors):
        assert df.FormatUnified(_result()) == "@@ -1,4 +1,4 @@\n a\n b\n!c\n \n"

    def test_default_colors(self):
        out = df.FormatUnified(_result())
        assert "\x1b[37m a\x1b[0m" in out
        assert "\x1b[33m" in out
        assert out.startswith("@@ -1,4 +1,4 @@")

    def test_context_lines_ignored(self):
        assert df.FormatUnified(_result(), 0) == df.FormatUnified(_result(), 10)


class TestFormatContext:
    def test_exact(self, plain_colors):
        assert (
            df.FormatContext(_result()) == "*** 1,4 ***\n--- 1,4 ---\n a\n b\n!c\n \n"
        )


class TestFormatSideBySide:
    def test_exact_40(self, plain_colors):
        assert df.FormatSideBySide(_result(), 40) == (
            "----------------------------------------\n"
            "@@ -1,4 +1,4 @@\n"
            " a                   | a\n"
            " b                   | b\n"
            "!c                   | d\n"
            "                     | \n"
            "----------------------------------------"
        )


class TestFormatCompact:
    def test_exact(self, plain_colors):
        assert df.FormatCompact(_result()) == "M 1..5 +1 -1"


class TestFormatMarkdown:
    def test_exact(self, plain_colors):
        assert df.FormatMarkdown(_result()) == (
            "```diff\n@@ -1,4 +1,4 @@\n  a\n  b\n~ c\n  \n```"
        )


class TestFormatWithLineNumbers:
    def test_exact(self, plain_colors):
        assert df.FormatWithLineNumbers(_result(), 2) == (
            "     1      1   a\n     2      2   b\n     3      3 ! c\n     4      4   \n"
        )

    def test_context_lines_ignored(self):
        assert df.FormatWithLineNumbers(_result(), 0) == df.FormatWithLineNumbers(
            _result(), 10
        )


class TestFormatJSON:
    def test_keys_and_modify_line(self):
        data = json.loads(df.FormatJSON(_result()))
        hunk = data["Hunks"][0]
        assert hunk["OldStart"] == 1
        assert hunk["OldCount"] == 4
        assert hunk["NewStart"] == 1
        assert hunk["NewCount"] == 4
        assert hunk["Lines"][2] == {
            "Type": "modify",
            "Content": "c\x00d",
            "LineNumOld": 3,
            "LineNumNew": 3,
        }
        assert hunk["Lines"][0] == {
            "Type": "equal",
            "Content": "a",
            "LineNumOld": 1,
            "LineNumNew": 1,
        }


class TestFormatHTML:
    def test_structure(self):
        out = df.FormatHTML(_result())
        assert out.startswith("<!DOCTYPE html>")
        assert "<title>Diff</title>" in out
        assert "c" in out


class TestColorScheme:
    def test_enabled_property(self):
        assert df.ColorScheme().enabled
        empty = df.ColorScheme(
            added="", removed="", modified="", context="", meta="", reset="", bold=""
        )
        assert not empty.enabled


class TestCreatePatch:
    def test_paths_and_hunks(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "old.txt", "new.txt")
        assert len(p.files) == 1
        fd = p.files[0]
        assert fd.old_path == "old.txt"
        assert fd.new_path == "new.txt"
        assert len(fd.hunks) == 1

    def test_is_deleted(self):
        p = df.CreatePatch("a\nb\n", "", "f", "f")
        assert p.files[0].is_deleted
        assert not p.files[0].is_new

    def test_is_new(self):
        p = df.CreatePatch("", "a\nb\n", "f", "f")
        assert p.files[0].is_new
        assert not p.files[0].is_deleted


class TestFormatPatch:
    def test_exact(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.FormatPatch(p) == (
            "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -1,3 +1,3 @@\n a\n-b\n+c\n \n"
        )

    def test_no_trailing_newline(self):
        p = df.CreatePatch("x", "x\n", "n", "n")
        assert (
            df.FormatPatch(p)
            == "diff --git a/n b/n\n--- a/n\n+++ b/n\n@@ -1,1 +1,2 @@\n x\n+\n"
        )

    def test_deleted_file(self):
        p = df.CreatePatch("a\nb\n", "", "d", "d")
        assert df.FormatPatch(p) == (
            "diff --git a/d b/d\ndeleted file mode 100644\n"
            "--- a/d\n+++ b/d\n@@ -1,3 +1,0 @@\n-a\n-b\n-\n"
        )

    def test_added_file(self):
        p = df.CreatePatch("", "a\nb\n", "d", "d")
        assert df.FormatPatch(p) == (
            "diff --git a/d b/d\nnew file mode 100644\n"
            "--- a/d\n+++ b/d\n@@ -1,0 +1,3 @@\n+a\n+b\n+\n"
        )


class TestParsePatch:
    def test_roundtrip_modify(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        parsed = df.ParsePatch(df.FormatPatch(p))
        assert parsed.files[0].old_path == "f"
        assert parsed.files[0].new_path == "f"
        assert df.ApplyPatch(parsed, "a\nb\n") == "a\nc\n"

    def test_roundtrip_no_trailing_newline(self):
        p = df.CreatePatch("x", "x\n", "n", "n")
        parsed = df.ParsePatch(df.FormatPatch(p))
        assert df.ApplyPatch(parsed, "x") == "x\n"

    def test_roundtrip_deleted(self):
        p = df.CreatePatch("a\nb\n", "", "d", "d")
        parsed = df.ParsePatch(df.FormatPatch(p))
        assert parsed.files[0].is_deleted
        assert df.ApplyPatch(parsed, "a\nb\n") == ""

    def test_garbage_is_empty_patch(self):
        p = df.ParsePatch("this is not a patch at all")
        assert p.files == []

    def test_invalid_hunk_header_raises(self):
        with pytest.raises(df.DiffError, match="invalid hunk"):
            df.ParsePatch("diff --git a/x b/x\n@@ -bad\n")


class TestApplyPatch:
    def test_empty_patch_raises(self):
        with pytest.raises(df.DiffError, match="patch has no hunks"):
            df.ApplyPatch(df.Patch(), "x")

    def test_context_mismatch_raises(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nb\nd\n", "f", "f")
        with pytest.raises(df.DiffError, match="context mismatch"):
            df.ApplyPatch(p, "x\ny\nz\n")

    def test_offset_apply(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nb\nd\n", "f", "f")
        df.PatchOffset(p, 0, 2)
        assert df.ApplyPatch(p, "x\ny\na\nb\nc\n") == "x\ny\na\nb\nd\n"


class TestApplyPatchToFile:
    def test_apply_and_revert(self, temp_dir):
        path = str(temp_dir / "f.txt")
        _write(path, "a\nb\n")
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.ApplyPatchToFile(p, path) == "a\nc\n"
        assert _read(path) == "a\nc\n"
        assert df.RevertPatchToFile(p, path) == "a\nb\n"
        assert _read(path) == "a\nb\n"

    def test_missing_file_raises(self, temp_dir):
        p = df.CreatePatch("a\n", "b\n", "f", "f")
        with pytest.raises(df.DiffError, match="file not found"):
            df.ApplyPatchToFile(p, str(temp_dir / "nope.txt"))


class TestRevertPatch:
    def test_revert(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.RevertPatch(p, "a\nc\n") == "a\nb\n"


class TestMergePatches:
    def test_empty_merge(self):
        assert df.MergePatches(df.Patch(), df.Patch()).files == []

    def test_chain_merge(self):
        pa = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        pb = df.CreatePatch("a\nc\n", "a\nd\n", "f", "f")
        merged = df.MergePatches(pa, pb)
        assert len(merged.files[0].hunks) == 2
        assert df.ApplyPatch(merged, "a\nb\n") == "a\nd\n"


class TestValidatePatch:
    def test_empty_patch_valid(self):
        assert df.ValidatePatch(df.Patch())

    def test_roundtrip_patch_valid(self):
        p = df.CreatePatch("a\nb\n", "a\nc\n", "f", "f")
        assert df.ValidatePatch(df.ParsePatch(df.FormatPatch(p)))


class TestPatchOffset:
    def test_bad_index_raises(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nb\nd\n", "f", "f")
        with pytest.raises(df.DiffError, match="patch is invalid"):
            df.PatchOffset(p, 5, 1)

    def test_negative_offset_allowed(self):
        p = df.CreatePatch("a\nb\nc\n", "a\nb\nd\n", "f", "f")
        assert df.PatchOffset(p, 0, -3) is None


class TestMatch:
    def test_basic(self):
        assert df.Match("*.txt", "hello.txt")
        assert not df.Match("*.md", "hello.txt")
        assert not df.Match("*.txt", "a/b.txt")

    def test_character_classes(self):
        assert df.Match("[a-c]x", "bx")
        assert not df.Match("[a-c]x", "dx")
        assert df.Match("[!a]", "x")
        assert not df.Match("[a-z]+", "abc")

    def test_escapes(self):
        assert df.Match("a\\*b", "a*b")
        assert not df.Match("a\\*b", "axb")
        assert df.Match("a**b", "aXXb")

    def test_separators(self):
        assert df.Match("?", "a")
        assert not df.Match("?", "/")
        assert df.Match("?.go", "x.go")

    def test_unclosed_class_fails(self):
        assert not df.Match("a[bc", "abc")


class TestCompareFiles:
    def test_identical(self, temp_dir):
        a = str(temp_dir / "a.txt")
        _write(a, "a\nb\n")
        assert df.CompareFiles(a, a).status == df.DiffStatus.UNCHANGED

    def test_pure_modify(self, temp_dir):
        a = str(temp_dir / "a.txt")
        b = str(temp_dir / "b.txt")
        _write(a, "1\n")
        _write(b, "2\n")
        fd = df.CompareFiles(a, b)
        assert fd.status == df.DiffStatus.MODIFIED
        assert fd.lines_added == 0
        assert fd.lines_removed == 0

    def test_added_line(self, temp_dir):
        a = str(temp_dir / "a.txt")
        b = str(temp_dir / "b.txt")
        _write(a, "a\nb\nc\n")
        _write(b, "a\nb\nc\nd\n")
        assert df.CompareFiles(a, b).status == df.DiffStatus.MODIFIED

    def test_missing_file_raises(self, temp_dir):
        a = str(temp_dir / "nope.txt")
        b = str(temp_dir / "b.txt")
        _write(b, "x\n")
        with pytest.raises(df.DiffError, match="file not found"):
            df.CompareFiles(a, b)

    def test_binary_files(self, temp_dir):
        a = str(temp_dir / "a.bin")
        b = str(temp_dir / "b.bin")
        with open(a, "wb") as fh:
            fh.write(b"\x00\x01")
        with open(b, "wb") as fh:
            fh.write(b"\x00\x02")
        fd = df.CompareFiles(a, b)
        assert fd.is_binary
        assert fd.status == df.DiffStatus.MODIFIED

    def test_binary_identical(self, temp_dir):
        a = str(temp_dir / "a.bin")
        with open(a, "wb") as fh:
            fh.write(b"\x00\x01")
        fd = df.CompareFiles(a, a)
        assert fd.is_binary
        assert fd.status == df.DiffStatus.UNCHANGED

    def test_ignore_whitespace(self, temp_dir):
        a = str(temp_dir / "a.txt")
        b = str(temp_dir / "b.txt")
        _write(a, "a b\n")
        _write(b, "a  b\n")
        assert df.CompareFilesWithOptions(a, b).status == df.DiffStatus.MODIFIED
        assert df.CompareFilesWithOptions(a, b, ignore_whitespace=True).status == (
            df.DiffStatus.UNCHANGED
        )


class TestCompareDirectories:
    def _make_tree(self, root):
        _write(str(root / "a.txt"), "1\n")
        _write(str(root / "gone.txt"), "x\n")
        (root / "subd").mkdir()

    def test_statuses(self, temp_dir):
        old = temp_dir / "old"
        new = temp_dir / "new"
        old.mkdir()
        new.mkdir()
        self._make_tree(old)
        self._make_tree(new)
        _write(str(new / "a.txt"), "2\n")
        _write(str(new / "new.txt"), "1\n")
        (new / "gone.txt").unlink()
        results = df.CompareDirectories(str(old), str(new))
        by_old = {fd.old_path: fd for fd in results}
        by_new = {fd.new_path: fd for fd in results}
        assert by_old["a.txt"].status == df.DiffStatus.MODIFIED
        assert by_old["gone.txt"].status == df.DiffStatus.REMOVED
        assert by_old["gone.txt"].new_path == ""
        assert by_new["new.txt"].status == df.DiffStatus.ADDED
        assert by_new["new.txt"].old_path == ""

    def test_missing_dir_raises(self, temp_dir):
        with pytest.raises(df.DiffError, match="not a directory"):
            df.CompareDirectories(str(temp_dir / "zz"), str(temp_dir))


class TestSummarizeDirectory:
    def test_hashes(self, temp_dir):
        _write(str(temp_dir / "a.txt"), "1\n")
        _write(str(temp_dir / "gone.txt"), "x\n")
        assert df.SummarizeDirectory(str(temp_dir)) == {
            "a.txt": "4355a46b19d3",
            "gone.txt": "73cb3858a687",
        }

    def test_missing_dir(self, temp_dir):
        assert df.SummarizeDirectory(str(temp_dir / "zz")) == {}


class TestSemanticChanges:
    def test_add_remove_refactor(self):
        sr = df.DetectSemanticChanges(
            "def foo():\n    pass\n", "def bar():\n    pass\n"
        )
        assert [(c.type, c.symbol, c.confidence) for c in sr.changes] == [
            (df.SemanticChangeType.ADD, "bar", 1.0),
            (df.SemanticChangeType.REMOVE, "foo", 1.0),
            (df.SemanticChangeType.REFACTOR, "", 0.6),
        ]

    def test_identical(self):
        sr = df.DetectSemanticChanges(
            "def foo():\n    pass\n", "def foo():\n    pass\n"
        )
        assert sr.changes == []
        assert sr.total_added == 0
        assert sr.total_removed == 0

    def test_format(self):
        sr = df.DetectSemanticChanges(
            "def foo():\n    pass\n", "def bar():\n    pass\n"
        )
        assert df.FormatSemanticChanges(sr).startswith(
            "add: bar ()\nremove: foo ()\nrefactor: def foo(): -> def bar(): ()\n"
        )

    def test_dir_diff_empty(self):
        assert df.DetectSemanticDirDiff([]).changes == []

    def test_file_diff_unchanged(self, temp_dir):
        a = str(temp_dir / "a.txt")
        _write(a, "a\nb\n")
        sr = df.DetectSemanticFileDiff(df.CompareFiles(a, a))
        assert sr.changes == []
        assert sr.total_added == 0
        assert sr.total_removed == 0


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()
