# SPDX-License-Identifier: MIT
"""Command registry: all command modules, mirroring internal/commands/*.go."""

from __future__ import annotations

from .registry import (
    Command,
    CommandContext,
    Flag,
    Registry,
    RunFn,
    go_duration,
    go_quote,
    parse_argv,
)

__all__ = [
    "Command",
    "CommandContext",
    "Flag",
    "Registry",
    "RunFn",
    "go_duration",
    "go_quote",
    "parse_argv",
    "register_all",
]


def register_all() -> Registry:
    """Registers every command"""
    from . import (
        agents,
        branch,
        commit,
        commit_push_pr,
        config,
        context,
        cost,
        diff,
        doctor,
        effort,
        export,
        fast,
        files,
        hooks,
        init,
        keybindings,
        mcp,
        memory,
        model,
        permissions_command,
        plan,
        plugin,
        pr_comments,
        rename,
        resume,
        review,
        rewind,
        security_review,
        session,
        share,
        skills,
        stats,
        tag,
        tasks,
        theme,
        usage,
        vim,
    )

    reg = Registry()
    agents.register_agents_command(reg)
    branch.register_branch_command(reg)
    commit.register_commit_command(reg)
    commit_push_pr.register_commit_push_pr_command(reg)
    config.register_config_command(reg)
    context.register_context_command(reg)
    cost.register_cost_command(reg)
    diff.register_diff_command(reg)
    doctor.register_doctor_command(reg)
    effort.register_effort_command(reg)
    export.register_export_command(reg)
    fast.register_fast_command(reg)
    files.register_files_command(reg)
    hooks.register_hooks_command(reg)
    init.register_init_command(reg)
    keybindings.register_keybindings_command(reg)
    mcp.register_mcp_command(reg)
    memory.register_memory_command(reg)
    model.register_model_command(reg)
    permissions_command.register_permissions_command(reg)
    plan.register_plan_command(reg)
    plugin.register_plugin_command(reg)
    pr_comments.register_pr_comments_command(reg)
    rename.register_rename_command(reg)
    resume.register_resume_command(reg)
    review.register_review_command(reg)
    security_review.register_security_review_command(reg)
    session.register_session_command(reg)
    share.register_share_command(reg)
    skills.register_skills_command(reg)
    stats.register_stats_command(reg)
    tag.register_tag_command(reg)
    tasks.register_tasks_command(reg)
    theme.register_theme_command(reg)
    usage.register_usage_command(reg)
    vim.register_vim_command(reg)
    rewind.register_rewind_command(reg)
    return reg
