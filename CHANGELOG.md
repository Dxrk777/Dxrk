# Changelog

Todos los cambios notables del proyecto se documentan aquí.
El formato sigue [Keep a Changelog](https://keepachangelog.com/es/1.1.0/) y este proyecto respeta [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Added
- Documentación de arquitectura, uso, agentes, componentes y plataformas en `docs/`.
- README profesional.
- Verificación exhaustiva de tipos con mypy (201 archivos) y suite de tests (2760 passed / 3 skipped).

### Changed
- Resolver de instalación de OpenCode: ahora usa la fórmula oficial de Homebrew (`brew install opencode`) en lugar de un tap de terceros.

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

[Unreleased]: https://github.com/Dxrk777/Dxrk/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.1
[0.1.0]: https://github.com/Dxrk777/Dxrk/releases/tag/v0.1.1
