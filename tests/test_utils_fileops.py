# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.fileops (mirrors internal/utils/fileops port)."""

from __future__ import annotations

import os
import struct
import zlib

import pytest

from dxrk.utils import fileops as f

_ERR = f.FileopsError


def _write(path: str, content: str) -> None:
    with open(path, "w") as fh:
        fh.write(content)


def _png_1x1() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        sig
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )


class TestFileopsError:
    def test_message(self):
        err = _ERR("boom")
        assert err.msg == "boom"
        assert str(err) == "boom"


class TestValidatePath:
    def test_traversal(self):
        assert (
            str(_ERR("x") and f.ValidatePath(".."))
            == "fileops: path contains traversal components"
        )

    def test_null_byte(self):
        assert str(f.ValidatePath("a\x00b")) == "fileops: path contains null byte"

    def test_ok(self):
        assert f.ValidatePath("a/b") is None


class TestDetectEncoding:
    def test_variants(self):
        assert f.DetectEncoding(b"hello") == "ASCII"
        assert f.DetectEncoding(b"\x01\x02\x03") == "ASCII"
        assert f.DetectEncoding(b"") == "UTF-8"
        assert f.DetectEncoding(b"\xc3\xa9") == "UTF-8"
        assert f.DetectEncoding(b"\xe9") == "Latin-1"
        assert f.DetectEncoding(b"\xef\xbb\xbfhi") == "UTF-8-BOM"
        assert f.DetectEncoding(b"\xff\xfea\x00") == "UTF-16LE"


class TestIsBinary:
    def test_text(self, temp_dir):
        path = str(temp_dir / "t.txt")
        _write(path, "hello")
        assert f.IsBinary(path) == (False, None)

    def test_binary(self, temp_dir):
        path = str(temp_dir / "b.bin")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x01")
        assert f.IsBinary(path) == (True, None)

    def test_missing(self, temp_dir):
        ok, err = f.IsBinary(str(temp_dir / "nope"))
        assert ok is False
        assert isinstance(err, _ERR)


class TestReadFile:
    def test_utf8(self, temp_dir):
        path = str(temp_dir / "u.txt")
        _write(path, "héllo\nwörld\n")
        fc, err = f.ReadFile(path)
        assert err is None
        assert fc is not None
        assert fc.path == path
        assert fc.content == "héllo\nwörld\n"
        assert fc.encoding == "UTF-8"
        assert fc.size == 14
        assert fc.line_count == 2

    def test_bom(self, temp_dir):
        path = str(temp_dir / "bom.txt")
        with open(path, "wb") as fh:
            fh.write(b"\xef\xbb\xbfhi\nthere\n")
        fc, err = f.ReadFile(path)
        assert err is None
        assert fc is not None
        assert fc.content == "\ufeffhi\nthere\n"
        assert fc.encoding == "UTF-8-BOM"

    def test_utf16le_reads_with_bom_encoding(self, temp_dir):
        path = str(temp_dir / "u16.txt")
        with open(path, "wb") as fh:
            fh.write(b"\xff\xfea\x00\n\x00")
        fc, err = f.ReadFile(path)
        assert err is None
        assert fc is not None
        assert fc.encoding == "UTF-16LE"

    def test_binary_reads_with_ascii_encoding(self, temp_dir):
        path = str(temp_dir / "b.bin")
        with open(path, "wb") as fh:
            fh.write(b"\x00\x01\x02")
        fc, err = f.ReadFile(path)
        assert err is None
        assert fc is not None
        assert fc.encoding == "ASCII"

    def test_missing(self, temp_dir):
        fc, err = f.ReadFile(str(temp_dir / "nope"))
        assert fc is None
        assert isinstance(err, _ERR)


