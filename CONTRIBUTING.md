# Contribuyendo a Dxrk

¡Gracias por tu interés en contribuir a Dxrk! Este documento describe cómo participar en el proyecto.

## Código de conducta

Al participar en este proyecto, aceptas seguir nuestro [Código de conducta](CODE_OF_CONDUCT.md).

## Empezar

1. Haz un fork del repositorio.
2. Clona tu fork: `git clone https://github.com/<tu-usuario>/Dxrk.git`
3. Instala dependencias: `uv sync --all-extras`
4. Crea una rama para tu cambio: `git checkout -b feat/mi-cambio`

## Entorno de desarrollo

- **Python 3.13+** con `uv` como gestor de paquetes.
- Ejecuta la suite de tests: `uv run pytest`
- Verifica tipos: `uv run --with mypy mypy dxrk/`

## Convenciones

- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) (`feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `style`, `perf`, `ci`).
- **Tests**: los cambios de código deben incluir tests; la suite completa debe pasar antes de abrir un PR.
- **Tipos**: TypeScript estricto no aplica (Python), pero mantenemos mypy limpio en `dxrk/`.
- **Idioma**: nombres de código en inglés; strings de UI pueden ser en español.
- **Commits chicos y atómicos**: un solo cambio por commit.

## Reportar issues

Usa las plantillas de issue:

- [Bug report](https://github.com/Dxrk777/Dxrk/issues/new?template=bug_report.yml)
- [Feature request](https://github.com/Dxrk777/Dxrk/issues/new?template=feature_request.yml)

## Pull requests

1. Asegúrate de que la suite completa pase localmente: `uv run pytest` y `uv run --with mypy mypy dxrk/`.
2. Describe el problema que resuelve tu PR y los pasos de verificación.
3. Un mantenedor revisará y hará merge cuando el CI esté verde.
