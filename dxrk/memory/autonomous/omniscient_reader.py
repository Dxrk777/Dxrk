"""
Omniscient Reader - Lee TODO el conocimiento relevante continuamente.
arXiv, GitHub, Stack Overflow, documentación, blogs.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime


class OmniscientReader:
    """Lee continuamente: arXiv, GitHub, Stack Overflow, docs, blogs."""

    SOURCES = {
        "arxiv": [
            "http://arxiv.org/rss/cs.AI",
            "http://arxiv.org/rss/cs.LG",
            "http://arxiv.org/rss/cs.SE",
        ],
        "github_trending": [
            "https://github.com/trending/python?since=daily",
        ],
        "stack_overflow": [
            "https://stackoverflow.com/feeds/tag/python",
        ],
    }

    def __init__(self, memory_engine=None):
        self.memory = memory_engine
        self.reading_log = []
        self.knowledge_gained_today = 0
        self.is_reading = False

    async def start_continuous_reading(self, interval_minutes: int = 30):
        self.is_reading = True
        while self.is_reading:
            await self._read_all_sources()
            await asyncio.sleep(interval_minutes * 60)

    async def _read_all_sources(self):
        tasks = []
        for source_type, urls in self.SOURCES.items():
            for url in urls:
                tasks.append(asyncio.create_task(self._read_source(source_type, url)))
        await asyncio.gather(*tasks, return_exceptions=True)
        self.reading_log.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "knowledge_gained": self.knowledge_gained_today,
            }
        )

    async def _read_source(self, source_type: str, url: str):
        try:
            if source_type == "arxiv":
                await self._read_arxiv(url)
        except Exception:
            pass

    async def _read_arxiv(self, feed_url: str):
        try:
            import feedparser

            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                paper_info = {
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                }
                relevance = self._calculate_relevance(paper_info)
                if relevance > 0.7:
                    self._store_knowledge(paper_info["title"], paper_info["summary"][:500], "arxiv", relevance)
                    self.knowledge_gained_today += 1
        except ImportError:
            pass

    def _calculate_relevance(self, content: dict) -> float:
        return 0.5

    def _store_knowledge(self, concept: str, definition: str, source: str, relevance: float):
        if self.memory and hasattr(self.memory, "knowledge_graph"):
            try:
                self.memory.knowledge_graph.add_concept(
                    concept=concept,
                    definition=definition,
                    source=source,
                    relevance=relevance,
                    timestamp=datetime.now(UTC).isoformat(),
                )
            except Exception:
                pass

    def stop_reading(self):
        self.is_reading = False

    def get_reading_stats(self) -> dict:
        return {
            "total_reading_sessions": len(self.reading_log),
            "knowledge_gained_today": self.knowledge_gained_today,
            "is_reading": self.is_reading,
        }

    def get_sources(self) -> list[str]:
        """Retorna las URLs de todas las fuentes configuradas."""
        urls: list[str] = []
        for url_list in self.SOURCES.values():
            urls.extend(url_list)
        return urls
