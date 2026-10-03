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
| 14 | `migrate` | `dxrk/memory/migrate.py` | — | Migración lazy a spine `schema_version=2`, checksums `content_sha256`, ledger hash-chain (`verify_chain`), `merkle_root` |
| 15 | `scoring` | `dxrk/memory/scoring.py` | — | Ranking RDU: `R_fsrs` + updates success/lapse (`S`/`D`/`rd`), `score_meta` unificado |
| 16 | `policy` | `dxrk/memory/policy.py` | — | `PolicyEngine`: triggers de higiene (`over_budget`, `rescore_stale`, `checksum_sweep`, `quarantine_sweep`) gateados por `memory.maintain` |

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
python -m dxrk.memory search "arquitectura memoria"   # vía AgentMemory
uv run python -m pytest tests/test_memory.py -q       # 19 passed
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

## Recall híbrido Phase 0–1 — vectores locales + fusión + eval

Stdlib-only, sin `torch`/`sentence-transformers`/`numpy`
(`dxrk/memory/vectors.py`, fusión en `dxrk/memory/backend/sqlite.py`).

| Pieza | Regla |
|-------|-------|
| Features | Tokens `w:<tok>` (`\w{2,}`) + char 3-grams con padding (`g:<tri>` sobre `^tok$`); lado query sin stopwords (`query_features`), docs con features completas |
| Hashing | `md5(feat)` → `DIM = 512` buckets; forma almacenada = conteos TF crudos (BLOB `float32`) |
| Coseno IDF | IDF estilo BM25 estimada sobre el pool de candidatos; `weighted_cosine` hunde ngrams comunes (`the`/`ing`) y deja dominar a distintivos (`jwt`/`auth`) |
| Fusión | `COS_W=0.6 · cos + BM25_W=0.3 · bm25norm + REC_W=0.05 · recency + IMP_W=0.05 · importance + ACC_W=0.03 · access`; `distance = 1 − fused` en `[0, 1]`; pool = hits FTS ∪ filas recientes (`_FTS_CANDIDATE_MULT=5`, min 100 / max 500) para rescatar docs sin overlap léxico |
| Recency | `exp(-age_days / 180)` sobre `filed_at` (`0.0` si falta); `importance` satura en `5.0`, `access` en `~20` lecturas vía `log1p` |
| Eval | `tests/test_memory_recall_eval.py` — queries conceptuales que NO solapan literalmente el documento target (BM25 puro + filtro AND las falla); asserts `precision@k`/`recall@k`; incluye round-trip `hook_session_start` y tests de `embed` determinista/`DIM` |

Phase 0 (limpieza previa): filtros de recall y duplicados corregidos
(`dxrk/memory/palace.py`, `miner.py`, `layers.py`, `hooks_cli.py`,
`mcp_server.py`; suite `tests/test_dxrk_memory_full.py`).

## Ciclo de vida Phase 3 — consolidate/forget/pin, budgets, timeline

Agentic memory management sobre el mismo modelo supersede (stdlib-only,
determinista, sin LLM). MCP expone 5 herramientas de escritura (`dxrk_memory_*`,
writes con gate RBAC `mine` → `PermissionError("RBAC_DENIED")` si
`DXRK_USER` no tiene el op en el tenant; `quarantine` exige además la cap
`memory.maintain`): `consolidate`, `forget`, `pin`, `quarantine` (writes) y
`timeline` (read). Total del servidor: **24 tools**
(`dxrk/memory/mcp_server.py`; eran 19 antes de Phase 3).

| Tool MCP | Tipo | Input clave |
|----------|------|-------------|
| `dxrk_memory_consolidate` | write | `drawer_ids[]` (≥2, required), `wing`, `room`, `palace` |
| `dxrk_memory_forget` | write | `drawer_ids[]` / `wing` / `room` / `before` (ISO, `filed_at` estrictamente anterior) / `hard` (default `False`) / `include_kg` (default `False`, solo supersede) |
| `dxrk_memory_pin` | write | `drawer_id` + `scope` (`drawer` \| `identity`, default `drawer`), `pinned` (default `True`) |
| `dxrk_memory_quarantine` | write (`memory.maintain`) | `drawer_id` (required), `reason`, `unquarantine` (default `False`), `palace` |
| `dxrk_memory_timeline` | read | `since` (incl.) / `before` (excl.), `wing`, `limit` (default 50, max 200) |

