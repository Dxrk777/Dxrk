# SPDX-License-Identifier: MIT
"""
Textual TUI app for Dxrk.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.theme import Theme
from textual.widgets import (
    Button,
    Footer,
    Label,
    LoadingIndicator,
    Static,
)

from dxrk import __version__
from dxrk.models import (
    AgentID,
    ModelAssignment,
    PersonaID,
    PresetID,
    SDDModeID,
    UninstallMode,
)
from dxrk.system import detect
from dxrk.tui.context import TUIContext, ctx_var, get_ctx
from dxrk.tui.screens.backups import (
    DeleteConfirmScreen,
    RenameBackupScreen,
    RestoreConfirmScreen,
)
from dxrk.tui.screens.chat import ChatScreen
from dxrk.tui.screens.dependency_tree import DependencyTreeScreen
from dxrk.tui.screens.installing import InstallingScreen
from dxrk.tui.screens.providers import ProvidersScreen
from dxrk.tui.screens.review import ReviewScreen
from dxrk.tui.screens.tenant_switcher import TenantSwitcherScreen

log = logging.getLogger(__name__)


DXRK_GOTHIC = Theme(
    name="dxrk-gothic",
    primary="#9d0208",  # sangre
    secondary="#5a189a",  # violeta arcano
    warning="#ffaa00",
    error="#ff0033",
    success="#4ade80",
    accent="#ff4d6d",  # rosa neón punk
    foreground="#e8e0d0",  # hueso
    background="#0c0612",  # negro violáceo
    surface="#150b1e",
    panel="#1a0e26",
    boost="#2a1740",
    dark=True,
)


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
    ("Instalación exprés", "Instala todo de una vez (Dxrk completo)"),
    ("Instalar / Configurar", "Configura agentes, componentes y herramientas"),
    ("Actualizar", "Actualiza los componentes instalados"),
    ("Sincronizar", "Sincroniza la configuración al disco"),
    ("Actualizar + Sincronizar", "Actualiza y sincroniza en un paso"),
    ("Configurar modelos", "Asigna modelos a las fases de SDD"),
    ("Crea tu propio agente", "Crea un agente personalizado con IA"),
    ("Plugins de OpenCode", "Gestiona los plugins comunitarios de OpenCode"),
]

if False:  # conditionally shown
    WELCOME_OPTIONS.append(("Perfiles", "Gestiona los perfiles del orquestador SDD"))

WELCOME_OPTIONS.extend(
    [
        ("Copias de seguridad", "Gestiona las copias de seguridad de la instalación"),
        ("Desinstalar", "Elimina agentes y componentes"),
        ("Salir", "Salir de Dxrk"),
    ]
)


class WelcomeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás", show=False),
        Binding("q", "quit", "Salir"),
        Binding("t", "tenant_switcher", "Tenants"),
        Binding("c", "chat", "Chat"),
        Binding("p", "providers", "IAs"),
    ]

    cursor = reactive(0)

    def _tenant_badge(self) -> str:
        ctx = get_ctx()
        tid = getattr(ctx, "tenant_id", "") or "default"
        role = getattr(ctx, "role", "") or "readonly"
        return f"tenant: {tid} · role: {role}"

    def compose(self) -> ComposeResult:
        with Container(id="welcome-container"):
            yield Static("[bold cyan]Dxrk[/] Instalador", id="title")
            # Migrated to ContextVar DI: prefer get_ctx() over STATE
            yield Static(f"v{get_ctx().version}", id="version")
            yield Static(self._tenant_badge(), id="tenant-badge")
            yield Static("[dim]pulsa t para Tenants[/]", id="tenant-hint")
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
            "Instalación exprés": "__express__",
            "Instalar / Configurar": "detection",
            "Actualizar": "upgrade",
            "Sincronizar": "sync",
            "Actualizar + Sincronizar": "upgrade_sync",
            "Configurar modelos": "model_config",
            "Crea tu propio agente": "agent_builder_engine",
            "Plugins de OpenCode": "opencode_plugins",
            "Perfiles": "profiles",
            "Copias de seguridad": "backups",
            "Desinstalar": "uninstall_mode",
            "Salir": "__quit__",
        }
        target = mapping.get(label, "__quit__")
        if target == "__quit__":
            self.app.exit()
        elif target == "__express__":
            self.action_express_install()
        else:
            self.app.push_screen(target)

    def action_express_install(self) -> None:
        """One-shot install: Full Dxrk preset + detected agents, no wizard.

        Reuses the exact CLI one-shot logic (normalize_install_flags with
        empty flags), so TUI Express and `dxrk-py install` behave identically.
        """
        from dxrk.cli.install import InstallFlags, normalize_install_flags

        ctx = get_ctx()
        detection = ctx.detection
        if detection is None:
            from dxrk.system import detect

            detection = detect()
            ctx.detection = detection
        inp = normalize_install_flags(InstallFlags(), detection)
        sel = inp.selection
        ctx.selected_agents = list(sel.agents)
        ctx.selected_components = list(sel.components)
        ctx.selected_skills = list(sel.skills)
        ctx.persona = sel.persona
        ctx.preset = sel.preset
        ctx.sdd_mode = sel.sdd_mode
        ctx.strict_tdd = False
        ctx.model_assignments = {}
        self.app.push_screen("installing")

    def action_back(self) -> None:
        pass

    def action_tenant_switcher(self) -> None:
        self.app.push_screen("tenant_switcher")

    def action_quit(self) -> None:
        self.app.exit()


# ── Placeholder Screen ───────────────────────────────────────────────


class PlaceholderScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Atrás"),
        Binding("q", "quit", "Salir"),
    ]

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[bold]{(self.name or 'screen').replace('_', ' ').title()}[/]")
            yield Static("")
            yield Static("Próximamente")
        yield Footer()

    def action_back(self) -> None:
        self.app.push_screen("welcome")

    def action_quit(self) -> None:
        self.app.exit()


# ── Detection Screen ──────────────────────────────────────────────────


class DetectionScreen(Screen):
    BINDINGS = [
        Binding("enter", "continue", "Continuar"),
        Binding("escape", "back", "Atrás"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="detection-container"):
            yield Static("[bold]Detección del sistema[/]", id="detection-title")
            yield LoadingIndicator(id="detection-spinner")
            yield Static("Detectando el sistema...", id="detection-status")
        yield Footer()

    def on_mount(self) -> None:
        self._run_detection()

    @work(exclusive=True, thread=True)
    async def _run_detection(self) -> None:
        self.query_one("#detection-status", Static).update("Detectando SO, herramientas y dependencias...")
        # DI migration: use get_ctx() (ContextVar) — STATE is deprecated proxy
        get_ctx().detection = detect()
        # Keep STATE sync for backward compat (proxy already forwards, explicit for clarity)
        # STATE.detection = get_ctx().detection
        self.app.call_from_thread(self._show_results)

    def _show_results(self) -> None:
        spinner = self.query_one("#detection-spinner", LoadingIndicator)
        spinner.display = False
        container = self.query_one("#detection-container", Container)

        d = get_ctx().detection
        if not d:
            container.mount(Static("[red]La detección falló[/]"))
            return

        items = VerticalScroll(id="detection-results")
        container.mount(items)
        items.mount(Static(f"SO: [green]{d.system.os}[/] / [green]{d.system.arch}[/]"))
        items.mount(Static(f"Shell: [green]{d.system.shell}[/]"))
        items.mount(Static(f"Gestor de paquetes: [green]{d.system.profile.package_manager}[/]"))
        items.mount(Static(""))
        items.mount(Static("[bold]Herramientas:[/]"))
        for name, status in d.tools.items():
            c = "green" if status.installed else "red"
            v = f"  ({status.path})" if status.installed else ""
            items.mount(Static(f"  [{c}]{'✅' if status.installed else '❌'} {name}{v}[/]"))
        items.mount(Static(""))
        items.mount(Static("[bold]Configuraciones encontradas:[/]"))
        for cfg in d.configs:
            items.mount(Static(f"  📄 {cfg.path}"))
        items.mount(Static(""))
        items.mount(Button("Continuar", variant="primary", id="detection-continue"))
        self.query_one("#detection-status", Static).update("Detección completa. Pulsa Enter o haz clic en Continuar.")

    @on(Button.Pressed, "#detection-continue")
    def on_continue_click(self) -> None:
        self.action_continue()

    def action_continue(self) -> None:
        self.app.push_screen("agents")

    def action_back(self) -> None:
        self.app.push_screen("welcome")


# ── Agent Selection Screen ────────────────────────────────────────────

AGENT_OPTIONS: list[tuple[AgentID, str, str]] = [
    (AgentID.CLAUDE_CODE, "Claude Code", "Agente CLI de Anthropic"),
    (AgentID.OPENCODE, "OpenCode", "Agente de código abierto"),
    (AgentID.KILOCODE, "Kilocode", "Agente ligero"),
    (AgentID.GEMINI_CLI, "Gemini CLI", "Agente de código de Google"),
    (AgentID.CURSOR, "Cursor", "IDE con IA integrada"),
    (AgentID.VSCODE_COPILOT, "VS Code Copilot", "Pareja de programación con IA de GitHub"),
    (AgentID.CODEX, "Codex", "Agente de programación para CLI"),
    (AgentID.ANTIGRAVITY, "Antigravity", "Herramienta de programación agéntica"),
    (AgentID.WINDSURF, "Windsurf", "IDE con IA"),
    (AgentID.KIMI, "Kimi", "Asistente de IA con contexto amplio"),
    (AgentID.QWEN_CODE, "Qwen Code", "Agente de código de Alibaba"),
    (AgentID.KIRO_IDE, "Kiro IDE", "IDE nativo de IA"),
]


class AgentsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("space", "toggle", "Alternar"),
        Binding("enter", "continue", "Continuar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="agents-container"):
            yield Static("[bold]Seleccionar agentes a instalar[/]", id="agents-title")
            with VerticalScroll(id="agent-list"):
                for i, (aid, name, desc) in enumerate(AGENT_OPTIONS):
                    checked = " " if aid not in get_ctx().selected_agents else "✓"
                    yield Static(f"{'[' if i == 0 else ' '}{checked}{']' if i == 0 else ' '} {name}")
            yield Static("")
            yield Static("[dim]Espacio: alternar • Enter: continuar • Esc: atrás[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._update_list()

    def watch_cursor(self, old: int, new: int) -> None:
        self._update_list()

    def _update_list(self) -> None:
        for i, child in enumerate(self.query("#agent-list > Static")):
            aid, name, _ = AGENT_OPTIONS[i]
            checked = "✓" if aid in get_ctx().selected_agents else " "
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
        ctx = get_ctx()
        if aid in ctx.selected_agents:
            ctx.selected_agents.remove(aid)
        else:
            ctx.selected_agents.append(aid)
        self._update_list()

    def action_continue(self) -> None:
        if get_ctx().selected_agents:
            self.app.push_screen("persona")

    def action_back(self) -> None:
        self.app.push_screen("detection")


# ── Persona Screen ────────────────────────────────────────────────────

PERSONA_OPTIONS = [
    (PersonaID.DXRK, "Dxrk", "Ecosistema SDD completo con orquestador, habilidades y MCP"),
    (PersonaID.NEUTRAL, "Neutra", "Configuración básica sin orquestación"),
    (PersonaID.CUSTOM, "Personalizada", "Selección manual de todas las opciones"),
]


class PersonaScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="persona-container"):
            yield Static("[bold]Seleccionar persona[/]", id="persona-title")
            with Vertical(id="persona-list"):
                for i, (pid, name, desc) in enumerate(PERSONA_OPTIONS):
                    with Container(classes="persona-card"):
                        yield Static(f"[bold]{name}[/]", classes="persona-name")
                        yield Static(desc, classes="persona-desc")
            yield Static("")
            yield Static("[dim]Enter: seleccionar • Esc: atrás[/]")
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
        # Migrated to DI
        get_ctx().persona = PERSONA_OPTIONS[self.cursor][0]
        self.app.push_screen("preset")

    def action_back(self) -> None:
        self.app.push_screen("agents")


# ── Preset Screen ─────────────────────────────────────────────────────

PRESET_OPTIONS = [
    (
        PresetID.FULL_DXRK,
        "Dxrk completo",
        "Ecosistema completo: todos los componentes + agentes",
    ),
    (PresetID.ECOSYSTEM_ONLY, "Solo ecosistema", "Solo componentes, sin agentes"),
    (PresetID.MINIMAL, "Mínimo", "Solo herramientas esenciales"),
    (PresetID.CUSTOM, "Personalizado", "Selecciona cada opción manualmente"),
]


class PresetScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container(id="preset-container"):
            yield Static("[bold]Seleccionar preset[/]", id="preset-title")
            with Vertical(id="preset-list"):
                for i, (pid, name, desc) in enumerate(PRESET_OPTIONS):
                    with Container(classes="preset-card"):
                        yield Static(f"[bold]{name}[/]", classes="preset-name")
                        yield Static(desc, classes="preset-desc")
            yield Static("")
            yield Static("[dim]Enter: seleccionar • Esc: atrás[/]")
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
        get_ctx().preset = PRESET_OPTIONS[self.cursor][0]
        self.app.push_screen("claude_model_picker")

    def action_back(self) -> None:
        self.app.push_screen("persona")


# ── SDD Mode Screen ───────────────────────────────────────────────────

SDD_OPTIONS = [
    (SDDModeID.SINGLE, "Agente único", "Un agente gestiona todas las fases de SDD"),
    (
        SDDModeID.MULTI,
        "Multiagente",
        "Un agente dedicado por fase de SDD (requiere configuración de modelos)",
    ),
]


class SDDModeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Modo de orquestación SDD[/]", id="sdd-title")
            for i, (mid, name, desc) in enumerate(SDD_OPTIONS):
                with Container(classes=f"option-row {'focused' if i == 0 else ''}"):
                    yield Static(f"[bold]{name}[/]")
                    yield Static(desc)
            yield Static("[dim]Enter: seleccionar • Esc: atrás[/]")
        yield Footer()

    def on_mount(self) -> None:
        self._update_focus()

    def watch_cursor(self, old: Any, new: Any) -> None:
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
        get_ctx().sdd_mode = SDD_OPTIONS[self.cursor][0]
        self.app.push_screen("model_picker")

    def action_back(self) -> None:
        self.app.push_screen("preset")


# ── Strict TDD Screen ─────────────────────────────────────────────────


class StrictTDDScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "toggle_and_continue", "Alternar y continuar"),
        Binding("escape", "skip", "Omitir"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Modo TDD estricto[/]")
            yield Static("")
            yield Static("Cuando está activado, todas las fases de SDD exigen programar las pruebas primero.")
            yield Static("El agente DEBE escribir las pruebas antes de implementar el código.")
            yield Static("")
            yield Static("  [1] Activar TDD estricto (recomendado)")
            yield Static("  [2] Omitir — Modo estándar")
        yield Footer()

    def action_cursor_up(self) -> None:
        if self.cursor > 0:
            self.cursor -= 1

    def action_cursor_down(self) -> None:
        if self.cursor < 1:
            self.cursor += 1

    def action_toggle_and_continue(self) -> None:
        get_ctx().strict_tdd = self.cursor == 0
        self.app.push_screen("dependency_tree")

    def action_skip(self) -> None:
        get_ctx().strict_tdd = False
        self.app.push_screen("preset")


# ── Complete Screen ───────────────────────────────────────────────────


class CompleteScreen(Screen):
    BINDINGS = [
        Binding("enter", "finish", "Finalizar"),
        Binding("escape", "finish", "Finalizar"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="complete-container"):
            yield Static("[bold green]✓ Instalación completa[/]", id="complete-title")
            yield Static("")
            yield Static(f"Agentes configurados: {len(get_ctx().selected_agents) or 'N/A'}")
            yield Static(f"Componentes instalados: {len(get_ctx().selected_components) or 'N/A'}")
            yield Static("")
            yield Static("[dim]Pulsa Enter para volver al menú principal[/]")
        yield Footer()

    def action_finish(self) -> None:
        self.app.push_screen("welcome")


# ── Uninstall Mode Screen ─────────────────────────────────────────────


class UninstallModeScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Modo de desinstalación[/]")
            yield Static("")
            modes = [
                "Parcial — selecciona qué eliminar",
                "Completa — elimina todos los agentes y componentes",
                "Eliminación total — desinstalación completa incluyendo archivos de configuración",
                "Instalación limpia — desinstalación completa y reinstalación",
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
        get_ctx().uninstall_mode = modes[self.cursor]
        self.app.push_screen("uninstall")

    def action_back(self) -> None:
        self.app.push_screen("welcome")


# ── Backup Screen ─────────────────────────────────────────────────────


class BackupsScreen(Screen):
    BINDINGS = [
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "back", "Atrás"),
    ]

    cursor = reactive(0)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Copias de seguridad[/]")
            yield Static("")
            yield Static("[dim]No se encontraron copias de seguridad.[/]")
            yield Static("")
            yield Static("[dim]Atrás[/]")
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
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "edit", "Editar"),
        Binding("escape", "done", "Listo"),
    ]

    cursor = reactive(0)
    editing = reactive(False)

    def compose(self) -> ComposeResult:
        with Container():
            yield Static("[bold]Asignación de modelos[/]")
            yield Static("[dim]Configura qué modelo usa cada fase de SDD[/]")
            yield Static("")
            for i, phase in enumerate(SDD_PHASES):
                assignment = get_ctx().model_assignments.get(phase)
                model_str = f"{assignment.provider_id}/{assignment.model_id}" if assignment else "[dim]sin asignar[/]"
                yield Static(f"  {'▸' if i == 0 else ' '} {phase}: {model_str}")
            yield Static("")
            yield Static("[dim]Enter: editar • Esc: listo[/]")
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
        Binding("up,k", "cursor_up", "Arriba", show=False),
        Binding("down,j", "cursor_down", "Abajo", show=False),
        Binding("enter", "select", "Seleccionar"),
        Binding("escape", "cancel", "Cancelar"),
    ]

    cursor = reactive(0)
    phase: str = ""

    def __init__(self, phase: str = ""):
        super().__init__()
        self.phase = phase

    def compose(self) -> ComposeResult:
        with Container():
            yield Static(f"[bold]Seleccionar modelo para {self.phase}[/]")
            yield Static("")
            with VerticalScroll():
                for i, m in enumerate(MODEL_OPTIONS):
                    yield Static(f"  {'▸' if i == 0 else ' '} {m}")
            yield Static("")
            yield Static("[dim]Enter: seleccionar • Esc: cancelar[/]")
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
        get_ctx().model_assignments[self.phase] = ModelAssignment(provider_id=provider, model_id=model)
        self.dismiss()

    def action_cancel(self) -> None:
        self.dismiss()


# ── Main App ──────────────────────────────────────────────────────────


class DxrkApp(App):
    """Dxrk Textual TUI — now ContextVar DI aware.

    Preferred usage: DxrkApp(ctx=TUIContext(version=...)).
    Legacy global STATE is kept as proxy for backward compat.
    """

    TITLE = "Dxrk"
    SUB_TITLE = f"v{__version__}"
    BINDINGS = [
        Binding("t", "tenant_switcher", "Tenants"),
    ]
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
        "tenant_switcher": TenantSwitcherScreen,
        "chat": ChatScreen,
        "providers": ProvidersScreen,
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

    def __init__(self, ctx: TUIContext | None = None, initial_screen: str = "welcome", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.initial_screen = initial_screen
        if ctx is not None:
            self.ctx: TUIContext = ctx
            ctx_var.set(self.ctx)
        else:
            # Reuse current ContextVar value (xdist-safe via ContextVar)
            self.ctx = get_ctx()
        # Sync legacy STATE proxy is automatic (STATE forwards to ctx_var),
        # but keep instance sub-title in sync for display.
        self.SUB_TITLE = f"v{self.ctx.version}"
        self.register_theme(DXRK_GOTHIC)
        self.theme = "dxrk-gothic"

    def action_tenant_switcher(self) -> None:
        self.push_screen("tenant_switcher")

    def action_chat(self) -> None:
        self.push_screen("chat")

    def action_providers(self) -> None:
        self.push_screen("providers")

    def on_mount(self) -> None:
        self.push_screen(self.initial_screen)


def run(version: str = __version__, initial_screen: str = "welcome") -> None:
    ctx = TUIContext(version=version)
    ctx_var.set(ctx)
    # Legacy sync: STATE is proxy -> also reflects ctx, explicit for clarity
    # (kept for tests that import STATE)
    app = DxrkApp(ctx, initial_screen=initial_screen)
    app.run()
