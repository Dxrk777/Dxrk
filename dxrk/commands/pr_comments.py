# SPDX-License-Identifier: MIT
"""PR comments command"""

from __future__ import annotations

import json

from .gitutil import git_current_branch, git_dir, run_gh
from .registry import Command, CommandContext, Registry


def _current_pr_number(wd: str) -> str | None:
    result = run_gh(wd, "pr", "view", "--json", "number")
    if not result.ok:
        return None
    try:
        info = json.loads(result.out)
    except json.JSONDecodeError:
        return None
    number = info.get("number")
    return str(number) if number is not None else None


def register_pr_comments_command(reg: Registry) -> None:
    """Registers the `dxrk pr comments` and `dxrk pr resolve` commands."""

    def comments_run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        if git_current_branch(wd) is None:
            ctx.err.write("Error: no PR found for current branch\n")
            return 1

        number = _current_pr_number(wd)
        if number is None:
            ctx.err.write("Error: no PR found for current branch\n")
            return 1

        issue = run_gh(wd, "api", f"repos/{{owner}}/{{repo}}/issues/{number}/comments")
        review = run_gh(wd, "api", f"repos/{{owner}}/{{repo}}/pulls/{number}/comments")

        out.write(f"PR #{number} Comments:\n\n")
        out.write("## General Comments\n")
        if not issue.ok or not issue.out.strip() or json.loads(issue.out or "[]") == []:
            out.write("No comments found.\n")
        else:
            try:
                for c in json.loads(issue.out):
                    out.write(f"- {c.get('user', {}).get('login', 'unknown')}: {c.get('body', '')}\n")
            except json.JSONDecodeError:
                ctx.err.write(f"warning: could not fetch PR comments: {issue.err.strip()}\n")

        out.write("\n## Code Review Comments\n")
        if not review.ok or not review.out.strip() or json.loads(review.out or "[]") == []:
            out.write("No comments found.\n")
        else:
            try:
                for c in json.loads(review.out):
                    path = c.get("path", "")
                    line = c.get("line") or c.get("original_line", "")
                    out.write(
                        f"- {c.get('user', {}).get('login', 'unknown')} ({path}:{line}): {c.get('body', '')}\n"
                    )
            except json.JSONDecodeError:
                ctx.err.write(f"warning: could not fetch review comments: {review.err.strip()}\n")
        return 0

    def resolve_run(ctx: CommandContext) -> int:
        out = ctx.out
        wd = ctx.cwd

        if not git_dir(wd).ok:
            ctx.err.write("Error: not a git repository\n")
            return 1

        number = _current_pr_number(wd)
        if number is None:
            ctx.err.write("Error: no PR found for current branch\n")
            return 1

        review = run_gh(wd, "api", f"repos/{{owner}}/{{repo}}/pulls/{number}/comments")
        if not review.ok:
            out.write("No comment threads to resolve.\n")
            return 0
        try:
            comments = json.loads(review.out)
        except json.JSONDecodeError:
            ctx.err.write(f"warning: could not fetch review comments: {review.err.strip()}\n")
            return 0

        threads: dict[str, list[dict]] = {}
        for c in comments:
            if c.get("in_reply_to_id"):
                continue
            threads.setdefault(c.get("id"), []).append(c)

        if not threads:
            out.write("No comment threads to resolve.\n")
            return 0

        resolved = 0
        for thread_id in threads:
            mutation = (
                "mutation { resolveReviewThread(input: {threadId: \""
                + str(thread_id)
                + "\"}) { thread { id } } }"
            )
            result = run_gh(wd, "api", "graphql", "-f", f"query={mutation}")
            if not result.ok:
                ctx.err.write(f"warning: could not resolve thread {thread_id}: {result.err.strip()}\n")
                continue
            resolved += 1
        out.write(f"resolved {resolved} comment thread(s)\n")
        return 0

    comments_cmd = Command(
        name="pr comments",
        short="Show comments on the current PR",
        run=comments_run,
    )
    resolve_cmd = Command(
        name="pr resolve",
        short="Resolve review comment threads on the current PR",
        run=resolve_run,
    )
    reg.add_command(comments_cmd)
    reg.add_command(resolve_cmd)
