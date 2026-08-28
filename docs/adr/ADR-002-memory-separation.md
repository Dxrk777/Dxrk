# ADR-002: Separación DxrkMemory vs Autonomy/Learner vs RAG/Store

| Campo | Valor |
|-------|-------|
| **Título** | Separación DxrkMemory vs autonomy/learner vs rag/store — aislamiento de 3 sistemas |
| **Estado** | **Accepted** |
| **Fecha** | 2026-08-27 |
| **Autores** | Dxrk Core |
| **Relacionado** | `docs/memory.md`, `docs/MIGRATION_3.3.5_3.7.1.md`, `dxrk/memory`, `dxrk/autonomy/learner.py`, `dxrk/rag` |
| **Supersede** | N/A (primera decisión formal de frontera memoria) |

---

## Contexto

Dxrk acumula tres subsistemas con “memoria” en el nombre pero con **propósitos, contratos y dependencias radicalmente distintos**:

1. **`dxrk/memory` — DxrkMemory 2.0** (`AgentMemory`, `Palace`, `KnowledgeGraph`, `Dialect` AAAK)
   - **13 módulos, ~4652 LOC, stdlib-only** (`sqlite3` FTS5 `trigram → porter → unicode61`, WAL, `hybrid_search` BM25).
   - Modelo **palace/wings/rooms/drawers** verbatim (`DrawerRecord.make_id` `sha256[:24]`), `chunking 800/100`, `KnowledgeGraph` temporal (`valid_from`/`valid_to`), `MemoryStack` L0-L3 wake-up **600–900 tok**.
   - Persistencia canónica del agente: `~/.dxrk/palace/sqlite_palace.db` (`0o600`), locks `~/.dxrk/locks` con `reap 900 s`, `SIGTERM → SystemExit`, `O_NONBLOCK+S_ISREG` anti-FIFO.
   - **Zero external deps**: sin `chromadb`, sin `hnswlib`, sin `onnx`, sin `numpy`. Import instantáneo (<50 ms cold). Paridad `mempalace 3.7.1` stdlib-only verificada (`979` reemplazos `engram|mempal → dxrk`, grep global `0`).

2. **`dxrk/autonomy/learner.py` — Learner** (`Learner`, `MemoryItem`, `Pattern`, `ErrorEntry`)
   - Memoria **de patrones de autonomía**, no verbatim. Registra `input/output/success/error/fixed_by/tags/tokens/latency_ms` en `list[MemoryItem]` con `max_items` (por defecto `1000`, evicción FIFO).
   - Persistencia: **JSON** `~/.dxrk/memories.json` / `.dxrk/memories.json` (`0o600`, `0o750` dir), `threading.RLock`, `hashlib.sha256(input+output+now)[:16]` para `id`.
   - API: `record()`, `suggest(input)` (top-5 por `success_rate`), `recent_memories(n)`, `top_errors(n)`, `_learn_pattern` (trigger = primeras 10 palabras).
   - **Sin FTS, sin vectores, sin embeddings**. Diseñado para `autonomy/evolution` y `permissions` — feedback loop de ejecución.

3. **`dxrk/rag` — Code RAG** (`chunker.py`, `indexer.py`, `store.py` `VectorStore`, `embedder.py` `OpenAIEmbedder`)
   - Indexado **de codebase** (no memoria de agente). `Chunk` (`text`, `file_path`, `start_line`, `end_line`, `language`), `VectorStore` in-memory + JSON opcional (`cosine_similarity` puro `math`), `OpenAIEmbedder` (`text-embedding-3-small`, `1536d`, `MAX_BATCH 256`, `urllib.request` stdlib).
   - Persistencia: `VectorRecord(id, chunk, embedding: list[float])` en dict + `SearchResult(score)`. **Requiere `OPENAI_API_KEY`** para `embed()`; sin clave, `VectorStore` opera vacío o con embeddings pre-cargados.
   - Propósito: `RAG.query()` alimenta contexto al agente durante `sdd-*`, `plan`, `commit`.

