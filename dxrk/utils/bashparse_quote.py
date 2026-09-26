# SPDX-License-Identifier: MIT
"""Shell quoting helpers shared by AST nodes and the parser."""

from __future__ import annotations

from dxrk.utils.bashparse_model import ASTNode

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
