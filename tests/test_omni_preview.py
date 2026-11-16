# SPDX-License-Identifier: MIT
"""Tests for read-only Omni preview discovery helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.omni_media import preview


def _run(root: Path, slug: str, payload: dict) -> Path:
    workdir = root / slug
    workdir.mkdir(parents=True)
    (workdir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return workdir


def test_load_manifest_and_errors(tmp_path: Path) -> None:
    workdir = _run(tmp_path, "run", {"status": "ok"})
    assert preview.load_manifest(workdir)["status"] == "ok"
    with pytest.raises(preview.PreviewError, match="no pude leer"):
        preview.load_manifest(tmp_path / "missing")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "manifest.json").write_text("{", encoding="utf-8")
    with pytest.raises(preview.PreviewError, match="inválido"):
        preview.load_manifest(bad)
    not_object = tmp_path / "list"
    not_object.mkdir()
    (not_object / "manifest.json").write_text("[]", encoding="utf-8")
    with pytest.raises(preview.PreviewError, match="objeto"):
        preview.load_manifest(not_object)


def test_resolve_media_path_inside_and_escapes(tmp_path: Path) -> None:
    workdir = tmp_path / "run"
    media = workdir / "assets" / "video.mp4"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"video")
    assert preview.resolve_media_path(workdir, "assets/video.mp4") == media.resolve()
    assert preview.resolve_media_path(workdir, media) == media.resolve()
    assert preview.resolve_media_path(workdir, "../outside.mp4") is None
    assert preview.resolve_media_path(workdir, "/etc/passwd") is None
    assert preview.resolve_media_path(workdir, "assets") is None
    assert preview.resolve_media_path(workdir, "missing.mp4") is None
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    link = workdir / "link.mp4"
    link.symlink_to(outside)
    assert preview.resolve_media_path(workdir, "link.mp4") is None


def test_discover_runs_filters_and_orders(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    first = _run(
        root,
        "first",
        {
            "status": "ok",
            "topic": "First",
            "video": "final.mp4",
            "contact_sheet": "contact_sheet.png",
            "progress": 1.0,
        },
    )
    (first / "final.mp4").write_bytes(b"v")
    (first / "contact_sheet.png").write_bytes(b"c")
    second = _run(root, "second", {"status": "failed", "longform": True, "progress": "bad"})
    _run(root, "third", {"created_at": "2026-01-01T00:00:00"})
    _run(root, ".hidden", {"status": "ok"})
    (root / "not-a-run").write_text("x", encoding="utf-8")
    (root / "broken").mkdir()
    (root / "broken" / "manifest.json").write_text("{", encoding="utf-8")
    runs = preview.discover_runs(root)
    assert [run.slug for run in runs] == ["third", "second", "first"]
    first_run = runs[-1]
    assert first_run.topic == "First"
    assert first_run.video == (first / "final.mp4").resolve()
    assert first_run.contact_sheet == (first / "contact_sheet.png").resolve()
    assert first_run.progress == 1.0
    second_run = runs[1]
    assert second_run.mode == "longform"
    assert second_run.progress is None
    assert second_run.status == "failed"
    third_run = runs[0]
    assert third_run.topic == "third"
    assert third_run.updated_at == "2026-01-01T00:00:00"
    assert third_run.video is None
    assert preview.discover_runs(tmp_path / "missing") == []
    assert preview.discover_runs(second) == []


def test_discover_runs_handles_stat_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeRun:
        name = "fake"

        def is_dir(self) -> bool:
            return True

        def stat(self) -> object:
            raise OSError("gone")

    root = tmp_path / "outputs"
    root.mkdir()
    monkeypatch.setattr(Path, "iterdir", lambda self: iter([FakeRun()]))
    monkeypatch.setattr(preview, "load_manifest", lambda workdir: {"status": "ok", "topic": "Fake"})
    runs = preview.discover_runs(root)
    assert len(runs) == 1
    assert runs[0].slug == "fake"
    assert runs[0].updated_at


def test_read_log_tail(tmp_path: Path) -> None:
    log = tmp_path / "engine.log"
    assert preview.read_log_tail(log) == ""
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    assert preview.read_log_tail(log) == "one\ntwo\nthree\n"
    tail = preview.read_log_tail(log, max_bytes=8)
    assert tail == "three\n"
    log.write_text("x" * 100, encoding="utf-8")
    assert preview.read_log_tail(log, max_bytes=10) == "x" * 10
    with pytest.raises(preview.PreviewError, match="positivo"):
        preview.read_log_tail(log, max_bytes=0)


def test_read_log_tail_wraps_os_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "engine.log"
    log.write_text("x", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(Path, "stat", boom)
    with pytest.raises(preview.PreviewError, match="no pude leer"):
        preview.read_log_tail(log)
