# SPDX-License-Identifier: MIT
"""Tests for dxrk.scholar (mirrors internal/scholar/*_test.go)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx
import pytest

from dxrk.scholar import (
    ArxivProvider,
    CrossrefProvider,
    New,
    NewArxivProvider,
    NewCrossrefProvider,
    NewOpenAlexProvider,
    NewPubMedProvider,
    NewSemanticScholarProvider,
    OpenAlexProvider,
    Paper,
    PubMedProvider,
    RegisterTools,
    Scholar,
    SemanticScholarProvider,
)
from dxrk.scholar.citation import (
    Paper as CitePaper,
)
from dxrk.scholar.citation.doi import extract_doi, normalize_doi, valid_doi
from dxrk.scholar.citation.format import format_apa, format_bibtex, format_mla
from dxrk.scholar.openalex import map_openalex_work, rebuild_openalex_abstract
from dxrk.scholar.pubmed import map_pubmed_summary, pubmed_year
from dxrk.scholar.semanticscholar import _map_ss_paper
from dxrk.tools import Registry


class FakeProvider:
    """Test provider with injectable functions (mirrors fakeProvider)."""

    def __init__(self, name="", search_fn=None, fetch_fn=None):
        self._name = name
        self._search_fn = search_fn
        self._fetch_fn = fetch_fn

    def name(self) -> str:
        return self._name

    def search(self, query, limit):
        if self._search_fn is not None:
            return self._search_fn(query, limit)
        return [], None

    def fetch_by_doi(self, doi):
        if self._fetch_fn is not None:
            return self._fetch_fn(doi)
        return None, None


class FakeClient:
    """In-memory httpx-like client."""

    def __init__(self, status_code=200, payload=None):
        self._status = status_code
        self._payload = payload
        self._requests: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, **kwargs):
        self._requests.append((url, params))
        if self._status != 200:
            return httpx.Response(self._status, request=httpx.Request("GET", url))
        if isinstance(self._payload, str):
            return httpx.Response(
                200, text=self._payload, request=httpx.Request("GET", url)
            )
        import json as _json

        return httpx.Response(
            200,
            json=_json.loads(_json.dumps(self._payload or {})),
            request=httpx.Request("GET", url),
        )


def _paper(**kw: object) -> Paper:
    base: dict[str, object] = {
        "title": "",
        "authors": [],
        "doi": "",
        "abstract": "",
        "url": "",
        "pdf_url": "",
        "year": 0,
        "source": "",
    }
    base.update(kw)
    return Paper(
        title=str(base["title"]),
        authors=list(base["authors"]),
        doi=str(base["doi"]),
        abstract=str(base["abstract"]),
        url=str(base["url"]),
        pdf_url=str(base["pdf_url"]),
        year=int(base["year"]),
        source=str(base["source"]),
    )


class TestScholar:
    def test_new_and_search(self):
        one = FakeProvider(
            name="one",
            search_fn=lambda q, limit: (
                [_paper(title="a", source="one"), _paper(title="b", source="one")],
                None,
            ),
        )
        two = FakeProvider(
            name="two",
            search_fn=lambda q, limit: ([_paper(title="c", source="two")], None),
        )
        s = New([one, two])
        papers, err = s.Search("query", 0)
        assert err is None
        assert [p.title for p in papers] == ["a", "b", "c"]
        papers, err = s.Search("query", 2)
        assert err is None
        assert len(papers) == 2
        s2 = New()
        papers, err = s2.Search("query", 0)
        assert papers == []
        assert err is None

    def test_search_skips_errors(self):
        bad = FakeProvider(name="bad", search_fn=lambda q, limit: ([], "boom"))
        good = FakeProvider(
            name="good",
            search_fn=lambda q, limit: ([_paper(title="ok", source="good")], None),
        )
        s = New([bad, good])
        papers, err = s.Search("query", 0)
        assert err is None
        assert len(papers) == 1
        assert papers[0].title == "ok"

    def test_fetch_by_doi(self):
        first = FakeProvider(name="first", fetch_fn=lambda doi: (None, None))
        second = FakeProvider(
            name="second", fetch_fn=lambda doi: (_paper(title="found"), None)
        )
        s = New([first, second])
        paper, err = s.FetchByDOI("10.1000/abc")
        assert err is None
        assert paper is not None
        assert paper.title == "found"
        s2 = New()
        paper, err = s2.FetchByDOI("10.1000/abc")
        assert paper is None
        assert err is None


class TestCitationDOI:
    def test_valid_doi(self):
        cases = {
            "": False,
            "   ": False,
            "10.1000": False,
            "10.1000/": False,
            "10.1/xyz": False,
            "10.1000/foo bar": False,
            "10.1000/ABC.123": True,
            "10.1000/xyz123": True,
            "10.48550/arXiv.2301.00234": True,
            "10.1145/3292500.3330701": True,
            "10.1038/nphys1505": True,
        }
        for s, want in cases.items():
            assert valid_doi(s) is want, s

    def test_extract_doi(self):
        cases = {
            "https://doi.org/10.1000/abc123": "10.1000/abc123",
            "ver doi 10.1000/xyz123 para más": "10.1000/xyz123",
            "Article DOI 10.1000/ABC.DEF": "10.1000/ABC.DEF",
            "there is nothing here": "",
            "doi 10.1000/abc.": "10.1000/abc",
        }
        for s, want in cases.items():
            assert extract_doi(s) == want, s

    def test_normalize_doi(self):
        assert normalize_doi("  Doi.Org/10.1000/ABC.123  ") == "doi.org/10.1000/abc.123"


class TestCitationFormat:
    def _sample(self) -> CitePaper:
        return CitePaper(
            title="Attention Is All You Need",
            authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
            doi="10.48550/arXiv.1706.03762",
            url="https://arxiv.org/abs/1706.03762",
            year=2017,
        )

    def test_format_bibtex(self):
        out = format_bibtex(self._sample())
        assert out.startswith("@article{vaswani2017,\n")
        assert "title = {Attention Is All You Need}" in out
        assert "author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki}" in out
        assert "doi = {10.48550/arXiv.1706.03762}" in out
        assert "year = {2017}" in out
        assert "url = {https://arxiv.org/abs/1706.03762}" in out

    def test_format_apa(self):
        out = format_apa(self._sample())
        assert "Vaswani, A., Shazeer, N., & Parmar, N." in out
        assert "(2017)." in out
        assert "Attention Is All You Need" in out
        assert "https://doi.org/10.48550/arXiv.1706.03762" in out

    def test_format_apa_undated(self):
        out = format_apa(CitePaper(title="Undated", authors=["Jane Doe"]))
        assert "(n.d.)." in out

    def test_format_apa_particle(self):
        out = format_apa(
            CitePaper(title="T", authors=["Ludwig van Beethoven"], year=1801)
        )
        assert "Beethoven, L." in out

    def test_format_mla(self):
        out = format_mla(self._sample())
        assert "Vaswani, Ashish" in out
        assert "Noam Shazeer" in out
        assert "2017." in out
        assert "Attention Is All You Need" in out
        assert "https://arxiv.org/abs/1706.03762" in out


_ARXIV_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762</id>
    <published>2017-06-12T10:00:00Z</published>
    <title>Attention Is All You Need</title>
    <summary>  We propose the Transformer.  </summary>
    <author><name>Ashish Vaswani</name></author>
    <author><name>Noam Shazeer</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/9999.99999</id>
    <published>garbage-date</published>
    <title>Second Paper</title>
    <summary>Summary two.</summary>
  </entry>
</feed>
"""


