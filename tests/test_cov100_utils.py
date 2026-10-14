# SPDX-License-Identifier: MIT
"""Coverage 100% for dxrk/utils (excluding dxrk/utils/http, covered elsewhere).

Uses the canonical snake_case API (the Go-style names remain as
backwards-compatible aliases only).
"""

from __future__ import annotations

import os

import pytest

from dxrk.utils.bashparse_model import (
    DangerLevel,
    Location,
    NodeType,
    ParseError,
    RedirectOp,
)
from dxrk.utils.bashparse_nodes import (
    AndNode,
    BackgroundNode,
    CommandNode,
    CompoundNode,
    OrNode,
    PipeNode,
    RedirectNode,
    SequenceNode,
    SubshellNode,
    collect_commands,
    walk,
)
from dxrk.utils.bashparse_parser import (
    _is_valid_env_key,
    _Parser,
    _Token,
    _tokenize,
    _TokenType,
    parse,
)
from dxrk.utils.bashparse_quote import _needs_quote, _node_string, _shell_quote
from dxrk.utils.filemerge_atomic import (
    WriteResult,
    ensure_atomic_parent_dir,
    read_comparable_file,
    write_file_atomic,
)
from dxrk.utils.filemerge_json import (
    merge_json_objects,
    merge_objects,
    strip_json_comments,
    strip_trailing_commas,
    unmarshal_json_object,
)
from dxrk.utils.filemerge_markdown import (
    find_line_start,
    inject_markdown_section,
    remove_line_start_markers,
    strip_legacy_atl_block,
    strip_legacy_persona_block,
)
from dxrk.utils.filemerge_toml import (
    upsert_codex_mcp_server_block,
    upsert_top_level_toml_string,
)
from dxrk.utils.fileops_path import (
    _SkipDir,
    dir_exists,
    resolve_path,
    safe_join,
    tmp_file,
    walk_dir,
)


class TestBashparseQuote:
    def test_shell_quote_escapes(self):
        assert _shell_quote('a"b') == '"a\\"b"'
        assert _shell_quote("a\\b") == '"a\\\\b"'
        assert _shell_quote("a\nb") == '"a\\nb"'
        assert _shell_quote("a\tb") == '"a\\tb"'
        assert _shell_quote("a\rb") == '"a\\rb"'

    def test_shell_quote_control_chars(self):
        assert _shell_quote("a\x01\x7f") == '"a\\x01\\x7f"'
        assert _shell_quote("plain") == '"plain"'

    def test_node_string_none(self):
        assert _node_string(None) == "<nil>"
        node = CommandNode(name="echo", args=["hi"])
        assert _node_string(node) == node.string()

    def test_needs_quote(self):
        assert _needs_quote("a b") is True
        assert _needs_quote("plain") is False


class TestBashparseModel:
    def test_danger_level_strings(self):
        assert DangerLevel.Safe.string() == "safe"
        assert DangerLevel.Warning.string() == "warning"
        assert DangerLevel.Dangerous.string() == "dangerous"
        assert DangerLevel.Critical.string() == "critical"

    def test_node_type_and_redirect_strings(self):
        assert NodeType.NodeCommand.string() == "Command"
        assert NodeType.NodeCompound.string() == "Compound"
        assert RedirectOp.RedirectWrite.string() == ">"
        assert RedirectOp.RedirectAppend.string() == ">>"

    def test_parse_error_str(self):
        assert "line 1" in str(ParseError("boom", Location(line=1, column=2)))
        assert str(ParseError("boom")) == "bashparse: boom"


class TestBashparseLexer:
    def test_advance_at_eof_is_noop(self):
        from dxrk.utils.bashparse_lexer import _Lexer

        lex = _Lexer("")
        lex._advance()
        assert lex._peek() == ""

    def test_newline_advance(self):
        node, err = parse("echo a\necho b")
        assert err is None
        assert node is not None
        assert "echo" in node.string()

    def test_unterminated_expansion(self):
        node, err = parse("echo ${UNFINISHED")
        assert err is None
        assert node is not None
        assert "${UNFINISHED" in node.string()


class TestBashparseNodes:
    def _cmd(self, name="echo", args=None):
        return CommandNode(name=name, args=args or ["hi"])

    def test_command_with_env_and_quoted_arg(self):
        node = CommandNode(name="echo", args=["hi", "a b"], env={"K": "v"})
        assert node.string() == 'K=v echo hi "a b"'
        assert node.node_type() is NodeType.NodeCommand
        assert node.children() == []
        assert collect_commands(node)[0] is node

    def test_sequence_string(self):
        node = SequenceNode(commands=[self._cmd(), self._cmd("ls")])
        assert node.string() == "echo hi; ls hi"
        assert node.node_type() is NodeType.NodeSequence
        assert len(node.children()) == 2

    def test_and_or_strings(self):
        and_node = AndNode(left=self._cmd(), right=self._cmd("ls"))
        assert and_node.string() == "echo hi && ls hi"
        assert and_node.node_type() is NodeType.NodeAnd
        or_node = OrNode(left=self._cmd(), right=self._cmd("ls"))
        assert or_node.string() == "echo hi || ls hi"
        assert or_node.node_type() is NodeType.NodeOr
        assert len(or_node.children()) == 2

    def test_subshell_and_pipe_strings(self):
        sub = SubshellNode(body=self._cmd())
        assert sub.string() == "(echo hi)"
        assert sub.children()[0].string() == "echo hi"
        pipe = PipeNode(commands=[self._cmd(), self._cmd("wc")])
        assert pipe.string() == "echo hi | wc hi"

    def test_redirect_variants(self):
        node = RedirectNode(fd=2, op=RedirectOp.RedirectWrite, target="f", body=self._cmd())
        assert node.node_type() is NodeType.NodeRedirect
        assert node.string() == "echo hi 2> f"
        assert len(node.children()) == 1
        bare = RedirectNode(fd=1, op=RedirectOp.RedirectWrite, target="f", body=None)
        assert bare.children() == []
        assert bare.string() == "> f"

    def test_background_and_compound(self):
        bg = BackgroundNode(command=self._cmd())
        assert bg.node_type() is NodeType.NodeBackground
        assert bg.string() == "echo hi &"
        assert len(bg.children()) == 1
        comp = CompoundNode(body=[self._cmd(), self._cmd("ls")])
        assert comp.node_type() is NodeType.NodeCompound
        assert comp.string() == "{ echo hi; ls hi }"
        assert len(comp.children()) == 2

    def test_walk_stops_when_fn_false(self):
        seen: list[str] = []
        root = AndNode(left=self._cmd(), right=self._cmd("ls"))
        walk(root, lambda n: seen.append(n.string()) or False)
        assert seen == ["echo hi && ls hi"]


class TestBashparseParser:
    def test_error_after_semicolon(self):
        node, err = parse("echo a; |")
        assert node is None
        assert err is not None

    def test_error_inside_compound(self):
        node, err = parse("{ | }")
        assert node is None
        assert err is not None

    def test_semicolon_inside_compound(self):
        # NOTE: the compound-level trailing-semicolon consume is defensive:
        # _parse_list always consumes `;` itself, so that branch is dead.
        from dxrk.utils.bashparse_nodes import SequenceNode

        node, err = parse("{ echo a; echo b; }")
        assert err is None
        assert isinstance(node, CompoundNode)
        assert len(node.body) == 1
        assert isinstance(node.body[0], SequenceNode)

    def test_invalid_env_key_becomes_arg(self):
        node, err = parse("echo 1X=y")
        assert err is None
        assert isinstance(node, CommandNode)
        assert node.env == {}
        assert node.args == ["1X=y"]

    def test_valid_env_assignment(self):
        node, err = parse("mycmd FOO=bar baz")
        assert err is None
        assert isinstance(node, CommandNode)
        assert node.env == {"FOO": "bar"}
        assert node.args == ["baz"]

    def test_peek_past_end_returns_eof(self):
        assert _Parser([])._peek().typ is _TokenType.tokEOF

    def test_parse_simple_command_error(self):
        parser = _Parser([_Token(_TokenType.tokEOF, "", Location())])
        node, err = parser._parse_simple_command()
        assert node is None
        assert err is not None

    def test_parse_command_propagates_simple_error(self):
        parser = _Parser(_tokenize("echo hi"))

        def _boom():
            return None, ParseError("boom")

        parser._parse_simple_command = _boom  # type: ignore[method-assign]
        node, err = parser._parse_command()
        assert node is None
        assert err is not None
        assert "boom" in str(err)

    def test_env_key_validation(self):
        assert _is_valid_env_key("") is False
        assert _is_valid_env_key("1A") is False
        assert _is_valid_env_key("A-B") is False
        assert _is_valid_env_key("A1_B") is True

    def test_stacked_redirect_with_dupe(self):
        node, err = parse("echo hi >file 2>&1")
        assert err is None
        assert node is not None
        assert node.string() == "echo hi > file <& 1"


class TestDiffCore:
    def test_build_result_ignores_unknown_op(self):
        from dxrk.utils.diff_core import _build_result
        from dxrk.utils.diff_model import _Op

        res = _build_result([_Op(typ=999, old_idx=0, new_idx=0)], ["a"], ["b"], 3)  # type: ignore[arg-type]
        assert res.stats.total_lines == 1
        assert res.hunks == []


class TestDiffSemantic:
    def test_is_noise_comment_vs_code(self):
        from dxrk.utils import diff_semantic as ds

        change = ds.SemanticChange(
            type=ds.SemanticChangeModify,
            old_symbol="# hello",
            new_symbol="x = 1",
        )
        assert ds._is_noise(change) is False

    def test_extract_blocks_with_leading_blanks(self):
        from dxrk.utils import diff_semantic as ds

        blocks = ds._extract_blocks(["", "def f():", "    pass", "", "x = 1"])
        assert blocks == ["def f():\n    pass"]


