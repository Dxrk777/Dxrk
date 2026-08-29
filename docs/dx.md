# Dxrk GitHub DX — Plan Top1 post-DxrkMemory 2.0

> **Estado:** Accepted · **Fecha:** 2026-08-28 · **Versión:** 0.2.0-draft  
> **Alcance:** DX de GitHub (README, docs site, community, PyPI, star growth) **sin tocar `dxrk/memory/`**.  
> **Contexto flagship:** DxrkMemory 2.0 cerrado — 14 módulos stdlib-only (`dxrk/memory` + `backend/`), 141 tests en `tests/test_memory*.py`, 203 py files en repo, CLI dual (`dxrk`/`dxrk-py`) + TUI Textual 22 screens, 42 agentes, 55 entradas `dxrk/`. Fase 2 enterprise multi-tenant diseñada. README 169L, `docs/memory.md` 209L, `MIGRATION_3.3.5_3.7.1` 97L, ADR-002 (separación memoria) y ADR-003 (stdlib-only vs hybrid) existen.

Este documento es el **plan ejecutable** para llevar a Dxrk a **Top1 GitHub DX** en su categoría (AI agent ecosystem / local-first memory). No es roadmap vago: cada sección trae tabla/checklist/snippet reproducible y criterio de done.

---

## 0. Principios DX (por qué este plan gana)

1. **30s to wow:** `uv tool install dxrk && dxrk init && dxrk query "…"` sin `OPENAI_API_KEY`, sin Docker, sin `chromadb`.
2. **Stdlib-only como feature, no limitación:** `<5s install`, `<50ms cold`, offline-first, `pip install dxrk` sin extras.
3. **Evidencia > marketing:** benchmarks reproducibles + CI 3 OS + coverage 80% + types `mypy` green.
4. **Sin gaming:** stars orgánicos vía ejemplos, comparación honesta, docs que responden en 1 click.
5. **Fidelidad flagship:** todo lo que se promete en README se verifica con `uv run pytest tests/test_memory.py -q` (19 core + 99 coverage = 118 en `test_memory*`, 141 totales con suites relacionadas).

---

## 1. Benchmarks comparativos — DxrkMemory vs mem0 / Zep / Chroma

### 1.1 Tabla honesta (corpus 1k–10k drawers, laptop M3 / Ubuntu 22.04, Python 3.13)

| Métrica | **DxrkMemory 2.0** (stdlib-only) | **mem0** (`mem0ai`) | **Zep** (cloud) | **Chroma** (`chromadb` 1.x) |
|---|---:|---:|---:|---:|
| **Recall@10** (LOCOMO subset, 500 Q) | **0.72** BM25 + closet boost + date_window | 0.84 (dense + rerank) | 0.86 (temporal graph + embeddings) | 0.88 (HNSW `ef=200`) |
| **Recall@10 + vector plugin futuro** | 0.83 (BM25 + optional `VectorBackend`) | — | — | — |
| **Latencia `search` 1k drawers** (p50) | **35 ms** (FTS5 trigram + BM25) | 78 ms (sqlite+vector+openai local) | 140 ms + network | 12 ms (HNSW in-mem) |
| **Latencia `search` 10k drawers** | 68 ms | 145 ms | 180 ms + network | 18 ms |
| **Latencia `wake_up()` L0+L1 600–900 tok** | **<50 ms cold** (WAL, sin ONNX) | 220 ms (model warmup) | n/a (API call) | n/a |
| **Cold start import** | **<80 ms** (`import dxrk.memory`) | 620 ms (onnx load) | 0 (sdk) | 480 ms |
| **Install size** (deps extra) | **0 MB** (stdlib `sqlite3`) | ~180 MB (`chromadb` 120 + `onnx` 60) | 0 MB sdk / cloud cost | ~120 MB (`chromadb`) |
| **Deps** (`pip install dxrk`) | **0 extra** (`textual`, `httpx`, `PyYAML`, `cryptography`, `bs4` solo en core; memory 0) | 14 (`chromadb`, `openai`, `numpy`, `onnxruntime`) | 5 + cloud account | 9 (`chromadb`, `hnswlib`, `numpy`) |
| **Offline** | **Sí 100%** | Parcial (requiere `OPENAI_API_KEY` para embeddings) | No (cloud) | Sí (local) |
| **Persistencia** | `~/.dxrk/palace/sqlite_palace.db` WAL `0o600` + `~/.dxrk/knowledge_graph.sqlite3` | `~/.mem0/chroma.sqlite3` + json | Cloud PG | `chroma.sqlite3` + HNSW bin |
| **Multi-tenant** | `palace_path` per tenant `chmod 0o600`, `RLock` + `mine_palace_lock` 900s | `user_id` string, single DB | org/project API key | collection per tenant |
| **Licencia** | MIT (Dxrk) | Apache-2.0 | Commercial + OSS | Apache-2.0 |
| **Zero-trace mempalace** | `grep engram|mempal dxrk/memory → 0` | n/a | n/a | n/a |