class TestArxiv:
    def test_search_parses_feed(self):
        p = ArxivProvider(client=FakeClient(payload=_ARXIV_FEED))
        papers, err = p.search("attention", 5)
        assert err is None
        assert len(papers) == 2
        first = papers[0]
        assert first.title == "Attention Is All You Need"
        assert first.authors == ["Ashish Vaswani", "Noam Shazeer"]
        assert first.abstract == "We propose the Transformer."
        assert first.url == "http://arxiv.org/abs/1706.03762"
        assert first.year == 2017
        assert first.source == "arxiv"
        assert papers[1].year == 0

    def test_search_status_error(self):
        p = ArxivProvider(client=FakeClient(status_code=500))
        papers, err = p.search("attention", 5)
        assert papers == []
        assert err == "arxiv: status 500"

    def test_fetch_by_doi(self):
        p = ArxivProvider(client=FakeClient(payload=_ARXIV_FEED))
        paper, err = p.fetch_by_doi("10.1000/abc")
        assert paper is None
        assert err is None


class TestCrossref:
    def test_search_maps_items(self):
        payload = {
            "message": {
                "items": [
                    {
                        "title": ["Paper One"],
                        "author": [
                            {"given": "Jane", "family": "Doe"},
                            {"given": "  ", "family": "  "},
                        ],
                        "DOI": "10.1000/one",
                        "abstract": "  Abstract one.  ",
                        "URL": "https://example.com/one",
                        "link": [{"URL": ""}, {"URL": "https://example.com/one.pdf"}],
                        "issued": {"date-parts": [[2021, 3, 1]]},
                    }
                ]
            }
        }
        p = CrossrefProvider(client=FakeClient(payload=payload))
        papers, err = p.search("paper", 5)
        assert err is None
        assert len(papers) == 1
        assert papers[0].title == "Paper One"
        assert papers[0].authors == ["Jane Doe"]
        assert papers[0].doi == "10.1000/one"
        assert papers[0].abstract == "Abstract one."
        assert papers[0].pdf_url == "https://example.com/one.pdf"
        assert papers[0].year == 2021
        assert papers[0].source == "crossref"

    def test_search_status_error(self):
        p = CrossrefProvider(client=FakeClient(status_code=500))
        papers, err = p.search("paper", 5)
        assert papers == []
        assert err == "crossref: status 500"

    def test_fetch_by_doi(self):
        payload = {
            "message": {
                "title": ["Found Paper"],
                "author": [{"given": "John", "family": "Smith"}],
                "DOI": "10.1000/abc",
                "issued": {"date-parts": [[2020]]},
            }
        }
        p = CrossrefProvider(client=FakeClient(payload=payload))
        paper, err = p.fetch_by_doi("10.1000/abc")
        assert err is None
        assert paper is not None
        assert paper.title == "Found Paper"
        assert paper.authors == ["John Smith"]
        assert paper.year == 2020
        assert paper.source == "crossref"


