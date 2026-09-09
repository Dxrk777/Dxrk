# SPDX-License-Identifier: MIT
"""Enterprise command — Dxrk Enterprise, la empresa de IA (7 departamentos)."""

from __future__ import annotations

from dxrk.enterprise import DxrkEnterprise

from .registry import Command, CommandContext, Registry


def register_enterprise_command(reg: Registry) -> None:
    """Registers the `dxrk enterprise` command and its subcommands."""

    def parent_run(ctx: CommandContext) -> int:
        ctx.err.write("Error: use 'dxrk enterprise start', 'stop', 'status', 'execute', 'skills' or 'report'\n")
        return 1

    def start_run(ctx: CommandContext) -> int:
        company = DxrkEnterprise()
        company.start_company()
        ctx.out.write(company.generate_company_report())
        return 0

    def stop_run(ctx: CommandContext) -> int:
        company = DxrkEnterprise()
        company.stop_company()
        ctx.out.write("Dxrk Enterprise stopped.\n")
        return 0

    def status_run(ctx: CommandContext) -> int:
        company = DxrkEnterprise()
        ctx.out.write(company.generate_company_report())
        return 0

    def execute_run(ctx: CommandContext) -> int:
        if not ctx.args:
            ctx.err.write("Error: use 'dxrk enterprise execute <task> [department]'\n")
            return 1
        company = DxrkEnterprise()
        company.start_company()
        task = ctx.args[0]
        dept = ctx.args[1] if len(ctx.args) > 1 else None
        result = company.execute_task(task, dept)
        if result.get("error"):
            ctx.err.write(f"Error: {result['error']}\n")
            return 1
        ctx.out.write(f"{result}\n")
        return 0

    def skills_run(ctx: CommandContext) -> int:
        company = DxrkEnterprise()
        for dept_id, skills in company.list_all_skills().items():
            ctx.out.write(f"{dept_id}:\n")
            for skill in skills:
                marker = "installed" if skill["installed"] else "available"
                ctx.out.write(f"  [{marker}] {skill['name']}\n")
        return 0

    def report_run(ctx: CommandContext) -> int:
        company = DxrkEnterprise()
        ctx.out.write(company.generate_company_report())
        return 0

    parent_cmd = Command(name="enterprise", short="Dxrk Enterprise, la empresa de IA", run=parent_run)
    start_cmd = Command(name="enterprise start", short="Iniciar empresa", run=start_run)
    stop_cmd = Command(name="enterprise stop", short="Detener empresa", run=stop_run)
    status_cmd = Command(name="enterprise status", short="Ver estado", run=status_run)
    execute_cmd = Command(
        name="enterprise execute",
        short="Ejecutar tarea",
        min_args=1,
        max_args=2,
        run=execute_run,
    )
    skills_cmd = Command(name="enterprise skills", short="Listar skills", run=skills_run)
    report_cmd = Command(name="enterprise report", short="Generar reporte", run=report_run)

    reg.add_command(parent_cmd)
    reg.add_command(start_cmd)
    reg.add_command(stop_cmd)
    reg.add_command(status_cmd)
    reg.add_command(execute_cmd)
    reg.add_command(skills_cmd)
    reg.add_command(report_cmd)