### Problema

Se evaluó **fusionar** los tres en un único “memory store” (un `sqlite` o un `VectorStore` compartido, `DxrkMemory` como fachada universal). La fusión parecía reducir duplicación (`store` vs `palace`, `MemoryItem` vs `MemoryEntry`) y habilitar búsqueda unificada.

Pero la fusión introduce acoplamientos incompatibles:

- **Dependencias**: `dxrk/memory` es **stdlib-only** por diseño (instalación `pip install dxrk` sin extras, offline, instantáneo). `dxrk/rag` depende opcionalmente de **OpenAI API + vectores densos** (`urllib`, network, API key). Fusionar contaminaría `memory` con deps de red/modelo, rompiendo el contrato `zero-deps` y el cold-start <50 ms.
- **Zero-trace**: `dxrk/memory` garantiza `grep -rn engram|mempal → 0` (compat `LEGACY_COLLECTION` ofuscada `chr-join`). Mezclar tablas `learner.memories` o `rag.vectors` en `sqlite_palace.db` re-expondría superficies de `where`/`json_extract` a semánticas incompatibles y complicaría el `LEGACY` `mempalace_drawers` → `dxrk_drawers`.
- **Semántica**: verbatim (`drawers` con `filed_at`, `wing/room`, `BM25`) ≠ patrones (`MemoryItem` con `success_rate`, `error`, `tokens`) ≠ chunks de código (`Chunk` con `start_line/end_line`). Unificar tipos fuerza `Any`/`Optional` masivos y viola mypy estricto.
- **Multi-tenant futuro**: `Palace` está diseñado para **un DB por palacio** (`palace_path/sqlite_palace.db`), aislable por proyecto/usuario. `Learner` y `RAG` tienen ciclos de vida distintos (learner por repo local `.dxrk/`, RAG por índice efímero). Compartir DB acoplaría `vacuum`, `WAL`, `chmod` y `mine_palace_lock` a dominios que no lo necesitan.
- **Operacional**: `Palace.mine` (re-mine honesty `1654cd2`, `chunk_total` `759b8f1`, `FIFO guard` `db29959`) y `reap_stale_dxrk_locks` (`27212e5`) son críticos para memoria verbatim; no aplican a `Learner` (JSON append) ni a `VectorStore` (in-memory). Unificar complica `try/except` de purga parcial y `DRAWER_UPSERT_BATCH_SIZE 500`.

---

## Decisión

**AISLAR — tres sistemas independientes, contratos explícitos, puentes opcionales sin acoplamiento de almacenamiento.**

### 1) `dxrk/memory` — canónico para memoria de agente (verbatim)

- **Source of truth** para todo lo que el agente debe recordar verbatim: decisiones, contexto de proyecto, conversaciones, `AAAK`, grafo temporal.
- Stack: `Palace` + `SqliteBackend` (FTS5 `trigram` + BM25 híbrido), `KnowledgeGraph` (`~/.dxrk/knowledge_graph.sqlite3`), `Dialect`, `MemoryStack` L0-L3.
- Contrato: `stdlib-only`, `sqlite_palace.db` por palacio, `WAL`, `0o600`, `hybrid_search(since, before)` con `pool 3×/15×`, `mine()` con locks `~/.dxrk/locks`.
- **No importa learner ni rag**. Expone `AgentMemory(path=dir)` como fachada que delega a `Palace`; `*.json` legacy solo para tests.

### 2) `dxrk/autonomy/learner` — patrones de autonomía (aislado)

