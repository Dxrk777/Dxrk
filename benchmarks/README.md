# Benchmarks Dxrk — Baseline v0.2.0

> **Roadmap R06** — benchmarks reproducibles stdlib-only para DxrkMemory 2.0 (14 módulos · 6303 LOC · backend sqlite FTS5) y `dxrk/utils/http` split 10 submódulos (~2480L).

## Qué mide

### `bench_memory.py` — DxrkMemory 2.0

| Benchmark | Qué hace | Métricas |
|---|---|---|
| `search BM25 hybrid` | `Palace.search` híbrido BM25 (`k1=1.5 b=0.75`) + FTS5 trigram→porter, pool 3×/15×, `closet boost 0.40→0.04` | p50/p95/p99 (ms), throughput ops/s |
| `search+window` | mismo + `since`/`before` sobre `filed_at` wall-clock (`date_window`) | p50/p95 |
| `mine throughput` | `Palace.mine` con `O_NONBLOCK`+`S_ISREG`, WAL `0o600`, locks `~/.dxrk/locks` | drawers/s, elapsed |
| `graph traverse` | `KnowledgeGraph.traverse(depth=2)` BFS sobre 500 triples WAL temporal | p50/p95 (ms) |
| `dialect AAAK compress` | `Dialect.compress` single-doc ~800 chars | p50 (µs), ops/s |
| `wake_up L0+L1` | `MemoryStack.wake_up()` 600–900 tok | p50/p95 (ms) |
| `cold import proxy` | `import dxrk.memory.palace` proxy | p50 (µs) |

Corpus sintético 1k/10k drawers (aislado `tempfile.TemporaryDirectory`), queries `QUERY_SET` 8 términos, warmup 5 queries antes de medir.

### `bench_http.py` — `dxrk/utils/http`

| Benchmark | Qué hace |
|---|---|
| `proxy parse` | `NewProxyConfig(url)` http/https/socks5 + auth + bypass |
| `TLS build` | `NewTLSConfig().BuildClientTLSConfig()` (`ssl.SSLContext` + `cryptography`) |
| `logging sanitize` | `SanitizeBody+SanitizeURL+SanitizeHeaders` (credit card/SSN/email redact) |
| `pool create` | `NewConnectionPool(DefaultPoolConfig())` + `Stats()` + `Close()` |
| `httpx request build` | `httpx.Request` sin IO |

Todo stdlib `time.perf_counter` + `statistics`, tmp isolation, no deps externas.

## Cómo correr

```bash
# stdlib-only, sin deps extras (siempre funciona)
uv run python benchmarks/bench_memory.py --quick
uv run python benchmarks/bench_http.py --quick

# corrida completa (1k + 10k drawers, 100 runs search)
uv run python benchmarks/bench_memory.py
uv run python benchmarks/bench_http.py

# custom
uv run python benchmarks/bench_memory.py --runs 100 --corpus 1000,10000
uv run python benchmarks/bench_memory.py --json /tmp/bench.json
uv run python benchmarks/bench_memory.py --markdown /tmp/bench.md
uv run python benchmarks/bench_http.py --runs 5000 --json /tmp/bench_http.json

# sin auto-save a benchmarks/results/
uv run python benchmarks/bench_memory.py --quick --results-dir ""
```

Salidas:
- stdout: tabla markdown lista para `docs/benchmarks.md` / `README`.
- stderr: `[bench] auto-saved → benchmarks/results/YYYY-MM-DD_bench*.json` (desactivable con `--results-dir ""`).
- `--json PATH`: JSON extra con `version`, `suite`, `cases[]` cada uno con `stats {p50_ms,p95_ms,mean_ms,…}` + `throughput`.

### `pytest` (opcional)

```bash
# smoke stdlib (sin pytest-benchmark): garantiza que benches corren y umbrales razonables
uv run python -m pytest benchmarks/ -q

# con pytest-benchmark (grupo opcional `bench`):
uv sync --group bench          # o: uv pip install pytest-benchmark
# o: pip install -e ".[bench]"

# usa fixture `benchmark` para micro-benchmarks con estadísticas ricas
uv run python -m pytest benchmarks/ -q --benchmark-only
uv run python -m pytest benchmarks/ --benchmark-json /tmp/bench_pytest.json
```

Fallback: si `pytest-benchmark` no está instalado, `benchmarks/test_bench_baseline.py` hace fallback a `timeit`/stdlib y **no falla** por fixture missing — tests siguen verdes.

## Baseline esperado v0.2.0 (estimado)

> Laptop M3 / Ubuntu 22.04 · Python 3.13 · WAL `0o600` · FTS5 trigram→porter→unicode61 · `mine_palace_lock` 900s

