"""
Dxrk Enterprise - Orquestador principal de la empresa de IA.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .departments import (
    DesignersDepartment,
    DevelopersDepartment,
    FinanceDepartment,
    LegalDepartment,
    MarketingDepartment,
    SmallBusinessDepartment,
    SocialMediaDepartment,
)
from .orchestrator import TaskOrchestrator
from .skills.registry import SkillRegistry
from .workforce import AIWorkforce


class DxrkEnterprise:
    """La Empresa de IA completa: 7 departamentos, 79 skills, 0 empleados."""

    DEPARTMENTS_CONFIG = {
        "developers": {"name": "Desarrolladores", "skills_count": 12},
        "designers": {"name": "Diseñadores", "skills_count": 6},
        "marketing": {"name": "Marketing", "skills_count": 15},
        "social_media": {"name": "Redes Sociales", "skills_count": 17},
        "finance": {"name": "Finanzas", "skills_count": 8},
        "small_business": {"name": "Pequeñas Empresas", "skills_count": 12},
        "legal": {"name": "Legal", "skills_count": 9},
    }

    def __init__(self, config_path: str = "~/.dxrk/enterprise"):
        self.config_path = Path(config_path).expanduser()
        self.config_path.mkdir(parents=True, exist_ok=True)
        self.departments: dict[str, Any] = {}
        self.skill_registry = SkillRegistry()
        self.orchestrator = TaskOrchestrator()
        self.workforce = AIWorkforce()
        self.is_operational = False
        self._initialize_departments()

    def _initialize_departments(self):
        self.departments = {
            "developers": DevelopersDepartment(self.skill_registry),
            "designers": DesignersDepartment(self.skill_registry),
            "marketing": MarketingDepartment(self.skill_registry),
            "social_media": SocialMediaDepartment(self.skill_registry),
            "finance": FinanceDepartment(self.skill_registry),
            "small_business": SmallBusinessDepartment(self.skill_registry),
            "legal": LegalDepartment(self.skill_registry),
        }

    def start_company(self):
        self.is_operational = True
        for dept in self.departments.values():
            dept.activate()
        self._save_company_state()

    def stop_company(self):
        self.is_operational = False
        for dept in self.departments.values():
            dept.deactivate()
        self._save_company_state()

    def execute_task(self, task_description: str, department: str | None = None) -> dict:
        if not self.is_operational:
            return {"error": "Company not operational. Call start_company() first."}
        if department is None:
            department = self.orchestrator.route_task(task_description)
        dept = self.departments.get(department)
        if dept is None:
            return {"error": f"Department '{department}' not found."}
        result: dict = dept.execute_task(task_description)
        self.orchestrator.record_completed_task(task_description, department, result)
        return result

    def get_company_status(self) -> dict:
        status: dict = {
            "is_operational": self.is_operational,
            "departments": {k: v.get_status() for k, v in self.departments.items()},
            "total_skills": self.skill_registry.get_total_skills(),
            "tasks_completed": self.orchestrator.get_completed_tasks_count(),
        }
        return status

    def install_skill(self, department: str, skill_name: str) -> dict:
        dept = self.departments.get(department)
        if dept is None:
            return {"error": f"Department '{department}' not found."}
        installed: dict = dept.install_skill(skill_name)
        return installed

    def list_all_skills(self) -> dict:
        return {k: v.list_skills() for k, v in self.departments.items()}

    def _save_company_state(self):
        state = {
            "is_operational": self.is_operational,
            "saved_at": datetime.now(UTC).isoformat(),
        }
        (self.config_path / "company_state.json").write_text(json.dumps(state, indent=2))

    def generate_company_report(self) -> str:
        status = self.get_company_status()
        report = f"\n{'=' * 60}\n  DXRK ENTERPRISE - COMPANY REPORT\n{'=' * 60}\n"
        report += f"  Status: {'OPERATIONAL' if status['is_operational'] else 'STOPPED'}\n"
        report += f"  Total Skills: {status['total_skills']}\n"
        report += f"  Tasks Completed: {status['tasks_completed']}\n"
        report += "\n  DEPARTMENTS:\n"
        for dept_id, dept_status in status["departments"].items():
            report += f"  - {dept_status['name']}: {dept_status['skills_count']} skills\n"
        report += f"{'=' * 60}\n"
        return report
