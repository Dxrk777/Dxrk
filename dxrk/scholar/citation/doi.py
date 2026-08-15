# SPDX-License-Identifier: MIT
""" DOI validation and extraction."""

from __future__ import annotations

import re

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$")


def valid_doi(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    return bool(DOI_PATTERN.match(s.upper()))


def normalize_doi(s: str) -> str:
    return s.strip().lower()


def extract_doi(s: str) -> str:
    idx = s.lower().find("10.")
    if idx < 0:
        return ""
    candidate = s[idx:]
    for i, ch in enumerate(candidate):
        if ch in " \t\n,":
            candidate = candidate[:i]
            break
    candidate = candidate.rstrip(".,;:)!?")
    if valid_doi(candidate):
        return candidate
    return ""
