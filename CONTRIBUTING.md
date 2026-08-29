# Contributing to Dxrk

¡Gracias por querer contribuir! Dxrk es un proyecto público y toda ayuda suma.

## Cómo contribuir

1. **Fork** el repositorio y creá una rama: `git checkout -b feat/mi-cambio`
2. Hacé cambios chicos y atómicos (una sola responsabilidad por commit)
3. Corré las verificaciones locales (abajo)
4. Abrí un **Pull Request** a `main` describiendo qué y por qué

## Entorno de desarrollo

Requisitos: **Python 3.13+** y [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-extras --dev
```

## Verificaciones obligatorias

Antes de pushear, todo debe pasar en verde:

```bash
uvx ruff check dxrk tests     # lint
uv run mypy dxrk              # type check
uv run pytest -q              # tests (2760+)
uv audit                      # seguridad de dependencias
```

Los mismos checks corren en CI (ubuntu, macos, windows) — si pasa local, pasa en CI.

## Convenciones

- **Commits**: [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `ci:`, `chore:`)
- **Tests**: escribí tests para cambios de comportamiento; el gate de cobertura es 80% (los tests POSIX-only se marcan `skipif(win32)`)
- **Tipos**: TypeScript estricto no aplica (Python), pero mypy estricto sí — sin `Any` innecesarios
- **Nombres**: descriptivos, en inglés (excepto strings de UI)
- **Documentación**: cambios de API o CLI se reflejan en `docs/` (mkdocs + mkdocstrings)

## Reportar bugs / pedir features

Usá los issue templates: `bug_report` y `feature_request`. Incluí versión (`dxrk --version`), OS y pasos para reproducir.

## Releases

Los releases se disparan con un tag `v*` desde `main` — el pipeline publica a PyPI, genera changelog y crea el release automáticamente. No es necesario (ni recomendable) tocar workflows de release en PRs normales.

## Código de conducta

Sea respetuoso y constructivo. Dxrk es un proyecto open source hecho con cariño.