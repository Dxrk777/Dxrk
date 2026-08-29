# SPDX-License-Identifier: MIT
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, TypedDict

from dxrk.models import (
    AgentID,
    ComponentID,
    ModelAssignment,
    PersonaID,
    Plan,
    PresetID,
    Profile,
    SDDModeID,
    SkillID,
    UninstallMode,
)
from dxrk.system import DetectionResult


class SelectedBackupDict(TypedDict, total=False):
    """Typed backup dict as used by TUI backup screens.

    Mirrors the dict structure produced by backup.Manifest / CLI helpers
    but kept as TypedDict for static checking. Extra keys are allowed via
    total=False + dict[str, Any] fallback in TUIContext.
    """

    id: str
    display_label: str
    description: str
    created_by_version: str
    pinned: bool
    source: str
    file_count: int
    created_at: str
    root_dir: str
    checksum: str
    compressed: bool


@dataclass
class TUIContext:
    """DI-friendly TUI state — replaces global mutable AppState.

    Uses ContextVar for isolation (pytest-xdist, asyncio tasks).
    All mutable fields use default_factory to avoid shared-state leaks.
    """

    version: str = "dev"
    detection: DetectionResult | None = None
    selected_agents: list[AgentID] = field(default_factory=list)
    selected_components: list[ComponentID] = field(default_factory=list)
    selected_skills: list[SkillID] = field(default_factory=list)
    persona: PersonaID = PersonaID.DXRK
    preset: PresetID = PresetID.FULL_DXRK
    sdd_mode: SDDModeID = SDDModeID.SINGLE
    strict_tdd: bool = False
    model_assignments: dict[str, ModelAssignment] = field(default_factory=dict)
    profiles: list[Profile] = field(default_factory=list)
    backups: list[dict[str, Any]] = field(default_factory=list)
    plan: Plan | None = None
    uninstall_mode: UninstallMode | None = None
    selected_backup: dict[str, Any] | None = None
    # Alternative typed alias (keep dict for compat):
    # selected_backup: SelectedBackupDict | None = None
    # R10 tenant-aware + R12 RBAC + R15 TUI switcher
    tenant_id: str = ""
    tenant_path: str = ""
    role: str = "readonly"


ctx_var: ContextVar[TUIContext] = ContextVar("tui_ctx", default=TUIContext())


def get_ctx() -> TUIContext:
    """Return current ContextVar TUIContext (default if not set)."""
    return ctx_var.get()


def set_ctx(ctx: TUIContext) -> None:
    """Set current ContextVar TUIContext."""
    ctx_var.set(ctx)
