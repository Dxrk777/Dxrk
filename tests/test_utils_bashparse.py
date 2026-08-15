# SPDX-License-Identifier: MIT
"""Tests for dxrk.utils.bashparse (mirrors internal/utils/bashparse port)."""

from __future__ import annotations

from typing import TypeVar

from dxrk.utils import bashparse as bp

_T = TypeVar("_T", bound=bp.ASTNode)


def _node(text: str, cls: type[_T]) -> _T:
    """Parses text, asserting success, and narrows the node to cls."""
    node, err = bp.Parse(text)
    assert err is None, err
    assert isinstance(node, cls)
    return node


def _cmd_of(n: bp.ASTNode | None) -> bp.CommandNode:
    assert isinstance(n, bp.CommandNode)
    return n


def _parse(text: str) -> tuple[bp.ASTNode | None, bp.ParseError | None]:
    return bp.Parse(text)


class TestParse:
    def test_simple_command(self):
        node = _node("echo hello", bp.CommandNode)
        assert node.name == "echo"
        assert node.args == ["hello"]
        assert node.env == {}

    def test_simple_command_no_args(self):
        node = _node("ls", bp.CommandNode)
        assert node.name == "ls"
        assert node.args == []

    def test_empty_input(self):
        node, err = _parse("")
        assert node is None
        assert isinstance(err, bp.ParseError)
        assert str(err) == "bashparse: empty input"

    def test_whitespace_input(self):
        node, err = _parse("   \n  ")
        assert node is None
        assert str(err) == "bashparse: empty input"

    def test_single_quotes(self):
        node = _node("echo 'a b'", bp.CommandNode)
        assert node.args == ["a b"]

    def test_double_quotes(self):
        node = _node('echo "a b"', bp.CommandNode)
        assert node.args == ["a b"]

    def test_backslash_escape_space(self):
        node = _node("echo a\\ b", bp.CommandNode)
        assert node.args == ["a b"]

    def test_backslash_escape_backslash(self):
        node = _node("echo a\\\\b", bp.CommandNode)
        assert node.args == ["a\\b"]

    def test_plain_variable(self):
        node = _node("echo $VAR", bp.CommandNode)
        assert node.args == ["$VAR"]

    def test_brace_variable(self):
        node = _node("echo ${VAR}", bp.CommandNode)
        assert node.args == ["${VAR}"]

    def test_brace_variable_with_default(self):
        node = _node("echo ${VAR:-x}", bp.CommandNode)
        assert node.args == ["${VAR:-x}"]

    def test_nested_brace_variable(self):
        node = _node("echo ${a:-${b}}", bp.CommandNode)
        assert node.args == ["${a:-${b}}"]

    def test_command_substitution(self):
        node = _node("echo $(ls)", bp.CommandNode)
        assert node.args == ["$(ls)"]

    def test_arithmetic_substitution(self):
        node = _node("echo $((1+2))", bp.CommandNode)
        assert node.args == ["$((1+2))"]

    def test_backtick_substitution(self):
        node = _node("echo `ls -la`", bp.CommandNode)
        assert node.args == ["`ls -la`"]

    def test_substitution_in_double_quotes(self):
        node = _node('echo "$(ls)"', bp.CommandNode)
        assert node.args == ["$(ls)"]

    def test_substitution_in_single_quotes_literal(self):
        node = _node("echo '$(ls)'", bp.CommandNode)
        assert node.args == ["$(ls)"]

    def test_trailing_semicolon(self):
        node = _node("echo a; echo b;", bp.SequenceNode)
        assert [_cmd_of(c).name for c in node.commands] == ["echo", "echo"]

    def test_env_after_name(self):
        node = _node("cmd A=1 B=2 arg", bp.CommandNode)
        assert node.name == "cmd"
        assert node.args == ["arg"]
        assert node.env == {"A": "1", "B": "2"}

    def test_leading_assignment_stays_in_name(self):
        node = _node("FOO=bar cmd arg", bp.CommandNode)
        assert node.name == "FOO=bar"
        assert node.args == ["cmd", "arg"]
        assert node.env == {}


class TestPipeline:
    def test_simple_pipeline(self):
        node = _node("a | b", bp.PipeNode)
        assert [_cmd_of(c).name for c in node.commands] == ["a", "b"]

    def test_multi_pipeline(self):
        node = _node("echo a | grep b | sort", bp.PipeNode)
        assert len(node.commands) == 3
        assert [_cmd_of(c).name for c in node.commands] == ["echo", "grep", "sort"]

    def test_pipeline_with_args(self):
        node = _node("ls -la | grep py", bp.PipeNode)
        assert _cmd_of(node.commands[0]).args == ["-la"]
        assert _cmd_of(node.commands[1]).args == ["py"]

    def test_dangling_pipe_is_error(self):
        node, err = _parse("echo a |")
        assert node is None
        assert "unexpected token" in str(err)


