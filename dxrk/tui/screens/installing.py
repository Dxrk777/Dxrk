# SPDX-License-Identifier: MIT
import asyncio

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, LoadingIndicator, ProgressBar, RichLog, Static


class InstallingScreen(Screen):
    BINDINGS = [
        Binding("escape", "noop", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="installing-container"):
            yield Static("[bold]Installing...[/]", id="installing-title")
            yield LoadingIndicator(id="install-spinner")
            yield ProgressBar(total=100, id="install-progress", show_eta=False)
            yield RichLog(id="install-log", highlight=True, max_lines=20)
        yield Footer()

    @work
    async def install(self) -> None:
        from dxrk.models import Selection
        from dxrk.pipeline import run_install_pipeline
        from dxrk.tui.shared import STATE

        log_widget = self.query_one("#install-log", RichLog)
        progress = self.query_one("#install-progress", ProgressBar)

        async def on_progress(msg: str, pct: float):
            log_widget.write(msg)
            progress.progress = pct

        selection = Selection(
            agents=list(STATE.selected_agents),
            components=list(STATE.selected_components),
            skills=list(STATE.selected_skills),
            persona=STATE.persona,
            preset=STATE.preset,
            sdd_mode=STATE.sdd_mode,
            strict_tdd=STATE.strict_tdd,
            model_assignments=dict(STATE.model_assignments),
        )
        success = await run_install_pipeline(
            selection=selection,
            on_progress=on_progress,
        )
        log_widget.write(
            "[green]Installation complete![/]"
            if success
            else "[red]Installation failed![/]"
        )
        progress.progress = 100
        await asyncio.sleep(1)
        self.app.push_screen("complete")

    def action_noop(self) -> None:
        pass
