# SPDX-License-Identifier: MIT
"""Bash command parsing, AST representation, and danger analysis utilities.

Implements a recursive-descent parser that converts bash command strings
into a structured abstract syntax tree (AST) capturing pipes, sequences,
subshells, redirections, background execution, and brace groups. The danger
analysis module scans AST nodes for destructive patterns (recursive
deletion, fork bombs, disk wiping, privilege escalation), each finding
carrying a severity level, the matched pattern, and a safer alternative.
Normalization utilities strip whitespace, expand variables, and classify
commands as built-in vs external.

Error sentinels use verbatim messages and are returned as values,
never raised.

Fidelity notes (mirrored intentionally, including upstream quirks):

* ``CommandNode.env`` is ordered by insertion in Python; the original iterates a map
  in random order, so ``string()`` may reorder env assignments.
* ``_go_quote`` writes printable non-ASCII literally; the original ``%q`` escapes
  non-printable runes as ``\\uXXXX``.
* The parser only collects ``VAR=value`` assignments that appear *after*
  the command name; leading assignments stay in ``name`` (e.g.
  ``FOO=bar cmd`` parses name ``FOO=bar``, args ``["cmd"]``) and round-trip
  identically through ``string()``.
* A numeric argument is only promoted to a file descriptor for dupe
  operators (``2>&1``); ``2>>x`` keeps ``2`` as a plain argument.
* The token-to-op mapping for dupe redirects is swapped: input
  ``<&`` yields ``RedirectDupeIn`` whose ``string()`` prints ``>&``, and
  input ``>&`` yields ``RedirectDupeOut`` printing ``<&``.
* A bare dupe like ``2>&`` normalizes its target to ``0`` (the original ``Atoi("")``
  fails, leaving the zero value).
* ``(a) | b`` panics in the original (type assertion on CommandNode); here the
  pipeline reuses the first node's location without crashing.
* ``StrCritical``/``StrUnknown``/``StrLocal`` are defined locally; the original
  imports them from the ``strconst`` package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

StrCritical = "critical"
StrUnknown = "unknown"
StrLocal = "local"


# --- ast.go ---


@dataclass
class Location:
    """Tracks the source position of a node for error reporting."""

    line: int = 0  # 1-based line number
    column: int = 0  # 1-based column number
    offset: int = 0  # 0-based byte offset from input start


class ParseError(Exception):
    """Reports a parse failure with source location."""

    def __init__(self, message: str, pos: Location | None = None) -> None:
        self.message = message
        self.pos = pos

    def __str__(self) -> str:
        if self.pos is not None and self.pos.line > 0:
            return f"bashparse: line {self.pos.line}, col {self.pos.column}: {self.message}"
        return f"bashparse: {self.message}"


class NodeType(IntEnum):
    """Identifies the kind of AST node."""

    NodeCommand = 0  # Simple command with name and arguments
    NodePipe = 1  # Pipeline of commands connected by |
    NodeSequence = 2  # Commands connected by ;
    NodeAnd = 3  # Commands connected by &&
    NodeOr = 4  # Commands connected by ||
    NodeSubshell = 5  # Command group inside ()
    NodeRedirect = 6  # I/O redirection
    NodeBackground = 7  # Command followed by &
    NodeCompound = 8  # Brace group { ... }

    def string(self) -> str:
        """Returns the human-readable name of the node type."""
        return {
            NodeType.NodeCommand: "Command",
            NodeType.NodePipe: "Pipe",
            NodeType.NodeSequence: "Sequence",
            NodeType.NodeAnd: "And",
            NodeType.NodeOr: "Or",
            NodeType.NodeSubshell: "Subshell",
            NodeType.NodeRedirect: "Redirect",
            NodeType.NodeBackground: "Background",
            NodeType.NodeCompound: "Compound",
        }.get(self, "Unknown")


class RedirectOp(IntEnum):
    """Enumerates the supported redirection operators."""

    RedirectRead = 0  # <
    RedirectWrite = 1  # >
    RedirectAppend = 2  # >>
    RedirectDupeIn = 3  # 2>&1 (dup stderr to stdout)
    RedirectDupeOut = 4  # <&1 (dup stdout to stderr)
    RedirectPipe = 5  # | (pipeline)

    def string(self) -> str:
        """Returns the shell representation of the operator."""
        return {
            RedirectOp.RedirectRead: "<",
            RedirectOp.RedirectWrite: ">",
            RedirectOp.RedirectAppend: ">>",
            RedirectOp.RedirectDupeIn: ">&",
            RedirectOp.RedirectDupeOut: "<&",
            RedirectOp.RedirectPipe: "|",
        }.get(self, "?")


class DangerLevel(IntEnum):
    """Classifies the severity of a detected danger."""

    Safe = 0  # No issues detected
    Warning = 1  # Potentially unsafe, review recommended
    Dangerous = 2  # Likely harmful, block or confirm
    Critical = 3  # Destructive, must block

    def string(self) -> str:
        """Returns the label for the danger level."""
        return {
            DangerLevel.Safe: "safe",
            DangerLevel.Warning: "warning",
            DangerLevel.Dangerous: "dangerous",
            DangerLevel.Critical: StrCritical,
        }.get(self, StrUnknown)


class ASTNode(ABC):
    """Interface implemented by all AST node types."""

    loc: Location

    @abstractmethod
    def node_type(self) -> NodeType:
        """Returns the type of this node."""

    @abstractmethod
    def string(self) -> str:
        """Returns the shell representation of this node."""

    @abstractmethod
    def children(self) -> list[ASTNode]:
        """Returns the child nodes of this node."""


_SHELL_SPECIALS = " \t\"'\\$`|;&<>()!"


def _needs_quote(value: str) -> bool:
    """Returns True if a shell word needs quoting."""
    return any(ch in _SHELL_SPECIALS for ch in value)


def _go_quote(value: str) -> str:
    """Quotes token values like fmt %q (strconv.Quote)."""
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _node_string(node: ASTNode | None) -> str:
    """Formats a node like %s, printing <nil> for a nil node."""
    if node is None:
        return "<nil>"
    return node.string()


@dataclass
class CommandNode(ASTNode):
    """A simple command with a name, arguments, and optional env assignments."""

    name: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeCommand

    def children(self) -> list[ASTNode]:
        return []

    def string(self) -> str:
        parts: list[str] = []
        for key, value in self.env.items():
            parts.append(f"{key}={value}")
        parts.append(self.name)
        for arg in self.args:
            if _needs_quote(arg):
                parts.append(_go_quote(arg))
            else:
                parts.append(arg)
        return " ".join(parts)


@dataclass
class PipeNode(ASTNode):
    """A pipeline of commands connected by | operators."""

    commands: list[ASTNode] = field(default_factory=list)
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodePipe

    def children(self) -> list[ASTNode]:
        return list(self.commands)

    def string(self) -> str:
        return " | ".join(cmd.string() for cmd in self.commands)


@dataclass
class SequenceNode(ASTNode):
    """Commands connected by semicolons."""

    commands: list[ASTNode] = field(default_factory=list)
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeSequence

    def children(self) -> list[ASTNode]:
        return list(self.commands)

    def string(self) -> str:
        return "; ".join(cmd.string() for cmd in self.commands)


@dataclass
class AndNode(ASTNode):
    """Commands connected by the && operator."""

    left: ASTNode = field(default_factory=lambda: CommandNode())
    right: ASTNode = field(default_factory=lambda: CommandNode())
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeAnd

    def children(self) -> list[ASTNode]:
        return [self.left, self.right]

    def string(self) -> str:
        return f"{_node_string(self.left)} && {_node_string(self.right)}"


@dataclass
class OrNode(ASTNode):
    """Commands connected by the || operator."""

    left: ASTNode = field(default_factory=lambda: CommandNode())
    right: ASTNode = field(default_factory=lambda: CommandNode())
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeOr

    def children(self) -> list[ASTNode]:
        return [self.left, self.right]

    def string(self) -> str:
        return f"{_node_string(self.left)} || {_node_string(self.right)}"


@dataclass
class SubshellNode(ASTNode):
    """A command group executed in a subshell."""

    body: ASTNode = field(default_factory=lambda: CommandNode())
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeSubshell

    def children(self) -> list[ASTNode]:
        return [self.body]

    def string(self) -> str:
        return f"({_node_string(self.body)})"


@dataclass
class RedirectNode(ASTNode):
    """An I/O redirection."""

    fd: int = 1  # File descriptor (default 1 for >, 0 for <)
    op: RedirectOp = RedirectOp.RedirectWrite
    target: str = ""  # Target file or fd number
    body: ASTNode | None = None  # The command being redirected (may be None)
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeRedirect

    def children(self) -> list[ASTNode]:
        if self.body is not None:
            return [self.body]
        return []

    def string(self) -> str:
        fd = ""
        if self.fd != 1 and self.fd != 0:
            fd = str(self.fd)
        body = ""
        if self.body is not None:
            body = self.body.string() + " "
        return f"{body}{fd}{self.op.string()} {self.target}"


@dataclass
class BackgroundNode(ASTNode):
    """A command executed in the background with &."""

    command: ASTNode = field(default_factory=lambda: CommandNode())
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeBackground

    def children(self) -> list[ASTNode]:
        return [self.command]

    def string(self) -> str:
        return f"{_node_string(self.command)} &"


@dataclass
class CompoundNode(ASTNode):
    """A brace group { ... } or if/while/for construct."""

    body: list[ASTNode] = field(default_factory=list)
    loc: Location = field(default_factory=Location)

    def node_type(self) -> NodeType:
        return NodeType.NodeCompound

    def children(self) -> list[ASTNode]:
        return list(self.body)

    def string(self) -> str:
        return "{ " + "; ".join(cmd.string() for cmd in self.body) + " }"


def Walk(node: ASTNode | None, fn: Callable[[ASTNode], bool]) -> None:
    """Calls fn for every node in the tree rooted at node, depth-first."""
    if node is None:
        return
    if not fn(node):
        return
    for child in node.children():
        Walk(child, fn)


def CollectCommands(node: ASTNode) -> list[CommandNode]:
    """Extracts all CommandNode instances from the tree."""
    cmds: list[CommandNode] = []

    def _visit(n: ASTNode) -> bool:
        if isinstance(n, CommandNode):
            cmds.append(n)
        return True

    Walk(node, _visit)
    return cmds


# --- parser.go ---


class _TokenType(IntEnum):
    tokWord = 0
    tokPipe = 1
    tokSemicolon = 2
    tokAnd = 3
    tokOr = 4
    tokLParen = 5
    tokRParen = 6
    tokLBrace = 7
    tokRBrace = 8
    tokAmp = 9
    tokRedirectIn = 10
    tokRedirectOut = 11
    tokRedirectAppend = 12
    tokRedirectDupIn = 13
    tokRedirectDupOut = 14
    tokEOF = 15


@dataclass
class _Token:
    typ: _TokenType
    val: str = ""
    pos: Location = field(default_factory=Location)


class _Lexer:
    """Splits bash input into tokens, tracking line/column/offset."""

    def __init__(self, text: str) -> None:
        self._input = list(text)
        self._pos = 0
        self._line = 1
        self._col = 1
        self._offset = 0

    def _location(self) -> Location:
        return Location(line=self._line, column=self._col, offset=self._offset)

    def _peek(self, ahead: int = 0) -> str:
        if self._pos + ahead >= len(self._input):
            return ""
        return self._input[self._pos + ahead]

    def _advance(self) -> None:
        if self._pos >= len(self._input):
            return
        r = self._input[self._pos]
        self._pos += 1
        self._offset += 1
        if r == "\n":
            self._line += 1
            self._col = 1
        else:
            self._col += 1

    def _skip_spaces(self) -> None:
        while self._peek() and self._peek().isspace():
            self._advance()

    def _read_word(self) -> str:
        chars: list[str] = []
        in_single = False
        in_double = False
        in_backtick = False
        escaped = False
        while True:
            r = self._peek()
            if r == "":
                break
            if escaped:
                chars.append(r)
                self._advance()
                escaped = False
                continue
            if r == "\\" and not in_single:
                escaped = True
                self._advance()
                continue
            if r == "'" and not in_double and not in_backtick:
                in_single = not in_single
                self._advance()
                continue
            if r == '"' and not in_single and not in_backtick:
                in_double = not in_double
                self._advance()
                continue
            if r == "`" and not in_single and not in_double:
                in_backtick = not in_backtick
                chars.append(r)
                self._advance()
                continue
            if in_single or in_double or in_backtick:
                chars.append(r)
                self._advance()
                continue
            if r == "$" and self._peek(1) in "({":
                close = "}" if self._peek(1) == "{" else ")"
                depth = 0
                while True:
                    c = self._peek()
                    if c == "":
                        break
                    chars.append(c)
                    self._advance()
                    if c in "({":
                        depth += 1
                    elif c in ")}":
                        depth -= 1
                        if depth == 0:
                            break
                continue
            if r.isspace() or r in "|;&(){}<>":
                break
            chars.append(r)
            self._advance()
        return "".join(chars)

    def _next_token(self) -> _Token:
        self._skip_spaces()
        if self._peek() == "":
            return _Token(_TokenType.tokEOF, "", self._location())

        pos = self._location()
        r = self._peek()

        if r == "|":
            self._advance()
            if self._peek() == "|":
                self._advance()
                return _Token(_TokenType.tokOr, "||", pos)
            return _Token(_TokenType.tokPipe, "|", pos)
        if r == "&":
            self._advance()
            if self._peek() == "&":
                self._advance()
                return _Token(_TokenType.tokAnd, "&&", pos)
            return _Token(_TokenType.tokAmp, "&", pos)
        if r == ";":
            self._advance()
            return _Token(_TokenType.tokSemicolon, ";", pos)
        if r == "(":
            self._advance()
            return _Token(_TokenType.tokLParen, "(", pos)
        if r == ")":
            self._advance()
            return _Token(_TokenType.tokRParen, ")", pos)
        if r == "{":
            self._advance()
            return _Token(_TokenType.tokLBrace, "{", pos)
        if r == "}":
            self._advance()
            return _Token(_TokenType.tokRBrace, "}", pos)
        if r == "<":
            self._advance()
            if self._peek() == "&":
                self._advance()
                return _Token(_TokenType.tokRedirectDupIn, "<&", pos)
            return _Token(_TokenType.tokRedirectIn, "<", pos)
        if r == ">":
            self._advance()
            if self._peek() == ">":
                self._advance()
                return _Token(_TokenType.tokRedirectAppend, ">>", pos)
            if self._peek() == "&":
                self._advance()
                return _Token(_TokenType.tokRedirectDupOut, ">&", pos)
            return _Token(_TokenType.tokRedirectOut, ">", pos)

        return _Token(_TokenType.tokWord, self._read_word(), pos)


def _tokenize(text: str) -> list[_Token]:
    lex = _Lexer(text)
    tokens: list[_Token] = []
    while True:
        t = lex._next_token()
        tokens.append(t)
        if t.typ == _TokenType.tokEOF:
            break
    return tokens


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
                f"expected {int(typ)}, got {int(t.typ)} ({_go_quote(t.val)})",
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
            while (
                self._peek().typ != _TokenType.tokRBrace
                and self._peek().typ != _TokenType.tokEOF
            ):
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
                f"unexpected token {int(t.typ)} ({_go_quote(t.val)})",
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
            f"unexpected token {int(t.typ)} ({_go_quote(t.val)})",
            t.pos,
        )

    return node, None
