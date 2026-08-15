# Dxrk

<p align="center">
  <strong>Ecosistema, Frameworks y Workflows para agentes de IA</strong>
</p>

<p align="center">
  <a href="https://github.com/Dxrk777/Dxrk/releases"><img src="https://img.shields.io/badge/Release-v0.1.1-blue" alt="Release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.13%2B-3776AB" alt="Python 3.13+"></a>
  <a href="https://github.com/Dxrk777/Dxrk"><img src="https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey" alt="Platform"></a>
  <a href="https://github.com/Dxrk777/Dxrk/actions"><img src="https://img.shields.io/github/actions/workflow/status/Dxrk777/Dxrk/ci.yml" alt="CI"></a>
  <a href="https://github.com/Dxrk777/Dxrk/stargazers"><img src="https://img.shields.io/github/stars/Dxrk777/Dxrk" alt="Stars"></a>
</p>

---

## Qué es Dxrk

**Dxrk** es el configurador y orquestador de ecosistemas para agentes de IA. Unifica
memoria persistente, Spec-Driven Development, skills curadas, servidores MCP y un
conmutador de proveedores de modelos en una sola herramienta de línea de comandos.

Escrito en **Python 3.13+** con una TUI basada en Textual, Dxrk:

- Configura **42 agentes de IA** (Claude Code, OpenCode, Codex, Gemini CLI, Cursor,
  Copilot, Windsurf y más) con un solo comando.
- Mantiene **memoria persistente** entre sesiones y proyectos (SDD, decisiones,
  contexto, aprender de cada interacción).
- Gestiona **skills curadas** y servidores **MCP** por proyecto.
- Conmuta entre **proveedores y modelos de IA** con perfiles de costo por fase
  (cheap/balanced/quality) o por comando.
- Ejecuta **workflows** de desarrollo: planificación, commits con conventional
  commits, PRs, revisión de código, keybindings y más.

## Instalación

Requisito: **Python 3.13 o superior**.

### Con uv (recomendado)

```bash
uv tool install --from git+https://github.com/Dxrk777/Dxrk.git dxrk
```

### Con pip

```bash
pip install git+https://github.com/Dxrk777/Dxrk.git
```

### Desde el código fuente

```bash
git clone https://github.com/Dxrk777/Dxrk.git
cd Dxrk
uv sync --all-extras
uv run dxrk-py --help
```

## Uso rápido

```bash
# Instalar y configurar un agente
dxrk-py install --agent claude-code --preset full-dxrk

# Preguntar sobre un concepto
dxrk-py query "explica qué es Spec-Driven Development"

# Sincronizar perfil de modelos barato
dxrk-py sync --profile cheap:openrouter/qwen/qwen3-30b-a3b:free

# Perfil por fase (ej. diseño)
dxrk-py sync --profile-phase cheap:sdd-design:anthropic/claude-sonnet-4-20250514
```

## Agentes soportados (42)

| | | | |
|---|---|---|---|
| Claude Code | OpenCode | Kilo Code | Gemini CLI |
| Cursor | VS Code Copilot | Codex | Windsurf |
| Antigravity | Kimi Code | Kiro IDE | Qwen Code |
| Pi | OpenClaw | Aider | Cline |
| Roo Code | Continue | Junie | Amazon Q |
| OpenHands | Zed AI | GitHub Copilot | Devin |
| Cody | Tabnine | Replit | Void |
| Amp | Blackbox AI | Bolt.new | Conductor |
| Hermes | JetBrains AI | Looperators | Lovable |
| PearAI | Qodo | RunCell | Trae |
| v0 | ZCode | | |

## Características

- **Memoria persistente**: `dxrk-memory` (binario externo en
  [Dxrk777/dxrk-memory](https://github.com/Dxrk777/dxrk-memory), instalable vía
  Homebrew o GitHub Releases) con búsqueda semántica: `dxrk-memory search "SDD"`.
- **Spec-Driven Development**: inicialización por proyecto con `/sdd-init`,
  especificaciones, diseño y verificación.
- **Skills**: `dxrk-py skill-registry refresh` para sincronizar el registro de
  skills del proyecto.
- **Servidores MCP**: 35 servidores configurables vía `.mcp.json`.
- **Conmutador de modelos**: perfiles `cheap` / `balanced` / `quality`, asignación
  por fase (sdd-design, sdd-spec, sdd-tasks, etc.).
- **TUI**: interfaz Textual con detección de agentes instalados.
- **Workflows Git**: commits con conventional commits, PRs con revisión,
  keybindings configurables.

## Estructura del proyecto

```
dxrk/
├── __main__.py            # Entry point CLI
├── autonomy/              # Aprendizaje, evolución, verificador
├── cli/                   # Comandos de instalación y ejecución
├── commands/              # Comandos del orquestador (commit, plan, mcp, ...)
├── config/                # Configuración y validación
├── mcp/                   # Clientes MCP
├── observe/               # Observabilidad y traces
├── query/                 # Motor de consultas
├── rag/                   # Retrieval-Augmented Generation
├── security/              # JWT, permisos
├── system/                # Detección de plataforma y gestión del sistema
├── tools/                 # Herramientas del agente
├── trace/                 # Trazabilidad
├── tui/                   # Interfaz Textual
└── utils/                 # Utilidades (fileops, hooks, http, ...)
```

## Desarrollo

```bash
uv sync --all-extras          # Instalar dependencias y extras
uv run pytest                 # Suite de tests (2760+ tests)
uv run --with mypy mypy dxrk/ # Type checking
```

## Roadmap

- **v4.1.0** — pipeline de entrenamiento ML, pre-commit, dependabot, más integraciones.
- **v4.2.0** — marketplace de plugins.
- **v5.0.0** — multi-tenant.

## Documentación

| Documento | Descripción |
|---|---|
| [docs/intended-usage.md](docs/intended-usage.md) | Uso intencional del ecosistema |
| [docs/agents.md](docs/agents.md) | Agentes soportados |
| [docs/components.md](docs/components.md) | Componentes del sistema |
| [docs/architecture.md](docs/architecture.md) | Arquitectura |
| [docs/usage.md](docs/usage.md) | Guía de uso |
| [docs/platforms.md](docs/platforms.md) | Plataformas |

## Licencia

MIT — ver [LICENSE](LICENSE).

---

**DXRK // BEYOND LIMITS**
