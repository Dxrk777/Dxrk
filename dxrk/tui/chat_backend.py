# SPDX-License-Identifier: MIT
"""Chat backend for the Dxrk conversational TUI.

Sends user messages to the `opencode run` CLI (non-interactive) and parses
`--format json` events into plain text chunks. Local slash commands
(/help, /memory, /clear, /model, /free, /session) run without the backend.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


def find_opencode_binary() -> str:
    """Locate the `opencode` CLI, or "" when it is not installed."""
    override = os.environ.get("DXRK_OPENCODE_BIN", "")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    found = shutil.which("opencode")
    if found:
        return found
    home = os.path.expanduser("~")
    for candidate in (
        os.path.join(home, ".opencode", "bin", "opencode"),
        os.path.join(home, ".local", "bin", "opencode"),
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


_TEXT_KEYS = ("text", "delta", "content")


# Verified free default: opencode provider, cost 0, no user token needed.
FREE_DEFAULT_MODEL = "opencode/big-pickle"


def collect_text_chunks(payload: object, _depth: int = 0) -> list[str]:
    """Collect human-readable text from `opencode run --format json` events.

    Only descends into dicts that look like assistant/text output
    (type containing "text"/"delta", or role "assistant"), so echoed
    prompts and metadata never leak into the transcript.
    """
    chunks: list[str] = []
    if _depth > 6:
        return chunks
    if isinstance(payload, dict):
        type_str = str(payload.get("type", "")).lower()
        role = str(payload.get("role", "")).lower()
        if "delta" in type_str or "text" in type_str or role == "assistant":
            for key in _TEXT_KEYS:
                value = payload.get(key)
                if isinstance(value, str) and value:
                    chunks.append(value)
        for value in payload.values():
            chunks.extend(collect_text_chunks(value, _depth + 1))
    elif isinstance(payload, list):
        for item in payload:
            chunks.extend(collect_text_chunks(item, _depth + 1))
    return chunks


def parse_json_events(raw: str) -> str:
    """Turn `--format json` stdout into transcript text."""
    parts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload: object = json.loads(line)
        except ValueError:
            parts.append(line)
            continue
        parts.extend(collect_text_chunks(payload))
    return "".join(parts).strip()


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    text: str


@dataclass
class SlashResult:
    handled: bool
    reply: str = ""
    clear: bool = False


@dataclass
class ChatBackend:
    binary: str = ""
    model: str = ""
    session: str = ""
    directory: str = ""
    timeout: int = 300

    def __post_init__(self) -> None:
        if not self.binary:
            self.binary = find_opencode_binary()

    @property
    def available(self) -> bool:
        return bool(self.binary)

    def send(self, message: str) -> ChatMessage:
        """Send one message; returns the assistant reply (blocking call)."""
        if not self.binary:
            return ChatMessage(
                role="system",
                text="CLI de opencode no encontrada. Instálala o configura DXRK_OPENCODE_BIN.",
            )
        cmd = [self.binary, "run", "--format", "json"]
        if self.model:
            cmd += ["--model", self.model]
        if self.session:
            cmd += ["--session", self.session]
        if self.directory:
            cmd += ["--dir", self.directory]
        cmd.append(message)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ChatMessage(role="system", text=f"error del backend de chat: {exc}")
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or "error desconocido"
            return ChatMessage(role="system", text=f"opencode falló: {detail}")
        text = parse_json_events(proc.stdout)
        if self.session == "" and proc.stderr:
            maybe_session = _guess_session_id(proc.stderr)
            if maybe_session:
                self.session = maybe_session
        return ChatMessage(role="assistant", text=text or "(respuesta vacía)")

    def handle_slash(self, text: str) -> SlashResult:
        """Run a local /command. Never touches the opencode backend."""
        parts = text[1:].split(None, 1)
        name = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""
        if name in ("help", "h"):
            return SlashResult(handled=True, reply=_HELP_TEXT)
        if name == "clear":
            return SlashResult(handled=True, reply="", clear=True)
        if name == "model":
            if not arg:
                return SlashResult(
                    handled=True,
                    reply=f"modelo: {self.model or '(predeterminado)'}",
                )
            self.model = arg
            return SlashResult(handled=True, reply=f"modelo cambiado a {arg}")
        if name == "free":
            self.model = FREE_DEFAULT_MODEL
            return SlashResult(
                handled=True,
                reply=f"modelo gratuito activado: {FREE_DEFAULT_MODEL} (costo 0, sin token)",
            )
        if name == "session":
            if not arg:
                return SlashResult(
                    handled=True,
                    reply=f"sesión: {self.session or '(nueva en el próximo mensaje)'}",
                )
            self.session = arg
            return SlashResult(handled=True, reply=f"sesión cambiada a {arg}")
        if name == "memory":
            if not arg:
                return SlashResult(handled=True, reply="uso: /memory <query>")
            return SlashResult(handled=True, reply=self._search_memory(arg))
        return SlashResult(
            handled=True,
            reply=f"comando desconocido /{name}. Escribe /help para ver la lista.",
        )

    def _search_memory(self, query: str) -> str:
        cmd = [sys.executable, "-m", "dxrk.memory", "search", query]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"error al buscar en memoria: {exc}"
        out = proc.stdout.strip()
        if proc.returncode != 0:
            detail = proc.stderr.strip() or out or "error desconocido"
            return f"la búsqueda en memoria falló: {detail}"
        return out or "(sin resultados en memoria)"


_HELP_TEXT = """Comandos:
/help ............ muestra esta lista
/memory <query> .. busca en la memoria de Dxrk (tenant actual)
/model [name] .... muestra o cambia el proveedor/modelo (p. ej. /model anthropic/claude)
/free ............ activa el modelo gratuito verificado (costo 0, sin token)
/session [id] .... muestra o retoma una sesión de opencode por id
/clear ........... borra la conversación
Todo lo demás se envía al agente."""


def _guess_session_id(stderr: str) -> str:
    for line in stderr.splitlines():
        line = line.strip()
        if line.lower().startswith("session"):
            for token in line.split():
                token = token.strip(" :\"'")
                if len(token) >= 8 and all(c.isalnum() or c in "-_" for c in token):
                    return token
    return ""
