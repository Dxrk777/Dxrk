# SPDX-License-Identifier: MIT
"""Commit and push PR command"""

from __future__ import annotations

from .gitutil import (
    generate_commit_message,
    git_current_branch,
    git_dir,
    git_status_porcelain,
    run_gh,
    run_git,
)
from .registry import Command, CommandContext, Flag, Registry


def register_commit_push_pr_command(reg: Registry) -> None:
    """Registers the `dxrk commit-push-pr` command."""

    def run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        branch = git_current_branch(wd)
        if branch is None:
            ctx.err.write("Error: no current branch\n")
            return 1

        status = git_status_porcelain(wd)
        if status.ok and status.out.strip() == "":
            ctx.err.write("nothing to commit\n")
            return 1

        diff = run_git(wd, "diff", "--cached").out
        title = ctx.flag_str("title")
        body = ctx.flag_str("body")
        if not title:
            try:
                title = generate_commit_message(diff, staged=True)
            except Exception as exc:
                ctx.err.write(f"Error: generate commit message: {exc}\n")
                return 1

        add = run_git(wd, "add", "-A")
        if not add.ok:
            ctx.err.write(f"Error: stage files: {add.err.strip() or add.out.strip()}\n")
            return 1

        commit_args = ["commit", "-m", title]
        if body:
            commit_args += ["-m", body]
        if ctx.flag_bool("no-verify"):
            commit_args.append("--no-verify")
        commit = run_git(wd, *commit_args)
        if not commit.ok:
            ctx.err.write(
                f"Error: git commit: {commit.err.strip() or commit.out.strip()}\n"
            )
            return 1
        out.write(commit.out)

        push = run_git(wd, "push", "-u", "origin", branch)
        if not push.ok:
            ctx.err.write(f"Error: push: {push.err.strip() or push.out.strip()}\n")
            return 1
        out.write(push.out)

        pr_args = ["pr", "create", "--title", title, "--body", body or title]
        result = run_gh(wd, *pr_args)
        if not result.ok:
            ctx.err.write(f"Error: create PR: {result.err.strip() or result.out.strip()}\n")
            return 1
        url = result.out.strip()
        out.write(f"PR created: {url}\n")
        return 0

    cmd = Command(
        name="commit-push-pr",
        short="Commit, push, and open a pull request",
        long="Stage all changes, commit with a generated message, push, and create a PR.",
        flags={
            "title": Flag("title", default="", shorthand="t", help="PR title"),
            "body": Flag("body", default="", shorthand="b", help="PR body"),
            "no-verify": Flag("no-verify", is_bool=True, default=False, help="Skip git hooks"),
        },
        run=run,
    )
    reg.add_command(cmd)