class TestReadFileLines:
    def _path(self, temp_dir) -> str:
        path = str(temp_dir / "l.txt")
        _write(path, "a\nb\nc\nd\n")
        return path

    def test_full(self, temp_dir):
        lines, total, err = f.ReadFileLines(self._path(temp_dir), 0, 100)
        assert err is None
        assert lines == ["a", "b", "c", "d", ""]
        assert total == 5

    def test_offset_limit(self, temp_dir):
        lines, total, err = f.ReadFileLines(self._path(temp_dir), 1, 2)
        assert lines == ["b", "c"]
        assert total == 5

    def test_negative_offset_clamped(self, temp_dir):
        lines, _, _ = f.ReadFileLines(self._path(temp_dir), -5, 2)
        assert lines == ["a", "b"]

    def test_offset_past_end(self, temp_dir):
        lines, total, _ = f.ReadFileLines(self._path(temp_dir), 10, 2)
        assert lines == []
        assert total == 5

    def test_zero_limit_means_rest(self, temp_dir):
        lines, _, _ = f.ReadFileLines(self._path(temp_dir), 1, 0)
        assert lines == ["b", "c", "d", ""]

    def test_missing(self, temp_dir):
        lines, total, err = f.ReadFileLines(str(temp_dir / "nope"), 0, 1)
        assert lines == []
        assert total == 0
        assert isinstance(err, _ERR)


class TestReadImage:
    def test_invalid_image(self, temp_dir):
        pytest.importorskip("PIL")
        path = str(temp_dir / "t.txt")
        _write(path, "not an image")
        img, err = f.ReadImage(path)
        assert img is None
        assert isinstance(err, _ERR)
        assert str(err).startswith("fileops: file is not a valid image:")

    def test_valid_png(self, temp_dir):
        pytest.importorskip("PIL")
        path = str(temp_dir / "p.png")
        with open(path, "wb") as fh:
            fh.write(_png_1x1())
        img, err = f.ReadImage(path)
        assert err is None
        assert img is not None
        assert img.width == 1
        assert img.height == 1
        assert img.media_type == "image/png"
        assert img.base64_data.startswith("iVBOR")


class TestWriteFile:
    def test_create(self, temp_dir):
        path = str(temp_dir / "w.txt")
        assert f.WriteFile(path, "a\n", f.WriteOpts()) is None
        assert _read(path) == "a\n"

    def test_overwrite_default(self, temp_dir):
        path = str(temp_dir / "w.txt")
        _write(path, "a\n")
        assert f.WriteFile(path, "b\n", f.WriteOpts()) is None
        assert _read(path) == "b\n"

    def test_no_overwrite_existing_errors(self, temp_dir):
        path = str(temp_dir / "w.txt")
        _write(path, "a\n")
        err = f.WriteFile(path, "b\n", f.WriteOpts(overwrite=False))
        assert isinstance(err, _ERR)
        assert str(err) == f"fileops: file exists and Overwrite is false: {path}"
        assert _read(path) == "a\n"

    def test_no_overwrite_missing_creates(self, temp_dir):
        path = str(temp_dir / "n.txt")
        assert f.WriteFile(path, "c\n", f.WriteOpts(overwrite=False)) is None
        assert _read(path) == "c\n"

    def test_create_dirs(self, temp_dir):
        path = str(temp_dir / "nd" / "x.txt")
        assert f.WriteFile(path, "a\n", f.WriteOpts(create_dirs=True)) is None
        assert _read(path) == "a\n"

    def test_missing_parent_errors(self, temp_dir):
        path = str(temp_dir / "nd2" / "x.txt")
        err = f.WriteFile(path, "a\n", f.WriteOpts())
        assert isinstance(err, _ERR)
        assert str(err).startswith("fileops: create temp:")

    def test_backup(self, temp_dir):
        path = str(temp_dir / "w.txt")
        _write(path, "a\n")
        assert f.WriteFile(path, "b\n", f.WriteOpts(backup=True)) is None
        assert _read(path) == "b\n"
        assert _read(str(temp_dir / "w.txt.bak")) == "a\n"

    def test_mode(self, temp_dir):
        path = str(temp_dir / "m.txt")
        assert f.WriteFile(path, "a\n", f.WriteOpts(mode=0o600)) is None
        assert os.stat(path).st_mode & 0o777 == 0o600


class TestWriteAtomic:
    def test_file(self, temp_dir):
        path = str(temp_dir / "a.txt")
        assert f.WriteAtomic(path, b"abc") is None
        with open(path, "rb") as fh:
            assert fh.read() == b"abc"

    def test_target_is_directory(self, temp_dir):
        err = f.WriteAtomic(str(temp_dir), b"x")
        assert isinstance(err, _ERR)
        assert str(err).startswith("fileops: rename:")