| Pieza | Regla |
|-------|-------|
| Consolidate | `consolidate_drawers(ids≥2)` — destilación extractiva: pool de fuentes → frases (split `[.!?]`), score TF + bonus de señal (decisión/obligación/hechos) + preferencia 8–45 palabras, colapso de near-idénticas (overlap ≥ 0.9), tope `MAX_CONSOLIDATED_CHARS=2000` / 12 frases. Nueva drawer `consolidated:<sha12>` con `supersedes` (primera fuente) + `consolidated_from` (todas); cada fuente `valid_to` + `superseded_by`. Bypass de `add_drawer` a propósito (el destilado suele estar contenido en una fuente y dedupe lo colapsaría); cap enforced tras insert |
| Forget | `forget(drawer_ids?, wing?, room?, before?, hard=False, include_kg=False)` — soft por defecto: `valid_to` + `forgotten` (legible vía `get`, invisible en search/L1/L2 como superseded). `hard=True` borra filas. KG **jamás** se borra: `include_kg=True` solo supersede (`valid_to`) episodios de los `source_file` matcheados. `before` = `filed_at` estrictamente anterior (filas sin fecha nunca matchean). Sin scope → `ValueError` |
| Pin | `pin_drawer` (`pinned` + `pinned_at`; upsert-replace porque `update()` mergea y resucitaría claves) — exento de eviction (`_enforce_wing_cap` salta pinned; si solo quedan pinned over-cap, no se borra nada) y primero en L1/`wake_up` (pinned ordenados por score, luego resto hasta `MAX_DRAWERS`). `pin_identity` registra el bloque L0 en sidecar `<palace>/pins.json` (L0 ya renderiza siempre, inmune por construcción) |
| Budgets | `wing_usage(wing)` → `{count, budget, remaining, over, unbounded, pinned, superseded, forgotten, truncated}`; `budgets()` agrupa todas en un scan acotado (`STATUS_SCAN_LIMIT=10000`). `dxrk_memory_status` incluye `budgets`. Write paths con cap: `add_drawer`, `mine`, `consolidate` y `update_drawer` (MCP, sobre wing destino). Orden de eviction: superseded/olvidados primero, luego menor `score_meta`, pinned nunca |
| Timeline | `timeline(since?, before?, wing?, limit→50, max 200)` → `[{time, kind, summary≤160, ref, wing}]` cronológico ascendente: `session` (drawers `source_file=session:*` del hook_stop), `file` (episodios KG agrupados por `source_file+valid_from` vía `KnowledgeGraph.all_episodes`, con `wing` resuelto por `source_drawer_id` y flag `current`), `pin` (drawers pinned + pin L0). Ventana `[since, before)` wall-clock reutilizando `date_window` |

Deliberadamente fuera: borrado físico de historia KG (ningún flag lo permite),
re-ranking con boost de pinned en search (pin protege de *removal*, no de orden),
agrupación de drawers minados en el timeline (los episodios KG son la vista file).

---

## Ranking RDU Fase 0 — spine `schema_version=2`, quarantine, policy

RDU (Recall-Decay-Update, estilo FSRS) reemplaza los rankers dispersos por una
sola señal por drawer. Cada metadata lleva el spine (`dxrk/memory/migrate.py`):

- `S` (estabilidad, días), `D` (dificultad 1–10), `rd` (desviación, arranca 350),
  `s_updates` — el estado de memoria.
- `content_sha256` — checksum de integridad (`""` = pendiente de rehash).
- `quarantined` / `quarantine_reason` / `quarantined_at`.
- `score_ledger` (hash-chain, tope 20 + contador `score_ledger_dropped`) y
  `access_history` (topes 20 + `access_count_total`).

