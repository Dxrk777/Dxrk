# SPDX-License-Identifier: MIT
"""RAG tools for LLM invocation."""

from __future__ import annotations

import logging
from typing import Any

from ..tools import Registry, ToolDef, build
from .rag import RAG

_logger = logging.getLogger("dxrk.rag")

KEY_DESCRIPTION = "description"
KEY_ENABLED = "enabled"
KEY_MESSAGE = "message"

codebase_query_schema = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Consulta en lenguaje natural sobre lo que buscas en el código",
        },
        "max_results": {
            "type": "integer",
            "description": "Máximo de resultados (default: 5)",
        },
    },
    "required": ["query"],
}

codebase_index_schema = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Ruta del proyecto a indexar (default: root del proyecto)",
        },
    },
    "required": [],
}


def RegisterTools(reg: Registry, rag: RAG) -> None:
    """Registers RAG tools with the given registry."""

    def codebase_query_execute(
        _ctx: Any, input_: dict[str, Any] | None
    ) -> tuple[Any, str | None]:
        query = ""
        max_results = 0
        if input_:
            query = input_.get("query", "")
            mr = input_.get("max_results")
            if isinstance(mr, int):
                max_results = mr
        if not query:
            return None, "query is required"
        if max_results <= 0:
            max_results = 5
        if not rag.IsEnabled():
            return {
                KEY_ENABLED: False,
                KEY_MESSAGE: "RAG no está habilitado. Actívalo en dxrk.yaml (rag.enabled: true) y ejecutá el indexador primero.",
            }, None
        results = rag.Query(query, max_results)
        if not results:
            return {
                "results": [],
                KEY_MESSAGE: "No se encontraron resultados. Probá indexar el codebase con codebase_reindex primero.",
            }, None
        items = []
        for r in results:
            c = r.record.chunk
            items.append(
                {
                    "file_path": c.file_path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "language": c.language,
                    "text": c.text,
                    "score": r.score,
                }
            )
        return {"results": items, "total": len(items), KEY_ENABLED: True}, None

    def codebase_index_execute(
        _ctx: Any, input_: dict[str, Any] | None
    ) -> tuple[Any, str | None]:
        if not rag.IsEnabled():
            return {
                KEY_ENABLED: False,
                KEY_MESSAGE: "RAG no está habilitado. Actívalo en dxrk.yaml (rag.enabled: true).",
            }, None
        path = ""
        if input_:
            path = input_.get("path", "")
        if path:
            return None, "path override not supported yet; index the project root"
        stats = rag._indexer.Index()
        return {
            "files_scanned": stats.files_scanned,
            "files_indexed": stats.files_indexed,
            "chunks_created": stats.chunks_created,
            "total_vectors": stats.total_vectors,
            "duration_ms": stats.duration_ms,
            "last_run": stats.last_run,
        }, None

    reg.register(
        build(
            ToolDef(
                name="codebase_query",
                description=(
                    "Busca código relevante en el codebase usando búsqueda semántica. "
                    "Retorna fragmentos de código con ruta, línea y score de similitud."
                ),
                input_schema=codebase_query_schema,
                execute=codebase_query_execute,
            )
        )
    )
    reg.register(
        build(
            ToolDef(
                name="codebase_index",
                description=(
                    "Indexa el codebase completo: escanea archivos, genera embeddings "
                    "y los almacena para búsqueda semántica."
                ),
                input_schema=codebase_index_schema,
                execute=codebase_index_execute,
            )
        )
    )
