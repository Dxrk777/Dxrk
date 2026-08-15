# SPDX-License-Identifier: MIT
""" PubMed API provider."""

from __future__ import annotations

import logging

import httpx

from .provider import Paper

_logger = logging.getLogger("dxrk.scholar")

PUBMED_ESEARCH_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_API = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_USER_AGENT = "dxrk-scholar/1.0 (mailto:research@dxrk.ai)"


class PubMedProvider:
    """Searches papers on the PubMed E-utilities API."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=15)

    def name(self) -> str:
        return "pubmed"

    def _get(self, url: str, params: dict) -> tuple[httpx.Response | None, str | None]:
        try:
            resp = self._client.get(
                url, params=params, headers={"User-Agent": PUBMED_USER_AGENT}
            )
        except httpx.RequestError as err:
            return None, f"pubmed: request: {err}"
        if resp.status_code != 200:
            if resp.status_code in (404, 429):
                return None, None
            return None, f"pubmed: status {resp.status_code}"
        return resp, None

    def search(self, query: str, limit: int) -> tuple[list[Paper], str | None]:
        if limit <= 0:
            limit = 10
        ids, err = self._search_ids(query, limit)
        if err is not None:
            return [], err
        return self._fetch_summaries(ids)

    def _search_ids(self, query: str, limit: int) -> tuple[list[str], str | None]:
        resp, err = self._get(
            PUBMED_ESEARCH_API,
            {"db": "pubmed", "term": query, "retmax": str(limit), "retmode": "json"},
        )
        if err is not None or resp is None:
            return [], err
        try:
            data = resp.json()
        except ValueError as err:
            return [], f"pubmed: decode search: {err}"
        return data.get("esearchresult", {}).get("idlist", []), None

    def _fetch_summaries(self, ids: list[str]) -> tuple[list[Paper], str | None]:
        if not ids:
            return [], None
        resp, err = self._get(
            PUBMED_ESUMMARY_API,
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
        )
        if err is not None or resp is None:
            return [], err
        try:
            data = resp.json()
        except ValueError as err:
            return [], f"pubmed: decode summary: {err}"
        result = data.get("result", {})
        papers: list[Paper] = []
        for uid in ids:
            s = result.get(uid)
            if not isinstance(s, dict):
                continue
            paper = map_pubmed_summary(s)
            if paper is not None:
                papers.append(paper)
        return papers, None

    def fetch_by_doi(self, doi: str) -> tuple[Paper | None, str | None]:
        ids, err = self._search_ids(f'{doi}"[doi]"', 1)
        if err is not None:
            return None, err
        if not ids:
            return None, None
        papers, err = self._fetch_summaries(ids[:1])
        if err is not None:
            return None, err
        if not papers:
            return None, None
        return papers[0], None


def pubmed_year(pubdate: str) -> int:
    """Extract the leading 4-digit year from a pubdate string."""
    year = 0
    for ch in pubdate:
        if not ch.isdigit():
            break
        year = year * 10 + int(ch)
    return year


def map_pubmed_summary(s: dict) -> Paper | None:
    """Map a PubMed summary JSON object to a Paper, or None if title is empty."""
    title = s.get("title", "") or ""
    if not title.strip():
        return None
    authors = [a.get("name", "").strip() for a in s.get("authors", [])]
    authors = [a for a in authors if a]
    uid = s.get("uid", "") or ""
    url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/" if uid else ""
    return Paper(
        title=title.strip(),
        authors=authors,
        doi=s.get("doi", "") or "",
        abstract=(s.get("abstract", "") or "").strip(),
        url=url,
        year=pubmed_year(s.get("pubdate", "") or ""),
        source="pubmed",
    )


def NewPubMedProvider() -> PubMedProvider:
    """Build a PubMedProvider with a 15s client timeout."""
    return PubMedProvider()
