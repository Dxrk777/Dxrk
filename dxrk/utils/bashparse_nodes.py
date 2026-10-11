# SPDX-License-Identifier: MIT
"""Concrete bash AST node types with traversal helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from dxrk.utils.bashparse_model import ASTNode, Location, NodeType, RedirectOp
from dxrk.utils.bashparse_quote import _needs_quote, _node_string, _shell_quote


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
                parts.append(_shell_quote(arg))
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