class TestBackupFile:
    def test_ok(self, temp_dir):
        path = str(temp_dir / "w.txt")
        _write(path, "a\n")
        bak, err = f.BackupFile(path)
        assert err is None
        assert bak == str(temp_dir / "w.txt.bak")
        assert _read(bak) == "a\n"

    def test_missing(self, temp_dir):
        bak, err = f.BackupFile(str(temp_dir / "nope"))
        assert bak == ""
        assert isinstance(err, _ERR)
        assert str(err).startswith("fileops: read for backup:")


class TestWriteLines:
    def test_joins_with_newline(self, temp_dir):
        path = str(temp_dir / "l.txt")
        assert f.WriteLines(path, ["a", "b"], f.WriteOpts()) is None
        assert _read(path) == "a\nb\n"


class TestAppendFile:
    def test_existing(self, temp_dir):
        path = str(temp_dir / "l.txt")
        _write(path, "a\nb\n")
        assert f.AppendFile(path, "c\n") is None
        assert _read(path) == "a\nb\nc\n"

    def test_missing_creates(self, temp_dir):
        path = str(temp_dir / "mm.txt")
        assert f.AppendFile(path, "x\n") is None
        assert _read(path) == "x\n"


class TestEnsureDir:
    def test_creates_parent_of_path(self, temp_dir):
        assert f.EnsureDir(str(temp_dir / "a" / "b" / "f.txt")) is None
        assert (temp_dir / "a" / "b").is_dir()
        assert not (temp_dir / "a" / "b" / "f.txt").exists()

    def test_existing(self, temp_dir):
        assert f.EnsureDir(str(temp_dir)) is None


class TestEditFile:
    def test_replace(self, temp_dir):
        path = str(temp_dir / "e.txt")
        _write(path, "hello\nworld\n")
        assert f.EditFile(path, [f.EditOp(old_text="hello", new_text="bye")]) is None
        assert _read(path) == "bye\nworld\n"

    def test_indent_preserved(self, temp_dir):
        path = str(temp_dir / "ed.txt")
        _write(path, "    x = 1\n    y = 2\n")
        assert (
            f.EditFile(path, [f.EditOp(old_text="x = 1", new_text="a = 1\nb = 2")])
            is None
        )
        assert _read(path) == "    a = 1\n    b = 2\n    y = 2\n"

    def test_missing_old_returns_editerror(self, temp_dir):
        path = str(temp_dir / "e.txt")
        _write(path, "hello\n")
        err = f.EditFile(path, [f.EditOp(old_text="zzz", new_text="bye")])
        assert isinstance(err, f.EditError)
        assert err.op_index == 0

    def test_missing_file(self, temp_dir):
        err = f.EditFile(str(temp_dir / "nope"), [f.EditOp(old_text="a", new_text="b")])
        assert isinstance(err, _ERR)


class TestEditFileRegex:
    def test_replace(self, temp_dir):
        path = str(temp_dir / "e.txt")
        _write(path, "hello\nworld\n")
        assert (
            f.EditFileRegex(
                path, [f.RegexEditOp(pattern="hello", replacement="bye", flags="g")]
            )
            is None
        )
        assert _read(path) == "bye\nworld\n"

    def test_bad_regex(self, temp_dir):
        path = str(temp_dir / "e.txt")
        _write(path, "hello\n")
        err = f.EditFileRegex(path, [f.RegexEditOp(pattern="(", replacement="x")])
        assert isinstance(err, _ERR)
        assert (
            str(err)
            == "regex edit op 0: missing ), unterminated subpattern at position 0"
        )


class TestApplyEdits:
    def test_ok(self):
        out, err = f.ApplyEdits(
            "hello\nworld\n", [f.EditOp(old_text="hello", new_text="hi")]
        )
        assert err is None
        assert out == "hi\nworld\n"

    def test_missing_old(self):
        out, err = f.ApplyEdits(
            "hello\nworld\n", [f.EditOp(old_text="zz", new_text="hi")]
        )
        assert out == ""
        assert isinstance(err, f.EditError)
        assert err.op_index == 0
        assert err.line == 0
        assert "old text not found" in err.message


class TestValidateEdits:
    def test_ok(self):
        assert (
            f.ValidateEdits(
                "hello\nworld\n", [f.EditOp(old_text="hello", new_text="hi")]
            )
            == []
        )

    def test_missing_old(self):
        errs = f.ValidateEdits(
            "hello\nworld\n", [f.EditOp(old_text="zz", new_text="hi")]
        )
        assert len(errs) == 1
        assert errs[0].op_index == 0
        assert errs[0].message == "old text not found: zz"


