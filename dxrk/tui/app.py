# SPDX-License-Identifier: MIT
"""
Textual TUI app for Dxrk.
"""

import logging

from typing import cast

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Label,
    LoadingIndicator,
    Static,
)

from dxrk.models import (
    AgentID,
    ModelAssignment,
    PersonaID,
    PresetID,
    SDDModeID,
    UninstallMode,
)
from dxrk.system import detect
from dxrk.tui.screens.backups import (
    DeleteConfirmScreen,
    RenameBackupScreen,
    RestoreConfirmScreen,
)
from dxrk.tui.screens.dependency_tree import DependencyTreeScreen
from dxrk.tui.screens.installing import InstallingScreen
from dxrk.tui.screens.review import ReviewScreen
from dxrk.tui.shared import STATE

log = logging.getLogger(__name__)


# ── Helper Widgets ────────────────────────────────────────────────────


class OptionCard(Container):
    """A card-like option with title and description."""

    def __init__(self, value: str, title: str, description: str = ""):
        super().__init__()
        self.value = value
        self._title = title
        self._desc = description

    def compose(self) -> ComposeResult:
        yield Label(f"[bold]{self._title}[/]", classes="card-title")
        if self._desc:
            yield Label(self._desc, classes="card-desc")


# ── Welcome Screen ────────────────────────────────────────────────────

WELCOME_OPTIONS = [
    ("Install / Configure", "Set up agents, components, and tools"),
    ("Upgrade", "Upgrade installed components"),
    ("Sync", "Sync configuration to disk"),
    ("Upgrade + Sync", "Upgrade and sync in one step"),
    ("Configure Models", "Assign models to SDD phases"),
    ("Create your own Agent", "Build a custom agent with AI"),
    ("OpenCode Plugins", "Manage OpenCode community plugins"),
]

if False:  # conditionally shown
    WELCOME_OPTIONS.append(("Profiles", "Manage SDD orchestrator profiles"))

WELCOME_OPTIONS.extend(
    [
        ("Backups", "Manage installation backups"),
        ("Uninstall", "Remove agents and components"),
        ("Quit", "Exit Dxrk"),
    ]
)


class WelcomeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back", show=False),
        Binding("q", "quit", "Quit"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="welcome-container"):
            yield Static("[bold cyan]Dxrk[/] Installer", id="title")
            yield Static(f"v{STATE.version}", id="version")
            with VerticalScroll(id="menu"):
                for i, (title, desc) in enumerate(WELCOME_OPTIONS):
                    with Container(classes=f"menu-item {'focused' if i == 0 else ''}"):
                        yield Static(f"{title}", classes="item-title")
                        yield Static(desc, classes="item-desc")
        yield Footer()

    def on_mount(self) -> None:
        self._update_focus()

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_focus()

    def _update_focus(self) -> None:
        for i, child in enumerate(self.query(".menu-item")):
            child.set_class(i == self.cursor, "focused")

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(WELCOME_OPTIONS) - 1:
            self.cursor += 1

    def action_select(self) -> None:
        label = WELCOME_OPTIONS[self.cursor][0]
        mapping = {
            "Install / Configure": "detection",
            "Upgrade": "upgrade",
            "Sync": "sync",
            "Upgrade + Sync": "upgrade_sync",
            "Configure Models": "model_config",
            "Create your own Agent": "agent_builder_engine",
            "OpenCode Plugins": "opencode_plugins",
            "Profiles": "profiles",
            "Backups": "backups",
            "Uninstall": "uninstall_mode",
            "Quit": "__quit__",
        }
        target = mapping.get(label, "__quit__")
        if target == "__quit__":
            self.app.exit()
        else:
            self.app.push_screen(target)

    def action_back(self) -> None:
        pass

    def action_quit(self) -> None:
        self.app.exit()


# ── Placeholder Screen ───────────────────────────────────────────────


class PlaceholderScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(
                f"[bold]{(self.name or 'screen').replace('_', ' ').title()}[/]"
            )
            yield Static("")
            yield Static("Coming soon")
        yield Footer()

    def action_back(self) -> None:
        self.app.push_screen("welcome")

    def action_quit(self) -> None:
        self.app.exit()


# ── Detection Screen ──────────────────────────────────────────────────


