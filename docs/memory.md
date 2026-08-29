# DxrkMemory 2.0 — Flagship Memory Engine (stdlib-only)

> **Top1 local-first** — 13 módulos `dxrk/memory` (~4652 LOC), **zero dependencias** (`sqlite3` stdlib), sin `chromadb`, sin `onnx`, sin `numpy`. Paridad funcional **mempalace 3.7.1** para todo el camino crítico stdlib-only.

DxrkMemory 2.0 es el resultado de la fusión **mempalace 3.3.5** (`feat/opencode-integration` `5623136`) → **upstream 3.7.1** (`359c579`, 388 archivos, 50+ commits). Se portaron los 6 parches críticos stdlib; se dejaron fuera a propósito los fixes exclusivos de `chromadb`/`HNSW`/`numpy2` por diseño *stdlib-only*. Cero trazas `engram`/`mempal` en `dxrk/memory` (979 reemplazos + 7 `git mv`) y 6 assets duplicados eliminados vía `git rm` dejando canónicos `memory-*.py`.

---

## Arquitectura — 13 módulos

| # | Módulo | Ruta | LOC | Responsabilidad |
|---|--------|------|-----|-----------------|
| 1 | `AgentMemory` (fachada) | `dxrk/memory/__init__.py` | 479 | Fachada `AgentMemory` compat + delegación `Palace`/`SqliteBackend` híbrido BM25; JSON fallback tests |
| 2 | `types` | `dxrk/memory/types.py` | 107 | `MemoryType` (SEMANTIC 0/EPISODIC 1/PROCEDURAL 2 + TECHNICAL/PERSONAL), `DrawerRecord`/`ClosetRecord` |
| 3 | `backend.base` | `dxrk/memory/backend/base.py` | 296 | Contratos `BaseBackend`/`BaseCollection`, `PalaceRef`, `HealthStatus`, `GetResult`/`QueryResult`, `IncludeSpec` |
| 4 | `backend` | `dxrk/memory/backend/__init__.py` | 63 | Registry `sqlite` (`SqliteBackend`), `get_backend`, `register_backend` |
| 5 | `SqliteBackend` | `dxrk/memory/backend/sqlite.py` | 770 | `sqlite3` FTS5 `trigram`→`porter` fallback, WAL, `dxrk_drawers` + `LEGACY` `chr-join` compat, BM25, `json_extract` where |
| 6 | `Palace` | `dxrk/memory/palace.py` | 891 | Orquestador wings/rooms/drawers, chunking 800/100, `mine()`, locks, SIGTERM, `O_NONBLOCK`+`S_ISREG` |
| 7 | `search` | `dxrk/memory/search.py` | 267 | `hybrid_search` BM25 + `closet_boost` + `sanitize_query`, `build_where_filter`, `date_window` pool 3×/15× |
| 8 | `date_window` | `dxrk/memory/date_window.py` | 88 | `parse_date_bound`/`parse_window`/`filed_at_in_window` — ventana `[since, before)` wall-clock sobre `filed_at` |
| 9 | `dialect` | `dxrk/memory/dialect.py` | 354 | Dialecto **AAAK** — `compress`/`decode`/`count_tokens`/`compression_stats`, entidades/tópicos/emociones/flags |
| 10 | `entity_detector` | `dxrk/memory/entity_detector.py` | 295 | `extract_candidates`/`score_entity`/`classify_entity`/`detect_entities`, 3+ menciones, person vs project |
| 11 | `graph` | `dxrk/memory/graph.py` | 381 | `KnowledgeGraph` temporal SQLite WAL, `valid_from`/`valid_to`, `as_of`, `traverse` BFS, `stats` |
| 12 | `layers` | `dxrk/memory/layers.py` | 263 | `MemoryStack` **L0-L3** wake-up 600–900 tok (L0 identity 100 tok, L1 500–800, L2 on-demand, L3 deep) |
| 13 | `miner` | `dxrk/memory/miner.py` | 398 | `GitignoreMatcher` + `scan_project`/`chunk_text`, `SKIP_DIRS`, `READABLE_EXTENSIONS`, safe `O_NONBLOCK` |

