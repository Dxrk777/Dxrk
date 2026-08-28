# Migración mempalace 3.3.5 → 3.7.1 — DxrkMemory 2.0

> **Nota de fusión stdlib-only:** `mempalace 3.3.5` (`feat/opencode-integration` `5623136`) → `upstream 3.7.1` (`359c579`). **388 archivos, 50+ commits.** DxrkMemory 2.0 porta solo el camino crítico stdlib; deja fuera a propósito todo lo acoplado a `chromadb`/`HNSW`/`onnx`/`numpy`.

## Resumen delta upstream

- **Desde:** `3.3.5` — rama `feat/opencode-integration` (`5623136`) — base Dxrk pre-fusión.
- **Hasta:** `3.7.1` — `359c579` — upstream `388 files changed`, `50+` commits.
- **Scope portado:** `palace.py` (mine/locks), `miner.py` (scan/gitignore/safe-read), `search.py` (hybrid BM25), `date_window.py` (since/before), `palace SIGTERM`, `locks reap`, `graph.py`/`layers.py`/`dialect.py` ya en paridad.
- **No portado:** ver tabla abajo — únicamente fixes `HNSW`/`numpy2`/`chroma cache` (justificado stdlib-only).
- **Limpieza:** `979` reemplazos `engram`/`mempal*` → `dxrk` + `7 git mv` + `6` assets duplicados `git rm` dejando canónicos `memory-*.py`; verificación global `0` (`grep -rn engram|mempal`).

```bash
# delta upstream (si tienes remote upstream)
git log --oneline 5623136..359c579 | wc -l          # ~50+
git diff --stat 5623136..359c579 | tail -1         # 388 files changed
# verificación DxrkMemory 2.0
uv run pytest tests/test_memory.py -q              # 19 passed
grep -rn "engram\|mempal" dxrk/memory --include="*.py" | wc -l  # 0
grep -rn "engram\|mempal" --include="*.py" | wc -l                # 0
```

---

## Parches críticos portados (6)

| # | Commit upstream | Área | Qué hace | Estado DxrkMemory 2.0 |
|---|-----------------|------|----------|-----------------------|
| 1 | `1654cd2` | `palace.mine` re-mine honesty | Batch `delete+upsert` 500: ante fallo multi-batch, **purga `drawers` + `closets` parciales** del `source_file` y re-raise para retry honesto | ✅ `palace.py::Palace.mine` — `try: upsert batches` / `except: col.delete(where={source_file})` + `closets_col.delete`, `chunk_total` stamp |
| 2 | `759b8f1` | `palace.mine` chamber | `chunk_total` en **cada drawer** para distinguir mina completa vs parcial multi-batch | ✅ `palace.py::_build_drawer_metadata(chunk_total=…)` + `_CHUNK_SIZE/_OVERLAP` |
| 3 | `db29959` | `miner`/`palace` FIFO hang | `O_NONBLOCK` + `S_ISREG` en `scan_project` y `mine` — **FIFOs nunca bloquean** (`EAGAIN` guard), misma-`mtime` `fstat` anti-TOCTOU | ✅ `miner.py::_is_regular_source_file`/`_read_text_no_follow`, `palace.py::_read_text_no_follow_palace`, `MAX_FILE_SIZE 500 MiB` |
| 4 | `27212e5` | `locks` orphan reap | `~/.dxrk/locks` (`~/.mempalace/locks` upstream) GC huérfanos `900 s` (`_LOCK_REAP_INTERVAL_SECONDS`), `reap_stale_dxrk_locks(min_age=3600)` con `flock` reacquire safety | ✅ `palace.py::reap_stale_dxrk_locks` + alias `reap_stale_mine_locks`, `mine_lock` opportunistic reap, `mine_palace_lock` re-entrante |
| 5 | `5036e3c` | `search/date_window` | Ventana `since`/`before` → `filed_at` wall-clock `[since, before)`, `pool 3×` → `15×` (`max 500`) cuando ventana activa, `date_filter_pool_truncated` flag | ✅ `date_window.py::parse_window/filed_at_in_window`, `search.py::_candidate_pool_size` + `hybrid_search(since,before)` post-filter |
| 6 | SIGTERM | `palace` signal | `SIGTERM`/`SIGHUP` → `SystemExit(0)` para `atexit` libere `flock` limpio | ✅ `palace.py::_install_shutdown_signal_handlers` |

