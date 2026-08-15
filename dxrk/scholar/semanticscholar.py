# SPDX-License-Identifier: MIT
"""Semantic Scholar API client."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from .provider import Paper

SEMANTICSCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
SEMANTICSCHOLAR_FIELDS = "title,abstract,year,externalIds,authors,openAccessPdf,url"
SEMANTICSCHOLAR_USER_AGENT = "dxrk-scholar/1.0"

_logger = logging.getLogger("dxrk.scholar")


def _map_ss_paper(item: dict[str, Any]) -> Paper | None:
    title = (item.get("title") or "").strip()
    if not title:
        return None
    external = item.get("externalIds")
    doi = ""
    if isinstance(external, dict):
        doi = external.get("DOI") or ""
    pdf_url = ""
    oa_pdf = item.get("openAccessPdf")
    if isinstance(oa_pdf, dict):
        pdf_url = oa_pdf.get("url") or ""
    authors = []
    for a in item.get("authors") or []:
        if not isinstance(a, dict):
            continue
        name = (a.get("name") or "").strip()
        if name:
            authors.append(name)
    url = (item.get("url") or "").strip()
    if not url and doi:
        url = "https://doi.org/" + doi
    year = 0
    try:
        year = int(item.get("year") or 0)
    except (TypeError, ValueError):
        year = 0
    return Paper(
        title=title,
        authors=authors,
        doi=doi,
        abstract=(item.get("abstract") or "").strip(),
        url=url,
        pdf_url=pdf_url,
        year=year,
        source="semantic_scholar",
    )


class SemanticScholarProvider:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15)

    def name(self) -> str:
        return "semantic_scholar"

    def _get(self, url: str) -> tuple[httpx.Response | None, str | None]:
        try:
            resp = self._client.get(
                url, headers={"User-Agent": SEMANTICSCHOLAR_USER_AGENT}
            )
        except httpx.RequestError as err:
            return None, f"semantic_scholar: request: {err}"
        if resp.status_code in (404, 429):
            return None, None
        if resp.status_code != 200:
            return None, f"semantic_scholar: status {resp.status_code}"
        return resp, None

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        if limit <= 0:
            limit = 10
        url = f"{SEMANTICSCHOLAR_API}/paper/search?query={quote(query)}&limit={limit}&fields={SEMANTICSCHOLAR_FIELDS}"
        resp, err = self._get(url)
        if err is not None:
            return [], err
        if resp is None:
            return [], None
        try:
            data = resp.json()
        except ValueError as verr:
            return [], f"semantic_scholar: decode search: {verr}"
        papers: list[Paper] = []
        for item in data.get("data") or []:
            if not isinstance(item, dict):
                continue
            paper = _map_ss_paper(item)
            if paper is not None:
                papers.append(paper)
        return papers, None

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]:
        url = f"{SEMANTICSCHOLAR_API}/paper/DOI:{quote(doi, safe='')}?fields={SEMANTICSCHOLAR_FIELDS}"
        resp, err = self._get(url)
        if err is not None:
            return None, err
        if resp is None:
            return None, None
        try:
            data = resp.json()
        except ValueError as verr:
            return None, f"semantic_scholar: decode doi lookup: {verr}"
        if not isinstance(data, dict):
            return None, None
        return _map_ss_paper(data), None


def NewSemanticScholarProvider() -> SemanticScholarProvider:
    return SemanticScholarProvider()
