# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.tui.context import get_ctx


class CompleteScreen(Screen):
    BINDINGS = [
        Binding("enter", "finish", "Finalizar"),
        Binding("escape", "finish", "Finalizar"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="complete-container"):
            yield Static(id="complete-content")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        content = self.query_one("#complete-content", Static)
        ctx = get_ctx()
        plan = ctx.plan
        failed = []
        if plan:
            for step in plan.steps:
                if step.error:
                    failed.append(step)

        if failed:
            lines = ["[bold red]La instalación terminó con errores.[/]", ""]
            lines.append("[bold]Pasos fallidos[/]")
            for step in failed:
                lines.append(f"  [red]✗ {step.id}[/]")
                for line in step.error.split("\n"):
                    lines.append(f"    [dim]{line}[/]")
            lines.append("")
            lines.append("[yellow]Es posible que se haya revertido — revisa el estado anterior.[/]")
            lines.append("")
            lines.append("[bold]Qué hacer[/]")
            lines.append("  1. Revisa los mensajes de error anteriores")
            lines.append("  2. Corrige el problema de fondo (dependencias faltantes, permisos, etc.)")
            lines.append("  3. Ejecuta Dxrk de nuevo para reintentar")
            lines.append("")
            lines.append("[dim]Pulsa Enter para volver al inicio.[/]")
            content.update("\n".join(lines))
        else:
            lines = ["[bold green]¡Listo! Tus agentes de IA están preparados.[/]", ""]
            n_agents = len(ctx.selected_agents) or 0
            n_components = len(ctx.selected_components) or 0
            lines.append(f"  [bold]Agentes configurados[/]  [green]{n_agents}[/]")
            lines.append(f"  [bold]Componentes instalados[/]  [green]{n_components}[/]")
            lines.append("")
            lines.append("[bold]Próximos pasos[/]")
            lines.append("  1. Configura tus claves de API")
            lines.append("  2. Ejecuta tu agente seleccionado")
            lines.append("  3. Prueba /sdd-new my-feature")
            lines.append("")
            if any(c.value == "DXRK_GUARDIAN" for c in ctx.selected_components):
                lines.append("[bold]GGA (por proyecto)[/]")
                lines.append("  GGA se instaló de forma global.")
                lines.append("  En cada repo ejecuta: gga init")
                lines.append("  Luego ejecuta: gga install")
                lines.append("")
            lines.append("[dim]Pulsa Enter para volver al inicio.[/]")
            content.update("\n".join(lines))

        return Widget._render(self)

    def action_finish(self) -> None:
        self.app.push_screen("welcome")
