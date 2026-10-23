# SPDX-License-Identifier: MIT
"""Compatibility and chained migration tests for the malla vocabulary.

Covers the three legacy generations (palace/wing/room/drawer,
crypt/chamber/relic and sangre/vena/capilar/globulo) migrating to
malla/partition/subgroup/recall, plus the deprecated module shims and the MCP
argument aliases.
"""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

from dxrk.memory import legacy
from dxrk.memory import malla as malla_module
from dxrk.memory.backend import MallaNotFoundError, MallaRef, SqliteBackend
from dxrk.memory.backend.sqlite import _parse_meta, _where_to_sql
from dxrk.memory.mcp_handlers import TOOL_HANDLERS
from dxrk.memory.mcp_server import TOOLS, _dispatch, _handle_tool, _normalize_tool_args


def _create_legacy_db(
    path: Path,
    *,
    generation: str = "palace",
    legacy_id: str | None = None,
    with_id_column: bool = True,
) -> None:
    """Create a minimal DB shaped like one of the three legacy generations."""
    columns = {
        "palace": ("palace_id", "dxrk_drawers", "wing", "room", "drawer"),
        "crypt": ("crypt_id", "dxrk_relics", "wing", "chamber", "relic"),
        "sangre": ("sangre_id", "dxrk_globulos", "vena", "capilar", "globulo"),
    }
    id_column, collection, partition_key, subgroup_key, recall_key = columns[generation]
    default_id = str(path.parent / generation)
    stored_id = legacy_id if legacy_id is not None else default_id
    extra_column = f",\n            {id_column} TEXT NOT NULL" if with_id_column else ""
    insert_columns = f", {id_column}" if with_id_column else ""
    insert_value = f", '{stored_id}'" if with_id_column else ""
    metadata = json.dumps({partition_key: "w", subgroup_key: "code", recall_key: "d-1"})
    conn = sqlite3.connect(path)
    conn.executescript(
        f"""
        CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE segments (id TEXT PRIMARY KEY, collection_id TEXT REFERENCES collections(id));
        CREATE TABLE embeddings (
            id TEXT PRIMARY KEY,
            document TEXT,
            metadata TEXT,
            collection TEXT NOT NULL{extra_column}
        );
        CREATE TABLE doc_vectors (rowid INTEGER PRIMARY KEY, dim INTEGER NOT NULL, vec BLOB NOT NULL);
        INSERT INTO collections (id, name) VALUES ('{collection}', '{collection}');
        INSERT INTO segments (id, collection_id) VALUES ('seg_{collection}', '{collection}');
        INSERT INTO embeddings (id, document, metadata, collection{insert_columns})
        VALUES ('fragment-1', 'hello world', '{metadata}', '{collection}'{insert_value});
        """
    )
    conn.commit()
    conn.close()


class TestMetadataNormalization:
    def test_renames_oldest_generation(self) -> None:
        meta = {"wing": "w", "room": "code", "drawer": "d-1"}
        assert legacy.normalize_meta_keys(meta) == {"partition": "w", "subgroup": "code", "recall": "d-1"}

    def test_renames_crypt_generation(self) -> None:
        meta = {"wing": "w", "chamber": "code", "relic": "d-1", "relic_id": "r"}
        assert legacy.normalize_meta_keys(meta) == {
            "partition": "w",
            "subgroup": "code",
            "recall": "d-1",
            "recall_id": "r",
        }

    def test_renames_sangre_generation(self) -> None:
        meta = {"vena": "w", "capilar": "code", "globulo": "g", "globulo_ids": ["a"]}
        assert legacy.normalize_meta_keys(meta) == {
            "partition": "w",
            "subgroup": "code",
            "recall": "g",
            "recall_ids": ["a"],
        }

    def test_canonical_key_wins(self) -> None:
        meta = {
            "partition": "new",
            "wing": "old",
            "subgroup": "new-subgroup",
            "room": "old-subgroup",
            "recall": "new-recall",
            "drawer": "old-recall",
        }
        assert legacy.normalize_meta_keys(meta) == {
            "partition": "new",
            "subgroup": "new-subgroup",
            "recall": "new-recall",
        }

    def test_newest_legacy_generation_wins(self) -> None:
        assert legacy.normalize_meta_keys({"wing": "old", "vena": "new"}) == {"partition": "new"}
        assert legacy.normalize_meta_keys({"room": "old", "chamber": "mid", "capilar": "new"}) == {"subgroup": "new"}
        assert legacy.normalize_meta_keys({"drawer": "old", "relic": "mid", "globulo": "new"}) == {"recall": "new"}

    def test_no_legacy_keys_returns_same_object(self) -> None:
        meta = {"partition": "w", "subgroup": "code"}
        assert legacy.normalize_meta_keys(meta) is meta

    def test_ids_and_paths_are_normalized(self) -> None:
        meta = {
            "wing_id": "w1",
            "room_id": "c1",
            "drawer_ids": ["d1"],
            "palace": "p",
            "crypt_path": "/c",
            "sangre_path": "/s",
        }
        assert legacy.normalize_meta_keys(meta) == {
            "partition_id": "w1",
            "subgroup_id": "c1",
            "recall_ids": ["d1"],
            "malla": "p",
            "malla_path": "/s",
        }

    def test_parse_meta_exposes_canonical_keys(self) -> None:
        assert _parse_meta('{"room": "code", "drawer": "d-1"}') == {"subgroup": "code", "recall": "d-1"}

    def test_parse_meta_bad_json_is_empty(self) -> None:
        assert _parse_meta("{not json") == {}
        assert _parse_meta("[1, 2]") == {}