class TestLogicalOperators:
    def test_and(self):
        node = _node("true && echo x", bp.AndNode)
        assert _cmd_of(node.left).name == "true"
        assert _cmd_of(node.right).name == "echo"

    def test_or(self):
        node = _node("false || echo x", bp.OrNode)
        assert _cmd_of(node.left).name == "false"
        assert _cmd_of(node.right).name == "echo"

    def test_and_binds_tighter_than_or(self):
        node = _node("true || echo x && echo y", bp.AndNode)
        assert isinstance(node.left, bp.OrNode)
        assert _cmd_of(node.right).name == "echo"

    def test_dangling_and_is_error(self):
        node, err = _parse("echo hi &&")
        assert node is None
        assert "unexpected token" in str(err)

    def test_dangling_or_is_error(self):
        node, err = _parse("echo hi ||")
        assert node is None
        assert "unexpected token" in str(err)


class TestSequence:
    def test_multiple_commands(self):
        node, err = _parse("ls -la; cd /; pwd")
        assert err is None, err
        assert node is not None
        names = bp.CollectCommands(node)
        assert [c.name for c in names] == ["ls", "cd", "pwd"]

    def test_semicolon_before_eof_ok(self):
        node = _node("echo a;", bp.CommandNode)
        assert node.name == "echo"


class TestSubshell:
    def test_basic_subshell(self):
        node = _node("(echo hi)", bp.SubshellNode)
        assert _cmd_of(node.body).name == "echo"

    def test_subshell_with_sequence(self):
        node = _node("(echo a; echo b)", bp.SubshellNode)
        assert isinstance(node.body, bp.SequenceNode)

    def test_nested_subshell(self):
        node = _node("(a | b) && (c)", bp.AndNode)
        assert isinstance(node.left, bp.SubshellNode)
        assert isinstance(node.right, bp.SubshellNode)

    def test_word_before_subshell_is_error(self):
        node, err = _parse("nested (a | b)")
        assert node is None
        assert "unexpected token" in str(err)

    def test_subshell_redirect(self):
        node = _node("(cmd) >f", bp.RedirectNode)
        assert node.op == bp.RedirectOp.RedirectWrite
        assert node.target == "f"
        assert isinstance(node.body, bp.SubshellNode)

    def test_subshell_background(self):
        node = _node("(cmd) &", bp.BackgroundNode)
        assert isinstance(node.command, bp.SubshellNode)

    def test_empty_subshell_is_error(self):
        node, err = _parse("()")
        assert node is None
        assert "unexpected token" in str(err)

    def test_unclosed_subshell_is_error(self):
        node, err = _parse("(echo")
        assert node is None
        assert "expected" in str(err)

    def test_stray_rparen_is_error(self):
        node, err = _parse("echo )")
        assert node is None
        assert "unexpected token" in str(err)


class TestBraceGroup:
    def test_basic_group(self):
        node, err = _parse("{ ls; cd /; }")
        assert err is None, err
        assert isinstance(node, bp.CompoundNode)
        names = bp.CollectCommands(node)
        assert [c.name for c in names] == ["ls", "cd"]

    def test_group_redirect(self):
        node = _node("{ a; b; } >log", bp.RedirectNode)
        assert node.op == bp.RedirectOp.RedirectWrite
        assert node.target == "log"
        assert isinstance(node.body, bp.CompoundNode)

    def test_unclosed_brace_is_error(self):
        node, err = _parse("{")
        assert node is None
        assert "expected" in str(err)


class TestBackground:
    def test_background(self):
        node = _node("echo a &", bp.BackgroundNode)
        assert _cmd_of(node.command).name == "echo"

    def test_background_redirect(self):
        node = _node("(cmd) >f &", bp.BackgroundNode)
        assert isinstance(node.command, bp.RedirectNode)

    def test_background_between_commands_is_error(self):
        node, err = _parse("echo a & echo b")
        assert node is None
        assert "unexpected token" in str(err)


