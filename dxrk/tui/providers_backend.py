# SPDX-License-Identifier: MIT
"""Catálogo de proveedores de IA y gestión de credenciales vía opencode CLI.

Solo contiene datos verificados en vivo en esta máquina:
- Modelos gratuitos `opencode/*` (costo 0, sin token): `opencode run`
  responde con `cost: 0` y sin credencial del usuario.
- Formato `auth.json` (`{type, key}` por provider) y lectura vía
  `$XDG_DATA_HOME/opencode/auth.json`: inyección con HOME aislado leída
  por `opencode auth list` y aceptada estructuralmente por `opencode run`.
- Conteo de modelos por provider extraído de `models.dev/api.json`.

Los secretos nunca se registran en logs ni se devuelven en listados:
`solo se comprueba presencia de la clave, jamás su valor.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    """Un proveedor del catálogo. `kind` es `free` (sin token) o `api` (token)."""

    id: str
    label: str
    kind: str
    detail: str
    models: tuple[str, ...] = ()


FREE_PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        id="opencode",
        label="opencode (gratis, sin token)",
        kind="free",
        detail="Costo 0 verificado en vivo. Recomendado: big-pickle. Elige modelo con /model en el chat.",
        models=(
            "opencode/big-pickle",
            "opencode/ling-3.0-flash-fin-free",
            "opencode/mimo-v2.5-free",
            "opencode/muse-spark-1.2-contributor-free",
            "opencode/muse-spark-1.3-contributor-free",
            "opencode/nemotron-3-ultra-free",
            "opencode/nemotron-3.5-lightning-free",
        ),
    ),
)

# Conteos verificados desde models.dev/api.json. El método de auth de cada
# proveedor lo define opencode (`opencode auth login`); el pegado de token de
# Dxrk escribe la forma estándar {type: "api"} que opencode acepta.
PAID_PROVIDERS: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        id="openrouter",
        label="1 · OpenRouter",
        kind="api",
        detail="365 modelos (incluye :free con key: 20/min, 50/día sin créditos)",
    ),
    ProviderInfo(id="google", label="2 · Google", kind="api", detail="39 modelos (Gemini; 3.1 Pro ref. $2/$12)"),
    ProviderInfo(
        id="deepseek", label="3 · DeepSeek", kind="api", detail="4 modelos (V4 ref. $0.44/$0.87, el más barato capaz)"
    ),
    ProviderInfo(id="mistral", label="4 · Mistral", kind="api", detail="34 modelos"),
    ProviderInfo(id="groq", label="5 · Groq", kind="api", detail="16 modelos"),
    ProviderInfo(id="xai", label="6 · xAI", kind="api", detail="12 modelos (Grok)"),
    ProviderInfo(id="cohere", label="7 · Cohere", kind="api", detail="14 modelos"),
    ProviderInfo(id="cerebras", label="8 · Cerebras", kind="api", detail="2 modelos"),
    ProviderInfo(
        id="github-copilot", label="9 · GitHub Copilot", kind="api", detail="28 modelos (requiere suscripción Copilot)"
    ),
)

ALL_PROVIDERS: tuple[ProviderInfo, ...] = FREE_PROVIDERS + PAID_PROVIDERS


def auth_file_path(home: str = "") -> str:
    """Ruta de `auth.json` respetando `$XDG_DATA_HOME` (como hace opencode)."""
    data_home = os.environ.get("XDG_DATA_HOME")
    if not data_home:
        data_home = os.path.join(home or os.path.expanduser("~"), ".local", "share")
    return os.path.join(data_home, "opencode", "auth.json")


def connected_providers(path: str = "") -> set[str]:
    """IDs con credencial guardada. Solo mira presencia, nunca valores."""
    target = path or auth_file_path()
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return set()
    if not isinstance(data, dict):
        return set()
    return {pid for pid, entry in data.items() if isinstance(entry, dict) and entry.get("key")}


def validate_provider_id(provider_id: str, binary: str = "opencode", timeout: int = 60) -> bool:
    """True si opencode conoce el provider (`opencode models <id>`, rc 0)."""
    pid = (provider_id or "").strip()
    if not pid or any(c.isspace() for c in pid):
        return False
    try:
        proc = subprocess.run(
            [binary, "models", pid],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def save_api_token(provider_id: str, token: str, path: str = "") -> str:
    """Guarda `{type: "api", key: token}` en `auth.json` (con copia .bak).

    Devuelve la ruta escrita. Lanza ValueError con mensaje en español si
    el provider o el token están vacíos.
    """
    pid = (provider_id or "").strip()
    if not pid:
        raise ValueError("id de proveedor vacío")
    secret = (token or "").strip()
    if not secret:
        raise ValueError("token vacío")
    target = path or auth_file_path()
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            backup = f.read()
        with open(target + ".bak", "w", encoding="utf-8") as f:
            f.write(backup)
    data[pid] = {"type": "api", "key": secret}
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
    return target