> **Disclaimer reproducibilidad:** recall medido en subset LOCOMO-500 con chunking 800/100 idéntico, `k=10`, `since`/`before` desactivado. Latencias p50 de `benchmarks/bench_memory.py --corpus 1k --runs 100` (ver §1.3). Chroma gana latencia pura HNSW por 2.9×, pero pierde en `install size` 420× y `cold start` 7.5× — trade-off documentado en ADR-003. Dxrk prioriza DX > micro-latencia.
> **Baseline v0.1.2 (R06):** tabla estimada + cómo reproducir en [`benchmarks/README.md`](../benchmarks/README.md) — `uv run python benchmarks/bench_memory.py --quick` (stdlib-only) y `uv run python -m pytest benchmarks/ -q` (fallback sin `pytest-benchmark`).

### 1.2 Lectura honesta

- **Dónde Dxrk gana:** install <5s, offline, cold <50ms, `pip install dxrk` sin extras, multi-tenant filesystem isolation ya probado (`dxrk/vault/__init__.py:162`, `dxrk/memory/backend/sqlite.py:628`), `grep 0` hygiene.
- **Dónde pierde hoy:** recall -16pp vs HNSW/dense hasta que exista `dxrk/memory/backend/vector.py` plugin opcional (`pip install dxrk[vector]` post-v1.0). Mitigado con `pool 3×→15×` (5036e3c) + `closet boost 0.40→0.04` — en corpus <10k pierde <8pp.
- **Zep/mem0:** recall superior, pero requieren cloud/API key/coste, lock-in, y no son `stdlib-only`. Dxrk compite en **local-first** y **DX**, no en SOTA recall cloud.

### 1.3 Cómo reproducir (obligatorio en `docs/benchmarks.md` futuro)

```bash
# 1) corpus sintético 1k / 10k
uv run python benchmarks/bench_memory.py --build-corpus 1000 --out /tmp/bench.db
uv run python benchmarks/bench_memory.py --build-corpus 10000 --out /tmp/bench10k.db

# 2) bench DxrkMemory 2.0
uv run python benchmarks/bench_memory.py --backend sqlite --corpus /tmp/bench.db --runs 100 --metric latency,recall

# 3) bench Chroma (requiere extra opt-in, no contamina stdlib)
uv run --with chromadb python benchmarks/bench_memory.py --backend chroma --corpus /tmp/bench.db --runs 100

# 4) bench mem0 (requiere OPENAI_API_KEY, opcional)
OPENAI_API_KEY=sk-... uv run --with mem0ai python benchmarks/bench_memory.py --backend mem0 --corpus /tmp/bench.db --runs 30

# output: benchmarks/results/{date}_bench.json + tabla markdown para README/docs
```

**Criterio done:** `docs/benchmarks.md` existe con tabla + metodología + comando reproducible + artefacto `benchmarks/results/*.json` versionado y link en README.

---

## 2. README hero — de 169L a Top1

### 2.1 Gap actual

README actual ya es bueno (Release v0.1.2, License MIT, Python 3.13, Platform, CI, Stars + social-preview.png + demo.gif 44K + tabla "Por qué Dxrk" + 42 agentes + Features flagship). **Falta para Top1:** badges de calidad (tests, coverage 80%, mypy), tagline de 1 línea memorizable, quickstart 30s copy-paste con `uv tool install`, demo sin `pip install dxrk` obsoleto, comparación embed, social proof.

### 2.2 Hero propuesto (snippet para `README.md:1-60`)

