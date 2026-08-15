import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

STATE_DIR = ".dxrk"
STATE_FILE = "state.json"


@dataclass
class ModelAssignmentState:
    provider_id: str
    model_id: str
    effort: str = ""


@dataclass
class InstallState:
    installed_agents: list[str] = field(default_factory=list)
    claude_model_assignments: dict[str, str] | None = None
    kiro_model_assignments: dict[str, str] | None = None
    model_assignments: dict[str, ModelAssignmentState] | None = None
    persona: str = ""

    def _to_dict(self) -> dict:
        out: dict = {"installed_agents": self.installed_agents}
        if self.claude_model_assignments:
            out["claude_model_assignments"] = self.claude_model_assignments
        if self.kiro_model_assignments:
            out["kiro_model_assignments"] = self.kiro_model_assignments
        if self.model_assignments:
            out["model_assignments"] = {
                k: {"provider_id": v.provider_id, "model_id": v.model_id}
                | ({"effort": v.effort} if v.effort else {})
                for k, v in self.model_assignments.items()
            }
        if self.persona:
            out["persona"] = self.persona
        return out

    @classmethod
    def _from_dict(cls, data: dict) -> "InstallState":
        ma = data.get("model_assignments") or {}
        return cls(
            installed_agents=list(data.get("installed_agents") or []),
            claude_model_assignments=data.get("claude_model_assignments"),
            kiro_model_assignments=data.get("kiro_model_assignments"),
            model_assignments={
                k: ModelAssignmentState(
                    provider_id=v.get("provider_id", ""),
                    model_id=v.get("model_id", ""),
                    effort=v.get("effort", ""),
                )
                for k, v in ma.items()
            }
            if ma
            else None,
            persona=data.get("persona", ""),
        )


def path(home_dir: str) -> str:
    return str(Path(home_dir) / STATE_DIR / STATE_FILE)


state_path = path


def read(home_dir: str) -> InstallState:
    with open(path(home_dir)) as f:
        data = f.read()
    return InstallState._from_dict(json.loads(data))


def write(home_dir: str, s: InstallState) -> None:
    dir_path = Path(home_dir) / STATE_DIR
    os.makedirs(dir_path, mode=0o750, exist_ok=True)
    data = json.dumps(s._to_dict(), indent=2) + "\n"
    fd = os.open(path(home_dir), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(data)
