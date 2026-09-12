# Plataformas

## Soporte

| Plataforma | Estado | Detalles |
| --- | --- | --- |
| macOS | Soportado | Homebrew recomendado; detección automática de `brew` |
| Linux | Soportado | apt/dnf/pacman detectados; requiere Python 3.13+ |
| Windows | Soportado | scoop/winget detectados; uso de `goos` para paths y comandos |

## Requisitos

- Python 3.13 o superior.
- Opcional: Pillow (procesamiento de imágenes). La memoria persistente es
  nativa 100% Python stdlib-only, sin binarios externos.

## Instalación por plataforma

### macOS

```bash
brew install python@3.13
uv tool install --from git+https://github.com/Dxrk777/Dxrk.git dxrk
```

### Linux

```bash
sudo apt install python3.13   # o equivalente
uv tool install --from git+https://github.com/Dxrk777/Dxrk.git dxrk
```

### Windows

```powershell
winget install Python.Python.3.13
uv tool install --from git+https://github.com/Dxrk777/Dxrk.git dxrk
```

## Notas

- En Windows la TUI Textual funciona en Windows Terminal.
- El instalador de agentes detecta el package manager disponible
  (`brew`, `apt`, `dnf`, `pacman`, `scoop`, `winget`, `npm`) y usa el más
  apropiado para cada componente.
- La memoria es 100% Python stdlib-only: no requiere binarios externos
  ni taps de Homebrew.