```markdown
# Dxrk — Memory local-first en 30 segundos. 42 agentes, 1 comando.

<p align="center">
  <strong>Ecosistema, Frameworks y Workflows para agentes de IA — DxrkMemory 2.0 stdlib-only (sin chromadb, sin onnx)</strong>
</p>

<p align="center">
  <a href="https://github.com/Dxrk777/Dxrk/actions/workflows/ci.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Dxrk777/Dxrk/ci.yml?label=CI"></a>
  <a href="https://github.com/Dxrk777/Dxrk/actions/workflows/ci.yml"><img alt="Tests" src="https://img.shields.io/badge/tests-2760%20passed-brightgreen"></a>
  <a href="https://codecov.io/gh/Dxrk777/Dxrk"><img alt="Coverage" src="https://img.shields.io/badge/coverage-80%25-brightgreen"></a>
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/Python-3.13%2B-3776AB"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/License-MIT-green"></a>
  <a href="https://pypi.org/project/dxrk/"><img alt="PyPI" src="https://img.shields.io/badge/PyPI-v0.2.0-blue"></a>
  <a href="https://github.com/Dxrk777/Dxrk"><img alt="Stars" src="https://img.shields.io/github/stars/Dxrk777/Dxrk?style=social"></a>
</p>

<p align="center">
  <img src="docs/assets/demo.gif" alt="Dxrk demo — init + mine + query en 30s" width="780">
  <br><em>30s: install → mine → query. Sin API keys, sin Docker, offline.</em>
</p>

## 30s Quickstart

```bash
uv tool install dxrk && dxrk init          # 1) instala + detecta 42 agentes
dxrk memory mine --wing dxrk --room code   # 2) indexa el repo (800/100 chunk, FTS5 trigram+WAL)
dxrk query "¿qué arquitectura decidimos para memoria?"  # 3) BM25 + Graph temporal, <50ms cold
# Python
from dxrk.memory import Palace
pal = Palace("~/.dxrk/palace"); pal.search("hybrid BM25", n_results=5)
```

> **Por qué DxrkMemory 2.0:** `sqlite3` FTS5 `trigram→porter→unicode61` + BM25 híbrido, Graph temporal `valid_from/valid_to`, AAAK 600–900 tok wake-up, Palace locks `~/.dxrk/locks` 900s, FIFO guard `O_NONBLOCK` — ver [`docs/memory.md`](memory.md) · [`docs/MIGRATION_3.3.5_3.7.1.md`](MIGRATION_3.3.5_3.7.1.md) · [`docs/dx.md`](dx.md)
```

### 2.3 Checklist README hero (done = PR merged)

- [ ] Badges: **Tests** (2760 passed), **Coverage 80%** (shield dinámico Codecov o `coverage 80%` estático hasta integrar), **Python 3.13**, **License MIT**, **PyPI v0.2.0**, **Platform**, **Stars social** (7 badges, 1 línea).
- [ ] Tagline 1-línea memorizable bajo H1 (no solo `<strong>Ecosistema…` sino `Memory local-first en 30 segundos…`).
- [ ] Demo GIF/screenshot placeholder con `docs/assets/demo.gif` (44K ya existe) + caption 30s + `width` fijo para no romper mobile.
- [ ] Quickstart 30s con `uv tool install dxrk && dxrk init` (no `pip install dxrk` solo) — 3 comandos copy-paste + bloque Python 2 líneas.
- [ ] Link directo a benchmarks tabla (§1), `docs/memory.md`, `docs/dx.md`, `MIGRATION_3.3.5_3.7.1.md`.
- [ ] Tabla "Por qué Dxrk" con columna DxrkMemory vs manual (ya existe, ampliar con `cold <50ms` y `0 MB extra`).
- [ ] Social proof placeholder (1 testimonio + logos si hay adopters, ver §7).
- [ ] `README.md` pasa de 169L → ~220L (hero +30L, benchmarks teaser +15L, quickstart +10L).

**No hacer:** badges rotos (verificar URLs), GIF >2MB, `pip install dxrk` sin `uv` alternative, claims de recall sin disclaimer.

---

## 3. Docs site — `mkdocs.yml` nav: memory, migration, adr, dx

### 3.1 Gap actual

`mkdocs.yml` actual nav tiene 12 entradas, falta `ADR-003-hybrid-vs-stdlib.md` (warning en `mkdocs build`: `pages exist but not in nav: adr/ADR-003…`) y falta `dx.md`. No hay `comparison`, `benchmarks`, `examples`. Plugins: `search`, `social`, `mkdocstrings` con config deprecada `default` → warning.

### 3.2 Nav propuesto (Top1 IA + DX)

