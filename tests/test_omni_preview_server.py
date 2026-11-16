# SPDX-License-Identifier: MIT
"""HTTP tests for the local Omni preview dashboard."""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from scripts import omni_preview
from scripts.omni_media import preview


def _run(root: Path, slug: str = "run-1") -> Path:
    workdir = root / slug
    (workdir / "assets").mkdir(parents=True)
    (workdir / "final.mp4").write_bytes(b"0123456789")
    (workdir / "contact_sheet.png").write_bytes(b"png")
    (workdir / "engine.log").write_text("line one\nline two\n", encoding="utf-8")
    (workdir / "assets" / "clip with space.mp4").write_bytes(b"clip")
    (workdir / "manifest.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "topic": "Demo",
                "mode": "short",
                "stage": "done",
                "progress": 1.0,
                "video": "final.mp4",
                "contact_sheet": "contact_sheet.png",
            }
        ),
        encoding="utf-8",
    )
    return workdir


@contextmanager
def _server(root: Path) -> Iterator[str]:
    server = omni_preview.make_server(root, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_dashboard_and_api_routes(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    workdir = _run(root)
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            dashboard = client.get("/")
            assert dashboard.status_code == 200
            assert "Dxrk Omni · Preview" in dashboard.text
            assert "text/html" in dashboard.headers["content-type"]
            assert client.get("/index.html").text == dashboard.text

            health = client.get("/healthz")
            assert health.status_code == 200
            assert health.json() == {"status": "ok", "runs": 1}

            runs = client.get("/api/runs").json()["runs"]
            assert len(runs) == 1
            run = runs[0]
            assert run["slug"] == "run-1"
            assert run["topic"] == "Demo"
            assert run["video_url"] == "/media/run-1/final.mp4"
            assert run["contact_sheet_url"] == "/media/run-1/contact_sheet.png"
            assert run["detail_url"] == "/api/runs/run-1"
            assert run["log_url"] == "/api/runs/run-1/log"

            detail = client.get("/api/runs/run-1")
            assert detail.status_code == 200
            payload = detail.json()
            assert payload["manifest"]["status"] == "ok"
            assert payload["video_url"] == "/media/run-1/final.mp4"
            assert payload["contact_sheet_url"] == "/media/run-1/contact_sheet.png"

            log = client.get("/api/runs/run-1/log")
            assert log.status_code == 200
            assert log.text == "line one\nline two\n"

            assert client.get("/api/runs/missing").status_code == 404
            assert client.get("/api/runs/missing/log").status_code == 404
            assert client.get("/api/runs/run-1/extra").status_code == 404
            assert client.get("/api/runs/run-1/log/extra").status_code == 404
            assert client.get("/api/runs").status_code == 200

            media = client.get("/media/run-1/final.mp4")
            assert media.status_code == 200
            assert media.content == b"0123456789"
            assert media.headers["content-type"] == "video/mp4"
            assert media.headers["accept-ranges"] == "bytes"

            spaced = client.get("/media/run-1/assets/clip%20with%20space.mp4")
            assert spaced.status_code == 200
            assert spaced.content == b"clip"

            assert client.get("/media/run-1/missing.mp4").status_code == 404
            assert client.get("/media/run-1/assets").status_code == 404
            assert client.get("/media/run-1/%2e%2e/outside.mp4").status_code == 404
            assert client.get("/media/missing/final.mp4").status_code == 404
            assert client.get("/media/run-1/").status_code == 404
            assert client.get("/nope").status_code == 404

            assert client.head("/media/run-1/final.mp4").status_code == 200
            assert client.head("/media/run-1/final.mp4").content == b""
            assert client.head("/media/run-1/").status_code == 405
            assert client.head("/api/runs").status_code == 405

    assert workdir.exists()


def test_range_requests(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    _run(root)
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            first = client.get("/media/run-1/final.mp4", headers={"Range": "bytes=0-3"})
            assert first.status_code == 206
            assert first.content == b"0123"
            assert first.headers["content-range"] == "bytes 0-3/10"

            rest = client.get("/media/run-1/final.mp4", headers={"Range": "bytes=4-"})
            assert rest.status_code == 206
            assert rest.content == b"456789"

            suffix = client.get("/media/run-1/final.mp4", headers={"Range": "bytes=-3"})
            assert suffix.status_code == 206
            assert suffix.content == b"789"
            assert suffix.headers["content-range"] == "bytes 7-9/10"

            oversized = client.get("/media/run-1/final.mp4", headers={"Range": "bytes=8-100"})
            assert oversized.status_code == 206
            assert oversized.content == b"89"
            assert oversized.headers["content-range"] == "bytes 8-9/10"

            for value in ("bytes=abc", "bytes=-", "bytes=20-", "bytes=5-3", "bytes=-0"):
                bad = client.get("/media/run-1/final.mp4", headers={"Range": value})
                assert bad.status_code == 416, value
                assert bad.headers["content-range"] == "bytes */10"


def test_host_validation(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    _run(root)
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            assert client.get("/healthz", headers={"Host": "evil.test"}).status_code == 403
            assert client.head("/media/run-1/final.mp4", headers={"Host": "evil.test"}).status_code == 403
            assert client.get("/healthz", headers={"Host": "localhost"}).status_code == 200
            assert client.get("/healthz", headers={"Host": "127.0.0.1"}).status_code == 200
            assert client.get("/healthz", headers={"Host": "[::1]"}).status_code == 200


def test_validate_host_missing_and_invalid() -> None:
    handler = object.__new__(omni_preview.PreviewHandler)
    handler.headers = {}  # type: ignore[assignment]
    handler.server = type("Server", (), {"server_address": ("0.0.0.0", 0)})()
    assert handler._validate_host() is True

    sent: list[tuple[int, str]] = []
    handler._send_error = lambda status, message: sent.append((status, message))  # type: ignore[method-assign]
    handler.headers = {"Host": ":"}
    assert handler._validate_host() is False
    assert sent == [(400, "Host inválido")]
    handler.headers = {"Host": "evil.test"}
    assert handler._validate_host() is False
    assert sent[-1] == (403, "Host no permitido")


def test_media_url_quote_and_jsonable(tmp_path: Path) -> None:
    root = tmp_path / "run"
    path = root / "assets" / "clip with space.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    assert omni_preview._media_url("run-1", path, root) == ("/media/run-1/assets/clip%20with%20space.mp4")
    assert omni_preview._quote("a/b c") == "a%2Fb%20c"
    assert omni_preview._jsonable({"a": [path, (1, 2)]}) == {"a": [str(path), [1, 2]]}
    assert omni_preview._jsonable(3) == 3
    assert omni_preview._content_type(path) == "video/mp4"
    assert omni_preview._content_type(root / "x.ass") == "text/plain; charset=utf-8"
    assert omni_preview._content_type(root / "x.log") == "text/plain; charset=utf-8"
    assert omni_preview._content_type(root / "x.txt") == "text/plain; charset=utf-8"
    assert omni_preview._content_type(root / "x.json") == "application/json; charset=utf-8"
    assert omni_preview._content_type(root / "x.m4a") == "audio/mp4"
    assert omni_preview._content_type(root / "x.png") == "image/png"
    assert omni_preview._content_type(root / "x.jpg") == "image/jpeg"
    assert omni_preview._content_type(root / "x.jpeg") == "image/jpeg"
    assert omni_preview._content_type(root / "x.unknown") == "application/octet-stream"


def test_detail_with_invalid_manifest_and_missing_media(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    workdir = _run(root)
    (workdir / "manifest.json").write_text("{", encoding="utf-8")
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            assert client.get("/api/runs/run-1").status_code == 404
            assert client.get("/api/runs/run-1/log").status_code == 200


def test_detail_ignores_missing_video_and_contact_sheet(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    workdir = _run(root)
    (workdir / "final.mp4").unlink()
    (workdir / "contact_sheet.png").unlink()
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            payload = client.get("/api/runs/run-1").json()
            assert payload["video_url"] is None
            assert payload["contact_sheet_url"] is None


def test_detail_without_media_keys(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    workdir = _run(root)
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("video")
    manifest.pop("contact_sheet")
    (workdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            payload = client.get("/api/runs/run-1").json()
            assert "video_url" not in payload
            assert "contact_sheet_url" not in payload


def test_serve_file_breaks_on_empty_read() -> None:
    class FakeHandle:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def seek(self, offset: int) -> None:
            return None

        def read(self, size: int) -> bytes:
            return b""

    class FakePath:
        name = "x.mp4"
        suffix = ".mp4"

        def stat(self):
            return type("Stat", (), {"st_size": 10})()

        def open(self, mode: str):
            return FakeHandle()

    handler = object.__new__(omni_preview.PreviewHandler)
    handler.headers = {}  # type: ignore[assignment]
    handler.wfile = io.BytesIO()
    responses: list[int] = []
    handler.send_response = lambda status: responses.append(status)  # type: ignore[method-assign]
    handler.send_header = lambda *args: None  # type: ignore[method-assign]
    handler.end_headers = lambda: None  # type: ignore[method-assign]
    handler._serve_file(FakePath())  # type: ignore[arg-type]
    assert responses == [200]


def test_log_read_error_returns_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "outputs"
    _run(root)

    def boom(path: Path) -> str:
        raise preview.PreviewError("no pude leer")

    monkeypatch.setattr(omni_preview, "read_log_tail", boom)
    with _server(root) as base:
        with httpx.Client(base_url=base, timeout=5) as client:
            response = client.get("/api/runs/run-1/log")
            assert response.status_code == 500
            assert response.json() == {"error": "no pude leer"}


def test_serve_file_missing_path() -> None:
    handler = object.__new__(omni_preview.PreviewHandler)
    handler.headers = {}  # type: ignore[assignment]
    handler.wfile = io.BytesIO()
    responses: list[int] = []
    handler.send_response = lambda status: responses.append(status)  # type: ignore[method-assign]
    handler.send_header = lambda *args: None  # type: ignore[method-assign]
    handler.end_headers = lambda: None  # type: ignore[method-assign]
    handler._serve_file(Path("/definitely/missing/file.mp4"))
    assert responses == [404]
    assert b"archivo no encontrado" in handler.wfile.getvalue()


def test_serve_and_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    class FakeServer:
        server_address = ("127.0.0.1", 12345)

        def __init__(self) -> None:
            self.closed = False
            self.interrupted = False

        def serve_forever(self) -> None:
            if self.interrupted:
                raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    fake = FakeServer()
    monkeypatch.setattr(omni_preview, "make_server", lambda root, host, port: fake)
    omni_preview.serve(tmp_path, port=0)
    output = capsys.readouterr().out
    assert "http://127.0.0.1:12345/" in output
    assert str(tmp_path.resolve()) in output
    assert fake.closed is True

    fake.interrupted = True
    omni_preview.serve(tmp_path, port=0)
    assert fake.closed is True

    captured: list[tuple[Path, str, int]] = []
    monkeypatch.setattr(
        omni_preview,
        "serve",
        lambda root, host, port: captured.append((root, host, port)),
    )
    assert omni_preview.main(["--root", str(tmp_path), "--host", "localhost", "--port", "0"]) == 0
    assert captured == [(tmp_path, "localhost", 0)]
    with pytest.raises(SystemExit):
        omni_preview.main(["--port", "70000"])


def test_build_parser_defaults() -> None:
    args = omni_preview.build_parser().parse_args([])
    assert args.root == "outputs"
    assert args.host == "127.0.0.1"
    assert args.port == 8765


def test_main_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import runpy
    import sys

    monkeypatch.setattr(sys, "argv", ["omni_preview.py", "--port", "70000"])
    with pytest.raises(SystemExit):
        runpy.run_path(str(Path(omni_preview.__file__)), run_name="__main__")