class TestWhereFallback:
    def test_canonical_filter_matches_three_generations(self) -> None:
        sql, params = _where_to_sql({"partition": "w"})
        assert "partition" in sql and "nodo" in sql and "vena" in sql and "wing" in sql
        assert params == ["w", "w", "w", "w"]

    def test_legacy_filter_key_maps_to_canonical(self) -> None:
        sql, params = _where_to_sql({"room": "code"})
        assert "subgroup" in sql and "celda" in sql and "room" in sql and "chamber" in sql and "capilar" in sql
        assert params == ["code", "code", "code", "code", "code"]

    def test_in_operator_expands_every_spelling(self) -> None:
        sql, params = _where_to_sql({"recall": {"$in": ["a", "b"]}})
        assert "recall" in sql and "fragmento" in sql and "globulo" in sql and "relic" in sql and "drawer" in sql
        assert params == ["a", "b"] * 5

    def test_non_legacy_key_stays_single_clause(self) -> None:
        sql, params = _where_to_sql({"source_file": "/tmp/x"})
        assert sql == " AND ((json_extract(metadata, '$.source_file') = ?))"
        assert params == ["/tmp/x"]

    def test_in_with_empty_list_matches_nothing(self) -> None:
        assert _where_to_sql({"partition": {"$in": []}}) == (" AND (1=0)", [])

    def test_unsupported_operator_raises(self) -> None:
        from dxrk.memory.backend.base import UnsupportedFilterError

        with pytest.raises(UnsupportedFilterError):
            _where_to_sql({"partition": {"$gt": 1}})

    def test_unsupported_top_level_operator_raises(self) -> None:
        from dxrk.memory.backend.base import UnsupportedFilterError

        with pytest.raises(UnsupportedFilterError):
            _where_to_sql({"$or": []})

    def test_and_list_and_non_dict_entries(self) -> None:
        sql, params = _where_to_sql({"$and": [{"partition": "w"}, "ignored", {"subgroup": "c"}]})
        assert "partition" in sql and "subgroup" in sql
        assert params == ["w"] * 4 + ["c"] * 5

    def test_and_without_conditions_is_empty(self) -> None:
        assert _where_to_sql({"$and": ["ignored"]}) == ("", [])

    def test_empty_where_is_empty(self) -> None:
        assert _where_to_sql(None) == ("", [])