class TestRedirects:
    def test_write(self):
        node = _node("echo hi >f", bp.RedirectNode)
        assert node.fd == 1
        assert node.op == bp.RedirectOp.RedirectWrite
        assert node.target == "f"
        assert _cmd_of(node.body).name == "echo"

    def test_append(self):
        node = _node("echo hi >>f", bp.RedirectNode)
        assert node.fd == 1
        assert node.op == bp.RedirectOp.RedirectAppend
        assert node.target == "f"

    def test_read(self):
        node = _node("a <in", bp.RedirectNode)
        assert node.fd == 0
        assert node.op == bp.RedirectOp.RedirectRead
        assert node.target == "in"

    def test_dupe_stderr_to_stdout(self):
        node = _node("echo hi 2>&1", bp.RedirectNode)
        assert node.fd == 2
        assert node.op == bp.RedirectOp.RedirectDupeOut
        assert node.target == "1"

    def test_dupe_in(self):
        node = _node("cat <&1", bp.RedirectNode)
        assert node.fd == 0
        assert node.op == bp.RedirectOp.RedirectDupeIn
        assert node.target == "1"

    def test_bare_dupe_target_normalized_to_zero(self):
        node = _node("echo 2>&", bp.RedirectNode)
        assert node.fd == 2
        assert node.op == bp.RedirectOp.RedirectDupeOut
        assert node.target == "0"

    def test_chained_redirects(self):
        node = _node("echo hi >f 2>g", bp.RedirectNode)
        assert node.fd == 1
        assert node.target == "g"
        inner = node.body
        assert isinstance(inner, bp.RedirectNode)
        assert inner.fd == 1
        assert inner.target == "f"
        assert _cmd_of(inner.body).name == "echo"

    def test_glued_redirect_keeps_fd_as_arg(self):
        node = _node("echo 2>/dev/null", bp.RedirectNode)
        assert node.fd == 1
        assert node.op == bp.RedirectOp.RedirectWrite
        assert node.target == "/dev/null"
        assert _cmd_of(node.body).args == ["2"]

    def test_glued_append_keeps_fd_as_arg(self):
        node = _node("echo 2>>x", bp.RedirectNode)
        assert node.fd == 1
        assert node.op == bp.RedirectOp.RedirectAppend
        assert _cmd_of(node.body).args == ["2"]

    def test_multi_redirects(self):
        node = _node("a <in >out", bp.RedirectNode)
        assert node.target == "out"
        inner = node.body
        assert isinstance(inner, bp.RedirectNode)
        assert inner.target == "in"
        assert _cmd_of(inner.body).name == "a"


class TestLocations:
    def test_single_line(self):
        node = _node("echo hi", bp.CommandNode)
        assert node.loc.line == 1
        assert node.loc.column == 1
        assert node.loc.offset == 0

    def test_error_location(self):
        node, err = _parse("echo )")
        assert node is None
        assert err is not None
        assert err.pos is not None
        assert err.pos.line == 1
        assert err.pos.column == 6


class TestNodeType:
    def test_values(self):
        assert bp.NodeType.NodeCommand == 0
        assert bp.NodeType.NodePipe == 1
        assert bp.NodeType.NodeSequence == 2
        assert bp.NodeType.NodeAnd == 3
        assert bp.NodeType.NodeOr == 4
        assert bp.NodeType.NodeSubshell == 5
        assert bp.NodeType.NodeRedirect == 6
        assert bp.NodeType.NodeBackground == 7
        assert bp.NodeType.NodeCompound == 8

    def test_string(self):
        node = _node("echo hi | sort", bp.PipeNode)
        assert node.node_type().string() == "Pipe"
        assert node.commands[0].node_type().string() == "Command"


class TestRedirectOp:
    def test_string(self):
        assert bp.RedirectOp.RedirectRead.string() == "<"
        assert bp.RedirectOp.RedirectWrite.string() == ">"
        assert bp.RedirectOp.RedirectAppend.string() == ">>"
        assert bp.RedirectOp.RedirectDupeIn.string() == ">&"
        assert bp.RedirectOp.RedirectDupeOut.string() == "<&"


class TestString:
    def test_simple(self):
        node = _node("echo hello", bp.CommandNode)
        assert node.string() == "echo hello"

    def test_env(self):
        node = _node("cmd A=1 B=2 arg", bp.CommandNode)
        assert node.string() == "A=1 B=2 cmd arg"

    def test_pipeline(self):
        node = _node("a | b | c", bp.PipeNode)
        assert node.string() == "a | b | c"

    def test_redirect(self):
        node = _node("echo hi >f 2>g", bp.RedirectNode)
        assert node.string() == "echo hi > f > g"


class TestWalk:
    def test_collect_commands(self):
        node, err = _parse("a | b && c; (d) >f")
        assert err is None, err
        assert node is not None
        cmds = bp.CollectCommands(node)
        assert [c.name for c in cmds] == ["a", "b", "c", "d"]

    def test_visit_every_node(self):
        node, err = _parse("a | b && (c; d)")
        assert err is None, err
        assert node is not None
        seen: list[str] = []

        def visit(n: bp.ASTNode) -> bool:
            seen.append(n.node_type().string())
            return True

        bp.Walk(node, visit)
        assert seen.count("Command") == 4
        assert seen.count("And") == 1
        assert seen.count("Pipe") == 1
        assert seen.count("Subshell") == 1
        assert seen.count("Sequence") == 1

    def test_walk_none(self):
        bp.Walk(None, lambda n: True)