### DxrkMemory

| Benchmark | Corpus | Runs | p50 (ms) | p95 (ms) | mean (ms) | throughput |
|---|---:|---:|---:|---:|---:|---|
| search BM25 hybrid | 1 000 | 100 | 35 | 55 | 38 | ~2600 ops/s |
| search BM25 hybrid | 10 000 | 100 | 68 | 110 | 75 | ~1300 ops/s |
| search+window BM25 | 1 000 | 50 | 42 | 65 | 45 | ~2200 ops/s |
| mine throughput | ~400 drawers | 200 files | 320 ms total | — | — | ~1200 drawers/s |
| graph traverse depth2 | 500 triples | 50 | 8 | 14 | 9 | ~110k ops/s |
| dialect AAAK compress | 1 000 docs | 1 000 | 0.08 | 0.15 | 0.09 | ~11k ops/s |
| wake_up L0+L1 | 200 drawers | 20 | 32 | 48 | 35 | ~28 ops/s |
| cold import proxy | 1 | 10 | 0.15 | 0.30 | 0.18 | — |

Chroma referencia (misma máquina, HNSW in-mem, no stdlib): 12 ms (1k) / 18 ms (10k) — gana 2.9× latencia pura pero pierde `install size` 420× y `cold start` 7.5×; trade-off documentado en `docs/adr/ADR-003-hybrid-vs-stdlib.md`.

### HTTP

| Benchmark | Runs | p50 (µs) | p95 (µs) | throughput |
|---|---:|---:|---:|---:|
| proxy parse | 5 000 | 4.5 | 8.0 | ~220k ops/s |
| TLS build | 1 000 | 85 | 140 | ~11k ops/s |
| logging sanitize | 5 000 | 12 | 20 | ~80k ops/s |
| pool create/stats/close | 500 | 180 | 280 | ~5.5k ops/s |
| httpx request build | 5 000 | 6.5 | 11 | ~150k ops/s |
| client headers sanitize+log | 1 000 | 22 | 35 | ~45k ops/s |

> **Estimados**: re-ejecutar localmente para tu hardware con `uv run python benchmarks/bench_memory.py --quick`.

## Formato salida

### Markdown (stdout)

```markdown
# DxrkMemory 2.0 — Benchmarks (stdlib-only)
| Benchmark | Corpus | Runs | p50 (ms) | p95 (ms) | p99 (ms) | mean (ms) | throughput |
|---|---|---|---|---|---|---|---|
| search BM25 hybrid | 1000 | 100 | 35.12 | 54.80 | ... | 38.10 | 2600 ops/s |
```

### JSON (`--json` o auto `benchmarks/results/YYYY-MM-DD_bench.json`)

```json
{
  "version": "0.2.0",
  "suite": "bench_memory",
  "quick": false,
  "generated_at": "2026-08-28T00:00:00Z",
  "python": "3.13.2",
  "cases": [
    {"name": "search BM25 hybrid", "corpus": 1000, "runs": 100, "stats": {"p50_ms": 35.1, "p95_ms": 54.8, "mean_ms": 38.1, ...}, "throughput": 2631.0}
  ]
}
```

Versionar artefactos en `benchmarks/results/` para `docs/benchmarks.md`.

## Integración docs

- `docs/dx.md` §1.3 referencia `benchmarks/bench_memory.py --corpus 1k --runs 100`.
- `docs/benchmarks.md` (futuro) debe incluir tabla + metodología + artefacto `benchmarks/results/*.json` + link desde README hero.
- `mkdocs.yml` nav: añadir `Benchmarks: benchmarks.md` cuando exista.

## Dependencias opcionales

```toml
[project.optional-dependencies]
bench = ["pytest-benchmark>=4.0"]

[dependency-groups]
bench = ["pytest-benchmark>=4.0"]
```

Instalar solo si se quiere `pytest --benchmark-only`:

```bash
uv sync --group bench
# o
uv pip install -e ".[bench]"
```

Sin el grupo, `pytest benchmarks/ -q` corre igual (fallback stdlib).

## Troubleshooting

- `RuntimeError: palace … is held by another writer` → otro `bench_memory.py` concurrente con mismo `palace_path` tmp; reintentar (usa `TemporaryDirectory` aislado, no debería pasar).
- `mypy benchmarks` con `too many errors` → benchmarks tiene `type: ignore` para `dxrk.utils.http` re-exports ya tipados; si falla, correr `uv run mypy benchmarks --python-version 3.13 --ignore-missing-imports`.
- `ruff check benchmarks` → debe dar `All checks passed`; imports ordenados con `isort` (I).