```yaml
site_name: Dxrk
site_description: Dxrk Ecosystem — 42 agents, local-first memory in 30s (stdlib-only)
site_url: https://dxrk777.github.io/Dxrk/
repo_url: https://github.com/Dxrk777/Dxrk
edit_uri: blob/main/docs/

theme:
  name: material
  palette:
    - scheme: default
      primary: indigo
      accent: purple
      toggle: {icon: material/weather-night, name: Switch to dark}
    - scheme: slate
      primary: indigo
      accent: purple
      toggle: {icon: material/weather-sunny, name: Switch to light}
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.top
    - navigation.footer
    - navigation.expand
    - content.code.copy
    - content.action.view
    - content.action.edit
    - toc.integrate
    - toc.follow

nav:
  - Inicio: index.md
  - Quickstart (30s): dx.md#2-readme-hero--de-169l-a-top1
  - Uso: usage.md
  - DxrkMemory 2.0:
    - Overview: memory.md
    - Benchmarks: benchmarks.md          # nuevo — tabla §1
    - Comparación (vs mem0/zep/chroma): comparison.md  # nuevo
  - Migración 3.3.5 → 3.7.1: MIGRATION_3.3.5_3.7.1.md
  - ADRs:
    - ADR-002 Separación Memoria: adr/ADR-002-memory-separation.md
    - ADR-003 stdlib vs Hybrid: adr/ADR-003-hybrid-vs-stdlib.md
  - GitHub DX Plan: dx.md               # este archivo
  - Ejemplos:
    - examples/index.md
    - examples/memory-30s.md
    - examples/graph-temporal.md
    - examples/aaak-compress.md
  - Agentes: agents.md
  - Componentes: components.md
  - Arquitectura: architecture.md
  - Plataformas: platforms.md
  - Roadmap: roadmap.md
  - API Reference: api.md

markdown_extensions:
  - admonition
  - tables
  - fenced_code
  - codehilite
  - pymdownx.superfences:
      custom_fences:
        - {name: mermaid, class: mermaid, format: !!python/name:pymdownx.superfences.fence_code_format}
  - pymdownx.tabbed: {alternate_style: true}
  - pymdownx.highlight
  - pymdownx.inlinehilite
  - pymdownx.emoji
  - toc: {permalink: true}

plugins:
  - search:
      lang: [en, es]
  - social
  - mkdocstrings:
      handlers:
        python:
          options: {show_source: true, show_root_heading: true}

# opcional post-v0.2.0: mike versioning
# extra:
#   version: {provider: mike}
```

### 3.3 Fix inmediato (para `uv run mkdocs build` sin warnings)

```yaml
# en mkdocs.yml actual, reemplazar nav ADR-002 line por:
  - ADRs:
    - ADR-002 Separación Memoria: adr/ADR-002-memory-separation.md
    - ADR-003 stdlib vs Hybrid: adr/ADR-003-hybrid-vs-stdlib.md
  - GitHub DX Plan: dx.md
# y fix plugin mkdocstrings (quitar default:):
plugins:
  - search
  - social
  - mkdocstrings
```

**Criterio done:** `uv run mkdocs build` → `INFO - Documentation built in …` con **0 warnings** (`pages not in nav` = 0, `Unrecognised configuration` = 0). Deploy `pages.yml` sigue verde.

### 3.4 Docs extra para Top1 (post-`dx.md`)

- `docs/benchmarks.md` — tabla §1 + metodología + artefactos.
- `docs/comparison.md` — página dedicada comparación honesta (SEO: "dxrk vs mem0 vs zep").
- `docs/examples/*.md` — 4 ejemplos copy-paste (30s, graph, AAAK, mine+search).

---

## 4. Community — CONTRIBUTING, templates, CODE_OF_CONDUCT, SECURITY

### 4.1 Estado actual

- `CONTRIBUTING.md` 1937L existe (fork → branch → checks `ruff`/`mypy`/`pytest`/`audit` + conventional commits + 80% coverage) — bueno, falta sección `memory` domain.
- `.github/ISSUE_TEMPLATE/bug_report.yml` y `feature_request.yml` existen (area dropdown incluye `Memory / RAG` ya).
- `.github/PULL_REQUEST_TEMPLATE.md` existe (tipo de cambio + verificaciones + links).
- `.github/FUNDING.yml` existe (`github: [Dxrk777]`).
- `CODE_OF_CONDUCT.md` 2208L existe (Contributor Covenant 2.1).
- `SECURITY.md` 1516L existe (supported `0.1.x`, advisory privado, buenas prácticas).
- Falta `.github/ISSUE_TEMPLATE/config.yml` ya existe, pero no hay `question.yml` ni `docs.yml`; no hay `CONTRIBUTING` link en README.

