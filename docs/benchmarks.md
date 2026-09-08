# Benchmarks Dxrk

Benchmarks reproducibles stdlib-only (`time.perf_counter` + `statistics`,
corpus sintético aislado en `tempfile`, sin dependencias externas).
Detalle de cada caso en `benchmarks/README.md`.

## Cómo correr

```bash
uv run python benchmarks/bench_memory.py --quick   # DxrkMemory 2.0
uv run python benchmarks/bench_http.py --quick     # dxrk/utils/http
uv run python benchmarks/bench_memory.py --json /tmp/bench.json
uv run python benchmarks/bench_memory.py --quick --results-dir ""  # sin auto-save
```

Cada corrida auto-guarda en `benchmarks/results/YYYY-MM-DD_bench*.json`
(desactivable con `--results-dir ""`); `--markdown` emite tabla lista para
pegar aquí. Hay baseline vía pytest opcional
(`benchmarks/test_bench_baseline.py`).

## Baseline v0.2.0 (2026-08-28, `bench_memory`)

| Caso | p50 | Throughput |
|------|-----|------------|
| search BM25 hybrid (1k) | 1.29 ms | 715 ops/s |
| search BM25 hybrid (10k) | 1.45 ms | 635 ops/s |
| search+window BM25 | 1.99 ms | 464 ops/s |
| mine throughput | 23.01 ms | 1304 drawers/s |
| graph traverse depth2 | 0.03 ms | 23708 ops/s |
| dialect AAAK compress | 0.14 ms | 7552 ops/s |
| wake_up L0+L1 | 1.24 ms | 814 ops/s |
| cold import proxy | 0.47 µs | — |

Config: warmup 5 queries, corpus 1k/10k drawers, `QUERY_SET` de 8 términos,
BM25 (`k1=1.5 b=0.75`) + FTS5 trigram→porter, WAL `0o600`.

## Reglas

- Todo benchmark nuevo debe ser reproducible: seed fija o corpus sintético
  generado, tmp aislado, sin red.
- Guardar el JSON en `benchmarks/results/` y actualizar esta tabla si cambia
  el baseline.
- Si un caso supera 2× el p50 del baseline, se investiga antes de mergear
  (ver `test_bench_baseline.py`).
