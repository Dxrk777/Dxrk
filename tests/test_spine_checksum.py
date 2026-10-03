# SPDX-License-Identifier: MIT
"""Spine checksums — content_sha256 at rest, rehash-on-read, auto-quarantine."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _dm(tmp_path: Path, **kwargs):  # type: ignore[no-untyped-def]
    from dxrk.memory.palace import DxrkMemory

    dm = DxrkMemory(str(tmp_path / "palace"), **kwargs)
    dm.init()
    return dm


DOC = "The checksum drawer holds exactly this text for integrity tests."


class TestSpineChecksum:
    def test_new_drawer_sha_matches_document(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC, "/c.md", 0)
            got = dm.get_drawer(did)
            assert got is not None and "document" in got
            assert got["metadata"]["content_sha256"] == hashlib.sha256(DOC.encode()).hexdigest()
            # Stable across reads (no rehash churn, no quarantine).
            again = dm.get_drawer(did)
            assert again is not None and "document" in again
            assert again.get("quarantined") is None
            assert again["metadata"]["content_sha256"] == hashlib.sha256(DOC.encode()).hexdigest()
        finally:
            dm.close()

    def test_legacy_empty_sha_rehashes_instead_of_quarantine(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            body = "Legacy body without checksum gets rehashed on read, not quarantined."
            col = dm._collection(create=True)
            col.upsert(
                documents=[body],
                ids=["drawer_w_r_1000000000000000000001"],
                metadatas=[{"wing": "w", "room": "r", "source_file": "/l.md", "filed_at": "2020-01-01T00:00:00+00:00"}],
            )
            got = dm.get_drawer("drawer_w_r_1000000000000000000001")
            assert got is not None and "document" in got
            assert got.get("quarantined") is None
            assert got["metadata"]["content_sha256"] == hashlib.sha256(body.encode()).hexdigest()
        finally:
            dm.close()

    def test_tampered_document_auto_quarantines_fail_closed(self, tmp_path: Path) -> None:
        dm = _dm(tmp_path)
        try:
            did = dm.add_drawer("w", "r", DOC, "/c.md", 0)
            col = dm._collection(create=False)
            # Tamper the document behind the metadata's back.
            raw = col.get(ids=[did], include=["documents", "metadatas"])
            assert isinstance(raw.metadatas[0], dict)
            col.upsert(
                documents=["TAMPERED body, checksum no longer matches."], ids=[did], metadatas=[raw.metadatas[0]]
            )
            before = int(dm.spine_counters().get("checksum_mismatches", 0))  # type: ignore[arg-type]
            got = dm.get_drawer(did)
            assert got is not None
            assert "document" not in got  # fail-closed: no document
            assert got.get("quarantined") is True
            assert got.get("quarantine_reason") == "checksum_mismatch"
            assert got["metadata"]["quarantined"] is True
            after = int(dm.spine_counters().get("checksum_mismatches", 0))  # type: ignore[arg-type]
            assert after == before + 1
            # Persisted: a second read stays fail-closed without double counting.
            again = dm.get_drawer(did)
            assert again is not None and "document" not in again
            assert int(dm.spine_counters().get("checksum_mismatches", 0)) == after  # type: ignore[arg-type]
        finally:
            dm.close()