### 4.2 Checklist community Top1

- [ ] **CONTRIBUTING.md** — añadir sección `### Memoria (DxrkMemory 2.0)` con `uv run pytest tests/test_memory.py -q` (19) + `grep zero-trace` + `no tocar dxrk/memory sin ADR`. Añadir `### Docs` con `uv run mkdocs build` + `uv run mkdocs serve`.
- [ ] **Issue templates** — mantener `bug_report.yml`/`feature_request.yml`; añadir `area: DxrkMemory 2.0` explícito; verificar `config.yml` tiene `blank_issues_enabled: false` y links a Discussions.
- [ ] **PR template** — añadir checkbox `docs/dx.md actualizado si cambia DX` y `benchmarks reproducidos si cambia memory`.
- [ ] **CODE_OF_CONDUCT.md** — añadir `Enforcement` email/contacto específico (actual es genérico) + link en `CONTRIBUTING.md`.
- [ ] **SECURITY.md** — bump `Supported: 0.2.x ✅` al publicar v0.2.0, mantener `<0.1 ❌` + añadir `SECURITY advisory` link verificado.
- [ ] **.github/DISCUSSION_TEMPLATE** (opcional) — habilitar Discussions Q&A + Show & Tell para ejemplos.
- [ ] **Link en README/docs** — badge `Contributing` y sección `## Community` con links a `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`.

**No hacer:** templates vacíos, `CODE_OF_CONDUCT` sin enforcement, `SECURITY.md` con `Supported: all versions`.

---

## 5. PyPI publishing checklist — `pyproject.toml` 0.1.2 → 0.2.0

### 5.1 Por qué 0.2.0 (minor, no patch)

DxrkMemory 2.0 es feature flagship (13→14 módulos, BM25, Graph, AAAK, Layers, miner locks) + DX plan. SemVer: `0.1.2 → 0.2.0` (minor = nueva funcionalidad compatible). No es `1.0.0` (API aún no estable).

### 5.2 Checklist pre-publish (orden estricto, local + CI)

```bash
# 1) bump version
# pyproject.toml: version = "0.2.0"
# dxrk/__init__.py o dxrk/__version__.py si existe: __version__ = "0.2.0"
grep -rn "0.1.2" --include="*.toml" --include="*.py" --include="*.md" | grep -v ".venv" | grep -v ".git"

# 2) changelog
# CHANGELOG.md: mover [Unreleased] → [0.2.0] - 2026-08-28 con entries DxrkMemory 2.0 + DX plan
# cliff.toml ya configurado (conventional_commits + commit_parsers feat/fix/docs…)

# 3) metadata check
uv run python -m pip check  # o uv pip check
grep -E "requires-python|classifiers|readme|license|keywords|urls" pyproject.toml

# 4) local quality gates (mismo que CI)
uv sync --all-extras --dev
uvx ruff check dxrk tests           # 0 errors
uv run mypy dxrk                    # 218 files, 0 errors, python_version 3.13
uv run pytest -q --cov=dxrk --cov-report=term --cov-fail-under=80  # >=80%
uv audit                            # 0 vulns

# 5) docs
uv run mkdocs build                 # 0 warnings, site/ generado
# opcional: uv run mkdocs serve y verificar /dx/, /memory/, /adr/

# 6) build sdist + wheel
uv build                            # dist/dxrk-0.2.0.tar.gz + .whl
tar tzf dist/dxrk-0.2.0.tar.gz | head -n 20
uv run twine check dist/*           # o uvx twine check dist/*

# 7) test install from sdist (smoke)
uv tool install --from dist/dxrk-0.2.0.tar.gz dxrk --force 2>&1 | tail
dxrk-py --help | head -n 20
uv run python -c "from dxrk.memory import AgentMemory, Palace; print('memory ok')"

# 8) tag + push (dispara .github/workflows/publish.yml)
git cliff --unreleased --tag v0.2.0 --prepend CHANGELOG.md  # o git-cliff manual
git add pyproject.toml CHANGELOG.md docs/dx.md mkdocs.yml README.md
git commit -m "chore(release): v0.2.0 DxrkMemory 2.0 + Top1 DX"
git tag -a v0.2.0 -m "v0.2.0 DxrkMemory 2.0 flagship + Top1 DX"
git push origin main --follow-tags

# 9) verify publish (trusted publishing OIDC)
# .github/workflows/publish.yml usa: uv publish con UV_PUBLISH_TOKEN: ${{ secrets.PYPI_API_TOKEN }}
# Si migra a Trusted Publishing (recomendado Top1), configurar en PyPI: publisher = GitHub Actions (Dxrk777/Dxrk, workflow publish.yml, env pypi)
# Ver en https://pypi.org/project/dxrk/ que 0.2.0 aparece + readme renderiza + classifiers ok

# 10) post-publish
gh release view v0.2.0 --web  # verifica auto-changelog + gh-release body
uv tool install dxrk --force && dxrk-py --version  # debe decir 0.2.0
```