- **Scope**: solo `autonomy` (`evolution`, `verifier`, `permissions`, `swarm`). `MemoryItem(max_items=1000)` en `.dxrk/memories.json`.
- **Aislado**: no lee/escribe `sqlite_palace.db`. No depende de `Palace` ni de `VectorStore`.
- **Puente opcional (export, no storage coupling)**: via **hooks** (`dxrk/memory/hooks_cli.py`, `~/.config/dxrk/hooks.json`) el learner puede **exportar** un `MemoryItem` exitoso a `Palace` como `DrawerRecord` (`wing=autonomy`, `room=pattern`, `source_file=learner:<id>`), pero **sin transacción compartida**. Es fire-and-forget: si `Palace` está down, el learner no falla.
- Futura multi-tenancy: cada repo tiene su `.dxrk/memories.json`; cada usuario su `~/.dxrk/` — sin colisión con `palace_path`.

### 3) `dxrk/rag` — indexado de codebase (aislado)

- **Scope**: solo RAG de código (`chunker → indexer → VectorStore → embedder`). `VectorStore(dimensions, persist_path="")` in-memory + JSON opcional.
- **Aislado**: no persiste en `sqlite_palace.db`. No comparte tablas con `DxrkMemory`.
- **Puente opcional (enrichment, no storage coupling)**: `AgentMemory.store(entry)` acepta `rag: object` inyectado (`is_enabled()`, `query(text, k)`). Si `rag` está habilitado, `store()` **enriquece** `entry.embedding` con `rag.query(entry.content, 1)` **antes** del `upsert` a `Palace`. Es **enrichment de embedding**, no coupling de storage: `Palace` sigue siendo el store; `RAG` solo provee el vector si hay `OPENAI_API_KEY`. Sin `rag` o sin clave, `store()` funciona idéntico (BM25 puro).
- `RAG` no lee `Palace`; `Palace` no lee `VectorStore`. Búsqueda unificada se hace **a nivel aplicación** (orquestador llama a ambos y hace `hybrid_rank` si quiere), no a nivel DB.

### Reglas de frontera

| Regla | Descripción |
|-------|-------------|
| **R1: stdlib-only** | `dxrk/memory` no añade deps (`openai`, `numpy`, `chromadb`). `rag/embedder` y `learner` pueden tener deps de red pero no las propagan a `memory`. |
| **R2: DB por dominio** | `memory` → `sqlite_palace.db` (WAL). `learner` → `.dxrk/memories.json`. `rag` → `VectorStore` in-memory/JSON (`persist_path` opcional). Nunca compartir archivo DB. |
| **R3: No read-through** | Ningún sistema hace `import` del store interno de otro para leer. Solo puentes explícitos (`hooks` export, `rag` enrichment) con contratos `Protocol`/`is_enabled`. |
| **R4: Zero-trace** | `memory` mantiene `grep engram|mempal == 0` (salvo `chr-join` LEGACY). `learner`/`rag` no reintroducen esos strings en `memory`. |
| **R5: Multi-tenant ready** | `palace_path` por proyecto/usuario. `learner` por repo. `rag` por índice. Aislamiento permite `chmod 0o600` y `mine_palace_lock` sin interferencia. |
| **R6: Fallback sin regresión** | Si `rag` no está configurado o `Palace` falla, `AgentMemory._use_sqlite` cae a JSON legacy; `learner` sigue en JSON; `rag` sigue vacío. Ningún fallo en puente rompe el otro sistema. |

---

## Alternativas consideradas

### A) Fusión completa — un único store (rechazada)

Un `SqliteBackend` único con tablas `drawers`, `memories`, `vectors` o un `VectorStore` único con `metadata.kind in {drawer, pattern, chunk}`. Búsqueda unificada `hybrid_search` sobre todo.

- **Rechazo**: contamina `stdlib-only` con `openai`/`numpy`; mezcla semánticas (`filed_at` vs `success_rate` vs `start_line`); acopla `WAL`/`FTS5`/`HNSW` a dominios que no lo necesitan; rompe `zero-trace` y `migrate` (`MIGRATION_3.3.5_3.7.1.md`); riesgo de `vacuum`/lock contention; testing explosivo (mock de OpenAI para tests de memoria verbatim).