class TestOpenAlex:
    def test_map_openalex_work(self):
        work = {
            "display_name": "Attention Is All You Need",
            "doi": "https://doi.org/10.5555/3295222.3295349",
            "publication_year": 2017,
            "abstract_inverted_index": {
                "attention": [0],
                "you": [2],
                "all": [1],
                "need": [3],
            },
            "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
            "primary_location": {
                "landing_page_url": "https://arxiv.org/abs/1706.03762",
                "pdf_url": "https://arxiv.org/pdf/1706.03762",
            },
            "open_access": {"oa_url": "https://arxiv.org/pdf/1706.03762v3"},
        }
        paper = map_openalex_work(work)
        assert paper is not None
        assert paper.title == "Attention Is All You Need"
        assert paper.doi == "10.5555/3295222.3295349"
        assert paper.year == 2017
        assert paper.source == "openalex"
        assert paper.abstract == "attention all you need"
        assert paper.authors == ["Ashish Vaswani"]
        assert paper.url == "https://arxiv.org/abs/1706.03762"
        assert paper.pdf_url == "https://arxiv.org/pdf/1706.03762"

    def test_map_openalex_work_empty_title(self):
        assert map_openalex_work({}) is None

    def test_map_openalex_work_fallbacks(self):
        work = {
            "display_name": "No Location",
            "doi": "https://doi.org/10.1234/abc",
            "primary_location": {},
            "open_access": {"oa_url": "https://example.com/paper.pdf"},
        }
        paper = map_openalex_work(work)
        assert paper is not None
        assert paper.url == "https://doi.org/10.1234/abc"
        assert paper.pdf_url == "https://example.com/paper.pdf"
        assert paper.authors == []

    def test_rebuild_openalex_abstract(self):
        assert rebuild_openalex_abstract({}) == ""
        assert rebuild_openalex_abstract(None) == ""
        inverted = {"world": [4], "hello": [0], "go": [2], "the": [3], "gopher": [1]}
        assert rebuild_openalex_abstract(inverted) == "hello gopher go the world"

    def test_search_and_fetch(self):
        payload = {
            "results": [
                {
                    "display_name": "OpenAlex Paper",
                    "doi": "https://doi.org/10.1000/xyz",
                    "publication_year": 2022,
                    "abstract_inverted_index": {"a": [0]},
                    "authorships": [],
                    "primary_location": {},
                    "open_access": {},
                }
            ]
        }
        p = OpenAlexProvider(client=FakeClient(payload=payload))
        papers, err = p.search("query", 5)
        assert err is None
        assert len(papers) == 1
        assert papers[0].title == "OpenAlex Paper"
        assert papers[0].year == 2022

    def test_search_status_error(self):
        p = OpenAlexProvider(client=FakeClient(status_code=500))
        papers, err = p.search("query", 5)
        assert papers == []
        assert err == "openalex: status 500"