class TestDirectoryMigration:
    def test_moves_palace_to_malla(self, tmp_path: Path) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "sqlite_palace.db").write_text("db")

        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert (tmp_path / "malla" / "sqlite_palace.db").read_text() == "db"
        assert not palace.exists()

    def test_moves_crypt_to_malla(self, tmp_path: Path) -> None:
        crypt = tmp_path / "crypt"
        crypt.mkdir()
        (crypt / "crypt.db").write_text("db")

        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert (tmp_path / "malla" / "crypt.db").read_text() == "db"
        assert not crypt.exists()

    def test_newest_legacy_directory_wins(self, tmp_path: Path) -> None:
        (tmp_path / "palace").mkdir()
        (tmp_path / "crypt").mkdir()
        (tmp_path / "crypt" / "crypt.db").write_text("new")
        (tmp_path / "palace" / "sqlite_palace.db").write_text("old")

        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert (tmp_path / "malla" / "crypt.db").read_text() == "new"
        assert (tmp_path / "palace").is_dir()

    def test_skips_when_target_exists(self, tmp_path: Path) -> None:
        (tmp_path / "crypt").mkdir()
        (tmp_path / "malla").mkdir()
        assert legacy.migrate_legacy_dir(tmp_path) is None
        assert (tmp_path / "crypt").is_dir()

    def test_skips_when_legacy_missing(self, tmp_path: Path) -> None:
        assert legacy.migrate_legacy_dir(tmp_path) is None

    def test_copy_fallback_keeps_backup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "file.txt").write_text("data")
        real_replace = os.replace

        def fake_replace(src: Any, dst: Any) -> None:
            if Path(src) == palace and Path(dst) == tmp_path / "malla":
                raise OSError("cross-device")
            real_replace(src, dst)

        monkeypatch.setattr(legacy.os, "replace", fake_replace)
        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert (tmp_path / "malla" / "file.txt").read_text() == "data"
        assert (tmp_path / "palace.bak" / "file.txt").read_text() == "data"
        assert not palace.exists()

    def test_copy_failure_leaves_legacy_untouched(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "file.txt").write_text("data")
        monkeypatch.setattr(legacy.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
        monkeypatch.setattr(legacy.shutil, "copytree", lambda *_: (_ for _ in ()).throw(OSError("no")))

        assert legacy.migrate_legacy_dir(tmp_path) is None
        assert not (tmp_path / "malla").exists()
        assert (palace / "file.txt").read_text() == "data"

    def test_existing_backup_is_not_overwritten(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "file.txt").write_text("data")
        backup = tmp_path / "palace.bak"
        backup.mkdir()
        (backup / "old.txt").write_text("old")
        monkeypatch.setattr(legacy.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))

        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert (backup / "old.txt").read_text() == "old"
        assert palace.is_dir()

    def test_backup_rename_failure_leaves_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        monkeypatch.setattr(legacy.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))

        assert legacy.migrate_legacy_dir(tmp_path) == tmp_path / "malla"
        assert palace.is_dir()

    def test_defaults_to_home_dxrk(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / ".dxrk" / "palace"
        palace.mkdir(parents=True)
        monkeypatch.setattr(legacy.Path, "home", classmethod(lambda cls: tmp_path))

        assert legacy.migrate_legacy_dir() == tmp_path / ".dxrk" / "malla"
        assert (tmp_path / ".dxrk" / "malla").is_dir()


class TestDatabaseMigration:
    def test_moves_palace_db_and_sidecars(self, tmp_path: Path) -> None:
        legacy_db = tmp_path / "sqlite_palace.db"
        legacy_db.write_text("db")
        (tmp_path / "sqlite_palace.db-wal").write_text("wal")
        (tmp_path / "sqlite_palace.db-shm").write_text("shm")
        (tmp_path / "malla.db-wal").write_text("keep")

        assert legacy.migrate_legacy_db(tmp_path) == tmp_path / "malla.db"
        assert (tmp_path / "malla.db").read_text() == "db"
        assert (tmp_path / "malla.db-wal").read_text() == "keep"
        assert (tmp_path / "malla.db-shm").read_text() == "shm"
        assert not legacy_db.exists()

    def test_moves_crypt_db_and_sidecars(self, tmp_path: Path) -> None:
        (tmp_path / "crypt.db").write_text("db")
        (tmp_path / "crypt.db-wal").write_text("wal")

        assert legacy.migrate_legacy_db(tmp_path) == tmp_path / "malla.db"
        assert (tmp_path / "malla.db-wal").read_text() == "wal"

    def test_skips_when_target_exists(self, tmp_path: Path) -> None:
        (tmp_path / "sqlite_palace.db").write_text("old")
        (tmp_path / "malla.db").write_text("new")
        assert legacy.migrate_legacy_db(tmp_path) is None
        assert (tmp_path / "malla.db").read_text() == "new"

    def test_skips_when_legacy_missing(self, tmp_path: Path) -> None:
        assert legacy.migrate_legacy_db(tmp_path) is None

    def test_copy_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "sqlite_palace.db").write_text("db")
        monkeypatch.setattr(legacy.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
        assert legacy.migrate_legacy_db(tmp_path) == tmp_path / "malla.db"
        assert (tmp_path / "malla.db").read_text() == "db"

    def test_copy_failure_keeps_legacy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "sqlite_palace.db").write_text("db")
        monkeypatch.setattr(legacy.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
        monkeypatch.setattr(legacy.shutil, "copy2", lambda *_: (_ for _ in ()).throw(OSError("no")))
        assert legacy.migrate_legacy_db(tmp_path) is None
        assert (tmp_path / "sqlite_palace.db").read_text() == "db"


class TestMallaRootMigration:
    def test_migrates_directory_and_database(self, tmp_path: Path) -> None:
        palace = tmp_path / "palace"
        palace.mkdir()
        (palace / "sqlite_palace.db").write_text("db")

        assert legacy.migrate_legacy_malla(tmp_path) == tmp_path / "malla"
        assert (tmp_path / "malla" / "malla.db").read_text() == "db"
        assert not palace.exists()

    def test_defaults_to_home_dxrk(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        palace = tmp_path / ".dxrk" / "palace"
        palace.mkdir(parents=True)
        monkeypatch.setattr(legacy.Path, "home", classmethod(lambda cls: tmp_path))

        assert legacy.migrate_legacy_malla() == tmp_path / ".dxrk" / "malla"
        assert (tmp_path / ".dxrk" / "malla").is_dir()

    def test_previous_public_names_are_aliases(self) -> None:
        assert legacy.migrate_legacy_crypt is legacy.migrate_legacy_malla
        assert legacy.migrate_legacy_crypt_id is legacy.migrate_legacy_malla_id
        assert legacy.migrate_legacy_sangre_id is legacy.migrate_legacy_malla_id


class TestSchemaMigration:
    @pytest.mark.parametrize("legacy_column", ["palace_id", "crypt_id", "sangre_id"])
    def test_renames_legacy_id_column(self, legacy_column: str) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute(f"CREATE TABLE embeddings (id TEXT, {legacy_column} TEXT)")
        legacy.migrate_legacy_schema(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(embeddings)")]
        assert columns == ["id", "malla_id"]

    def test_adds_id_column_when_missing(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE embeddings (id TEXT)")
        legacy.migrate_legacy_schema(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(embeddings)")]
        assert columns == ["id", "malla_id"]

    def test_missing_table_is_a_noop(self) -> None:
        conn = sqlite3.connect(":memory:")
        legacy.migrate_legacy_schema(conn)
        assert conn.execute("PRAGMA table_info(embeddings)").fetchall() == []

    def test_existing_malla_id_is_a_noop(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE embeddings (id TEXT, malla_id TEXT)")
        legacy.migrate_legacy_schema(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(embeddings)")]
        assert columns == ["id", "malla_id"]

    def test_adopts_legacy_malla_ids(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE embeddings (id TEXT, malla_id TEXT)")
        conn.executemany(
            "INSERT INTO embeddings VALUES (?, ?)",
            [
                ("a", "current"),
                ("b", "other"),
                ("c", str(Path("/home/u/.dxrk/palace"))),
                ("d", str(Path("/home/u/.dxrk/crypt"))),
                ("e", str(Path("/home/u/.dxrk/sangre"))),
                ("f", ""),
            ],
        )
        assert legacy.migrate_legacy_malla_id(conn, "current") == 4
        assert conn.execute("SELECT id, malla_id FROM embeddings ORDER BY id").fetchall() == [
            ("a", "current"),
            ("b", "other"),
            ("c", "current"),
            ("d", "current"),
            ("e", "current"),
            ("f", "current"),
        ]
        assert legacy.migrate_legacy_malla_id(conn, "current") == 0

    def test_empty_malla_id_is_a_noop(self) -> None:
        conn = sqlite3.connect(":memory:")
        assert legacy.migrate_legacy_malla_id(conn, "") == 0


class TestCollectionMigration:
    def test_folds_every_legacy_collection(self) -> None:
        conn = sqlite3.connect(":memory:")
        legacy_name = "".join(["mempalace", "_drawers"])
        conn.executescript(
            f"""
            CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL);
            CREATE TABLE segments (id TEXT PRIMARY KEY, collection_id TEXT REFERENCES collections(id));
            CREATE TABLE embeddings (id TEXT PRIMARY KEY, collection TEXT NOT NULL);
            INSERT INTO collections VALUES ('dxrk_drawers', 'dxrk_drawers');
            INSERT INTO segments VALUES ('seg_dxrk_drawers', 'dxrk_drawers');
            INSERT INTO collections VALUES ('{legacy_name}', '{legacy_name}');
            INSERT INTO segments VALUES ('seg_{legacy_name}', '{legacy_name}');
            INSERT INTO embeddings VALUES ('r1', 'dxrk_drawers');
            INSERT INTO embeddings VALUES ('r2', 'dxrk_relics');
            INSERT INTO embeddings VALUES ('r3', 'dxrk_globulos');
            INSERT INTO embeddings VALUES ('r4', '{legacy_name}');
            """
        )
        conn.commit()
        assert legacy.migrate_legacy_collections(conn) == 4
        assert conn.execute("SELECT DISTINCT collection FROM embeddings").fetchall() == [("dxrk_recalls",)]
        assert conn.execute("SELECT COUNT(*) FROM collections WHERE name='dxrk_drawers'").fetchone()[0] == 0
        assert conn.execute("SELECT id FROM collections").fetchall() == [("dxrk_recalls",)]
        assert legacy.migrate_legacy_collections(conn) == 0


class TestMetadataMigration:
    def test_rewrites_all_generations_and_skips_bad_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE embeddings (rowid INTEGER PRIMARY KEY, metadata TEXT)")
        conn.executemany(
            "INSERT INTO embeddings (metadata) VALUES (?)",
            [
                ('{"room": "code"}',),
                ('{"wing": "w", "drawer": "d"}',),
                ('{"chamber": "code", "relic": "r"}',),
                ('{"vena": "v", "capilar": "c", "globulo": "g"}',),
                ('{"partition": "already"}',),
                ("{not json",),
                ("[]",),
                (None,),
                ("",),
            ],
        )
        assert legacy.migrate_legacy_metadata(conn) == 4
        rows = conn.execute("SELECT metadata FROM embeddings WHERE metadata IS NOT NULL AND metadata != ''").fetchall()
        assert json.loads(rows[0][0]) == {"subgroup": "code"}
        assert json.loads(rows[1][0]) == {"partition": "w", "recall": "d"}
        assert json.loads(rows[2][0]) == {"subgroup": "code", "recall": "r"}
        assert json.loads(rows[3][0]) == {"partition": "v", "subgroup": "c", "recall": "g"}
        assert json.loads(rows[4][0]) == {"partition": "already"}
        assert legacy.migrate_legacy_metadata(conn) == 0

    def test_rolls_back_on_sqlite_error(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE embeddings (rowid INTEGER PRIMARY KEY, metadata TEXT)")
        conn.execute('INSERT INTO embeddings (metadata) VALUES (\'{"room": "code"}\')')
        conn.execute("CREATE TRIGGER fail_update BEFORE UPDATE ON embeddings BEGIN SELECT RAISE(ABORT, 'nope'); END")
        with pytest.raises(sqlite3.IntegrityError):
            legacy.migrate_legacy_metadata(conn)
        assert conn.execute("SELECT metadata FROM embeddings").fetchone()[0] == '{"room": "code"}'


class TestBackendIntegration:
    @pytest.mark.parametrize(
        ("generation", "db_name"),
        [("palace", "sqlite_palace.db"), ("crypt", "crypt.db"), ("sangre", "sangre.db")],
    )
    def test_open_migrates_each_generation_in_place(self, tmp_path: Path, generation: str, db_name: str) -> None:
        _create_legacy_db(tmp_path / db_name, generation=generation, legacy_id=str(tmp_path / generation))
        backend = SqliteBackend()
        try:
            col = backend.get_collection(
                malla=MallaRef(id=str(tmp_path), local_path=str(tmp_path)),
                collection_name="dxrk_recalls",
            )
            assert (tmp_path / "malla.db").is_file()
            assert not (tmp_path / db_name).exists()
            got = col.get(ids=["fragment-1"], include=["documents", "metadatas"])
        finally:
            backend.close()
        assert got.ids == ["fragment-1"]
        meta = got.metadatas[0]
        assert meta["partition"] == "w"
        assert meta["subgroup"] == "code"
        assert meta["recall"] == "d-1"
        assert not any(
            key in meta for key in ("wing", "room", "drawer", "chamber", "relic", "vena", "capilar", "globulo")
        )

    def test_open_adds_missing_id_column(self, tmp_path: Path) -> None:
        _create_legacy_db(tmp_path / "sqlite_palace.db", with_id_column=False)
        backend = SqliteBackend()
        try:
            col = backend.get_collection(
                malla=MallaRef(id=str(tmp_path), local_path=str(tmp_path)),
                collection_name="dxrk_recalls",
            )
            got = col.get(ids=["fragment-1"], include=["metadatas"])
        finally:
            backend.close()
        assert got.ids == ["fragment-1"]
        assert got.metadatas[0]["subgroup"] == "code"

    def test_detect_accepts_legacy_filenames(self, tmp_path: Path) -> None:
        palace_db = tmp_path / "sqlite_palace.db"
        palace_db.write_text("db")
        assert SqliteBackend.detect(str(palace_db)) is True
        assert SqliteBackend.detect(str(tmp_path)) is True
        crypt_dir = tmp_path / "crypt-root"
        crypt_dir.mkdir()
        (crypt_dir / "crypt.db").write_text("db")
        assert SqliteBackend.detect(str(crypt_dir)) is True
        assert SqliteBackend.detect(str(tmp_path / "nope")) is False

    def test_db_path_remaps_legacy_filename(self, tmp_path: Path) -> None:
        legacy_db = tmp_path / "sqlite_palace.db"
        legacy_db.write_text("db")
        current_db = tmp_path / "malla.db"
        current_db.write_text("db")
        backend = SqliteBackend()
        try:
            assert backend._db_path(MallaRef(id="legacy", local_path=str(legacy_db))) == current_db
            assert backend._db_path(MallaRef(id="current", local_path=str(current_db))) == current_db
        finally:
            backend.close()


class TestModuleShims:
    def test_crypt_shim_aliases_and_warning(self) -> None:
        sys.modules.pop("dxrk.memory.crypt", None)
        with pytest.warns(DeprecationWarning):
            shim = importlib.import_module("dxrk.memory.crypt")
        assert shim.Crypt is malla_module.Malla
        assert shim.DxrkCrypt is malla_module.DxrkMalla
        assert shim.CryptConfig is malla_module.MallaConfig
        assert shim.mine_crypt_lock is malla_module.mine_malla_lock
        assert shim.CryptRef is MallaRef
        assert shim.CryptNotFoundError is MallaNotFoundError
        assert shim.RelicRecord is malla_module.RecallRecord
        assert shim.migrate_legacy_crypt is legacy.migrate_legacy_malla
        assert shim.__getattr__("CryptConfig") is malla_module.MallaConfig
        assert shim.__getattr__("mine_malla_lock") is malla_module.mine_malla_lock
        with pytest.raises(AttributeError):
            shim.__getattr__("missing")

    def test_palace_shim_aliases_and_warning(self) -> None:
        sys.modules.pop("dxrk.memory.palace", None)
        with pytest.warns(DeprecationWarning):
            shim = importlib.import_module("dxrk.memory.palace")
        assert shim.Palace is malla_module.Malla
        assert shim.DxrkPalace is malla_module.DxrkMalla
        assert shim.PalaceConfig is malla_module.MallaConfig
        assert shim.mine_palace_lock is malla_module.mine_malla_lock
        assert shim.DrawerRecord is malla_module.RecallRecord
        assert shim.__getattr__("PalaceConfig") is malla_module.MallaConfig
        assert shim.__getattr__("mine_malla_lock") is malla_module.mine_malla_lock
        with pytest.raises(AttributeError):
            shim.__getattr__("missing")

    def test_sangre_shim_aliases_and_warning(self) -> None:
        sys.modules.pop("dxrk.memory.sangre", None)
        with pytest.warns(DeprecationWarning):
            shim = importlib.import_module("dxrk.memory.sangre")
        assert shim.Sangre is malla_module.Malla
        assert shim.DxrkSangre is malla_module.DxrkMalla
        assert shim.SangreConfig is malla_module.MallaConfig
        assert shim.mine_sangre_lock is malla_module.mine_malla_lock
        assert shim.SangreRef is MallaRef
        assert shim.SangreNotFoundError is MallaNotFoundError
        assert shim.GlobuloRecord is malla_module.RecallRecord
        assert shim.__getattr__("SangreConfig") is malla_module.MallaConfig
        assert shim.__getattr__("mine_malla_lock") is malla_module.mine_malla_lock
        with pytest.raises(AttributeError):
            shim.__getattr__("missing")

    def test_legacy_method_aliases(self) -> None:
        cls = malla_module.DxrkMemory
        assert cls.add_drawer is cls.add_recall
        assert cls.get_drawer is cls.get_recall
        assert cls.list_drawers is cls.list_recalls
        assert cls.pin_drawer is cls.pin_recall
        assert cls.quarantine_drawer is cls.quarantine_recall
        assert cls.consolidate_drawers is cls.consolidate_recalls
        assert cls.add_relic is cls.add_recall
        assert cls.list_relics is cls.list_recalls
        assert cls.add_globulo is cls.add_recall
        assert cls.list_globulos is cls.list_recalls
        assert cls.list_rooms is cls.list_subgroups
        assert cls.list_chambers is cls.list_subgroups
        assert cls.list_wings is cls.list_partitions
        assert cls.wing_usage is cls.partition_usage
        assert cls.enforce_wing_cap is cls.enforce_partition_cap


class TestMcpAliases:
    def test_normalize_every_legacy_generation(self) -> None:
        assert _normalize_tool_args(
            {"wing": "w", "room": "code", "drawer": "d", "drawer_id": "id", "drawer_ids": ["ids"]}
        ) == {"partition": "w", "subgroup": "code", "recall": "d", "recall_id": "id", "recall_ids": ["ids"]}
        assert _normalize_tool_args(
            {"wing": "w", "chamber": "code", "relic": "r", "relic_id": "id", "relic_ids": ["ids"]}
        ) == {"partition": "w", "subgroup": "code", "recall": "r", "recall_id": "id", "recall_ids": ["ids"]}
        assert _normalize_tool_args(
            {"vena": "v", "capilar": "c", "globulo": "g", "globulo_id": "id", "globulo_ids": ["ids"]}
        ) == {"partition": "v", "subgroup": "c", "recall": "g", "recall_id": "id", "recall_ids": ["ids"]}

    def test_canonical_key_wins(self) -> None:
        assert _normalize_tool_args({"room": "old", "subgroup": "new"}) == {"subgroup": "new"}
        assert _normalize_tool_args({"sangre": "old", "malla": "new"}) == {"malla": "new"}

    def test_path_aliases(self) -> None:
        assert _normalize_tool_args({"palace": "/p"}) == {"malla": "/p"}
        assert _normalize_tool_args({"crypt": "/c"}) == {"malla": "/c"}
        assert _normalize_tool_args({"sangre_path": "/s"}) == {"malla_path": "/s"}

    def test_no_alias_returns_copy(self) -> None:
        args = {"partition": "w"}
        normalized = _normalize_tool_args(args)
        assert normalized == args
        assert normalized is not args

    def test_old_arg_names_reach_handler(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[dict[str, Any]] = []

        def stub(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
            calls.append(args)
            return {"ok": True}

        monkeypatch.setitem(TOOL_HANDLERS, "dxrk_memory_list_subgroups", stub)
        assert _handle_tool("dxrk_memory_list_subgroups", {"room": "code", "sangre": str(tmp_path)}) == {"ok": True}
        assert calls[0]["subgroup"] == "code"
        assert calls[0]["malla"] == str(tmp_path)
        assert "room" not in calls[0]

    def test_old_tool_name_dispatches_to_canonical_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def stub(args: dict[str, Any], malla_path: str) -> dict[str, Any]:
            calls.append(malla_path)
            return {"ok": True}

        monkeypatch.setitem(TOOL_HANDLERS, "dxrk_memory_list_subgroups", stub)
        response = _dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "dxrk_memory_list_rooms",
                    "arguments": {"room": "code", "crypt": str(tmp_path)},
                },
            }
        )
        assert response is not None
        assert response["result"]["isError"] is False
        assert calls == [str(tmp_path.resolve())]

    def test_tool_names_are_stable(self) -> None:
        assert len(TOOLS) == 35
        assert "dxrk_memory_add_recall" in TOOLS
        assert "dxrk_memory_list_subgroups" in TOOLS
        assert "dxrk_memory_add_drawer" not in TOOLS
        assert "dxrk_memory_add_globulo" not in TOOLS

    def test_non_string_tool_name_is_rejected(self) -> None:
        response = _dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": {"nested": "name"}, "arguments": {}},
            }
        )
        assert response is not None
        assert response["error"]["code"] == -32602
