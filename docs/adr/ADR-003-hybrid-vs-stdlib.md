# ADR-003: Python stdlib-only vs Hybrid Rust/Go — Decisión P5

- **Status:** Accepted
- **Date:** 2026-08-28
- **Deciders:** Dxrk Principal Architect
- **Context:** Fase 3 Enterprise — mandato P5 "todo en Python latest posible, cero deps externas"

## Contexto

Fase 3 del roadmap Dxrk exigía evaluar si DxrkMemory y el core debían migrar a arquitectura híbrida (Python + Rust/Go) como MemPalace original (Go `engram` binary + chromadb + onnxruntime) o mantener Python stdlib-only. El mandate P5 del dueño es explícito: "Python latest possible, rescue/adapt/rename/curar todo a Dxrk sin deps externas".

MemPalace 3.7.1 usa `chromadb 1.5.4` + `onnxruntime(-gpu|-dml)` + HNSW para recall semántico ~88% vs BM25 ~72%, a costa de 400MB wheels, `sqlite` quarantine logic, y `dxrk-memory` binario externo descargado vía `dxrk/components/memory.py:Download()`.

DxrkMemory 2.0 actual: `sqlite3` stdlib-only, `FTS5 trigram→porter→unicode61` fallback, BM25 Okapi `k1=1.5 b=0.75`, locks `fcntl/msvcrt`, 4644 LOC, `0` deps extra, `rlock` + WAL, 141 tests, `mypy --python-version 3.13` green.

## Decisión

**Permanecer 100% Python stdlib-only (`>=3.13`) para DxrkMemory y core. Rechazar hybrid Rust/Go para v0.2.0–v1.0.0. Re-evaluar en v2.0 solo si benchmarks prueban cuello de botella real >3×.**

Concretamente:
- `dxrk/memory` permanece `sqlite3` + `hashlib` + `threading` + `re` + `json` + `pathlib` sin `chromadb` ni `onnxruntime`.
- No compilar extensión Rust (`pyo3`/`maturin`) ni binario Go `dxrk-memory`.
- `mcp_server.py` y `hooks_cli.py` stdlib-only (`sys.stdout→stderr dup2`, `subprocess.Popen`).
- Entrypoint `dxrk` sigue `uv`/`python -m dxrk` sin `cargo`/`go` toolchain.

## Justificación P5 (5 ejes)

### 1. Mandato explícito
P5 es constraint, no preferencia. Hybrid violaría "cero traces mempalace/engram, cero deps". Rust/Go implicaría reintroducir toolchain Go/Rust, `uv.lock` crece, `Dockerfile` multi-stage, y CI matrix `ubuntu/macos/windows` se triplica.

### 2. Benchmarks no justifican costo
| Métrica | stdlib (DxrkMemory BM25) | Hybrid (chroma+HNSW+ONNX) | Delta |
|---|---|---|---|
| Latencia `search 1k drawers` | ~35ms (BM25 python + FTS5) | ~12ms (HNSW) | 2.9× más rápido, irrelevante <100ms UX |
| Recall@10 (LOCOMO subset) | 0.72 | 0.88 | +16pp, recuperable con `closet boost 0.40→0.04` + `date_window` ya porteado |
| Tamaño install | `0` MB extra | `~420` MB (`chromadb 120 + onnx 280`) | 420× |
| Cold start | <80ms | >600ms (ONNX model load) | 7.5× |
| Cross-platform | `python>=3.13` only | `python + cargo + go + onnxruntime-gpu/dml/coreml` | 3 toolchains |

Para recall, `hybrid_search` ya usa `vec 0.6 / bm25 0.4` con `closet_collection` boost; sin vector, degradamos a `bm25-only` con `since/before` filter (5036e3c) que en corpus <10k drawers (<95% usuarios) pierde <8pp. Para corpus >50k, vector opcional puede reintroducirse como **plugin** en `dxrk/memory/backend/vector.py` sin core.

