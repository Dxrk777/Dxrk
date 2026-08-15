# SPDX-License-Identifier: MIT
from dxrk.models import (
    AgentID,
    ComponentID,
    ModelAssignment,
    PersonaID,
    Plan,
    PresetID,
    SDDModeID,
    UninstallMode,
)
from dxrk.system import DetectionResult


class AppState:
    def __init__(self):
        self.version: str = "dev"
        self.detection: DetectionResult | None = None
        self.selected_agents: list[AgentID] = []
        self.selected_components: list[ComponentID] = []
        self.selected_skills: list = []
        self.persona: PersonaID = PersonaID.DXRK
        self.preset: PresetID = PresetID.FULL_DXRK
        self.sdd_mode: SDDModeID = SDDModeID.SINGLE
        self.strict_tdd: bool = False
        self.model_assignments: dict[str, ModelAssignment] = {}
        self.profiles: list = []
        self.backups: list = []
        self.plan: Plan | None = None
        self.uninstall_mode: UninstallMode | None = None
        self.selected_backup: dict | None = None


STATE = AppState()


SCREEN_FLOW: dict[str, dict[str, str | None]] = {
    "welcome": {"forward": "detection", "backward": None},
    "detection": {"forward": "agents", "backward": "welcome"},
    "agents": {"forward": "persona", "backward": "detection"},
    "persona": {"forward": "preset", "backward": "agents"},
    "preset": {"forward": "claude_model_picker", "backward": "persona"},
    "claude_model_picker": {"forward": "kiro_model_picker", "backward": "preset"},
    "kiro_model_picker": {"forward": "sdd_mode", "backward": "claude_model_picker"},
    "sdd_mode": {"forward": "strict_tdd", "backward": "preset"},
    "strict_tdd": {"forward": "dependency_tree", "backward": "sdd_mode"},
    "model_picker": {"forward": "dependency_tree", "backward": "sdd_mode"},
    "model_select": {"forward": "model_picker", "backward": "model_picker"},
    "dependency_tree": {"forward": "review", "backward": "preset"},
    "skill_picker": {"forward": "review", "backward": "dependency_tree"},
    "review": {"forward": "installing", "backward": "dependency_tree"},
    "installing": {"forward": "complete", "backward": "review"},
    "complete": {"forward": None, "backward": "welcome"},
    "backups": {"forward": None, "backward": "welcome"},
    "upgrade": {"forward": None, "backward": "welcome"},
    "sync": {"forward": None, "backward": "welcome"},
    "upgrade_sync": {"forward": None, "backward": "welcome"},
    "model_config": {"forward": None, "backward": "welcome"},
    "profiles": {"forward": None, "backward": "welcome"},
    "uninstall_mode": {"forward": None, "backward": "welcome"},
    "restore_confirm": {"forward": None, "backward": "backups"},
    "restore_result": {"forward": None, "backward": "backups"},
    "delete_confirm": {"forward": None, "backward": "backups"},
    "delete_result": {"forward": None, "backward": "backups"},
    "rename_backup": {"forward": None, "backward": "backups"},
    "agent_builder_engine": {"forward": None, "backward": "welcome"},
    "opencode_plugins": {"forward": None, "backward": "welcome"},
    "uninstall": {"forward": None, "backward": "uninstall_mode"},
}

NEXT = {k: v["forward"] for k, v in SCREEN_FLOW.items()}
PREV = {k: v["backward"] for k, v in SCREEN_FLOW.items()}


def go_next(current: str) -> str | None:
    n = NEXT.get(current)
    if n is not None:
        return n
    return None


def go_back(current: str) -> str | None:
    return PREV.get(current)