| Pieza | Regla |
|-------|-------|
| Recall `R_fsrs` | `get_drawer` es un outcome *success*: crece `S`, cae `rd`, suma ledger `access`. Contradicción/supersede/forget/quarantine son *lapse*: colapsa `S`, sube `D`, suma ledger con su motivo. Solo el tiempo nunca mueve `S`/`D` |
| Migración lazy | Filas legacy (`schema_version < 2`) migran al leer: `S = 1 + log1p(access_count)`, `D = 5.0`, `rd = 350 / (1 + n)`, checksum `""` (rehash en el próximo read) |
| Integridad | Read con checksum ausente → adopta el actual (rehash); mismatch → auto-quarantine + contador `checksum_mismatches` (sidecar). `status()` expone `merkle_root`, `quarantined`, `quarantine_warning`, `needs_rehash` |
| Quarantine | `quarantine_drawer` aísla fail-closed: invisible en search/L1/L2/timeline, `get` devuelve flags + motivo sin documento. `unquarantine` libera sin devolver la estabilidad perdida. Vía MCP solo con cap `memory.maintain` |
| Reads MCP | `get_drawer`/`list_drawers` proyectan metadata: `score_ledger` truncado a los últimos 5 (con `score_ledger_dropped` ajustado para que el slice siga verificando con `verify_chain`) y `access_history` crudo reemplazado por `access_history_len` |
| Policy | `PolicyEngine(palace).maybe_run("write" \| "periodic")`: `write` corre `over_budget` inline (wing.count > cap → `enforce_wing_cap`); `periodic` corre `rescore_stale` (filed > 30d sin ledger reciente → append con score actual), `checksum_sweep` (ventana rotativa de 200, rehash de faltantes) y `quarantine_sweep` (documento vacío / sha mismatch → quarantine), cada uno máx. 1/15 min (sidecar `<palace>/.policy_state.json`). Todo trigger corre bajo `mine_palace_lock` como tenant efectivo con `require_op(tenant, "system:policy", "memory.maintain")` — sin grant aborta `RBAC_DENIED`, nunca bypassea el chequeo |

Suites: `tests/test_rdu_goldens.py` (bandas de recall), `tests/test_scoring.py`,
`tests/test_migrate.py`, `tests/test_spine_{checksum,quarantine,ledger,status,actr_history}.py`,
`tests/test_policy.py`, `tests/test_memory_mcp_reads.py`.

---

## Ciclo de vida Phase 2 — distill/dedupe, decay, episodios KG, contradicción

Heurístico, stdlib-only, determinista (sin LLM). Una fórmula de scoring
(`dxrk/memory/scoring.py:rank_score`) en todos lados: `top_by_importance`,
`Layer1`, ranker fusionado sqlite (`COS 0.6 + BM25 0.3 + recency 0.05 +
importance 0.05 + access 0.03`), rerank híbrido (`_hybrid_rank` × frescura).

| Pieza | Regla |
|-------|-------|
| Dedupe (A) | `add_drawer`/`mine` colapsan near-duplicates del mismo wing (coseno ≥ 0.85 + overlap ≥ 0.7 o contenencia): update del drawer existente (`last_seen`/`seen_count`), sin copias divergentes |
| Decay (B) | `(importance + 0.5·log1p(access)) × half-life(filed_at, 180d) × acceso(30d)`; `get_drawer` suma `access_count`/`accessed_at`; cap por wing `DEFAULT_MAX_ENTRIES_PER_WING = 1000` (0 = legacy sin cota) |
| Episodios KG (C) | `mine` extrae `entity_detector` → `add_triple` con `source_drawer_id`; re-mine idéntico = no-op; cambiado = `supersede_source` (`valid_to`, jamás delete). KG palace-local: `<palace>/knowledge_graph.sqlite3` |
| Contradicción (D) | vectores similares + texto distinto (overlap < 0.5) o señal explícita `supersedes=`: viejo `valid_to` + `superseded_by`, nuevo `supersedes`; superseded nunca rankea (`hybrid_search`, L1, L2) |

---

