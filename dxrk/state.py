# SPDX-License-Identifier: MIT
"""Install state persistence"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATE_DIR = ".dxrk"
STATE_FILE = "state.json"


@dataclass
class ModelAssignmentState:
    provider_id: str = ""
    model_id: str = ""


@dataclass
class InstallState:
    installed_agents: list[str] = field(default_factory=list)
    claude_model_assignments: dict[str, str] | None = None
    kiro_model_assignments: dict[str, str] | None = None
    model_assignments: dict[str, ModelAssignmentState] | None = None


def state_path(home_dir: str | Path) -> Path:
    return Path(home_dir) / STATE_DIR / STATE_FILE


def read(home_dir: str | Path) -> InstallState:
    p = state_path(home_dir)
    data = p.read_text()
    raw = json.loads(data)
    mas = raw.get("model_assignments")
    if mas:
        raw["model_assignments"] = {
            k: ModelAssignmentState(**v) for k, v in mas.items()
        }
    return InstallState(**raw)


def write(home_dir: str | Path, s: InstallState) -> None:
    p = state_path(home_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = asdict(s)
    p.write_text(json.dumps(raw, indent=2, default=str) + "\n")
