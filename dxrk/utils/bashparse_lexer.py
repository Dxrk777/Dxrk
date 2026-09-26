# SPDX-License-Identifier: MIT
"""Bash lexer: token types and word splitting with position tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from dxrk.utils.bashparse_model import Location


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
                "}" if self._peek(1) == "{" else ")"
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
