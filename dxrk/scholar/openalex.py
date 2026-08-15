# SPDX-License-Identifier: MIT
""" OpenAlex API provider."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from .provider import Paper

_logger = logging.getLogger("dxrk.scholar")

OPENALEX_API = "https://api.openalex.org/works"
OPENALEX_USER_AGENT = "dxrk-scholar/1.0 (mailto:research@dxrk.ai)"
DOI_PREFIX = "https://doi.org/"


class OpenAlexProvider:
    """Searches papers on the OpenAlex API."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15)

    def name(self) -> str:
        return "openalex"

    def _get(self, url: str) -> tuple[httpx.Response | None, str | None]:
        try:
            resp = self._client.get(url, headers={"User-Agent": OPENALEX_USER_AGENT})
        except httpx.RequestError as err:
            return None, f"openalex: request: {err}"
        if resp.status_code != 200:
            if resp.status_code in (404, 429):
                return None, None
            return None, f"openalex: status {resp.status_code}"
        return resp, None

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        if limit <= 0:
            limit = 10
        resp, err = self._get(f"{OPENALEX_API}?search={quote(query)}&per-page={limit}")
        if err is not None or resp is None:
            return [], err
        try:
            data = resp.json()
        except ValueError as err:
            return [], f"openalex: decode search: {err}"
        papers: list[Paper] = []
        for w in data.get("results", []):
            paper = map_openalex_work(w)
            if paper is not None:
                papers.append(paper)
        return papers, None

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]:
        resp, err = self._get(f"{OPENALEX_API}/doi:{quote(doi, safe='')}")
        if err is not None or resp is None:
            return None, err
        try:
            data = resp.json()
        except ValueError as err:
            return None, f"openalex: decode doi lookup: {err}"
        return map_openalex_work(data), None


def rebuild_openalex_abstract(inverted: dict | None) -> str:
    """Rebuild an abstract from its inverted index representation."""
    if not inverted:
        return ""
    tokens: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            tokens.append((int(pos), word))
    tokens.sort(key=lambda t: t[0])
    return " ".join(w for _, w in tokens)


def map_openalex_work(work: dict) -> Paper | None:
    """Map an OpenAlex work JSON object to a Paper, or None if title is empty."""
    title = work.get("display_name", "")
    if not title.strip():
        return None
    doi = work.get("doi", "") or ""
    if doi.startswith(DOI_PREFIX):
        doi = doi[len(DOI_PREFIX) :]
    authors = [
        a.get("author", {}).get("display_name", "").strip()
        for a in work.get("authorships", [])
    ]
    authors = [a for a in authors if a]
    loc = work.get("primary_location", {}) or {}
    url = loc.get("landing_page_url", "") or ""
    if not url and doi:
        url = DOI_PREFIX + doi
    pdf_url = loc.get("pdf_url", "") or ""
    if not pdf_url:
        oa = work.get("open_access", {}) or {}
        pdf_url = oa.get("oa_url", "") or ""
    return Paper(
        title=title.strip(),
        authors=authors,
        doi=doi,
        abstract=rebuild_openalex_abstract(work.get("abstract_inverted_index")),
        url=url,
        pdf_url=pdf_url,
        year=int(work.get("publication_year") or 0),
        source="openalex",
    )


def NewOpenAlexProvider() -> OpenAlexProvider:
    """Build an OpenAlexProvider with a 15s client timeout."""
    return OpenAlexProvider()
