# Arquitectura

Este documento describe la estructura interna de Dxrk y de su pipeline multimedia.

## Visión general

Dxrk es un motor open-source de automatización y generación multimedia para agentes de IA, escrito en Python 3.14+. Expone una CLI (`dxrk-py`) y una TUI (Textual), se integra con agentes de código mediante hooks, permisos y sesiones, y ofrece **Dxrk Omni** como pipeline multimedia aislado del paquete principal.

La arquitectura separa dos dominios:

| Dominio | Ubicación | Responsabilidad |
| --- | --- | --- |
| **Core / agentes** | `dxrk/` | Instalación, configuración, memoria, MCP, SDD, permisos, TUI y workflows Git. |
| **Omni / multimedia** | `scripts/` | Guion, imágenes, narración, subtítulos, música y montaje con FFmpeg. |

Omni no forma parte del paquete `dxrk`. Es un pipeline experimental con binarios y servicios externos; sus tests viven en `tests/test_omni_*.py` y no debilitan el contrato de cobertura del core.

## Paquetes del core

| Paquete | Responsabilidad |
| --- | --- |
| `dxrk/autonomy/` | Solo vocabulario de capabilities (`permissions.py`, incluye `memory.maintain`); el loop self-update/self-verify/self-learn se eliminó |
| `dxrk/judge/` | Juez externo de verificación (observe-only, auto-fix default-off) |
| `dxrk/cli/` | Parsing de argumentos, instalador, dry-run, run |
| `dxrk/commands/` | Comandos del agente: plan, commit, PR, files, model, mcp, ... |
| `dxrk/config/` | Settings, perfiles, validación |
| `dxrk/mcp/` | Cliente de servidores MCP sobre stdio y JSON-RPC |
| `dxrk/observe/` | Observabilidad y trazado |
| `dxrk/query/` | Consultas de contexto y memoria |
| `dxrk/rag/` | Chunking, indexado y recuperación local |
| `dxrk/security/` | JWT, permisos, auditoría |
| `dxrk/system/` | Detección de sistema, instalación de herramientas |
| `dxrk/tools/` | Herramientas del agente (bash, files, http, ...) |
| `dxrk/trace/` | Trazado de sesiones |
| `dxrk/tui/` | Interfaz Textual |
| `dxrk/utils/` | Utilidades: fileops, diff, hooks, http, image, messages, ... |

## Flujo principal del core

1. `dxrk.__main__:main` despacha el comando solicitado.
2. `dxrk/config` carga settings y perfiles (modelos por fase).
3. `dxrk/commands/*` ejecuta la lógica de negocio (instalación, sync, plan, commit).
4. `dxrk/tools` y `dxrk/mcp` exponen capacidades al agente.
5. `dxrk/utils/hooks` y `dxrk/utils/permissions` controlan qué puede hacer el agente.
6. `dxrk/rag` y `dxrk/query` alimentan contexto desde la memoria.

## Pipeline de Dxrk Omni

```text
tema
  └─> guion (LLM opcional, fallback determinista)
      └─> imágenes (ComfyUI / SD WebUI / locales / placeholder)
          └─> narración (Edge-TTS) + word timings (Whisper / proporcional)
              └─> música (FFmpeg synth / MusicGen / Stable Audio / track)
                  └─> montaje FFmpeg
                      └─> final.mp4 (1080x1920, 30 fps, H.264/AAC)
```

| Módulo | Responsabilidad |
| --- | --- |
| `scripts/omni.py` | Orquestación, CLI, guion, montaje y manifest. |
| `scripts/omni_media/images.py` | ComfyUI, SD WebUI, Pollinations, imágenes locales y placeholders. |
| `scripts/omni_media/longform.py` | Plan de capítulos y shots para long-form. |
| `scripts/omni_media/music.py` | Synth con FFmpeg, MusicGen, Stable Audio y concatenación con crossfades. |
| `scripts/omni_media/words.py` | Word timings, ASS karaoke y transcripción con Whisper. |

Cada etapa escribe sus artefactos en `outputs/<slug>-<timestamp>/`. El `manifest.json` registra estado, timings, fuentes de imagen, errores y motivos de fallback. Los backends externos se cargan de forma lazy y solo cuando se seleccionan.

### Backends y fallbacks

- **Imágenes:** `auto` prueba ComfyUI, luego SD WebUI, luego placeholder. Pollinations se usa solo de forma explícita.
- **Subtítulos:** `edge` usa `WordBoundary`; `whisper` usa `faster-whisper`; `proportional` distribuye por peso de caracteres.
- **Música:** `synth` usa FFmpeg; `musicgen` y `stable-audio` generan por chunks con crossfades; `file` usa una pista propia.
- **Guion:** LLM compatible con OpenAI (Ollama por defecto); si falla, se usa un plan determinista.

## Persistencia

La memoria persistente la provee DxrkMemory 2.0, implementación 100% Python stdlib-only (`dxrk/memory`: SQLite FTS5 + BM25, grafo temporal, AAAK y layers, sin binarios externos). Los settings de usuario viven en el directorio de configuración del sistema (`~/.config/dxrk/` en Linux/macOS).

Los artefactos de Omni viven en `outputs/`, que está ignorado por Git.

## Tests

- `tests/` cubre adaptadores por agente, instalador, config, RAG, utils y el pipeline Omni.
- Correr la suite completa: `uv run python -m pytest`.
- Correr solo Omni: `uv run python -m pytest -q --no-cov tests/test_omni_script.py tests/test_omni_advanced.py`.
- Gate actual: **7.406 passed, 1 skipped, 100.00% coverage**.
- Tipos: `uv run mypy dxrk` (**367 archivos**, sin errores).
- Lint: `uvx ruff check dxrk tests`.
