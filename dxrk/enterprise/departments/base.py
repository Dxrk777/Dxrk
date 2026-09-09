"""Base Department - Clase base para todos los departamentos."""

from __future__ import annotations

from datetime import UTC, datetime


class BaseDepartment:
    DEPARTMENT_ID = "base"
    DEPARTMENT_NAME = "Base"
    DEPARTMENT_DESCRIPTION = "Base department"
    SKILLS: list[str] = []

    def __init__(self, skill_registry=None):
        self.skill_registry = skill_registry
        self.is_active = False
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.installed_skills = []
        self.task_history = []

    def _registry(self):
        """Retorna el registry; falla explícito si no se configuró."""
        assert self.skill_registry is not None, "skill_registry is required"
        return self.skill_registry

    def activate(self):
        self.is_active = True
        self._auto_install_default_skills()

    def deactivate(self):
        self.is_active = False

    def execute_task(self, task_description: str) -> dict:
        if not self.is_active:
            return {"error": f"{self.DEPARTMENT_NAME} is not active."}
        best_skill = self._find_best_skill(task_description)
        if best_skill is None:
            return {"error": f"No skill found for: {task_description}", "success": False}
        result: dict = best_skill.execute(task_description)
        if result.get("success", False):
            self.tasks_completed += 1
        else:
            self.tasks_failed += 1
        self.task_history.append(
            {
                "task": task_description,
                "skill": best_skill.name,
                "result": result,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        return result

    def install_skill(self, skill_name: str) -> dict:
        skill = self._registry().get_skill(skill_name)
        if skill is None:
            return {"error": f"Skill '{skill_name}' not found."}
        if skill_name not in self.installed_skills:
            self.installed_skills.append(skill_name)
            return {"success": True, "message": f"'{skill_name}' installed."}
        return {"success": False, "message": "Already installed."}

    def list_skills(self) -> list[dict]:
        return [{"name": s, "installed": s in self.installed_skills} for s in self.SKILLS]

    def get_status(self) -> dict:
        total = self.tasks_completed + self.tasks_failed
        return {
            "id": self.DEPARTMENT_ID,
            "name": self.DEPARTMENT_NAME,
            "is_active": self.is_active,
            "skills_count": len(self.SKILLS),
            "installed_skills": len(self.installed_skills),
            "tasks_completed": self.tasks_completed,
            "success_rate": self.tasks_completed / total if total > 0 else 0,
        }

    def _auto_install_default_skills(self):
        for skill_name in self.SKILLS[:5]:
            self.install_skill(skill_name)

    def _find_best_skill(self, task_description: str):
        task_lower = task_description.lower()
        registry = self._registry()
        for skill_name in self.installed_skills:
            skill = registry.get_skill(skill_name)
            if skill and skill.can_handle(task_lower):
                return skill
        for skill_name in self.SKILLS:
            skill = registry.get_skill(skill_name)
            if skill and skill.can_handle(task_lower):
                return skill
        return None
