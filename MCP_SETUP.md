# Configure Dxrk as MCP Server in OpenCode Desktop

## Pasos para configurar:

### Método 1: Archivo de configuración

Crea el archivo `~/.config/opencode/mcp-servers.json`:

```json
{
  "dxrk": {
    "command": "python3",
    "args": ["/home/dxrk/DxrkMonorepo_final/mcp_server.py"]
  }
}
```

### Método 2: Usando línea de comandos

```bash
# Abrir settings de MCP
opencode settings mcp add dxrk python3 "/home/dxrk/DxrkMonorepo_final/mcp_server.py"
```

### Método 3: Buscar en la UI

1. Abre OpenCode Desktop
2. Busca en el menú: `Settings > Server Tools` o `Settings > MCP`
3. Agrega un nuevo servidor

### Verificar después de configurar

Una vez configurado, usa en el chat:
- Escribe `/dxrk status` para ver el estado
- O usa `dxrk_memory_save` para guardar info

### Si no encuentras la opción MCP

Prueba estos atajos:
- Presiona `Ctrl+,` para abrir settings
- Busca "MCP" o "Server Tools"
- O Busca en el menú de OpenCode: `Server` → `Manage`