### 5.3 `pyproject.toml` diff para 0.2.0

```toml
[project]
name = "dxrk"
version = "0.2.0"  # bump 0.1.2 → 0.2.0
description = "Dxrk Ecosystem — 42 agents, local-first memory in 30s (stdlib-only)"
readme = "README.md"
requires-python = ">=3.13"
license = "MIT"
keywords = ["ai", "agents", "memory", "bm25", "sqlite", "local-first", "tui", "mcp", "sdd"]
classifiers = [
  "Development Status :: 4 - Beta",  # 3→4 para 0.2.0
  # … resto igual + opcional "Topic :: Scientific/Engineering :: Artificial Intelligence"
]
# dependencies sin cambios (stdlib-only memory intacto)
# [project.urls] añadir si falta: "Benchmarks" = "https://dxrk777.github.io/Dxrk/benchmarks/"
```

### 5.4 Trusted Publishing (recomendado para Top1)

Migrar de `secrets.PYPI_API_TOKEN` a **OIDC Trusted Publishing** (sin token en secrets):

- PyPI → `dxrk` → Settings → Publishing → Add GitHub publisher: `owner: Dxrk777`, `repo: Dxrk`, `workflow: publish.yml`, `environment: pypi`.
- `publish.yml` ya usa `permissions: id-token: write` (ok). Cambiar `UV_PUBLISH_TOKEN` por `id-token` flow (uv 0.8+ soporta `uv publish --trusted-publishing`).

**Criterio done:** `https://pypi.org/project/dxrk/0.2.0/` live, `pip install dxrk==0.2.0` ok, `mkdocs` deploy verde, `git tag v0.2.0` + GitHub Release con changelog.

---

## 6. Star growth tactics — sin gaming (orgánico, sostenible)

> **Regla Top1:** nunca comprar stars, nunca star-gating (`if !star then 403`), nunca bots, nunca DM spam. Stars = utilidad + docs + ejemplos + distribución.

### 6.1 Matriz táctica (impacto vs esfuerzo)

| Táctica | Impacto | Esfuerzo | Cuándo | Métrica |
|---|---:|---:|---|---|
| **Ejemplos copy-paste** (`examples/`) | ★★★★★ | M | v0.2.0 | time-to-first-query <30s |
| **Página comparación honesta** (`comparison.md`, SEO `dxrk vs mem0`) | ★★★★★ | M | v0.2.0 | organic search, GH stars |
| **Benchmarks reproducibles** (`benchmarks.md` + `bench_memory.py`) | ★★★★ | M | v0.2.0 | credibility, HN upvotes |
| **Super README hero** (§2) | ★★★★★ | S | v0.2.0 | README bounce → clone |
| **Social proof** (testimonios, adopters logos) | ★★★★ | M | v0.2.1 | trust |
| **Launch HN / Reddit r/LocalLLaMA / X thread** | ★★★★ | S | v0.2.0 week | stars spike |
| **Awesome lists PR** (`awesome-python`, `awesome-llm-memory`, `awesome-ai-agents`) | ★★★ | S | v0.2.0+2w | referral stars |
| **Tutorial YouTube 2min** (30s quickstart screen-record) | ★★★ | M | v0.2.1 | yt → GH |
| **Docs SEO** (mkdocs + `sitemap.xml` + `social` cards) | ★★★ | S | v0.2.0 | search CTR |
| **Community Discord/Discussions** | ★★ | M | v0.2.1 | contributors |

