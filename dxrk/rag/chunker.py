# SPDX-License-Identifier: MIT
"""Chunking helpers for RAG indexing."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

_logger = logging.getLogger("dxrk.rag")

_CODE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".go",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".py",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".ex",
        ".exs",
        ".clj",
        ".cljs",
        ".elm",
        ".hs",
        ".lua",
        ".r",
        ".m",
        ".mm",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".md",
        ".css",
        ".scss",
        ".less",
        ".html",
        ".svelte",
        ".vue",
    }
)

_LANGUAGE_BY_EXT: dict[str, str] = {
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".svelte": "html",
    ".vue": "html",
    ".css": "css",
    ".scss": "css",
    ".less": "css",
}


@dataclass
class Chunk:
    """A single chunk of code extracted from a file."""

    text: str
    file_path: str
    start_line: int
    end_line: int
    language: str


@dataclass
class ChunkConfig:
    """Configuration for the chunker."""

    chunk_size: int
    chunk_overlap: int


def DefaultChunkConfig() -> ChunkConfig:
    """Returns the default chunk configuration."""
    return ChunkConfig(chunk_size=512, chunk_overlap=64)


def IsCodeFile(path: str) -> bool:
    """Reports whether a file is a supported code file based on its extension."""
    ext = ""
    dot = path.rfind(".")
    if dot >= 0:
        ext = path[dot:].lower()
    return ext in _CODE_EXTENSIONS


def LanguageFromExt(path: str) -> str:
    """Returns the programming language for a file path's extension."""
    ext = ""
    dot = path.rfind(".")
    if dot >= 0:
        ext = path[dot:].lower()
    return _LANGUAGE_BY_EXT.get(ext, "text")


def ChunkFile(path: str, cfg: ChunkConfig) -> list[Chunk]:
    """Splits a file into chunks. Returns an empty list for non-UTF-8 files."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return []

    lang = LanguageFromExt(path)
    lines = text.split("\n")

    if len(lines) <= cfg.chunk_size:
        return [
            Chunk(
                text=text,
                file_path=path,
                start_line=1,
                end_line=len(lines),
                language=lang,
            )
        ]

    chunks: list[Chunk] = []
    step = cfg.chunk_size - cfg.chunk_overlap
    if step < 1:
        step = 1

    i = 0
    while i < len(lines):
        end = min(i + cfg.chunk_size, len(lines))
        chunk_text = "\n".join(lines[i:end])
        chunks.append(
            Chunk(
                text=chunk_text,
                file_path=path,
                start_line=i + 1,
                end_line=end,
                language=lang,
            )
        )
        if end >= len(lines):
            break
        i += step
    return chunks


def DefaultIgnoreDirs() -> dict[str, bool]:
    """Returns a copy of the default set of directories to ignore."""
    return {
        ".git": True,
        "node_modules": True,
        "__pycache__": True,
        ".venv": True,
        "vendor": True,
        "target": True,
        "dist": True,
        "build": True,
        ".next": True,
        ".cache": True,
        "third_party": True,
        ".dxrk": True,
    }
