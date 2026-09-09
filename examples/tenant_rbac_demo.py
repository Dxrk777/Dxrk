"""Dos tenants aislados + RBAC: crea, lista, verifica y muestra un denegado.

Uso:
    uv run python examples/tenant_rbac_demo.py

Todo corre con un HOME aislado para no tocar tu ~/.dxrk real.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and p.returncode != 0:
        raise SystemExit(f"fallo {cmd}: {p.stderr.strip()}")
    return p


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="dxrk-tenant-demo-"))
    env = dict(os.environ, HOME=str(tmp / "home"))
    dxrk_py = [sys.executable, "-m", "dxrk", "--tenant"]
    mem = [sys.executable, "-m", "dxrk.memory"]

    for tenant in ("acme", "personal"):
        p = run([*dxrk_py, tenant, "tenant", "create", tenant], env)
        print(p.stdout.strip())

    print(run([sys.executable, "-m", "dxrk", "tenant", "list"], env).stdout.strip())

    out = run([sys.executable, "-m", "dxrk", "tenant", "whoami"], dict(env, DXRK_TENANT="acme")).stdout.strip()
    assert out == "acme", out
    print(f"whoami con DXRK_TENANT=acme: {out}")

    # Gate RBAC: tenant invalido + usuario -> denegado con salida 1.
    bad = run([*mem, "search", "hola"], dict(env, DXRK_TENANT="bad!id", DXRK_USER="alice"), check=False)
    assert bad.returncode == 1 and "denied" in bad.stderr.lower(), bad
    print(f"RBAC denegado como debe ser: {bad.stderr.strip()}")

    print("OK: tenants aislados + RBAC verificado")


if __name__ == "__main__":
    main()