class DetectionScreen(Screen):
    BINDINGS = [
        Binding("enter", "continue", "Continue"),
        Binding("escape", "back", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="detection-container"):
            yield Static("[bold]System Detection[/]", id="detection-title")
            yield LoadingIndicator(id="detection-spinner")
            yield Static("Detecting system...", id="detection-status")
        yield Footer()

    def on_mount(self) -> None:
        self._run_detection()

    @work(exclusive=True, thread=True)
    async def _run_detection(self) -> None:
        self.query_one("#detection-status", Static).update(
            "Detecting OS, tools, and dependencies..."
        )
        STATE.detection = detect()
        self.app.call_from_thread(self._show_results)

    def _show_results(self) -> None:
        spinner = self.query_one("#detection-spinner", LoadingIndicator)
        spinner.display = False
        container = self.query_one("#detection-container", Container)

        d = STATE.detection
        if not d:
            container.mount(Static("[red]Detection failed[/]"))
            return

        items = VerticalScroll(id="detection-results")
        container.mount(items)
        items.mount(Static(f"OS: [green]{d.system.os}[/] / [green]{d.system.arch}[/]"))
        items.mount(Static(f"Shell: [green]{d.system.shell}[/]"))
        items.mount(
            Static(f"Package Manager: [green]{d.system.profile.package_manager}[/]")
        )
        items.mount(Static(""))
        items.mount(Static("[bold]Tools:[/]"))
        for name, status in d.tools.items():
            c = "green" if status.installed else "red"
            v = f"  ({status.path})" if status.installed else ""
            items.mount(
                Static(f"  [{c}]{'✅' if status.installed else '❌'} {name}{v}[/]")
            )
        items.mount(Static(""))
        items.mount(Static("[bold]Configs Found:[/]"))
        for cfg in d.configs:
            items.mount(Static(f"  📄 {cfg.path}"))
        items.mount(Static(""))
        items.mount(Button("Continue", variant="primary", id="detection-continue"))
        self.query_one("#detection-status", Static).update(
            "Detection complete. Press Enter or click Continue."
        )

    @on(Button.Pressed, "#detection-continue")
    def on_continue_click(self) -> None:
        self.action_continue()

    def action_continue(self) -> None:
        self.app.push_screen("agents")

    def action_back(self) -> None:
        self.app.push_screen("welcome")


# ── Agent Selection Screen ────────────────────────────────────────────

AGENT_OPTIONS: list[tuple[AgentID, str, str]] = [
    (AgentID.CLAUDE_CODE, "Claude Code", "Anthropic's CLI agent"),
    (AgentID.OPENCODE, "OpenCode", "Open-source coding agent"),
    (AgentID.KILOCODE, "Kilocode", "Lightweight agent"),
    (AgentID.GEMINI_CLI, "Gemini CLI", "Google's coding agent"),
    (AgentID.CURSOR, "Cursor", "AI-first IDE"),
    (AgentID.VSCODE_COPILOT, "VS Code Copilot", "GitHub's AI pair programmer"),
    (AgentID.CODEX, "Codex", "CLI coding agent"),
    (AgentID.ANTIGRAVITY, "Antigravity", "Agentic coding tool"),
    (AgentID.WINDSURF, "Windsurf", "AI IDE"),
    (AgentID.KIMI, "Kimi", "AI assistant with long context"),
    (AgentID.QWEN_CODE, "Qwen Code", "Alibaba's coding agent"),
    (AgentID.KIRO_IDE, "Kiro IDE", "AI-native IDE"),
]


class AgentsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("space", "toggle", "Toggle"),
        Binding("enter", "continue", "Continue"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="agents-container"):
            yield Static("[bold]Select Agents to Install[/]", id="agents-title")
            with VerticalScroll(id="agent-list"):
                for i, (aid, name, desc) in enumerate(AGENT_OPTIONS):
                    checked = " " if aid not in STATE.selected_agents else "✓"
                    yield Static(
                        f"{'[' if i == 0 else ' '}{checked}{']' if i == 0 else ' '} {name}"
                    )
            yield Static("")
            yield Static("[dim]Space: toggle • Enter: continue • Esc: back[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._update_list()

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_list()

    def _update_list(self) -> None:
        for i, child in enumerate(self.query("#agent-list > Static")):
            aid, name, _ = AGENT_OPTIONS[i]
            checked = "✓" if aid in STATE.selected_agents else " "
            prefix = "▸" if i == self.cursor else " "
            cast(Static, child).update(f"{prefix}[{checked}] {name}")
            child.set_class(i == self.cursor, "focused")

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(AGENT_OPTIONS) - 1:
            self.cursor += 1

    async def action_toggle(self, attribute_name: str = "") -> None:
        aid = AGENT_OPTIONS[self.cursor][0]
        if aid in STATE.selected_agents:
            STATE.selected_agents.remove(aid)
        else:
            STATE.selected_agents.append(aid)
        self._update_list()

    def action_continue(self) -> None:
        if STATE.selected_agents:
            self.app.push_screen("persona")

    def action_back(self) -> None:
        self.app.push_screen("detection")


# ── Persona Screen ────────────────────────────────────────────────────

PERSONA_OPTIONS = [
    (PersonaID.DXRK, "Gentleman", "Full SDD ecosystem with orchestrator, skills, MCP"),
    (PersonaID.NEUTRAL, "Neutral", "Basic configuration without orchestration"),
    (PersonaID.CUSTOM, "Custom", "Manual selection of all options"),
]


class PersonaScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="persona-container"):
            yield Static("[bold]Select Persona[/]", id="persona-title")
            with Vertical(id="persona-list"):
                for i, (pid, name, desc) in enumerate(PERSONA_OPTIONS):
                    with Container(classes="persona-card"):
                        yield Static(f"[bold]{name}[/]", classes="persona-name")
                        yield Static(desc, classes="persona-desc")
            yield Static("")
            yield Static("[dim]Enter: select • Esc: back[/]")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1
        self._update_focus()

    def action_cursor_down(self) -> None:
        if self.cursor < len(PERSONA_OPTIONS) - 1:
            self.cursor += 1
        self._update_focus()

    def _update_focus(self) -> None:
        for i, child in enumerate(self.query(".persona-card")):
            child.set_class(i == self.cursor, "focused")

    def action_select(self) -> None:
        STATE.persona = PERSONA_OPTIONS[self.cursor][0]
        self.app.push_screen("preset")

    def action_back(self) -> None:
        self.app.push_screen("agents")


# ── Preset Screen ─────────────────────────────────────────────────────

PRESET_OPTIONS = [
    (
        PresetID.FULL_DXRK,
        "Full Gentleman",
        "Complete ecosystem: all components + agents",
    ),
    (PresetID.ECOSYSTEM_ONLY, "Ecosystem Only", "Components only, no agents"),
    (PresetID.MINIMAL, "Minimal", "Only essential tools"),
    (PresetID.CUSTOM, "Custom", "Manually select every option"),
]


class PresetScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="preset-container"):
            yield Static("[bold]Select Preset[/]", id="preset-title")
            with Vertical(id="preset-list"):
                for i, (pid, name, desc) in enumerate(PRESET_OPTIONS):
                    with Container(classes="preset-card"):
                        yield Static(f"[bold]{name}[/]", classes="preset-name")
                        yield Static(desc, classes="preset-desc")
            yield Static("")
            yield Static("[dim]Enter: select • Esc: back[/]")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1
        self._update_focus()

    def action_cursor_down(self) -> None:
        if self.cursor < len(PRESET_OPTIONS) - 1:
            self.cursor += 1
        self._update_focus()

    def _update_focus(self) -> None:
        for i, child in enumerate(self.query(".preset-card")):
            child.set_class(i == self.cursor, "focused")

    def action_select(self) -> None:
        STATE.preset = PRESET_OPTIONS[self.cursor][0]
        self.app.push_screen("claude_model_picker")

    def action_back(self) -> None:
        self.app.push_screen("persona")


