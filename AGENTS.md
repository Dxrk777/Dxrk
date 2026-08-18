# AGENTS.md

Instrucciones para agentes de IA que trabajan en **Dxrk** (configurador/orquestador de ecosistemas para agentes de IA, Python 3.13+).

## Comandos

- Setup: `uv sync --all-extras --dev` (requiere Python 3.13+ y uv)
- Test SIEMPRE: `uv run python -m pytest -q` — **nunca `uv run pytest`** (resuelve a `/usr/bin/pytest` del sistema, que no ve `textual` ni el venv)
- Test con cobertura: `uv run python -m pytest -q --cov=dxrk --cov-report=term-missing --cov-fail-under=80`
- Lint: `uvx ruff check dxrk tests` (regla `--fix` también usada)
- Typecheck: `uv run mypy dxrk` (excluye `tests/`)
- Audit de dependencias: `uv audit`
- Docs: `mkdocs serve` / `mkdocs build` (config `mkdocs.yml`, tema Material + mkdocstrings)
- Release: tag `v*` desde `main` dispara publish a PyPI + changelog + release (no tocar workflows de release)

## Arquitectura

- Paquete raíz `dxrk/`, espejo de `internal/commands/*.go`. Entry point CLI/TUI: `dxrk/__main__.py` (`main()`); console script publicado: `dxrk-py` (no `dxrk`).
- **Comandos CLI**: cada módulo en `dxrk/commands/*.py` expone `register_<name>_command(reg: Registry) -> None`; TODOS se registran en `dxrk/commands/__init__.py` (`register_all`). Al crear un comando hay que agregarlo ahí.
- `dxrk/commands/registry.py` define `Command`, `CommandContext` (out/err como `TextIO`, default `sys.stdout`/`sys.stderr`), `Registry` (`add_command`, `execute(argv, out, err)`), `go_quote`.
- Submódulos por dominio: `agents/`, `autonomy/`, `cli/`, `commands/`, `components/`, `config/`, `mcp/`, `rag/`, `scholar/`, `security/`, `tui/`, `utils/`.
- `utils/http.py` y `utils/image.py` son grandes (1000-1900 líneas) y de bajo coverage; `utils/` contiene helpers con sus propios tests (`tests/test_utils_*.py`).
- Config de usuario en `~/.config/dxrk/` (p.ej. `hooks.json`).

## Tests

- `pytest.ini_options` en `pyproject.toml`: `testpaths=["tests"]`, `pythonpath=["."]`, `asyncio_mode="auto"` (no hace falta `@pytest.mark.asyncio`).
- Tests por módulo espejo de `dxrk/`: `tests/test_<modulo>.py`, helpers en `tests/test_utils_*.py`. Fixture global `temp_dir` en `tests/conftest.py`.
- Tests de adapters usan markers (`.claude`, `.opencode`, etc.) definidos en `pyproject.toml`.
- Gate de cobertura: **80%** (`.github/workflows/ci.yml:48`, `CONTRIBUTING.md:36`). CI corre en ubuntu/macos/windows; tests POSIX-only se marcan `skipif(win32)`; el gate de coverage solo aplica en non-Windows.
- Gotchas httpx: `httpx.Timeout` no tiene atributo `.timeout` (usar `.connect`/`.read` o `isinstance`); `httpx.Headers` no tiene `.append` (construir con lista de pares).

## Convenciones

- Commits: Conventional Commits (`feat:`/`fix:`/`docs:`/`refactor:`/`test:`/`ci:`/`chore:`), en inglés, chicos y atómicos. Si no hay user.name/email configurados: `git -c user.name='Dxrk System' -c user.email='dxrk@local' commit -m "..."`.
- Código: mypy estricto sin `Any` innecesarios (mypy excluye `tests/`), ruff `line-length=120`, select `E,F,I,UP`. Nombres descriptivos en inglés (excepto strings de UI).
- Idioma de respuestas y docs de proyecto: español.
- Cambios de API/CLI deben reflejarse en `docs/` (mkdocs + mkdocstrings).

## Referencias

- `CONTRIBUTING.md` — convenciones de contribución y flujo de PR a `main`.
- `README.md` — visión, instalación y uso.
- `.github/workflows/ci.yml` — los checks exactos que corren en CI (fuente de verdad: si pasa local con los comandos de arriba, pasa en CI).