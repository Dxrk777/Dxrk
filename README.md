# Dxrk — Memory local-first en 30 segundos. 42 agentes, 1 comando.

<strong>Ecosistema, Frameworks y Workflows para agentes de IA — DxrkMemory 2.0 stdlib-only (sin chromadb, sin onnx)</strong>

![Social](assets/social-preview.png)

[![Release](https://img.shields.io/badge/Release-v0.2.0-blue)](https://github.com/Dxrk777/Dxrk/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey)](docs/platforms.md)
[![CI](https://img.shields.io/github/actions/workflow/status/Dxrk777/Dxrk/ci.yml)](https://github.com/Dxrk777/Dxrk/actions)
[![Stars](https://img.shields.io/github/stars/Dxrk777/Dxrk)](https://github.com/Dxrk777/Dxrk)

---

## Qué es Dxrk

**Dxrk** es un configurador y orquestador de ecosistemas para agentes de IA. En un solo comando instala, configura y sincroniza **42 agentes de IA**, memoria persistente, skills curadas, servidores MCP y conmutador de modelos para tu stack de desarrollo completo.

![Demo](docs/assets/demo.gif)
*30s: install → mine → query. Sin API keys, sin Docker, offline.*

## 30s Quickstart

```bash
uv tool install dxrk                                            # 1) instala (42 agentes, memoria, MCP)
dxrk-py install --agent claude-code --preset full-dxrk --dry-run  # 2) vista previa del setup
python -m dxrk.memory mine ./mi-proyecto                        # 3) indexa tu codigo (FTS5 + BM25, offline)
python -m dxrk.memory search "arquitectura memoria"             # 4) busca (AND de tokens; ver docs/tutorial.md)
```
> **Por qué DxrkMemory 2.0:** `sqlite3` FTS5 `trigram→porter→unicode61` + BM25 híbrido, Graph temporal `valid_from/valid_to`, AAAK 600–900 tok wake-up, Palace locks `~/.dxrk/locks` 900s — ver [`docs/memory.md`](docs/memory.md) · [`docs/MIGRATION_3.3.5_3.7.1.md`](docs/MIGRATION_3.3.5_3.7.1.md) · [`docs/dx.md`](docs/dx.md)

- 🐍 **Python 3.13+** con TUI moderna basada en [Textual](https://textual.textualize.io/)
- 🤖 Configura **42 agentes** con un solo comando
- 🧠 **DxrkMemory 2.0 — Flagship local-first stdlib-only** (sin `chromadb`, sin `onnx`) — `sqlite3` FTS5 `trigram`+WAL, 13 módulos 4652 LOC, hybrid BM25, Palace locks, Graph temporal, dialecto AAAK, wake-up **600–900 tok** (paridad mempalace 3.7.1) — ver [`docs/memory.md`](docs/memory.md)
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

# Indexa y consulta tu memoria persistente
python -m dxrk.memory mine ./mi-proyecto
python -m dxrk.memory search "arquitectura memoria"

# Sincroniza tu configuracion (vista previa)
dxrk-py sync --agent claude-code --dry-run
```

## Enterprise (multi-tenant + RBAC)

Aislamiento local por tenant bajo `~/.dxrk/tenants/{id}/` (dirs `0o750`, archivos `0o600`). Sin servidor ni red.

```bash
dxrk-py tenant create acme          # crea tenants/acme/
dxrk-py tenant switch acme          # fija el tenant activo
dxrk-py --tenant acme tenant whoami # cualquier comando bajo ese tenant
DXRK_TENANT=acme dxrk-py tenant whoami
```

| Rol | Puede | Defecto |
|---|---|---|
| `admin` | lectura + escritura + minería + gestión de tenants | no |
| `dev` | lectura + escritura + minería (sin borrado de tenants / sudo) | no |
| `readonly` | solo búsqueda/recuerdo (`fs.read`) | **sí** |

Usuario desconocido → `readonly`. Política por tenant en `roles.json` (`{"users": {"alice": "admin"}, "default_role": "readonly"}`).

Ver [docs/tenants.md](docs/tenants.md) y [docs/rbac.md](docs/rbac.md).

![Demo multi-tenant](docs/assets/demo_tenant.gif)

## Por qué Dxrk

| Característica | Dxrk | Configurar a mano |
|---|---|---|
| Instalar un agente de IA | `dxrk-py install --agent claude-code` | Documentación, paths, symlinks, permisos |
| 42 agentes configurados | 1 comando | Horas de setup manual |
| Memoria persistente | `python -m dxrk.memory search "..."` | Buscar soluciones hechas a medida |
| Skills curadas + MCP | `dxrk-py install --component skills` | Scraping manual de repos |
| Cambiar de proveedor | `config.yaml` (`model.provider`, ver docs/config.md) | Editar config de cada agente |
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

- 🧠 **DxrkMemory 2.0 — Flagship top1 local-first stdlib-only** — `dxrk/memory` 13 archivos 4652 LOC `sqlite3` **FTS5 `trigram`+WAL** sin `chromadb`/sin `onnx`/sin `numpy`; `chr-join` LEGACY `dxrk_drawers` compat, `0` traces `engram`/`mempal` (979 reemplazos + 7 `git mv`), **fidelity 3.7.1** (388 files / 50+ commits `359c579`): re-mine honesty `1654cd2`/`759b8f1`, FIFO `O_NONBLOCK`+`S_ISREG` `db29959`, orphan lock reap `27212e5` `~/.dxrk/locks` 900 s, `since`/`before` `5036e3c` pool 3×/15×, SIGTERM. Hybrid **BM25** + closet boost, **Graph** temporal `valid_from`/`valid_to`+`as_of`, dialecto **AAAK** `compress`/`decode`, **Layers** wake-up **600–900 tok** (L0 100 + L1 500–800) — [`docs/memory.md`](docs/memory.md) · [`docs/MIGRATION_3.3.5_3.7.1.md`](docs/MIGRATION_3.3.5_3.7.1.md) · `from dxrk.memory import AgentMemory, Palace, KnowledgeGraph` — verif. `uv run pytest tests/test_memory.py -q` **19 passed**
- ✅ **Spec-Driven Development** — workflow completo con `/sdd-init`, skill registry, hooks y permisos
- ✅ **Skills curadas** — `dxrk-py install --component skills`
- ✅ **35+ servidores MCP** — configurables vía `.mcp.json`
- ✅ **Conmutador de modelos** — `model.provider` en `config.yaml`, `dxrk-py sync` lo propaga
- ✅ **TUI Textual** — detección de agentes instalados en tiempo real
- ✅ **Workflows Git** — conventional commits, PRs con revisión automática y keybindings

## Estructura del proyecto

```text
dxrk/
├── agents/          # Adaptadores para 42 agentes de IA
├── cli/             # Interfaz de línea de comandos
├── commands/        # Comandos disponibles (/commit, /branch, ...)
├── config/          # Configuración, perfiles y feature flags
├── memory/          # DxrkMemory 2.0 flagship stdlib-only 13 módulos 4652 LOC — Palace+sqlite FTS5+Graph+Layers+AAAK+miner (ver docs/memory.md)
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
Editando `model.provider` en tu `config.yaml` (ver [docs/config.md](docs/config.md));
`dxrk-py sync` propaga tu configuración a los agentes instalados.

## Roadmap

- **v0.2.0** — Pipeline de entrenamiento ML, pre-commit hooks y Dependabot
- **v0.5.0** — Marketplace de plugins
- **v1.0.0** — Multi-tenant y estabilización de API

## Documentación

| Documento | Descripción |
|---|---|
| [memory.md](docs/memory.md) | **DxrkMemory 2.0 flagship** — 13 módulos, sqlite FTS5, Palace locks, BM25, Graph, AAAK, Layers 600–900 tok |
| [MIGRATION_3.3.5_3.7.1.md](docs/MIGRATION_3.3.5_3.7.1.md) | Migración mempalace 3.3.5 → 3.7.1 — delta 388 files, parches portados |
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
