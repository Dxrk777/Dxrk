# SPDX-License-Identifier: MIT
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.visual import Visual
from textual.widget import Widget
from textual.widgets import Footer, Static

from dxrk.tui.shared import STATE


class CompleteScreen(Screen):
    BINDINGS = [
        Binding("enter", "finish", "Finish"),
        Binding("escape", "finish", "Finish"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="complete-container"):
            yield Static(id="complete-content")
        yield Footer()

    def on_mount(self) -> None:
        self._render()

    def _render(self) -> Visual:
        content = self.query_one("#complete-content", Static)
        plan = STATE.plan
        failed = []
        if plan:
            for step in plan.steps:
                if step.error:
                    failed.append(step)

        if failed:
            lines = ["[bold red]Installation completed with errors.[/]", ""]
            lines.append("[bold]Failed steps[/]")
            for step in failed:
                lines.append(f"  [red]✗ {step.id}[/]")
                for line in step.error.split("\n"):
                    lines.append(f"    [dim]{line}[/]")
            lines.append("")
            lines.append(
                "[yellow]Rollback may have been performed — check the state above.[/]"
            )
            lines.append("")
            lines.append("[bold]What to do[/]")
            lines.append("  1. Check the error messages above")
            lines.append(
                "  2. Fix the underlying issue (missing deps, permissions, etc.)"
            )
            lines.append("  3. Run Dxrk again to retry")
            lines.append("")
            lines.append("[dim]Press Enter to return to welcome.[/]")
            content.update("\n".join(lines))
        else:
            lines = ["[bold green]Done! Your AI agents are ready.[/]", ""]
            n_agents = len(STATE.selected_agents) or 0
            n_components = len(STATE.selected_components) or 0
            lines.append(f"  [bold]Configured agents[/]  [green]{n_agents}[/]")
            lines.append(f"  [bold]Installed components[/]  [green]{n_components}[/]")
            lines.append("")
            lines.append("[bold]Next steps[/]")
            lines.append("  1. Set your API keys")
            lines.append("  2. Run your selected agent")
            lines.append("  3. Try /sdd-new my-feature")
            lines.append("")
            if any(c.value == "DXRK_GUARDIAN" for c in STATE.selected_components):
                lines.append("[bold]GGA (per project)[/]")
                lines.append("  GGA was installed globally.")
                lines.append("  In each repo run: gga init")
                lines.append("  Then run: gga install")
                lines.append("")
            lines.append("[dim]Press Enter to return to welcome.[/]")
            content.update("\n".join(lines))

        return Widget._render(self)

    def action_finish(self) -> None:
        self.app.push_screen("welcome")