# ── SDD Mode Screen ───────────────────────────────────────────────────

SDD_OPTIONS = [
    (SDDModeID.SINGLE, "Single Agent", "One agent handles all SDD phases"),
    (
        SDDModeID.MULTI,
        "Multi Agent",
        "Dedicated agent per SDD phase (requires model config)",
    ),
]


class SDDModeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]SDD Orchestration Mode[/]", id="sdd-title")
            for i, (mid, name, desc) in enumerate(SDD_OPTIONS):
                with Container(classes=f"option-row {'focused' if i == 0 else ''}"):
                    yield Static(f"[bold]{name}[/]")
                    yield Static(desc)
            yield Static("[dim]Enter: select • Esc: back[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._update_focus()

    def watch_cursor(self, old, new):
        self._update_focus()

    def _update_focus(self) -> None:
        for i, child in enumerate(self.query(".option-row")):
            child.set_class(i == self.cursor, "focused")

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(SDD_OPTIONS) - 1:
            self.cursor += 1

    def action_select(self) -> None:
        STATE.sdd_mode = SDD_OPTIONS[self.cursor][0]
        self.app.push_screen("model_picker")

    def action_back(self) -> None:
        self.app.push_screen("preset")


# ── Strict TDD Screen ─────────────────────────────────────────────────


class StrictTDDScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "toggle_and_continue", "Toggle & Continue"),
        Binding("escape", "skip", "Skip"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Strict TDD Mode[/]")
            yield Static("")
            yield Static("When enabled, all SDD phases enforce test-first development.")
            yield Static("The agent MUST write tests before implementing code.")
            yield Static("")
            yield Static("  [1] Enable Strict TDD (recommended)")
            yield Static("  [2] Skip — Standard Mode")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1

    def action_toggle_and_continue(self) -> None:
        STATE.strict_tdd = self.cursor == 0
        self.app.push_screen("dependency_tree")

    def action_skip(self) -> None:
        STATE.strict_tdd = False
        self.app.push_screen("preset")


# ── Complete Screen ───────────────────────────────────────────────────


class CompleteScreen(Screen):
    BINDINGS = [
        Binding("enter", "finish", "Finish"),
        Binding("escape", "finish", "Finish"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="complete-container"):
            yield Static("[bold green]✓ Installation Complete[/]", id="complete-title")
            yield Static("")
            yield Static(f"Agents configured: {len(STATE.selected_agents) or 'N/A'}")
            yield Static(
                f"Components installed: {len(STATE.selected_components) or 'N/A'}"
            )
            yield Static("")
            yield Static("[dim]Press Enter to return to the main menu[/]")
        yield Footer()

    def action_finish(self) -> None:
        self.app.push_screen("welcome")


# ── Uninstall Mode Screen ─────────────────────────────────────────────


class UninstallModeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Uninstall Mode[/]")
            yield Static("")
            modes = [
                "Partial — select what to remove",
                "Full — remove all agents and components",
                "Full Remove — full uninstall including config files",
                "Clean Install — full uninstall then reinstall",
            ]
            for i, m in enumerate(modes):
                yield Static(f"  {'▸' if i == 0 else ' '} [{i + 1}] {m}")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 3:
            self.cursor += 1

    def action_select(self) -> None:
        modes = [
            UninstallMode.PARTIAL,
            UninstallMode.FULL,
            UninstallMode.FULL_REMOVE,
            UninstallMode.CLEAN_INSTALL,
        ]
        STATE.uninstall_mode = modes[self.cursor]
        self.app.push_screen("uninstall")

    def action_back(self) -> None:
        self.app.push_screen("welcome")


# ── Backup Screen ─────────────────────────────────────────────────────


class BackupsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "back", "Back"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Backups[/]")
            yield Static("")
            yield Static("[dim]No backups found.[/]")
            yield Static("")
            yield Static("[dim]Back[/]")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 0:
            self.cursor += 1

    def action_select(self) -> None:
        self.app.push_screen("welcome")

    def action_back(self) -> None:
        self.app.push_screen("welcome")


# ── Model Picker Screen ───────────────────────────────────────────────

SDD_PHASES = [
    "sdd-orchestrator",
    "sdd-init",
    "sdd-explore",
    "sdd-propose",
    "sdd-spec",
    "sdd-design",
    "sdd-tasks",
    "sdd-apply",
    "sdd-verify",
    "sdd-archive",
]

MODEL_OPTIONS = [
    "claude-sonnet-4-20250514",
    "claude-3-5-sonnet-20241022",
    "claude-3-opus-20240229",
    "claude-3-haiku-20240307",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gpt-4o",
    "gpt-4o-mini",
]


class ModelPickerScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "edit", "Edit"),
        Binding("escape", "done", "Done"),
    ]

    cursor = reactive(0)
    editing = reactive(False)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Model Assignments[/]")
            yield Static("[dim]Configure which model each SDD phase uses[/]")
            yield Static("")
            for i, phase in enumerate(SDD_PHASES):
                assignment = STATE.model_assignments.get(phase)
                model_str = (
                    f"{assignment.provider_id}/{assignment.model_id}"
                    if assignment
                    else "[dim]not set[/]"
                )
                yield Static(f"  {'▸' if i == 0 else ' '} {phase}: {model_str}")
            yield Static("")
            yield Static("[dim]Enter: edit • Esc: done[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._render_list()

    def _render_list(self) -> None:
        pass

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(SDD_PHASES):
            self.cursor += 1

    def action_edit(self) -> None:
        if self.cursor < len(SDD_PHASES):
            phase = SDD_PHASES[self.cursor]
            self.app.push_screen(ModelSelectScreen(phase))

    def action_done(self) -> None:
        self.app.push_screen("dependency_tree")


# ── Model Select (sub-screen for picking a model) ─────────────────────


class ModelSelectScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Up", show=False),
        Binding("down,j", "cursor_down", "Down", show=False),
        Binding("enter", "select", "Select"),
        Binding("escape", "cancel", "Cancel"),
    ]

    cursor = reactive(0)
    phase: str = ""

    def __init__(self, phase: str = ""):
        super().__init__()
        self.phase = phase

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[bold]Select model for {self.phase}[/]")
            yield Static("")
            with VerticalScroll():
                for i, m in enumerate(MODEL_OPTIONS):
                    yield Static(f"  {'▸' if i == 0 else ' '} {m}")
            yield Static("")
            yield Static("[dim]Enter: select • Esc: cancel[/]")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < len(MODEL_OPTIONS) - 1:
            self.cursor += 1

    def action_select(self) -> None:
        provider = "anthropic"
        model = MODEL_OPTIONS[self.cursor]
        STATE.model_assignments[self.phase] = ModelAssignment(
            provider_id=provider, model_id=model
        )
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