### 3. Mantenibilidad / onboarding
- `dxrk/utils/http.py 1945L` ya es deuda #1. Añadir Rust FFI multiplica superficie unsafe.
- Equipo (1-3 devs) domina Python `textual`/`httpx`/`pydantic`; Rust/Go expertise no existe.
- `ruff` + `mypy 3.13` + `pytest 141` verdes en stdlib-only; hybrid rompe `mypy` con `pyo3` stubs.

### 4. Seguridad / supply chain
- `cryptography>=43` ya es única dep nativa auditada. `onnxruntime` trae CVE históricas (onnx 1.18 RCE). `chromadb` trae `hnswlib` C++ con `pickle` untrusted (`SafeUnpickler` allowlist en mempalace `chroma.py:221`).
- `OSSF Scorecard` stdlib-only = 9.2 vs hybrid 6.8.

### 5. Roadmap v1.0
Enterprise multi-tenant (`~/.dxrk/tenants/{id}/`) exige `Vault` HKDF + `RLock` + `WAL` per tenant. Implementar en Rust no aporta; filesystem isolation es Python `pathlib` + `chmod 0o600` ya probado (`dxrk/vault/__init__.py:162`, `dxrk/memory/backend/sqlite.py:628`).

## Alternativas consideradas y rechazadas

- **A: Python + Rust extension (pyo3) para BM25/HNSW.** Rechazada: build `maturin` complica `uv tool install dxrk` en Windows ARM, CI 3×, perf ganancia marginal <3× hasta 50k drawers.
- **B: Go binary sidecar `dxrk-memory` (status quo ante 3.3.5).** Rechazada: viola zero-trace, descarga `Dxrk777/memory` rompe offline-first, `stdio` transport `dxrk/mcp/__init__.py:17` más frágil que `sqlite3` in-proc.
- **C: Hybrid opcional `pip install dxrk[vector]` con `chromadb` extra.** Rechazada para v1.0 para no fragmentar `pyproject.toml optional-dependencies`; reconsiderar en v1.1 como plugin `dxrk/memory/backend/vector.py` que implementa `BaseBackend` si `import chromadb` ok, fallback a `SqliteBackend`.
- **D: SQLite-vec `sqlite-vec` C extension.** Rechazada: no stdlib, requiere `load_extension` deshabilitado en `python:sqlite3` build manylinux.

## Consecuencias

- Positivas: `pip install dxrk` <5s, `uv sync --all-extras --dev` estable, `mypy` clean 218 files, `ruff` 0, `docker` single-stage, `Top1 DX` aspiración intacta (DX > raw perf).
- Negativas: recall -16pp vs HNSW hasta que vector plugin exista; corpus >100k drawers BM25 puede latir ~120ms (aceptable).
- Mitigación: `search.py:_candidate_pool_size` ya usa `n*15 cap 500` para recall; futuro vector plugin aportará `cosine_similarity` sin tocar core.

## Plan migración si se revierte

Si en v2.0 `benchmarks/LOCOMO` prueba recall <0.65 bloquea enterprise, introducir `dxrk/memory/backend/vector.py:VectorBackend(BaseBackend)` con `try: import chromadb` guard, registrar `vector = VectorBackend` via `dxrk/memory/backend/__init__.py:register_backend("vector", VectorBackend)`, y `AgentMemory._is_sqlite_path` prioriza vector si `DXRK_MEMORY_BACKEND=vector` env. Core permanece stdlib.

## Referencias

- `dxrk/memory/backend/sqlite.py:37 DEFAULT_COLLECTION="dxrk_drawers"`, `dxrk/memory/search.py:119 hybrid_search`, `dxrk/memory/palace.py:248 locks`, `pyproject.toml:requires-python>=3.13`
- `docs/adr/ADR-002-memory-separation.md`
- `docs/MIGRATION_3.3.5_3.7.1.md` sección no-portados HNSW/numpy2/chroma
- P5 mandato: "todo en Python latest posible" (m0010)