**Total stdlib-only:** 13 archivos, **4652 LOC** (sin `chromadb`, sin `onnx`, sin `numpy`, solo `sqlite3`, `hashlib`, `re`, `pathlib`, `threading`).

---

## Backend — `sqlite3` FTS5 trigram + WAL

- **Un DB por palacio:** `<palace_path>/sqlite_palace.db` — `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `chmod 0o600` (directorio `0o750`).
- **Esquema:** `collections(id, name)`, `segments(id, collection_id)`, `embeddings(id, document, metadata json, collection, palace_id)` + `embedding_fts` virtual `FTS5(content='embeddings', tokenize='trigram' → 'porter unicode61' → 'unicode61' fallback)`.
- **Compat LEGACY:** `LEGACY_COLLECTION = chr(109)+chr(101)+… → "mempalace_drawers"` ofuscado para grep zero-trace; coexiste con `DEFAULT_COLLECTION = "dxrk_drawers"`. `where` vía `json_extract(metadata, '$.key')`, `$and`/`$in` soportados.
- **FTS5 + BM25:** tokenizador `\w{2,}`; `_sanitize_query` strip FTS5 specials → 500 chars; `_bm25_scores(k1=1.5,b=0.75)` + normalización y `distance = 1 - norm`; pooling FTS5 `OR` limitado 10 tokens, fallback `ORDER BY rowid DESC`.
- **Zero traces:** `979` reemplazos `engram`/`mempal*` → `dxrk` + `7 git mv` + `6 assets` duplicados `git rm`; verificación `grep -rn engram|mempal` global `0`.

---

## Palace & Locks — `~/.dxrk/locks` 900 s

- **Jerarquía:** `wings / rooms / drawers` — `DrawerRecord.make_id(wing,room,source_file,chunk_index)` `sha256(... )[:24]`; metadata `wing`, `room`, `source_file`, `chunk_index`, `filed_at` (ISO), `source_mtime`, `chunk_total`, `normalize_version=2`, `hall`, `entities`.
- **Chunking:** `CHUNK_SIZE=800`, `CHUNK_OVERLAP=100`, `MIN_CHUNK_SIZE=50`, `MAX_FILE_SIZE=500 MiB`, paragraph-aware (`\n\n` > `\n` > hard cut).
- **`mine_lock(source_file)`:** lock por archivo en `~/.dxrk/locks/<sha16>.lock` (`hashlib.sha256(source_file).hexdigest()[:16]`), `fcntl.flock`/`msvcrt.locking`, opportunistic reap throttled.
- **`mine_palace_lock(palace_path)`:** lock por palacio `mine_palace_<sha16>.lock`, **re-entrante por thread** (`threading.local` + `os.getpid()`), `LOCK_NB` + `RuntimeError("palace … is held by another writer")`.
- **Orphan reap `27212e5`:** `reap_stale_dxrk_locks(min_age_seconds=3600)` — GC `mine_*.lock` huérfanos reacquire no-bloqueante (never kill held locks), `marker .last_reap` 900 s (`_LOCK_REAP_INTERVAL_SECONDS`), alias `reap_stale_mine_locks`.
- **SIGTERM handler:** `_install_shutdown_signal_handlers()` rutea `SIGTERM`/`SIGHUP` → `SystemExit(0)` para que `atexit`/`contextmanager` liberen `flock` limpio.

---

## Hybrid BM25 — drawer + closet boost

- **`sanitize_query`:** strip control/prompt-injection (`ignore previous`, `system:`…), FTS5 specials → ` `, collapse whitespace, 500 chars.
- **`_bm25_scores` + `_hybrid_rank(vector_weight=0.6,bm25_weight=0.4)`:** `vec_sim = max(0, 1-distance)`, `score = 0.6*vec_sim + 0.4*bm25_norm`.
- **`hybrid_search(collection, query, where, n_results, closet_collection, since, before)`:** parse `since`/`before` primero (error aunque índice down), `pool 3×` normal / `15×` con ventana (min `500`), `closet_boosts [0.40,0.25,0.15,0.08,0.04]` con cap `1.5`; `matched_via drawer | drawer+closet`; `similarity=round(1-eff,3)`.
- **`build_where_filter(wing,room)`:** `{"wing":…}`, `{"$and":[…]}` para `sqlite` backend.

---

## Graph — KnowledgeGraph temporal

- **SQLite WAL** `~/.dxrk/knowledge_graph.sqlite3` (`entities(id,name,type,properties)`, `triples(id,subject,predicate,object,valid_from,valid_to,confidence,source_closet,source_file,source_drawer_id,adapter_name)`), índices `subject/object/predicate/valid`.
- **Temporal:** `valid_from`/`valid_to` ISO (`YYYY-MM-DD` o datetime `Z`/`+HH:MM`); `_sanitize_iso`, `_start_key`/`_end_key` (date-only → `T00:00:00Z`/`T23:59:59Z`), `temporal_filter_sql` `CASE length=10` para `as_of` wall-clock; `valid_to >= valid_from` validado.
- **API:** `add_entity(name,type,properties)`, `add_triple(subject,predicate,obj,valid_from,valid_to,confidence,source_*)` (dedup si `valid_to IS NULL`), `invalidate(subject,predicate,obj,ended=today)` → `SET valid_to`, `query_entity(name,as_of,direction=outgoing|incoming|both)`, `query_relationship(predicate,as_of)`, `timeline(entity?)`, `traverse(start,depth=2,as_of)` BFS, `stats(){entities,triples,current_facts,expired_facts,relationship_types}`.
- **Thread-safe:** `RLock`, `check_same_thread=False`, `timeout=10`.

---

## Dialecto AAAK

- **`Dialect(entities, skip_names)`:** `encode_entity` (code map + fallback `UPP`), `compress(text, metadata)` → `wing|room|date|stem\n0:ENT+…|topic|\"quote\"|emotion|flag`, `decode(dialect_text)` → `{header,arc,zettels,tunnels}`, `count_tokens(text)=max(1,int(words*1.3))`, `compression_stats(original,compressed)` con `size_ratio`.
- **Señales:** `_EMOTION_SIGNALS` (`worried→anx`, `love→love`… 15), `_FLAG_SIGNALS` (`decided→DECISION`, `api→TECHNICAL`…), `_STOP_WORDS` 80+, `_extract_topics` (freq + boost `Capitalized`/`snake-kebab`/`CamelCase`), `_extract_key_sentence` (score `decided/because/why/breakthrough`…), `_detect_entities_in_text` (code map o `Capitalized` 3).