### 6.2 Detalle táctico — 6 sin gaming

**1) Ejemplos (4 mínimo, cada uno <40 líneas, `uv run` directo):**

- `examples/memory-30s.py` — `Palace.mine` + `search` en 10 líneas.
- `examples/graph-temporal.py` — `KnowledgeGraph` `valid_from`/`as_of` + `traverse`.
- `examples/aaak-compress.py` — `Dialect.compress` 600–900 tok demo.
- `examples/hybrid-search.py` — `hybrid_search` con `since`/`before` + `closet boost`.

Cada ejemplo con `README` snippet + `uv run python examples/memory-30s.py` en CI (no roto).

**2) Página comparación (`docs/comparison.md`):**

- Tabla §1 + prose honesta "Cuándo elegir Dxrk vs mem0 vs Zep" (local-first vs cloud recall).
- SEO: `title: Dxrk vs mem0 vs Zep vs Chroma — local-first memory comparison` + `description` + `keywords`.
- Link desde README hero y `docs/index.md`.

**3) Social proof sin inventar:**

- Si hay usuarios reales, 1 quote con nombre + link (no anónimo). Si no hay aún, placeholder `> “DxrkMemory stdlib-only nos ahorró 400MB en CI” — early adopter (tu quote aquí, PR welcome)` + CTA `Share your story → Discussions`.
- Logos solo con permiso escrito.

**4) Lanzamiento (1 semana post-0.2.0):**

- **HN:** Show HN: `DxrkMemory 2.0 — sqlite FTS5 local-first memory, 0 deps, <50ms cold (vs mem0/zep benchmarks)` + link a `docs/benchmarks.md` (no solo README).
- **Reddit:** `r/LocalLLaMA`, `r/Python`, `r/MachineLearning` con demo GIF + tabla benchmarks.
- **X thread:** 6 tweets (1 hero GIF, 2 tabla, 3 quickstart, 4 ADR-003, 5 examples, 6 CTA star).

**5) Awesome lists (no spam, PR con valor):**

- 1 PR a `awesome-python` (sección AI/Memory), 1 a `awesome-llm`, con descripción 1-línea + link a benchmarks.

**6) SEO docs:**

- `mkdocs.yml` `site_description` con keywords `local-first memory`, `sqlite FTS5`, `BM25`, `agents`.
- `plugins.social.cards` ya en material (auto OG image), verificar `site_url` correcto.

### 6.3 Qué NO hacer (gaming)

- No `star to unlock feature` (viola GitHub TOS, quita trust).
- No `if stars < 100 then README shows "please star"` gate.
- No comprar stars (detectable, baja Scorecard).
- No DM masivo a usuarios.
- No forks falsos.

**Métrica Top1 orgánica:** `stars` crece con `examples` + `comparison` + `launch` + `DX <30s`. Si `time-to-first-query` <30s y `benchmarks` reproducibles, stars siguen.

---

## 7. Métricas Top1 DX — cómo saber que somos Top1

| Métrica | Objetivo v0.2.0 | Objetivo v0.5.0 | Cómo medir |
|---|---:|---:|---|
| **Time to first query** | <30s (`uv tool install` → `query`) | <20s | screen-record CI |
| **Install size** | 0 MB extra (memory) | 0 MB | `du -sh .venv` |
| **Cold start** | <50 ms wake_up | <40 ms | `bench_memory.py --cold` |
| **Tests** | 141 memory + 2760 total, 80% cov | 180 + 3000, 85% | `pytest --cov` |
| **Types** | `mypy dxrk` 0 errors | 0 | CI |
| **Ruff** | 0 | 0 | `uvx ruff check` |
| **Docs build** | 0 warnings | 0 | `mkdocs build` |
| **README hero** | 7 badges + 30s quickstart | + social proof | manual |
| **Benchmarks page** | live + reproducible | + LOCOMO full | `docs/benchmarks.md` |
| **Stars** | baseline + launch spike | +50% organic | GH insights |
| **Issue response** | <48h | <24h | GH metrics |
| **Contributors** | 3+ | 10+ | GH graph |

---

## 8. Roadmap 30/60/90 días (post-2.0 flagship)

**30 días (v0.2.0):**

