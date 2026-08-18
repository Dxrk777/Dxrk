# Dxrk

<strong>Ecosistema, Frameworks y Workflows para agentes de IA</strong>

![Social](assets/social-preview.png)

[![Release](https://img.shields.io/badge/Release-v0.1.2-blue)](https://github.com/Dxrk777/Dxrk/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](docs/platforms.md)
[![CI](https://img.shields.io/github/actions/workflow/status/Dxrk777/Dxrk/ci.yml)](https://github.com/Dxrk777/Dxrk/actions)
[![Stars](https://img.shields.io/github/stars/Dxrk777/Dxrk)](https://github.com/Dxrk777/Dxrk)

---

## Qué es Dxrk

**Dxrk** es un configurador y orquestador de ecosistemas para agentes de IA. En un solo comando instala, configura y sincroniza **42 agentes de IA**, memoria persistente, skills curadas, servidores MCP y conmutador de modelos para tu stack de desarrollo completo.

![Demo](docs/assets/demo.gif)

- 🐍 **Python 3.13+** con TUI moderna basada en [Textual](https://textual.textualize.io/)
- 🤖 Configura **42 agentes** con un solo comando
- 🧠 Memoria persistente con búsqueda semántica
- ⚡ Conmutador de proveedores y modelos con perfiles `cheap` / `balanced` / `quality`

## Instalación

> Requisito: **Python 3.13+**

```bash
pip install dxrk
```

También disponible vía `uv`:

```bash
uv tool install dxrk
```

**Desde el código fuente:**

```bash
git clone https://github.com/Dxrk777/Dxrk.git
cd Dxrk
uv sync --all-extras
uv run dxrk-py --help
```

## Uso rápido

```bash
# Instala y configura un agente con el preset completo
dxrk-py install --agent claude-code --preset full-dxrk

# Consulta tu memoria persistente
dxrk-py query "¿qué arquitectura decidimos para el módulo de memoria?"

# Cambia de proveedor de modelos
dxrk-py sync --profile cheap:openrouter/qwen/qwen3-30b-a3b:free

# Asigna modelos por fase de desarrollo
dxrk-py sync --profile-phase cheap:sdd-design:anthropic/claude-sonnet-4-20250514
```

## Por qué Dxrk

| Característica | Dxrk | Configurar a mano |
|---|---|---|
| Instalar un agente de IA | `dxrk-py install --agent claude-code` | Documentación, paths, symlinks, permisos |
| 42 agentes configurados | 1 comando | Horas de setup manual |
| Memoria persistente | `dxrk-py query "..."` | Buscar soluciones hechas a medida |
| Skills curadas + MCP | `dxrk-py skill-registry refresh` | Scraping manual de repos |
| Cambiar de proveedor | `dxrk-py sync --profile cheap:...` | Editar config de cada agente |
| Workflows Git | `/commit`, `/branch`, `/pr` | Comandos largos manuales |

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

- ✅ **Memoria persistente** — binario externo [Dxrk-memory](https://github.com/Dxrk777/dxrk-memory) (Homebrew / GitHub Releases) con búsqueda semántica: `dxrk-memory search "SDD"`
- ✅ **Spec-Driven Development** — workflow completo con `/sdd-init`, skill registry, hooks y permisos
- ✅ **Skills curadas** — `dxrk-py skill-registry refresh`
- ✅ **35+ servidores MCP** — configurables vía `.mcp.json`
- ✅ **Conmutador de modelos** — perfiles `cheap` / `balanced` / `quality` con asignación por fase (`sdd-design`, `spec`, `tasks`)
- ✅ **TUI Textual** — detección de agentes instalados en tiempo real
- ✅ **Workflows Git** — conventional commits, PRs con revisión automática y keybindings

## Estructura del proyecto

```text
dxrk/
├── agents/          # Adaptadores para 42 agentes de IA
├── cli/             # Interfaz de línea de comandos
├── commands/        # Comandos disponibles (/commit, /branch, ...)
├── config/          # Configuración, perfiles y feature flags
├── memory/          # Motor de memoria persistente
├── rag/             # RAG local (chunking, indexado, consulta)
├── security/        # Permisos y verificación de seguridad
├── tools/           # Herramientas de detección y utilidades
├── tui/             # Interfaz de terminal con Textual
├── mcp/             # Servidores MCP configurables
├── autonomy/        # Evolución de prompts, aprendizaje y verificación
├── scholar/         # Búsqueda académica y citas
└── utils/           # Utilidades compartidas
```

## Desarrollo

```bash
uv sync --all-extras          # Instala dependencias incl. dev
uv run pytest                 # 2760+ tests
uv run --with mypy mypy dxrk/ # Verificación de tipos
```

## FAQ

**¿Necesito un agente específico para usar Dxrk?**
No. Dxrk configura tu ecosistema completo; úsalo con los agentes que ya tienes instalados.

**¿Dxrk guarda mis datos?**
La memoria es local y persistente; los proveedores de modelos se configuran con tus propias API keys.

**¿Funciona en Windows?**
Sí, macOS, Linux y Windows (ver [platforms.md](docs/platforms.md)).

**¿Cómo cambio de modelo en mitad de un proyecto?**
`dxrk-py sync --profile <perfil>` y Dxrk actualiza la configuración de todos los agentes.

## Roadmap

- **v0.2.0** — Pipeline de entrenamiento ML, pre-commit hooks y Dependabot
- **v0.5.0** — Marketplace de plugins
- **v1.0.0** — Multi-tenant y estabilización de API

## Documentación

| Documento | Descripción |
|---|---|
| [intended-usage.md](docs/intended-usage.md) | Uso previsto del proyecto |
| [agents.md](docs/agents.md) | Adaptadores de agentes |
| [components.md](docs/components.md) | Componentes internos |
| [architecture.md](docs/architecture.md) | Arquitectura del sistema |
| [usage.md](docs/usage.md) | Guía de uso |
| [platforms.md](docs/platforms.md) | Plataformas soportadas |

## Licencia

[MIT](LICENSE)

---

**DXRK // BEYOND LIMITS**
