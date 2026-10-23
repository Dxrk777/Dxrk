# SPDX-License-Identifier: MIT
"""Compatibility coverage for the previous hierarchy vocabulary.

The canonical hierarchy is DxrkPartition -> DxrkSubgroup -> DxrkRecall.
These tests pin the deprecated ``nodo/celda/fragmento`` surface so old
call sites and JSON files keep working during the transition.
"""

from __future__ import annotations

import json
from pathlib import Path

from dxrk.memory import AgentMemory
from dxrk.memory.malla import DxrkMemory, MallaConfig
from dxrk.memory.types import ClosetRecord, DxrkRecall, MemoryEntry


def test_memory_entry_alias_properties_roundtrip() -> None:
    entry = MemoryEntry(partition="p", subgroup="s", recall_id="r")
    assert entry.nodo == "p"
    assert entry.celda == "s"
    assert entry.fragmento_id == "r"

    entry.nodo = "p2"
    entry.celda = "s2"
    entry.fragmento_id = "r2"
    assert entry.partition == "p2"
    assert entry.subgroup == "s2"
    assert entry.recall_id == "r2"


def test_recall_record_alias_properties() -> None:
    recall = DxrkRecall(
        recall_id="recall_p_s_1",
        partition="p",
        subgroup="s",
        content="c",
        source_file="/a",
        chunk_index=0,
        malla_path="/m",
    )
    assert recall.fragmento_id == recall.recall_id
    assert recall.nodo == "p"
    assert recall.celda == "s"


def test_closet_record_alias_properties() -> None:
    closet = ClosetRecord(
        closet_id="closet_p_s_1",
        partition="p",
        subgroup="s",
        source_file="/a",
        content="c",
        recall_ids=("r1", "r2"),
        malla_path="/m",
    )
    assert closet.fragmento_ids == ("r1", "r2")
    assert closet.nodo == "p"
    assert closet.celda == "s"


def test_malla_config_nodo_alias(tmp_path: Path) -> None:
    config = MallaConfig(str(tmp_path), partition="p")
    assert config.nodo == "p"
    config.nodo = "p2"
    assert config.partition == "p2"


def test_max_entries_per_nodo_alias(tmp_path: Path) -> None:
    memory = DxrkMemory(str(tmp_path / "malla_cap"), max_entries_per_nodo=7)
    memory.init()
    assert memory._max_entries_per_partition == 7
    memory.close()


def test_legacy_json_keys_migrate_on_load(tmp_path: Path) -> None:
    path = tmp_path / "entries.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "m1",
                    "type": 0,
                    "content": "legacy row",
                    "nodo": "p",
                    "celda": "s",
                    "fragmento_id": "r",
                }
            ]
        ),
        encoding="utf-8",
    )

    memory = AgentMemory(path=path)
    entry = memory.retrieve("m1")
    assert entry is not None
    assert entry.partition == "p"
    assert entry.subgroup == "s"
    assert entry.recall_id == "r"


def test_fragmento_wrappers_delegate_to_canonical_api(tmp_path: Path) -> None:
    memory = DxrkMemory(str(tmp_path / "malla_wrappers"))
    memory.init()
    first = memory.add_fragmento(
        nodo="p",
        celda="s",
        content="one",
        source_file="/one.txt",
        chunk_index=0,
        importance=0.4,
    )
    second = memory.add_fragmento("p", "s", "two", "/two.txt", 0)

    assert memory.get_fragmento(first) is not None
    assert {row["id"] for row in memory.list_fragmentos(nodo="p", celda="s")} == {first, second}
    assert memory.pin_fragmento(first) is True
    assert memory.unpin_fragmento(first) is True
    assert memory.quarantine_fragmento(first, "test") is True
    assert memory.unquarantine_fragmento(first) is True
    assert memory.consolidate_fragmentos([first, second], nodo="p", celda="s")
    assert set(memory.list_nodos()) == {"p"}
    assert set(memory.list_celdas("p")) == {"s"}
    assert "count" in memory.nodo_usage("p")
    assert memory.enforce_nodo_cap("p") >= 0
    memory.close()


def test_search_accepts_legacy_hierarchy_kwargs(tmp_path: Path) -> None:
    memory = DxrkMemory(str(tmp_path / "malla_search"))
    memory.init()
    memory.add_recall("p1", "s1", "alpha beta", "/a.txt", 0)
    memory.add_recall("p2", "s1", "alpha gamma", "/b.txt", 0)

    assert memory.search("alpha", nodo="p1", celda="s1")["results"]
    assert memory.search("alpha", subgroup="s1")["results"]
    memory.close()
