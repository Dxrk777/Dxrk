# SPDX-License-Identifier: MIT
"""Tests for dxrk.tools.filetools — mirrors internal/tools/filetools behaviors."""

from __future__ import annotations

import base64

import pytest

from dxrk.tools import Registry, filetools


@pytest.fixture
def registry() -> Registry:
    reg = Registry()
    filetools.register_all(reg)
    return reg


def run_tool(
    reg: Registry, name: str, input_: dict | None = None
) -> tuple[object, str | None]:
    tool = reg.get(name)
    assert tool is not None, f"tool {name} not registered"
    return tool.execute({}, input_)


def test_register_all_registers_five(registry: Registry) -> None:
    names = [t.name() for t in registry.list()]
    assert names == ["file_edit", "file_read", "file_write", "glob", "grep"]


def test_file_write_create(registry: Registry, temp_dir) -> None:
    target = temp_dir / "nested" / "out.txt"
    result, err = run_tool(
        registry, "file_write", {"file_path": str(target), "content": "a\nb\n"}
    )
    assert err is None
    assert result["type"] == "create"
    assert result["path"] == str(target)
    assert result["size_bytes"] == 4
    assert result["lines"] == 3
    assert target.read_text() == "a\nb\n"


def test_file_write_update(registry: Registry, temp_dir) -> None:
    target = temp_dir / "out.txt"
    target.write_text("old\n")
    result, err = run_tool(
        registry, "file_write", {"file_path": str(target), "content": "new\n"}
    )
    assert err is None
    assert result["type"] == "update"
    assert result["lines_before"] == 2
    assert target.read_text() == "new\n"


def test_file_write_validate_missing(registry: Registry) -> None:
    tool = registry.get("file_write")
    assert tool is not None
    assert (
        tool.validate({"file_path": "/tmp/x"})
        == "file_path and content are required"
    )
    assert tool.validate({"content": "x"}) == "file_path and content are required"


def test_file_write_relative_path(registry: Registry) -> None:
    result, err = run_tool(
        registry, "file_write", {"file_path": "relative.txt", "content": "x"}
    )
    assert result is None
    assert err is not None
    assert "absolute" in err


def test_file_read_text(registry: Registry, temp_dir) -> None:
    target = temp_dir / "read.txt"
    target.write_text("l1\nl2\nl3")
    result, err = run_tool(registry, "file_read", {"file_path": str(target)})
    assert err is None
    assert result["content"] == "l1\nl2\nl3"
    assert result["total_lines"] == 3
    assert result["encoding"] == "utf8"
    assert result["start_line"] == 1
    assert result["num_lines"] == 3


def test_file_read_offset_limit(registry: Registry, temp_dir) -> None:
    target = temp_dir / "read.txt"
    target.write_text("\n".join(f"line{i}" for i in range(10)))
    result, err = run_tool(
        registry, "file_read", {"file_path": str(target), "offset": 3, "limit": 2}
    )
    assert err is None
    assert result["start_line"] == 4
    assert result["num_lines"] == 2
    assert result["content"] == "line3\nline4"


def test_file_read_offset_exceeds(registry: Registry, temp_dir) -> None:
    target = temp_dir / "read.txt"
    target.write_text("a\n")
    result, err = run_tool(
        registry, "file_read", {"file_path": str(target), "offset": 50}
    )
    assert err is None
    assert result["content"] == ""
    assert result["start_line"] == 3
    assert "exceeds" in result["warning"]


def test_file_read_image_base64(registry: Registry, temp_dir) -> None:
    target = temp_dir / "pic.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 10)
    result, err = run_tool(registry, "file_read", {"file_path": str(target)})
    assert err is None
    assert result["type"] == "image"
    assert result["media_type"] == "image/png"
    assert result["base64"] == base64.b64encode(target.read_bytes()).decode("ascii")


def test_file_read_missing(registry: Registry, temp_dir) -> None:
    result, err = run_tool(
        registry, "file_read", {"file_path": str(temp_dir / "nope.txt")}
    )
    assert result is None
    assert err is not None
    assert "file does not exist" in err


def test_file_read_directory(registry: Registry, temp_dir) -> None:
    result, err = run_tool(registry, "file_read", {"file_path": str(temp_dir)})
    assert result is None
    assert err is not None
    assert "is a directory" in err


def test_file_edit_replace(registry: Registry, temp_dir) -> None:
    target = temp_dir / "edit.txt"
    target.write_text("hello world\nhello there\n")
    result, err = run_tool(
        registry,
        "file_edit",
        {
            "file_path": str(target),
            "old_string": "hello world",
            "new_string": "hi world",
        },
    )
    assert err is None
    assert result["replacements"] == 1
    assert target.read_text() == "hi world\nhello there\n"


def test_file_edit_replace_all(registry: Registry, temp_dir) -> None:
    target = temp_dir / "edit.txt"
    target.write_text("a hello b hello\n")
    result, err = run_tool(
        registry,
        "file_edit",
        {
            "file_path": str(target),
            "old_string": "hello",
            "new_string": "hi",
            "replace_all": True,
        },
    )
    assert err is None
    assert result["replacements"] == 2
    assert target.read_text() == "a hi b hi\n"


