# SPDX-License-Identifier: MIT
""" multi-provider academic paper search and citation."""

from .arxiv import ArxivProvider, NewArxivProvider
from .crossref import CrossrefProvider, NewCrossrefProvider
from .openalex import NewOpenAlexProvider, OpenAlexProvider
from .provider import Paper, Provider
from .pubmed import NewPubMedProvider, PubMedProvider
from .scholar import New, Scholar
from .semanticscholar import NewSemanticScholarProvider, SemanticScholarProvider
from .tools import RegisterTools

__all__ = [
    "ArxivProvider",
    "CrossrefProvider",
    "New",
    "NewArxivProvider",
    "NewCrossrefProvider",
    "NewOpenAlexProvider",
    "NewPubMedProvider",
    "NewSemanticScholarProvider",
    "OpenAlexProvider",
    "Paper",
    "Provider",
    "PubMedProvider",
    "RegisterTools",
    "Scholar",
    "SemanticScholarProvider",
]
