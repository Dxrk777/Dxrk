# Dxrk

<strong>Ecosistema, Frameworks y Workflows para agentes de IA</strong>

**Dxrk** es un configurador y orquestador de ecosistemas para agentes de IA. En un solo comando instala, configura y sincroniza **42 agentes de IA**, memoria persistente, skills curadas, servidores MCP y conmutador de modelos para tu stack de desarrollo completo.

- 🐍 **Python 3.13+** con TUI moderna basada en [Textual](https://textual.textualize.io/)
- 🤖 Configura **42 agentes** con un solo comando
- 🧠 Memoria persistente con búsqueda semántica
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
dxrk-py query "¿cómo configuro mi stack?"

# Sincroniza perfiles de modelos
dxrk-py sync --profile cheap:openrouter/qwen/qwen3-30b-a3b:free
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