def test_file_edit_multiple_matches_requires_replace_all(
    registry: Registry, temp_dir
) -> None:
    target = temp_dir / "edit.txt"
    target.write_text("hello hello\n")
    result, err = run_tool(
        registry,
        "file_edit",
        {"file_path": str(target), "old_string": "hello", "new_string": "hi"},
    )
    assert result is None
    assert err is not None
    assert "set replace_all=true" in err


def test_file_edit_not_found(registry: Registry, temp_dir) -> None:
    target = temp_dir / "edit.txt"
    target.write_text("abc\n")
    result, err = run_tool(
        registry,
        "file_edit",
        {"file_path": str(target), "old_string": "zzz", "new_string": "x"},
    )
    assert result is None
    assert err is not None
    assert "old_string not found" in err


def test_file_edit_identical(registry: Registry, temp_dir) -> None:
    target = temp_dir / "edit.txt"
    target.write_text("abc\n")
    result, err = run_tool(
        registry,
        "file_edit",
        {"file_path": str(target), "old_string": "a", "new_string": "a"},
    )
    assert result is None
    assert err is not None
    assert "identical" in err


def test_glob_basic(registry: Registry, temp_dir) -> None:
    (temp_dir / "a.txt").write_text("")
    (temp_dir / "b.py").write_text("")
    (temp_dir / "sub").mkdir()
    (temp_dir / "sub" / "c.txt").write_text("")
    result, err = run_tool(
        registry, "glob", {"pattern": "*.txt", "path": str(temp_dir)}
    )
    assert err is None
    assert result["count"] == 1
    assert result["files"] == [str(temp_dir / "a.txt")]
    assert result["truncated"] is False


def test_glob_double_star(registry: Registry, temp_dir, monkeypatch) -> None:
    (temp_dir / "a.txt").write_text("")
    (temp_dir / "sub").mkdir()
    (temp_dir / "sub" / "b.txt").write_text("")
    monkeypatch.chdir(temp_dir)
    result, err = run_tool(registry, "glob", {"pattern": "**/*.txt"})
    assert err is None
    assert result["count"] == 1
    assert result["files"] == ["./a.txt"]


def test_glob_skips_hidden_and_vendor(
    registry: Registry, temp_dir, monkeypatch
) -> None:
    (temp_dir / ".hidden").mkdir()
    (temp_dir / ".hidden" / "x.txt").write_text("")
    (temp_dir / "vendor").mkdir()
    (temp_dir / "vendor" / "y.txt").write_text("")
    (temp_dir / "keep.txt").write_text("")
    monkeypatch.chdir(temp_dir)
    result, err = run_tool(registry, "glob", {"pattern": "**/*.txt"})
    assert err is None
    assert result["files"] == ["./keep.txt"]
    assert result["count"] == 1


def test_glob_validate(registry: Registry) -> None:
    tool = registry.get("glob")
    assert tool is not None
    assert tool.validate({}) == "pattern is required"


def test_grep_basic(registry: Registry, temp_dir) -> None:
    (temp_dir / "a.txt").write_text("foo bar\nnothing\nfoo again\n")
    (temp_dir / "b.txt").write_text("no match\n")
    result, err = run_tool(registry, "grep", {"pattern": "foo", "path": str(temp_dir)})
    assert err is None
    assert result["num_matches"] == 2
    assert result["num_files"] == 1
    assert result["files"] == ["a.txt"]
    assert result["matches"][0]["line"] == 1
    assert result["matches"][0]["text"] == "foo bar"


def test_grep_case_insensitive(registry: Registry, temp_dir) -> None:
    (temp_dir / "a.txt").write_text("FOO\n")
    result, err = run_tool(
        registry, "grep", {"pattern": "foo", "-i": True, "path": str(temp_dir)}
    )
    assert err is None
    assert result["num_matches"] == 1


def test_grep_include_filter(registry: Registry, temp_dir) -> None:
    (temp_dir / "a.go").write_text("match\n")
    (temp_dir / "a.py").write_text("match\n")
    result, err = run_tool(
        registry, "grep", {"pattern": "match", "path": str(temp_dir), "include": ".*go"}
    )
    assert err is None
    assert result["num_matches"] == 1
    assert result["matches"][0]["file"] == "a.go"


def test_grep_include_invalid_regex(registry: Registry, temp_dir) -> None:
    (temp_dir / "a.go").write_text("match\n")
    result, err = run_tool(
        registry, "grep", {"pattern": "match", "path": str(temp_dir), "include": ".go"}
    )
    assert result is None
    assert err is not None
    assert "compile include pattern" in err


def test_grep_single_file(registry: Registry, temp_dir) -> None:
    target = temp_dir / "one.txt"
    target.write_text("hit\n")
    result, err = run_tool(registry, "grep", {"pattern": "hit", "path": str(target)})
    assert err is None
    assert result["num_matches"] == 1
    assert result["matches"][0]["file"] == str(target)


def test_grep_invalid_regex(registry: Registry, temp_dir) -> None:
    result, err = run_tool(registry, "grep", {"pattern": "([", "path": str(temp_dir)})
    assert result is None
    assert err is not None
    assert "invalid regex" in err


def test_grep_validate(registry: Registry) -> None:
    tool = registry.get("grep")
    assert tool is not None
    assert tool.validate({}) == "pattern is required"


import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific paths")
