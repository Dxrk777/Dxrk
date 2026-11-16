# SPDX-License-Identifier: MIT
"""Local, read-only preview dashboard for Dxrk Omni runs.

Run it with::

    uv run python scripts/omni_preview.py --root outputs

The server uses only the Python standard library. It binds to localhost by
default, never writes to the outputs tree, and serves only files that resolve
inside a run directory.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    from scripts.omni_media.preview import (
        PreviewError,
        discover_runs,
        load_manifest,
        read_log_tail,
        resolve_media_path,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from omni_media.preview import (  # type: ignore[no-redef]
        PreviewError,
        discover_runs,
        load_manifest,
        read_log_tail,
        resolve_media_path,
    )

DASHBOARD_HTML = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dxrk Omni · Preview</title>
<style>
:root { color-scheme: dark; --bg:#0b0d12; --panel:#141821; --line:#252c3a; --text:#e8ecf5; --muted:#8d98ad; --accent:#5ee0c0; --warn:#ffcc66; --bad:#ff7b8a; }
* { box-sizing: border-box; }
body { margin:0; font:15px/1.5 system-ui, sans-serif; background:var(--bg); color:var(--text); }
header { padding:28px 24px 16px; max-width:1200px; margin:0 auto; }
h1 { margin:0 0 4px; font-size:24px; letter-spacing:.02em; }
header p { margin:0; color:var(--muted); }
main { max-width:1200px; margin:0 auto; padding:16px 24px 48px; }
#runs { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:16px; min-height:180px; }
.card h2 { margin:0 0 6px; font-size:17px; overflow-wrap:anywhere; }
.meta { margin:0 0 12px; color:var(--muted); font-size:13px; }
.status { font-weight:600; }
.status.ok { color:var(--accent); }
.status.failed { color:var(--bad); }
.status.running { color:var(--warn); }
.bar { height:6px; background:#0a0c10; border-radius:99px; overflow:hidden; margin:8px 0 14px; }
.bar span { display:block; height:100%; background:var(--accent); }
.links { display:flex; flex-wrap:wrap; gap:8px; }
.links a { color:var(--text); text-decoration:none; border:1px solid var(--line); border-radius:8px; padding:6px 9px; font-size:13px; }
.links a:hover { border-color:var(--accent); color:var(--accent); }
.empty { color:var(--muted); padding:24px 0; }
</style>
</head>
<body>
<header>
  <h1>Dxrk Omni · Preview</h1>
  <p>Catálogo local de runs, videos finales, audio, contact sheets y logs.</p>
</header>
<main><div id="runs"><p class="empty">Cargando…</p></div></main>
<script>
const runsEl = document.getElementById('runs');
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function load() {
  try {
    const response = await fetch('/api/runs', {cache: 'no-store'});
    if (!response.ok) throw new Error('HTTP ' + response.status);
    const data = await response.json();
    const runs = data.runs || [];
    runsEl.replaceChildren();
    if (!runs.length) {
      runsEl.append(el('p', 'Todavía no hay runs en outputs/.', 'empty'));
      return;
    }
    for (const run of runs) {
      const card = el('article', undefined, 'card');
      card.append(el('h2', run.topic));
      const meta = el('p', `${run.mode} · ${run.stage || '—'} · ${run.updated_at || ''}`, 'meta');
      const status = el('span', run.status, 'status ' + run.status);
      meta.prepend(status);
      meta.append(document.createTextNode(' · '));
      card.append(meta);
      if (typeof run.progress === 'number') {
        const bar = el('div', undefined, 'bar');
        const fill = el('span');
        fill.style.width = Math.max(0, Math.min(100, Math.round(run.progress * 100))) + '%';
        bar.append(fill);
        card.append(bar);
      }
      const links = el('div', undefined, 'links');
      if (run.video_url) {
        const a = el('a', 'Video'); a.href = run.video_url; a.target = '_blank'; a.rel = 'noopener'; links.append(a);
      }
      if (run.contact_sheet_url) {
        const a = el('a', 'Contact sheet'); a.href = run.contact_sheet_url; a.target = '_blank'; a.rel = 'noopener'; links.append(a);
      }
      const log = el('a', 'Log'); log.href = run.log_url; log.target = '_blank'; log.rel = 'noopener'; links.append(log);
      card.append(links);
      runsEl.append(card);
    }
  } catch (error) {
    runsEl.replaceChildren(el('p', 'Error cargando runs: ' + error.message, 'empty'));
  }
}
load();
setInterval(load, 2000);
</script>
</body>
</html>
"""


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _media_url(slug: str, path: Path, root: Path) -> str:
    relative = Path(path).resolve().relative_to(Path(root).resolve())
    encoded = "/".join(_quote(part) for part in relative.parts)
    return f"/media/{_quote(slug)}/{encoded}"


