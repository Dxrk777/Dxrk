# Dxrk MCP Server Configuration

Para usar Dxrk como MCP en OpenCode Desktop, agrega esta configuración:

## Opción 1: Configuración en OpenCode

Abre OpenCode Desktop y ve a:
- Settings → MCP Servers → Add New

Y configura:
```
Name: Dxrk
Command: python3
Arguments: /home/dxrk/DxrkMonorepo_final/mcp_server.py
```

## Opción 2: Archivo de configuración

Crea `~/.opencode/mcp-servers.json`:

```json
{
  "dxrk": {
    "command": "python3",
    "args": ["/home/dxrk/DxrkMonorepo_final/mcp_server.py"]
  }
}
```

## Herramientas disponibles

Una vez configurado, tendrás:

- `dxrk_memory_save` - Guardar en memoria
- `dxrk_memory_get` - Recuperar de memoria  
- `dxrk_status` - Ver estado
- `dxrk_start` - Iniciar sistema
- `dxrk_stop` - Detener sistema

## Uso en OpenCode

```bash
# Usar herramienta
/mcp dxrk_status
```

O en el chat:

```
Usa la herramienta dxrk_memory_save para guardar "proyecto actual" = "Dxrk v1.0"
```