class TestFilemergeAtomic:
    def test_read_symlink_refused(self, tmp_path):
        import sys

        if sys.platform == "win32":
            pytest.skip("POSIX-only")
        target = tmp_path / "real.txt"
        target.write_bytes(b"data")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        with pytest.raises(OSError, match="symlink"):
            read_comparable_file(str(link))

    def test_read_oversize_refused(self, tmp_path, monkeypatch):
        import os
        import stat as stat_mod
        from types import SimpleNamespace

        from dxrk.utils import filemerge_atomic as fa

        target = tmp_path / "big.bin"
        target.write_bytes(b"x")
        fake = SimpleNamespace(st_mode=stat_mod.S_IFREG, st_size=fa.MAX_ATOMIC_FILE_SIZE + 1)
        monkeypatch.setattr(os, "lstat", lambda p: fake)
        with pytest.raises(OSError, match="exceeds max atomic"):
            read_comparable_file(str(target))

    def test_read_grown_file_refused(self, tmp_path, monkeypatch):
        import os
        import stat as stat_mod
        from types import SimpleNamespace

        from dxrk.utils import filemerge_atomic as fa

        target = tmp_path / "grow.bin"
        target.write_bytes(b"x")
        fake = SimpleNamespace(st_mode=stat_mod.S_IFREG, st_size=10)
        monkeypatch.setattr(os, "lstat", lambda p: fake)

        class _BigFile:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n=-1):
                return b"y" * (fa.MAX_ATOMIC_FILE_SIZE + 1)

        monkeypatch.setattr("builtins.open", lambda *a, **k: _BigFile())
        with pytest.raises(OSError, match="exceeds max atomic"):
            read_comparable_file(str(target))

    def test_ensure_parent_creates_missing(self, tmp_path):
        new_sub = tmp_path / "newsub"
        ensure_atomic_parent_dir(str(new_sub), "p")
        assert new_sub.is_dir()

    def test_ensure_parent_makedirs_fail(self, tmp_path, monkeypatch):
        import os

        monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        with pytest.raises(OSError, match="create parent directories"):
            ensure_atomic_parent_dir(str(tmp_path / "nope" / "sub"), "p")

    def test_ensure_parent_stat_fail(self, tmp_path, monkeypatch):
        import os

        real_lstat = os.lstat
        missing = tmp_path / "gone"

        def _fake_lstat(p):
            if str(p) == str(missing):
                raise PermissionError("denied")
            return real_lstat(p)

        monkeypatch.setattr(os, "lstat", _fake_lstat)
        with pytest.raises(OSError, match="stat parent directory"):
            ensure_atomic_parent_dir(str(missing), "p")

    def test_ensure_parent_rejects_symlink_and_file(self, tmp_path):
        import sys

        if sys.platform == "win32":
            pytest.skip("POSIX-only")
        real_dir = tmp_path / "realdir"
        real_dir.mkdir()
        link = tmp_path / "linkdir"
        link.symlink_to(real_dir, target_is_directory=True)
        with pytest.raises(OSError, match="symlink parent"):
            ensure_atomic_parent_dir(str(link), "p")
        plain = tmp_path / "plain.txt"
        plain.write_text("x")
        with pytest.raises(OSError, match="not a directory"):
            ensure_atomic_parent_dir(str(plain), "p")

    def test_ensure_parent_chmod_relax_fail(self, tmp_path, monkeypatch):
        import os
        import sys

        if sys.platform == "win32":
            pytest.skip("POSIX-only")
        ro_dir = tmp_path / "rodir"
        ro_dir.mkdir()
        os.chmod(ro_dir, 0o555)
        monkeypatch.setattr(os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        try:
            with pytest.raises(OSError, match="relax parent directory"):
                ensure_atomic_parent_dir(str(ro_dir), "p")
        finally:
            monkeypatch.undo()
            os.chmod(ro_dir, 0o755)

    def test_write_perm_zero_defaults(self, tmp_path):
        target = tmp_path / "out.txt"
        res = write_file_atomic(str(target), b"hi", perm=0)
        assert res == WriteResult(Changed=True, Created=True)
        assert target.read_bytes() == b"hi"

    def test_write_wraps_read_error(self, tmp_path):
        import sys

        if sys.platform == "win32":
            pytest.skip("POSIX-only")
        target = tmp_path / "real.txt"
        target.write_bytes(b"old")
        link = tmp_path / "link.txt"
        link.symlink_to(target)
        with pytest.raises(OSError, match="read existing file"):
            write_file_atomic(str(link), b"new")

    def test_write_mkstemp_fail(self, tmp_path, monkeypatch):
        import tempfile

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(tempfile, "mkstemp", lambda *a, **k: (_ for _ in ()).throw(OSError("no tmp")))
        with pytest.raises(OSError, match="create temp file"):
            write_file_atomic(str(tmp_path / "out.txt"), b"new")

    def test_write_write_fail(self, tmp_path, monkeypatch):
        import os

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("wboom")))
        with pytest.raises(OSError, match="write temp file"):
            write_file_atomic(str(tmp_path / "out.txt"), b"new")

    def test_write_rename_fail(self, tmp_path, monkeypatch):
        import os

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(os, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError("rboom")))
        with pytest.raises(OSError, match="replace .* atomically"):
            write_file_atomic(str(tmp_path / "out.txt"), b"new")

    def test_write_sync_oserror_fail(self, tmp_path, monkeypatch):
        from dxrk.utils import filemerge_atomic as fa

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(fa, "_sync_dir_fn", lambda d: (_ for _ in ()).throw(OSError("sync down")))
        with pytest.raises(OSError, match="sync parent directory"):
            write_file_atomic(str(tmp_path / "out.txt"), b"new")

    def test_write_sync_win32_tolerance(self, tmp_path, monkeypatch):
        from dxrk.utils import filemerge_atomic as fa

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(fa, "_sync_dir_fn", lambda d: (_ for _ in ()).throw(PermissionError("perm")))
        monkeypatch.setattr(fa, "_runtime_goos", "win32")
        res = write_file_atomic(str(tmp_path / "out.txt"), b"new")
        assert res == WriteResult(Changed=True, Created=False)

    def test_write_sync_permission_fail(self, tmp_path, monkeypatch):
        from dxrk.utils import filemerge_atomic as fa

        (tmp_path / "out.txt").write_bytes(b"old")
        monkeypatch.setattr(fa, "_sync_dir_fn", lambda d: (_ for _ in ()).throw(PermissionError("perm")))
        if fa._runtime_goos == "win32":
            pytest.skip("POSIX-only")
        with pytest.raises(OSError, match="sync parent directory"):
            write_file_atomic(str(tmp_path / "out.txt"), b"new")

    def test_default_sync_dir_open_fail(self, monkeypatch):
        import os

        from dxrk.utils import filemerge_atomic as fa

        monkeypatch.setattr(os, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
        with pytest.raises(OSError, match="open parent directory"):
            fa._default_sync_dir("/nonexistent-xyz")


class TestFilemergeJson:
    def test_strip_comments_escaped_quote(self):
        assert strip_json_comments('{"a":"x\\"y"}') == '{"a":"x\\"y"}'

    def test_strip_comments_backslash(self):
        assert strip_json_comments('{"a":"x\\\\y"}') == '{"a":"x\\\\y"}'

    def test_strip_comments_bare_slash(self):
        assert strip_json_comments("{} /x") == "{} /x"

    def test_strip_comments_bare_slash_in_string_kept(self):
        assert strip_json_comments('{"a":"b/c"}') == '{"a":"b/c"}'

    def test_strip_commas_escapes(self):
        assert strip_trailing_commas('{"a":"x\\"y",}') == '{"a":"x\\"y"}'
        assert strip_trailing_commas('{"a":"x\\\\y",}') == '{"a":"x\\\\y"}'

    def test_strip_commas_keeps_valid_comma(self):
        assert strip_trailing_commas('{"a":1,"b":2}') == '{"a":1,"b":2}'
        assert strip_trailing_commas('{"a":1,}') == '{"a":1}'

    def test_strip_commas_trailing_comma_kept(self):
        assert strip_trailing_commas('{"a":1,') == '{"a":1,'

    def test_unmarshal_empty_and_non_object(self):
        assert unmarshal_json_object("") == {}
        with pytest.raises(TypeError):
            unmarshal_json_object("[1,2]")

    def test_merge_objects_recurses_into_new_dict(self):
        assert merge_objects({"x": 1}, {"n": {"a": 1}}) == {"x": 1, "n": {"a": 1}}

    def test_merge_tolerates_bad_base(self):
        out = merge_json_objects("{bad", '{"a":1}')
        assert '"a": 1' in out

    def test_merge_marshal_fail(self, monkeypatch):
        import json as json_mod

        monkeypatch.setattr(json_mod, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("nope")))
        with pytest.raises(ValueError, match="marshal merged json"):
            merge_json_objects('{"a":1}', '{"b":2}')


