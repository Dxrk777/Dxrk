# SPDX-License-Identifier: MIT
"""dxrk.memory CLI — mine + hooks dispatch (stdlib-only)."""

from __future__ import annotations

import argparse
import sys


def _cmd_mine(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="dxrk.memory mine")
    parser.add_argument("path", help="project dir to ingest")
    parser.add_argument("--wing", default="default", help="wing name")
    parser.add_argument("--room", default="", help="room name (auto if empty)")
    parser.add_argument("--dry-run", action="store_true")
    ns = parser.parse_args(args)
    try:
        from pathlib import Path

        from dxrk.memory.palace import DxrkMemory

        dm = DxrkMemory(Path.home() / ".dxrk" / "memory")
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
    from dxrk.memory import AgentMemory

    mem = AgentMemory()
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
