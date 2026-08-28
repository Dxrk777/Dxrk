# Changelog

Todos los cambios notables del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y este proyecto respeta [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added
- **DxrkMemory 2.0 — flagship local-first stdlib-only** — fusión `mempalace 3.3.5` (`feat/opencode-integration` `5623136`) → `3.7.1` (`359c579`, 388 files, 50+ commits): 13 archivos `dxrk/memory` 4652 LOC `sqlite3` FTS5 `trigram`+WAL sin `chromadb`/sin `onnx`/sin `numpy`, `chr-join` LEGACY `dxrk_drawers` compat, `0` traces `engram`/`mempal` global (979 reemplazos + 7 `git mv`), 6 assets duplicados `git rm` dejando canónicos `memory-*.py`. Parches portados: re-mine honesty + chamber `1654cd2`/`759b8f1` (batch delete+closet purge + `chunk_total`), FIFO `O_NONBLOCK`+`S_ISREG` `db29959`, orphan lock reap `27212e5` (`~/.dxrk/locks` 900 s), `since`/`before` `5036e3c` pool 3×/15× + `filed_at` filter `[since, before)`, SIGTERM handler; no-portados justificados `HNSW`/`numpy2`/`chroma cache` (stdlib-only). Backend `SqliteBackend` WAL `0o600`, hybrid **BM25** + closet boost + `sanitize_query`, **Graph** temporal `valid_from`/`valid_to`/`as_of`+`traverse`, dialecto **AAAK** `compress`/`decode`/`count_tokens`, **Layers** `MemoryStack` L0-L3 wake-up **600–900 tok** (L0 100 + L1 500–800), **miner** `GitignoreMatcher` + safe reads — ver [`docs/memory.md`](docs/memory.md) y [`docs/MIGRATION_3.3.5_3.7.1.md`](docs/MIGRATION_3.3.5_3.7.1.md); verificación `uv run pytest tests/test_memory.py -q` **19 passed**. `from dxrk.memory import AgentMemory, Palace, KnowledgeGraph`.
- Documentación flagship `docs/memory.md` (arquitectura 13 módulos tabla, backend FTS5, Palace locks, hybrid BM25, Graph temporal KG, AAAK, Layers 600–900 tok, GitignoreMatcher, fidelity 3.7.1, zero-deps vs mempalace/engram, uso con ejemplo) y nota de migración `docs/MIGRATION_3.3.5_3.7.1.md` (delta 388 files, tabla 6 parches portados + no-portados, repro `git log upstream/main` + `uv run pytest tests/test_memory.py -q` 19 passed).
- Documentación de arquitectura, uso, agentes, componentes y plataformas en `docs/`.
- README profesional (ahora con DxrkMemory 2.0 como flagship top1 local-first, benchmarks wake-up 600–900 tok, paridad 3.7.1).
- Verificación exhaustiva de tipos con mypy (201 archivos) y suite de tests (2760 passed / 3 skipped).

### Changed
- `README.md` sección Memory/Features reposicionada: DxrkMemory 2.0 flagship stdlib-only sin `chromadb`/`onnx`, menciona 3.7.1 parity y benchmarks wake-up; estructura `dxrk/memory` actualizada en árbol del proyecto; tabla Documentación con `memory.md` y `MIGRATION_3.3.5_3.7.1.md`.
- Resolver de instalación de OpenCode: ahora usa la fórmula oficial de Homebrew (`brew install opencode`) en lugar de un tap de terceros.

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

[Unreleased]: https://github.com/Dxrk777/Dxrk/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.2
[0.1.1]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.2
[0.1.0]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.2