class TestFilemergeMarkdown:
    def test_persona_zone_mismatch_returns_content(self):
        content = "## Personality\nSenior Architect\n<!-- dxrk:s -->\nx\n<!-- /dxrk:s -->\n## Rules\n"
        assert strip_legacy_persona_block(content) == content

    def test_find_line_start_offset_overflow(self):
        assert find_line_start("ab", "b") == -1
        assert find_line_start("xxMARK", "MARK") == -1

    def test_remove_markers_consumes_crlf(self):
        assert remove_line_start_markers("M\r\nrest", "M") == "rest"

    def test_atl_begin_without_end_cleaned(self):
        out = strip_legacy_atl_block("head\n<!-- BEGIN:agent-teams-lite -->\norphan\n")
        assert "BEGIN" not in out
        assert "orphan" in out

    def test_atl_empty_block(self):
        assert strip_legacy_atl_block("<!-- BEGIN:agent-teams-lite -->\n<!-- END:agent-teams-lite -->") == ""

    def test_atl_before_empty_after_tail(self):
        out = strip_legacy_atl_block("<!-- BEGIN:agent-teams-lite -->\nmiddle\n<!-- END:agent-teams-lite -->\ntail")
        assert out == "tail"

    def test_atl_head_before_empty_after(self):
        out = strip_legacy_atl_block("head\n<!-- BEGIN:agent-teams-lite -->\nx\n<!-- END:agent-teams-lite -->")
        assert out == "head\n"

    def test_atl_collapses_blank_runs(self):
        assert strip_legacy_atl_block("a\n\n\n\nb") == "a\n\nb"

    def test_inject_remove_with_trailing_newline(self):
        existing = "head\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->\ntail"
        assert inject_markdown_section(existing, "s", "") == "head\ntail"

    def test_inject_remove_at_end(self):
        existing = "head\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->"
        assert inject_markdown_section(existing, "s", "") == "head\n"

    def test_inject_remove_at_start(self):
        existing = "<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->\ntail"
        assert inject_markdown_section(existing, "s", "") == "tail"

    def test_inject_remove_only_section(self):
        existing = "<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->"
        assert inject_markdown_section(existing, "s", "") == ""

    def test_inject_replace_without_trailing_newline(self):
        existing = "head\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->\ntail"
        out = inject_markdown_section(existing, "s", "new")
        assert "new\n<!-- /dxrk:s -->" in out

    def test_inject_replace_with_trailing_newline(self):
        existing = "head\n<!-- dxrk:s -->\nold\n<!-- /dxrk:s -->\ntail"
        out = inject_markdown_section(existing, "s", "new\n")
        assert "<!-- dxrk:s -->\nnew\n<!-- /dxrk:s -->" in out

    def test_inject_append_with_trailing_newline(self):
        out = inject_markdown_section("hello", "s", "x\n")
        assert out == "hello\n\n<!-- dxrk:s -->\nx\n<!-- /dxrk:s -->\n"

    def test_inject_empty_into_missing_returns_existing(self):
        assert inject_markdown_section("hello", "s", "") == "hello"
        assert inject_markdown_section("hello", "s", "") == "hello"

    def test_inject_append_without_trailing_newline(self):
        out = inject_markdown_section("hello", "s", "x")
        assert out == "hello\n\n<!-- dxrk:s -->\nx\n<!-- /dxrk:s -->\n"

    def test_inject_append_into_empty(self):
        out = inject_markdown_section("", "s", "x")
        assert out == "<!-- dxrk:s -->\nx\n<!-- /dxrk:s -->\n"


class TestFilemergeToml:
    def test_upsert_replaces_existing_block(self):
        content = '[mcp_servers.srv1]\ncommand = "old"\nargs = []\n\n[other]\nx = 1\n'
        out = upsert_codex_mcp_server_block(content, "srv1", "newcmd", ["a"])
        assert "newcmd" in out
        assert '"old"' not in out
        assert "[other]" in out

    def test_upsert_replaces_last_block(self):
        out = upsert_codex_mcp_server_block("[mcp_servers.srv1]", "srv1", "cmd", [])
        assert out == '[mcp_servers.srv1]\ncommand = "cmd"\nargs = []\n'

    def test_upsert_appends_to_nonempty(self):
        out = upsert_codex_mcp_server_block('title = "t"\n', "srv1", "cmd", [])
        assert out.startswith('title = "t"')
        assert "[mcp_servers.srv1]" in out

    def test_upsert_top_level_before_section(self):
        out = upsert_top_level_toml_string("[sec]\na = 1\n", "key", "v")
        assert out.index('key = "v"') < out.index("[sec]")


class TestFileopsCache:
    def test_invalidate_missing_is_noop(self):
        from dxrk.utils.fileops_cache import new_file_cache

        cache = new_file_cache(10, None)
        cache.set("/real", "data")
        cache.invalidate("ghost")
        assert cache.size() == 1

    def test_touch_missing_is_noop(self):
        from dxrk.utils.fileops_cache import new_file_cache

        cache = new_file_cache(10, None)
        cache.set("/real", "data")
        cache._touch_locked("ghost")
        assert cache.paths() == ["/real"]


class TestFileopsEdit:
    def test_extract_indent_empty(self):
        from dxrk.utils.fileops_edit import _extract_indent

        assert _extract_indent("", 0) == ""
        assert _extract_indent("    code", 4) == "    "


class TestFileopsPath:
    def test_resolve_path_empty_workdir(self):
        import os

        path, err = resolve_path("rel.txt", "")
        assert err is None
        assert path == os.path.join(os.getcwd(), "rel.txt")

    def test_resolve_path_explicit_workdir(self):
        path, err = resolve_path("rel.txt", "/wd")
        assert err is None
        assert path == "/wd/rel.txt"

    def test_safe_join_no_elems_raises(self):
        # os.path.join() requires at least one arg, so the len(elems)==0
        # guard is defensive-only (unreachable); zero-arg calls raise.
        with pytest.raises(TypeError):
            safe_join()

    def test_walk_child_error_propagates(self, tmp_path):
        import os

        from dxrk.utils.fileops_errors import FileopsError

        (tmp_path / "a.txt").write_text("x")

        def _fail_files(path, info, err):
            if os.path.isdir(path):
                return None
            return FileopsError("boom")

        result = walk_dir(str(tmp_path), _fail_files)
        assert isinstance(result, FileopsError)
        assert "boom" in str(result)

    def test_walk_skipdir_on_file_returns_none(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x")
        assert walk_dir(str(target), lambda p, i, e: _SkipDir()) is None

    def test_tmp_file_cleanup_missing_ok(self):
        name, cleanup, err = tmp_file(".x")
        assert err is None
        os.remove(name)
        cleanup()

    def test_dir_exists_missing(self, tmp_path):
        ok, err = dir_exists(str(tmp_path / "gone"))
        assert err is None
        assert ok is False


class TestFileopsRead:
    def test_read_image_without_pillow(self, tmp_path, monkeypatch):
        from dxrk.utils import fileops_read

        target = tmp_path / "img.png"
        target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        monkeypatch.setattr(fileops_read, "_PILImage", None)
        with pytest.raises(ImportError):
            fileops_read.read_image(str(target))


class TestHooksCircuit:
    def test_unknown_state_denies(self):
        from datetime import timedelta

        from dxrk.utils.hooks_circuit import new_circuit_breaker

        cb = new_circuit_breaker(1, 1, timedelta(seconds=30))
        cb._state = 99  # corrupt state: defensive fallback denies
        assert cb._allow_request() is False


class TestHooksModelConfig:
    def test_save_config_fdopen_fail_closes_and_raises(self, tmp_path, monkeypatch):
        import os as os_mod

        from dxrk.utils.hooks_model_config import default_config, save_config

        monkeypatch.setattr(os_mod, "fdopen", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fdopen boom")))
        monkeypatch.setattr(os_mod, "close", lambda *a, **k: (_ for _ in ()).throw(OSError("close down")))
        with pytest.raises(RuntimeError, match="fdopen boom"):
            save_config(str(tmp_path / "hooks.json"), default_config())


class TestHooksQueue:
    def test_worker_tolerates_empty_poll(self):
        import queue as queue_mod

        from dxrk.utils.hooks_queue import _SENTINEL, new_hook_queue

        q = new_hook_queue()
        calls = {"n": 0}

        class _FlakyQueue:
            def get(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise queue_mod.Empty()
                return _SENTINEL

        q._tasks = _FlakyQueue()  # type: ignore[assignment]
        q._worker()
        assert calls["n"] == 2


class TestImageCache:
    def test_get_expired_is_miss(self):
        from datetime import datetime, timedelta

        from dxrk.utils.image_cache import ImageCache
        from dxrk.utils.image_format import Format

        cache = ImageCache(max_size=10, max_age=timedelta(hours=1))
        cache.set("k", b"data", Format.PNG, 1, 1)
        cache._entries["k"].created_at = datetime.now() - timedelta(days=2)
        data, fmt, width, height, ok = cache.get("k")
        assert ok is False
        assert data is None
        assert fmt is Format.UNKNOWN

    def test_evict_lru_empty_is_noop(self):
        from dxrk.utils.image_cache import ImageCache

        ImageCache()._evict_lru()


class TestImageCodec:
    def test_pillow_missing_errors(self, monkeypatch):
        import io as io_mod

        from dxrk.utils import image_codec

        monkeypatch.setattr(image_codec, "_PILImage", None)
        with pytest.raises(ImportError):
            image_codec.decode(io_mod.BytesIO(b"x"))
        with pytest.raises(ImportError):
            image_codec.decode_config(io_mod.BytesIO(b"x"))
        with pytest.raises(ImportError):
            image_codec.encode(io_mod.BytesIO(), object(), image_codec.Format.PNG, 80)

    def test_from_base64_data_without_comma(self):
        from dxrk.utils import image_codec

        with pytest.raises(Exception):
            image_codec.from_base64("data:image/png")

    def test_decode_format_pillow_missing(self, monkeypatch):
        from dxrk.utils import image_codec

        monkeypatch.setattr(image_codec, "_PILImage", None)
        with pytest.raises(ImportError):
            image_codec.decode_format(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4)


class TestImagePdf:
    def _write(self, tmp_path, name, data):
        target = tmp_path / name
        target.write_bytes(data)
        return str(target)

    def test_extract_plain_stream(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "a.pdf", b"%PDF-1.4\n1 0 obj\nstream\nHello\nendstream\nendobj\n%%EOF")
        assert "Hello" in image_pdf.extract_text(path)

    def test_extract_cr_stream(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "b.pdf", b"%PDF-1.4\nstream\rX\nendstream\n%%EOF")
        assert "X" in image_pdf.extract_text(path)

    def test_extract_crlf_stream(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "c.pdf", b"%PDF-1.4\nstream\r\nY\nendstream\n%%EOF")
        assert "Y" in image_pdf.extract_text(path)

    def test_decode_backslash_and_octal(self):
        from dxrk.utils.image_pdf import _decode_stream

        assert _decode_stream(b"\\\\") == "\\"
        assert _decode_stream(b"\\101") == "A"
        assert _decode_stream(b"\\(") == "("

    def test_page_count_without_digits(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "d.pdf", b"%PDF-1.4\n/Count \n/Count 3\n%%EOF")
        assert image_pdf.get_page_count(path) == 3

    def test_page_count_from_bytes_error(self):
        from dxrk.utils.image_pdf import _page_count_from_bytes

        count, exc = _page_count_from_bytes(b"junk")
        assert count == 0
        assert exc is not None

    def test_metadata_not_pdf(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "e.bin", b"hello")
        with pytest.raises(image_pdf.PDFError):
            image_pdf.get_metadata(path)

    def test_metadata_partial_fields(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "f.pdf", b"%PDF-1.4\n/Title (Hello)\n/Count 1\n%%EOF")
        meta = image_pdf.get_metadata(path)
        assert meta.title == "(Hello)"
        assert meta.author == ""

    def test_metadata_unclosed_string(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "g.pdf", b"%PDF-1.4\n/Title (abc\n%%EOF")
        meta = image_pdf.get_metadata(path)
        assert meta.title == ""

    def test_metadata_field_without_parens(self, tmp_path):
        from dxrk.utils import image_pdf

        path = self._write(tmp_path, "h.pdf", b"%PDF-1.4\n/Title plain\n%%EOF")
        meta = image_pdf.get_metadata(path)
        assert meta.title == ""

    def test_find_end_of_string_nested(self):
        from dxrk.utils.image_pdf import _find_end_of_string

        assert _find_end_of_string(b"(a(b)c)", 0) == 6
        assert _find_end_of_string(b")abc", 0) == -1


class TestImageProcessor:
    def _img(self):
        from dxrk.utils.image_format import _PILImage

        assert _PILImage is not None
        return _PILImage.new("RGB", (4, 4), color="red")

    def test_none_image_ops_are_noop(self):
        from dxrk.utils.image_format import Format
        from dxrk.utils.image_processor import ImageProcessor

        proc = ImageProcessor(None, Format.PNG)  # type: ignore[arg-type]
        assert proc.resize(2, 2) is proc
        assert proc.crop(0, 0, 2, 2) is proc
        assert proc.rotate(0.5) is proc
        assert proc.grayscale() is proc
        assert proc.image() is None

    def test_pillow_missing_errors(self, monkeypatch):
        from dxrk.utils import image_processor as ip
        from dxrk.utils.image_format import Format

        monkeypatch.setattr(ip, "_PILImage", None)
        img = self._img()
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).resize(2, 2)
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).crop(0, 0, 2, 2)
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).rotate(0.5)
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).grayscale()
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).blur(1)
        with pytest.raises(ImportError):
            ip.ImageProcessor(img, Format.PNG).encode()

    def test_blur_degenerate_kernel_skips_pixels(self, monkeypatch):
        from dxrk.utils import image_processor as ip
        from dxrk.utils.image_format import Format

        monkeypatch.setattr(ip, "_gaussian_kernel", lambda r: [[0.0] * 3 for _ in range(3)])
        proc = ip.ImageProcessor(self._img(), Format.PNG).blur(1)
        assert proc.image() is not None
        assert proc.image().size == (4, 4)
        assert proc.image().getpixel((0, 0)) == (0, 0, 0, 0)

    def test_encode_without_image(self):
        from dxrk.utils.image_format import Format
        from dxrk.utils.image_processor import ImageProcessor

        with pytest.raises(ValueError, match="no image"):
            ImageProcessor(None, Format.PNG).encode()  # type: ignore[arg-type]