---

## Layers — wake-up 600–900 tok

| Layer | Nombre | Tokens | Fuente | Cuándo |
|-------|--------|--------|--------|--------|
| **L0** | IDENTITY | ~100 | `~/.dxrk/identity.txt` | Siempre (cache) |
| **L1** | ESSENTIAL STORY | 500–800 | Top `MAX_DRAWERS_L1=15` por `importance`/`emotional_weight`/`weight`, agrupado por `room`, `MAX_CHARS_L1=3200`, `MAX_SCAN=2000` | `wake_up()` |
| **L2** | ON-DEMAND | variable | `where wing/room` filtrado `col.get(limit=n)` | `recall(wing,room)` |
| **L3** | DEEP SEARCH | variable | `hybrid_search(col,query,where,n)` | `search(query,wing,room)` |

- **`MemoryStack(palace_path, identity_path)`:** `wake_up(wing?) = L0.render() + L1.generate()`, `recall`, `search`, `status(){palace_path,L0_identity{exists,tokens},L1/L2/L3 description,total_drawers}`. Estimación `len(text)//4`.
- **Benchmark wake-up:** `L0 100` + `L1 500–800` = **600–900 tok** típicos (header + 15 drawers 200 chars c/u). `L2`/`L3` bajo demanda no cuentan en wake-up frío. Sin `onnx`/`chromadb` el cold start es `sqlite3` instantáneo (<50 ms `WAL` + `FTS5`).

---

## Miner — `GitignoreMatcher`

