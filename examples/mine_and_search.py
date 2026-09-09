"""Indexa un proyecto y busca en el: el flujo mine -> search de punta a punta.

Uso:
    uv run python examples/mine_and_search.py [DIR]

Si no se pasa DIR, crea un proyecto de ejemplo temporal. Todo corre con un
HOME aislado para no tocar tu ~/.dxrk real.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SAMPLE = '''"""Notas de arquitectura del proyecto ejemplo."""


def decision_memoria() -> str:
    """La memoria persistente vive en SQLite local con FTS5."""
    return "sqlite FTS5 sin servidor"


VALOR_EJEMPLO = 42
'''


def run(cmd: list[str], env: dict[str, str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise SystemExit(f"fallo {cmd[2:]}: {p.stderr.strip()}")
    return p.stdout.strip()


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="dxrk-ejemplo-"))
    home = tmp / "home"
    home.mkdir()
    proj = Path(sys.argv[1]) if len(sys.argv) > 1 else tmp / "proj"
    if len(sys.argv) == 1:
        proj.mkdir()
        (proj / "notas.py").write_text(SAMPLE, encoding="utf-8")

    env = dict(os.environ, HOME=str(home))
    py = [sys.executable, "-m", "dxrk.memory"]

    print(f"minando {proj} ...")
    print(run([*py, "mine", str(proj)], env))

    print('buscando "memoria SQLite" ...')
    out = run([*py, "search", "memoria SQLite", "--n", "3"], env)
    for line in out.splitlines():
        row = json.loads(line)
        print(f"- {row['id'][:32]}... | {row['content'][:100]}")

    if not out:
        raise SystemExit("sin resultados: algo cambio, revisa el tutorial")
    print("OK: mine -> search funciona")


if __name__ == "__main__":
    main()