class TestFindAndReplace:
    def test_first_only(self):
        out, count, err = f.FindAndReplace("a a a", "a", "b")
        assert err is None
        assert out == "b a a"
        assert count == 1

    def test_all(self):
        out, count, err = f.FindAndReplaceAll("a a a", "a", "b")
        assert err is None
        assert out == "b b b"
        assert count == 3


class TestApplyRegexEdits:
    def test_global_flag(self):
        out, count, err = f.ApplyRegexEdits(
            "foo foo", [f.RegexEditOp(pattern="foo", replacement="bar", flags="g")]
        )
        assert err is None
        assert out == "bar bar"
        assert count == 2

    def test_case_insensitive(self):
        out, _, err = f.ApplyRegexEdits(
            "x x", [f.RegexEditOp(pattern="X", replacement="y", flags="gi")]
        )
        assert err is None
        assert out == "y y"

    def test_bad_regex(self):
        out, count, err = f.ApplyRegexEdits(
            "foo", [f.RegexEditOp(pattern="(", replacement="x")]
        )
        assert out == ""
        assert count == 0
        assert isinstance(err, _ERR)
        assert (
            str(err)
            == "regex edit op 0: missing ), unterminated subpattern at position 0"
        )


class TestWalkDir:
    def test_visits_all(self, temp_dir):
        root = str(temp_dir)
        _write(str(temp_dir / "a.txt"), "a\n")
        (temp_dir / "sub").mkdir()
        _write(str(temp_dir / "sub" / "c.txt"), "c\n")
        seen = []
        err = f.WalkDir(
            root, lambda path, info, walk_err: seen.append((path, info, walk_err))
        )
        assert err is None
        assert {os.path.relpath(p, root) for p, _, _ in seen} == {
            ".",
            "a.txt",
            "sub",
            os.path.join("sub", "c.txt"),
        }

    def test_skip_dir(self, temp_dir):
        root = str(temp_dir)
        (temp_dir / "sub").mkdir()
        _write(str(temp_dir / "sub" / "c.txt"), "c\n")
        _write(str(temp_dir / "a.txt"), "a\n")
        _write(str(temp_dir / "z.txt"), "z\n")
        seen = []
        assert (
            f.WalkDir(
                root,
                lambda path, info, walk_err: (
                    f._SkipDir()
                    if os.path.basename(path) == "sub"
                    else seen.append((path, info, walk_err))
                ),
            )
            is None
        )
        names = {os.path.basename(p) for p, _, _ in seen}
        assert names == {os.path.basename(root), "a.txt", "z.txt"}
        assert "c.txt" not in names

    def test_missing_root_calls_fn(self, temp_dir):
        root = str(temp_dir / "zz")
        calls = []
        err = f.WalkDir(
            root, lambda path, info, walk_err: calls.append((path, info, walk_err))
        )
        assert err is None
        assert len(calls) == 1
        assert calls[0][0] == root
        assert calls[0][1] is None
        assert isinstance(calls[0][2], OSError)

    def test_error_propagates(self, temp_dir):
        err = f.WalkDir(str(temp_dir), lambda path, info, walk_err: _ERR("stop"))
        assert isinstance(err, _ERR)
        assert err.msg == "stop"


class TestGlob:
    def test_root_pattern(self, temp_dir):
        _write(str(temp_dir / "a.txt"), "a\n")
        _write(str(temp_dir / "b.md"), "b\n")
        (temp_dir / "sub").mkdir()
        out, err = f.Glob("*.txt", str(temp_dir))
        assert err is None
        assert out == [str(temp_dir / "a.txt")]

    def test_nested_pattern(self, temp_dir):
        (temp_dir / "sub").mkdir()
        _write(str(temp_dir / "sub" / "c.txt"), "c\n")
        out, _ = f.Glob(os.path.join("sub", "*.txt"), str(temp_dir))
        assert out == [os.path.join(str(temp_dir), "sub", "c.txt")]

    def test_no_match(self, temp_dir):
        out, err = f.Glob("*.zzz", str(temp_dir))
        assert err is None
        assert out == []