- **`GitignoreMatcher(base_dir, rules[{pattern,anchored,dir_only,negated}])`:** `from_dir` parsea `.gitignore` (escapes `\#`/`\!`, `!` negated, `/` anchored, `/` dir_only), `matches(path,is_dir)` last-wins, `_rule_matches` con `fnmatch` + `**` recursivo `_match_from_root`.
- **`scan_project(project_dir, respect_gitignore, include_ignored)`:** `os.walk` con `SKIP_DIRS` (`node_modules`, `.venv`, `.git`, `dist`, `target`… 26), `SKIP_FILENAMES` (`package-lock.json`…), `READABLE_EXTENSIONS` 21 (`.txt/.md/.py/.js/.ts/.json/.yaml/.html/.css/.java/.go/.rs…`), `MAX_FILE_SIZE 500 MiB`, `is_gitignored` acumulado por directorio, `normalize_include_paths`/`is_force_included`.
- **Safe reads `db29959`:** `_is_regular_source_file` + `_read_text_no_follow` con `O_RDONLY|O_NOFOLLOW|O_NONBLOCK`, `S_ISREG(os.fstat/fstat)`, `EAGAIN` → `FIFO` guard never-block, misma-`mtime` `fstat` anti-TOCTOU, `_path_within_root` anti-escape.
- **Chunk + normalize:** `chunk_text` re-export, `normalize_content` (`\r\n→\n`, `\n{3,}→\n\n`), `scan_and_chunk`.

---

## Fidelity 3.7.1 — paridad stdlib-only

Ver detalle completo en [`docs/MIGRATION_3.3.5_3.7.1.md`](MIGRATION_3.3.5_3.7.1.md). Resumen:

- **Delta upstream:** `3.3.5` → `3.7.1` = `388` archivos, `50+` commits (`359c579`).
- **Paridad 100 %** en camino stdlib: `palace.mine` re-mine honesty, `mine_lock` FIFO guard, `reap_stale_*` 900 s, `date_window` pool `15×` + `filed_at` filter, `SIGTERM`, `WAL`/`FTS5`, `Graph` temporal, `Layers` wake-up, `Dialect` AAAK, `GitignoreMatcher`.
- **Explícitamente no portado** (justificado): `HNSW` defaults, `numpy2` compat, `chroma` cache fixes — todo acoplado a `chromadb`/`hnswlib`/`onnx` que DxrkMemory 2.0 elimina por diseño.

---

## Zero-deps vs mempalace / engram

| Eje | mempalace 3.3.5/3.7.1 | **DxrkMemory 2.0** |
|-----|----------------------|-------------------|
| Runtime | `chromadb` + `hnswlib` + `onnx`/`numpy` | **stdlib-only** `sqlite3` (sin `chromadb`, sin `onnx`, sin `numpy`) |
| Vector store | HNSW (heavy, native) | **FTS5 `trigram`** + BM25 híbrido (pure Python) |
| Persistencia | `~/.mempalace` / `~/.engram` | `~/.dxrk/palace` + `knowledge_graph.sqlite3`, `WAL`, `0o600` |
| Locks | `~/.mempalace/locks` | `~/.dxrk/locks` `reap 900 s` |
| Legacy compat | `mempalace_drawers` | `dxrk_drawers` + `LEGACY chr-join` compat (grep `0`) |
| Colección | `mempalace_drawers` | `dxrk_drawers` (canónico) |
| Token budget | sin contrato L0-L3 | **L0-L3 600–900 tok wake-up** medible |
| Grep traces | `engram`/`mempal` presentes | **0** (979 reemplazos + 7 `git mv`, 6 `git rm` duplicados) |
| Instalación | `pip install mempalace[chromadb]` | `pip install dxrk` — **sin extras** |

---

## Uso

