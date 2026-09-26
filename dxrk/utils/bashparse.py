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

from dxrk.utils.bashparse_lexer import _Lexer as _Lexer
from dxrk.utils.bashparse_lexer import _Token as _Token
from dxrk.utils.bashparse_lexer import _tokenize as _tokenize
from dxrk.utils.bashparse_lexer import _TokenType as _TokenType
from dxrk.utils.bashparse_model import ASTNode as ASTNode
from dxrk.utils.bashparse_model import DangerLevel as DangerLevel
from dxrk.utils.bashparse_model import Location as Location
from dxrk.utils.bashparse_model import NodeType as NodeType
from dxrk.utils.bashparse_model import ParseError as ParseError
from dxrk.utils.bashparse_model import RedirectOp as RedirectOp
from dxrk.utils.bashparse_model import StrCritical as StrCritical
from dxrk.utils.bashparse_model import StrLocal as StrLocal
from dxrk.utils.bashparse_model import StrUnknown as StrUnknown
from dxrk.utils.bashparse_nodes import AndNode as AndNode
from dxrk.utils.bashparse_nodes import BackgroundNode as BackgroundNode
from dxrk.utils.bashparse_nodes import CollectCommands as CollectCommands
from dxrk.utils.bashparse_nodes import CommandNode as CommandNode
from dxrk.utils.bashparse_nodes import CompoundNode as CompoundNode
from dxrk.utils.bashparse_nodes import OrNode as OrNode
from dxrk.utils.bashparse_nodes import PipeNode as PipeNode
from dxrk.utils.bashparse_nodes import RedirectNode as RedirectNode
from dxrk.utils.bashparse_nodes import SequenceNode as SequenceNode
from dxrk.utils.bashparse_nodes import SubshellNode as SubshellNode
from dxrk.utils.bashparse_nodes import Walk as Walk
from dxrk.utils.bashparse_parser import Parse as Parse
from dxrk.utils.bashparse_parser import _is_valid_env_key as _is_valid_env_key
from dxrk.utils.bashparse_parser import _Parser as _Parser
from dxrk.utils.bashparse_quote import _SHELL_SPECIALS as _SHELL_SPECIALS
from dxrk.utils.bashparse_quote import _go_quote as _go_quote
from dxrk.utils.bashparse_quote import _needs_quote as _needs_quote
from dxrk.utils.bashparse_quote import _node_string as _node_string