### B) SQLite compartido, colecciones separadas (rechazada)

Un `sqlite_palace.db` con `collection_name in {dxrk_drawers, learner_memories, rag_chunks}` via `Palace.get_collection()`.

- **Rechazo**: aunque separa por colección, sigue compartiendo **archivo, WAL, `mine_palace_lock`, `chmod`, `health()`** y el `backend` registry. `Learner` (JSON `max_items 1000`) no necesita FTS5 ni `reap_stale_dxrk_locks`; `RAG` (cosine `VectorStore`) no necesita `FTS5 trigram` ni `BM25`. El coste es acoplamiento operacional sin beneficio: vaciar `learner` implica `DELETE FROM embeddings WHERE collection='learner'` con `json_extract` — frágil vs `os.truncate` JSON.

### C) Shared vector store — todo a embeddings (rechazada)

`Palace` migrado a `VectorStore` + `OpenAIEmbedder` (HNSW/Chroma-lite), `Learner` y `RAG` como namespaces del mismo `VectorStore`.

- **Rechazo**: requiere `OPENAI_API_KEY` para que `memory` funcione (offline roto); `chroma`/`hnsw` pesados vs `sqlite3` stdlib; cold-start >>50 ms; `onnx` warmup; `numpy` 2.x compat (ver `MIGRATION_3.3.5_3.7.1.md` “No portados”); `zero-trace` perdido. Contradice flagship **stdlib-only**.

### D) Aislamiento con puentes opcionales — **elegida**

Ver **Decisión**. Mantiene `stdlib-only`, `zero-trace`, `WAL`/`FTS5` intactos; permite `rag` enrichment y `learner` export sin acoplamiento de storage; multi-tenant trivial.

---

## Consecuencias

### Positivas

- **Stdlib-only preservado**: `pip install dxrk` sin extras, offline, <50 ms cold. `memory` testeable sin mocks de red (`tests/test_memory.py 19 passed`).
- **Zero-trace**: `grep -rn engram|mempal dxrk/memory → 0` se mantiene; `LEGACY_COLLECTION` ofuscado `chr-join` no se expande a otros dominios.
- **Evolución independiente**: `Palace` puede iterar (`chunk_total`, `reap`, `FIFO guard`) sin tocar `Learner`/`RAG`; `RAG` puede cambiar modelo (`text-embedding-3-small → 3-large`) sin migrar `sqlite_palace.db`.
- **Multi-tenant**: aislar `palace_path` por proyecto/usuario, `learner` por repo `.dxrk/`, `rag` por índice — sin `mine_palace_lock` cruzado ni `WAL` compartido.
- **Testing simple**: `memory` tests stdlib; `learner` tests JSON; `rag` tests con `VectorStore` mock sin tocar `Palace`.
- **Seguridad**: `chmod 0o600` y `0o750` por archivo; `O_NONBLOCK`/`S_ISREG` solo donde aplica; superficie de ataque mínima.

### Negativas / Costes

- **Duplicación aparente**: `MemoryEntry` vs `MemoryItem` vs `Chunk` — tres dataclasses similares. Mitigado: semánticas distintas justifican tipos distintos; mypy estricto lo exige.
- **Búsqueda no unificada por defecto**: orquestador debe llamar `Palace.search` + `VectorStore.Search` + `Learner.suggest` y rankear. Mitigado: puentes `rag` enrichment y `hooks` export cubren 80% sin query federada.
- **Docs adicionales**: hay que documentar frontera (este ADR + `docs/memory.md` “Relación con Autonomy y RAG”). Coste menor.

### Neutras

- `AgentMemory(rag=...)` enrichment sigue disponible pero **opcional** y sin coupling de storage. No requiere `RAG` para que `memory` funcione.

---

## Plan de migración

No hay migración de datos — los tres sistemas ya están aislados en `main`. Este ADR **formaliza** el estado actual como decisión.

