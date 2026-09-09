# Comparativa: Dxrk frente a otras formas de dar memoria a tus agentes

Comparación honesta a nivel de arquitectura. Del lado Dxrk solo hay afirmaciones
verificables en este repo; del lado rival, patrones típicos, no cifras.

## El problema

Un agente de IA sin memoria redescubre tu arquitectura en cada sesión
(600–900 tokens de wake-up por sesión en el mejor caso, mucho más sin sistema).
Las opciones habituales:

| Dimensión | Dxrk 1.0 | SaaS de memoria en la nube | Vector DB propia (Chroma/pgvector/…) | Notas markdown sueltas |
|---|---|---|---|---|
| Dónde viven tus datos | `~/.dxrk/` local, SQLite | Servidor de un tercero | Tu infra, tú la operas | Tus archivos |
| Red necesaria | No (offline total) | Sí, siempre | No | No |
| Dependencias pesadas | Ninguna (`sqlite3` stdlib, sin chromadb/onnx) | SDK del vendor | Servidor + embeddings (típicamente ONNX o API) | Ninguna |
| Búsqueda | FTS5 + BM25 híbrido, grafo temporal | La del vendor | La que configures | `grep` |
| Multi-tenant local | Sí (`tenants/{id}/`, RBAC admin/dev/readonly, vault HKDF) | Depende del plan | La construyes tú | Disciplina manual |
| Setup multi-agente | 1 comando, 42 agentes, presets | Por agente, a mano | Por agente, a mano | Por agente, a mano |
| Servidor MCP | Incluido (stdio, stdlib-only) | El del vendor | Lo construyes tú | No |
| Coste operativo | 0 (local, MIT) | Suscripción + egress | Tu tiempo de ops | 0 |
| Límite | Un nodo, tu disco | El del plan | Tu tuning | Tu memoria |

## Cuándo NO usar Dxrk

- Necesitas memoria compartida en tiempo real entre un equipo (Dxrk es local-first;
  el sync entre máquinas es rsync/git de `~/.dxrk/`, sin protocolo propio).
- Necesitas embeddings semánticos densos multilingües de última generación
  (Dxrk usa FTS5+BM25: excelente para código y notas, peor para paráfrasis lejanas).
- Tu organización prohíbe SQLite o exige un backend concreto (hay ADR abierto
  para plugin vectorial opcional, pero hoy es SQLite).
- Quieres memoria efímera por conversación sin persistencia (Dxrk persiste por diseño).

## Cuándo SÍ

- Trabajas solo o en equipo pequeño, offline o con red limitada.
- Quieres aislar clientes/proyectos (`tenant acme` vs `tenant personal`) sin servidores.
- Te importa auditar cada byte: cero telemetría, cero red, `uv audit` limpio.
- Ya vives en el terminal y quieres 42 agentes configurados con un comando.

Ver el [tutorial](tutorial.md) para probarlo en 10 minutos antes de creer esta tabla.