# ── Main App ──────────────────────────────────────────────────────────


class DxrkApp(App):
    """Dxrk Textual TUI."""

    TITLE = "Dxrk"
    SUB_TITLE = f"v{STATE.version}"
    CSS = """
    Screen {
        background: $surface;
    }

    #welcome-container, #detection-container, #agents-container,
    #persona-container, #preset-container, #installing-container,
    #complete-container {
        padding: 1 2;
    }

    #title {
        text-style: bold;
        color: $accent;
        content-align: center top;
        padding: 1;
    }

    #version {
        color: $text-disabled;
        content-align: center top;
    }

    .menu-item {
        padding: 0 1;
        margin: 0 2;
    }

    .menu-item.focused {
        background: $accent 20%;
        border: tall $accent;
    }

    .item-title {
        text-style: bold;
    }

    .item-desc {
        color: $text-disabled;
    }

    .option-row {
        padding: 0 1;
        margin: 0 2;
    }

    .option-row.focused {
        background: $accent 20%;
        border: tall $accent;
    }

    .persona-card, .preset-card {
        padding: 0 1;
        margin: 0 2;
        border: solid $border;
    }

    .persona-card.focused, .preset-card.focused {
        background: $accent 20%;
        border: tall $accent;
    }

    .persona-name, .preset-name {
        text-style: bold;
    }

    .persona-desc, .preset-desc {
        color: $text-disabled;
    }

    #install-progress {
        margin: 1 2;
    }

    #install-log {
        border: solid $border;
        margin: 1 2;
        height: 12;
    }

    #detection-results {
        margin: 0 2;
    }

    #agent-list {
        margin: 0 2;
    }

    #agent-list > Static {
        padding: 0 1;
    }

    #agent-list > Static.focused {
        background: $accent 20%;
    }

    Footer {
        background: $panel;
        color: $text;
    }

    Button {
        margin: 1 2;
    }

    #detection-spinner {
        margin: 1 2;
    }

    #detection-status {
        color: $text-disabled;
        margin: 0 2;
    }
    """

    SCREENS = {
        "welcome": WelcomeScreen,
        "detection": DetectionScreen,
        "agents": AgentsScreen,
        "persona": PersonaScreen,
        "preset": PresetScreen,
        "sdd_mode": SDDModeScreen,
        "strict_tdd": StrictTDDScreen,
        "model_picker": ModelPickerScreen,
        "model_select": ModelSelectScreen,
        "installing": InstallingScreen,
        "complete": CompleteScreen,
        "backups": BackupsScreen,
        "uninstall_mode": UninstallModeScreen,
        "review": ReviewScreen,
        "dependency_tree": DependencyTreeScreen,
        "restore_confirm": RestoreConfirmScreen,
        "delete_confirm": DeleteConfirmScreen,
        "rename_backup": RenameBackupScreen,
        # Placeholders for missing screens
        "upgrade": PlaceholderScreen,
        "sync": PlaceholderScreen,
        "upgrade_sync": PlaceholderScreen,
        "model_config": PlaceholderScreen,
        "profiles": PlaceholderScreen,
        "agent_builder_engine": PlaceholderScreen,
        "opencode_plugins": PlaceholderScreen,
        "restore_result": PlaceholderScreen,
        "delete_result": PlaceholderScreen,
        "uninstall": PlaceholderScreen,
        "claude_model_picker": PlaceholderScreen,
        "kiro_model_picker": PlaceholderScreen,
        "skill_picker": PlaceholderScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("welcome")


def run(version: str = "dev") -> None:
    STATE.version = version
    app = DxrkApp()
    app.run()
