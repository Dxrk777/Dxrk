# SPDX-License-Identifier: MIT
""" paper model and provider protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Paper:
    """A scholarly paper returned by a provider."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str = ""
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    year: int = 0
    source: str = ""


class Provider(Protocol):
    """A source of scholarly papers."""

    def name(self) -> str: ...

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]: ...

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]: ...
