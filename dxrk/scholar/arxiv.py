# SPDX-License-Identifier: MIT
""" arXiv API provider."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import httpx

from .provider import Paper

_logger = logging.getLogger("dxrk.scholar")

ARXIV_API = "http://export.arxiv.org/api/query"
ARXIV_USER_AGENT = "dxrk-scholar/1.0"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivProvider:
    """Searches papers on the arXiv API."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15)

    def name(self) -> str:
        return "arxiv"

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        try:
            resp = self._client.get(
                ARXIV_API,
                params={
                    "search_query": f"all:{query}",
                    "max_results": str(limit),
                },
                headers={"User-Agent": ARXIV_USER_AGENT},
            )
        except httpx.RequestError as err:
            _logger.warning("arxiv request failed: %s", err)
            return [], f"arxiv: request: {err}"
        if resp.status_code != 200:
            return [], f"arxiv: status {resp.status_code}"
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as err:
            return [], f"arxiv: decode: {err}"
        papers: list[Paper] = []
        for entry in root.iter(f"{_ATOM}entry"):
            published = entry.findtext(f"{_ATOM}published", "")
            year = 0
            if len(published) >= 4:
                try:
                    year = int(published[:4])
                except ValueError:
                    year = 0
            authors = [a.text or "" for a in entry.iter(f"{_ATOM}name")]
            papers.append(
                Paper(
                    title=entry.findtext(f"{_ATOM}title", ""),
                    authors=authors,
                    abstract=(entry.findtext(f"{_ATOM}summary", "") or "").strip(),
                    url=entry.findtext(f"{_ATOM}id", ""),
                    year=year,
                    source="arxiv",
                )
            )
        return papers, None

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]:
        return None, None


def NewArxivProvider() -> ArxivProvider:
    """Build an ArxivProvider with a 15s client timeout."""
    return ArxivProvider()