def _content_type(path: Path) -> str:
    overrides = {
        ".ass": "text/plain; charset=utf-8",
        ".log": "text/plain; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".m4a": "audio/mp4",
        ".mp4": "video/mp4",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = "DxrkOmniPreview/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib API
        return

    def _validate_host(self) -> bool:
        host = self.headers.get("Host", "")
        if not host:
            return True
        hostname = urllib.parse.urlsplit("//" + host).hostname
        if hostname is None:
            self._send_error(400, "Host inválido")
            return False
        allowed = {"localhost", "127.0.0.1", "::1"}
        address: Any = getattr(self.server, "server_address", ("", 0))
        bind_host = str(address[0])
        if bind_host not in {"0.0.0.0", "::", ""}:
            allowed.add(bind_host)
        if hostname not in allowed:
            self._send_error(403, "Host no permitido")
            return False
        return True

    def _send_bytes(self, payload: bytes, *, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if getattr(self, "command", "") != "HEAD":
            self.wfile.write(payload)

    def _send_text(self, text: str, *, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        self._send_bytes(text.encode("utf-8"), content_type=content_type, status=status)

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(_jsonable(payload), ensure_ascii=False, indent=2).encode("utf-8")
        self._send_bytes(body, content_type="application/json; charset=utf-8", status=status)

    def _send_error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status=status)

    def _run_payload(self, run: Any) -> dict[str, Any]:
        video_url = _media_url(run.slug, run.video, run.workdir) if run.video else None
        contact_url = _media_url(run.slug, run.contact_sheet, run.workdir) if run.contact_sheet else None
        return {
            "slug": run.slug,
            "status": run.status,
            "topic": run.topic,
            "mode": run.mode,
            "stage": run.stage,
            "updated_at": run.updated_at,
            "progress": run.progress,
            "video_url": video_url,
            "contact_sheet_url": contact_url,
            "detail_url": f"/api/runs/{_quote(run.slug)}",
            "log_url": f"/api/runs/{_quote(run.slug)}/log",
        }

    def _detail(self, slug: str) -> None:
        workdir = self.root / slug
        if not workdir.is_dir():
            self._send_error(404, "run no encontrado")
            return
        try:
            manifest = load_manifest(workdir)
        except PreviewError as exc:
            self._send_error(404, str(exc))
            return
        payload: dict[str, Any] = {"slug": slug, "manifest": manifest}
        if manifest.get("video"):
            path = resolve_media_path(workdir, str(manifest["video"]))
            payload["video_url"] = _media_url(slug, path, workdir) if path else None
        if manifest.get("contact_sheet"):
            path = resolve_media_path(workdir, str(manifest["contact_sheet"]))
            payload["contact_sheet_url"] = _media_url(slug, path, workdir) if path else None
        payload["log_url"] = f"/api/runs/{_quote(slug)}/log"
        self._send_json(payload)

    def _log(self, slug: str) -> None:
        workdir = self.root / slug
        if not workdir.is_dir():
            self._send_error(404, "run no encontrado")
            return
        try:
            text = read_log_tail(workdir / "engine.log")
        except PreviewError as exc:
            self._send_error(500, str(exc))
            return
        self._send_text(text)

    def _serve_file(self, path: Path, *, head_only: bool = False) -> None:
        try:
            size = path.stat().st_size
        except OSError:
            self._send_error(404, "archivo no encontrado")
            return
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self._range_error(size)
                return
            left, right = match.groups()
            if left:
                start = int(left)
                end = int(right) if right else size - 1
            elif right:
                length = int(right)
                start = max(0, size - length)
                end = size - 1
            else:
                self._range_error(size)
                return
            if start >= size or start > end:
                self._range_error(size)
                return
            end = min(end, size - 1)
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", _content_type(path))
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _range_error(self, size: int) -> None:
        self.send_response(416)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _media(self, slug: str, raw: str, *, head_only: bool = False) -> None:
        workdir = self.root / slug
        if not workdir.is_dir():
            self._send_error(404, "run no encontrado")
            return
        path = resolve_media_path(workdir, raw)
        if path is None:
            self._send_error(404, "archivo no encontrado")
            return
        self._serve_file(path, head_only=head_only)

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        if not self._validate_host():
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path in {"/", "/index.html"}:
            self._send_text(DASHBOARD_HTML, content_type="text/html; charset=utf-8")
            return
        if path == "/healthz":
            self._send_json({"status": "ok", "runs": len(discover_runs(self.root))})
            return
        if path == "/api/runs":
            self._send_json({"runs": [self._run_payload(run) for run in discover_runs(self.root)]})
            return
        if path.startswith("/api/runs/"):
            parts = [part for part in path.strip("/").split("/") if part]
            if len(parts) == 3:
                self._detail(parts[2])
                return
            if len(parts) == 4 and parts[3] == "log":
                self._log(parts[2])
                return
        if path.startswith("/media/"):
            parts = path.split("/", 3)
            if len(parts) == 4 and parts[1] == "media" and parts[2] and parts[3]:
                self._media(parts[2], parts[3])
                return
        self._send_error(404, "not found")

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib API
        if not self._validate_host():
            return
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path.startswith("/media/"):
            parts = path.split("/", 3)
            if len(parts) == 4 and parts[1] == "media" and parts[2] and parts[3]:
                self._media(parts[2], parts[3], head_only=True)
                return
        self._send_error(405, "method not allowed")


def make_server(root: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), PreviewHandler)
    server.root = Path(root).resolve()  # type: ignore[attr-defined]
    return server


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = make_server(root, host, port)
    actual_host, actual_port = server.server_address[:2]
    print(f"Dxrk Omni preview: http://{actual_host}:{actual_port}/")
    print(f"Runs root: {Path(root).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dxrk-omni-preview",
        description="Dashboard local de runs de Dxrk Omni.",
    )
    parser.add_argument("--root", default="outputs", help="Directorio raíz de runs (default: outputs)")
    parser.add_argument("--host", default="127.0.0.1", help="Host de escucha (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Puerto (default: 8765)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        build_parser().error("--port debe estar entre 0 y 65535")
    serve(Path(args.root), host=str(args.host), port=int(args.port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
