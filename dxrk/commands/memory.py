# SPDX-License-Identifier: MIT
"""Memory command"""

from __future__ import annotations

import os
import resource

from .registry import Command, CommandContext, Registry


def _meminfo() -> tuple[int, int]:
    """Returns (total_kb, available_kb) from /proc/meminfo."""
    total = 0
    available = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1])
                if total and available:
                    break
    except OSError:
        pass
    return total, available


def _process_rss_kb() -> int:
    try:
        with open(f"/proc/{os.getpid()}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ValueError, OSError):
        return 0


def register_memory_command(reg: Registry) -> None:
    """Registers the `dxrk memory` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        total_kb, available_kb = _meminfo()
        rss_kb = _process_rss_kb()

        out.write("Memory Usage\n")
        out.write("────────────\n")
        if total_kb:
            used_kb = total_kb - available_kb
            out.write(f"  System:  {used_kb / 1024:.0f} MB used of {total_kb / 1024:.0f} MB\n")
        else:
            out.write("  System:  unknown\n")
        out.write(f"  Process: {rss_kb / 1024:.1f} MB (RSS)\n")
        return 0

    cmd = Command(
        name="memory",
        short="Show memory usage",
        run=run,
    )
    reg.add_command(cmd)
