# SPDX-License-Identifier: MIT
""" Crossref API provider."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from .provider import Paper

_logger = logging.getLogger("dxrk.scholar")

CROSSREF_API = "https://api.crossref.org/works"
CROSSREF_USER_AGENT = "dxrk-scholar/1.0 (mailto:research@dxrk.ai)"


class CrossrefProvider:
    """Searches papers on the Crossref API."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15)

    def name(self) -> str:
        return "crossref"

    def _map_message(self, m: dict) -> Paper:
        authors: list[str] = []
        for a in m.get("author", []):
            given = a.get("given", "")
            family = a.get("family", "")
            full = f"{given} {family}".strip()
            if full:
                authors.append(full)
        year = 0
        parts = m.get("issued", {}).get("date-parts", [])
        if parts and parts[0]:
            year = int(parts[0][0])
        title = ""
        titles = m.get("title", [])
        if titles:
            title = titles[0]
        pdf_url = ""
        for link in m.get("link", []):
            url = link.get("URL", "")
            if url:
                pdf_url = url
                break
        return Paper(
            title=title,
            authors=authors,
            doi=m.get("DOI", ""),
            abstract=(m.get("abstract", "") or "").strip(),
            url=m.get("URL", ""),
            pdf_url=pdf_url,
            year=year,
            source="crossref",
        )

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        try:
            resp = self._client.get(
                CROSSREF_API,
                params={"query": query, "rows": str(limit)},
                headers={"User-Agent": CROSSREF_USER_AGENT},
            )
        except httpx.RequestError as err:
            _logger.warning("crossref request failed: %s", err)
            return [], f"crossref: request: {err}"
        if resp.status_code != 200:
            return [], f"crossref: status {resp.status_code}"
        try:
            data = resp.json()
        except ValueError as err:
            return [], f"crossref: decode: {err}"
        papers = [
            self._map_message(i) for i in data.get("message", {}).get("items", [])
        ]
        return papers, None

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]:
        try:
            resp = self._client.get(
                f"{CROSSREF_API}/{quote(doi, safe='')}",
                headers={"User-Agent": CROSSREF_USER_AGENT},
            )
        except httpx.RequestError as err:
            _logger.warning("crossref request failed: %s", err)
            return None, f"crossref: request: {err}"
        if resp.status_code != 200:
            return None, f"crossref: status {resp.status_code}"
        try:
            data = resp.json()
        except ValueError as err:
            return None, f"crossref: decode: {err}"
        paper = self._map_message(data.get("message", {}))
        return paper, None


def NewCrossrefProvider() -> CrossrefProvider:
    """Build a CrossrefProvider with a 15s client timeout."""
    return CrossrefProvider()
