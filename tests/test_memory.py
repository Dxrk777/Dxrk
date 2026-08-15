# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dxrk.memory import AgentMemory, MemoryEntry, MemoryType, top_by_importance


class FakeRecord:
    def __init__(self, entry_id: str, embedding: list[float] | None = None) -> None:
        self.id = entry_id
        self.embedding = embedding


class FakeRAG:
    def __init__(
        self, enabled: bool = True, results: list[FakeRecord] | None = None
    ) -> None:
        self._enabled = enabled
        self._results = results or []

    def is_enabled(self) -> bool:
        return self._enabled

    def query(self, text: str, limit: int) -> list[FakeRecord]:
        return self._results


def make_entry(**overrides: Any) -> MemoryEntry:
    base: dict[str, Any] = dict(
        content="hello world",
        importance=0.5,
        project_id="p1",
        session_id="s1",
    )
    base.update(overrides)
    return MemoryEntry(**base)


def test_store_generates_id_and_timestamps():
    m = AgentMemory()
    m.store(make_entry())

    entry = m.retrieve("mem-0") or next(iter(m._entries.values()))
    assert entry.id.startswith("mem-")
    assert entry.created_at
    assert entry.accessed_at == entry.created_at


def test_retrieve_updates_access_count():
    m = AgentMemory()
    m.store(make_entry())
    entry_id = next(iter(m._entries))

    first = m.retrieve(entry_id)
    second = m.retrieve(entry_id)
    assert first is not None
    assert second is not None
    assert second.access_count == 2


def test_retrieve_missing_returns_none():
    m = AgentMemory()
    assert m.retrieve("missing") is None


def test_search_local_case_insensitive():
    m = AgentMemory()
    m.store(make_entry(content="Project ALPHA launch", importance=0.9))
    m.store(make_entry(content="unrelated notes", importance=0.1))

    results = m.search("", "alpha", 0, 10)
    assert [e.content for e in results] == ["Project ALPHA launch"]


def test_search_filters_by_project_and_type():
    m = AgentMemory()
    m.store(make_entry(content="one", project_id="p1", type=MemoryType.EPISODIC))
    m.store(make_entry(content="one", project_id="p2", type=MemoryType.EPISODIC))
    m.store(make_entry(content="one", project_id="p1", type=MemoryType.SEMANTIC))

    assert len(m.search("p1", "", 0, 10)) == 2
    assert len(m.search("p1", "", MemoryType.EPISODIC, 10)) == 1


def test_search_limits_by_importance():
    m = AgentMemory()
    for i in range(5):
        m.store(make_entry(content=f"item {i}", importance=float(i)))

    results = m.search("", "", 0, 2)
    assert len(results) == 2
    assert results[0].importance == 4.0
    assert results[1].importance == 3.0


def test_top_by_importance_sorts_descending():
    entries = [make_entry(importance=0.3), make_entry(importance=0.9)]
    top = top_by_importance(entries, 1)
    assert len(top) == 1
    assert top[0].importance == 0.9


def test_evict_least_recently_accessed(temp_dir: Path):
    m = AgentMemory(path=temp_dir / "mem.json", max_entries=2)
    m.store(make_entry(id="a", content="oldest"))
    m.store(make_entry(id="b", content="second"))
    m.retrieve("a")
    m.store(make_entry(id="c", content="third"))

    assert m.retrieve("a") is not None
    assert m.retrieve("b") is None
    assert m.retrieve("c") is not None


def test_delete_removes_entry_and_indexes(temp_dir: Path):
    m = AgentMemory(path=temp_dir / "mem.json")
    m.store(make_entry(id="a"))
    m.store(make_entry(id="b"))

    m.delete("a")

    assert m.retrieve("a") is None
    assert m.get_by_project("p1") == [m.retrieve("b")]
    assert m.stats().total_entries == 1


def test_persistence_roundtrip(temp_dir: Path):
    path = temp_dir / "mem.json"
    m = AgentMemory(path=path)
    m.store(make_entry(id="a", content="persisted", importance=0.8))

    loaded = AgentMemory(path=path)
    entry = loaded.retrieve("a")
    assert entry is not None
    assert entry.content == "persisted"
    assert entry.importance == 0.8
    assert entry.type == MemoryType.SEMANTIC


def test_get_by_session_and_type():
    m = AgentMemory()
    m.store(make_entry(id="a", session_id="s1", type=MemoryType.PROCEDURAL))
    m.store(make_entry(id="b", session_id="s2", type=MemoryType.PROCEDURAL))

    assert [e.id for e in m.get_by_session("s1")] == ["a"]
    assert [e.id for e in m.get_by_type(MemoryType.PROCEDURAL)] == ["a", "b"]


def test_stats_counts():
    m = AgentMemory()
    m.store(make_entry(project_id="p1", session_id="s1"))
    m.store(make_entry(project_id="p2", session_id="s2"))
    m.store(make_entry(project_id="p1", session_id="s3", type=MemoryType.EPISODIC))

    stats = m.stats()
    assert stats.total_entries == 3
    assert stats.by_project == 2
    assert stats.by_session == 3
    assert stats.by_type == {MemoryType.SEMANTIC: 2, MemoryType.EPISODIC: 1}


def test_store_embeds_via_rag():
    rag = FakeRAG(results=[FakeRecord("a", embedding=[0.1, 0.2, 0.3])])
    m = AgentMemory(rag=rag)
    m.store(make_entry())

    entry = next(iter(m._entries.values()))
    assert entry.embedding == [0.1, 0.2, 0.3]


def test_search_uses_rag_results_with_filters():
    rag = FakeRAG(results=[FakeRecord("a"), FakeRecord("b")])
    m = AgentMemory(rag=rag)
    m.store(make_entry(id="a", project_id="p1", type=MemoryType.SEMANTIC))
    m.store(make_entry(id="b", project_id="p2", type=MemoryType.SEMANTIC))
    m.store(make_entry(id="c", project_id="p1", type=MemoryType.SEMANTIC))

    results = m.search("p1", "anything", 0, 10)
    assert [e.id for e in results] == ["a"]


def test_search_falls_back_to_local_when_rag_empty():
    rag = FakeRAG(results=[])
    m = AgentMemory(rag=rag)
    m.store(make_entry(id="a", content="needle in haystack"))

    results = m.search("", "needle", 0, 10)
    assert [e.id for e in results] == ["a"]


def test_search_falls_back_to_local_when_rag_disabled():
    rag = FakeRAG(enabled=False)
    m = AgentMemory(rag=rag)
    m.store(make_entry(id="a", content="needle in haystack"))

    results = m.search("", "needle", 0, 10)
    assert [e.id for e in results] == ["a"]


def test_missing_file_loads_empty_store(temp_dir: Path):
    m = AgentMemory(path=temp_dir / "does-not-exist.json")
    assert m.stats().total_entries == 0


@pytest.mark.parametrize("path", [None, ""])
def test_no_path_skips_persistence(path):
    m = AgentMemory(path=path)
    m.store(make_entry())
    assert m.stats().total_entries == 1
