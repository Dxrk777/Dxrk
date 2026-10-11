# SPDX-License-Identifier: MIT
"""Bash recursive-descent parser producing the AST."""

from __future__ import annotations

from dxrk.utils.bashparse_lexer import _Token, _tokenize, _TokenType
from dxrk.utils.bashparse_model import ASTNode, ParseError, RedirectOp
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
)
from dxrk.utils.bashparse_quote import _shell_quote


class _Parser:
    """State for the recursive-descent parser."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> _Token:
        if self._pos >= len(self._tokens):
            return _Token(_TokenType.tokEOF)
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        t = self._tokens[self._pos]
        self._pos += 1
        return t

    def _expect(self, typ: _TokenType) -> ParseError | None:
        t = self._peek()
        if t.typ != typ:
            return ParseError(
                f"expected {int(typ)}, got {int(t.typ)} ({_shell_quote(t.val)})",
                t.pos,
            )
        self._advance()
        return None

    def _parse_list(self) -> tuple[ASTNode | None, ParseError | None]:
        left, err = self._parse_pipeline()
        if err is not None:
            return None, err
        assert left is not None

        while True:
            t = self._peek()
            if t.typ == _TokenType.tokSemicolon:
                self._advance()
                nxt = self._peek()
                if nxt.typ in (_TokenType.tokRBrace, _TokenType.tokEOF):
                    return left, None
                right, err = self._parse_pipeline()
                if err is not None:
                    return None, err
                assert right is not None
                left = SequenceNode(commands=[left, right], loc=t.pos)
            elif t.typ == _TokenType.tokAnd:
                self._advance()
                right, err = self._parse_pipeline()
                if err is not None:
                    return None, err
                assert right is not None
                left = AndNode(left=left, right=right, loc=t.pos)
            elif t.typ == _TokenType.tokOr:
                self._advance()
                right, err = self._parse_pipeline()
                if err is not None:
                    return None, err
                assert right is not None
                left = OrNode(left=left, right=right, loc=t.pos)
            else:
                return left, None

    def _parse_pipeline(self) -> tuple[ASTNode | None, ParseError | None]:
        first, err = self._parse_command()
        if err is not None:
            return None, err
        assert first is not None

        if self._peek().typ != _TokenType.tokPipe:
            return first, None

        cmds: list[ASTNode] = [first]
        while self._peek().typ == _TokenType.tokPipe:
            self._advance()
            cmd, err = self._parse_command()
            if err is not None:
                return None, err
            assert cmd is not None
            cmds.append(cmd)
        return PipeNode(commands=cmds, loc=first.loc), None

    def _parse_command(self) -> tuple[ASTNode | None, ParseError | None]:
        t = self._peek()

        # Subshell
        if t.typ == _TokenType.tokLParen:
            self._advance()
            body, err = self._parse_list()
            if err is not None:
                return None, err
            assert body is not None
            err = self._expect(_TokenType.tokRParen)
            if err is not None:
                return None, err
            node: ASTNode = SubshellNode(body=body, loc=t.pos)
            # Redirections apply to the subshell (e.g. (cmd) >file)
            node = self._attach_redirects(node)
            # Check for background
            if self._peek().typ == _TokenType.tokAmp:
                self._advance()
                return BackgroundNode(command=node, loc=t.pos), None
            return node, None

        # Compound block { ... }
        if t.typ == _TokenType.tokLBrace:
            self._advance()
            nodes: list[ASTNode] = []
            while self._peek().typ != _TokenType.tokRBrace and self._peek().typ != _TokenType.tokEOF:
                n, err = self._parse_list()
                if err is not None:
                    return None, err
                assert n is not None
                nodes.append(n)
                if self._peek().typ == _TokenType.tokSemicolon:
                    self._advance()
            err = self._expect(_TokenType.tokRBrace)
            if err is not None:
                return None, err
            node = CompoundNode(body=nodes, loc=t.pos)
            # Redirections apply to the block (e.g. { cmd; } >file)
            node = self._attach_redirects(node)
            return node, None

        # Simple command
        if t.typ != _TokenType.tokWord:
            return None, ParseError(
                f"unexpected token {int(t.typ)} ({_shell_quote(t.val)})",
                t.pos,
            )

        cmd, err = self._parse_simple_command()
        if err is not None:
            return None, err
        assert cmd is not None

        # Handle redirections after the command
        cmd = self._attach_redirects(cmd)

        # Handle background
        if self._peek().typ == _TokenType.tokAmp:
            self._advance()
            return BackgroundNode(command=cmd, loc=t.pos), None

        return cmd, None

    def _parse_simple_command(self) -> tuple[ASTNode | None, ParseError | None]:
        t = self._peek()
        if t.typ != _TokenType.tokWord:
            return None, ParseError(
                f"expected command name, got {int(t.typ)}",
                t.pos,
            )

        name = self._advance().val
        env: dict[str, str] = {}
        args: list[str] = []

        # Check for VAR=value assignments after the command name
        while self._peek().typ == _TokenType.tokWord:
            w = self._peek().val
            idx = w.find("=")
            if idx > 0:
                key = w[:idx]
                val = w[idx + 1 :]
                if _is_valid_env_key(key):
                    self._advance()
                    env[key] = val
                    continue
            break

        # Collect remaining arguments
        while self._peek().typ == _TokenType.tokWord:
            args.append(self._advance().val)

        return CommandNode(name=name, args=args, env=env, loc=t.pos), None

    _REDIRECT_TYPES = frozenset(
        {
            _TokenType.tokRedirectIn,
            _TokenType.tokRedirectOut,
            _TokenType.tokRedirectAppend,
            _TokenType.tokRedirectDupIn,
            _TokenType.tokRedirectDupOut,
        }
    )

    def _attach_redirects(self, node: ASTNode) -> ASTNode:
        while True:
            # Words were already collected into args up front; skip any that
            # precede a redirect (e.g. the "2" in `echo hi >f 2>g`).
            while (
                self._peek().typ == _TokenType.tokWord
                and self._pos + 1 < len(self._tokens)
                and self._tokens[self._pos + 1].typ in self._REDIRECT_TYPES
            ):
                self._advance()

            t = self._peek()

            if t.typ == _TokenType.tokRedirectIn:
                op = RedirectOp.RedirectRead
                fd = 0
            elif t.typ == _TokenType.tokRedirectDupIn:
                op = RedirectOp.RedirectDupeIn
                fd = 0
            elif t.typ == _TokenType.tokRedirectOut:
                op = RedirectOp.RedirectWrite
                fd = 1
            elif t.typ == _TokenType.tokRedirectAppend:
                op = RedirectOp.RedirectAppend
                fd = 1
            elif t.typ == _TokenType.tokRedirectDupOut:
                op = RedirectOp.RedirectDupeOut
                fd = 1
            else:
                return node

            self._advance()

            # A numeric argument is promoted to a file descriptor only for
            # dupe operators (e.g. 2>&1); 2>file keeps "2" as an argument.
            if op in (RedirectOp.RedirectDupeIn, RedirectOp.RedirectDupeOut):
                inner: ASTNode = node
                while isinstance(inner, RedirectNode):
                    assert inner.body is not None
                    inner = inner.body
                if isinstance(inner, CommandNode) and inner.args:
                    last = inner.args[-1]
                    if last.isdigit():
                        inner.args.pop()
                        fd = int(last)

            target = ""
            if self._peek().typ == _TokenType.tokWord:
                target = self._advance().val

            # Bare dupe like 2>& normalizes its target to 0
            if op in (RedirectOp.RedirectDupeIn, RedirectOp.RedirectDupeOut):
                try:
                    target_fd = int(target)
                except ValueError:
                    target_fd = 0
                target = str(target_fd)

            node = RedirectNode(fd=fd, op=op, target=target, body=node, loc=t.pos)


def _is_valid_env_key(key: str) -> bool:
    if key == "":
        return False
    for i, ch in enumerate(key):
        if i == 0:
            if not (ch.isalpha() or ch == "_"):
                return False
        elif not (ch.isalpha() or ch.isdigit() or ch == "_"):
            return False
    return True


def Parse(text: str) -> tuple[ASTNode | None, ParseError | None]:
    """Parses a bash command string into an AST.

    Handles simple commands with arguments, pipelines (|), logical
    operators (&&, ||), command sequences (;), subshells (()), background
    execution (&), redirections (>, >>, <, 2>&1), single/double quotes,
    backslash escapes, variable references ($VAR, ${VAR}), and command
    substitution ($(...), `...`).
    """
    text = text.strip()
    if text == "":
        return None, ParseError("empty input")

    tokens = _tokenize(text)
    parser = _Parser(tokens)

    node, err = parser._parse_list()
    if err is not None:
        return None, err
    assert node is not None

    # Anything left over is a syntax error (e.g. `cmd (` or `cmd &&`)
    if parser._peek().typ != _TokenType.tokEOF:
        t = parser._peek()
        return None, ParseError(
            f"unexpected token {int(t.typ)} ({_shell_quote(t.val)})",
            t.pos,
        )

    return node, None