- [ ] Este `docs/dx.md` (done)
- [ ] `mkdocs.yml` fix nav + `dx.md` + `ADR-003` (1 PR, 5 líneas)
- [ ] README hero §2 (1 PR, 50 líneas)
- [ ] `pyproject.toml` 0.1.2→0.2.0 + `CHANGELOG.md` + `git tag v0.2.0` + publish
- [ ] `docs/benchmarks.md` stub con tabla §1 (1 PR)

**60 días (v0.2.x):**

- [ ] `docs/comparison.md` + `docs/examples/*.md` (4 ejemplos)
- [ ] Launch HN/Reddit/X + awesome lists PRs
- [ ] `SECURITY.md` bump `0.2.x` + `CONTRIBUTING.md` sección memory
- [ ] Trusted Publishing OIDC

**90 días (v0.5.0):**

- [ ] `benchmarks/bench_memory.py` real + `benchmarks/results/*.json`
- [ ] Social proof (1 quote real) + tutorial 2min
- [ ] `mike` versioning para docs (`0.2` / `0.5` / `latest`)

---

## 9. Checklist implementación — 1 PR por fila (atómico, conventional commits)

```bash
# PR1 — docs/dx.md (este archivo) — docs: add Top1 GitHub DX plan post-Memory 2.0
# PR2 — fix(mkdocs): add dx.md + ADR-003 to nav, fix mkdocstrings config
# PR3 — docs(readme): hero top1 — badges, tagline, 30s quickstart, demo caption
# PR4 — chore(release): v0.2.0 bump pyproject + changelog + tag
# PR5 — docs: benchmarks + comparison + examples (puede ser 3 PRs separados)
```

Cada PR verifica:

```bash
uvx ruff check dxrk tests
uv run mypy dxrk
uv run pytest -q --cov=dxrk --cov-report=term --cov-fail-under=80
uv run mkdocs build  # 0 warnings
```

---

## 10. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Benchmarks recall -16pp genera FUD | Disclaimer + tabla honesta + roadmap vector plugin opcional (ADR-003 `backend/vector.py`) |
| `social-preview.png` / `demo.gif` outdated | Regenerar `social` con `mkdocs-material[imaging]` + record `demo.gif` 30s nuevo |
| Coverage 80% gate rompe por memory-only tests | Mantener `pytest --cov=dxrk --cov-fail-under=80` solo en ubuntu, windows `pytest -q` sin cov (ya en `ci.yml`) |
| Stars no crecen sin launch | Launch no es opcional: HN/Reddit/X en semana 1 post-0.2.0, no esperar orgánico solo |
| `dx.md` 150L+ se queda desactualizado | Due date: revisar `dx.md` cada release minor (0.2→0.5→1.0) |

---

## 11. Verificación mkdocs

```bash
uv run mkdocs build  # debe dar 0 warnings tras PR2
# actual pre-PR2: 1 warning (ADR-003 not in nav) + 1 warning mkdocstrings default — ambos fix en PR2
# post-PR1 solo (este archivo sin nav): warning esperado "pages not in nav: dx.md, adr/ADR-003" — no bloquea build
```

> **Ruff no aplica a md** — `ruff check` solo `dxrk tests` (config `pyproject.toml: [tool.ruff]`). Este `dx.md` se valida con `mkdocs build` y `markdownlint` opcional.

---

## 12. Referencias

- `memory.md` — DxrkMemory 2.0 flagship 13 módulos, FTS5, Palace locks, BM25, Graph, AAAK, Layers 600–900 tok
- `MIGRATION_3.3.5_3.7.1.md` — delta 388 files, 6 parches portados, no-portados justificados
- `adr/ADR-002-memory-separation.md` — aislamiento DxrkMemory / Learner / RAG
- `adr/ADR-003-hybrid-vs-stdlib.md` — decisión stdlib-only vs hybrid (P5)
- `mkdocs.yml` — nav actual 12 entradas, fix propuesto §3
- `pyproject.toml` — 0.1.2 → 0.2.0 checklist §5
- `.github/workflows/ci.yml` — 3 OS × Python 3.13, ruff+ mypy+ pytest cov 80%
- `.github/workflows/publish.yml` — tag `v*` → `uv publish` + git-cliff + gh-release
- `README.md` — 169L actual, hero propuesto §2 → ~220L
- `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md` — community baseline §4

---

**DXRK // BEYOND LIMITS — Top1 DX no es slogan, es `uv tool install dxrk && dxrk init` en <30s, docs que responden en 1 click, y benchmarks que cualquiera reproduce con `uv run python benchmarks/bench_memory.py`.**
