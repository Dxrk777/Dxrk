# SPDX-License-Identifier: MIT
""" BibTeX, APA and MLA formatting."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    abstract: str = ""
    url: str = ""
    year: int = 0


def _last_name(full: str) -> str:
    parts = full.split()
    if not parts:
        return full
    return parts[-1]


def _normalize_key(s: str) -> str:
    out: list[str] = []
    for ch in s:
        if "a" <= ch <= "z":
            out.append(ch)
        elif "A" <= ch <= "Z":
            out.append(ch.lower())
        elif ch in " -":
            continue
        else:
            out.append(ch)
    key = "".join(out)
    if not key:
        return "paper"
    return key


def _bibtex_escape(s: str) -> str:
    for src, dst in (
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
    ):
        s = s.replace(src, dst)
    return s


def _format_bibtex_authors(authors: list[str]) -> str:
    out: list[str] = []
    for a in authors:
        parts = a.strip().split()
        if len(parts) > 1:
            out.append(parts[-1] + ", " + " ".join(parts[:-1]))
        else:
            out.append(a.strip())
    return " and ".join(out)


def format_bibtex(p: Paper) -> str:
    key = "paper"
    if p.authors:
        key = _normalize_key(_last_name(p.authors[0]))
        if p.year > 0:
            key += str(p.year)
    lines = [f"@article{{{key},"]
    if p.title:
        lines.append(f"\ttitle = {{{_bibtex_escape(p.title)}}},")
    if p.authors:
        lines.append(f"\tauthor = {{{_format_bibtex_authors(p.authors)}}},")
    if p.year > 0:
        lines.append(f"\tyear = {{{p.year}}},")
    if p.doi:
        lines.append(f"\tdoi = {{{p.doi}}},")
    if p.abstract:
        lines.append(f"\tabstract = {{{_bibtex_escape(p.abstract)}}},")
    if p.url:
        lines.append(f"\turl = {{{p.url}}},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _fmt_apa_invert(full: str) -> str:
    parts = full.strip().split()
    if not parts:
        return full
    last = parts[-1]
    prefixes = {"van", "von", "de", "del", "la"}
    if len(parts) > 1 and parts[0] in prefixes:
        last = parts[0] + " " + last
        parts = parts[1:]
    if len(parts) <= 1:
        return last
    initials = [p[0] + "." for p in parts[:-1]]
    return last + ", " + " ".join(initials)


def format_apa(p: Paper) -> str:
    out: list[str] = []
    n = len(p.authors)
    for i, a in enumerate(p.authors):
        if i > 0:
            if i == n - 1 and n > 2:
                out.append(", & ")
            else:
                out.append(", ")
        out.append(_fmt_apa_invert(a))
    if n == 0:
        out.append("Anonymous")
    out.append(". ")
    if p.year > 0:
        out.append(f"({p.year}). ")
    else:
        out.append("(n.d.). ")
    if p.title:
        out.append(p.title)
    if p.doi:
        out.append(" https://doi.org/" + p.doi)
    elif p.url:
        out.append(" " + p.url)
    return "".join(out)


def _fmt_mla(full: str, first: bool) -> str:
    if not first:
        return full.strip()
    parts = full.strip().split()
    if len(parts) <= 1:
        return full.strip()
    return parts[-1] + ", " + " ".join(parts[:-1])


def format_mla(p: Paper) -> str:
    out: list[str] = []
    for i, a in enumerate(p.authors):
        if i > 0:
            out.append(", ")
        out.append(_fmt_mla(a, i == 0))
    if p.authors:
        out.append(". ")
    if p.title:
        out.append(p.title)
    if p.year > 0:
        out.append(f". {p.year}. ")
    else:
        out.append(". n.d. ")
    if p.url:
        out.append(p.url)
    return "".join(out)
