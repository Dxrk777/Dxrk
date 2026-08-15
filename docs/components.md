# Componentes

## Skills

Dxrk gestiona un registry de skills curadas (`dxrk-py skill-registry refresh`),
usadas por los agentes para tareas especializadas (SDD, memoria, batch, etc.).

## Servidores MCP

Dxrk configura hasta 35 servidores MCP vía `.mcp.json`. Cada servidor se
declara con nombre, comando y argumentos, y queda disponible para el agente.

## Memoria

- `dxrk-memory`: binario externo (repo `Dxrk777/dxrk-memory`) que provee
  memoria persistente con búsqueda semántica.
- `dxrk/rag/`: implementación local de chunking, indexado y recuperación.

## Hooks y permisos

- `dxrk/utils/hooks.py`: sistema de hooks (eventos, matcher glob/regex,
  registry thread-safe, circuit breaker, executor con timeout/retry, logger).
- `dxrk/utils/permissions.py`: política de permisos en JSON con capas.

## TUI

- `dxrk/tui/`: interfaz Textual con pantallas de detección, review, etc.

## Autonomía

- `dxrk/autonomy/`: evolución de prompts del sistema, aprendizaje,
  métricas y verificación automática de cambios.

## Conmutador de proveedores

Dxrk asigna modelos por fase del workflow (cheap / balanced / quality) y por
proveedor, mediante `dxrk-py sync --profile ...` y `--profile-phase ...`.

## Utilerías

- `dxrk/utils/diff.py`: diff LCS con formateadores (unified, side-by-side, HTML, JSON).
- `dxrk/utils/fileops.py`: operaciones de archivo atómicas y con caché.
- `dxrk/utils/http.py`: cliente HTTP con TLS y timeouts configurables.
- `dxrk/utils/image.py`: detección y procesamiento de imágenes (Pillow opcional).
- `dxrk/utils/messages.py`: primitivas de mensajes y formato de conversación.
