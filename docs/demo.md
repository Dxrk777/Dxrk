# Demo 60 segundos — DxrkMemory + session recall

> Runnable: `bash demo/demo-60s.sh` (~2 s, no interactivo).
> Todo vive en `mktemp` dirs (`HOME` redirigido): palace, sesiones,
> hooks e identidad se limpian al salir. Nunca toca tu `~/.dxrk` real.

## El guion (leelo mientras corren los comandos)

| # | Decís | Comando que corre | Qué prueba |
|---|-------|-------------------|------------|
| 1 | "Minamos un proyectito de 3 archivos a un palace temporal" | `python -m dxrk.memory mine $SAMPLE --wing demo` | Ingesta real: `files_mined: 3`. Mismo entry point que usa el hook de auto-ingest (`dxrk/memory/__main__.py`, flags `--wing/--room/--dry-run` verificados) |
| 2 | "grep no encuentra nada; la memoria sí" | `grep -riF "how do I authenticate API users"` → sin hits, luego `python -m dxrk.memory search … --wing demo` → top-1 `auth.py` | Hybrid search (FTS5 trigram + coseno de char-trigramas con IDF + rerank BM25, `dxrk/memory/search.py` + `vectors.py`): el query parafasea, no repite keywords. El diseño trigrama es literalmente el ejemplo del docstring de `vectors.py` (`auth` ~ `authentication`) |
| 3 | "Pineamos lo importante; el status lo confirma en budgets" | MCP `dxrk_memory_pin` + `dxrk_memory_status` (vía `DXRK_MEMORY_PATH`, stdio JSON-RPC a `dxrk/memory/mcp_server.py`) | El pin existe de verdad: `budgets.demo.pinned: 1`. De paso se siembra un episodio `session:demo-001` por el mismo write path que usa `hook_stop` (`hooks_cli._save_session_summary_direct`) |
| 4 | "La timeline episódica: sesiones + pins en orden" | MCP `dxrk_memory_timeline` | `kind: session` y `kind: pin` cronológicos (`DxrkMemory.timeline`, ventana `[since, before)`) |
| 5 | "Cada sesión arranca recordando: L0 + L1" | `echo '{"session_id":"demo-60s",…}' \| python -m dxrk.memory.hooks_cli session-start dxrk` | `hook_session_start` → `MemoryStack.wake_up` (`dxrk/memory/layers.py`): identidad L0 + story L1 con los drawers top |
| 6 | "Y las sesiones viven en sqlite" | `session create/list/info` vía `Registry.execute` (nombres y flags `--limit/--status/--tag` verificados en `dxrk/commands/session.py`) con `DXRK_SESSION_BACKEND=sqlite` | Backend seleccionable por env var (`dxrk/utils/session_storage.py`); `info` resuelve por prefijo de id |

## Para probar después (deliberadamente fuera de los 60 s)

- `dxrk_memory_consolidate` (funde ≥2 drawers en un destilado que los supersede) y `dxrk_memory_forget` (scoped erase, soft por defecto) — verificados manualmente contra MCP stdio (`sources: 2`, `soft_forgotten: 1`, exit 0), pero mutan el palace y romperían el paso 2 si van antes.
- Familia KG (`kg_add/query/timeline/traverse/stats`), `check_duplicate`, `graph_stats`, `update/delete_drawer` — reales en `mcp_server.py:TOOLS`, fuera del arco narrativo.
- `stop` / `precompact` hooks y `DXRK_TENANT` multi-tenant: ver `docs/memory.md`, `docs/session.md` y `docs/tenants.md`.
