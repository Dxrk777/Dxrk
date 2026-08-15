# SPDX-License-Identifier: MIT
"""Fail-closed shell command parsing and security analysis"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional

# ---- AST Node Types ----


class NodeType(IntEnum):
    COMMAND = 0
    PIPELINE = 1
    LIST = 2
    SUBSHELL = 3
    REDIRECT = 4
    VARIABLE = 5
    ASSIGNMENT = 6
    WORD = 7
    OPERATOR = 8
    HEREDOC = 9
    COMMENT = 10
    UNKNOWN = 11

    @classmethod
    def _missing_(cls, value):
        return cls.UNKNOWN

    def __str__(self) -> str:
        names = {
            NodeType.COMMAND: "command",
            NodeType.PIPELINE: "pipeline",
            NodeType.LIST: "list",
            NodeType.SUBSHELL: "subshell",
            NodeType.REDIRECT: "redirect",
            NodeType.VARIABLE: "variable",
            NodeType.ASSIGNMENT: "assignment",
            NodeType.WORD: "word",
            NodeType.OPERATOR: "operator",
            NodeType.HEREDOC: "heredoc",
            NodeType.COMMENT: "comment",
        }
        return names.get(self, "unknown")


@dataclass
class ASTNode:
    """A node in the parsed shell AST."""

    type: NodeType
    value: str = ""
    children: List["ASTNode"] = field(default_factory=list)
    pos: int = 0
    length: int = 0


@dataclass
class ParseForSecurityResult:
    """The outcome of security-focused shell parsing."""

    root: Optional[ASTNode] = None
    command: str = ""
    env_vars: List[str] = field(default_factory=list)
    operators: List[str] = field(default_factory=list)
    is_safe: bool = True
    violations: List[str] = field(default_factory=list)


# ---- Safe builtins (commands that are considered safe) ----

SAFE_BUILTINS = {
    "echo",
    "printf",
    "cat",
    "head",
    "tail",
    "wc",
    "ls",
    "pwd",
    "whoami",
    "date",
    "env",
    "printenv",
    "which",
    "type",
    "file",
    "stat",
    "readlink",
    "dirname",
    "basename",
    "sort",
    "uniq",
    "tr",
    "cut",
    "paste",
    "column",
    "tee",
    "xargs",
    "find",
    "grep",
    "rg",
    "ag",
    "awk",
    "sed",
    "jq",
    "yq",
    "diff",
    "comm",
    "mktemp",
    "realpath",
    "go",
    "cargo",
    "rustc",
    "node",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "bun",
    "deno",
    "python",
    "python3",
    "pip",
    "pip3",
    "uv",
    "git",
    "gh",
    "docker",
    "podman",
    "make",
    "cmake",
    "meson",
    "mkdir",
    "touch",
    "cp",
    "mv",
    "ln",
    "chmod",
    "chown",
    "df",
    "du",
    "tree",
    "sha256sum",
    "md5sum",
    "base64",
    "sleep",
    "true",
    "false",
    "test",
}

# ---- Regex patterns for dangerous constructs ----

_CMD_SUBST_RE = re.compile(r"\$\(")
_BACKTICK_RE = re.compile(r"`[^`]*`")
_VAR_EXPAND_RE = re.compile(r"\$\{[^}]*\}")
_EVAL_RE = re.compile(r"(?:^|\s)(?:eval|exec|source|\.)\s")
_SUDO_RE = re.compile(r"(?:^|\s)(?:sudo|su|doas)\s")
_HEX_ESCAPE_RE = re.compile(r"\\x[0-9a-fA-F]{2}")
_NULL_BYTE_RE = re.compile(r"\x00")

# ---- Public API ----


def parse_for_security(command: str) -> ParseForSecurityResult:
    """Parse a shell command and return a security analysis.

    Fail-closed: any parse error results in is_safe=False with violations.
    """
    if command == "":
        return ParseForSecurityResult(command=command, is_safe=True)

    # Input length guard
    if len(command) > 10000:
        return ParseForSecurityResult(
            command=command,
            is_safe=False,
            violations=["command exceeds maximum length (10000 bytes)"],
        )

    # Null byte check
    if _NULL_BYTE_RE.search(command):
        return ParseForSecurityResult(
            command=command,
            is_safe=False,
            violations=["null byte detected in command"],
        )

    # Phase 1: Regex-based pattern detection (fast path)
    violations = detect_dangerous_patterns(command)

    # Phase 2: Lightweight AST parsing
    try:
        root = parse_shell(command)
    except ValueError as err:
        violations.append(f"parse error: {err}")
        return ParseForSecurityResult(
            command=command,
            root=None,
            is_safe=False,
            violations=violations,
        )

    # Phase 3: AST-based analysis
    env_vars, operators = analyze_ast(root)
    ast_violations = validate_ast(root)
    violations.extend(ast_violations)

    return ParseForSecurityResult(
        root=root,
        command=command,
        env_vars=env_vars,
        operators=operators,
        is_safe=len(violations) == 0,
        violations=violations,
    )


# ---- Phase 1: Regex pattern detection ----


def detect_dangerous_patterns(command: str) -> List[str]:
    violations: List[str] = []

    if _CMD_SUBST_RE.search(command):
        violations.append("command substitution detected: $()")
    if _BACKTICK_RE.search(command):
        violations.append("backtick substitution detected")
    if _VAR_EXPAND_RE.search(command):
        violations.append("variable expansion detected: ${}")
    if _EVAL_RE.search(command):
        violations.append("eval/exec/source builtin detected")
    if _SUDO_RE.search(command):
        violations.append("privilege escalation detected: sudo/su/doas")
    if _HEX_ESCAPE_RE.search(command):
        violations.append("hex escape sequence detected")

    return violations


# ---- Phase 2: Lightweight shell parser ----


class TokenType(IntEnum):
    WORD = 0
    PIPE = 1
    AMP_AMP = 2
    PIPE_PIPE = 3
    SEMICOLON = 4
    AND = 5
    REDIRECT_OUT = 6
    REDIRECT_APPEND = 7
    REDIRECT_IN = 8
    HEREDOC = 9
    LPAREN = 10
    RPAREN = 11
    LBRACE = 12
    RBRACE = 13
    DOLLAR = 14
    BACKTICK = 15
    NEWLINE = 16
    EOF = 17


@dataclass
class Token:
    typ: TokenType
    value: str
    pos: int

    def __str__(self) -> str:
        return f"tok({self.typ}, {self.value!r}, {self.pos})"


def parse_shell(input_: str) -> ASTNode:
    """Perform a lightweight shell parse (no external deps). Fail-closed."""
    tokens = tokenize(input_)
    return build_ast(tokens)


def tokenize(input_: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    depth = 0
    n = len(input_)

    while i < n:
        ch = input_[i]

        # Skip whitespace
        if ch == " " or ch == "\t":
            i += 1
            continue

        # Newline
        if ch == "\n":
            tokens.append(Token(typ=TokenType.NEWLINE, value="\n", pos=i))
            i += 1
            continue

        # Comments
        if ch == "#":
            end = input_.find("\n", i)
            if end == -1:
                break
            i = end + 1
            continue

        # Quoted strings — skip to closing quote
        if ch == '"' or ch == "'":
            quote = ch
            i += 1  # skip opening quote
            while i < n and input_[i] != quote:
                if input_[i] == "\\" and i + 1 < n:
                    i += 2  # skip escaped char
                else:
                    i += 1
            if i >= n:
                raise ValueError(f"unterminated string starting at position {i}")
            i += 1  # skip closing quote
            continue

        # Dollar in various forms
        if ch == "$":
            if i + 1 < n and input_[i + 1] == "(":
                # Command substitution: $()
                tokens.append(Token(typ=TokenType.DOLLAR, value="$(", pos=i))
                i += 2
                depth += 1
                continue
            # Variable reference
            j = i + 1
            if j < n and input_[j] == "{":
                # ${var}
                j += 1
                while j < n and input_[j] != "}":
                    j += 1
                if j < n:
                    j += 1  # closing }
            else:
                # $var
                while j < n and (input_[j].isalnum() or input_[j] == "_"):
                    j += 1
            tokens.append(Token(typ=TokenType.WORD, value=input_[i:j], pos=i))
            i = j
            continue

        # Backtick
        if ch == "`":
            tokens.append(Token(typ=TokenType.BACKTICK, value="`", pos=i))
            i += 1
            depth += 1
            continue

        # Closing subshell / group
        if ch == ")":
            if depth > 0:
                depth -= 1
            tokens.append(Token(typ=TokenType.RPAREN, value=")", pos=i))
            i += 1
            continue

        if ch == "(":
            depth += 1
            tokens.append(Token(typ=TokenType.LPAREN, value="(", pos=i))
            i += 1
            continue

        # Redirections
        if ch == ">":
            if i + 1 < n and input_[i + 1] == ">":
                tokens.append(Token(typ=TokenType.REDIRECT_APPEND, value=">>", pos=i))
                i += 2
            else:
                tokens.append(Token(typ=TokenType.REDIRECT_OUT, value=">", pos=i))
                i += 1
            continue

        if ch == "<":
            if i + 2 < n and input_[i + 1] == "<" and input_[i + 2] == "<":
                tokens.append(Token(typ=TokenType.HEREDOC, value="<<<", pos=i))
                i += 3
            elif i + 1 < n and input_[i + 1] == "<":
                tokens.append(Token(typ=TokenType.HEREDOC, value="<<", pos=i))
                i += 2
            else:
                tokens.append(Token(typ=TokenType.REDIRECT_IN, value="<", pos=i))
                i += 1
            continue

        # Pipes and operators
        if ch == "|":
            if i + 1 < n and input_[i + 1] == "|":
                tokens.append(Token(typ=TokenType.PIPE_PIPE, value="||", pos=i))
                i += 2
            else:
                tokens.append(Token(typ=TokenType.PIPE, value="|", pos=i))
                i += 1
            continue

        if ch == "&":
            if i + 1 < n and input_[i + 1] == "&":
                tokens.append(Token(typ=TokenType.AMP_AMP, value="&&", pos=i))
                i += 2
            else:
                # background &
                tokens.append(Token(typ=TokenType.WORD, value="&", pos=i))
                i += 1
            continue

        if ch == ";":
            tokens.append(Token(typ=TokenType.SEMICOLON, value=";", pos=i))
            i += 1
            continue

        # Word (command name, argument, etc.)
        j = i
        while j < n:
            c = input_[j]
            if c in " \t\n;|&><()~`#":
                break
            if c == '"' or c == "'":
                # embedded quote in word — skip
                j += 1
                while j < n and input_[j] != c:
                    if input_[j] == "\\" and j + 1 < n:
                        j += 2
                    else:
                        j += 1
                if j < n:
                    j += 1
                continue
            if (
                c == "$"
                and j + 1 < n
                and (
                    input_[j + 1] == "("
                    or input_[j + 1] == "{"
                    or input_[j + 1].isalnum()
                    or input_[j + 1] == "_"
                )
            ):
                # stop word at variable/command substitution
                break
            j += 1
        if j > i:
            tokens.append(Token(typ=TokenType.WORD, value=input_[i:j], pos=i))
        i = j

    tokens.append(Token(typ=TokenType.EOF, value="", pos=i))
    return tokens


def build_ast(tokens: List[Token]) -> ASTNode:
    root = ASTNode(type=NodeType.LIST, value="root")
    i = 0
    n = len(tokens)

    while i < n:
        tok = tokens[i]
        if tok.typ == TokenType.EOF:
            return root
        if tok.typ == TokenType.NEWLINE:
            i += 1
            continue
        if tok.typ == TokenType.WORD:
            # Collect command + arguments until a separator
            cmd = ASTNode(type=NodeType.COMMAND, value=tok.value, pos=tok.pos)
            i += 1
            while i < n:
                nxt = tokens[i]
                if nxt.typ == TokenType.WORD:
                    cmd.children.append(
                        ASTNode(type=NodeType.WORD, value=nxt.value, pos=nxt.pos)
                    )
                    i += 1
                elif nxt.typ in (
                    TokenType.REDIRECT_OUT,
                    TokenType.REDIRECT_APPEND,
                    TokenType.REDIRECT_IN,
                    TokenType.HEREDOC,
                ):
                    redir = ASTNode(
                        type=NodeType.REDIRECT, value=nxt.value, pos=nxt.pos
                    )
                    # next token should be the target
                    i += 1
                    if i < n and tokens[i].typ == TokenType.WORD:
                        redir.children.append(
                            ASTNode(
                                type=NodeType.WORD,
                                value=tokens[i].value,
                                pos=tokens[i].pos,
                            )
                        )
                        i += 1
                    cmd.children.append(redir)
                else:
                    break
            root.children.append(cmd)
        elif tok.typ == TokenType.PIPE:
            # Wrap last two children in a pipeline
            if len(root.children) >= 2:
                last = root.children[-1]
                prev = root.children[-2]
                pipeline = ASTNode(
                    type=NodeType.PIPELINE,
                    value="|",
                    children=[prev, last],
                    pos=tok.pos,
                )
                root.children = root.children[:-2]
                root.children.append(pipeline)
            i += 1
        elif tok.typ in (TokenType.SEMICOLON, TokenType.AMP_AMP, TokenType.PIPE_PIPE):
            op = ASTNode(type=NodeType.OPERATOR, value=tok.value, pos=tok.pos)
            root.children.append(op)
            i += 1
        elif tok.typ == TokenType.LPAREN:
            depth = 1
            sub_tokens: List[Token] = []
            i += 1  # skip (
            start = tok.pos
            while i < n and depth > 0:
                if tokens[i].typ == TokenType.LPAREN:
                    depth += 1
                elif tokens[i].typ == TokenType.RPAREN:
                    depth -= 1
                    if depth == 0:
                        i += 1  # skip )
                        break
                sub_tokens.append(tokens[i])
                i += 1
            sub = build_ast(sub_tokens)
            sub.type = NodeType.SUBSHELL
            sub.pos = start
            root.children.append(sub)
        else:
            i += 1

    return root


# ---- Phase 3: AST analysis ----


def analyze_ast(root: Optional[ASTNode]) -> tuple[List[str], List[str]]:
    env_vars: List[str] = []
    operators: List[str] = []

    if root is None:
        return env_vars, operators

    for child in root.children:
        if child.type == NodeType.COMMAND:
            name = command_name(child)
            if is_env_assignment(child):
                env_vars.append(child.value)
            operators.append(name)
        elif child.type in (NodeType.PIPELINE, NodeType.SUBSHELL):
            env_vars2, ops2 = analyze_ast(child)
            env_vars.extend(env_vars2)
            operators.extend(ops2)
        elif child.type == NodeType.OPERATOR:
            operators.append(child.value)
        elif child.type == NodeType.REDIRECT:
            operators.append(child.value)

    return env_vars, operators


def validate_ast(root: Optional[ASTNode]) -> List[str]:
    if root is None:
        return []

    violations: List[str] = []

    for child in root.children:
        if child.type == NodeType.COMMAND:
            name = command_name(child)
            if name != "" and name not in SAFE_BUILTINS:
                # Unknown command — not necessarily a violation, but flagged.
                # Only flag truly dangerous ones.
                if is_dangerous_command(name):
                    violations.append(f"dangerous command: {name}")
        elif child.type in (NodeType.PIPELINE, NodeType.SUBSHELL):
            violations.extend(validate_ast(child))

    return violations


def command_name(cmd: Optional[ASTNode]) -> str:
    if cmd is None or cmd.type != NodeType.COMMAND:
        return ""
    # Strip any assignment prefix
    val = cmd.value
    if "=" in val:
        idx = val.index("=")
        if idx > 0 and " " not in val[:idx]:
            return ""  # it's an assignment
    return val


def is_env_assignment(node: Optional[ASTNode]) -> bool:
    if node is None or node.type != NodeType.COMMAND:
        return False
    val = node.value
    if "=" in val:
        idx = val.index("=")
        if 0 < idx < len(val) - 1:
            prefix = val[:idx]
            for r in prefix:
                if not (r.isalnum() or r == "_"):
                    return False
            return True
    return False


def is_dangerous_command(name: str) -> bool:
    dangerous = {
        "eval",
        "exec",
        "source",
        "sudo",
        "su",
        "doas",
        "rm",
        "dd",
        "mkfs",
        "format",
        ":(){",  # fork bomb pattern
    }
    return name in dangerous


# ---- Utilities ----


def extract_command_name(command: str) -> str:
    """Extract the first command name from a shell command string.

    Returns empty string on parse failure (fail-closed).
    """
    result = parse_for_security(command)
    if result.root is None:
        return ""
    for child in result.root.children:
        if child.type == NodeType.COMMAND:
            return child.value
    return ""


def has_dangerous_patterns(command: str) -> bool:
    """Check if a command contains any dangerous shell patterns."""
    return len(detect_dangerous_patterns(command)) > 0


def sanitize_for_log(command: str) -> str:
    """Remove sensitive patterns from a command string for logging."""
    sensitive = re.compile(r"(sk-[a-zA-Z0-9_-]{20,}|token[=:]\s*\S+)")
    result = sensitive.sub("[REDACTED]", command)

    # Truncate very long commands
    if len(result) > 500:
        result = result[:500] + "...[truncated]"

    # Remove ANSI escape codes
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    result = ansi.sub("", result)

    return result.strip()


def is_read_only_command(command: str) -> bool:
    """Check if a command is read-only (no side effects)."""
    ro = {
        "echo",
        "printf",
        "cat",
        "head",
        "tail",
        "wc",
        "ls",
        "pwd",
        "whoami",
        "date",
        "env",
        "printenv",
        "which",
        "type",
        "file",
        "stat",
        "readlink",
        "dirname",
        "basename",
        "sort",
        "uniq",
        "tr",
        "cut",
        "diff",
        "comm",
        "tree",
        "df",
        "du",
    }
    name = extract_command_name(command)
    return name in ro


# MaxCommandLength is the maximum allowed command length.
MAX_COMMAND_LENGTH = 10000


def quote_safety(command: str) -> str:
    """Wrap a command for safe shell execution."""
    if not any(c in command for c in " \t\n\"'\\$`|&;><"):
        return command
    # Use single quotes with internal escaping
    out = ["'"]
    for r in command:
        if r == "'":
            out.append("'\"'\"'")
        else:
            out.append(r)
    out.append("'")
    return "".join(out)


def strip_ansi(s: str) -> str:
    """Remove ANSI escape codes from a string."""
    ansi = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    return ansi.sub("", s)


def is_quiet(s: str) -> bool:
    """Check if a string contains only whitespace or is empty."""
    return s.strip() == ""


def truncate_with_suffix(s: str, max_len: int, suffix: str) -> str:
    """Truncate a string to max_len, adding suffix if truncated."""
    if len(s) <= max_len:
        return s
    return s[: max_len - len(suffix)] + suffix


def redact_sensitive(s: str) -> str:
    """Remove tokens, keys, and passwords from strings."""
    # sk-ant-* tokens
    t1 = re.compile(r"sk-[a-zA-Z0-9_-]{20,}")
    s = t1.sub("[REDACTED]", s)

    # API key patterns
    t2 = re.compile(r"(?i)(?:api[_-]?key|token|secret|password)[=:]\s*\S+")
    s = t2.sub("[REDACTED]", s)

    return s


def is_ascii(s: str) -> bool:
    """Check if a string contains only ASCII characters."""
    return all(ord(r) <= 0x7F for r in s)
