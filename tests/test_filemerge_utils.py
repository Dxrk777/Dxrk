import json
import sys

import pytest

from dxrk.utils import filemerge


def test_strip_json_comments():
    raw = '{\n  // comment\n  "a": 1, /* block */\n  "b": 2\n}'
    out = filemerge.strip_json_comments(raw)
    assert "comment" not in out
    assert "block" not in out
    assert json.loads(out) == {"a": 1, "b": 2}


def test_strip_trailing_commas():
    raw = '{"a": 1, "b": 2,}'
    out = filemerge.strip_trailing_commas(raw)
    assert json.loads(out) == {"a": 1, "b": 2}


def test_normalize_json():
    assert filemerge.normalize_json('{"a": 1}') == '{"a": 1}'
    assert filemerge.normalize_json("{}") == "{}"


def test_unmarshal_json_object():
    assert filemerge.unmarshal_json_object(b'{"a": 1}') == {"a": 1}
    assert filemerge.unmarshal_json_object('{"a": 1}') == {"a": 1}
    with pytest.raises(ValueError):
        filemerge.unmarshal_json_object("not json")


def test_as_sentinel():
    assert filemerge.as_sentinel({"__replace__": 42}) == (42, True)
    assert filemerge.as_sentinel({"__replace__": 1, "x": 2}) == (None, False)
    assert filemerge.as_sentinel(5) == (None, False)


def test_merge_objects():
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    overlay = {"a": 2, "nested": {"y": 3}, "new": "v"}
    result = filemerge.merge_objects(base, overlay)
    assert result == {"a": 2, "nested": {"x": 1, "y": 3}, "new": "v"}


def test_merge_objects_sentinel():
    base = {"nested": {"x": 1}}
    overlay = {"nested": {"__replace__": {"fresh": True}}}
    result = filemerge.merge_objects(base, overlay)
    assert result == {"nested": {"fresh": True}}


def test_merge_json_objects():
    out = filemerge.merge_json_objects('{"a": 1}', '{"b": 2}')
    assert json.loads(out) == {"a": 1, "b": 2}


def test_merge_json_objects_bad_base():
    out = filemerge.merge_json_objects("not json", '{"a": 1}')
    assert json.loads(out) == {"a": 1}


def test_merge_json_objects_bad_overlay():
    with pytest.raises(ValueError):
        filemerge.merge_json_objects('{"a": 1}', "not json")


def test_markers():
    assert filemerge.open_marker("s1") == "<!-- dxrk:s1 -->"
    assert filemerge.close_marker("s1") == "<!-- /dxrk:s1 -->"


def test_strip_legacy_persona_block():
    legacy = "## Personality\nSenior Architect\n## Rules\nold"
    assert filemerge.strip_legacy_persona_block(legacy) == ""
    with_marker = legacy + "\n<!-- dxrk:keep -->\ntail"
    out = filemerge.strip_legacy_persona_block(with_marker)
    assert "old" not in out
    assert "tail" in out
    assert filemerge.strip_legacy_persona_block("no fingerprints here") == "no fingerprints here"


def test_find_line_start():
    text = "line1\nline2\nline3"
    assert filemerge.find_line_start(text, "line2") == 6


def test_remove_line_start_markers():
    out = filemerge.remove_line_start_markers("# a\n# b\nplain", "# ")
    assert out == "a\nb\nplain"


def test_strip_legacy_atl_block():
    content = "head\n<!-- BEGIN:agent-teams-lite -->\nold\n<!-- END:agent-teams-lite -->\ntail"
    out = filemerge.strip_legacy_atl_block(content)
    assert "old" not in out
    assert "head" in out and "tail" in out
    orphan = "a\n<!-- END:agent-teams-lite -->\nb"
    assert "END:agent-teams-lite" not in filemerge.strip_legacy_atl_block(orphan)


def test_inject_markdown_section_replace():
    existing = "head\n<!-- dxrk:sec -->\nold\n<!-- /dxrk:sec -->\nfoot"
    out = filemerge.inject_markdown_section(existing, "sec", "new")
    assert "old" not in out
    assert "new" in out
    assert "head" in out and "foot" in out


def test_inject_markdown_section_remove():
    existing = "head\n<!-- dxrk:sec -->\nold\n<!-- /dxrk:sec -->\nfoot"
    out = filemerge.inject_markdown_section(existing, "sec", "")
    assert "old" not in out
    assert "dxrk:sec" not in out
    assert "head" in out and "foot" in out


def test_inject_markdown_section_append():
    out = filemerge.inject_markdown_section("head", "sec", "new")
    assert "head" in out
    assert "<!-- dxrk:sec -->" in out
    assert "new" in out


def test_go_quote():
    assert filemerge.go_quote('he said "hi"') == '"he said \\"hi\\""'


def test_upsert_codex_mcp_server_block():
    out = filemerge.upsert_codex_mcp_server_block("", "", "", [])
    assert "dxrk-memory" in out
    out2 = filemerge.upsert_codex_mcp_server_block("", "srv", "cmd", ["a", "b"])
    assert "[mcp_servers.srv]" in out2
    assert 'args = ["a", "b"]' in out2


def test_upsert_codex_dxrk_memory_block():
    out = filemerge.upsert_codex_dxrk_memory_block("")
    assert "dxrk" in out.lower()


def test_upsert_top_level_toml_string():
    out = filemerge.upsert_top_level_toml_string('key = "old"\n', "key", "new")
    assert "new" in out


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific directory handle")
def test_write_file_atomic(tmp_path):
    path = str(tmp_path / "f.txt")
    result = filemerge.write_file_atomic(path, b"hello")
    assert result.Created
    assert filemerge.read_comparable_file(path) == b"hello"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific directory handle")
def test_write_file_atomic_overwrite(tmp_path):
    path = str(tmp_path / "f.txt")
    filemerge.write_file_atomic(path, b"one")
    result = filemerge.write_file_atomic(path, b"two")
    assert result.Changed
    assert filemerge.read_comparable_file(path) == b"two"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific directory handle")
def test_write_file_atomic_same(tmp_path):
    path = str(tmp_path / "f.txt")
    filemerge.write_file_atomic(path, b"x")
    result = filemerge.write_file_atomic(path, b"x")
    assert not result.Changed
    assert not result.Created