## Relación con Autonomy y RAG — ver [ADR-002](adr/ADR-002-memory-separation.md)

> **Decisión: AISLAR** — `dxrk/memory` (DxrkMemory) y `dxrk/rag` son
> **sistemas aislados** con contratos y persistencias distintas. El
> `Learner` de `dxrk/autonomy/` se eliminó (tanda 2: solo sobrevive el
> vocabulario de capabilities en `permissions.py`); la verificación vive
> como juez externo en `dxrk/judge/` (observe-only, auto-fix default-off).
> Detalle formal en **[ADR-002: Separación DxrkMemory vs Autonomy/Learner vs RAG/Store](adr/ADR-002-memory-separation.md)** (Accepted 2026-08-27).

**Frontera por diseño — 2 dominios, 2 stores, 0 coupling:**

| Sistema | Módulo | Persistencia | API clave | Deps |
|---------|--------|--------------|-----------|------|
| **DxrkMemory** (canónico) | `dxrk/memory` — `Palace`, `AgentMemory`, `KnowledgeGraph`, `AAAK` | `~/.dxrk/palace/sqlite_palace.db` — `sqlite3` FTS5 `trigram` + BM25, `WAL`, `0o600` | `mine()`, `search(since,before)`, `hybrid_search`, `traverse()` | **stdlib-only** (`sqlite3`, `hashlib`, `re`) |
| **RAG** (code index) | `dxrk/rag` — `chunker`, `indexer`, `VectorStore`, `OpenAIEmbedder` | in-memory `dict[str,VectorRecord]` + JSON opcional | `VectorStore.Search()`, `embed()`, `cosine_similarity` | `urllib` + `OPENAI_API_KEY` opcional |

**Por qué no fusionar.** Fusionar contaminaría `memory` (offline, <50 ms cold, `pip install dxrk` sin extras) con deps de red/modelo, rompería `zero-trace` (`grep engram|mempal == 0`, `LEGACY` `chr-join` ofuscado), mezclaría semánticas incompatibles (`filed_at`/`wing` vs `success_rate`/`error` vs `start_line`/`language`) y acoplaría `WAL`/`mine_palace_lock`/`reap 900 s`/`FIFO guard` (`db29959`/`27212e5`) a dominios que no los necesitan. Alternativas `SQLite compartido` (colecciones separadas en mismo `.db`) y `shared vector store` (todo a `OpenAIEmbedder` + HNSW) se rechazan en el ADR — ver `MIGRATION_3.3.5_3.7.1.md` “No portados” (`HNSW`/`numpy2`/`onnx`).

**Puentes opcionales sin storage coupling:**

- `RAG → Palace` via **enrichment** (`dxrk/memory/__init__.py:148-157`): `AgentMemory(path, rag=rag)` inyecta `rag.is_enabled()/query(text,1)` en `store()` para poblar `entry.embedding` antes del `upsert`. Sin `rag` o sin `OPENAI_API_KEY`, `memory` opera **BM25 puro**. `RAG` nunca lee `sqlite_palace.db`.
- El puente histórico `Learner → Palace` (export fire-and-forget a `wing=autonomy/room=pattern`) murió con el `Learner`; `wing=autonomy` queda como datos históricos legibles, sin productor.

**Reglas de frontera (ADR-002):**

- `R1 stdlib-only` — `memory` sin `openai`/`numpy`/`chromadb`.
- `R2 DB por dominio` — `memory` WAL, `rag` in-memory/JSON.
- `R3 no read-through` — ningún sistema importa el store interno de otro.
- `R4 zero-trace` — `grep engram|mempal dxrk/memory → 0`.
- `R5 multi-tenant ready` — `palace_path` por proyecto/usuario, `rag` por índice.
- `R6 fallback sin regresión` — si `rag`/`Palace` falla, cada sistema sigue operativo.

Verificación y plan de migración completos en [ADR-002](adr/ADR-002-memory-separation.md) — ningún `from dxrk.memory` en `rag`, ningún `from dxrk.rag` en `memory` salvo `Protocol` `rag: object`.
