# SPDX-License-Identifier: MIT
"""Commit command"""

from __future__ import annotations

from .gitutil import generate_commit_message, git_dir, git_status_porcelain, run_git
from .registry import Command, CommandContext, Flag, Registry


def register_commit_command(reg: Registry) -> None:
    """Registers the `dxrk commit` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        message = ctx.flag_str("message")
        if not message:
            diff = run_git(wd, "diff", "--cached").out
            try:
                message = generate_commit_message(diff, staged=True)
            except Exception as exc:
                ctx.err.write(f"Error: generate commit message: {exc}\n")
                return 1

        staged = git_status_porcelain(wd)
        if staged.ok and staged.out.strip() == "":
            ctx.err.write("nothing to commit\n")
            return 1

        args = ["add", "-A"]
        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1
        add = run_git(wd, *args)
        if not add.ok:
            ctx.err.write(f"Error: stage files: {add.err.strip() or add.out.strip()}\n")
            return 1

        commit_args = ["commit", "-m", message]
        if ctx.flag_bool("no-verify"):
            commit_args.append("--no-verify")
        commit = run_git(wd, *commit_args)
        if not commit.ok:
            ctx.err.write(f"Error: git commit: {commit.err.strip() or commit.out.strip()}\n")
            return 1
        out.write(commit.out)
        return 0

    cmd = Command(
        name="commit",
        short="Commit staged changes with a generated message",
        flags={
            "message": Flag("message", default="", shorthand="m", help="Commit message"),
            "no-verify": Flag("no-verify", is_bool=True, default=False, help="Skip git hooks"),
        },
        run=run,
    )
    reg.add_command(cmd)