class TestPathHelpers:
    def test_clean_path(self):
        assert f.CleanPath("/a//b/./c") == "/a/b/c"

    def test_normalize_path(self):
        out, err = f.NormalizePath("/a/./b/../c")
        assert err is None
        assert out == "/a/c"

    def test_split_path(self):
        assert f.SplitPath("/a/b/c.txt") == ("/a/b/", "c.txt")

    def test_safe_join_ok(self, temp_dir):
        root = str(temp_dir)
        assert f.SafeJoin(root, "x") == os.path.join(root, "x")

    def test_safe_join_traversal_clamped(self, temp_dir):
        root = str(temp_dir)
        assert f.SafeJoin(root, "../evil") == root

    def test_is_within_dir(self, temp_dir):
        root = str(temp_dir)
        inside = os.path.join(root, "a.txt")
        outside = os.path.join(str(temp_dir.parent), "other")
        assert f.IsWithinDir(inside, root) == (True, None)
        assert f.IsWithinDir(outside, root) == (False, None)
        assert f.IsWithinDir(root, root) == (True, None)

    def test_relative_path(self, temp_dir):
        root = str(temp_dir)
        out, err = f.RelativePath(os.path.join(root, "a.txt"), root)
        assert err is None
        assert out == "a.txt"

    def test_relative_path_outside(self, temp_dir):
        root = str(temp_dir)
        out, err = f.RelativePath(os.path.join(str(temp_dir.parent), "u.txt"), root)
        assert err is None
        assert out == os.path.join("..", "u.txt")

    def test_change_extension(self):
        assert f.ChangeExtension("a.txt", "md") == "a.md"
        assert f.ChangeExtension("a", "md") == "a.md"
        assert f.ChangeExtension("a.txt", "") == "a."

    def test_get_extension(self):
        assert f.GetExtension("a.tar.gz") == ".gz"

    def test_get_base_name(self):
        assert f.GetBaseName("/x/y/a.txt") == "a"

    def test_ensure_trailing_sep(self):
        assert f.EnsureTrailingSep("/a/b") == "/a/b/"
        assert f.EnsureTrailingSep("/a/b/") == "/a/b/"

    def test_expand_home(self):
        out, err = f.ExpandHome("~/x")
        assert err is None
        assert out == os.path.join(os.path.expanduser("~"), "x")
        out, err = f.ExpandHome("x")
        assert err is None
        assert out == "x"

    def test_home_dir(self):
        out, err = f.HomeDir()
        assert err is None
        assert out == os.path.expanduser("~")

    def test_platform(self):
        assert f.Platform() == "linux"

    def test_is_hidden(self):
        assert f.IsHidden(".a")
        assert not f.IsHidden("a")

    def test_is_symlink(self, temp_dir):
        target = str(temp_dir / "t.txt")
        _write(target, "x")
        link = str(temp_dir / "ln")
        os.symlink(target, link)
        assert f.IsSymlink(link) == (True, None)
        assert f.IsSymlink(target) == (False, None)

    def test_dir_and_file_predicates(self, temp_dir):
        path = str(temp_dir / "t.txt")
        _write(path, "x")
        assert f.IsDir(str(temp_dir)) is True
        assert f.IsFile(str(temp_dir)) is False
        assert f.IsDir(path) is False
        assert f.IsFile(path) is True
        assert f.DirExists(str(temp_dir)) == (True, None)
        assert f.FileExists(path) == (True, None)
        assert f.DirExists(path) == (False, None)
        assert f.FileExists(str(temp_dir / "zz")) == (False, None)

    def test_abs_and_real_path(self, temp_dir):
        root = str(temp_dir)
        assert f.AbsPath(root) == (os.path.abspath(root), None)
        assert f.RealPath(root) == (os.path.realpath(root), None)

    def test_user_dirs(self):
        for fn in (f.ExecutableDir, f.UserCacheDir, f.UserConfigDir):
            out, err = fn()
            assert err is None
            assert out


class TestTempFiles:
    def test_tmp_file(self, temp_dir):
        path, cleanup, err = f.TmpFile("txt")
        assert err is None
        assert os.path.exists(path)
        assert cleanup() is None
        assert not os.path.exists(path)

    def test_mkdir_temp(self, temp_dir):
        path, cleanup, err = f.MkdirTemp("probe")
        assert err is None
        assert os.path.isdir(path)
        assert cleanup() is None
        assert not os.path.isdir(path)


