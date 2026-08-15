# SPDX-License-Identifier: MIT
from __future__ import annotations

import sys
from typing import Any, TextIO

__all__ = [
    "ParseRestoreFlags",
    "RunRestore",
]


def ParseRestoreFlags(args: list[str]) -> dict[str, Any]:
    positional: list[str] = []
    list_flag = False
    yes_flag = False

    for a in args:
        if a in ("--list", "-list"):
            list_flag = True
        elif a in ("--yes", "-yes", "-y"):
            yes_flag = True
        elif a.startswith("-"):
            raise ValueError(f"unknown flag {a!r}")
        else:
            positional.append(a)

    return {
        "list": list_flag,
        "yes": yes_flag,
        "target": positional[0] if positional else None,
    }


def RunRestore(args: list[str], stdout: TextIO | None = None) -> str | None:
    from dxrk.cli.install import run_restore

    return run_restore(args, stdout or sys.stdout)
