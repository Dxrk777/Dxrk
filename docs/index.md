# Dxrk

![Dxrk](assets/dxrk-icon.jpg){ width="120" align="right" }

<strong>Orquestador local-first de ecosistemas para agentes de IA: 14 agentes, memoria, SDD, MCP y multi-tenant</strong>

**Dxrk** es un configurador y orquestador de ecosistemas para agentes de IA. En un solo comando instala, configura y sincroniza **14 agentes de IA**, memoria persistente, skills curadas, servidores MCP y conmutador de modelos para tu stack de desarrollo completo.

- 🐍 **Python 3.13+** con TUI moderna basada en [Textual](https://textual.textualize.io/)
- 🤖 Configura **14 agentes** con un solo comando
- 🧠 **DxrkMemory 2.0** — memoria local con búsqueda híbrida FTS5 + BM25 y grafo temporal (sin embeddings, offline)
- 🔄 Conmutador de proveedores y modelos con perfiles `cheap` / `balanced` / `quality`
- 🛠️ Workflows de desarrollo completos (Git, commit, review, PR)

## Instalación

```bash
pip install dxrk
```

## Uso rápido

```bash
# Instala y configura un agente con el preset completo
dxrk-py install --agent claude-code --preset full-dxrk

# Consulta tu base de conocimiento
python -m dxrk.memory search "configuro mi stack"

# Sincroniza tu configuracion (vista previa)
dxrk-py sync --agent claude-code --dry-run
```

## Documentación

- [Uso](usage.md)
- [Uso previsto](intended-usage.md)
- [Agentes soportados](agents.md)
- [Componentes](components.md)
- [Arquitectura](architecture.md)
- [Plataformas](platforms.md)

## Licencia

MIT — consulta [LICENSE](https://github.com/Dxrk777/Dxrk/blob/main/LICENSE).