class TestFileCache:
    def test_set_get(self):
        c = f.NewFileCache(2, None)
        assert c.Set("/x", "1") is None
        assert c.Get("/x") == ("1", True)
        assert c.Get("/y") == ("", False)

    def test_lru_eviction(self):
        c = f.NewFileCache(2, None)
        c.Set("/a", "1")
        c.Set("/b", "2")
        c.Set("/c", "3")
        assert c.Get("/a") == ("", False)
        assert c.Get("/b") == ("2", True)
        assert c.Get("/c") == ("3", True)
        assert c.Stats().evictions == 1
        assert c.Stats().entries == 2

    def test_max_entries_defaults_to_256(self):
        c = f.NewFileCache(0, None)
        for i in range(300):
            c.Set(f"/k{i}", str(i))
        assert c.Stats().entries == 256
        assert c.Stats().evictions == 44

    def test_negative_ttl_expires(self):
        import datetime

        c = f.NewFileCache(2, datetime.timedelta(seconds=-1))
        c.Set("/x", "1")
        assert c.Get("/x") == ("", False)

    def test_none_ttl_persists(self):
        c = f.NewFileCache(2, None)
        c.Set("/x", "1")
        assert c.Get("/x") == ("1", True)

    def test_invalidate(self):
        c = f.NewFileCache(4, None)
        c.Set("/x", "1")
        assert c.Contains("/x")
        c.Invalidate("/x")
        assert not c.Contains("/x")
        assert c.Size() == 0

    def test_invalidate_all(self):
        c = f.NewFileCache(4, None)
        c.Set("/x", "1")
        c.Set("/y", "2")
        c.InvalidateAll()
        assert c.Size() == 0

    def test_invalidate_pattern_matches_basename(self):
        c = f.NewFileCache(4, None)
        c.Set("/dir/a.txt", "1")
        c.Set("/dir/b.md", "2")
        c.InvalidatePattern("*.txt")
        assert not c.Contains("/dir/a.txt")
        assert c.Contains("/dir/b.md")

    def test_invalidate_pattern_does_not_match_subdirs(self):
        c = f.NewFileCache(4, None)
        c.Set("/dir/a.txt", "1")
        c.InvalidatePattern("sub/*")
        assert c.Contains("/dir/a.txt")

    def test_invalidate_prefix(self):
        c = f.NewFileCache(4, None)
        c.Set("/dir/a.txt", "1")
        c.Set("/dir/b.md", "2")
        c.Set("/other/x", "3")
        c.InvalidatePrefix("/dir")
        assert not c.Contains("/dir/a.txt")
        assert not c.Contains("/dir/b.md")
        assert c.Contains("/other/x")

    def test_get_or_load_caches(self):
        calls = []

        def loader(path):
            calls.append(path)
            return "loaded"

        c = f.NewFileCache(2, None)
        assert c.GetOrLoad("/x", loader) == ("loaded", None)
        assert c.GetOrLoad("/x", loader) == ("loaded", None)
        assert calls == ["/x"]

    def test_get_or_load_error_not_cached(self):
        calls = []

        def loader(path):
            calls.append(path)
            return ("", _ERR("boom"))

        c = f.NewFileCache(2, None)
        out, err = c.GetOrLoad("/x", loader)
        assert out == ""
        assert isinstance(err, _ERR)
        out2, err2 = c.GetOrLoad("/x", loader)
        assert out2 == ""
        assert isinstance(err2, _ERR)
        assert str(err2) == "boom"
        assert len(calls) == 2

    def test_keys_and_paths_order(self):
        c = f.NewFileCache(4, None)
        c.Set("/x", "1")
        c.Set("/y", "2")
        c.Get("/x")
        assert c.Keys() == ["/y", "/x"]
        assert c.Paths() == ["/y", "/x"]

    def test_stats(self):
        c = f.NewFileCache(4, None)
        c.Set("/x", "1")
        c.Get("/x")
        c.Get("/zz")
        stats = c.Stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.entries == 1
        assert stats.hit_rate == 0.5
        assert stats.evictions == 0

    def test_close(self):
        c = f.NewFileCache(4, None)
        c.Set("/x", "1")
        assert c.Close() is None


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()
