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

## Recall híbrido (2026-09-27, `bench_recall`)

Números públicos del recall híbrido (`0.6·cosine + 0.3·BM25 + 0.05·recency
+ 0.05·importance + 0.03·access`), medidos con
`uv run python benchmarks/bench_recall.py` (reps por defecto: 5).

### Método

- **Corpus**: 60 documentos sintéticos pero realistas (6 tópicos × 10 docs:
  `auth`, `deploy`, `backup`, `verify`, `cook`, `sport`), definidos en
  `benchmarks/bench_recall.py` (`CORPUS`). Aislado en `tempfile`, sin red.
- **Queries**: 24 consultas graduadas (`QUERIES`), mezcla de formulaciones
  conceptuales (sin solapamiento literal, ej. *"how do we handle auth?"*),
  léxicas (ej. *"blue-green rollback pipeline?"*) y cortas, 4 por tópico.
- **Relevancia**: a nivel de tópico — los 10 docs del tópico objetivo son
  relevantes (denominador de recall@5 = 10).
- **Métodos**:
  - `hybrid`: path productivo `DxrkMemory.search` de punta a punta (pool de
    candidatos FTS5 + rank fusionado + rerank `search._hybrid_rank`).
  - `bm25-only` (ablación): rankea el corpus completo solo con
    `dxrk.memory.search._bm25_scores` (k1=1.5, b=0.75); vector, recency,
    importance y access desactivados.
  - `vector-only` (ablación): rankea el corpus completo solo con los
    primitivos reales de `dxrk.memory.vectors` (`embed_query_counts` +
    `idf_weights` del pool + `weighted_cosine`); BM25 y resto desactivados.

### Resultados (medidos, deterministas en calidad)

| Método | P@1 | P@3 | P@5 | R@5 | latencia media/query |
|---|---:|---:|---:|---:|---:|
| hybrid | 1.000 | 0.639 | 0.542 | 0.271 | 6.97 ms |
| bm25-only | 0.958 | 0.583 | 0.492 | 0.246 | 0.30 ms |
| vector-only | 0.958 | 0.639 | 0.525 | 0.263 | 3.27 ms |

Lectura: el híbrido acierta el tópico en el top-1 en las 24 queries y supera
a ambas ablaciones en P@1/P@5/R@5 (vector-only empata en P@3). Las diferencias
son chicas — 1 query ≈ 0.04 en P@1 — y consistentes con el diseño: la fusión
hereda lo mejor de cada señal. BM25 es ~20× más rápido (0.3 ms) porque es
aritmética sobre tokens; el vector puro (~3.3 ms) paga el coseno ponderado en
512 dimensiones en Python puro; el híbrido (~7 ms) paga el path completo
sqlite + rerank.

Artefacto: `benchmarks/results/2026-09-27_bench_recall.json`
(reproducir con `uv run python benchmarks/bench_recall.py --json <path>`).

### Limitaciones (lo que este benchmark NO prueba)

- Corpus sintético y tópicos bien separados: no mide recall sobre jerga
  real de un proyecto ni tópicos ambiguos que se solapan.
- 24 queries: sin significancia estadística; 1 query mueve P@1 en 0.04.
- Recency/importance/access entran neutros (docs frescos, sin importance):
  sus pesos (+0.05/+0.05/+0.03) no se ejercitan aquí.
- Latencias no estrictamente comparables: el híbrido se mide end-to-end
  (sqlite + rerank) y las ablaciones como scoring en Python sobre el corpus
  pre-cargado (fetch excluido); el corpus (60 docs) no predice latencia a
  1k/10k drawers (ver baseline de arriba para escala).
- Una sola máquina / una sola corrida de calidad (determinista) — la
  latencia varía con el hardware; re-ejecutar localmente.

## Reglas

- Todo benchmark nuevo debe ser reproducible: seed fija o corpus sintético
  generado, tmp aislado, sin red.
- Guardar el JSON en `benchmarks/results/` y actualizar esta tabla si cambia
  el baseline.
- Si un caso supera 2× el p50 del baseline, se investiga antes de mergear
  (ver `test_bench_baseline.py`).