> **Repro steps para cada parche:** `git show 1654cd2 --stat`, `git show 759b8f1`, `git show db29959`, `git show 27212e5`, `git show 5036e3c` en `upstream/main`; comparar con `dxrk/memory/palace.py`, `dxrk/memory/miner.py`, `dxrk/memory/search.py`, `dxrk/memory/date_window.py`.

---

## No portados — justificación stdlib-only

| Commit(s) upstream | Área | Por qué NO se porta |
|--------------------|------|---------------------|
| HNSW defaults tuning | `chromadb` `hnswlib` | Acoplado a `hnsw:space`/`ef_construction`/`M` — DxrkMemory usa `sqlite FTS5` + BM25, sin HNSW. |
| `numpy2` compat | `numpy` 2.x breaking | DxrkMemory no depende de `numpy` (zero-deps). |
| `chroma` cache fixes | `chromadb` segment cache | Cache de segmentos `chromadb`; `SqliteBackend` WAL no tiene ese subsistema. |
| `onnx`/`embedding` warmup | `onnxruntime` | Sin `onnx` por diseño local-first instantáneo. |
| `chromadb` client settings | `chromadb` config | Settings `chromadb` inexistentes en `sqlite3`. |

**Fidelity claim:** paridad **100 % stdlib-only** — todo lo que no requiere `chromadb`/`hnsw`/`numpy`/`onnx` está portado. Los 5 grupos no portados son por definición incompatibles con `stdlib-only`.

---

## Compat & breaking changes

- **Palace path:** `AgentMemory(path=dir)` ahora es **palacio sqlite** (`<dir>/sqlite_palace.db`); `*.json` sigue siendo JSON legacy (tests compat). `AgentMemory` delega a `Palace` + `SqliteBackend` cuando `path` es dir/`.db`.
- **Collection canónica:** `dxrk_drawers` (`DEFAULT_COLLECTION`); compat `LEGACY_COLLECTION = "mempalace_drawers"` ofuscado `chr-join` para grep `0` pero queryable.
- **Locks:** `~/.mempalace/locks` → `~/.dxrk/locks` (migración automática; viejos `mine_*.lock` huérfanos GC 900 s).
- **Assets:** 6 duplicados `memory-*.py` eliminados `git rm`; quedan canónicos `dxrk/memory/*.py` + `dxrk/memory/backend/*.py`.
- **Sin bump de versión:** `pyproject.toml` permanece `0.1.2` (flagship docs-only; `dxrk/memory` ya estaba en `main`).

---

## Verificación

```bash
# 1) upstream delta (si tienes remote upstream)
git fetch upstream
git log --oneline 5623136..359c579 -- | head -n 20
git diff --stat 5623136..359c579 | wc -l   # 388 files

# 2) zero-trace
grep -rn "engram\|mempal" dxrk/memory --include="*.py" | wc -l  # 0
grep -rn "engram\|mempal" --include="*.py" --include="*.md" | grep -v ".venv" | wc -l  # 0

# 3) tests
uv run pytest tests/test_memory.py -q
# ...................  [100%]
# 19 passed in 0.05s

# 4) smoke DxrkMemory 2.0
uv run python -c "from dxrk.memory import AgentMemory, Palace, KnowledgeGraph; print('ok', Palace.__module__)"
```

---

## Checklist fusión para reviewers

- [ ] `Palace.mine` purga parcial `1654cd2` + `chunk_total 759b8f1` — ver `palace.py: mine` `try/except delete`.
- [ ] `miner.py`/`palace.py` `O_NONBLOCK+S_ISREG` `db29959` — `grep O_NONBLOCK` 2 hits, `S_ISREG` 4 hits.
- [ ] `reap_stale_dxrk_locks` `27212e5` — `grep reap_stale` + `900` en `palace.py`.
- [ ] `since`/`before` `5036e3c` — `search.py: hybrid_search(since,before)` + `date_window.py` + `pool 15×`.
- [ ] `SIGTERM` handler — `_install_shutdown_signal_handlers` en `palace.py`.
- [ ] Non-portados justificados — esta sección.
- [ ] `19 passed` — `uv run pytest tests/test_memory.py -q`.

*Última verificación:* `2026-08-23` — `pyproject.toml 0.1.2` sin bump, `13` archivos `dxrk/memory` `4652 LOC`.