class TestPubMed:
    def test_map_pubmed_summary(self):
        s = {
            "uid": "36303072",
            "title": "A Study of Something",
            "pubdate": "2023 Jan 15",
            "doi": "10.1234/study",
            "abstract": "Some abstract text.",
            "authors": [{"name": "Jane Doe"}, {"name": "John Smith"}, {"name": "  "}],
        }
        paper = map_pubmed_summary(s)
        assert paper is not None
        assert paper.title == "A Study of Something"
        assert paper.doi == "10.1234/study"
        assert paper.year == 2023
        assert paper.source == "pubmed"
        assert paper.url == "https://pubmed.ncbi.nlm.nih.gov/36303072/"
        assert paper.authors == ["Jane Doe", "John Smith"]

    def test_map_pubmed_summary_empty_title(self):
        assert map_pubmed_summary({}) is None

    def test_pubmed_year(self):
        cases = {
            "2023 Jan 15": 2023,
            "2022": 2022,
            "2023 Jul-Aug": 2023,
            "": 0,
            "not a date": 0,
            "20A": 20,
        }
        for s, want in cases.items():
            assert pubmed_year(s) == want, s

    def test_fetch_summaries_empty(self):
        p = PubMedProvider(client=FakeClient(payload={}))
        papers, err = p._fetch_summaries([])
        assert papers == []
        assert err is None

    def test_fetch_by_doi(self):
        payload = {
            "esearchresult": {"idlist": ["36303072"]},
        }
        p = PubMedProvider(client=FakeClient(payload=payload))
        paper, err = p.fetch_by_doi("10.1000/abc")
        assert err is None
        assert paper is None  # fetch_summaries no mapea el resultado sin summary

    def test_fetch_by_doi_not_found(self):
        p = PubMedProvider(client=FakeClient(payload={"esearchresult": {"idlist": []}}))
        paper, err = p.fetch_by_doi("10.1000/abc")
        assert paper is None
        assert err is None


class TestSemanticScholar:
    def test_map_ss_paper(self):
        item = {
            "paperId": "abc123",
            "title": "SS Paper",
            "abstract": "SS abstract.",
            "year": 2024,
            "externalIds": {"DOI": "10.1000/ss"},
            "authors": [{"name": "Alice"}, {"name": "  "}],
            "openAccessPdf": {"url": "https://example.com/ss.pdf"},
            "url": "https://example.com/ss",
        }
        paper = _map_ss_paper(item)
        assert paper is not None
        assert paper.title == "SS Paper"
        assert paper.doi == "10.1000/ss"
        assert paper.year == 2024
        assert paper.authors == ["Alice"]
        assert paper.pdf_url == "https://example.com/ss.pdf"
        assert paper.url == "https://example.com/ss"
        assert paper.source == "semantic_scholar"

    def test_search_status_error(self):
        p = SemanticScholarProvider(client=FakeClient(status_code=500))
        papers, err = p.search("query", 5)
        assert papers == []
        assert err == "semantic_scholar: status 500"


class TestTools:
    def _make_provider(self, papers=None, doi=None):
        return FakeProvider(
            name="fake",
            search_fn=lambda q, limit: (papers if papers is not None else [], None),
            fetch_fn=lambda d: (doi, None),
        )

    def _registry(self, scholar: Scholar) -> Registry:
        reg = Registry()
        RegisterTools(reg, scholar)
        return reg

    def test_registered(self):
        reg = self._registry(New([self._make_provider(papers=[_paper(title="x")])]))
        assert reg.get("scholar_search") is not None
        assert reg.get("scholar_cite") is not None

    def test_search_success(self):
        paper = _paper(title="Found", authors=["Jane Doe"], year=2021, source="fake")
        reg = self._registry(New([self._make_provider(papers=[paper])]))
        tool = reg.get("scholar_search")
        assert tool is not None
        result, err = tool.execute(None, {"query": "attention"})
        assert err is None
        assert result["enabled"] is True
        assert result["total"] == 1
        item = result["results"][0]
        assert item["title"] == "Found"
        assert item["authors"] == ["Jane Doe"]
        assert item["year"] == 2021
        assert item["source"] == "fake"

    def test_search_query_required(self):
        reg = self._registry(New())
        tool = reg.get("scholar_search")
        assert tool is not None
        result, err = tool.execute(None, {})
        assert err == "query is required"
        assert result == {}

    def test_cite_found(self):
        paper = _paper(title="Cited Paper", authors=["Jane Doe"], year=2020)
        reg = self._registry(New([self._make_provider(doi=paper)]))
        tool = reg.get("scholar_cite")
        assert tool is not None
        result, err = tool.execute(None, {"doi": "10.1000/abc"})
        assert err is None
        assert result["found"] is True
        assert result["doi"] == "10.1000/abc"
        assert result["title"] == "Cited Paper"
        assert result["bibtex"].startswith("@article{doe2020")
        assert "Doe, J." in result["apa"]

    def test_cite_not_found(self):
        reg = self._registry(New([self._make_provider(doi=None)]))
        tool = reg.get("scholar_cite")
        assert tool is not None
        result, err = tool.execute(None, {"doi": "10.1000/xyz"})
        assert err is None
        assert result["found"] is False

    def test_cite_invalid_doi(self):
        reg = self._registry(New())
        tool = reg.get("scholar_cite")
        assert tool is not None
        result, err = tool.execute(None, {"doi": "not-a-doi"})
        assert err is not None
        assert "invalid DOI" in err
        assert result == {}
