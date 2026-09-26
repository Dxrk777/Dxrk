# SPDX-License-Identifier: MIT
"""Bash AST base model: string constants, locations, errors, and node enums."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum

StrCritical = "critical"
StrUnknown = "unknown"
StrLocal = "local"


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