class TestImageTransform:
    def _rgba(self):
        from dxrk.utils.image_format import _PILImage

        assert _PILImage is not None
        return _PILImage.new("RGBA", (2, 2))

    def test_pillow_missing_errors(self, monkeypatch):
        from dxrk.utils import image_transform as it

        monkeypatch.setattr(it, "_PILImage", None)
        img = self._rgba()
        for fn in (it.resize, it.crop, it.to_rgba, it.to_nrgba, it.to_paletted, it.to_grayscale):
            with pytest.raises(ImportError):
                if fn is it.resize:
                    fn(img, 1, 1)
                elif fn is it.crop:
                    fn(img, 0, 0, 1, 1)
                else:
                    fn(img)

    def test_rgba_passthrough(self):
        from dxrk.utils import image_transform as it

        img = self._rgba()
        assert it.to_rgba(img) is img
        assert it.to_nrgba(img) is img

    def test_convert_non_rgba(self):
        from dxrk.utils import image_transform as it
        from dxrk.utils.image_format import _PILImage

        assert _PILImage is not None
        rgb = _PILImage.new("RGB", (2, 2))
        assert it.to_rgba(rgb).mode == "RGBA"
        assert it.to_nrgba(rgb).mode == "RGBA"


class TestMessagesFormat:
    def _msg_with_bare_tool_result(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Content, ContentType, Role

        msg = new_message(Role.RoleUser).text("hi").build()
        msg.contents.append(Content(type=ContentType.ContentToolResult))
        return msg

    def test_markdown_skips_bare_tool_result(self):
        from dxrk.utils.messages_format import FormatStyle, format_message

        out = format_message(self._msg_with_bare_tool_result(), FormatStyle.Markdown)
        assert "hi" in out

    def test_rich_skips_bare_tool_result(self):
        from dxrk.utils.messages_format import FormatStyle, format_message

        out = format_message(self._msg_with_bare_tool_result(), FormatStyle.Rich)
        assert "hi" in out

    def test_verbose_skips_bare_tool_result(self):
        from dxrk.utils.messages_format import FormatStyle, format_message

        out = format_message(self._msg_with_bare_tool_result(), FormatStyle.Verbose)
        assert "hi" in out

    def test_unknown_content_type_skipped(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_format import FormatStyle, format_message
        from dxrk.utils.messages_model import Content, Role

        # Forward-compat: blocks of an unknown kind are skipped, not fatal.
        # (A foreign enum with String() also exercises verbose's type label.)
        msg = new_message(Role.RoleUser).text("hi").build()
        msg.contents.append(Content(type=Role.RoleSystem))  # type: ignore[arg-type]
        assert "hi" in format_message(msg, FormatStyle.Markdown)
        assert "hi" in format_message(msg, FormatStyle.Rich)
        assert "hi" in format_message(msg, FormatStyle.Verbose)


class TestMessagesNormalize:
    def test_truncate_system_only(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_normalize import truncate_by_tokens

        sys_msg = new_message(Role.RoleSystem).text("be brief").build()
        assert truncate_by_tokens([sys_msg], 10_000) == [sys_msg]


class TestMessagesQuery:
    def _msgs(self):
        from datetime import UTC, datetime

        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import (
            Content,
            ContentType,
            Role,
            ToolUseData,
        )

        use = new_message(Role.RoleAssistant).text("run").build()
        use.contents.append(Content(type=ContentType.ContentToolUse, tool_use=ToolUseData(id="t1", name="sh")))
        use.timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        res = new_message(Role.RoleToolResult).text("out").build()
        res.timestamp = datetime(2024, 1, 2, tzinfo=UTC)
        return use, res

    def test_find_calls_without_result_index(self):
        from dxrk.utils.messages_query import find_tool_calls

        use, res = self._msgs()
        calls = find_tool_calls([use, res], "")
        assert len(calls) == 1
        assert calls[0].result is None

    def test_find_calls_skips_non_matching_content(self):
        from dxrk.utils.messages_model import Content, ContentType, ToolResultData
        from dxrk.utils.messages_query import find_tool_calls

        use, res = self._msgs()
        res.contents.append(Content(type=ContentType.ContentToolResult, tool_result=None))
        res.contents.append(
            Content(
                type=ContentType.ContentToolResult,
                tool_result=ToolResultData(tool_use_id="t1", content="ok"),
            )
        )
        calls = find_tool_calls([use, res], "")
        assert len(calls) == 1
        assert calls[0].result is not None
        assert calls[0].result.content == "ok"

    def test_stats_out_of_order_timestamps(self):
        from dxrk.utils.messages_query import get_conversation_stats

        use, res = self._msgs()
        stats = get_conversation_stats([use, res])
        assert stats.first_message_time == use.timestamp
        assert stats.last_message_time == res.timestamp


class TestMessagesWindow:
    def test_score_long_message_penalized(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import score_messages

        msg = new_message(Role.RoleUser).text("x" * 3000).build()
        scores = score_messages([msg])
        assert len(scores) == 1
        assert scores[0].score < 100 + 50 + 30

    def test_score_tool_result_text_content(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Content, ContentType, Role
        from dxrk.utils.messages_window import score_messages

        msg = new_message(Role.RoleToolResult).text("oops").build()
        msg.contents.append(Content(type=ContentType.ContentText, text="more"))
        assert len(score_messages([msg])) == 1

    def test_drop_oldest_all_system(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import ContextWindow

        s1 = new_message(Role.RoleSystem).text("a").build()
        s1.token_count = 6
        s2 = new_message(Role.RoleSystem).text("b").build()
        s2.token_count = 6
        small = new_message(Role.RoleSystem).text("hi").build()
        small.token_count = 1
        window = ContextWindow(messages=[s1, s2], token_count=12, max_tokens=10)
        window.add_message(small)
        assert window.truncated is True
        assert len(window.messages) == 2

    def test_drop_oldest_empty_is_noop(self):
        from dxrk.utils.messages_window import ContextWindow

        window = ContextWindow(messages=[], token_count=0, max_tokens=10)
        window._drop_oldest()
        assert window.messages == []

    def test_compact_by_importance_empty_is_noop(self):
        from dxrk.utils.messages_window import ContextWindow

        ContextWindow(messages=[], token_count=0, max_tokens=10)._compact_by_importance()

    def test_compact_recursive_huge_system_prompt(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import CompactStrategy, new_context_window

        window = new_context_window(10)
        window.set_system_prompt("x" * 100)
        small = new_message(Role.RoleUser).text("hi").build()
        window.messages.append(small)
        window._recount_tokens()
        window.compact(CompactStrategy.CompactRecursive)
        assert window.messages == []

    def test_compact_recursive_removes_lowest_first(self):
        from datetime import UTC, datetime

        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import CompactStrategy, ContextWindow

        old = new_message(Role.RoleUser).text("first").build()
        old.timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        new = new_message(Role.RoleToolResult).text("last").build()
        new.timestamp = datetime(2024, 1, 1, hour=2, tzinfo=UTC)
        window = ContextWindow(messages=[old, new], token_count=2, max_tokens=1)
        window.compact(CompactStrategy.CompactRecursive)
        assert window.messages == []
        assert window.truncated is True

    def test_compact_by_importance_tolerates_stale_scores(self, monkeypatch):
        from datetime import UTC, datetime

        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import ContextWindow, MessageScore

        msg = new_message(Role.RoleUser).text("hello world keeper").build()
        msg.id = "live-1"
        msg.timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        window = ContextWindow(messages=[msg], token_count=50, max_tokens=10)
        foreign = new_message(Role.RoleAssistant).text("ghost entry here").build()
        foreign.id = "ghost-1"
        foreign.timestamp = datetime(2025, 6, 1, tzinfo=UTC)
        monkeypatch.setattr(
            "dxrk.utils.messages_window.ScoreMessages",
            lambda msgs: [MessageScore(message=foreign, score=-999.0, reason="stale")],
        )
        window._compact_by_importance()
        assert window.messages == [msg]
        assert window.truncated is False

    def test_compact_recursive_tolerates_stale_scores(self, monkeypatch):
        from datetime import UTC, datetime

        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import ContextWindow, MessageScore

        msg = new_message(Role.RoleUser).text("live keeper message").build()
        msg.id = "live-2"
        msg.timestamp = datetime(2024, 1, 1, tzinfo=UTC)
        window = ContextWindow(messages=[msg], token_count=50, max_tokens=10)
        foreign = new_message(Role.RoleAssistant).text("ghost stale entry").build()
        foreign.id = "ghost-2"
        foreign.timestamp = datetime(2025, 6, 1, tzinfo=UTC)
        calls = {"n": 0}

        def _stale(msgs):
            calls["n"] += 1
            if calls["n"] > 1:
                window.token_count = 0
            return [MessageScore(message=foreign, score=-1.0, reason="stale")]

        monkeypatch.setattr("dxrk.utils.messages_window.ScoreMessages", _stale)
        window._compact_recursive()
        assert msg in window.messages

    def test_compact_recursive_exhausts_max_iters(self):
        from dxrk.utils.messages_builder import new_message
        from dxrk.utils.messages_model import Role
        from dxrk.utils.messages_window import ContextWindow

        msgs = []
        for i in range(15):
            m = new_message(Role.RoleUser).text(f"keeper message number {i} with padding").build()
            m.token_count = 100
            msgs.append(m)
        window = ContextWindow(messages=list(msgs), token_count=1500, max_tokens=10)
        window._compact_recursive()
        assert len(window.messages) == 5
        assert window.truncated is True


class TestPermissionsAudit:
    def test_parse_risk_levels(self):
        from dxrk.utils.permissions_audit import _parse_risk_level
        from dxrk.utils.permissions_classify import RiskLevel

        assert _parse_risk_level("low") is RiskLevel.Low
        assert _parse_risk_level("medium") is RiskLevel.Medium
        assert _parse_risk_level("high") is RiskLevel.High
        assert _parse_risk_level("critical") is RiskLevel.Critical
        assert _parse_risk_level("bogus") is RiskLevel.Low

    def test_export_write_failures(self):
        from dxrk.utils.permissions_audit import AuditEntry, new_audit_log

        class _Boom:
            def write(self, s):
                raise OSError("disk down")

        log = new_audit_log(10)
        log.log(AuditEntry(tool="Bash", resource="rm -rf /"))
        assert log.export_json(_Boom()) is not None  # type: ignore[arg-type]
        assert log.export_csv(_Boom()) is not None  # type: ignore[arg-type]


class TestPermissionsCache:
    def test_touch_and_remove_missing(self):
        from datetime import timedelta

        from dxrk.utils.permissions_cache import CacheEntry, new_permission_cache
        from dxrk.utils.permissions_model import _now

        cache = new_permission_cache(timedelta(minutes=5))
        cache.set("a", CacheEntry(key="a"))
        cache._touch_locked("ghost")
        _, ok = cache.get("a")
        assert ok is True
        cache.invalidate("ghost")
        cache._entries["k"] = CacheEntry(key="k")
        cache._remove_locked("k")
        assert "k" not in cache._entries
        assert _now() is not None

    def test_evict_empty_is_noop(self):
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache

        new_permission_cache(timedelta(minutes=5))._evict_oldest_locked()

    def test_set_inherits_existing_expiry(self):
        from datetime import timedelta

        from dxrk.utils.permissions_cache import CacheEntry, new_permission_cache
        from dxrk.utils.permissions_model import _now

        cache = new_permission_cache(timedelta(minutes=5))
        first = CacheEntry(key="k", expiry=_now() + timedelta(hours=1))
        cache.set("k", first)
        cache.set("k", CacheEntry(key="k"))
        cache.set("k", CacheEntry(key="k"))
        got, ok = cache.get("k")
        assert ok is True
        assert got is not None
        assert got.expiry == first.expiry
        replacement = CacheEntry(key="k", expiry=_now() + timedelta(hours=2))
        cache.set("k", replacement)
        got2, ok2 = cache.get("k")
        assert ok2 is True
        assert got2 is not None
        assert got2.expiry == replacement.expiry

    def _write(self, tmp_path, name, text):
        target = tmp_path / name
        target.write_text(text)
        return str(target)

    def test_load_entries_not_list(self, tmp_path):
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache

        path = self._write(tmp_path, "c.json", '{"entries": {}}')
        err = new_permission_cache(timedelta(minutes=5)).load_from_disk(path)
        assert err is not None

    def test_load_skips_non_dict_entry(self, tmp_path):
        import json as json_mod
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache
        from dxrk.utils.permissions_model import _go_time_fmt, _now

        good = {
            "key": "k",
            "action": 0,
            "expiry": _go_time_fmt(_now() + timedelta(hours=1)),
            "timestamp": _go_time_fmt(_now()),
        }
        path = self._write(tmp_path, "c.json", json_mod.dumps({"entries": [42, good]}))
        cache = new_permission_cache(timedelta(minutes=5))
        assert cache.load_from_disk(path) is None
        _, ok = cache.get("k")
        assert ok is True

    def test_load_skips_bad_action(self, tmp_path):
        import json as json_mod
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache

        bad = {"key": "k", "action": "bogus", "expiry": "", "timestamp": ""}
        path = self._write(tmp_path, "c.json", json_mod.dumps({"entries": [bad]}))
        cache = new_permission_cache(timedelta(minutes=5))
        assert cache.load_from_disk(path) is None
        assert cache.size() == 0

    def test_load_skips_expired(self, tmp_path):
        import json as json_mod
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache

        old = {"key": "k", "action": 0, "expiry": "2000-01-01T00:00:00Z", "timestamp": ""}
        path = self._write(tmp_path, "c.json", json_mod.dumps({"entries": [old]}))
        cache = new_permission_cache(timedelta(minutes=5))
        assert cache.load_from_disk(path) is None
        assert cache.size() == 0

    def test_load_evicts_when_full(self, tmp_path):
        import json as json_mod
        from datetime import timedelta

        from dxrk.utils.permissions_cache import new_permission_cache
        from dxrk.utils.permissions_model import _go_time_fmt, _now

        def _entry(k):
            return {
                "key": k,
                "action": 0,
                "expiry": _go_time_fmt(_now() + timedelta(hours=1)),
                "timestamp": _go_time_fmt(_now()),
            }

        path = self._write(tmp_path, "c.json", json_mod.dumps({"entries": [_entry("a"), _entry("b")]}))
        cache = new_permission_cache(timedelta(minutes=5), max_size=1)
        assert cache.load_from_disk(path) is None
        assert cache.size() == 1


class TestPermissionsEngine:
    def test_match_glob_trailing_star(self):
        from dxrk.utils.permissions_engine import _match_glob

        assert _match_glob("foo*", "foobar") is True
        assert _match_glob("foobar*", "foobar") is True
        assert _match_glob("foo*", "bar") is False

    def test_remove_second_rule(self):
        from dxrk.utils.permissions_engine import new_policy_engine
        from dxrk.utils.permissions_model import Policy, Rule

        engine = new_policy_engine(Policy(rules=[Rule(id="a"), Rule(id="b")]))
        assert engine.remove_rule("b") is True
        assert [r.id for r in engine.get_rules()] == ["a"]

    def test_eval_regex_invalid(self):
        from dxrk.utils.permissions_engine import new_policy_engine
        from dxrk.utils.permissions_model import Condition, EvalContext, Policy, Rule

        rule = Rule(
            id="r",
            subject="*",
            resource="*",
            conditions=[Condition(field="tool", operator="regex", value="[")],
        )
        engine = new_policy_engine(Policy(rules=[rule]))
        action, _, _ = engine.evaluate(EvalContext(tool_name="Bash", user="u"))
        assert action == engine.policy().default_action


class TestPermissionsModel:
    def test_naive_time_formats(self):
        from datetime import datetime

        from dxrk.utils.permissions_model import _go_time_fmt, _rfc3339

        assert _go_time_fmt(datetime(2024, 1, 1)) == "2024-01-01T00:00:00Z"
        assert _rfc3339(datetime(2024, 1, 1)) == "2024-01-01T00:00:00Z"

    def test_parse_go_time_invalid(self):
        from dxrk.utils.permissions_model import _ZERO_TIME, _parse_go_time

        assert _parse_go_time("bogus") == _ZERO_TIME

    def test_as_int_default(self):
        from dxrk.utils.permissions_model import _as_int

        assert _as_int("x") == 0
        assert _as_int("x", 5) == 5
        assert _as_int(3) == 3

    def test_field_value_metadata_miss(self):
        from dxrk.utils.permissions_model import EvalContext

        assert EvalContext(metadata={"a": "b"}).fieldValue("zzz") == ""
        assert EvalContext(metadata={"a": "b"}).fieldValue("a") == "b"


class TestPermissionsPolicy:
    def test_unmarshal_empty_and_foreign_conditions(self):
        import json as json_mod

        from dxrk.utils.permissions_policy import unmarshal_policy_json

        policy, err = unmarshal_policy_json(json_mod.dumps({"rules": [{"id": "r", "conditions": []}]}))
        assert err is None
        assert policy is not None
        assert policy.rules[0].conditions == []
        policy_nl, err_nl = unmarshal_policy_json(json_mod.dumps({"rules": [{"id": "r", "conditions": "x"}]}))
        assert err_nl is None
        assert policy_nl is not None
        assert policy_nl.rules[0].conditions == []
        policy2, err2 = unmarshal_policy_json(
            json_mod.dumps(
                {
                    "rules": [
                        {
                            "id": "r",
                            "conditions": [42, {"field": "tool", "operator": "eq", "value": "Bash"}],
                        }
                    ]
                }
            )
        )
        assert err2 is None
        assert policy2 is not None
        assert len(policy2.rules[0].conditions) == 1

    def test_remove_missing_layer_is_noop(self):
        from dxrk.utils.permissions_policy import Layer, new_layered_policy

        lp = new_layered_policy()
        before = len(lp.get_layers())
        lp.remove_layer(Layer.LayerUser)
        assert len(lp.get_layers()) == before

    def test_project_policy_listdir_not_dir(self, tmp_path):
        from dxrk.utils.permissions_policy import load_project_policy

        (tmp_path / ".dxrk").write_text("not a dir")
        policy, err = load_project_policy(str(tmp_path))
        assert policy is None
        assert err is not None

    def test_user_policy_is_dir(self, tmp_path):
        from dxrk.utils.permissions_policy import load_user_policy

        target = tmp_path / "permissions" / "policy.json"
        target.parent.mkdir(parents=True)
        target.mkdir()
        policy, err = load_user_policy(str(tmp_path))
        assert policy is None
        assert err is not None


class TestSessionRestore:
    def _stored(self, tmp_path, version=2):
        from dxrk.utils.session_model import new_session
        from dxrk.utils.session_storage import MemoryStorage

        store = MemoryStorage()
        session = new_session()
        session.version = version
        store.save(session)
        return store, session

    def test_migration_failure_passes_through(self, tmp_path, monkeypatch):
        from dxrk.utils import session_restore
        from dxrk.utils.session_model import SessionError

        store, session = self._stored(tmp_path, version=1)
        monkeypatch.setattr(
            session_restore,
            "migrate_to_current",
            lambda raw: (_ for _ in ()).throw(SessionError("nope")),
        )
        out = session_restore.restore_session(session.id, store)
        assert out.version == 1

    def test_cleanup_expired_save_fail(self):
        from datetime import timedelta

        from dxrk.utils.session_model import Session, SessionStatus, now
        from dxrk.utils.session_restore import cleanup_expired
        from dxrk.utils.session_storage import SessionSummary

        old = now() - timedelta(days=30)
        session = Session(id="s1", status=SessionStatus.Active, created_at=old, updated_at=old)

        class _FailSave:
            def list(self, opts=None):
                return [SessionSummary(id="s1")]

            def load(self, id):
                return session

            def save(self, s):
                raise_session_error()

            def delete(self, id):
                pass

            def exists(self, id):
                return True

        def raise_session_error():
            from dxrk.utils.session_model import SessionError

            raise SessionError("disk down")

        assert cleanup_expired(_FailSave(), timedelta(hours=1)) == 0

    def test_cleanup_unknown_status_archives(self):
        from datetime import timedelta

        from dxrk.utils.session_model import Session, SessionStatus, now
        from dxrk.utils.session_restore import cleanup_expired
        from dxrk.utils.session_storage import SessionSummary

        old = now() - timedelta(days=30)
        session = Session(id="s1", status=SessionStatus.Active, created_at=old, updated_at=old)
        session.status = 99  # unknown status from a newer writer
        saved = {}

        class _Store:
            def list(self, opts=None):
                return [SessionSummary(id="s1")]

            def load(self, id):
                return session

            def save(self, s):
                saved["status"] = s.status

            def delete(self, id):
                pass

            def exists(self, id):
                return True

        assert cleanup_expired(_Store(), timedelta(hours=1)) == 1
        assert saved["status"] == SessionStatus.Archived

    def test_cleanup_archive_save_fail(self):
        from datetime import timedelta

        from dxrk.utils.session_model import Session, SessionError, SessionStatus, now
        from dxrk.utils.session_restore import cleanup_expired
        from dxrk.utils.session_storage import SessionSummary

        old = now() - timedelta(days=30)
        session = Session(id="s1", status=SessionStatus.Active, created_at=old, updated_at=old)
        session.status = 99

        class _FailSave:
            def list(self, opts=None):
                return [SessionSummary(id="s1")]

            def load(self, id):
                return session

            def save(self, s):
                raise SessionError("disk down")

            def delete(self, id):
                pass

            def exists(self, id):
                return True

        assert cleanup_expired(_FailSave(), timedelta(hours=1)) == 0


class TestSessionStorage:
    def test_fsync_parent_variants(self, monkeypatch):
        import os

        from dxrk.utils.session_storage import _fsync_parent

        _fsync_parent("")
        _fsync_parent("/nonexistent-dir-xyz-abc")
        monkeypatch.setattr(os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("io")))
        _fsync_parent(os.getcwd())
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError("c")))
        _fsync_parent(os.getcwd())

    def test_atomic_write_failures(self, tmp_path, monkeypatch):
        import os

        from dxrk.utils.session_storage import _atomic_write_bytes

        target = tmp_path / "f.bin"
        monkeypatch.setattr(os, "write", lambda fd, data: (_ for _ in ()).throw(OSError("w")))
        with pytest.raises(OSError, match="write temp"):
            _atomic_write_bytes(str(target), b"data")

    def test_atomic_write_close_chmod_ok(self, tmp_path, monkeypatch):
        import os

        from dxrk.utils.session_storage import _atomic_write_bytes

        target = tmp_path / "f.bin"
        monkeypatch.setattr(os, "close", lambda fd: (_ for _ in ()).throw(OSError("c")))
        _atomic_write_bytes(str(target), b"data")
        assert target.read_bytes() == b"data"
        monkeypatch.undo()
        monkeypatch.setattr(os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("c")))
        _atomic_write_bytes(str(target), b"data2")
        assert target.read_bytes() == b"data2"

    def test_parse_non_object(self):
        from dxrk.utils.session_model import SessionError
        from dxrk.utils.session_storage import _parse_session_payload

        with pytest.raises(SessionError, match="expected object"):
            _parse_session_payload("[1,2]")

    def test_storage_protocol_defaults(self):
        from dxrk.utils.session_model import new_session
        from dxrk.utils.session_storage import Storage

        # Protocol bodies are bare `...` no-ops; call them unbound.
        session = new_session()
        assert Storage.save(None, session) is None  # type: ignore[arg-type]
        assert Storage.load(None, "x") is None  # type: ignore[arg-type]
        assert Storage.delete(None, "x") is None  # type: ignore[arg-type]
        assert Storage.list(None, None) is None  # type: ignore[arg-type]
        assert Storage.exists(None, "x") is None  # type: ignore[arg-type]

    def test_rebuild_skips_non_sessions(self, tmp_path):
        from dxrk.utils.session_model import new_session
        from dxrk.utils.session_storage import FileStorage

        store = FileStorage(str(tmp_path / "s"))
        session = new_session()
        store.save(session)
        (tmp_path / "s" / "sub").mkdir()
        (tmp_path / "s" / "notes.txt").write_text("hi")
        (tmp_path / "s" / ".json").write_text("[]")
        (tmp_path / "s" / "torn.json.gz").write_bytes(b"not gzip at all")
        (tmp_path / "s" / ".index.json").unlink()
        healed = FileStorage(str(tmp_path / "s"))
        assert session.id in healed.index
        assert "torn" not in healed.index

    def test_rebuild_skips_unreadable(self, tmp_path, monkeypatch):
        from dxrk.utils.session_storage import FileStorage

        (tmp_path / "bad.json").write_text("{}")
        monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
        store = FileStorage(str(tmp_path))
        assert store.index == {}

    def test_write_index_marshal_fail(self, tmp_path, monkeypatch):
        import json as json_mod

        from dxrk.utils.session_model import SessionError, new_session
        from dxrk.utils.session_storage import FileStorage

        store = FileStorage(str(tmp_path / "s"))
        store.save(new_session())
        monkeypatch.setattr(json_mod, "dumps", lambda *a, **k: (_ for _ in ()).throw(TypeError("nope")))
        with pytest.raises(SessionError):
            store._write_index()

    def test_sqlite_ts_invalid(self):
        from dxrk.utils.session_storage import _sqlite_ts

        assert _sqlite_ts("bogus") is None
        assert _sqlite_ts("") is None

    def test_sqlite_default_home(self, tmp_path, monkeypatch):
        from dxrk.utils.session_storage import SQLiteSessionStorage

        monkeypatch.setenv("HOME", str(tmp_path))
        store = SQLiteSessionStorage("")
        try:
            assert store.base_dir.endswith(os.path.join(".dxrk", "sessions"))
        finally:
            store.close()

    def test_sqlite_connect_fail(self, tmp_path, monkeypatch):
        import sqlite3

        from dxrk.utils.session_model import SessionError
        from dxrk.utils.session_storage import SQLiteSessionStorage

        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(sqlite3.Error("down")))
        with pytest.raises(SessionError, match="open sqlite store"):
            SQLiteSessionStorage(str(tmp_path))

    def test_sqlite_init_fail(self, tmp_path, monkeypatch):
        import sqlite3

        from dxrk.utils.session_model import SessionError
        from dxrk.utils.session_storage import SQLiteSessionStorage

        class _BadConn:
            def execute(self, *a, **k):
                raise sqlite3.Error("pragma down")

            def close(self):
                pass

        monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: _BadConn())
        with pytest.raises(SessionError, match="init sqlite store"):
            SQLiteSessionStorage(str(tmp_path))

    def test_sqlite_chmod_fail_ok(self, tmp_path, monkeypatch):
        import os

        from dxrk.utils.session_model import new_session
        from dxrk.utils.session_storage import SQLiteSessionStorage

        monkeypatch.setattr(os, "chmod", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
        store = SQLiteSessionStorage(str(tmp_path))
        try:
            session = new_session()
            store.save(session)
            assert store.exists(session.id) is True
        finally:
            store.close()

    def test_sqlite_save_marshal_fail(self, tmp_path):
        from dxrk.utils.session_model import SessionError, new_session
        from dxrk.utils.session_storage import SQLiteSessionStorage

        store = SQLiteSessionStorage(str(tmp_path))
        try:
            session = new_session()
            session.metadata["k"] = object()  # type: ignore[assignment]
            with pytest.raises(SessionError, match="marshal session"):
                store.save(session)
        finally:
            store.close()

    def test_sqlite_upsert_tags_marshal_fail(self, tmp_path):
        from dxrk.utils.session_model import SessionError, new_session
        from dxrk.utils.session_storage import SQLiteSessionStorage

        store = SQLiteSessionStorage(str(tmp_path))
        try:
            session = new_session()
            session.tags.append(object())  # type: ignore[arg-type]
            with pytest.raises(SessionError, match="marshal session"):
                store._upsert_row(session, '{"ok": true}')
        finally:
            store.close()

    def test_sqlite_closed_conn_errors(self, tmp_path):
        from dxrk.utils.session_model import SessionError, new_session
        from dxrk.utils.session_storage import SQLiteSessionStorage

        store = SQLiteSessionStorage(str(tmp_path))
        session = new_session()
        store.save(session)
        store.close()
        with pytest.raises(SessionError, match="save session"):
            store.save(session)
        with pytest.raises(SessionError, match="read session"):
            store.load(session.id)
        with pytest.raises(SessionError, match="delete session"):
            store.delete(session.id)
        with pytest.raises(SessionError, match="read session"):
            store.exists(session.id)
        with pytest.raises(SessionError, match="list sessions"):
            store.list(None)

    def test_sqlite_status_from_row_invalid(self):
        from dxrk.utils.session_model import SessionStatus
        from dxrk.utils.session_storage import SQLiteSessionStorage

        assert SQLiteSessionStorage._status_from_row("bogus") is SessionStatus.Active

    def test_sqlite_close_swallows_error(self, tmp_path):
        import sqlite3

        from dxrk.utils.session_storage import SQLiteSessionStorage

        store = SQLiteSessionStorage(str(tmp_path))

        class _CloseBoom:
            def close(self):
                raise sqlite3.Error("busy")

        store._conn = _CloseBoom()  # type: ignore[assignment]
        store.close()

    def test_migrate_listdir_fail(self, tmp_path, monkeypatch):
        import os

        from dxrk.utils.session_model import SessionError
        from dxrk.utils.session_storage import SQLiteSessionStorage, migrate_json_dir_to_sqlite

        target = SQLiteSessionStorage(str(tmp_path / "t"))
        try:
            monkeypatch.setattr(os, "listdir", lambda p: (_ for _ in ()).throw(OSError("denied")))
            with pytest.raises(SessionError, match="read session dir"):
                migrate_json_dir_to_sqlite(str(tmp_path / "s"), target)
        finally:
            target.close()

    def test_migrate_skips_and_pairs(self, tmp_path):
        import gzip
        import json as json_mod

        from dxrk.utils.session_codec import _session_to_dict
        from dxrk.utils.session_model import new_session
        from dxrk.utils.session_storage import (
            FileStorage,
            SQLiteSessionStorage,
            migrate_json_dir_to_sqlite,
        )

        src = FileStorage(str(tmp_path / "s"))
        session = new_session()
        src.save(session)
        raw = json_mod.dumps(_session_to_dict(session))
        with gzip.open(tmp_path / "s" / f"{session.id}.json.gz", "wt", encoding="utf-8") as f:
            f.write(raw)
        (tmp_path / "s" / "sub").mkdir()
        (tmp_path / "s" / "notes.txt").write_text("hi")
        (tmp_path / "s" / ".json").write_text(raw)
        target = SQLiteSessionStorage(str(tmp_path / "t"))
        try:
            result = migrate_json_dir_to_sqlite(str(tmp_path / "s"), target)
            assert result.imported == 1
            assert result.skipped == 0
            assert target.exists(session.id) is True
        finally:
            target.close()

    def test_migrate_marshal_fail(self, tmp_path, monkeypatch):
        from dxrk.utils import session_storage as storage_mod
        from dxrk.utils.session_model import SessionError, new_session
        from dxrk.utils.session_storage import (
            FileStorage,
            SQLiteSessionStorage,
            migrate_json_dir_to_sqlite,
        )

        src = FileStorage(str(tmp_path / "s"))
        src.save(new_session())
        monkeypatch.setattr(storage_mod, "_session_to_dict", lambda s: {"bad": object()})
        target = SQLiteSessionStorage(str(tmp_path / "t"))
        try:
            with pytest.raises(SessionError, match="marshal session"):
                migrate_json_dir_to_sqlite(str(tmp_path / "s"), target)
        finally:
            target.close()

    def test_validate_session_id_realpath_escape(self, tmp_path, monkeypatch):
        import os

        from dxrk.utils.session_model import SessionError
        from dxrk.utils.session_storage import _validate_session_id

        base = str(tmp_path / "base")
        os.makedirs(base, exist_ok=True)
        real_realpath = os.path.realpath

        def _fake_realpath(p):
            if p.endswith(".json"):
                return "/evil/outside.json"
            return real_realpath(p)

        monkeypatch.setattr(os.path, "realpath", _fake_realpath)
        with pytest.raises(SessionError, match="invalid session id"):
            _validate_session_id(base, "abc123")


class TestSwarmEvents:
    def test_publish_overflow_drops_and_counts(self):
        from dxrk.utils.swarm_events import new_event_bus
        from dxrk.utils.swarm_model import SwarmEvent, SwarmEventType

        bus = new_event_bus()
        for _ in range(1030):
            bus.publish(SwarmEvent(type=SwarmEventType.EventTaskCompleted))
        assert bus.dropped_count() == 6

    def test_unsubscribe_typed_and_all(self):
        from dxrk.utils.swarm_events import new_event_bus
        from dxrk.utils.swarm_model import SwarmEventType

        bus = new_event_bus()
        seen: list[str] = []
        handler = lambda e: seen.append("x")  # noqa: E731
        other = lambda e: seen.append("y")  # noqa: E731
        bus.subscribe(SwarmEventType.EventTaskCompleted, handler)
        assert bus.unsubscribe(SwarmEventType.EventTaskCompleted, handler) is True
        bus.subscribe_all(handler)
        assert bus.unsubscribe(SwarmEventType.EventTaskStarted, handler) is True
        bus.subscribe_all(handler)
        assert bus.unsubscribe(SwarmEventType.EventTaskStarted, other) is False

    def test_double_unsubscribe_is_idempotent(self):
        from dxrk.utils.swarm_events import new_event_bus

        bus = new_event_bus()
        handler = lambda e: None  # noqa: E731
        other = lambda e: None  # noqa: E731
        unsub = bus.subscribe_all(handler)
        unsub()
        bus.subscribe_all(other)
        unsub()
        assert bus.len() == 1


class TestSwarmCoord:
    def _coord(self, store=None):
        from dxrk.utils.swarm_coord import CoordinatorConfig, new_swarm_coordinator
        from dxrk.utils.swarm_model import default_swarm_config
        from dxrk.utils.swarm_registry import new_backend_registry

        reg = new_backend_registry(default_swarm_config(), None)
        return new_swarm_coordinator(reg, CoordinatorConfig(), store)

    def test_failing_store_swallowed(self):
        from dxrk.utils.swarm_model import Task, TaskResult

        class _FailStore:
            def RecordTask(self, task):
                raise RuntimeError("disk down")

            def RecordResult(self, result):
                raise RuntimeError("disk down")

        coord = self._coord(_FailStore())
        result = TaskResult(task_id="t1", backend_id="b1", session_id="s1")
        coord._handle_task_result(result)
        assert coord._results["t1"] is result
        task = Task(id="t2", max_retries=0)
        assert coord.submit_task(task) is None
        assert task.max_retries == 3

    def test_submit_keeps_explicit_retries(self):
        from dxrk.utils.swarm_model import Task

        coord = self._coord()
        task = Task(id="t3", max_retries=5)
        assert coord.submit_task(task) is None
        assert task.max_retries == 5

    def test_reschedule_retryable_task(self):
        from dxrk.utils.swarm_model import Task

        class _FailStore:
            def RecordTask(self, task):
                raise RuntimeError("disk down")

            def RecordResult(self, result):
                raise RuntimeError("disk down")

        coord = self._coord(_FailStore())
        task = Task(id="t4", session_id="s", max_retries=3)
        task.assign("b9")
        coord._tasks["t4"] = task
        coord._reschedule_tasks("b9")
        assert task.retries == 1
        assert task.assigned_backend == ""

    def test_reschedule_skips_exhausted_and_full_queue(self):
        from dxrk.utils.swarm_model import Task

        coord = self._coord()
        stuck = Task(id="stuck", session_id="s", max_retries=1)
        stuck.retries = 1
        stuck.assign("b9")
        coord._tasks["stuck"] = stuck
        retryable = Task(id="retry", session_id="s", max_retries=3)
        retryable.assign("b9")
        coord._tasks["retry"] = retryable
        for i in range(100):
            coord._scheduler._task_queue.put_nowait(Task(id=f"fill-{i}"))
        coord._reschedule_tasks("b9")
        assert stuck.retries == 1
        assert retryable.retries == 1
        assert coord._scheduler._task_queue.qsize() == 100

    def test_session_summary_from_store(self):
        class _SummaryStore:
            def RecordTask(self, task):
                pass

            def RecordResult(self, result):
                pass

            def SessionSummary(self, sid):
                return {"submitted": 2, "completed": 1, "in_flight": 1}

            def SessionSummaryText(self, sid):
                return f"session {sid}: custom"

        coord = self._coord(_SummaryStore())
        assert coord.session_summary("s9") == {"submitted": 2, "completed": 1, "in_flight": 1}
        assert coord.session_summary_text("s9") == "session s9: custom"

    def test_get_task_result_paths(self):
        from dxrk.utils.swarm_model import ErrTaskNotFound, TaskResult

        coord = self._coord()
        res, err = coord.get_task_result(None, "nope")
        assert res is None
        assert err is ErrTaskNotFound
        cached = TaskResult(task_id="t1", session_id="s")
        coord._results["t1"] = cached
        res, err = coord.get_task_result(None, "t1")
        assert res is cached
        assert err is None
        drained = TaskResult(task_id="t9", session_id="s")
        coord._scheduler.results().put_nowait(drained)
        res, err = coord.get_task_result(None, "t9")
        assert res is not None
        assert res.task_id == "t9"
        assert err is None

    def test_session_summary_in_memory(self):
        from dxrk.utils.swarm_model import Task, TaskResult

        coord = self._coord()
        coord._tasks["a"] = Task(id="a", session_id="s1")
        coord._results["a"] = TaskResult(task_id="a", session_id="s1")
        assert coord.session_summary("s1") == {"submitted": 1, "completed": 1, "in_flight": 0}
        text = coord.session_summary_text("s1")
        assert "s1" in text
        assert "1/1" in text


class TestSwarmSchedule:
    def _sched(self, **kwargs):
        from datetime import timedelta

        from dxrk.utils.swarm_model import default_swarm_config
        from dxrk.utils.swarm_registry import new_backend_registry
        from dxrk.utils.swarm_schedule import SchedulerConfig, new_task_scheduler

        reg = new_backend_registry(default_swarm_config(), None)
        cfg = SchedulerConfig(
            max_concurrent_tasks=2,
            queue_size=10,
            task_timeout=timedelta(seconds=5),
            retry_attempts=1,
            retry_delay=timedelta(0),
        )
        return reg, new_task_scheduler(reg, cfg, **kwargs)

    def _backend(self, reg, name="b1", capacity=10, capabilities=None):
        from dxrk.utils.swarm_model import Backend

        backend = Backend(name=name, capacity=capacity, capabilities=capabilities or {})
        assert reg.register(None, backend) is None
        return backend

    def test_dispatch_worker_queue_full(self):
        import queue as queue_mod

        from dxrk.utils.swarm_model import Task
        from dxrk.utils.swarm_schedule import _Worker

        reg, sched = self._sched()
        self._backend(reg)

        class _FullRace:
            def qsize(self):
                return 0

            def full(self):
                return False

            def put_nowait(self, task):
                raise queue_mod.Full()

        sched._workers["w-race"] = _Worker(id="w-race", tasks=_FullRace(), results=sched.results())  # type: ignore[arg-type]
        task = Task(id="tfull")
        sched._dispatch_task(task)
        assert task.error == "worker queue full"
        assert sched.results().get_nowait().task_id == "tfull"

    def test_select_worker_qsize_fallback(self):
        from dxrk.utils.swarm_schedule import _Worker

        _, sched = self._sched()

        class _QBoom:
            def qsize(self):
                raise NotImplementedError("no qsize")

            def full(self):
                return False

        worker = _Worker(id="w2", tasks=_QBoom(), results=sched.results())  # type: ignore[arg-type]
        sched._workers["w2"] = worker
        assert sched._select_worker() is worker

    def test_select_least_loaded_no_match(self):
        from dxrk.utils.swarm_model import Backend, BackendStatus, Task

        _, sched = self._sched()
        gpu = Backend(name="gpu", capacity=4, capabilities={"gpu": 8})
        gpu.set_status(BackendStatus.StatusHealthy)
        task = Task(id="x", required_capabilities={"tpu": 1})
        assert sched._select_backend_least_loaded([gpu], task) is None

    def test_select_least_loaded_prefers_lower(self):
        from dxrk.utils.swarm_model import Backend, BackendStatus, Task

        _, sched = self._sched()
        low = Backend(name="low", capacity=10)
        low.set_status(BackendStatus.StatusHealthy)
        high = Backend(name="high", capacity=10)
        high.set_status(BackendStatus.StatusHealthy)
        high.load = 5
        task = Task(id="x")
        assert sched._select_backend_least_loaded([low, high], task) is low

    def test_select_work_stealing_prefers_idle(self):
        from dxrk.utils.swarm_model import Backend, Task

        _, sched = self._sched()
        busy = Backend(name="b1", capacity=10)
        busy.load = 9
        idle = Backend(name="b2", capacity=10)
        task = Task(id="y")
        assert sched._select_backend_work_stealing([busy, idle], task) is idle
        assert sched._select_backend_work_stealing([idle, busy], task) is idle

    def test_effective_timeout_prefers_task(self):
        from datetime import timedelta

        from dxrk.utils.swarm_model import Task

        _, sched = self._sched()
        assert sched._effective_timeout(Task(id="z", timeout=timedelta(seconds=30))) == 30.0

    def test_run_task_timeout(self):
        import time
        from datetime import timedelta

        from dxrk.utils.swarm_model import Task
        from dxrk.utils.swarm_schedule import _Worker

        _, sched = self._sched(handler=lambda task: time.sleep(0.3))
        try:
            task = Task(id="to", timeout=timedelta(milliseconds=1))
            result = sched._run_task(_Worker(id="w"), task)
            assert "deadline" in task.error
            assert result.metrics.get("timeout") == 1.0
        finally:
            sched.stop()

    def test_run_task_handler_raises(self):
        from dxrk.utils.swarm_model import Task
        from dxrk.utils.swarm_schedule import _Worker

        def _boom(task):
            raise ValueError("handler down")

        _, sched = self._sched(handler=_boom)
        try:
            task = Task(id="bad")
            result = sched._run_task(_Worker(id="w"), task)
            assert task.error == "handler down"
            assert result.metrics.get("error") == 1.0
        finally:
            sched.stop()

    def test_run_task_executor_shutdown(self):
        from dxrk.utils.swarm_model import Task
        from dxrk.utils.swarm_schedule import _Worker

        _, sched = self._sched(handler=lambda task: b"ok")
        sched._exec.shutdown(wait=True)
        task = Task(id="sh")
        result = sched._run_task(_Worker(id="w"), task)
        assert task.error != ""
        assert result.metrics.get("error") == 1.0


class TestSwarmSupervise:
    def _monitor(self, threshold=1):
        from datetime import timedelta

        from dxrk.utils.swarm_model import Backend, default_swarm_config
        from dxrk.utils.swarm_registry import new_backend_registry
        from dxrk.utils.swarm_supervise import new_health_monitor

        reg = new_backend_registry(default_swarm_config(), None)
        backend = Backend(name="hb", capacity=1)
        assert reg.register(None, backend) is None
        monitor = new_health_monitor(reg, timedelta(seconds=10), timedelta(seconds=5), threshold)
        return monitor, backend

    def test_ping_fail_then_recover(self):
        from dxrk.utils.swarm_model import BackendStatus, SwarmError

        monitor, backend = self._monitor()
        monitor.set_ping(lambda b: SwarmError("down"))
        assert monitor.force_check(backend.id) is None
        assert monitor.get_health(backend.id)[0] is BackendStatus.StatusUnhealthy
        monitor.set_backend_ping(backend.id, lambda b: None)
        monitor.set_backend_ping(backend.id, None)
        monitor.set_ping(lambda b: None)
        assert monitor.force_check(backend.id) is None
        assert monitor.get_health(backend.id)[0] is BackendStatus.StatusHealthy

    def test_ping_backend_none(self):
        monitor, _ = self._monitor()
        assert monitor._ping_backend(None) is None

    def test_default_ping_stopping(self):
        from dxrk.utils.swarm_model import Backend, BackendStatus, SwarmError

        backend = Backend(name="stop", capacity=1)
        backend.set_status(BackendStatus.StatusStopping)
        from dxrk.utils.swarm_supervise import HealthMonitor

        assert isinstance(HealthMonitor._default_ping(backend), SwarmError)


# __COV100_UTILS_TAIL__