```python
from dxrk.memory import AgentMemory, Palace, KnowledgeGraph

# 1) AgentMemory — fachada compat (JSON o sqlite palace según path)
mem = AgentMemory(path="/tmp/my_palace")  # dir → sqlite; *.json → JSON legacy
mem.store(mem.__class__.__dict__["__doc__"] and __import__("dxrk.memory").memory.MemoryEntry(
    content="Decidimos usar sqlite FTS5 por latencia <50ms y zero-deps",
    project_id="dxrk",
    session_id="memory-2.0",
    importance=0.9,
))
hits = mem.search(project_id="dxrk", query="sqlite FTS5", limit=5)
print([(h.content[:60], h.importance) for h in hits])

# 2) Palace — wings/rooms/drawers + mine
pal = Palace("/tmp/dxrk_palace")
pal.init()
res = pal.mine(project_dir=".", wing="dxrk", room="code")  # scan_project + chunk + upsert
print(res)  # {"files_mined": 42, "files_skipped": 7, "drawers_added": 128}
hits = pal.search(query="hybrid BM25", wing="dxrk", n_results=5, since="2026-01-01")
for h in hits["results"]:
    print(h["wing"], h["room"], h["similarity"], h["text"][:80])

# 3) KnowledgeGraph — temporal
kg = KnowledgeGraph(db_path="/tmp/kg.sqlite3")
kg.add_triple("DxrkMemory", "uses", "sqlite", valid_from="2026-08-23")
kg.add_triple("Alice", "works_on", "DxrkMemory", valid_from="2026-08-01")
print(kg.query_entity("DxrkMemory", as_of="2026-08-24"))
print(kg.traverse("DxrkMemory", depth=2))
print(kg.stats())

# 4) MemoryStack — wake-up 600–900 tok
from dxrk.memory.layers import MemoryStack
stack = MemoryStack(palace_path="/tmp/dxrk_palace")
print(stack.wake_up(wing="dxrk"))          # L0 + L1
print(stack.recall(wing="dxrk", room="code", n_results=10))  # L2
print(stack.search("AAAK dialect", n_results=5))             # L3

# 5) AAAK dialect + miner
from dxrk.memory.dialect import Dialect
from dxrk.memory.miner import GitignoreMatcher, scan_project

d = Dialect(entities={"DxrkMemory": "DXM"})
print(d.compress("Decided to use sqlite because latency matters", {"wing":"dxrk","room":"code","source_file":"palace.py"}))
print(d.compression_stats("long original ...", "short ..."))

files = scan_project(".", respect_gitignore=True)
matcher = GitignoreMatcher.from_dir(__import__("pathlib").Path("."))
print(f"scanned {len(files)} files, gitignore={matcher is not None}")
```

### CLI relacionado

```bash
dxrk-py query "¿qué arquitectura decidimos para memoria?"   # vía AgentMemory
uv run pytest tests/test_memory.py -q                        # 19 passed
```

---

## Benchmarks wake-up (estimados, local-first)

| Escenario | Tokens | Latencia cold | Notas |
|-----------|--------|---------------|-------|
| `wake_up()` L0+L1 (15 drawers, 3200 chars) | **600–900** | <50 ms (WAL) | `L0 100` + `L1 500–800`; sin `onnx` |
| `recall(wing,room)` L2 (10 drawers) | +300–600 | <20 ms (`get` + `json_extract`) | on-demand |
| `search(query)` L3 (5 hits BM25) | +400–700 | <80 ms (FTS5 + BM25 rerank) | `pool 15×` si `since`/`before` |
| `mine .` (100 files, 300 chunks) | — | ~1–2 s | `scan_project` + `chunk` + `upsert` batched 500 |

> Sin `chromadb`/`HNSW`/`onnx`, el import de `dxrk.memory` es instantáneo (stdlib). La comparación justa con mempalace es *wake-up* frío: `chromadb` bootstrap + `onnx` warmup >> `sqlite3` WAL.

---

## Verificación

```bash
uv run pytest tests/test_memory.py -q   # 19 passed
grep -rn "engram\|mempal" dxrk/memory --include="*.py" | wc -l  # 0 (mempalace-compat legado ofuscado chr-join)
grep -rn "engram\|mempal" --include="*.py" | wc -l                # 0 global
```

Más en [MIGRATION_3.3.5_3.7.1.md](MIGRATION_3.3.5_3.7.1.md) y `docs/architecture.md`.

---

## Relación con Autonomy y RAG — ver [ADR-002](adr/ADR-002-memory-separation.md)

