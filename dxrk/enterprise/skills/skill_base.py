"""Base Skill - Clase base para todas las habilidades."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class BaseSkill:
    SKILL_NAME = "base_skill"
    SKILL_DESCRIPTION = "Base skill"
    SKILL_CATEGORY = "general"
    KEYWORDS: list[str] = []

    def __init__(self):
        self.is_active = True
        self.usage_count = 0
        self.success_count = 0
        self.last_used = None

    def execute(self, task_description: str, context: dict | None = None) -> dict:
        self.usage_count += 1
        self.last_used = datetime.now(UTC).isoformat()
        try:
            result = self._perform_task(task_description, context or {})
            self.success_count += 1
            return {"success": True, "skill": self.SKILL_NAME, "result": result}
        except Exception as e:
            return {"success": False, "skill": self.SKILL_NAME, "error": str(e)}

    def _perform_task(self, task: str, context: dict) -> Any:
        return {"message": f"Skill '{self.SKILL_NAME}' processed: {task[:100]}"}

    def can_handle(self, task_description: str) -> bool:
        task_lower = task_description.lower()
        return any(kw in task_lower for kw in self.KEYWORDS)

    @property
    def name(self):
        return self.SKILL_NAME

    def get_stats(self) -> dict:
        return {
            "name": self.SKILL_NAME,
            "usage_count": self.usage_count,
            "success_rate": self.success_count / self.usage_count if self.usage_count > 0 else 0,
        }
