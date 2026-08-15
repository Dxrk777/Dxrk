# SPDX-License-Identifier: MIT
"""Task management commands"""

from __future__ import annotations

from dxrk.task import (
    Payload,
    TaskID,
    TaskStatus,
    TaskType,
    new_queue,
    new_task,
    with_priority,
)

from .registry import Command, CommandContext, Flag, Registry, go_quote

_queue = new_queue()


def _status_label(status: TaskStatus) -> str:
    return status.label()


def tasks_list_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        tasks = _queue.list()
        if not tasks:
            out.write("No tasks.\n")
            return 0
        out.write("ID\tTYPE\tSTATUS\tPRIORITY\tCREATED\n")
        for t in tasks:
            out.write(
                f"{t.id}\t{t.type.value}\t{_status_label(t.status)}\t{t.priority}\t"
                f"{t.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            )
        return 0

    return Command(name="tasks list", short="List tasks", run=run)


def tasks_add_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        name = ctx.args[0]
        typ_name = ctx.flag_str("type", "generic")
        try:
            typ = TaskType(typ_name)
        except ValueError:
            ctx.err.write(f"Error: invalid task type {go_quote(typ_name)}\n")
            return 1
        try:
            priority = int(ctx.flag_str("priority", "0"))
        except ValueError:
            ctx.err.write("Error: invalid priority\n")
            return 1
        t = new_task(typ, Payload({"name": name}), with_priority(priority))
        _queue.push(t)
        out.write(f"Created task {t.id}: {name}\n")
        return 0

    return Command(
        name="tasks add",
        short="Create a task",
        min_args=1,
        max_args=1,
        flags={
            "type": Flag(
                "type",
                default="generic",
                help="Task type (generic, dream, local_bash, local_agent)",
            ),
            "priority": Flag(
                "priority", default="0", help="Priority (higher = sooner)"
            ),
        },
        run=run,
    )


def tasks_delete_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        out = ctx.out
        task_id = TaskID(ctx.args[0])
        tasks = _queue.list()
        found = any(t.id == task_id for t in tasks)
        if not found:
            ctx.err.write(f"Error: task {go_quote(ctx.args[0])} not found\n")
            return 1
        _queue.remove(task_id)
        out.write(f"Deleted task {task_id}\n")
        return 0

    return Command(
        name="tasks delete", short="Delete a task", min_args=1, max_args=1, run=run
    )


def tasks_parent_cmd() -> Command:
    def run(ctx: CommandContext) -> int:
        ctx.err.write("Error: use 'dxrk tasks list', 'add', or 'delete'\n")
        return 1

    return Command(
        name="tasks",
        short="Manage tasks",
        long="Create, list, and delete tasks in the task queue.",
        run=run,
    )


def register_tasks_command(reg: Registry) -> None:
    """Registers the `dxrk tasks` command and its subcommands."""
    reg.add_command(tasks_parent_cmd())
    reg.add_command(tasks_list_cmd())
    reg.add_command(tasks_add_cmd())
    reg.add_command(tasks_delete_cmd())