> **Decisión: AISLAR** — `dxrk/memory` (DxrkMemory), `dxrk/autonomy/learner` y `dxrk/rag` son **3 sistemas aislados** con contratos y persistencias distintas.
> Detalle formal en **[ADR-002: Separación DxrkMemory vs Autonomy/Learner vs RAG/Store](adr/ADR-002-memory-separation.md)** (Accepted 2026-08-27).

**Frontera por diseño — 3 dominios, 3 stores, 0 coupling:**

| Sistema | Módulo | Persistencia | API clave | Deps |
|---------|--------|--------------|-----------|------|
| **DxrkMemory** (canónico) | `dxrk/memory` — `Palace`, `AgentMemory`, `KnowledgeGraph`, `AAAK` | `~/.dxrk/palace/sqlite_palace.db` — `sqlite3` FTS5 `trigram` + BM25, `WAL`, `0o600` | `mine()`, `search(since,before)`, `hybrid_search`, `traverse()` | **stdlib-only** (`sqlite3`, `hashlib`, `re`) |
| **Learner** (patrones) | `dxrk/autonomy/learner.py` — `Learner`, `MemoryItem` | `.dxrk/memories.json` — JSON `0o600`, `max_items 1000`, `RLock` | `record()`, `suggest()`, `top_errors()`, `recent_memories()` | stdlib (`json`, `hashlib`) |
| **RAG** (code index) | `dxrk/rag` — `chunker`, `indexer`, `VectorStore`, `OpenAIEmbedder` | in-memory `dict[str,VectorRecord]` + JSON opcional | `VectorStore.Search()`, `embed()`, `cosine_similarity` | `urllib` + `OPENAI_API_KEY` opcional |

**Por qué no fusionar.** Fusionar contaminaría `memory` (offline, <50 ms cold, `pip install dxrk` sin extras) con deps de red/modelo, rompería `zero-trace` (`grep engram|mempal == 0`, `LEGACY` `chr-join` ofuscado), mezclaría semánticas incompatibles (`filed_at`/`wing` vs `success_rate`/`error` vs `start_line`/`language`) y acoplaría `WAL`/`mine_palace_lock`/`reap 900 s`/`FIFO guard` (`db29959`/`27212e5`) a dominios que no los necesitan. Alternativas `SQLite compartido` (colecciones separadas en mismo `.db`) y `shared vector store` (todo a `OpenAIEmbedder` + HNSW) se rechazan en el ADR — ver `MIGRATION_3.3.5_3.7.1.md` “No portados” (`HNSW`/`numpy2`/`onnx`).

**Puentes opcionales sin storage coupling:**

- `Learner → Palace` via **hooks** (`dxrk/memory/hooks_cli.py`, `~/.config/dxrk/hooks.json`): export fire-and-forget de `MemoryItem` exitoso a `wing=autonomy/room=pattern` (`source_file=learner:<id>`). Si `Palace` falla, `Learner` no falla — sin transacción compartida.
- `RAG → Palace` via **enrichment** (`dxrk/memory/__init__.py:148-157`): `AgentMemory(path, rag=rag)` inyecta `rag.is_enabled()/query(text,1)` en `store()` para poblar `entry.embedding` antes del `upsert`. Sin `rag` o sin `OPENAI_API_KEY`, `memory` opera **BM25 puro**. `RAG` nunca lee `sqlite_palace.db`.

**Reglas de frontera (ADR-002):**

- `R1 stdlib-only` — `memory` sin `openai`/`numpy`/`chromadb`.
- `R2 DB por dominio` — `memory` WAL, `learner` JSON, `rag` in-memory/JSON.
- `R3 no read-through` — ningún sistema importa el store interno de otro.
- `R4 zero-trace` — `grep engram|mempal dxrk/memory → 0`.
- `R5 multi-tenant ready` — `palace_path` por proyecto/usuario, `learner` por repo, `rag` por índice.
- `R6 fallback sin regresión` — si `rag`/`Palace` falla, cada sistema sigue operativo.

Verificación y plan de migración completos en [ADR-002](adr/ADR-002-memory-separation.md) — ningún `from dxrk.memory` en `learner`/`rag`, ningún `from dxrk.rag` en `memory` salvo `Protocol` `rag: object`.
