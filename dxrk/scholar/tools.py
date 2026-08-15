# SPDX-License-Identifier: MIT
""" MCP/registry tools for scholarly search."""

from __future__ import annotations

import logging
from typing import Any

from ..tools import ToolDef, build
from .citation import Paper as CitePaper
from .citation import format_apa, format_bibtex, format_mla, normalize_doi, valid_doi

_logger = logging.getLogger("dxrk.scholar")

KEY_DESCRIPTION = "description"
KEY_ENABLED = "enabled"
KEY_MESSAGE = "message"


def RegisterTools(reg: Any, scholar: Any | None = None) -> None:
    def execute_search(
        _ctx: Any,
        input: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        data = input or {}
        query = data.get("query", "")
        if not isinstance(query, str):
            query = str(query)
        if query.strip() == "":
            return {}, "query is required"
        limit = data.get("limit", 0)
        if not isinstance(limit, int):
            try:
                limit = int(limit)
            except (TypeError, ValueError):
                limit = 0
        if limit <= 0:
            limit = 10
        source = data.get("source", "")
        if not isinstance(source, str):
            source = str(source)
        if scholar is None:
            return (
                {
                    KEY_ENABLED: False,
                    KEY_MESSAGE: "Scholar no está configurado. Inicializá dxrk/scholar y exponelo en el contexto de tools.",
                },
                None,
            )
        papers, err = scholar.Search(query, limit)
        if err is not None:
            return {}, f"scholar search: {err}"
        if not papers:
            return (
                {
                    "results": [],
                    "total": 0,
                    KEY_MESSAGE: "No se encontraron papers. Probá con otros términos de búsqueda o una fuente específica.",
                },
                None,
            )
        items = []
        for p in papers:
            if source != "" and source.lower() != p.source.lower():
                continue
            items.append(
                {
                    "title": p.title,
                    "authors": p.authors,
                    "doi": p.doi,
                    "abstract": p.abstract,
                    "url": p.url,
                    "pdf_url": p.pdf_url,
                    "year": p.year,
                    "source": p.source,
                }
            )
        return {"results": items, "total": len(items), KEY_ENABLED: True}, None

    def execute_cite(
        _ctx: Any,
        input: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], str | None]:
        data = input or {}
        doi = data.get("doi", "")
        if not isinstance(doi, str):
            doi = str(doi)
        doi = normalize_doi(doi)
        if not valid_doi(doi):
            return {}, f'invalid DOI "{doi}"'
        if scholar is None:
            return (
                {
                    KEY_ENABLED: False,
                    KEY_MESSAGE: "Scholar no está configurado. Inicializá un servicio y exponelo en el contexto de tools.",
                },
                None,
            )
        paper, err = scholar.FetchByDOI(doi)
        if err is not None:
            return {}, f"scholar fetch: {err}"
        if paper is None:
            return (
                {
                    "found": False,
                    "doi": doi,
                    KEY_MESSAGE: "No se encontró ningún paper para ese DOI en los proveedores configurados.",
                },
                None,
            )
        c = CitePaper(
            title=paper.title,
            authors=paper.authors,
            doi=paper.doi,
            abstract=paper.abstract,
            url=paper.url,
            year=paper.year,
        )
        return (
            {
                "found": True,
                "doi": doi,
                "title": paper.title,
                "bibtex": format_bibtex(c),
                "apa": format_apa(c),
                "mla": format_mla(c),
            },
            None,
        )

    defs = [
        ToolDef(
            name="scholar_search",
            description="Busca papers académicos (arXiv, Crossref, Semantic Scholar, OpenAlex, PubMed) y retorna título, autores, DOI, abstract y URLs.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Términos de búsqueda académica.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Máximo de papers por proveedor (default: 10)",
                    },
                    "source": {
                        "type": "string",
                        "description": "Proveedor específico: arxiv, crossref, semantic_scholar, openalex, pubmed (default: todos)",
                    },
                },
                "required": ["query"],
            },
            execute=execute_search,
        ),
        ToolDef(
            name="scholar_cite",
            description="Genera la cita de un paper en formato BibTeX, APA y MLA a partir de su DOI.",
            input_schema={
                "type": "object",
                "properties": {
                    "doi": {
                        "type": "string",
                        "description": "DOI del paper, por ejemplo 10.48550/arXiv.2301.00234",
                    },
                },
                "required": ["doi"],
            },
            execute=execute_cite,
        ),
    ]
    for td in defs:
        t = build(td)
        reg.register(t)
