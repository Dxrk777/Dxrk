# SPDX-License-Identifier: MIT
""" multi-provider aggregator."""

from __future__ import annotations

from collections.abc import Sequence

from .provider import Paper, Provider


class Scholar:
    """Aggregates search results from multiple providers."""

    def __init__(self, providers: Sequence[Provider] | None = None) -> None:
        self._providers: list[Provider] = list(providers) if providers else []

    def Search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        """Search all providers and merge results; provider errors are skipped."""
        if not self._providers:
            return [], None
        papers: list[Paper] = []
        for p in self._providers:
            items, err = p.search(query, limit)
            if err is not None:
                continue
            papers.extend(items)
            if limit > 0 and len(papers) > limit:
                papers = papers[:limit]
        return papers, None

    def FetchByDOI(self, doi: str) -> tuple[Paper | None, str | None]:
        """Return the first paper found by any provider for the DOI."""
        if not self._providers:
            return None, None
        for p in self._providers:
            paper, err = p.fetch_by_doi(doi)
            if err is None and paper is not None:
                return paper, None
        return None, None


def New(providers: Sequence[Provider] | None = None) -> Scholar:
    """Build a Scholar with the given providers."""
    return Scholar(providers)
