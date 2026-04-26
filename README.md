# DXRK 

Unified AI System - DxrkCore + DxrkControl + DxrkMemory

## Descripción

Dxrk es un sistema de IA unificado que integra tres componentes principales:

- **DxrkCore**: Núcleo del sistema
- **DxrkControl**: Controlador de ejecución
- **DxrkMemory**: Memoria unificada (brain)

## Estado

![CI](https://github.com/Dxrk777/Dxrk/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.13-blue)
![License](https://img.shields.io/badge/license-Propietary-red)

**Dxrk System v1.0 - ONLINE**

## Estructura

```
Dxrk/
├── DxrkCore/           # Núcleo
├── DxrkControl/        # Controlador + dist/
├── DxrkMemory/         # Memoria unificada
│   ├── dxrk_base/     # Almacenamiento base
│   └── dxrk_sync/     # Sincronización
├── dxrk_master.py      # Orquestador
├── dxrk_install.py    # Instalador
├── LICENSE-OUR.md    # Licencia propietaria
└── CONTRIBUTING.md   # Guía de contribución
```

## Instalación

```bash
# Clonar el repo
git clone https://github.com/Dxrk777/Dxrk.git
cd Dxrk

# Instalar dependencias
python3 dxrk_install.py

# Iniciar el sistema
python3 dxrk_master.py start

# Verificar estado
python3 dxrk_master.py status
```

## Docker

```bash
# Construir DxrkControl en Docker
docker build -t dxrkcontrol-build -f docker/DxrkControl.Dockerfile .
docker run --rm -v $(pwd)/DxrkControl/dist:/dxrk/DxrkControl/dist dxrkcontrol-build
```

## Tests

```bash
pytest -q tests/
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md)

## Licencia

Este software es propietario. Ver [LICENSE-OUR.md](LICENSE-OUR.md)

Copyright (c) 2026 DXRK. Todos los derechos reservados.