| Paso | Acción | Estado |
|------|--------|--------|
| 1 | Verificar aislamiento: `grep -rn "from dxrk.rag" dxrk/memory` → 0 (salvo `__init__.py: rag: object` Protocol), `grep -rn "from dxrk.autonomy" dxrk/memory` → 0 | ✅ Hecho |
| 2 | Verificar `rag` no importa `palace`: `grep -rn "palace\|SqliteBackend" dxrk/rag` → 0 | ✅ Hecho |
| 3 | Verificar `learner` no importa `memory`/`rag`: `grep -rn "from dxrk.memory\|from dxrk.rag" dxrk/autonomy/learner.py` → 0 | ✅ Hecho |
| 4 | Documentar puente `AgentMemory.store` enrichment: `dxrk/memory/__init__.py:148-157` (`self._rag.is_enabled()/query() → entry.embedding`) | ✅ Hecho |
| 5 | Documentar puente `learner → palace` via hooks: `dxrk/memory/hooks_cli.py` + `~/.config/dxrk/hooks.json` (export fire-and-forget) | ✅ Existente, referenciado aquí |
| 6 | Añadir sección `docs/memory.md: Relación con Autonomy y RAG` (~30 líneas) con referencia a este ADR | ⏳ Este ADR |
| 7 | Añadir entrada `mkdocs.yml` `nav: ADR-002: adr/ADR-002-memory-separation.md` | ⏳ Este ADR |
| 8 | CI: `uv run python -m pytest -q tests/test_memory.py` (19 passed) + `grep zero-trace` | ✅ Sin regresión |
| 9 | Futuro multi-tenant: `Palace(palace_path=per_user/per_project)` ya soportado; `Learner(path=.dxrk/memories.json)` por repo; `VectorStore(persist_path=per_index)` por índice. Sin cambios. | N/A |

### Rollback

Si se decide fusionar en el futuro, este ADR se marca `Superseded` por `ADR-00X` y se diseña migración explícita (dump `memories.json` → `dxrk_drawers` con `wing=autonomy`, re-index `VectorStore` → `sqlite_fts`). No se hace sin ADR nuevo.

---

## Referencias

- `dxrk/memory/__init__.py` — `AgentMemory` fachada + `rag` enrichment (`store:148-157`, `search:272-278`)
- `dxrk/memory/palace.py` — `Palace.mine`, `mine_lock`, `mine_palace_lock`, `reap_stale_dxrk_locks`, `chunk_text`, `Fifo guard`
- `dxrk/memory/backend/sqlite.py` — `SqliteBackend`, `FTS5 trigram`, `WAL`, `BM25`
- `dxrk/autonomy/learner.py` — `Learner`, `MemoryItem(max_items)`, `suggest`, `top_errors`, `.dxrk/memories.json`
- `dxrk/rag/store.py` — `VectorStore`, `VectorRecord`, `cosine_similarity`
- `dxrk/rag/embedder.py` — `OpenAIEmbedder`, `DEFAULT_EMBEDDING_MODEL text-embedding-3-small`
- `dxrk/rag/chunker.py`, `dxrk/rag/indexer.py` — chunking/indexado de codebase
- `dxrk/memory/hooks_cli.py` — hooks `export` learner → palace (fire-and-forget)
- `docs/memory.md` — DxrkMemory 2.0 flagship stdlib-only (13 módulos, 4652 LOC)
- `docs/MIGRATION_3.3.5_3.7.1.md` — paridad mempalace 3.7.1, no portados `HNSW`/`numpy2`/`onnx`
- `mkdocs.yml` — `nav` incluye `ADR-002`

> **Verificación**: `uv run python -m pytest -q tests/test_memory.py` → `19 passed`; `grep -rn "engram\|mempal" dxrk/memory --include="*.py" | wc -l` → `0`; `grep -rn "from dxrk.memory" dxrk/autonomy/learner.py dxrk/rag` → `0`.

