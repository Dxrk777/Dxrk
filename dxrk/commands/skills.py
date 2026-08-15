# SPDX-License-Identifier: MIT
"""Skills command"""

from __future__ import annotations

import os

from dxrk.skillregistry import load_skill, project_skill_dirs, user_skill_dirs

from .registry import Command, CommandContext, Registry


def discover_skills(cwd: str, home: str) -> list[tuple[str, str, str]]:
    """Returns (name, description, path) for every discovered skill."""
    sources = user_skill_dirs(home) + project_skill_dirs(cwd)
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for source in sources:
        if not os.path.isdir(source):
            continue
        for name in sorted(os.listdir(source)):
            dir_path = os.path.join(source, name)
            if not os.path.isdir(dir_path):
                continue
            skill_file = os.path.join(dir_path, "SKILL.md")
            entry = load_skill(skill_file)
            if entry is None or entry.name in seen:
                continue
            seen.add(entry.name)
            entries.append((entry.name, entry.description, entry.path))
    return entries


def register_skills_command(reg: Registry) -> None:
    """Registers the `dxrk skills` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        skills = discover_skills(ctx.cwd, os.path.expanduser("~"))
        if not skills:
            out.write("No skills found.\n")
            return 0
        out.write("NAME\tDESCRIPTION\tPATH\n")
        for name, description, path in skills:
            out.write(f"{name}\t{description}\t{path}\n")
        return 0

    cmd = Command(
        name="skills",
        short="List available skills",
        run=run,
    )
    reg.add_command(cmd)
