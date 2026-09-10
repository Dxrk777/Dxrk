# SPDX-License-Identifier: MIT
"""dxrk.memory CLI — mine + hooks dispatch (stdlib-only)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _palace_dir_for_cli() -> Path:
    """Palace dir que respeta DXRK_TENANT (mine/search tenant-aware).

    - Con tenant -> ``~/.dxrk/tenants/{tid}/palace`` (igual que
      ``dxrk.memory.palace._resolve_tenant_path``).
    - Sin tenant -> legacy global ``~/.dxrk/memory`` (no se cambia el
      default para no huerfanar datos ya minados ahi).
    """
    tid = os.environ.get("DXRK_TENANT", "").strip()
    if tid:
        from dxrk.tenant.migration import tenant_root

        return tenant_root(tid) / "palace"
    return Path.home() / ".dxrk" / "memory"


def _cmd_mine(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dxrk.memory mine")
    parser.add_argument("path", help="project dir to ingest")
    parser.add_argument("--wing", default="default", help="wing name")
    parser.add_argument("--room", default="", help="room name (auto if empty)")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args(args)
    try:
        from dxrk.memory.palace import DxrkMemory
        from dxrk.security.enforcement import require_op, resolve_user

        # R12: mine mutates palace state -> readonly denied (RBAC_DENIED).
        # require_op valida el tenant antes de que tenant_root lo use.
        require_op(os.environ.get("DXRK_TENANT", ""), resolve_user(), "mine")
        dm = DxrkMemory(_palace_dir_for_cli())
        dm.init()
        result = dm.mine(ns.path, wing=ns.wing, room=ns.room or "general", dry_run=ns.dry_run)
        print(f"mine: {result}", file=sys.stderr)
        return 0
    except Exception as e:
        print(f"mine failed: {e}", file=sys.stderr)
        return 1


def _cmd_hooks(args: list[str]) -> int:
    from dxrk.memory.hooks_cli import main as hooks_main

    return hooks_main(args)


def _cmd_search(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dxrk.memory search")
    parser.add_argument("query", help="search query")
    parser.add_argument("--wing", default="")
    parser.add_argument("--n", type=int, default=5)
    ns = parser.parse_args(args)
    try:
        from dxrk.security.enforcement import require_op, resolve_user

        # R12: search is read-only -> all roles pass; gate stays wired
        # so identity/tenant errors surface here instead of storage.
        require_op(os.environ.get("DXRK_TENANT", ""), resolve_user(), "read")
    except Exception as exc:
        print(f"search denied: {exc}", file=sys.stderr)
        return 1
    from dxrk.memory import AgentMemory

    # mismo palace que _cmd_mine (tenant-aware): sin path, AgentMemory queda
    # en modo solo-memoria y search siempre devuelve [] aunque haya datos.
    mem = AgentMemory(_palace_dir_for_cli())
    res = mem.search(project_id=ns.wing or "default", query=ns.query, limit=ns.n)
    import json

    for e in res:
        print(json.dumps({"id": e.id, "content": e.content[:160], "project": e.project_id}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m dxrk.memory <mine|hooks|search> ...", file=sys.stderr)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "mine":
        return _cmd_mine(rest)
    if cmd in ("hooks", "hook"):
        return _cmd_hooks(rest)
    if cmd == "search":
        return _cmd_search(rest)
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
