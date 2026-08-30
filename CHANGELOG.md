# Changelog

Todos los cambios notables del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y este proyecto respeta [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

## [0.2.1] - 2026-08-29

### Added
- Enterprise multi-tenant stage 1 cerrado — migración idempotente `~/.dxrk/tenants/default` (`dxrk/tenant/migration.py` 301L `TENANT_ID_RE` 9 `LEGACY_PATHS`), isolation filesystem `palace/locks/graph/identity` per tenant (`DxrkMemory`/`KnowledgeGraph`/`Layer0-3` tenant-aware `~/.dxrk/tenants/{id}/`), vault **HKDF** per-tenant (`HKDF-SHA256 salt=tenant_id info=dxrk/vault/tenant` + `DXRK_VAULT_KEY_{TENANT}` fallback), JWT `tid`/`role`/`tenants` (`TokenInfo`, `tenant_key_func`, `TenantAuthorizer`), RBAC `admin/dev/readonly` (`dxrk/security/rbac.py` `TenantRoleResolver` `roles.json` 0o600, `load_policy_for_tenant` POLICY 50), CLI `--tenant/-t` global + `DXRK_TENANT` env + `dxrk tenant list|create|switch|current|delete|whoami|migrate` 245L, TUI `TenantSwitcherScreen` modal `t` + badge `tenant: · role:`.
- Coverage **74% → 76.28%** — `tests/test_r05_coverage_boost.py` 24 tests (tenant 8%→69%, rbac 17%→86%, vault 66→81%, jwt 66→70%, entity 9→81%) + `tests/test_r05_p2_coverage.py` 34 tests (tenant CLI 16→87%, hooks 25→64%, `__main__` 0→94%, switcher 14→73%, +1.32% global 3155 passed) + `tests/test_r05_p3_coverage.py` 45 tests (pool 32→98%, logging 46→93%, transport 60→66%, +0.71% global 3200 passed) — gate `75` en `pyproject.toml` branch `true`.
- Benchmarks enterprise tenant tenant-aware + coverage reports branch.

### Changed
- `README.md` hero **30s**: H1 `Dxrk — Memory local-first en 30 segundos. 42 agentes, 1 comando.` + subtítulo DxrkMemory 2.0 stdlib-only sin chroma/onnx + demo caption 30s + `## 30s Quickstart` 3 líneas `uv tool install dxrk && dxrk-py init` + `Palace` query + `docs/memory.md` por qué FTS5 trigram BM25.
- `pyproject.toml` `version = "0.2.1"`, `dxrk/__init__.py` `__version__ = "0.2.1"`, `.github/workflows/ci.yml` bench CI non-blocking `benchmark` job (`benchmarks/bench_memory.py --quick`, `bench_http.py --quick`, `pytest benchmarks` smoke) `continue-on-error: true`.

## [0.2.0] - 2026-08-28

### Added
- **DxrkMemory 2.0 — flagship local-first stdlib-only** — fusión `mempalace 3.3.5` (`feat/opencode-integration` `5623136`) → `3.7.1` (`359c579`, 388 files, 50+ commits): 14 archivos `dxrk/memory` 6303 LOC `sqlite3` FTS5 `trigram`+WAL sin `chromadb`/sin `onnx`/sin `numpy`, `chr-join` LEGACY `dxrk_drawers` compat, `0` traces `engram`/`mempal` global (979 reemplazos + 7 `git mv`), 6 assets duplicados `git rm` dejando canónicos `memory-*`. Parches portados: re-mine honesty + chamber `1654cd2`/`759b8f1` (batch delete+closet purge + `chunk_total`), FIFO `O_NONBLOCK`+`S_ISREG` `db29959`, orphan lock reap `27212e5` (`~/.dxrk/locks` 900 s), `since`/`before` `5036e3c` pool 3×/15× + `filed_at` filter `[since, before)`, SIGTERM handler; no-portados justificados `HNSW`/`numpy2`/`chroma cache` (stdlib-only). Backend `SqliteBackend` WAL `0o600`, hybrid **BM25** + closet boost + `sanitize_query` + `date_window`, **Graph** temporal `valid_from`/`valid_to`/`as_of`+`traverse`, dialecto **AAAK** `compress`/`decode`/`count_tokens`, **Layers** `MemoryStack` L0-L3 wake-up **600–900 tok** (L0 100 + L1 500–800), **miner** `GitignoreMatcher` + safe reads — ver [`docs/memory.md`](docs/memory.md) y [`docs/MIGRATION_3.3.5_3.7.1.md`](docs/MIGRATION_3.3.5_3.7.1.md); verificación `uv run pytest tests/test_memory.py tests/test_dxrk_memory_full.py -q` **141 passed**. `from dxrk.memory import DxrkMemory, AgentMemory, KnowledgeGraph`. Hooks stdlib-only `dxrk/memory/hooks_cli.py` (`~/.dxrk/hook_state` 900 s) + MCP `mcp_server.py` 19 tools `dxrk_memory_*`.
- Suite benchmarks reproducible `benchmarks/` — `bench_memory.py` (BM25 1k/10k, mine, graph, AAAK) + `bench_http.py` (proxy/TLS/logging/pool 10 submódulos) stdlib-only, JSON versionado `benchmarks/results/`, smoke `benchmarks/test_bench_baseline.py` — ver `benchmarks/README.md` y `docs/dx.md`.
- Refactors deuda Fase 1: `dxrk/utils/http.py` 1945L → `dxrk/utils/http/{errors,context,retry,tls,proxy,transport,client,pool,logging,__init__}` 10 submódulos 2480L facade retrocompatible; `dxrk/config` unificado `storage.save_json_atomic` + `ConfigSettingsStore`/`UnifiedConfig` (priority 150); `dxrk/tui` DI `TUIContext` + `ContextVar` (`STATE` proxy xdist-safe, `DxrkApp(ctx)`).
- Documentación flagship `docs/memory.md`, migración `docs/MIGRATION_3.3.5_3.7.1.md`, ADRs `ADR-002-memory-separation`/`ADR-003-hybrid-vs-stdlib`, DX Top1 `docs/dx.md` (535L), roadmap `docs/roadmap.md` (403L, matriz I×E 15 iniciativas v0.2.0→v1.0.0).
- Cobertura branch `true` y gate `74%` en `pyproject.toml` (`--cov-fail-under=74`), CI uniforme sin `if Windows`.

### Changed
- `README.md` sección Memory/Features reposicionada: DxrkMemory 2.0 flagship stdlib-only sin `chromadb`/`onnx`, menciona 3.7.1 parity y benchmarks wake-up; estructura `dxrk/memory` actualizada en árbol del proyecto; tabla Documentación con `memory.md` y `MIGRATION_3.3.5_3.7.1.md`.
- Resolver de instalación de OpenCode: ahora usa la fórmula oficial de Homebrew (`brew install opencode`) en lugar de un tap de terceros.
- `pyproject.toml` `version = "0.2.0"`, `[tool.coverage.run]` branch + `[dependency-groups] bench` (`pytest-benchmark`), `mkdocs.yml` nav con `ADR-003`, `DX Top1`, `Roadmap`, `Benchmarks`.

## [0.1.2] - 2026-08-15

### Added
- Metadata de empaquetado premium para PyPI: `readme`, `license` SPDX (PEP 639), `classifiers`, `keywords` y URLs de proyecto (Repository, Documentation, Changelog, Issues).

## [0.1.1] - 2026-08-15

### Fixed
- Re-publicación del paquete en PyPI tras limpieza de releases.

## [0.1.0] - 2026-08-15

### Added
- CLI `dxrk-py` con entry point en `pyproject.toml` (`dxrk.__main__:main`).
- TUI basada en Textual (`dxrk/tui/`).
- Motor de memoria persistente integrable con el binario externo `Dxrk-memory` (repo `Dxrk777/dxrk-memory`).
- Sistema de adaptadores para 42 agentes de IA: Claude Code, OpenCode, Kilo Code, Gemini CLI, Cursor, VS Code Copilot, Codex, Windsurf, Antigravity, Kimi Code, Kiro IDE, Qwen Code, Pi, OpenClaw, Aider, Cline, Roo Code, Continue, Junie, Amazon Q, OpenHands, Zed AI, GitHub Copilot, Devin, Cody, Tabnine, Replit, Void, Amp, Blackbox AI, Bolt.new, Conductor, Hermes, JetBrains AI, Looperators, Lovable, PearAI, Qodo, RunCell, Trae, v0 y ZCode.
- Workflow Spec-Driven Development (`/sdd-init`), skill registry, hooks y permisos.
- Servidores MCP configurables (`.mcp.json`).
- Conmutador de proveedores y asignación de modelos por fase (`--profile` / `--profile-phase`).
- RAG local (chunking, indexado y consulta).
- Instalador multi-plataforma (`dxrk/installcmd.py`) con soporte de agentes y presets.
- Autonomía: evolución de prompts, aprendizaje, métricas y verificación.

### Changed
- Build system a setuptools con lockfile `uv.lock`.

[Unreleased]: https://github.com/Dxrk777/Dxrk/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/Dxrk777/Dxrk/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Dxrk777/Dxrk/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.2
[0.1.1]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.1
[0.1.0]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.0
