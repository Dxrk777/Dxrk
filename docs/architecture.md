# Arquitectura

Este documento describe la estructura interna de Dxrk.

## Visión general

Dxrk es un configurador y orquestador de ecosistemas para agentes de IA,
escrito en Python 3.13+. Expone una CLI (`dxrk-py`) y una TUI (Textual), y se
integra con agentes de código mediante hooks, permisos y sesiones.

## Paquetes

| Paquete | Responsabilidad |
| --- | --- |
| `dxrk/autonomy/` | Evolución de prompts, aprendizaje, métricas, verificación |
| `dxrk/cli/` | Parsing de argumentos, instalador, dry-run, run |
| `dxrk/commands/` | Comandos del agente: plan, commit, PR, files, model, mcp, ... |
| `dxrk/config/` | Settings, perfiles, validación |
| `dxrk/mcp/` | Cliente de servidores MCP |
| `dxrk/observe/` | Observabilidad y trazado |
| `dxrk/query/` | Consultas de contexto y memoria |
| `dxrk/rag/` | Chunking, indexado y recuperación local |
| `dxrk/security/` | JWT, permisos, auditoría |
| `dxrk/system/` | Detección de sistema, instalación de herramientas |
| `dxrk/tools/` | Herramientas del agente (bash, files, http, ...) |
| `dxrk/trace/` | Trazado de sesiones |
| `dxrk/tui/` | Interfaz Textual |
| `dxrk/utils/` | Utilidades: fileops, diff, hooks, http, image, messages, ... |

## Flujo principal

1. `dxrk.__main__:main` despacha el comando solicitado.
2. `dxrk/config` carga settings y perfiles (modelos por fase).
3. `dxrk/commands/*` ejecuta la lógica de negocio (instalación, sync, plan, commit).
4. `dxrk/tools` y `dxrk/mcp` exponen capacidades al agente.
5. `dxrk/utils/hooks` y `dxrk/utils/permissions` controlan qué puede hacer el agente.
6. `dxrk/rag` y `dxrk/query` alimentan contexto desde la memoria.

## Persistencia

La memoria persistente la provee el binario externo `Dxrk-memory`
(repo `Dxrk777/dxrk-memory`), instalable vía Homebrew o GitHub Releases.
Los settings de usuario viven en el directorio de configuración del sistema
(`~/.config/dxrk/` en Linux/macOS).

## Tests

- `tests/` cubre adaptadores por agente, instalador, config, RAG y utils.
- Correr: `uv run pytest`.
- Tipos: `uv run --with mypy mypy dxrk/` (201 archivos, sin errores).
